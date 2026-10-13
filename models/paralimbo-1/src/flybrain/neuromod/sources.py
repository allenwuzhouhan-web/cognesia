"""Stage 1: source integrity, Defect D and exact release census (V-NM-C).

Source membership NEVER reads top_nt. Audits retain every annotation row;
model indices are an explicit, order-preserving projection onto Completeness.
A failed gate leaves diagnostic artifacts, never an approved network matrix.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ..fetch import checksum, stat_signature
from ..inspect_data import atomic_write_json, inspect_table
from ..memguard import check_memory
from ..validate_data import validate_data

RAW_FILES = ("Completeness_783.csv", "Connectivity_783.parquet",
             "Supplemental_file1_neuron_annotations.tsv")
EXPECTED_AUDIT = {
    "acetylcholine": (52053, 86193, 44999), "gaba": (9089, 19171, 7438),
    "glutamate": (11378, 24875, 9139), "dopamine": (1395, 5909, 381),
    "octopamine": (68, 216, 39), "serotonin": (197, 2282, 18),
    "tyramine": (104, 0, 0), "histamine": (11129, 0, 0),
}
PAM_COUNTS = dict(zip(
    [f"PAM{i:02d}" for i in range(1, 16)],
    [41, 16, 10, 32, 21, 30, 18, 45, 9, 15, 16, 23, 12, 16, 3], strict=True))
DAN_COUNTS = {**PAM_COUNTS, **{f"PPL1{i:02d}": 2 for i in range(1, 9)},
              **{f"PPL2{i:02d}": 2 for i in range(1, 5)},
              **{f"PAL{i:02d}": 2 for i in range(1, 4)}}
SPECIES = {"DA": "dopamine", "OA": "octopamine", "5HT": "serotonin",
           "TA": "tyramine", "NO": "nitric oxide", "sNPF": "snpf"}
AMINERGIC = ("DA", "OA", "5HT", "TA")
EXPECTED_BLOCKS = {
    # neurons, left, right, named types, untyped neurons (Patch 1 section 1).
    "ORN": (2279, 1116, 1133, 53, 4), "PN": (685, 341, 344, 182, 0),
    "ALLN": (429, 214, 213, 94, 1), "KC": (5177, 2580, 2597, 11, 0),
    "MBON": (96, 48, 48, 35, 0), "DAN": (337, 169, 168, 30, 0),
    "APL_DPM": (4, 2, 2, 2, 0), "OA_named": (43, 15, 15, 18, 0),
    "CSD": (2, 1, 1, 1, 0), "CX": (2875, 1438, 1437, 229, 9),
    "DN": (1299, 645, 646, 472, 0), "endocrine": (76, 37, 39, 10, 0),
}
EXPECTED_NO_DAN_COUNTS = {"PAM01": 40, "PAM05": 20, "PAM06": 2, "PPL101": 2, "PPL103": 2}
EXPECTED_MOTIFS = {
    "KC->MBON": (62261, 256719, 3), "KC->DAN": (81057, 125134, 1),
    "DAN->KC": (47404, 60657, 1), "KC->APL_DPM": (10390, 204929, 19),
    "APL_DPM->KC": (9251, 107934, 12), "MBON->MBON": (1343, 19983, 3),
    "MBON->DAN": (2383, 9009, 2), "DAN->MBON": (2035, 15325, 3),
    "APL_DPM->MBON": (193, 6910, 11), "PN->KC": (27848, 329394, 11),
    "KC->KC": (293762, 379338, 1),
}
SELECTIONS = {
    "PN": "cell_class == 'ALPN'", "ORN": "(cell_class == 'olfactory') & (super_class == 'sensory')",
    "ALLN": "cell_class == 'ALLN'", "KC": "cell_type.startswith('KC')",
    "MBON": "cell_type.startswith('MBON')", "DAN": "cell_type.startswith(('PAM', 'PPL1', 'PPL2', 'PAL'))",
    "APL_DPM": "cell_type.startswith(('APL', 'DPM'))", "OA_named": "cell_type.startswith(('OA-', 'VPM', 'VUM'))",
    "CSD": "cell_type.startswith('CSD')", "CX": "cell_class == 'CX'",
    "DN": "super_class == 'descending'", "endocrine": "super_class == 'endocrine'",
}


def parse_positive_nt(value: Any) -> frozenset[str]:
    """Split both separators, trim/casefold, reject whole -negative fragments.

    A positive assertion elsewhere in the same row is retained even when a
    separate experiment reported a negative result, as specified by the brief.
    """
    if value is None or pd.isna(value):
        return frozenset()
    return frozenset(token for part in re.split(r"[;,]", str(value))
                     if (token := part.strip().casefold()) and not token.endswith("-negative"))


def positive_nt_masks(table: pd.DataFrame, names: dict[str, str] = SPECIES) -> dict[str, np.ndarray]:
    tokens = table.known_nt.map(parse_positive_nt)
    return {key: tokens.map(lambda row: nt.casefold() in row).to_numpy(dtype=bool)
            for key, nt in names.items()}


def source_masks(table: pd.DataFrame) -> dict[str, np.ndarray]:
    """Ground-truth source selection plus the explicit KC aminergic exclusion.

    KC sNPF is intentionally preserved, separate from the aminergic inventory,
    as explicitly resolved by Patch 1 section 3. NO remains per neuron.
    """
    masks = positive_nt_masks(table)
    kc = table.cell_type.fillna("").str.startswith("KC").to_numpy(dtype=bool)
    for species in AMINERGIC:
        masks[species] = masks[species] & ~kc
    return masks


def model_subset(completeness: pd.DataFrame, annotations: pd.DataFrame) -> pd.DataFrame:
    """Join without float coercion of root IDs or loss of completeness ordering."""
    roots = completeness.rename(columns={"Unnamed: 0": "root_id"})
    if roots.root_id.dtype != np.dtype("int64") or annotations.root_id.dtype != np.dtype("int64"):
        raise ValueError("root_id must be int64 in both source tables")
    if roots.root_id.duplicated().any() or annotations.root_id.duplicated().any():
        raise ValueError("Duplicate root IDs in source tables")
    result = roots.merge(annotations, on="root_id", how="left", sort=False, validate="one_to_one")
    if not np.array_equal(result.root_id, roots.root_id):
        raise ValueError("Completeness row order changed")
    result.insert(0, "model_index", np.arange(len(result), dtype=np.int32))
    return result


def block_masks(table: pd.DataFrame) -> dict[str, np.ndarray]:
    """Normative Patch 1 selectors; never trim or expand to reach a count."""
    cells = table.cell_type.fillna("")
    masks = {key: table.cell_class.eq(name) for key, name in
             {"PN": "ALPN", "ALLN": "ALLN", "CX": "CX"}.items()}
    masks.update({"ORN": table.cell_class.eq("olfactory") & table.super_class.eq("sensory"),
                  "KC": cells.str.startswith("KC"), "MBON": cells.str.startswith("MBON"),
                  "DAN": cells.str.startswith(("PAM", "PPL1", "PPL2", "PAL")),
                  "APL_DPM": cells.str.startswith(("APL", "DPM")),
                  "OA_named": cells.str.startswith(("OA-", "VPM", "VUM")),
                  "CSD": cells.str.startswith("CSD"),
                  "DN": table.super_class.eq("descending"),
                  "endocrine": table.super_class.eq("endocrine")})
    return {key: value.fillna(False).to_numpy(dtype=bool) for key, value in masks.items()}


def reference_check(name: str, observed: Any, expected: Any, *, kind: str = "primary_data") -> dict:
    """Primary/software mismatches fail; population definitions warn and proceed."""
    if kind not in {"primary_data", "software_integrity", "population_definition"}:
        raise ValueError(f"Unknown check kind: {kind}")
    status = "PASS" if observed == expected else ("WARNING" if kind == "population_definition" else "FAIL")
    return {"name": name, "status": status, "kind": kind, "observed": observed, "expected": expected}


def gate_status(checks: list[dict]) -> str:
    accepted = lambda row: row["status"] == "PASS" or (
        row["status"] == "WARNING" and row.get("kind") == "population_definition")
    return "PASS" if checks and all(accepted(row) for row in checks) else "FAIL"


def population_inventory(table: pd.DataFrame, blocks: dict[str, np.ndarray]) -> dict:
    """Count named types, unknown category, untyped cells and all side labels."""
    result = {}
    for key, mask in blocks.items():
        selected = table.loc[mask]
        types = selected.cell_type.fillna("")
        named = int(types[types.ne("")].nunique())
        untyped = int(types.eq("").sum())
        sides = selected.side.fillna("__UNKNOWN__").value_counts().to_dict()
        result[key] = {"neurons": int(mask.sum()), "named_types": named,
                       "type_categories": named + int(untyped > 0), "types": named + int(untyped > 0),
                       "untyped": untyped, "left": int(sides.get("left", 0)),
                       "right": int(sides.get("right", 0)), "side_counts": sides,
                       "selection": SELECTIONS[key]}
    return result


def transmitter_audit(annotations: pd.DataFrame) -> list[dict]:
    positive = positive_nt_masks(annotations, {key: key for key in EXPECTED_AUDIT})
    audit = []
    for nt, truth in positive.items():
        prediction = annotations.top_nt.fillna("").str.casefold().eq(nt).to_numpy(dtype=bool)
        n_truth, agree = int(truth.sum()), int((truth & prediction).sum())
        audit.append({"transmitter": nt, "positive_known_nt": n_truth,
                      "predicted_top_nt": int(prediction.sum()), "agree": agree,
                      "ground_truth_recovered_pct": 100 * agree / n_truth if n_truth else None})
    return audit


def census_edges(path: Path, blocks: dict[str, np.ndarray]) -> tuple[dict, dict]:
    """Batched exact edge/synapse counts; store only small motif count vectors."""
    pairs = {name: name.split("->") for name in EXPECTED_MOTIFS}
    chunks = {name: [] for name in pairs}
    core_mask = np.logical_or.reduce(list(blocks.values()))
    core = {"neurons": int(core_mask.sum()), "edges": 0, "synapses": 0,
            "selection": "deduplicated union of the explicit block selections"}
    core["csr_float32_int32_bytes"] = 0
    columns = ["Presynaptic_Index", "Postsynaptic_Index", "Connectivity"]
    for batch in pq.ParquetFile(path).iter_batches(batch_size=262144, columns=columns):
        check_memory()
        pre, post, weights = [batch.column(name).to_numpy() for name in columns]
        if any(np.any((indices < 0) | (indices >= len(core_mask))) for indices in (pre, post)):
            raise ValueError("Out-of-bounds connectivity index")
        for name, (a, b) in pairs.items():
            selected = weights[blocks[a][pre] & blocks[b][post]]
            if len(selected):
                chunks[name].append(selected.copy())
        selected = weights[core_mask[pre] & core_mask[post]]
        core["edges"] += len(selected)
        core["synapses"] += int(selected.sum(dtype=np.int64))
    motifs = {}
    for name, values in chunks.items():
        weights = np.concatenate(values) if values else np.empty(0, dtype=np.int64)
        motifs[name] = {"edges": len(weights), "synapses": int(weights.sum(dtype=np.int64)),
                        "median_synapses_per_edge": float(np.median(weights)) if len(weights) else None}
        if name == "KC->KC":
            motifs[name]["threshold_2_edges"] = int((weights >= 2).sum())
            motifs[name]["threshold_2_synapses"] = int(weights[weights >= 2].sum(dtype=np.int64))
    core["csr_float32_int32_bytes"] = core["edges"] * 8 + (core["neurons"] + 1) * 4
    return motifs, core


def _write_parquet(table: pd.DataFrame, path: Path) -> None:
    temporary = path.with_suffix(".partial.parquet")
    table.to_parquet(temporary, index=False)
    temporary.replace(path)


def _source_rows(annotations: pd.DataFrame, neurons: pd.DataFrame) -> pd.DataFrame:
    indices = pd.Series(neurons.model_index.to_numpy(), index=neurons.root_id)
    columns = ["root_id", "cell_type", "cell_class", "super_class", "side", "known_nt", "known_nt_source"]
    rows = []
    for species, selected in source_masks(annotations).items():
        frame = annotations.loc[selected, columns].copy()
        frame.insert(0, "species", species)
        frame["model_index"] = frame.root_id.map(indices).fillna(-1).astype(np.int32)
        frame["in_model"] = frame.model_index.ge(0)
        frame["selection_evidence"] = "positive known_nt token; top_nt never consulted"
        rows.append(frame)
    return pd.concat(rows, ignore_index=True)


def _verify_base_artifacts(root: Path, source_hashes: dict[str, str]) -> dict:
    build = root / "build"
    summary = json.loads((build / "build_summary.json").read_text())
    if summary.get("status") != "PASS" or summary.get("source_hashes") != source_hashes:
        raise ValueError("Base network build is not PASS for these exact source hashes")
    required = {"neurons.parquet", "graded_counts.npz", "spiking_counts.npz", "reference_counts.npz"}
    if not required.issubset(summary.get("output_hashes", {})):
        raise ValueError("Base network lacks required neuron/CSR hashes")
    for name, digest in summary["output_hashes"].items():
        if checksum(build / name) != digest:
            raise ValueError(f"Base network artifact was modified: {name}")
    for name, digest in summary.get("config_hashes", {}).items():
        if checksum(root / "config" / name) != digest:
            raise ValueError(f"Base network config was modified: {name}")
    return summary


def build_sources(root: Path) -> dict:
    """Reinspect, validate V-A and save a durable PASS/FAIL V-NM-C record.

    Patch 1 fixes the population definition in selectors, with reference-count
    discrepancies reported as warnings. Primary-data mismatches remain fatal.
    The source gate does not certify an engine or emit a simulation matrix.
    """
    root = Path(root).resolve()
    output, raw = root / "build", root / "data/raw"
    output.mkdir(parents=True, exist_ok=True)
    checks, artifacts = [], []
    result = {"gate": "V-NM-C", "status": "FAIL", "created_at": datetime.now(timezone.utc).isoformat(),
              "checks": checks, "source": "NEUROMOD_BUILD_BRIEF.md sections 2 and 10, superseded by NEUROMOD_PATCH1.md sections 1-3",
              "artifacts_usable_for_simulation": False, "artifacts_usable_for_source_layer": False,
              "selections": SELECTIONS, "population_definition_version": 2,
              "notes": ["Named types, named plus unknown category, and untyped neurons are counted separately.",
                        "All annotation source rows are retained; model_index=-1 means outside Completeness.",
                        "Patch 1 preserves KC sNPF independently while excluding every KC from aminergic sources.",
                        "Population-reference differences warn and proceed using the normative selector; primary-data differences fail.",
                        "Source acceptance does not certify a runnable or validated simulation engine."]}

    # Invalidate old acceptance before doing work. A crash or later I/O error
    # must not leave a previous PASS authorizing consumers.
    atomic_write_json(output / "validation_neuromod_sources.json", {
        **result, "failed_checks": ["build_in_progress"], "stop_reason": "Source audit in progress; artifacts are not approved."})
    atomic_write_json(output / "neuromod_sources_manifest.json", {
        "gate": "V-NM-C", "status": "FAIL", "artifacts_usable_for_simulation": False,
        "validation_sha256": checksum(output / "validation_neuromod_sources.json")})

    def check(name: str, observed: Any, expected: Any, *, kind: str = "primary_data") -> bool:
        row = reference_check(name, observed, expected, kind=kind)
        checks.append(row)
        print(f"[V-NM-C {row['status']}] {name}: {observed!r}; expected {expected!r}")
        return row["status"] != "FAIL"

    try:
        result["implementation_hashes"] = {"src/flybrain/neuromod/sources.py": checksum(Path(__file__))}
        result["config_hashes"] = {"neuromod.yaml": checksum(root / "config/neuromod.yaml")} if (root / "config/neuromod.yaml").exists() else {}
        result["source_stats"] = {name: stat_signature(raw / name) for name in RAW_FILES}
        inspection = {name: inspect_table(raw / name) for name in RAW_FILES}
        inspection["neurons.parquet"] = inspect_table(output / "neurons.parquet")
        atomic_write_json(output / "schema_inspection_neuromod.json", inspection)
        artifacts.append("schema_inspection_neuromod.json")
        prerequisite = validate_data(root)
        result["source_hashes"] = prerequisite.get("source_hashes", {})
        if not check("prerequisite_V-A", prerequisite["status"], "PASS"):
            raise ValueError("V-A failed; source stage stopped")
        base = _verify_base_artifacts(root, result["source_hashes"])
        result["base_artifact_hashes"] = base["output_hashes"]
        result["base_config_hashes"] = base.get("config_hashes", {})
        check("prerequisite_base_build", base["status"], "PASS")
        annotations = pd.read_csv(raw / RAW_FILES[2], sep="\t", low_memory=False)
        neurons = model_subset(pd.read_csv(raw / RAW_FILES[0]), annotations)
        saved_neurons = pd.read_parquet(output / "neurons.parquet", columns=["index", "root_id"])
        check("base_neuron_row_order", bool(np.array_equal(neurons.root_id, saved_neurons.root_id)
                                           and np.array_equal(neurons.model_index, saved_neurons["index"])), True)
        check("annotation_empty_known_nt", int(annotations.known_nt.isna().sum()), 51411)
        result["audit"] = transmitter_audit(annotations)
        pd.DataFrame(result["audit"]).to_csv(output / "neuromod_transmitter_audit.csv", index=False)
        artifacts.append("neuromod_transmitter_audit.csv")
        for row in result["audit"]:
            check(f"audit_{row['transmitter']}", [row[k] for k in ("positive_known_nt", "predicted_top_nt", "agree")],
                  list(EXPECTED_AUDIT[row["transmitter"]]))
        blocks, ann_blocks = block_masks(neurons), block_masks(annotations)
        inventory = population_inventory(neurons, blocks)
        result["inventory"] = inventory
        for key, expected in EXPECTED_BLOCKS.items():
            for field, value in zip(("neurons", "left", "right", "named_types", "untyped"), expected, strict=True):
                check(f"block_{key}_{field}", inventory[key][field], value, kind="population_definition")
        check("ORN_PN_disjoint", int((blocks["ORN"] & blocks["PN"]).sum()), 0, kind="software_integrity")
        check("DAN_annotation_per_type", annotations.loc[ann_blocks["DAN"], "cell_type"].value_counts().to_dict(), DAN_COUNTS,
              kind="population_definition")
        for cluster, expected in {"PAM": 307, "PPL1": 16, "PPL2": 8, "PAL": 6}.items():
            check(f"DAN_{cluster}", int(neurons.cell_type.fillna("").str.startswith(cluster).sum()), expected,
                  kind="population_definition")
        positive = positive_nt_masks(annotations)
        check("all_MB_DAN_positive_dopamine", int((ann_blocks["DAN"] & positive["DA"]).sum()),
              int(ann_blocks["DAN"].sum()), kind="software_integrity")
        check("dopamine_super_classes", annotations.loc[positive["DA"], "super_class"].value_counts().to_dict(),
              {"optic": 980, "central": 408, "visual_centrifugal": 7})
        result["MB_DAN_nitric_oxide_counts"] = annotations.loc[ann_blocks["DAN"] & positive["NO"], "cell_type"].value_counts().to_dict()
        check("MB_DAN_nitric_oxide_per_neuron_counts", result["MB_DAN_nitric_oxide_counts"], EXPECTED_NO_DAN_COUNTS)
        check("endocrine_annotation", int(ann_blocks["endocrine"].sum()), 80, kind="population_definition")
        endocrine = annotations.loc[ann_blocks["endocrine"], ["root_id", "cell_type", "cell_class", "known_nt"]].copy()
        endocrine["in_model"] = endocrine.root_id.isin(neurons.root_id)
        _write_parquet(endocrine, output / "neuromod_endocrine.parquet")
        artifacts.append("neuromod_endocrine.parquet")
        result["endocrine_by_type"] = {"annotation": endocrine.cell_type.value_counts().to_dict(),
                                      "model": endocrine.loc[endocrine.in_model, "cell_type"].value_counts().to_dict()}
        selected = source_masks(annotations)
        oa_al2b2 = annotations.cell_type.eq("OA-AL2b2").to_numpy(dtype=bool)
        check("OA-AL2b2_neurons", int(oa_al2b2.sum()), 4)
        check("OA-AL2b2_octopamine_sources", int((oa_al2b2 & selected["OA"]).sum()), 0)
        check("OA-AL2b2_tyramine_sources", int((oa_al2b2 & selected["TA"]).sum()), 4)
        rows = _source_rows(annotations, neurons)
        primary = rows[rows.species.ne("sNPF")].copy()
        peptides = rows[rows.species.eq("sNPF")].copy()
        for name, table in [("neuromod_sources.parquet", primary), ("neuromod_peptide_sources.parquet", peptides)]:
            _write_parquet(table, output / name)
            artifacts.append(name)
        type_inventory = rows.groupby(["species", "cell_type", "side"], dropna=False).agg(
            annotation_neurons=("root_id", "size"), model_neurons=("in_model", "sum")).reset_index()
        type_inventory.to_csv(output / "neuromod_source_inventory.csv", index=False)
        artifacts.append("neuromod_source_inventory.csv")
        result["source_counts"] = {key: {"annotation": int(mask.sum()), "model": int(((rows.species == key) & rows.in_model).sum())}
                                   for key, mask in selected.items()}
        kc = blocks["KC"]
        known_ach = neurons.known_nt.map(parse_positive_nt).map(lambda v: "acetylcholine" in v).to_numpy(dtype=bool)
        check("KC_known_acetylcholine", int((kc & known_ach).sum()), int(kc.sum()), kind="software_integrity")
        check("KC_predicted_dopamine", int((kc & neurons.top_nt.eq("dopamine").to_numpy(dtype=bool)).sum()), 5172,
              kind="population_definition")
        overrides = neurons.loc[kc, ["model_index", "root_id", "cell_type", "top_nt", "known_nt"]].copy()
        overrides["effective_fast_nt"] = "acetylcholine"
        overrides["effective_fast_sign"] = 1
        overrides["exclude_aminergic_source"] = True
        overrides["reason"] = "Defect D: positive known acetylcholine overrides EM prediction"
        overrides["source"] = "PMID:26948892"
        overrides.to_csv(output / "neuromod_overrides.csv", index=False)
        artifacts.append("neuromod_overrides.csv")
        check("defect_D_override_rows", len(overrides), int(kc.sum()), kind="software_integrity")
        kc_sources = source_masks(neurons)
        check("KC_aminergic_sources", int((kc & np.logical_or.reduce([kc_sources[k] for k in AMINERGIC])).sum()), 0)
        result["KC_sNPF_sources"] = int((kc & kc_sources["sNPF"]).sum())
        check("KC_sNPF_sources", result["KC_sNPF_sources"], 4133)
        check("brain_sNPF_sources", int(kc_sources["sNPF"].sum()), 5034)
        result["motifs"], result["core"] = census_edges(raw / RAW_FILES[1], blocks)
        for name, (edges, synapses, median) in EXPECTED_MOTIFS.items():
            actual = result["motifs"][name]
            check(f"motif_{name}", [actual["edges"], actual["synapses"], actual["median_synapses_per_edge"]], [edges, synapses, median])
        for name, expected in {"neurons": 13300, "edges": 1161917, "synapses": 4581576}.items():
            check(f"core_{name}", result["core"][name], expected,
                  kind="population_definition" if name == "neurons" else "primary_data")
        core_mask = np.logical_or.reduce(list(blocks.values()))
        result["core"]["block_sum"] = sum(int(mask.sum()) for mask in blocks.values())
        check("core_block_sum", result["core"]["block_sum"], 13302, kind="population_definition")
        overlaps = []
        keys = list(blocks)
        for i, first in enumerate(keys):
            for second in keys[i + 1:]:
                mask = blocks[first] & blocks[second]
                if mask.any():
                    overlaps.append({"blocks": sorted([first, second]), "neurons": int(mask.sum()),
                                     "cell_types": neurons.loc[mask, "cell_type"].value_counts().to_dict(),
                                     "root_ids": neurons.loc[mask, "root_id"].tolist()})
        result["core"]["overlaps"] = overlaps
        check("core_overlap_membership", [{k: v for k, v in row.items() if k != "root_ids"} for row in overlaps],
              [{"blocks": ["ALLN", "OA_named"], "neurons": 2, "cell_types": {"OA-VUMa5": 2}}],
              kind="population_definition")
        core_neurons = neurons.loc[core_mask].copy()
        core_neurons.insert(0, "core_index", np.arange(len(core_neurons), dtype=np.int32))
        for block, mask in blocks.items():
            core_neurons[f"block_{block}"] = mask[core_mask]
        _write_parquet(core_neurons, output / "neuromod_core_diagnostic.parquet")
        artifacts.append("neuromod_core_diagnostic.parquet")
        # Explain an exact numerical coincidence without adopting an invalid biological selection.
        pn_plus_orn = blocks["PN"] | neurons.cell_type.fillna("").str.startswith("ORN").to_numpy(dtype=bool)
        result["unaccepted_selection_diagnostic"] = {
            "PN_plus_named_ORNs_neurons": int(pn_plus_orn.sum()),
            "PN_plus_named_ORNs_types": int(neurons.loc[pn_plus_orn, "cell_type"].nunique()),
            "interpretation": "This union matches the brief's PN count but includes receptor neurons; not used as a PN selector."}
        for name, before in result["source_stats"].items():
            check(f"source_unchanged_{name}", stat_signature(raw / name), before)
        for name, digest in result["base_artifact_hashes"].items():
            check(f"base_artifact_unchanged_{name}", checksum(output / name), digest)
    except Exception as exc:
        check("source_stage_execution", {"error_type": type(exc).__name__, "error": str(exc)}, "no errors")
    result["artifact_hashes"] = {}
    try:
        atomic_write_json(output / "neuromod_population_discrepancies.json",
                          [row for row in checks if row["status"] == "WARNING"])
        artifacts.append("neuromod_population_discrepancies.json")
        result["artifact_hashes"] = {name: checksum(output / name) for name in artifacts}
    except Exception as exc:
        check("artifact_hash_execution", {"error_type": type(exc).__name__, "error": str(exc)}, "no errors")
    result["status"] = gate_status(checks)
    result["failed_checks"] = [row["name"] for row in checks if row["status"] == "FAIL"]
    result["warning_checks"] = [row["name"] for row in checks if row["status"] == "WARNING"]
    result["artifacts_usable_for_source_layer"] = result["status"] == "PASS"
    result["stop_reason"] = ("V-NM-C failed; subsequent stages are blocked: " + ", ".join(result["failed_checks"])) if result["failed_checks"] else None
    atomic_write_json(output / "validation_neuromod_sources.json", result)
    atomic_write_json(output / "neuromod_sources_manifest.json", {
        "gate": "V-NM-C", "status": result["status"], "artifacts_usable_for_simulation": False,
        "artifacts_usable_for_source_layer": result["artifacts_usable_for_source_layer"],
        "validation_sha256": checksum(output / "validation_neuromod_sources.json"),
        "source_hashes": result.get("source_hashes", {}), "artifacts": result["artifact_hashes"]})
    return result


def require_source_gate(root: Path) -> dict:
    """Fail closed on red, stale, modified or internally inconsistent evidence."""
    root = Path(root)
    build = root / "build"
    path = build / "validation_neuromod_sources.json"
    result = json.loads(path.read_text())
    manifest = json.loads((build / "neuromod_sources_manifest.json").read_text())
    if manifest.get("validation_sha256") != checksum(path):
        raise ValueError("V-NM-C validation record was modified")
    if result.get("status") != "PASS" or manifest.get("status") != "PASS" or result.get("failed_checks"):
        raise ValueError(f"V-NM-C is not PASS: {result.get('failed_checks', [])}")
    if gate_status(result.get("checks", [])) != "PASS":
        raise ValueError("V-NM-C check evidence is incomplete")
    for name in RAW_FILES:
        if checksum(root / "data/raw" / name) != result["source_hashes"].get(name):
            raise ValueError(f"V-NM-C source changed: {name}")
    for name, digest in result["artifact_hashes"].items():
        if checksum(build / name) != digest:
            raise ValueError(f"V-NM-C artifact changed: {name}")
    for name, before in result.get("source_stats", {}).items():
        if stat_signature(root / "data/raw" / name) != before:
            raise ValueError(f"V-NM-C source signature changed: {name}")
    for key, directory in (("base_artifact_hashes", build), ("base_config_hashes", root / "config"),
                           ("config_hashes", root / "config"), ("implementation_hashes", root)):
        for name, digest in result.get(key, {}).items():
            if checksum(directory / name) != digest:
                raise ValueError(f"V-NM-C {key} changed: {name}")
    return result
