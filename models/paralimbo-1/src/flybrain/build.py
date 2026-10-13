"""Assemble released FlyWire edges, with explicit modes and sign corrections.

Matrices contain signed SYNAPSE COUNTS.  They have postsynaptic rows and
presynaptic columns; engine gains/units must be applied once at delivery time.
No lamina repairs, retinotopy, or new edges are introduced in this stage.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy import sparse

from .fetch import checksum, stat_signature
from .memguard import check_memory
from .validate_data import validate_data


MISSING_TYPE = "__MISSING__"
VISUAL_CLASSES = {"optic", "visual_projection", "visual_centrifugal"}
PHOTORECEPTORS = {"R1-6", "R7", "R8"}
DEFAULT_SIGN_OVERRIDES = [
    {"pre_type": name, "post_type": "*", "sign": -1,
     "source": "PMID:12196539", "reason": "Photoreceptor histamine chloride-channel correction"}
    for name in sorted(PHOTORECEPTORS)
]


def default_graded(cell_type: str, super_class: str) -> bool:
    """Refined brief rule, restricted to visual classifications.

    Known photoreceptors are sensory cells and explicitly bypass that gate.
    Prefixes describe the named visual families, not arbitrary central types.
    """
    if cell_type in PHOTORECEPTORS:
        return True
    if super_class not in VISUAL_CLASSES or not cell_type or cell_type == MISSING_TYPE:
        return False
    if cell_type in {"C2", "C3", "T1", "T2", "T2a", "T3", "CT1", "Lai"}:
        return True
    if re.fullmatch(r"L[1-5](?:-[1-5])?", cell_type):
        return True
    if cell_type in {f"{family}{subtype}" for family in ("T4", "T5") for subtype in "abcd"}:
        return True
    return cell_type.startswith(("Lawf", "Mi", "Dm", "Pm", "Sm", "Tm", "LPi", "Li", "Y", "HS", "VS"))


def _prepare_modes(neurons: pd.DataFrame, path: Path, mode: str) -> np.ndarray:
    if mode not in {"hybrid", "all_lif"}:
        raise ValueError("mode must be hybrid or all_lif")
    type_keys = neurons.cell_type.fillna(MISSING_TYPE)
    defaults = np.array([default_graded(str(cell_type), str(super_class))
                         for cell_type, super_class in zip(type_keys, neurons.super_class)], dtype=bool)
    existing = pd.read_csv(path, keep_default_na=False) if path.exists() else pd.DataFrame()
    required = {"cell_type", "mode", "source"}
    if not existing.empty:
        if not required.issubset(existing.columns):
            raise ValueError(f"Neuron mode config must include {sorted(required)}")
        if existing.cell_type.duplicated().any():
            raise ValueError("Duplicate cell_type rows in neuron_modes.csv")
        if not existing["mode"].isin(["graded", "spiking"]).all():
            raise ValueError("Neuron modes must be graded or spiking")
        if (existing.source.str.strip() == "").any():
            raise ValueError("Every neuron mode requires a source or ASSUMPTION")
    by_type = existing.set_index("cell_type").to_dict("index") if not existing.empty else {}
    output = []
    final = defaults.copy()
    for cell_type, indices in type_keys.groupby(type_keys, sort=True).groups.items():
        idx = np.asarray(indices, dtype=np.int64)
        default_mode = "graded" if defaults[idx].any() else "spiking"
        row = by_type.get(cell_type, {"mode": default_mode, "source": "ASSUMPTION"})
        configured = row["mode"]
        # Configured changes are explicit per-type overrides. Generated default
        # rows retain per-neuron visual gating when a label crosses classes.
        edited = configured != default_mode
        final[idx] = (configured == "graded") if edited else defaults[idx]
        output.append({"cell_type": cell_type, "mode": configured, "source": row["source"],
                       "n_neurons": len(idx), "default_mode": default_mode,
                       "n_graded_default": int(defaults[idx].sum()),
                       "rule": "explicit per-type override" if edited else "BUILD_BRIEF.md 3.2 refined visual-family rule"})
    unknown = set(by_type) - set(type_keys)
    if unknown:
        raise ValueError(f"Neuron-mode config names unknown cell types: {sorted(unknown)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(output).to_csv(path, index=False)
    return np.zeros(len(neurons), dtype=bool) if mode == "all_lif" else final


def _load_sign_rules(path: Path, known_types: set[str]) -> list[dict]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(DEFAULT_SIGN_OVERRIDES).to_csv(path, index=False)
    table = pd.read_csv(path, keep_default_na=False)
    required = {"pre_type", "post_type", "sign", "source"}
    if not required.issubset(table):
        raise ValueError(f"Sign config must include {sorted(required)}")
    if table[["pre_type", "post_type"]].duplicated().any():
        raise ValueError("Duplicate pre_type/post_type sign override")
    if not table.sign.isin([-1, 1]).all() or (table.source.str.strip() == "").any():
        raise ValueError("Each sign override requires sign +/-1 and a provenance source")
    for field in ("pre_type", "post_type"):
        unknown = set(table[field]) - known_types - {"*"}
        if unknown:
            raise ValueError(f"Unknown {field} in sign overrides: {sorted(unknown)}")
    # The mandatory correction supplies a baseline even if its rows were
    # accidentally removed; explicit pre/post rules may refine that baseline.
    return table.to_dict("records")


def corrected_signs(pre_type_codes: np.ndarray, post_type_codes: np.ndarray,
                    original_signs: np.ndarray, type_names: list[str], rules: list[dict]) -> np.ndarray:
    """Apply histamine baseline, then generic and more specific explicit rules."""
    corrected = original_signs.copy()
    code = {name: i for i, name in enumerate(type_names)}
    photo_codes = [code[name] for name in PHOTORECEPTORS if name in code]
    corrected[np.isin(pre_type_codes, photo_codes)] = -1
    # More specific matches take precedence, stable CSV order breaks ties.
    for rule in sorted(rules, key=lambda row: int(row["pre_type"] != "*") + int(row["post_type"] != "*")):
        mask = np.ones(len(corrected), dtype=bool)
        if rule["pre_type"] != "*":
            mask &= pre_type_codes == code[rule["pre_type"]]
        if rule["post_type"] != "*":
            mask &= post_type_codes == code[rule["post_type"]]
        corrected[mask] = int(rule["sign"])
    return corrected


def make_csr(pre: np.ndarray, post: np.ndarray, values: np.ndarray, n_neurons: int) -> sparse.csr_matrix:
    """W[post, pre]; duplicates add, zero entries are removed, indices are int32."""
    matrix = sparse.coo_matrix((values.astype(np.float32), (post, pre)),
                               shape=(n_neurons, n_neurons), dtype=np.float32).tocsr()
    matrix.sum_duplicates()
    matrix.eliminate_zeros()
    matrix.sort_indices()
    matrix.indices = matrix.indices.astype(np.int32, copy=False)
    matrix.indptr = matrix.indptr.astype(np.int32, copy=False)
    return matrix


def _save_csr(path: Path, matrix: sparse.csr_matrix) -> None:
    temporary = path.with_name(path.stem + ".partial.npz")
    sparse.save_npz(temporary, matrix, compressed=True)
    temporary.replace(path)


def build_network(root: Path, mode: str = "hybrid") -> dict:
    """Verify V-A, assemble the real released graph, and save auditable outputs."""
    root = Path(root).resolve()
    started = time.perf_counter()
    validation = validate_data(root)
    if validation["status"] != "PASS":
        raise ValueError(f"Cannot build: V-A failed: {validation['failed_checks']}")
    raw, output, config = root / "data/raw", root / "build", root / "config"
    output.mkdir(parents=True, exist_ok=True)
    completeness = pd.read_csv(raw / "Completeness_783.csv").rename(columns={"Unnamed: 0": "root_id"})
    annotations = pd.read_csv(raw / "Supplemental_file1_neuron_annotations.tsv", sep="\t", low_memory=False)
    neurons = completeness.merge(annotations, on="root_id", how="left", sort=False, validate="one_to_one")
    neurons.insert(0, "index", np.arange(len(neurons), dtype=np.int32))
    graded = _prepare_modes(neurons, config / "neuron_modes.csv", mode)
    neurons["is_graded"] = graded
    neurons["mode"] = np.where(graded, "graded", "spiking")
    type_names = sorted(neurons.cell_type.fillna(MISSING_TYPE).unique().tolist())
    type_codes = pd.Categorical(neurons.cell_type.fillna(MISSING_TYPE), categories=type_names).codes.astype(np.int32)
    rules = _load_sign_rules(config / "sign_overrides.csv", set(type_names))
    table = pq.ParquetFile(raw / "Connectivity_783.parquet")
    n_edges, n_neurons = table.metadata.num_rows, len(neurons)
    pre = np.empty(n_edges, dtype=np.int32)
    post = np.empty(n_edges, dtype=np.int32)
    raw_values = np.empty(n_edges, dtype=np.float32)
    values = np.empty(n_edges, dtype=np.float32)
    overridden = defaultdict(lambda: [0, 0])
    first_pass_graded = (neurons.super_class.isin(VISUAL_CLASSES) | neurons.cell_type.isin(PHOTORECEPTORS)).to_numpy()
    partitions = {"graded_to_graded": 0, "graded_to_spiking": 0,
                  "spiking_to_graded": 0, "spiking_to_spiking": 0}
    first_pass_partitions = dict(partitions)
    offset = 0
    columns = ["Presynaptic_Index", "Postsynaptic_Index", "Connectivity", "Excitatory"]
    for batch in table.iter_batches(batch_size=262_144, columns=columns):
        check_memory()
        size = batch.num_rows
        sl = slice(offset, offset + size)
        a = batch.column("Presynaptic_Index").to_numpy().astype(np.int32)
        b = batch.column("Postsynaptic_Index").to_numpy().astype(np.int32)
        counts = batch.column("Connectivity").to_numpy()
        original = batch.column("Excitatory").to_numpy().astype(np.int8)
        corrected = corrected_signs(type_codes[a], type_codes[b], original, type_names, rules)
        pre[sl], post[sl] = a, b
        raw_values[sl], values[sl] = original * counts, corrected * counts
        changed = original != corrected
        # Aggregate without turning the complete 15M-edge table into strings.
        if changed.any():
            pairs = type_codes[a[changed]].astype(np.int64) * len(type_names) + type_codes[b[changed]]
            unique_pairs, inverse, edge_counts = np.unique(pairs, return_inverse=True, return_counts=True)
            synapse_counts = np.zeros(len(unique_pairs), dtype=np.int64)
            np.add.at(synapse_counts, inverse, counts[changed])
            for pair, edge_count, synapse_count in zip(unique_pairs, edge_counts, synapse_counts):
                key = (int(pair // len(type_names)), int(pair % len(type_names)))
                overridden[key][0] += int(edge_count)
                overridden[key][1] += int(synapse_count)
        for selection, target in [(graded, partitions), (first_pass_graded, first_pass_partitions)]:
            is_pre, is_post = selection[a], selection[b]
            target["graded_to_graded"] += int(np.count_nonzero(is_pre & is_post))
            target["graded_to_spiking"] += int(np.count_nonzero(is_pre & ~is_post))
            target["spiking_to_graded"] += int(np.count_nonzero(~is_pre & is_post))
            target["spiking_to_spiking"] += int(np.count_nonzero(~is_pre & ~is_post))
        offset += size
    check_memory()
    reference = make_csr(pre, post, raw_values, n_neurons)
    _save_csr(output / "reference_counts.npz", reference)
    reference_nnz = int(reference.nnz)
    del reference, raw_values
    check_memory()
    selection = graded[pre]
    graded_matrix = make_csr(pre[selection], post[selection], values[selection], n_neurons)
    _save_csr(output / "graded_counts.npz", graded_matrix)
    graded_nnz = int(graded_matrix.nnz)
    graded_bytes = graded_matrix.data.nbytes + graded_matrix.indices.nbytes + graded_matrix.indptr.nbytes
    del graded_matrix
    selection = ~selection
    check_memory()
    spiking_matrix = make_csr(pre[selection], post[selection], values[selection], n_neurons)
    _save_csr(output / "spiking_counts.npz", spiking_matrix)
    spiking_nnz = int(spiking_matrix.nnz)
    spiking_bytes = spiking_matrix.data.nbytes + spiking_matrix.indices.nbytes + spiking_matrix.indptr.nbytes
    del spiking_matrix
    neurons.to_parquet(output / "neurons.parquet", index=False)
    override_records = [{"pre_type": type_names[a], "post_type": type_names[b],
                         "n_edges": count[0], "n_synapses": count[1]}
                        for (a, b), count in sorted(overridden.items())]
    pd.DataFrame(override_records, columns=["pre_type", "post_type", "n_edges", "n_synapses"]).to_csv(
        output / "sign_overrides.csv", index=False)
    for name, expected_stat in validation["source_stats"].items():
        if stat_signature(raw / name) != expected_stat:
            raise ValueError(f"Release source changed during assembly: {name}")
    summary = {
        "status": "PASS", "stage": "released_network_assembly", "mode": mode,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n_neurons": n_neurons, "n_edges_released": n_edges,
        "n_graded": int(graded.sum()), "n_spiking": int((~graded).sum()),
        "edge_partition": partitions,
        "first_pass_n_graded": int(first_pass_graded.sum()),
        "first_pass_n_spiking": int((~first_pass_graded).sum()),
        "first_pass_edge_partition": first_pass_partitions,
        "matrix_orientation": "rows=postsynaptic; columns=presynaptic",
        "matrix_units": "signed synapse counts; apply per-mode engine gain exactly once",
        "matrix_dtype": "float32", "matrix_index_dtype": "int32",
        "graded_nnz": graded_nnz, "spiking_nnz": spiking_nnz, "reference_nnz": reference_nnz,
        "csr_hybrid_bytes": int(graded_bytes + spiking_bytes),
        "sign_overridden_edges": sum(x["n_edges"] for x in override_records),
        "sign_overridden_synapses": sum(x["n_synapses"] for x in override_records),
        "synthetic_edges": 0,
        "lamina_mode": "connectome", "cartridge_repair_status": "NOT-RUN (requires stage 5 priors and columns)",
        "source_hashes": validation["source_hashes"],
        "source_stats": validation["source_stats"],
        "config_hashes": {name: checksum(config / name) for name in ("neuron_modes.csv", "sign_overrides.csv")},
        "wall_seconds": time.perf_counter() - started,
    }
    summary["output_hashes"] = {name: checksum(output / name) for name in (
        "neurons.parquet", "graded_counts.npz", "spiking_counts.npz", "reference_counts.npz", "sign_overrides.csv")}
    (output / "build_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return summary


def load_network(root: Path) -> dict:
    """Return neurons, graded/spiking/reference CSR counts, and build summary.

    `neurons.iloc[i]` is neuron i; `neurons.is_graded` defines current modes.
    Every matrix is shape (N,N), float32 with int32 indices. `reference` retains
    original classifier signs and is exclusively for the reference cross-check.
    """
    output = Path(root) / "build"
    summary = json.loads((output / "build_summary.json").read_text())
    if summary["status"] != "PASS":
        raise ValueError("Network build is not PASS")
    for name, expected_stat in summary["source_stats"].items():
        if stat_signature(Path(root) / "data/raw" / name) != expected_stat:
            raise ValueError(f"Release source changed; revalidate and rebuild required: {name}")
    for name, digest in summary["output_hashes"].items():
        if checksum(output / name) != digest:
            raise ValueError(f"Built network file changed since assembly: {name}")
    for name, digest in summary["config_hashes"].items():
        if checksum(Path(root) / "config" / name) != digest:
            raise ValueError(f"Configuration changed; rebuild required: {name}")
    return {
        "neurons": pd.read_parquet(output / "neurons.parquet"),
        "graded": sparse.load_npz(output / "graded_counts.npz").tocsr(),
        "spiking": sparse.load_npz(output / "spiking_counts.npz").tocsr(),
        "reference": sparse.load_npz(output / "reference_counts.npz").tocsr(),
        "summary": summary,
    }
