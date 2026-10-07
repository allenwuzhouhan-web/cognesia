"""Actual-core odour sparseness experiment, separate from software certification.

No weights, gains, damping or clamps are adjusted to reach the biological target.
A fixed protocol is measured once on the existing LIF engine and connectome.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from ..config import parameters
from ..engine import LIFEngine
from ..fetch import checksum, stat_signature
from ..inspect_data import atomic_write_json
from .core import load_core
from .odour import BASELINE_NOTE, OdourEventSampler, OdourLibrary, OdourTransduction, read_odour_parameters
from .sources import require_source_gate

PROTOCOL = {
    "schema_version": 1, "source": "ASSUMPTION", "seed": 783,
    "odours": ["OCT", "MCH"], "baseline_ms": 1000.0,
    "baseline_measurement_ms": 500.0, "stimulus_ms": 1000.0, "recovery_ms": 500.0,
    "intensity": 1.0, "chunk_ms": 100.0, "kc_kc_mode": "thresholded", "threads": 1,
    "clamp": False, "baseline_mode": "source_sfr", "sample_every_integration_step": True,
    "fraction_definition": "Fraction of all core KCs with >=1 actual LIF spike in the full stimulus window",
    "window_rule": "Half-open [start,end); compare final 500 ms of baseline with 1000 ms stimulus",
    "gate_range": [0.02, 0.12], "gate_citation": "PMID:24561998; DOI:10.1038/nn.3660",
    "input_path": "DoOR signed response -> existing odour transduction -> seeded Poisson source events -> unchanged LIF external-input interface -> released core connectivity",
    "input_amplitude": "Unchanged base spike_weight * poisson_factor; no hand-built AL gain",
    "fresh_initialization": "Independent fresh resting LIF engine for each odour, same seed and identical source-SFR baseline prefix",
}


def protocol_hash(protocol: dict) -> str:
    return hashlib.sha256(json.dumps(protocol, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def integer_steps(duration_ms, dt_ms):
    if not np.isfinite(duration_ms) or not np.isfinite(dt_ms) or duration_ms < 0 or dt_ms <= 0:
        raise ValueError("Durations must be finite/nonnegative and dt positive")
    result = int(round(duration_ms / dt_ms))
    if not np.isclose(result * dt_ms, duration_ms, rtol=0, atol=1e-8):
        raise ValueError("Protocol times must be exact multiples of dt")
    return result


def core_orn_indices(model_indices, orn_model_indices):
    """Preserve library ORN order; reject absent or ambiguous core identities."""
    model = np.asarray(model_indices)
    orn = np.asarray(orn_model_indices)
    if model.ndim != 1 or orn.ndim != 1 or len(np.unique(model)) != len(model) or len(np.unique(orn)) != len(orn):
        raise ValueError("Core and ORN indices must be unique one-dimensional arrays")
    lookup = {int(value): index for index, value in enumerate(model)}
    if any(int(value) not in lookup for value in orn):
        raise ValueError("Every normative ORN must be present in the core")
    return np.array([lookup[int(value)] for value in orn], dtype=np.int32)


def source_event_log(library, odour, odour_parameters, dt_ms, protocol=PROTOCOL):
    """Return deterministic source events, not predeclared network spikes."""
    if odour_parameters["odour_baseline_mode"] != "source_sfr":
        raise ValueError("This fixed validation protocol requires source_sfr baseline")
    onset = integer_steps(protocol["baseline_ms"], dt_ms)
    offset = onset + integer_steps(protocol["stimulus_ms"], dt_ms)
    total = offset + integer_steps(protocol["recovery_ms"], dt_ms)
    stride = max(1, integer_steps(protocol["chunk_ms"], dt_ms))
    transduction = OdourTransduction(library, odour_parameters)
    rng = OdourEventSampler(protocol["seed"])
    parts, sampled_rates, sampled_times = [], [], []
    for step in range(total):
        active = onset <= step < offset
        rates = transduction.step(odour if active else None, protocol["intensity"] if active else 0.0, dt_ms)
        counts = rng.sample(rates, dt_ms)
        indices = np.repeat(np.arange(len(rates), dtype=np.int32), counts)
        if len(indices):
            parts.append(np.column_stack((np.full(len(indices), step, np.int64), indices)))
        if step % stride == 0:
            sampled_times.append(step * dt_ms)
            sampled_rates.append(rates.copy())
    events = np.concatenate(parts) if parts else np.empty((0, 2), np.int64)
    return events, np.asarray(sampled_times), np.asarray(sampled_rates)


def window_counts(spike_indices, spike_times_ms, n_neurons, start_ms, end_ms):
    if end_ms <= start_ms:
        raise ValueError("A measurement window must have positive duration")
    indices, times = np.asarray(spike_indices), np.asarray(spike_times_ms)
    if indices.shape != times.shape or indices.ndim != 1 or np.any((indices < 0) | (indices >= n_neurons)):
        raise ValueError("Invalid actual-spike indices or times")
    if not np.isfinite(times).all():
        raise ValueError("Nonfinite actual-spike time")
    selected = (times >= start_ms) & (times < end_ms)
    counts = np.bincount(indices[selected].astype(int), minlength=n_neurons)
    return counts, counts / ((end_ms - start_ms) / 1000.0)


def voltage_metrics(samples, minimum, maximum):
    """Bounds violations count observed samples, never nonexistent clamp events."""
    values = np.asarray(samples)
    finite = np.isfinite(values)
    bounded = finite & ((values < minimum) | (values > maximum))
    return {"nonfinite_samples": int((~finite).sum()), "out_of_bound_samples": int(bounded.sum()),
            "out_of_bound_counts": bounded.sum(axis=0).astype(np.int64),
            "nonfinite_counts": (~finite).sum(axis=0).astype(np.int64),
            "minimum_sample_mV": float(values[finite].min()) if finite.any() else None,
            "maximum_sample_mV": float(values[finite].max()) if finite.any() else None}


def _trace_indices(neurons):
    cell_types = neurons.cell_type.fillna("")
    masks = [cell_types.str.startswith("ORN_"), neurons.cell_class.eq("ALPN"),
             cell_types.str.startswith("KC"), cell_types.str.startswith("APL"),
             cell_types.str.startswith("MBON"), cell_types.str.startswith(("PAM", "PPL1"))]
    return np.unique(np.concatenate([np.flatnonzero(mask.to_numpy())[:2] for mask in masks])).astype(np.int32)


def run_core_protocol(core, library, odour, base_parameters, odour_parameters, output, protocol=PROTOCOL):
    """Run short streamed chunks; keep every actual spike/event and selected traces."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    p = dict(base_parameters)
    dt = float(p["dt"])
    p["record_dt_ms"] = dt  # recording only: all neuronal dynamics remain unchanged.
    total_ms = protocol["baseline_ms"] + protocol["stimulus_ms"] + protocol["recovery_ms"]
    total_steps = integer_steps(total_ms, dt)
    chunk_steps = integer_steps(protocol["chunk_ms"], dt)
    inputs = core_orn_indices(core.model_indices, library.neuron_indices)
    if not np.array_equal(core.neurons.root_id.to_numpy()[inputs], library.root_ids):
        raise ValueError("Mapped ORN root identities differ between library and core")
    events, rate_times, source_rates = source_event_log(library, odour, odour_parameters, dt, protocol)
    engine = LIFEngine(core.counts, p, dt=dt, threads=protocol["threads"], clamp=False)
    selected = _trace_indices(core.neurons)
    all_indices = np.arange(len(core.neurons), dtype=np.int32)
    spike_parts, time_parts, trace_parts, trace_time_parts, checkpoints = [], [], [], [], []
    out_of_bounds = np.zeros(len(core.neurons), np.int64)
    nonfinite_counts = np.zeros(len(core.neurons), np.int64)
    observed_min, observed_max = np.inf, -np.inf
    wall_seconds = 0.0
    failure = None
    for start in range(0, total_steps, chunk_steps):
        stop = min(start + chunk_steps, total_steps)
        lo, hi = np.searchsorted(events[:, 0], [start, stop])
        local_events = events[lo:hi].copy()
        local_events[:, 0] -= start
        try:
            activity = engine.run((stop - start) * dt, inputs, local_events,
                                  record_indices=all_indices, chunk_ms=(stop - start) * dt)
        except Exception as exc:
            activity = engine.last_result
            failure = f"{type(exc).__name__}: {exc}"
        if activity is None:
            raise RuntimeError(failure or "Engine returned no evidence")
        wall_seconds += activity["wall_seconds"]
        spike_parts.append(activity["spike_indices"])
        time_parts.append(activity["spike_times"])
        samples = activity["voltages"]
        metrics = voltage_metrics(samples, p["voltage_min"], p["voltage_max"])
        out_of_bounds += metrics["out_of_bound_counts"]
        nonfinite_counts += metrics["nonfinite_counts"]
        if metrics["minimum_sample_mV"] is not None:
            observed_min = min(observed_min, metrics["minimum_sample_mV"])
            observed_max = max(observed_max, metrics["maximum_sample_mV"])
        trace_parts.append(samples[:, selected].copy())
        trace_time_parts.append(activity["voltage_times"])
        checkpoints.append({"t_ms": engine.step * dt,
                            "finite_voltage": bool(np.isfinite(engine.v).all()),
                            "finite_synaptic_state": bool(np.isfinite(engine.g).all()),
                            "minimum_v_mV": float(engine.v.min()) if np.isfinite(engine.v).all() else None,
                            "maximum_v_mV": float(engine.v.max()) if np.isfinite(engine.v).all() else None,
                            "maximum_abs_g_mV": float(np.abs(engine.g).max()) if np.isfinite(engine.g).all() else None})
        if failure or not activity["completed"] or not checkpoints[-1]["finite_voltage"] or not checkpoints[-1]["finite_synaptic_state"]:
            failure = failure or "Incomplete/nonfinite driven core state; run stopped and evidence retained"
            break
    spikes = np.concatenate(spike_parts) if spike_parts else np.empty(0, np.int32)
    times = np.concatenate(time_parts) if time_parts else np.empty(0, np.float32)
    onset = protocol["baseline_ms"]
    offset = onset + protocol["stimulus_ms"]
    baseline_counts, baseline_rates = window_counts(spikes, times, len(core.neurons), onset - protocol["baseline_measurement_ms"], onset)
    stimulus_counts, stimulus_rates = window_counts(spikes, times, len(core.neurons), onset, offset)
    recovery_counts, recovery_rates = window_counts(spikes, times, len(core.neurons), offset, total_ms)
    kc = core.neurons.cell_type.fillna("").str.startswith("KC").to_numpy()
    n_kc = int(kc.sum())
    if n_kc == 0:
        raise ValueError("No KCs in core")
    completed = engine.step == total_steps and failure is None
    endpoint_finite = bool(np.isfinite(engine.v).all() and np.isfinite(engine.g).all())
    endpoint_bound_counts = ((engine.v < p["voltage_min"]) | (engine.v > p["voltage_max"])).astype(np.int64)
    within_sample_bounds = not out_of_bounds.any() and not endpoint_bound_counts.any()
    finite = not nonfinite_counts.any() and endpoint_finite
    fraction = float(np.count_nonzero(stimulus_counts[kc]) / n_kc) if completed else None
    baseline_fraction = float(np.count_nonzero(baseline_counts[kc]) / n_kc) if completed else None
    target_met = fraction is not None and protocol["gate_range"][0] <= fraction <= protocol["gate_range"][1]
    row = {"odour": odour, "status": "PASS" if completed and finite and within_sample_bounds and target_met else "FAIL",
           "completed": completed, "failure": failure, "simulated_ms": engine.step * dt,
           "seed": protocol["seed"], "kc_neurons": n_kc, "kc_active_fraction": fraction,
           "baseline_kc_active_fraction": baseline_fraction,
           "kc_fraction_change": fraction - baseline_fraction if completed else None,
           "mean_kc_rate_hz": float(stimulus_rates[kc].mean()) if completed else None,
           "baseline_mean_kc_rate_hz": float(baseline_rates[kc].mean()) if completed else None,
           "max_kc_rate_hz": float(stimulus_rates[kc].max()) if completed else None,
           "max_neuron_rate_hz": float(stimulus_rates.max()) if completed else None,
           "biological_fraction_target_met": target_met,
           "numerics": {"finite_observed_state": bool(finite), "sampled_voltage_bounds_met": bool(within_sample_bounds),
                        "out_of_bound_voltage_samples": int(out_of_bounds.sum()),
                        "neurons_with_out_of_bound_samples": int(np.count_nonzero(out_of_bounds)),
                        "endpoint_out_of_bound_neurons": int(endpoint_bound_counts.sum()),
                        "nonfinite_voltage_samples": int(nonfinite_counts.sum()),
                        "minimum_sample_voltage_mV": float(observed_min) if np.isfinite(observed_min) else None,
                        "maximum_sample_voltage_mV": float(observed_max) if np.isfinite(observed_max) else None,
                        "clamp_enabled": engine.clamp, "clamp_events": int(engine.clamp_count),
                        "sample_dt_ms": dt, "bounds_mV": [p["voltage_min"], p["voltage_max"]],
                        "scope": "Every integration-start voltage plus chunk endpoint states; does not inspect internal pre-reset threshold overshoot, prove equilibrium, or establish general driven stability"},
           "source_event_count": len(events), "network_spike_count": len(spikes),
           "wall_seconds_engine": wall_seconds, "core": core.metadata,
           "coverage": library.responses(odour).metadata,
           "baseline_note": BASELINE_NOTE, "checkpoints": checkpoints}
    prefix = f"odour_sparseness_{odour}"
    table = core.neurons[["root_id", "cell_type", "cell_class", "super_class"]].copy()
    table.insert(0, "model_index", core.model_indices)
    table["protocol_completed"] = completed
    table["baseline_rate_hz"], table["stimulus_rate_hz"], table["recovery_rate_hz"] = baseline_rates, stimulus_rates, recovery_rates
    table["baseline_spikes"], table["stimulus_spikes"], table["recovery_spikes"] = baseline_counts, stimulus_counts, recovery_counts
    table["out_of_bound_samples"], table["nonfinite_samples"] = out_of_bounds, nonfinite_counts
    table.to_csv(output / f"{prefix}_neurons.csv", index=False)
    table.groupby("cell_type", dropna=False).agg(neurons=("root_id", "size"),
        mean_baseline_rate_hz=("baseline_rate_hz", "mean"), mean_stimulus_rate_hz=("stimulus_rate_hz", "mean"),
        max_stimulus_rate_hz=("stimulus_rate_hz", "max"), stimulus_spikes=("stimulus_spikes", "sum"),
        out_of_bound_samples=("out_of_bound_samples", "sum"), nonfinite_samples=("nonfinite_samples", "sum")).reset_index().to_csv(output / f"{prefix}_types.csv", index=False)
    ring_parts = [np.column_stack((np.full(int(count), slot, np.int32),
                                  engine.ring[slot, :int(count)]))
                  for slot, count in enumerate(engine.ring_counts) if count]
    pending_ring = np.concatenate(ring_parts) if ring_parts else np.empty((0, 2), np.int32)
    np.savez_compressed(output / f"{prefix}_activity.npz", root_ids=core.neurons.root_id.to_numpy(),
                        model_indices=core.model_indices, input_core_indices=inputs,
                        input_model_indices=library.neuron_indices, source_events=events,
                        source_rate_times_ms=rate_times, source_rates_hz=source_rates,
                        spike_indices=spikes, spike_times_ms=times,
                        trace_indices=selected, trace_times_ms=np.concatenate(trace_time_parts),
                        trace_voltages_mV=np.concatenate(trace_parts), final_v=engine.v, final_g=engine.g,
                        final_step=np.array(engine.step), last_spike_steps=engine.last_spike,
                        ring_counts=engine.ring_counts, pending_ring_slot_neuron=pending_ring)
    row["artifact_hashes"] = {f"{prefix}{suffix}": checksum(output / f"{prefix}{suffix}")
                              for suffix in ("_neurons.csv", "_types.csv", "_activity.npz")}
    return row


def validate_odour_sparseness(root: Path) -> dict:
    root = Path(root).resolve()
    output = root / "build"
    output.mkdir(parents=True, exist_ok=True)
    result = {"gate": "V-NM-ODSP", "kind": "biology", "status": "NOT-RUN", "software_execution": "FAIL",
              "created_at": datetime.now(timezone.utc).isoformat(), "protocol": PROTOCOL,
              "protocol_sha256": protocol_hash(PROTOCOL), "baseline_note": BASELINE_NOTE,
              "citation": "PMID:24561998; DOI:10.1038/nn.3660", "runs": [], "artifact_hashes": {},
              "limitations": ["No parameter fitted to the sparseness range; no damping, clamp or compensating AL gain",
                              "PASS covers this finite protocol only, not general driven stability or whole-brain validity",
                              "Different baseline and stimulus windows affect any-spike fractions; per-neuron rates are also reported"]}
    atomic_write_json(output / "validation_neuromod_odour_sparseness.json", result)
    started = time.perf_counter()
    try:
        source = require_source_gate(root)
        result["source_hashes"], result["base_artifact_hashes"] = dict(source["source_hashes"]), source["base_artifact_hashes"]
        result["source_stats"] = dict(source["source_stats"])
        result["base_config_hashes"] = source["base_config_hashes"]
        result["config_hashes"] = {name: checksum(root / "config" / name) for name in ("parameters.yaml", "neuromod.yaml")}
        paths = ("src/flybrain/neuromod/odour_validation.py", "src/flybrain/neuromod/odour.py",
                 "src/flybrain/neuromod/core.py", "src/flybrain/engine.py", "src/flybrain/neuromod/sources.py")
        result["implementation_hashes"] = {name: checksum(root / name) for name in paths}
        result["dependency_hashes"] = {name: checksum(root / name) for name in (
            "build/validation_neuromod_sources.json", "build/validation_neuromod_odour.json",
            "build/neuromod_core_diagnostic.parquet")}
        core = load_core(root, kc_kc_mode=PROTOCOL["kc_kc_mode"])
        library = OdourLibrary.from_root(root, download=False)
        if library.mode != "door":
            raise ValueError("Measured ODSP protocol requires actual DoOR responses")
        if len(core.neurons) != 13300 or len(library.neuron_indices) != 2279:
            raise ValueError("Protocol expects the accepted 13,300-neuron core and 2,279 ORNs")
        result["door_source_files"] = library.source_audit
        for name, audit in library.source_audit.items():
            key = "neuromod/door/" + name
            result["source_hashes"][key] = audit["sha256"]
            result["source_stats"][key] = audit["source_stats"]
        p, odor_p = parameters(root), read_odour_parameters(root)
        result["input_amplitude_mV"] = p["spike_weight"] * p["poisson_factor"]
        for name in PROTOCOL["odours"]:
            run = run_core_protocol(core, library, name, p, odor_p, output)
            result["runs"].append(run)
            result["artifact_hashes"].update(run["artifact_hashes"])
        for name, digest in result["config_hashes"].items():
            if checksum(root / "config" / name) != digest:
                raise ValueError(f"Configuration changed during ODSP run: {name}")
        for name, digest in result["implementation_hashes"].items():
            if checksum(root / name) != digest:
                raise ValueError(f"Implementation changed during ODSP run: {name}")
        for name, digest in result["dependency_hashes"].items():
            if checksum(root / name) != digest:
                raise ValueError(f"Dependency changed during ODSP run: {name}")
        for name, digest in result["source_hashes"].items():
            if checksum(root / "data/raw" / name) != digest or stat_signature(root / "data/raw" / name) != result["source_stats"][name]:
                raise ValueError(f"Source changed during ODSP run: {name}")
        require_source_gate(root)
        result["software_execution"] = "PASS" if all(r["completed"] for r in result["runs"]) else "FAIL"
        result["status"] = "PASS" if all(r["status"] == "PASS" for r in result["runs"]) else "FAIL"
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        result["status"] = "FAIL" if result["runs"] else "NOT-RUN"
    result["wall_seconds_total"] = time.perf_counter() - started
    atomic_write_json(output / "validation_neuromod_odour_sparseness.json", result)
    return result
