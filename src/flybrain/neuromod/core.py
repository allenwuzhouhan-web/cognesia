"""Verified core extraction and a narrowly scoped zero-input prerequisite.

This module reuses the base engine. It is neither a modulated real-time engine
nor a claim that a resting equilibrium remains stable under sensory drive.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

from ..build import load_network
from ..config import parameters
from ..engine import LIFEngine
from ..fetch import checksum
from ..inspect_data import atomic_write_json
from .sources import require_source_gate


@dataclass
class CoreNetwork:
    neurons: pd.DataFrame
    model_indices: np.ndarray
    counts: sparse.csr_matrix
    metadata: dict


def prepare_core_counts(matrix, kc_mask, kc_kc_mode="thresholded"):
    """Apply explicit KC cholinergic signs and the requested KC recurrence policy."""
    if kc_kc_mode not in {"off", "as_released", "thresholded"}:
        raise ValueError("kc_kc_mode must be off, as_released or thresholded")
    matrix = sparse.csr_matrix(matrix, dtype=np.float32, copy=True)
    kc_mask = np.asarray(kc_mask)
    if kc_mask.dtype != bool or kc_mask.shape != (matrix.shape[0],) or matrix.shape[0] != matrix.shape[1]:
        raise ValueError("KC mask must match the square matrix")
    if not np.isfinite(matrix.data).all():
        raise ValueError("Nonfinite synaptic counts")
    matrix.sum_duplicates()
    matrix.sort_indices()
    rows = np.repeat(np.arange(matrix.shape[0]), np.diff(matrix.indptr))
    kc_pre = kc_mask[matrix.indices]
    corrected = kc_pre & (matrix.data < 0)
    n_corrected = int(corrected.sum())
    matrix.data[kc_pre] = np.abs(matrix.data[kc_pre])
    recurrence = kc_pre & kc_mask[rows]
    remove = recurrence if kc_kc_mode == "off" else recurrence & (matrix.data < 2) if kc_kc_mode == "thresholded" else np.zeros(matrix.nnz, bool)
    metadata = {"kc_kc_mode": kc_kc_mode, "released_edges": int(matrix.nnz),
                "KC_fast_sign_corrected_edges": n_corrected,
                "removed_KC_KC_edges": int(remove.sum()),
                "removed_KC_KC_synapses": int(np.abs(matrix.data[remove]).sum())}
    matrix.data[remove] = 0
    matrix.eliminate_zeros()
    metadata["effective_edges"] = int(matrix.nnz)
    return matrix, metadata


def load_core(root: Path, *, kc_kc_mode="thresholded") -> CoreNetwork:
    root = Path(root)
    source = require_source_gate(root)
    network = load_network(root)
    inventory = pd.read_parquet(root / "build/neuromod_core_diagnostic.parquet")
    indices = inventory.model_index.to_numpy(dtype=np.int32)
    neurons = network["neurons"].iloc[indices].reset_index(drop=True)
    if not np.array_equal(inventory.root_id, neurons.root_id):
        raise ValueError("Core row ordering differs from verified base")
    if neurons.is_graded.any():
        raise ValueError("Current core implementation requires the verified all-spiking core; graded members need an unclamped hybrid path")
    matrix = network["spiking"][indices][:, indices].tocsr()
    if matrix.nnz != source["core"]["edges"] or network["graded"][indices][:, indices].nnz:
        raise ValueError("Core sparse edge count differs from the verified released census")
    kc = neurons.cell_type.fillna("").str.startswith("KC").to_numpy(bool)
    counts, metadata = prepare_core_counts(matrix, kc, kc_kc_mode)
    metadata.update({"neurons": len(neurons), "mode": "all_spiking",
                     "source_validation_sha256": checksum(root / "build/validation_neuromod_sources.json"),
                     "base_artifact_hashes": source["base_artifact_hashes"]})
    return CoreNetwork(neurons, indices, counts, metadata)


def saved_wholebrain_rates(root: Path, neurons: pd.DataFrame) -> dict:
    """Recover rates of the failed base run from hashed recordings; do not rerun."""
    document = json.loads((root / "build/validation_hybrid.json").read_text())
    gate = next(g for g in document["gates"] if g["gate"] == "V-C")
    equilibration = gate["equilibration"]
    recording = root / equilibration["evidence"]
    manifest = json.loads((recording / "run_manifest.json").read_text())
    for name, key in (("activity.npz", "output_sha256"), ("endpoint_state.npz", "endpoint_state_sha256")):
        if checksum(recording / name) != manifest[key]:
            raise ValueError(f"Saved whole-brain evidence changed: {name}")
    with np.load(recording / "activity.npz", allow_pickle=False) as data:
        counts = np.bincount(data["spike_indices"], minlength=len(neurons))
    with np.load(recording / "endpoint_state.npz", allow_pickle=False) as data:
        if not np.array_equal(data["root_ids"], neurons.root_id):
            raise ValueError("Saved whole-brain row order changed")
        dvdt, clamps = data["final_dvdt"].copy(), data["per_neuron_clamp_counts"].copy()
    rows = neurons[["cell_type", "super_class", "mode"]].copy()
    rows["rate_hz"] = counts / (equilibration["duration_ms"] / 1000)
    rows["spikes"] = counts
    rows["unstable"] = ~np.isfinite(dvdt) | (np.abs(dvdt) > parameters(root)["stationary_tolerance"])
    rows["clamps"] = clamps
    rows["abs_dvdt"] = np.abs(dvdt)
    grouped = rows.groupby(["cell_type", "super_class", "mode"], dropna=False).agg(
        neurons=("rate_hz", "size"), unstable_neurons=("unstable", "sum"),
        spikes=("spikes", "sum"), mean_rate_hz=("rate_hz", "mean"),
        max_rate_hz=("rate_hz", "max"), clamp_events=("clamps", "sum"),
        max_abs_dvdt_mV_per_ms=("abs_dvdt", "max")).reset_index()
    failing = grouped[(grouped.unstable_neurons > 0) | (grouped.clamp_events > 0)]
    target = root / "build/neuromod_wholebrain_failed_types.csv"
    failing.to_csv(target, index=False)
    return {"status": gate["status"], "rerun": False, "evidence": str(recording.relative_to(root)),
            "max_abs_dvdt_mV_per_ms": equilibration["max_abs_dvdt_mV_per_ms"],
            "unstable_neurons": int(rows.unstable.sum()), "clamp_events": int(clamps.sum()),
            "spikes": int(counts.sum()), "failed_type_groups": len(failing),
            "per_type_rates_file": str(target.relative_to(root)),
            "dependency_hashes": {str((recording / name).relative_to(root)): checksum(recording / name)
                                  for name in ("activity.npz", "endpoint_state.npz", "run_manifest.json")}}


def validate_core_stationarity(root: Path) -> dict:
    root = Path(root).resolve()
    result = {"gate": "V-NM-CORE", "status": "FAIL", "created_at": datetime.now(timezone.utc).isoformat(),
              "checks": [], "scope": "Zero-input equilibrium from base resting initialization, not driven/recurrent stability or a real-time benchmark"}
    def check(name, observed, expected):
        result["checks"].append({"name": name, "observed": observed, "expected": expected,
                                  "status": "PASS" if observed == expected else "FAIL"})
    try:
        source = require_source_gate(root)
        result["source_hashes"], result["source_stats"] = source["source_hashes"], source["source_stats"]
        result["base_artifact_hashes"] = source["base_artifact_hashes"]
        result["base_config_hashes"] = source["base_config_hashes"]
        result["config_hashes"] = {name: checksum(root / "config" / name) for name in ("parameters.yaml", "neuromod.yaml")}
        result["implementation_hashes"] = {name: checksum(root / name) for name in (
            "src/flybrain/engine.py", "src/flybrain/neuromod/core.py", "src/flybrain/neuromod/sources.py")}
        result["dependency_hashes"] = {"build/validation_neuromod_sources.json": checksum(root / "build/validation_neuromod_sources.json")}
        result["wholebrain_comparison"] = saved_wholebrain_rates(root, pd.read_parquet(root / "build/neurons.parquet"))
        result["dependency_hashes"].update(result["wholebrain_comparison"]["dependency_hashes"])
        core = load_core(root, kc_kc_mode="as_released")
        p = parameters(root)
        duration = float(p["pre_equilibration"])
        engine = LIFEngine(core.counts, p, dt=p["dt"], threads=1, clamp=False)
        activity = engine.run(duration, np.empty(0, np.int32), np.empty((0, 2), np.int64), record_indices=[])
        derivative = (p["v_rest"] - engine.v + engine.g) / p["tau_membrane"]
        derivative[engine.step - engine.last_spike < engine.refractory_steps] = 0
        counts = np.bincount(activity["spike_indices"], minlength=len(core.neurons))
        failed = ~np.isfinite(derivative) | (np.abs(derivative) > p["stationary_tolerance"])
        rows = core.neurons[["root_id", "cell_type", "super_class"]].copy()
        rows.insert(0, "model_index", core.model_indices)
        rows["rate_hz"] = counts / (duration / 1000)
        rows["failed_stationarity"] = failed
        rows["abs_dvdt_mV_per_ms"] = np.abs(derivative)
        by_type = rows.groupby("cell_type", dropna=False).agg(
            neurons=("rate_hz", "size"), mean_rate_hz=("rate_hz", "mean"), max_rate_hz=("rate_hz", "max"),
            failed_neurons=("failed_stationarity", "sum"), max_abs_dvdt_mV_per_ms=("abs_dvdt_mV_per_ms", "max")).reset_index()
        by_type.to_csv(root / "build/neuromod_core_rates.csv", index=False)
        np.savez_compressed(root / "build/neuromod_core_endpoint.npz", root_ids=core.neurons.root_id.to_numpy(),
                            final_v=engine.v, final_g=engine.g, final_dvdt=derivative,
                            spike_indices=activity["spike_indices"], spike_times=activity["spike_times"])
        check("completed", bool(activity["completed"]), True)
        check("finite_state", bool(np.isfinite(engine.v).all() and np.isfinite(engine.g).all()), True)
        check("stationary_neurons", int(failed.sum()), 0)
        check("zero_input_spikes", len(activity["spike_indices"]), 0)
        check("clamping_disabled", engine.clamp, False)
        result["metrics"] = {"neurons": len(core.neurons), "edges": int(core.counts.nnz),
                             "duration_ms": duration, "dt_ms": engine.dt, "threads": 1,
                             "max_abs_dvdt_mV_per_ms": float(np.abs(derivative).max()),
                             "tolerance_mV_per_ms": p["stationary_tolerance"], "spikes": len(activity["spike_indices"]),
                             "clamps": 0, "wall_seconds": activity["wall_seconds"]}
        result["failed_cell_types"] = by_type[by_type.failed_neurons > 0].fillna("__UNKNOWN__").to_dict("records")
        result["artifact_hashes"] = {name: checksum(root / "build" / name) for name in (
            "neuromod_core_rates.csv", "neuromod_core_endpoint.npz", "neuromod_wholebrain_failed_types.csv")}
        require_source_gate(root)
        for field, base in (("config_hashes", root / "config"), ("implementation_hashes", root),
                            ("dependency_hashes", root)):
            for name, digest in result[field].items():
                check(f"unchanged_{field}_{name}", checksum(base / name), digest)
    except Exception as exc:
        check("stationarity_execution", {"type": type(exc).__name__, "error": str(exc)}, "no errors")
    result["status"] = "PASS" if result["checks"] and all(c["status"] == "PASS" for c in result["checks"]) else "FAIL"
    result["failed_checks"] = [c["name"] for c in result["checks"] if c["status"] == "FAIL"]
    atomic_write_json(root / "build/validation_neuromod_core.json", result)
    return result
