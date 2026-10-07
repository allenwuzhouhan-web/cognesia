"""Exact V-A checks against the supplied, unmodified FlyWire release facts.

The large connectivity table is read in batches.  Root IDs remain int64 (never
float64): adjacent IDs at this magnitude cannot be distinguished by a float.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .memguard import check_memory
from .fetch import checksum, stat_signature


CONNECTIVITY_COLUMNS = [
    "Presynaptic_ID", "Postsynaptic_ID", "Presynaptic_Index",
    "Postsynaptic_Index", "Connectivity", "Excitatory",
    "Excitatory x Connectivity",
]
ANNOTATION_REQUIRED_COLUMNS = [
    "root_id", "super_class", "cell_class", "cell_sub_class", "cell_type",
    "top_nt", "top_nt_conf", "side", "vfb_id",
]
EXPECTED_SUPER_CLASSES = {
    "optic": 77_530, "central": 32_379, "sensory": 16_352,
    "visual_projection": 8_038, "ascending": 1_736, "descending": 1_299,
    "sensory_ascending": 581, "visual_centrifugal": 524, "motor": 110,
    "endocrine": 76, "missing": 14,
}
EXPECTED_CELL_COUNTS = {
    "R1-6": {"left": 4_044, "right": 3_888},
    "R7": {"left": 668, "right": 668},
    "R8": {"left": 662, "right": 652},
    "L1": {"left": 802, "right": 789},
    "Mi1": {"left": 788, "right": 796},
    "T4a-d": {"left": 3_137, "right": 3_104},
    "T5a-d": {"left": 3_009, "right": 2_996},
    "HS family": {"left": 3, "right": 3},
    "VS family": {"left": 16, "right": 16},
    "LPLC2": {"left": 108, "right": 102},
    "DNa02": {"left": 1, "right": 1},
    "DNp01": {"left": 1, "right": 1},
}


def inspect_edge_batch(batch: pa.RecordBatch, root_ids: np.ndarray) -> dict[str, Any]:
    """Measure an edge batch without trusting its bounds or signed weights.

    This helper deliberately reports malformed rows instead of indexing with an
    invalid index.  Callers must check column presence and integer types first.
    Counts are additive across batches, while extrema use min/max reductions.
    """
    arrays = {}
    null_count = 0
    for name in CONNECTIVITY_COLUMNS:
        column = batch.column(batch.schema.get_field_index(name))
        null_count += column.null_count
        # Nulls get a sentinel for diagnostics; any null fails independently.
        arrays[name] = column.fill_null(-1).to_numpy(zero_copy_only=False)
    n = len(root_ids)
    counts = arrays["Connectivity"]
    signs = arrays["Excitatory"]
    result = {
        "rows": batch.num_rows,
        "null_count": int(null_count),
        "synapse_sum": int(counts.sum(dtype=np.int64)),
        "synapse_min": int(counts.min()) if len(counts) else None,
        "positive_edges": int(np.count_nonzero(signs == 1)),
        "negative_edges": int(np.count_nonzero(signs == -1)),
        "invalid_signs": int(np.count_nonzero((signs != 1) & (signs != -1))),
        "signed_product_mismatches": int(np.count_nonzero(
            arrays["Excitatory x Connectivity"] != signs * counts
        )),
    }
    for prefix in ("Presynaptic", "Postsynaptic"):
        index = arrays[f"{prefix}_Index"]
        valid = (index >= 0) & (index < n)
        result[f"{prefix}_index_min"] = int(index.min()) if len(index) else None
        result[f"{prefix}_index_max"] = int(index.max()) if len(index) else None
        result[f"{prefix}_out_of_bounds"] = int(np.count_nonzero(~valid))
        result[f"{prefix}_root_mismatches"] = int(np.count_nonzero(
            arrays[f"{prefix}_ID"][valid] != root_ids[index[valid]]
        ))
    return result


def _cell_mask(cells: pd.Series, label: str) -> pd.Series:
    if label in ("T4a-d", "T5a-d"):
        return cells.isin([label[:2] + suffix for suffix in "abcd"])
    if label == "HS family":
        return cells.str.startswith("HS", na=False)
    if label == "VS family":
        return cells.str.startswith("VS", na=False)
    return cells.eq(label).fillna(False)


def validate_data(root: Path) -> dict[str, Any]:
    """Run all V-A release assertions and always save a durable result.

    A FAIL return prevents later stages; assertions are never altered in
    response to the downloaded values. I/O/schema errors are recorded as FAIL.
    """
    root = Path(root).resolve()
    raw = root / "data" / "raw"
    checks: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "gate": "V-A", "status": "FAIL", "checks": checks,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "BUILD_BRIEF.md sections 2.1, 2.2, 3.1, and 6",
        "notes": [
            "The Parquet pandas index is physical storage metadata, not an eighth data column.",
            "HS / VS row is interpreted as HS = 3 left + 3 right and VS = 16 left + 16 right. "
            "Its two table cells describe families rather than the stated left/right headers. "
            "VS family includes VS1-8, VST1, VST2 and VSm; member counts are reported below.",
        ],
    }

    def check(name: str, observed: Any, expected: Any, *, passed: bool | None = None) -> bool:
        ok = observed == expected if passed is None else passed
        checks.append({"name": name, "status": "PASS" if ok else "FAIL",
                       "observed": observed, "expected": expected})
        print(f"[V-A {'PASS' if ok else 'FAIL'}] {name}: {observed!r}; expected {expected!r}")
        return bool(ok)

    def run_checks() -> None:
        files = ["Completeness_783.csv", "Connectivity_783.parquet",
                 "Supplemental_file1_neuron_annotations.tsv"]
        manifest_path = root / "build" / "downloads.json"
        manifest = json.loads(manifest_path.read_text()).get("files", {}) if manifest_path.exists() else {}
        result["source_stats"] = {name: stat_signature(raw / name) for name in files}
        result["source_hashes"] = {name: checksum(raw / name) for name in files}
        for name in files:
            if name in manifest:
                check(f"source_manifest_sha256_{name}", result["source_hashes"][name], manifest[name]["sha256"])
        completeness = pd.read_csv(raw / "Completeness_783.csv")
        annotations = pd.read_csv(raw / "Supplemental_file1_neuron_annotations.tsv",
                                  sep="\t", low_memory=False)
        parquet = pq.ParquetFile(raw / "Connectivity_783.parquet")
        check("completeness_rows", len(completeness), 138_639)
        check("completeness_columns", list(completeness.columns), ["Unnamed: 0", "Completed"])
        check("annotations_rows", len(annotations), 139_248)
        check("annotations_column_count", len(annotations.columns), 31)
        ann_columns_ok = check("annotations_required_columns",
                              sorted(set(ANNOTATION_REQUIRED_COLUMNS) - set(annotations.columns)), [])
        check("connectivity_rows", parquet.metadata.num_rows, 15_091_983)
        metadata = parquet.schema_arrow.metadata or {}
        pandas_metadata = json.loads(metadata.get(b"pandas", b"{}"))
        index_columns = [x for x in pandas_metadata.get("index_columns", []) if isinstance(x, str)]
        result["parquet_stored_index_columns"] = index_columns
        logical_columns = [x for x in parquet.schema_arrow.names if x not in index_columns]
        connectivity_columns_ok = check("connectivity_data_columns", logical_columns, CONNECTIVITY_COLUMNS)
        types = {name: str(parquet.schema_arrow.field(name).type)
                 for name in CONNECTIVITY_COLUMNS if name in parquet.schema_arrow.names}
        connectivity_types_ok = check("connectivity_column_dtypes", types,
                                      {name: "int64" for name in CONNECTIVITY_COLUMNS})
        if "Unnamed: 0" not in completeness or not ann_columns_ok:
            return
        root_series = completeness["Unnamed: 0"]
        root_type_ok = check("completeness_root_dtype", str(root_series.dtype), "int64")
        check("completeness_root_nulls", int(root_series.isna().sum()), 0)
        check("completeness_duplicate_roots", int(root_series.duplicated().sum()), 0)
        check("annotation_root_dtype", str(annotations.root_id.dtype), "int64")
        check("annotation_root_nulls", int(annotations.root_id.isna().sum()), 0)
        unique_annotations = check("annotation_duplicate_roots", int(annotations.root_id.duplicated().sum()), 0)
        if unique_annotations:
            neurons = completeness.rename(columns={"Unnamed: 0": "root_id"}).merge(
                annotations, how="left", on="root_id", sort=False, validate="many_to_one")
            check("joined_neuron_rows", len(neurons), 138_639)
            check("joined_root_order_preserved", bool(np.array_equal(neurons.root_id, root_series)), True)
            class_counts = neurons.super_class.fillna("missing").value_counts().to_dict()
            check("super_class_counts", class_counts, EXPECTED_SUPER_CLASSES)
            for label, expected_counts in EXPECTED_CELL_COUNTS.items():
                mask = _cell_mask(neurons.cell_type, label)
                counts = neurons.loc[mask, "side"].fillna("missing").value_counts().to_dict()
                check(f"cell_counts_{label}", counts, expected_counts)
            for label in ("R7", "R8"):
                check(f"DRA_{label}", int((neurons.cell_type.eq(label)
                                          & neurons.cell_sub_class.eq("DRA")).sum()), 77)
            check("ocellar_afferents", int(neurons.cell_sub_class.eq("ocellar").sum()), 273)
            widefield = neurons[_cell_mask(neurons.cell_type, "HS family")
                                | _cell_mask(neurons.cell_type, "VS family")]
            result["widefield_family_members"] = [
                {"cell_type": str(cell_type), "side": str(side), "count": int(count)}
                for (cell_type, side), count in widefield.groupby(["cell_type", "side"]).size().items()
            ]
        if not (connectivity_columns_ok and connectivity_types_ok and root_type_ok):
            return
        roots = root_series.to_numpy(dtype=np.int64)
        totals: dict[str, int | None] = {}
        out_synapses = np.zeros(len(roots), dtype=np.int64)
        for batch in parquet.iter_batches(batch_size=262_144, columns=CONNECTIVITY_COLUMNS):
            check_memory()
            measured = inspect_edge_batch(batch, roots)
            for name, value in measured.items():
                if value is None:
                    continue
                if name.endswith("_min"):
                    totals[name] = min(totals.get(name, value), value)
                elif name.endswith("_max"):
                    totals[name] = max(totals.get(name, value), value)
                else:
                    totals[name] = totals.get(name, 0) + value
            pre = batch.column("Presynaptic_Index").fill_null(-1).to_numpy()
            weights = batch.column("Connectivity").fill_null(0).to_numpy()
            valid = (pre >= 0) & (pre < len(roots))
            np.add.at(out_synapses, pre[valid], weights[valid])
        result["edge_measurements"] = totals
        for name, expected in {
            "rows": 15_091_983, "null_count": 0, "synapse_sum": 54_492_922,
            "synapse_min": 1, "positive_edges": 9_059_302,
            "negative_edges": 6_032_681, "invalid_signs": 0,
            "signed_product_mismatches": 0,
        }.items():
            check(f"edges_{name}", totals.get(name), expected)
        for prefix in ("Presynaptic", "Postsynaptic"):
            check(f"{prefix}_out_of_bounds", totals.get(f"{prefix}_out_of_bounds"), 0)
            check(f"{prefix}_index_range", {
                "min": totals.get(f"{prefix}_index_min"),
                "max": totals.get(f"{prefix}_index_max"),
            }, f"0 <= index < {len(roots)}", passed=(
                totals.get(f"{prefix}_index_min", -1) >= 0
                and totals.get(f"{prefix}_index_max", len(roots)) < len(roots)))
            check(f"{prefix}_root_order_alignment", totals.get(f"{prefix}_root_mismatches"), 0)
        if unique_annotations:
            for label, expected_median in {
                "R1-6": 19, "R7": 20, "R8": 18, "L1": 285,
                "Mi1": 973, "T4a-d": 137, "T5a-d": 147,
            }.items():
                selected = out_synapses[_cell_mask(neurons.cell_type, label).to_numpy(dtype=bool)]
                median = float(np.median(selected)) if len(selected) else None
                check(f"median_output_synapses_{label}", median, expected_median)
            r16 = _cell_mask(neurons.cell_type, "R1-6").to_numpy(dtype=bool)
            check("R1-6_zero_output_neurons", int(np.count_nonzero(out_synapses[r16] == 0)), 277)

    try:
        run_checks()
        for name, before in result.get("source_stats", {}).items():
            check(f"source_unchanged_{name}", stat_signature(raw / name), before)
    except Exception as exc:
        check("validation_execution", {"error_type": type(exc).__name__, "error": str(exc)}, "no errors")
    result["status"] = "PASS" if checks and all(x["status"] == "PASS" for x in checks) else "FAIL"
    result["failed_checks"] = [x["name"] for x in checks if x["status"] == "FAIL"]
    destination = root / "build" / "validation_data.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    temporary.replace(destination)
    return result
