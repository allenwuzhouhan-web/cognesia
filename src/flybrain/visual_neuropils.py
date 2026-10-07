"""Real neuropil-weighted membrane-voltage views for the visual simulator.

Each neuron contributes according to the fraction of its annotated presynaptic
and postsynaptic endpoint counts in each neuropil. Region traces are weighted
MEAN membrane voltages, not spike rates, calcium signals, or validation results.
The large raw tables are streamed by Arrow record batch; root IDs stay int64.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from scipy import sparse

from .fetch import checksum
from .inspect_data import atomic_write_json, stat_signature
from .memguard import check_memory


CACHE_VERSION = 1
WEIGHTING = "synapsefractionweightedmean membranevoltage"
SOURCE_FILES = {
    "pre": ("per_neuron_neuropil_count_pre_783.feather", "pre_pt_root_id"),
    "post": ("per_neuron_neuropil_count_post_783.feather", "post_pt_root_id"),
}


def _save_sparse_atomic(path: Path, matrix):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".npz", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        sparse.save_npz(temporary, matrix, compressed=True)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_model_roots(path: Path) -> np.ndarray:
    table = pq.read_table(path, columns=["root_id"])
    column = table.column("root_id")
    if column.type != pa.int64() or column.null_count:
        raise ValueError("Model root_id must contain non-null exact int64 IDs")
    roots = column.combine_chunks().to_numpy()
    if not len(roots) or len(np.unique(roots)) != len(roots):
        raise ValueError("Model root_id must be nonempty and unique")
    return roots


def _aggregate_counts(root: Path, roots: np.ndarray):
    """Stream all rows, keeping only exact model root matches, without floats."""
    sorted_to_model = np.argsort(roots)
    sorted_roots = roots[sorted_to_model]
    vectors = {}
    file_stats = {}
    for part, (filename, root_column) in SOURCE_FILES.items():
        stats = {"rows": 0, "matched_rows": 0, "excluded_rows": 0,
                 "all_endpoint_count": 0, "model_endpoint_count": 0,
                 "excluded_endpoint_count": 0, "record_batches": 0}
        with pa.memory_map(str(root / "data/raw" / filename), "r") as source:
            reader = pa.ipc.open_file(source)
            expected = pa.schema([(root_column, pa.int64()), ("neuropil", pa.string()), ("count", pa.int64())])
            if not reader.schema.equals(expected, check_metadata=False):
                raise ValueError(f"Unexpected neuropil source schema: {filename}: {reader.schema}")
            stats["schema"] = str(reader.schema.remove_metadata())
            for batch_number in range(reader.num_record_batches):
                check_memory()
                batch = reader.get_batch(batch_number)
                if any(column.null_count for column in batch.columns):
                    raise ValueError(f"Null source value in {filename}, batch {batch_number}")
                ids = batch.column(root_column).to_numpy()
                counts = batch.column("count").to_numpy()
                if np.any(counts < 0):
                    raise ValueError(f"Negative endpoint count in {filename}")
                encoded = pc.dictionary_encode(batch.column("neuropil"))
                names = encoded.dictionary.to_pylist()
                if any(not isinstance(name, str) or not name for name in names):
                    raise ValueError(f"Empty neuropil name in {filename}")
                codes = encoded.indices.to_numpy()
                positions = np.searchsorted(sorted_roots, ids)
                matched = positions < len(roots)
                matched[matched] &= sorted_roots[positions[matched]] == ids[matched]
                matched_indices = sorted_to_model[positions[matched]]
                matched_counts = counts[matched]
                matched_codes = codes[matched]
                for code, name in enumerate(names):
                    if name not in vectors:
                        vectors[name] = np.zeros(len(roots), dtype=np.int64)
                    select = matched_codes == code
                    np.add.at(vectors[name], matched_indices[select], matched_counts[select])
                all_count = int(counts.sum(dtype=np.int64))
                model_count = int(matched_counts.sum(dtype=np.int64))
                stats["rows"] += batch.num_rows
                stats["matched_rows"] += int(matched.sum())
                stats["excluded_rows"] += int((~matched).sum())
                stats["all_endpoint_count"] += all_count
                stats["model_endpoint_count"] += model_count
                stats["excluded_endpoint_count"] += all_count - model_count
                stats["record_batches"] += 1
        file_stats[part] = stats
    names = sorted(vectors)
    counts = sparse.vstack([sparse.csr_matrix(vectors[name][None, :]) for name in names], format="csr")
    if not names:
        raise ValueError("No neuropil names found in source tables")
    return names, counts, file_stats


def load_neuropil_weights(root: Path, *, force=False) -> dict:
    """Build/load a source-bound neuropil-by-neuron CSR fraction matrix.

    Cache reuse checks immutable identities and file stat signatures, avoiding
    repeated scans of 43 million rows. A changed source rebuilds from real data.
    Actual content SHA-256 is recorded whenever a cache is constructed.
    """
    root = Path(root)
    build = root / "build"
    metadata_path = build / "visual_neuropil_weights.json"
    weights_path = build / "visual_neuropil_weights.npz"
    counts_path = build / "visual_neuropil_counts.npz"
    input_paths = {"build/neurons.parquet": build / "neurons.parquet"}
    input_paths.update({"data/raw/" + filename: root / "data/raw" / filename for filename, _ in SOURCE_FILES.values()})
    input_stats = {name: stat_signature(path) for name, path in input_paths.items()}
    if not force and metadata_path.exists() and weights_path.exists() and counts_path.exists():
        metadata = json.loads(metadata_path.read_text())
        if metadata.get("cache_version") == CACHE_VERSION and metadata.get("source_stats") == input_stats:
            for path in (weights_path, counts_path):
                if checksum(path) != metadata["output_sha256"][path.name]:
                    raise ValueError(f"Neuropil cache changed: {path.name}; explicit rebuild required")
            weights = sparse.load_npz(weights_path).tocsr()
            return {"weights": weights, "metadata": metadata, "names": metadata["neuropils"], "cache_hit": True}

    started = time.perf_counter()
    source_hashes = {name: checksum(path) for name, path in input_paths.items()}
    roots = _read_model_roots(build / "neurons.parquet")
    names, counts, file_stats = _aggregate_counts(root, roots)
    per_neuron = np.asarray(counts.sum(axis=0), dtype=np.int64).ravel()
    covered = per_neuron > 0
    inverse = np.zeros(len(roots), dtype=np.float64)
    inverse[covered] = 1.0 / per_neuron[covered]
    weights = counts.astype(np.float64).multiply(inverse[None, :]).tocsr()
    weights.eliminate_zeros()
    column_sums = np.asarray(weights.sum(axis=0)).ravel()
    error = float(np.max(np.abs(column_sums[covered] - 1))) if covered.any() else 0.
    if error > 1e-12 or np.any(column_sums[~covered] != 0):
        raise ValueError("Neuropil fractions do not normalize per neuron")
    matrix_count = int(counts.sum(dtype=np.int64))
    expected_count = sum(stats["model_endpoint_count"] for stats in file_stats.values())
    if matrix_count != expected_count:
        raise ValueError("Aggregated endpoint count does not match streamed totals")
    if {name: stat_signature(path) for name, path in input_paths.items()} != input_stats:
        raise ValueError("A neuropil input changed during aggregation; cache was not saved")
    check_memory()
    _save_sparse_atomic(counts_path, counts)
    _save_sparse_atomic(weights_path, weights)
    denominators = np.asarray(weights.sum(axis=1)).ravel()
    metadata = {
        "cache_version": CACHE_VERSION, "n_neurons": len(roots), "n_neuropils": len(names),
        "neuropils": names, "matrix_shape": list(weights.shape), "nnz": weights.nnz,
        "unassigned_source_labels": [name for name in names if name == "None"],
        "weighting": WEIGHTING,
        "definition": "(pre+post endpoint count in neuropil)/(all pre+post endpoint counts for neuron); region mean divides weighted voltage sum by region weight sum",
        "units": "mV", "interpretation": "weighted mean membrane voltage; not spike rate, calcium, or biological validation",
        "missing_weight_neurons": int((~covered).sum()),
        "missing_weight_indices": np.flatnonzero(~covered).tolist(),
        "missing_weight_root_ids": [str(value) for value in roots[~covered]],
        "covered_neurons": int(covered.sum()), "max_column_normalization_error": error,
        "model_pre_plus_post_endpoint_count": matrix_count, "source_measurements": file_stats,
        "area_endpoint_counts": np.asarray(counts.sum(axis=1), dtype=np.int64).ravel().tolist(),
        "area_weight_sums": denominators.tolist(),
        "area_neuron_counts": np.diff(weights.indptr).tolist(),
        "source_sha256": source_hashes, "source_stats": input_stats,
        "output_sha256": {path.name: checksum(path) for path in (weights_path, counts_path)},
        "build_wall_seconds": time.perf_counter() - started,
    }
    atomic_write_json(metadata_path, metadata)
    return {"weights": weights, "metadata": metadata, "names": names, "cache_hit": False}


def neuropil_traces(root, raw_mv: np.ndarray, baseline_mv) -> list[dict]:
    """Return actual area-weighted voltage means and their baseline differences.

    raw_mv must cover every model neuron in build table order. Baseline may be
    scalar, [neurons], or [frames,neurons]. Nonfinite values are rejected rather
    than silently varying the population or denominator between frames.
    """
    package = load_neuropil_weights(Path(root))
    weights, metadata = package["weights"], package["metadata"]
    raw = np.asarray(raw_mv)
    if raw.ndim != 2 or raw.shape[1] != weights.shape[1] or not np.isfinite(raw).all():
        raise ValueError("raw_mv must be finite [frames, all model neurons] in model index order")
    baseline = np.asarray(baseline_mv)
    if baseline.ndim == 0:
        if not np.isfinite(baseline):
            raise ValueError("baseline_mv must be finite")
    elif baseline.shape not in {(raw.shape[1],), raw.shape} or not np.isfinite(baseline).all():
        raise ValueError("baseline_mv must be scalar, [neurons], or [frames,neurons], with finite values")
    denominators = np.asarray(metadata["area_weight_sums"], dtype=np.float64)
    raw_means = np.asarray(weights @ raw.T, dtype=np.float64)
    good = denominators > 0
    raw_means[good] /= denominators[good, None]
    if baseline.ndim == 0:
        baseline_means = np.full(raw_means.shape, float(baseline), dtype=np.float64)
    elif baseline.ndim == 1:
        means = np.asarray(weights @ baseline, dtype=np.float64)
        means[good] /= denominators[good]
        baseline_means = np.broadcast_to(means[:, None], raw_means.shape)
    else:
        baseline_means = np.asarray(weights @ baseline.T, dtype=np.float64)
        baseline_means[good] /= denominators[good, None]
    traces = []
    for area, name in enumerate(package["names"]):
        n = metadata["area_neuron_counts"][area]
        traces.append({
            "name": name, "n_recorded": n, "n_total": n,
            "display_name": "Unassigned (source label: None)" if name == "None" else name,
            "is_unassigned": name == "None",
            "raw_mv": raw_means[area].tolist() if good[area] else [None] * len(raw),
            "baseline_mv": baseline_means[area].tolist() if good[area] else [None] * len(raw),
            "delta_mv": (raw_means[area] - baseline_means[area]).tolist() if good[area] else [None] * len(raw),
            "weighting": WEIGHTING, "weight_sum": float(denominators[area]),
            "endpoint_count": metadata["area_endpoint_counts"][area],
            "units": "mV", "statistic": "weighted mean membrane voltage",
            "not_spike_rate": True, "biological_validation": False,
            "coverage": "all finite model-neuron voltages; neurons without neuropil endpoint counts have no region weight",
            "missing_weight_neurons_global": metadata["missing_weight_neurons"],
        })
    return traces
