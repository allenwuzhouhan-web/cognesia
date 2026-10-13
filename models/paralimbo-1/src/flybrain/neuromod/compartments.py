"""Auditable compartment membership and independent mushroom-body clustering.

The released connectivity determines clusters. Published anatomy labels them
afterwards; disagreement never changes the clustering. A membership is a coarse
model volume proxy, not a measured neurotransmitter-release location.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import scipy
from scipy.cluster.hierarchy import cut_tree, linkage
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import pdist, squareform

from ..fetch import checksum
from ..inspect_data import atomic_write_json
from ..memguard import check_memory
from ..visual_neuropils import load_neuropil_weights
from .sources import block_masks, require_source_gate


MB_NAMES = ("g1", "g2", "g3", "g4", "g5", "bp1", "bp2", "b1", "b2",
            "a1", "a2", "a3", "ap1", "ap2", "ap3")
SCHEMA_VERSION = 1
METHOD = {
    "partner_direction": "DAN->KC and KC->MBON",
    "edge_threshold_synapses": 1,
    "vector": "binary union of KC partners across all cells of each type; both hemispheres pooled",
    "distance": "Jaccard",
    "linkage": "average",
    "n_clusters": 15,
    "ordering": "lexicographically sorted cell types; scipy cut_tree exact cluster count",
    "empty_vectors": "excluded from clustering and retained with assignment -1",
    "canonical_alignment": "Hungarian optimum of fractional type votes (1 / published compartment count)",
    "membership": "DAN/MBON single empirical cluster; KCs in every cluster containing an observed partner",
    "source": "ASSUMPTION; mandated empirical procedure in NEUROMOD_BUILD_BRIEF.md section 4",
}


@dataclass(frozen=True)
class CompartmentMap:
    names: tuple[str, ...]
    membership: np.ndarray
    adjacency: np.ndarray
    mb_assignment: np.ndarray
    model_root_ids: np.ndarray
    metadata: dict


def read_reference(path: Path) -> dict[str, dict]:
    table = pd.read_csv(path, keep_default_na=False)
    required = {"cell_type", "compartments", "status", "role", "source", "url", "note"}
    if not required.issubset(table.columns) or table.cell_type.duplicated().any():
        raise ValueError("Compartment reference needs unique types and complete provenance columns")
    reference = {}
    for row in table.to_dict("records"):
        labels = tuple(filter(None, row["compartments"].split(";")))
        if not set(labels).issubset(MB_NAMES):
            raise ValueError(f"Unknown published compartment: {row['cell_type']}")
        if not row["source"] or not row["url"] or row["role"] not in {"DAN", "MBON"}:
            raise ValueError(f"Missing published reference provenance: {row['cell_type']}")
        if row["status"] not in {"published", "ambiguous_label", "outside_15", "unmapped"}:
            raise ValueError("Unknown anatomical reference status")
        if row["status"] == "published" and not labels:
            raise ValueError("A published lobe assignment must identify a compartment")
        reference[row["cell_type"]] = row | {"labels": labels}
    return reference


def kc_partner_vectors(neurons: pd.DataFrame, connectivity: Path) -> dict:
    """Return type-by-KC binary vectors and the exact plastic edge identities."""
    blocks = block_masks(neurons)
    kc_indices = np.flatnonzero(blocks["KC"]).astype(np.int32)
    kc_lookup = np.full(len(neurons), -1, np.int32)
    kc_lookup[kc_indices] = np.arange(len(kc_indices), dtype=np.int32)
    types = tuple(sorted(neurons.loc[blocks["DAN"] | blocks["MBON"], "cell_type"].unique()))
    lookup = {name: index for index, name in enumerate(types)}
    type_codes = np.array([lookup.get(name, -1) for name in neurons.cell_type.fillna("")], np.int32)
    vectors = np.zeros((len(types), len(kc_indices)), dtype=bool)
    edge_parts = []
    columns = ["Presynaptic_Index", "Postsynaptic_Index", "Connectivity"]
    for batch in pq.ParquetFile(connectivity).iter_batches(batch_size=262144, columns=columns):
        check_memory()
        pre, post, count = [batch.column(name).to_numpy() for name in columns]
        if np.any(pre < 0) or np.any(post < 0) or np.any(pre >= len(neurons)) or np.any(post >= len(neurons)):
            raise ValueError("Connectivity index out of model bounds")
        positive = count >= 1
        dan = positive & blocks["DAN"][pre] & blocks["KC"][post]
        vectors[type_codes[pre[dan]], kc_lookup[post[dan]]] = True
        mbon = positive & blocks["KC"][pre] & blocks["MBON"][post]
        vectors[type_codes[post[mbon]], kc_lookup[pre[mbon]]] = True
        if mbon.any():
            edge_parts.append(np.column_stack((pre[mbon], post[mbon], count[mbon])))
    edges = np.concatenate(edge_parts).astype(np.int64) if edge_parts else np.empty((0, 3), np.int64)
    return {"types": types, "vectors": vectors, "kc_indices": kc_indices,
            "type_codes": type_codes, "plastic_edges": edges}


def cluster_partners(types: tuple[str, ...], vectors: np.ndarray, reference: dict,
                     n_clusters: int = 15) -> dict:
    """Cluster before any reference is read; retain unsupported labels explicitly."""
    vectors = np.asarray(vectors, dtype=bool)
    if vectors.ndim != 2 or vectors.shape[0] != len(types) or len(set(types)) != len(types):
        raise ValueError("Partner vectors require one row per unique ordered type")
    nonempty = vectors.any(axis=1)
    if nonempty.sum() < n_clusters:
        raise ValueError("Fewer nonempty KC-partner vectors than requested clusters")
    distances = pdist(vectors[nonempty], metric="jaccard")
    if not np.isfinite(distances).all():
        raise ValueError("Nonfinite KC-partner Jaccard distances")
    tree = linkage(distances, method="average")
    raw = cut_tree(tree, n_clusters=[n_clusters]).ravel()
    if len(np.unique(raw)) != n_clusters:
        raise ValueError("Empirical clustering did not produce the exact cluster count")
    # Reference-free membership is fixed above this line.
    scores = np.zeros((n_clusters, len(MB_NAMES)), np.float64)
    active_rows = np.flatnonzero(nonempty)
    for row, cluster in zip(active_rows, raw, strict=True):
        info = reference.get(types[row], {})
        labels = info.get("labels", ()) if info.get("status") == "published" else ()
        for label in labels:
            scores[cluster, MB_NAMES.index(label)] += 1.0 / len(labels)
    cluster_rows, label_columns = linear_sum_assignment(-scores)
    alignment = {int(row): int(col) for row, col in zip(cluster_rows, label_columns, strict=True)}
    assigned = np.full(len(types), -1, np.int16)
    empirical = np.full(len(types), -1, np.int16)
    for row, cluster in zip(active_rows, raw, strict=True):
        assigned[row] = alignment[int(cluster)]
        empirical[row] = cluster
    rows = []
    for i, name in enumerate(types):
        info = reference.get(name, {})
        canonical = MB_NAMES[assigned[i]] if assigned[i] >= 0 else None
        support = float(scores[empirical[i], assigned[i]]) if assigned[i] >= 0 else 0.0
        labels = info.get("labels", ())
        if not nonempty[i]:
            comparison = "empty_partner_vector"
        elif info.get("status") == "ambiguous_label":
            comparison = "ambiguous_reference_label"
        elif not labels:
            comparison = "outside_15" if info.get("status") == "outside_15" else "unmapped_reference"
        elif support == 0:
            comparison = "unsupported_cluster_label"
        elif len(labels) > 1:
            comparison = "multi_compartment_contains_cluster" if canonical in labels else "multi_compartment_disagrees"
        else:
            comparison = "match" if canonical in labels else "disagreement"
        rows.append({"cell_type": name, "empirical_cluster": int(empirical[i]),
                     "aligned_compartment": canonical, "alignment_support": support,
                     "canonical_identity_supported": support > 0,
                     "n_KC_partners": int(vectors[i].sum()), "reference_compartments": list(labels),
                     "reference_status": info.get("status", "unmapped"), "comparison": comparison,
                     "source": info.get("source"), "url": info.get("url")})
    matrix = np.full((len(types), len(types)), np.nan, np.float64)
    matrix[np.ix_(nonempty, nonempty)] = squareform(distances)
    return {"assignment": assigned, "raw_cluster": empirical, "rows": rows,
            "alignment_scores": scores, "alignment": alignment, "jaccard": matrix,
            "linkage": tree, "empty_types": [types[i] for i in np.flatnonzero(~nonempty)]}


def glomeruli_from_type(cell_type: str, cell_class: str) -> tuple[str, ...]:
    """Parse anatomical names, never interpreting M/MZ/Z or CB as glomeruli.

    VM6l/m/v are subglomeruli of VM6 (Schlegel 2021; Task 2022). A trailing
    '+' means additional unspecified territory, not another invented glomerulus.
    """
    if cell_class == "olfactory" and cell_type.startswith("ORN_"):
        candidates = [cell_type[4:]]
    elif cell_class == "ALPN":
        candidates = [token for alternative in cell_type.split(",")
                      for token in alternative.split("_", 1)[0].split("+")]
    else:
        return ()
    labels = set()
    for token in candidates:
        if token in {"VM6l", "VM6m", "VM6v"}:
            token = "VM6"
        if token in {"D", "V"} or re.fullmatch(r"(?:DA|DC|DL|DM|DP|VA|VC|VL|VM|VP)\d+[a-z]?", token):
            labels.add(token)
    return tuple(sorted(labels))


def anatomical_membership(neurons: pd.DataFrame, vectors: dict, clusters: dict,
                          neuropils: dict) -> tuple[CompartmentMap, list[dict]]:
    """Combine empirical MB, named AL, measured coarse ROIs and endocrine pool."""
    n = len(neurons)
    names, masks = list(MB_NAMES), [np.zeros(n, bool) for _ in MB_NAMES]
    assignments = np.full(n, -1, np.int16)
    for type_index, label_index in enumerate(clusters["assignment"]):
        if label_index < 0:
            continue
        members = vectors["type_codes"] == type_index
        masks[label_index][members] = True
        assignments[members] = label_index
        masks[label_index][vectors["kc_indices"][vectors["vectors"][type_index]]] = True
    roi_lookup = {name: i for i, name in enumerate(neuropils["names"])}

    def roi(name):
        if name not in roi_lookup:
            return np.zeros(n, bool)
        return np.asarray(neuropils["weights"][roi_lookup[name]].toarray()).ravel() > 0

    def add(name, mask):
        names.append(name)
        masks.append(np.asarray(mask, dtype=bool))

    cells = neurons.cell_type.fillna("")
    classes = neurons.cell_class.fillna("")
    glomerulus_masks, al_rows = {}, []
    for i, (cell, cell_class) in enumerate(zip(cells, classes, strict=True)):
        if cell_class not in {"olfactory", "ALPN"}:
            continue
        glomeruli = glomeruli_from_type(cell, cell_class)
        for glomerulus in glomeruli:
            glomerulus_masks.setdefault(glomerulus, np.zeros(n, bool))[i] = True
        al_rows.append({"model_index": i, "root_id": int(neurons.root_id.iloc[i]),
                        "cell_type": cell, "cell_class": cell_class,
                        "glomeruli": ";".join(glomeruli),
                        "status": "mapped_named_territory" if glomeruli else "unresolved",
                        "additional_unspecified_territory": "+_" in cell or cell.startswith(("M_", "MZ_")),
                        "source": "DOI:10.7554/eLife.57443; DOI:10.7554/eLife.66018; DOI:10.7554/eLife.72599"})
    for label, mask in sorted(glomerulus_masks.items()):
        add("AL_" + label, mask)
    mapped_al = np.logical_or.reduce(list(glomerulus_masks.values())) if glomerulus_masks else np.zeros(n, bool)
    add("AL_unresolved", (roi("AL_L") | roi("AL_R") | classes.isin(["olfactory", "ALPN", "ALLN"]).to_numpy()) & ~mapped_al)
    for label in ("EB", "PB", "NO"):
        add("CX_" + label, roi(label))
    fb_assigned = np.zeros(n, bool)
    cx = classes.eq("CX").to_numpy()
    for layer in range(1, 10):
        # Tangential FB names encode a layer; FC/FS/FR and columnar names do not.
        member = cx & cells.str.contains(rf"(?:^|,)FB{layer}(?:[A-Z_,]|$)", regex=True).to_numpy() & roi("FB")
        add(f"CX_FB{layer}", member)
        fb_assigned |= member
    add("CX_FB_unresolved", roi("FB") & ~fb_assigned)
    for label in ("LA", "ME", "LO", "LOP"):
        for side in ("L", "R"):
            add(f"{label}_{side}", roi(f"{label}_{side}"))
    add("hemolymph", neurons.super_class.eq("endocrine").to_numpy())
    membership = np.asarray(masks, bool)
    adjacency = compartment_adjacency(tuple(names))
    metadata = {
        "schema_version": SCHEMA_VERSION, "method": METHOD,
        "units": "boolean membership, dimensionless assumed adjacency",
        "anatomical_interpretation": "Synaptic partner/endpoint/name evidence; NOT a release-site map or receptor-expression map",
        "hemolymph": "Symbolic global pool: membership marks endocrine source-interface cells; receptor targets are defined by later layers",
        "AL": "Hemisphere pooled; 53 named ORN classes retain identity but VM6 subglomeruli share VM6 volume; multi/unknown names stay unresolved",
        "CX": "EB/PB/NO from actual endpoint ROIs; FB1-9 from named tangential type layer plus FB endpoints; other FB arbors unresolved",
        "optic": "Actual pre+post endpoint membership in LA/ME/LO/LOP per side; not inferred from soma side or type prefix",
        "adjacency": "ASSUMPTION: consecutive MB lobe slices and FB layers; LA-ME, ME-LO and ME-LOP within each optic side; AL, unresolved volumes and hemolymph have no assumed diffusion neighbors",
        "anatomical_sources": {
            "MB": "https://pmc.ncbi.nlm.nih.gov/articles/PMC7909955/ (Figures 6, 6 supplement 1, 7 and 8; DOI:10.7554/eLife.62576)",
            "AL_naming": "https://elifesciences.org/articles/57443/figures (DOI:10.7554/eLife.57443)",
            "AL_VM6": "https://elifesciences.org/articles/66018 and https://pmc.ncbi.nlm.nih.gov/articles/PMC9020824/ (DOI:10.7554/eLife.66018; DOI:10.7554/eLife.72599)",
            "CX": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9477501/ (DOI:10.7554/eLife.66039)",
        },
        "unassigned_neurons": int((~membership.any(axis=0)).sum()),
        "unassigned_root_ids": [int(x) for x in neurons.root_id[~membership.any(axis=0)]],
        "n_compartments": len(names), "membership_neurons": membership.sum(axis=1).astype(int).tolist(),
        "missing_ROI_labels": [name for name in ["AL_L", "AL_R", "EB", "PB", "NO", "FB"]
                               + [f"{p}_{s}" for p in ("LA", "ME", "LO", "LOP") for s in ("L", "R")]
                               if name not in roi_lookup],
    }
    return CompartmentMap(tuple(names), membership, adjacency, assignments,
                          neurons.root_id.to_numpy(dtype=np.int64), metadata), al_rows


def compartment_adjacency(names: tuple[str, ...]) -> np.ndarray:
    """Explicit assumed spatial adjacency, independent of neural connectivity."""
    adjacency = np.zeros((len(names), len(names)), np.float32)
    lookup = {name: i for i, name in enumerate(names)}
    chains = [("g1", "g2", "g3", "g4", "g5"), ("bp1", "bp2"), ("b1", "b2"),
              ("a1", "a2", "a3"), ("ap1", "ap2", "ap3"),
              tuple(f"CX_FB{n}" for n in range(1, 10))]
    pairs = [(a, b) for chain in chains for a, b in zip(chain[:-1], chain[1:])]
    for side in ("L", "R"):
        pairs.extend([(f"LA_{side}", f"ME_{side}"), (f"ME_{side}", f"LO_{side}"),
                      (f"ME_{side}", f"LOP_{side}")])
    for left, right in pairs:
        if left in lookup and right in lookup:
            adjacency[lookup[left], lookup[right]] = adjacency[lookup[right], lookup[left]] = 1
    return adjacency


def build_compartments(root: Path) -> dict:
    root = Path(root).resolve()
    output = root / "build"
    output.mkdir(parents=True, exist_ok=True)
    result = {"gate": "V-NM-COMP", "status": "FAIL", "checks": [],
              "created_at": datetime.now(timezone.utc).isoformat(), "method": METHOD,
              "software_versions": {"numpy": np.__version__, "scipy": scipy.__version__, "pandas": pd.__version__},
              "warnings": [], "artifact_hashes": {}}
    artifacts = []

    def check(name, observed, expected):
        result["checks"].append({"name": name, "observed": observed, "expected": expected,
                                 "status": "PASS" if observed == expected else "FAIL"})

    try:
        source = require_source_gate(root)
        check("prerequisite_source_gate", source["status"], "PASS")
        result["source_hashes"] = source["source_hashes"]
        result["source_stats"] = source["source_stats"]
        result["base_artifact_hashes"] = source["base_artifact_hashes"]
        result["config_hashes"] = {name: checksum(root / "config" / name)
                                   for name in ("neuromod.yaml", "mb_compartment_reference.csv")}
        result["implementation_hashes"] = {name: checksum(root / name) for name in (
            "src/flybrain/neuromod/compartments.py", "src/flybrain/neuromod/sources.py", "src/flybrain/visual_neuropils.py")}
        result["dependency_hashes"] = {"build/validation_neuromod_sources.json": checksum(output / "validation_neuromod_sources.json")}
        reference = read_reference(root / "config/mb_compartment_reference.csv")
        neurons = pd.read_parquet(output / "neurons.parquet")
        vectors = kc_partner_vectors(neurons, root / "data/raw/Connectivity_783.parquet")
        clusters = cluster_partners(vectors["types"], vectors["vectors"], reference)
        check("joint_DAN_MBON_types", len(vectors["types"]), 65)
        check("empirical_clusters", len(set(clusters["assignment"]) - {-1}), 15)
        check("reference_covers_each_type_with_explicit_status", set(vectors["types"]) == set(reference), True)
        neuropils = load_neuropil_weights(root)
        result["neuropil_source_hashes"] = neuropils["metadata"]["source_sha256"]
        result["neuropil_source_stats"] = neuropils["metadata"]["source_stats"]
        result["dependency_hashes"].update({"build/" + name: digest for name, digest in neuropils["metadata"]["output_sha256"].items()})
        mapping, al_rows = anatomical_membership(neurons, vectors, clusters, neuropils)
        check("model_row_order", bool(np.array_equal(mapping.model_root_ids, neurons.root_id)), True)
        check("membership_shape", list(mapping.membership.shape), [len(mapping.names), len(neurons)])
        check("symmetric_nonnegative_adjacency", bool(np.array_equal(mapping.adjacency, mapping.adjacency.T)
                                                      and np.all(mapping.adjacency >= 0)), True)
        check("no_self_adjacency", int(np.count_nonzero(np.diag(mapping.adjacency))), 0)
        check("all_required_ROIs_available", mapping.metadata["missing_ROI_labels"], [])
        check("empty_partner_types_unassigned", bool(np.all(clusters["assignment"][~vectors["vectors"].any(axis=1)] == -1)), True)
        edges = vectors["plastic_edges"]
        check("plastic_edge_count", len(edges), 62261)
        check("plastic_synapse_count", int(edges[:, 2].sum()), 256719)
        edge_compartment = mapping.mb_assignment[edges[:, 1]]
        check("every_plastic_edge_has_empirical_assignment", int((edge_compartment < 0).sum()), 0)
        result["clustering"] = {"types": clusters["rows"], "empty_types": clusters["empty_types"],
                                 "comparison_counts": pd.Series([r["comparison"] for r in clusters["rows"]]).value_counts().to_dict(),
                                 "alignment_scores": clusters["alignment_scores"].tolist(),
                                 "alignment": {str(k): MB_NAMES[v] for k, v in clusters["alignment"].items()},
                                 "multi_compartment_rule": "A single empirical cluster cannot recover every territory of a multi-compartment neuron; containment is reported separately from exact matches"}
        result["coverage"] = {k: v for k, v in mapping.metadata.items() if k in ("n_compartments", "unassigned_neurons", "membership_neurons")}
        result["coverage"]["AL_named_territory_cells"] = sum(bool(r["glomeruli"]) for r in al_rows)
        result["coverage"]["AL_cells_considered"] = len(al_rows)
        result["coverage"]["AL_unresolved_cells"] = sum(not r["glomeruli"] for r in al_rows)
        result["coverage"]["AL_glomeruli"] = sum(name.startswith("AL_") and name != "AL_unresolved" for name in mapping.names)
        result["warnings"] = [
            "Canonical alignment is a label comparison, not validation of anatomical compartments.",
            "Binary KC-partner overlap discards positions along KC axons; matching or mismatching labels is the result, not a fitting objective.",
            "Published mapping is from the hemibrain; correspondence of identically named FlyWire types is a cross-dataset assumption.",
            "Source membership in a compartment does not establish its modulator release location.",
        ]
        for row in clusters["rows"]:
            if row["aligned_compartment"] is not None and not row["canonical_identity_supported"]:
                result["warnings"].append(f"Unsupported canonical label {row['aligned_compartment']} for empirical cluster {row['empirical_cluster']}")
        result["warnings"] = list(dict.fromkeys(result["warnings"]))
        mapping.metadata.update({"clustering": result["clustering"], "coverage": result["coverage"],
                                 "warnings": result["warnings"], "software_versions": result["software_versions"],
                                 "reference_file": "config/mb_compartment_reference.csv",
                                 "reference_sha256": result["config_hashes"]["mb_compartment_reference.csv"]})
        # Persist primitive arrays only: np.load(..., allow_pickle=False) is sufficient.
        np.savez_compressed(output / "compartments.npz", names=np.asarray(mapping.names),
                            membership=mapping.membership, adjacency=mapping.adjacency,
                            mb_assignment=mapping.mb_assignment, model_root_ids=mapping.model_root_ids,
                            type_names=np.asarray(vectors["types"]), type_assignment=clusters["assignment"],
                            type_raw_cluster=clusters["raw_cluster"], kc_indices=vectors["kc_indices"],
                            kc_partner_vectors=vectors["vectors"], jaccard=clusters["jaccard"],
                            linkage=clusters["linkage"], plastic_pre=edges[:, 0].astype(np.int32),
                            plastic_post=edges[:, 1].astype(np.int32), plastic_synapses=edges[:, 2].astype(np.int32),
                            plastic_compartment=edge_compartment)
        atomic_write_json(output / "compartments_metadata.json", mapping.metadata)
        pd.DataFrame(clusters["rows"]).to_csv(output / "mb_compartment_comparison.csv", index=False)
        pd.DataFrame(al_rows).to_csv(output / "al_glomerulus_membership.csv", index=False)
        summary_rows = []
        for label_index, name in enumerate(MB_NAMES):
            types_here = [t for t, a in zip(vectors["types"], clusters["assignment"], strict=True) if a == label_index]
            summary_rows.append({"compartment": name,
                                 "DAN_types": ";".join(t for t in types_here if not t.startswith("MBON")),
                                 "MBON_types": ";".join(t for t in types_here if t.startswith("MBON")),
                                 "KC_count": int(mapping.membership[label_index, vectors["kc_indices"]].sum()),
                                 "KC_MBON_edges": int((edge_compartment == label_index).sum()),
                                 "KC_MBON_synapses": int(edges[edge_compartment == label_index, 2].sum()),
                                 "canonical_identity_supported": any(r["canonical_identity_supported"] for r in clusters["rows"] if r["aligned_compartment"] == name)})
        pd.DataFrame(summary_rows).to_csv(output / "mb_compartments.csv", index=False)
        artifacts = ["compartments.npz", "compartments_metadata.json", "mb_compartment_comparison.csv",
                     "al_glomerulus_membership.csv", "mb_compartments.csv"]
        # Recheck actual inputs after assembly so concurrent edits cannot produce a valid mixed artifact.
        require_source_gate(root)
        for field, prefix in (("config_hashes", root / "config"), ("implementation_hashes", root),
                              ("dependency_hashes", root), ("neuropil_source_hashes", root)):
            for name, digest in result[field].items():
                check(f"unchanged_{field}_{name}", checksum(prefix / name), digest)
        result["artifact_hashes"] = {name: checksum(output / name) for name in artifacts}
    except Exception as exc:
        check("compartment_stage_execution", {"type": type(exc).__name__, "error": str(exc)}, "no errors")
    result["status"] = "PASS" if result["checks"] and all(c["status"] == "PASS" for c in result["checks"]) else "FAIL"
    result["failed_checks"] = [c["name"] for c in result["checks"] if c["status"] == "FAIL"]
    atomic_write_json(output / "validation_neuromod_compartments.json", result)
    return result


def load_compartments(root: Path, *, verify: bool = True) -> CompartmentMap:
    root = Path(root).resolve()
    output = root / "build"
    result = json.loads((output / "validation_neuromod_compartments.json").read_text())
    if result.get("status") != "PASS" or result.get("failed_checks") or not result.get("checks"):
        raise ValueError("Compartment stage is not PASS")
    if any(c.get("status") != "PASS" for c in result["checks"]):
        raise ValueError("Compartment check evidence is incomplete")
    if verify:
        require_source_gate(root)
        for field, base in (("artifact_hashes", output), ("config_hashes", root / "config"),
                            ("implementation_hashes", root), ("dependency_hashes", root),
                            ("neuropil_source_hashes", root)):
            if not result.get(field):
                raise ValueError(f"Missing compartment provenance: {field}")
            for name, digest in result[field].items():
                if checksum(base / name) != digest:
                    raise ValueError(f"Compartment input/artifact changed: {name}")
    with np.load(output / "compartments.npz", allow_pickle=False) as archive:
        names = tuple(archive["names"].tolist())
        membership = archive["membership"]
        adjacency = archive["adjacency"]
        assignment = archive["mb_assignment"]
        roots = archive["model_root_ids"]
    if membership.shape != (len(names), len(roots)) or membership.dtype != bool:
        raise ValueError("Invalid compartment membership array")
    if adjacency.shape != (len(names), len(names)) or not np.isfinite(adjacency).all() or np.any(adjacency < 0):
        raise ValueError("Invalid compartment adjacency array")
    if assignment.shape != roots.shape or roots.dtype != np.int64 or len(set(names)) != len(names):
        raise ValueError("Invalid model ordering or duplicate compartment names")
    return CompartmentMap(names, membership, adjacency, assignment, roots,
                          json.loads((output / "compartments_metadata.json").read_text()))
