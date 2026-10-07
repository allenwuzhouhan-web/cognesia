"""Whole-brain stage-4 equilibration and dark-control checks.

Eye-dependent peak-convergence testing is deliberately NOT-RUN at this stage.
No amplitudes, gains, delays, or thresholds are fitted to these observations.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import resource
import time

import numpy as np
import pandas as pd

from .build import load_network
from .config import parameters
from .fetch import checksum, stat_signature
from .inspect_data import atomic_write_json
from .memguard import check_memory
from .record import run_directory, save_run


def _peak_rss_bytes() -> int:
    amount = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(amount if platform.system() == "Darwin" else amount * 1024)


def summarize_endpoint(neurons: pd.DataFrame, dvdt: np.ndarray,
                       per_neuron_clamps: np.ndarray, tolerance: float) -> dict:
    """Describe actual unforced endpoint derivatives without hiding NaNs/clips."""
    dvdt = np.asarray(dvdt, dtype=np.float64)
    clamps = np.asarray(per_neuron_clamps, dtype=np.int64)
    if dvdt.shape != (len(neurons),) or clamps.shape != (len(neurons),):
        raise ValueError("Endpoint derivatives and clamp counts must cover every neuron")
    if np.any(clamps < 0):
        raise ValueError("Clamp counts cannot be negative")
    finite = np.isfinite(dvdt)
    unstable = (~finite) | (np.abs(dvdt) > tolerance)
    table = pd.DataFrame({
        "cell_type": neurons.cell_type.fillna("__MISSING__").to_numpy(),
        "super_class": neurons.super_class.fillna("missing").to_numpy(),
        "mode": neurons["mode"].to_numpy(),
        "unstable": unstable, "clamps": clamps,
        "abs_dvdt": np.where(finite, np.abs(dvdt), np.nan),
    })
    groups = table.groupby(["cell_type", "super_class", "mode"], dropna=False).agg(
        n_neurons=("unstable", "size"), n_unstable=("unstable", "sum"),
        clamp_events=("clamps", "sum"), max_abs_dvdt=("abs_dvdt", "max"))
    noteworthy = groups[(groups.n_unstable > 0) | (groups.clamp_events > 0)]
    records = []
    for (cell_type, super_class, mode), row in noteworthy.iterrows():
        records.append({"cell_type": cell_type, "super_class": super_class, "mode": mode,
                        "n_neurons": int(row.n_neurons), "n_unstable": int(row.n_unstable),
                        "clamp_events": int(row.clamp_events),
                        "max_abs_dvdt_mV_per_ms": float(row.max_abs_dvdt) if np.isfinite(row.max_abs_dvdt) else None})
    records.sort(key=lambda row: (row["n_unstable"], row["clamp_events"]), reverse=True)
    return {
        "stationary": bool(finite.all() and not unstable.any()),
        "max_abs_dvdt_mV_per_ms": float(np.max(np.abs(dvdt))) if finite.all() else None,
        "nonfinite_derivatives": int((~finite).sum()),
        "unstable_neurons": int(unstable.sum()),
        "unstable_by_mode": {mode: int(np.count_nonzero(unstable & (neurons["mode"].to_numpy() == mode)))
                             for mode in ("graded", "spiking")},
        "clamp_events": int(clamps.sum()), "clamped_neurons": int(np.count_nonzero(clamps)),
        "affected_cell_types": records,
    }


def class_spike_counts(neurons: pd.DataFrame, indices: np.ndarray) -> dict[str, int]:
    counts = np.bincount(np.asarray(indices, dtype=np.int32), minlength=len(neurons))
    return {str(name): int(group.sum()) for name, group in
            pd.Series(counts).groupby(neurons.super_class.fillna("missing").to_numpy())}


def _check(name: str, observed, expected, passed: bool) -> dict:
    return {"name": name, "status": "PASS" if passed else "FAIL", "observed": observed, "expected": expected}


def _require_current_reference_gate(root: Path) -> None:
    path = root / "build/validation_engine.json"
    if not path.exists():
        raise ValueError("Stage 4 requires the completed full V-E gate")
    gate = json.loads(path.read_text())
    if gate.get("status") != "PASS" or not gate.get("protocol", {}).get("full_protocol"):
        raise ValueError("Stage 4 requires V-E PASS for the full production protocol")
    for category, base in [("config_hashes", root / "config"), ("implementation_hashes", root)]:
        for name, expected in gate.get(category, {}).items():
            if checksum(base / name) != expected:
                raise ValueError(f"V-E evidence is stale: {name}")
    for name, expected in gate["source_stats"].items():
        if stat_signature(root / "data/raw" / name) != expected:
            raise ValueError(f"V-E source changed: {name}")


def _assert_unchanged(root: Path, binding: dict) -> None:
    for name, expected in binding["source_stats"].items():
        if stat_signature(root / "data/raw" / name) != expected:
            raise ValueError(f"Source changed during hybrid validation: {name}")
    for category, base in [("config_hashes", root / "config"), ("implementation_hashes", root)]:
        for name, expected in binding[category].items():
            if checksum(base / name) != expected:
                raise ValueError(f"Implementation or configuration changed during hybrid validation: {name}")


def _record_phase(root, neurons, result, params, binding, phase):
    directory = run_directory(root, f"hybrid_{phase}")
    manifest = save_run(root, directory, result, config=params | {
        "mode": "hybrid", "lamina_mode": "connectome", "phase": phase,
        "external_input": "none; photoreceptors and every other sensory neuron receive zero external drive",
        "integration_dt_ms": params["dt"],
    }, seed=params["seed"], experiment=f"hybrid_{phase}", peak_rss=_peak_rss_bytes(),
        complete=bool(result.get("completed", True)))
    endpoints = {name: np.asarray(result[name]) for name in (
        "final_v", "final_g", "final_dvdt", "per_neuron_clamp_counts") if name in result}
    endpoints["root_ids"] = neurons.root_id.to_numpy(dtype=np.int64)
    np.savez_compressed(directory / "endpoint_state.npz", **endpoints)
    manifest.update({"validation_binding": binding,
                     "endpoint_state_sha256": checksum(directory / "endpoint_state.npz"),
                     "actual_dt_graded_ms": result.get("actual_dt_graded_ms"),
                     "requested_dt_graded_ms": result.get("requested_dt_graded_ms"),
                     "graded_timestep_note": result.get("graded_timestep_note"),
                     "chunk_timings": result.get("chunk_timings", [])})
    atomic_write_json(directory / "run_manifest.json", manifest)
    return directory


def validate_hybrid(root: Path, threads: int = 16) -> dict:
    """Return {'gates': [V-C, V-D], 'stage4_status': PASS|FAIL} and save evidence.

    A stage-4 PASS means only equilibration/clamps and dark control passed.
    Full V-C remains NOT-RUN pending eye-driven T4/T5 timestep convergence.
    """
    root = Path(root).resolve()
    destination = root / "build/validation_hybrid.json"
    started = time.perf_counter()
    created_at = datetime.now(timezone.utc).isoformat()
    c = {"gate": "V-C", "status": "NOT-RUN", "created_at": created_at, "checks": [], "warnings": []}
    d = {"gate": "V-D", "status": "NOT-RUN", "created_at": created_at, "checks": [], "warnings": []}
    document = {"gates": [c, d], "stage4_status": "FAIL", "created_at": created_at,
                "runs": [], "assumptions_changed": False}
    atomic_write_json(destination, document)
    engine = None
    neurons = None
    binding = None
    try:
        from .hybrid_engine import HybridEngine

        _require_current_reference_gate(root)
        params = parameters(root)
        built = load_network(root)
        if built["summary"]["mode"] != "hybrid":
            raise ValueError("Stage 4 requires a hybrid network build")
        neurons = built["neurons"]
        del built["reference"]
        binding = {
            "source_hashes": built["summary"]["source_hashes"],
            "source_stats": built["summary"]["source_stats"],
            "config_hashes": {**built["summary"]["config_hashes"],
                              "parameters.yaml": checksum(root / "config/parameters.yaml")},
            "implementation_hashes": {f"src/flybrain/{name}": checksum(Path(__file__).parent / name)
                                      for name in ("engine.py", "hybrid_engine.py", "validate_hybrid.py")},
        }
        for gate in (c, d):
            gate.update(binding)
            gate["protocol"] = {"mode": "hybrid", "lamina_mode": "connectome", "params": "uniform",
                                "dt_ms": params["dt"], "external_input": "zero", "threads": threads,
                                "graded_dynamics": "DESIGN_NOTES.md normalized passive voltage-state equation"}
        cells = neurons.cell_type.fillna("")
        record_mask = (cells.str.fullmatch(r"T[45][abcd]") | cells.str.startswith(("HS", "VS"))
                       | cells.eq("LPLC2") | neurons.super_class.eq("descending"))
        records = np.flatnonzero(record_mask).astype(np.int32)
        engine = HybridEngine(built["graded"], built["spiking"], neurons.is_graded.to_numpy(), params, threads=threads)
        print(f"[V-C] Pre-equilibrating all {len(neurons):,} neurons for {params['pre_equilibration']:g} ms, zero external drive", flush=True)
        check_memory()
        equilibrated = engine.run(params["pre_equilibration"], record_indices=records, chunk_ms=100)
        for gate in (c, d):
            gate["protocol"]["actual_dt_graded_ms"] = equilibrated["actual_dt_graded_ms"]
            gate["protocol"]["requested_dt_graded_ms"] = equilibrated["requested_dt_graded_ms"]
        endpoint = summarize_endpoint(neurons, equilibrated["final_dvdt"],
                                      equilibrated["per_neuron_clamp_counts"], params["stationary_tolerance"])
        directory = _record_phase(root, neurons, equilibrated, params, binding, "preequilibration")
        document["runs"].append(str(directory.relative_to(root)))
        c["equilibration"] = endpoint
        c["equilibration"]["duration_ms"] = params["pre_equilibration"]
        c["equilibration"]["spikes_by_super_class"] = class_spike_counts(neurons, equilibrated["spike_indices"])
        c["equilibration"]["evidence"] = str(directory.relative_to(root))
        clamp_accounting_ok = endpoint["clamp_events"] == int(equilibrated["clamp_count"])
        c["checks"] += [
            _check("per_neuron_clamp_accounting", endpoint["clamp_events"],
                   int(equilibrated["clamp_count"]), clamp_accounting_ok),
            _check("stationary_after_preequilibration", endpoint["max_abs_dvdt_mV_per_ms"],
                   f"max |dV/dt| <= {params['stationary_tolerance']} mV/ms; all derivatives finite", endpoint["stationary"]),
            _check("zero_preequilibration_clamps", endpoint["clamp_events"], 0, endpoint["clamp_events"] == 0),
            {"name": "T4_T5_peak_response_dt_convergence", "status": "NOT-RUN", "observed": None,
             "expected": "<5% change on halving dt; requires stage-5 eye/transduction and full-field ON/OFF input"},
        ]
        if not endpoint["stationary"] or endpoint["clamp_events"] or not clamp_accounting_ok:
            c["status"] = "FAIL"
            c["stage4_subgate_status"] = "FAIL"
            d["reason"] = "Not started: fixed-parameter pre-equilibration failed V-C; later stages stopped."
            document["stop_reason"] = "V-C pre-equilibration or clamp criterion failed; no gain or damping changes attempted."
            _assert_unchanged(root, binding)
        else:
            c["stage4_subgate_status"] = "PASS"
            atomic_write_json(destination, document)
            print("[V-D] Running 5,000 ms at constant dark input from the equilibrated state", flush=True)
            dark = engine.run(5000, record_indices=records, chunk_ms=100)
            counts = class_spike_counts(neurons, dark["spike_indices"])
            central = counts.get("central", 0)
            directory = _record_phase(root, neurons, dark, params, binding, "dark_control")
            document["runs"].append(str(directory.relative_to(root)))
            d["protocol"]["duration_ms"] = 5000
            d["spikes_by_super_class"] = counts
            d["total_spikes"] = int(len(dark["spike_indices"]))
            d["clamp_count"] = int(dark["clamp_count"])
            d["evidence"] = str(directory.relative_to(root))
            d["checks"].append(_check("central_brain_spikes", central, 0, central == 0))
            d["status"] = "PASS" if central == 0 else "FAIL"
            c["checks"].append(_check("zero_dark_control_clamps", int(dark["clamp_count"]), 0, dark["clamp_count"] == 0))
            if dark["clamp_count"]:
                c["status"] = "FAIL"
                c["stage4_subgate_status"] = "FAIL"
            else:
                c["status"] = "NOT-RUN"
                c["reason"] = "Stage-4 stationarity and clamp checks passed; eye-dependent dt convergence remains unexecuted."
            document["stage4_status"] = "PASS" if c["stage4_subgate_status"] == "PASS" and d["status"] == "PASS" else "FAIL"
            _assert_unchanged(root, binding)
    except Exception as exc:
        c["status"] = "FAIL"
        c["stage4_subgate_status"] = "FAIL"
        c["checks"].append(_check("validation_execution", {"error_type": type(exc).__name__, "error": str(exc)}, "successful stage-4 execution", False))
        document["stage4_status"] = "FAIL"
        document["stop_reason"] = f"{type(exc).__name__}: {exc}"
        if d["status"] == "PASS":
            d["status"] = "NOT-RUN"
            d["reason"] = "Completed measurements could not be bound to unchanged implementation/configuration."
        if engine is not None and getattr(engine, "partial_result", None) is not None and neurons is not None and binding is not None:
            try:
                directory = _record_phase(root, neurons, engine.partial_result, params, binding, "aborted_partial")
                document["runs"].append(str(directory.relative_to(root)))
            except Exception as save_error:
                document["partial_save_error"] = str(save_error)
    document["wall_seconds"] = time.perf_counter() - started
    document["peak_rss_bytes"] = _peak_rss_bytes()
    atomic_write_json(destination, document)
    print(f"[HYBRID {document['stage4_status']}] V-C {c['status']}; V-D {d['status']}", flush=True)
    return document
