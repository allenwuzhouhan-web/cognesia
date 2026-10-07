"""V-E: the full released graph against the downloaded Brian2 implementation.

Identical, pre-generated Bernoulli events replace only the reference's random
PoissonInput source. The reference equations, reset, graph, signs and integration
method are obtained unchanged from the downloaded model.py create_model.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import platform
import resource
import subprocess
import time

import numpy as np

from .build import load_network
from .config import parameters
from .fetch import checksum, stat_signature
from .memguard import check_memory


def generate_input_events(seed: int, n_neurons: int, trials: int, duration_ms: float,
                          dt: float, rate_hz: float = 150.0, n_driven: int = 20):
    """Seeded N=1 PoissonInput-equivalent Bernoulli trials on a fixed dt grid."""
    if trials < 1 or duration_ms <= 0 or dt <= 0 or n_neurons < n_driven:
        raise ValueError("Invalid event-generation dimensions")
    steps = round(duration_ms / dt)
    if not np.isclose(steps * dt, duration_ms):
        raise ValueError("Duration must be an integer number of simulation steps")
    probability = rate_hz * dt / 1000
    if not 0 <= probability <= 1:
        raise ValueError("Bernoulli spike probability must be in [0,1]")
    rng = np.random.default_rng(seed)
    driven = rng.choice(n_neurons, size=n_driven, replace=False).astype(np.int32)
    events = [np.argwhere(rng.random((steps, n_driven)) < probability).astype(np.int32)
              for _ in range(trials)]
    return driven, events


def _correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) < 2 or np.std(left) == 0 or np.std(right) == 0:
        return None
    return float(np.corrcoef(left, right)[0, 1])


def compare_rates(custom_counts: np.ndarray, reference_counts: np.ndarray,
                  driven: np.ndarray, duration_ms: float) -> dict:
    """Compare means over trials, reporting follower and pooled diagnostics."""
    custom = np.asarray(custom_counts, dtype=np.float64) / (duration_ms / 1000)
    reference = np.asarray(reference_counts, dtype=np.float64) / (duration_ms / 1000)
    if custom.shape != reference.shape or custom.ndim != 2:
        raise ValueError("Spike counts must have equal (trial, neuron) shape")
    active = np.any((custom > 0) | (reference > 0), axis=0)
    followers = active.copy()
    followers[driven] = False
    custom_mean, reference_mean = custom.mean(axis=0), reference.mean(axis=0)
    return {
        "mean_rate_correlation": _correlation(custom_mean[active], reference_mean[active]),
        "follower_mean_rate_correlation": _correlation(custom_mean[followers], reference_mean[followers]),
        "pooled_trial_neuron_correlation": _correlation(custom[:, active].ravel(), reference[:, active].ravel()),
        "follower_pooled_correlation": _correlation(custom[:, followers].ravel(), reference[:, followers].ravel()),
        "active_union_neurons": int(active.sum()), "follower_active_union_neurons": int(followers.sum()),
        "custom_active_neurons": int(np.any(custom > 0, axis=0).sum()),
        "reference_active_neurons": int(np.any(reference > 0, axis=0).sum()),
        "custom_spikes": int(custom_counts.sum()), "reference_spikes": int(reference_counts.sum()),
        "mean_rate_absolute_error_hz": float(np.mean(np.abs(custom_mean[active] - reference_mean[active]))) if active.any() else None,
        "follower_mean_rate_absolute_error_hz": float(np.mean(np.abs(custom_mean[followers] - reference_mean[followers]))) if followers.any() else None,
        "max_mean_rate_absolute_error_hz": float(np.max(np.abs(custom_mean[active] - reference_mean[active]))) if active.any() else None,
    }


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    temp.replace(path)


def _spike_hash(indices: np.ndarray, times: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(indices, dtype=np.int32).tobytes())
    digest.update(np.ascontiguousarray(times, dtype=np.float32).tobytes())
    return digest.hexdigest()


def _peak_rss_bytes() -> int:
    measured = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(measured if platform.system() == "Darwin" else measured * 1024)


def _create_reference(root: Path, driven: np.ndarray, params: dict):
    import brian2 as brian

    path = root / "data/raw/model.py"
    spec = importlib.util.spec_from_file_location("flybrain_downloaded_shiu_reference", path)
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    # Validate agreement rather than overriding the reference's constants.
    reference_parameters = dict(reference.default_params)
    for local, remote, unit in [
        ("v_rest", "v_0", brian.mV), ("v_reset", "v_rst", brian.mV),
        ("v_threshold", "v_th", brian.mV), ("tau_membrane", "t_mbr", brian.ms),
        ("tau_synapse", "tau", brian.ms), ("refractory", "t_rfc", brian.ms),
        ("synaptic_delay", "t_dly", brian.ms), ("spike_weight", "w_syn", brian.mV),
        ("poisson_rate", "r_poi", brian.Hz),
    ]:
        measured = float(reference_parameters[remote] / unit)
        if not np.isclose(params[local], measured, rtol=0, atol=1e-12):
            raise ValueError(f"Configured {local}={params[local]} differs from released reference {remote}={measured}")
    if params["poisson_factor"] != reference_parameters["f_poi"]:
        raise ValueError("Configured poisson_factor differs from released reference")
    brian.start_scope()
    brian.defaultclock.dt = params["dt"] * brian.ms
    brian.prefs.codegen.target = "cython"
    neu, syn, monitor = reference.create_model(
        root / "data/raw/Completeness_783.csv", root / "data/raw/Connectivity_783.parquet", reference_parameters)
    neu.rfc[driven] = 0 * brian.ms
    source = brian.SpikeGeneratorGroup(len(driven), np.array([], dtype=int), np.array([]) * brian.ms,
                                      sorted=True, name="ve_input_source")
    inputs = brian.Synapses(source, neu, on_pre="v_post += input_increment",
                           namespace={"input_increment": reference_parameters["w_syn"] * reference_parameters["f_poi"]},
                           name="ve_input_synapses")
    inputs.connect(i=np.arange(len(driven)), j=driven)
    network = brian.Network(neu, syn, monitor, source, inputs)
    # Compile before the snapshot; store/restore ensures fresh state and queue.
    network.run(0 * brian.ms)
    network.store("baseline")
    return brian, network, source, monitor


def validate_engine(root: Path, trials: int = 10, duration_ms: float = 1000,
                    threads: int = 16, integrator: str = "exponential_euler") -> dict:
    """Full V-E or an explicitly labelled smoke run; never tune to pass."""
    root = Path(root).resolve()
    destination = root / "build/validation_engine.json"
    start = time.perf_counter()
    full_protocol = trials == 10 and duration_ms == 1000 and integrator == "exponential_euler"
    result = {
        "gate": "V-E", "status": "NOT-RUN", "checks": [], "warnings": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "protocol": {"trials": trials, "duration_ms": duration_ms, "n_driven": 20,
                     "threads": threads, "custom_integrator": integrator,
                     "reference_integrator": "linear (released create_model)",
                     "full_protocol": full_protocol,
                     "primary_metric": "Pearson r of mean per-neuron firing rate over trials, union of firing neurons",
                     "threshold": 0.95},
        "trial_results": [],
    }
    _write_json(destination, result)
    try:
        from .engine import LIFEngine

        params = parameters(root)
        network = load_network(root)
        weights = network["reference"]
        neuron_count = len(network["neurons"])
        del network["graded"], network["spiking"], network["neurons"]
        manifest_path = root / "build/downloads.json"
        manifest = json.loads(manifest_path.read_text())["files"]
        source = root / "data/raw/model.py"
        if checksum(source) != manifest["model.py"]["sha256"]:
            raise ValueError("Downloaded reference model.py differs from the recorded download")
        result["source_hashes"] = {**network["summary"]["source_hashes"], "model.py": checksum(source)}
        result["source_stats"] = {**network["summary"]["source_stats"], "model.py": stat_signature(source)}
        result["config_hashes"] = {**network["summary"]["config_hashes"],
                                    "parameters.yaml": checksum(root / "config/parameters.yaml")}
        result["code_hashes"] = {name: checksum(Path(__file__).parent / name)
                                  for name in ("engine.py", "validate_engine.py")}
        result["implementation_hashes"] = {f"src/flybrain/{name}": digest
                                            for name, digest in result["code_hashes"].items()}
        result["versions"] = {name: importlib.metadata.version(name) for name in ("numpy", "scipy", "brian2", "numba")}
        result["versions"]["python"] = platform.python_version()
        result["git_hash"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip() or None
        driven, input_trials = generate_input_events(int(params["seed"]), neuron_count, trials,
                                                     duration_ms, params["dt"], params["poisson_rate"])
        result["seed"] = int(params["seed"])
        result["driven_neuron_indices"] = driven.tolist()
        result["protocol"].update({"dt_ms": params["dt"], "input_rate_hz": params["poisson_rate"],
                                   "input_voltage_increment_mV": params["poisson_factor"] * params["spike_weight"],
                                   "driven_refractory_ms": 0, "reference_signs": "unmodified classifier signs"})
        run_dir = root / "build/engine_crosscheck" / integrator
        run_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(run_dir / "inputs.npz", driven_neuron_indices=driven,
                            **{f"trial_{i:02d}": event for i, event in enumerate(input_trials)})
        result["input_events_sha256"] = checksum(run_dir / "inputs.npz")
        custom_counts = np.zeros((trials, neuron_count), dtype=np.int64)
        reference_counts = np.zeros_like(custom_counts)
        custom_clamps = 0
        print(f"[V-E] Preparing full {neuron_count:,}-neuron Brian2 reference", flush=True)
        brian, reference_net, event_source, reference_monitor = _create_reference(root, driven, params)
        for trial, events in enumerate(input_trials):
            check_memory()
            print(f"[V-E] Trial {trial + 1}/{trials}: custom {integrator}, {duration_ms:g} ms", flush=True)
            engine = LIFEngine(weights, params, integrator=integrator, threads=threads, clamp=True)
            custom = engine.run(duration_ms, input_neurons=driven, input_events=events, chunk_ms=100)
            custom_counts[trial] = np.bincount(custom["spike_indices"], minlength=neuron_count)
            custom_clamps += int(custom["clamp_count"])
            custom_hash = _spike_hash(custom["spike_indices"], custom["spike_times"])
            custom_path = run_dir / f"trial_{trial:02d}_custom.npz"
            np.savez_compressed(custom_path, spike_indices=np.asarray(custom["spike_indices"], dtype=np.int32),
                                spike_times=np.asarray(custom["spike_times"], dtype=np.float32))
            if trial == 0:
                print("[V-E] Replaying custom trial 1 to verify bit-identical spike trains", flush=True)
                repeat = LIFEngine(weights, params, integrator=integrator, threads=threads, clamp=True).run(
                    duration_ms, input_neurons=driven, input_events=events, chunk_ms=100)
                result["determinism"] = {
                    "status": "PASS" if custom_hash == _spike_hash(repeat["spike_indices"], repeat["spike_times"]) else "FAIL",
                    "first_trial_spike_hash": custom_hash,
                    "repeat_spike_hash": _spike_hash(repeat["spike_indices"], repeat["spike_times"]),
                }
                del repeat
            print(f"[V-E] Trial {trial + 1}/{trials}: released Brian2 reference", flush=True)
            reference_net.restore("baseline")
            event_source.set_spikes(events[:, 1], events[:, 0] * params["dt"] * brian.ms, sorted=True)
            reference_start = time.perf_counter()
            elapsed = 0.0
            while elapsed < duration_ms - 1e-9:
                check_memory()
                chunk = min(100, duration_ms - elapsed)
                reference_net.run(chunk * brian.ms)
                elapsed += chunk
            reference_indices = np.asarray(reference_monitor.i[:], dtype=np.int32)
            reference_times = np.asarray(reference_monitor.t[:] / brian.ms, dtype=np.float32)
            reference_counts[trial] = np.bincount(reference_indices, minlength=neuron_count)
            reference_path = run_dir / f"trial_{trial:02d}_reference.npz"
            np.savez_compressed(reference_path, spike_indices=reference_indices, spike_times=reference_times)
            trial_result = {"trial": trial, "input_events": len(events),
                            "custom_spikes": int(custom_counts[trial].sum()),
                            "reference_spikes": int(reference_counts[trial].sum()),
                            "custom_clamp_count": int(custom["clamp_count"]),
                            "custom_wall_seconds": custom["wall_seconds"],
                            "reference_wall_seconds": time.perf_counter() - reference_start,
                            "custom_spike_hash": custom_hash,
                            "reference_spike_hash": _spike_hash(reference_indices, reference_times),
                            "custom_file_sha256": checksum(custom_path),
                            "reference_file_sha256": checksum(reference_path)}
            trial_result["peak_process_rss_bytes"] = _peak_rss_bytes()
            result["trial_results"].append(trial_result)
            _write_json(run_dir / f"trial_{trial:02d}_manifest.json", {**trial_result,
                "config_hashes": result["config_hashes"], "source_hashes": result["source_hashes"],
                "code_hashes": result["code_hashes"], "seed": params["seed"], "versions": result["versions"],
                "git_hash": result["git_hash"], "protocol": result["protocol"]})
            _write_json(destination, result)
            del engine, custom
        metrics = compare_rates(custom_counts, reference_counts, driven, duration_ms)
        result["metrics"] = metrics
        result["clamp_count"] = custom_clamps
        primary_r = metrics["mean_rate_correlation"]
        correlation_ok = primary_r is not None and primary_r >= 0.95
        result["checks"].append({"name": "mean_firing_rate_correlation", "status": "PASS" if correlation_ok else "FAIL",
                                 "observed": primary_r, "expected": ">=0.95"})
        result["checks"].append({"name": "deterministic_spike_trains", "status": result["determinism"]["status"],
                                 "observed": result["determinism"]["first_trial_spike_hash"],
                                 "expected": result["determinism"]["repeat_spike_hash"]})
        follower_r = metrics["follower_mean_rate_correlation"]
        if follower_r is None or follower_r < 0.95:
            result["warnings"].append(f"Follower-only mean-rate correlation is {follower_r}; driven cells can dominate the primary statistic.")
        if custom_clamps:
            result["warnings"].append(f"Production voltage limits clamped {custom_clamps} events during V-E.")
        for name, previous in result["source_stats"].items():
            if stat_signature(root / "data/raw" / name) != previous:
                raise ValueError(f"Source changed during V-E: {name}")
        for name, previous in result["config_hashes"].items():
            if checksum(root / "config" / name) != previous:
                raise ValueError(f"Configuration changed during V-E: {name}; measured result belongs to the earlier config")
        for relative_path, previous in result["implementation_hashes"].items():
            if checksum(root / relative_path) != previous:
                raise ValueError(f"Implementation changed during V-E: {relative_path}; measured result belongs to the earlier loaded code")
        np.savez_compressed(run_dir / "firing_counts.npz", custom=custom_counts, reference=reference_counts,
                            driven_neuron_indices=driven)
        result["status"] = ("PASS" if all(check["status"] == "PASS" for check in result["checks"]) else "FAIL") if full_protocol else "NOT-RUN"
        if not full_protocol:
            result["warnings"].append("Reduced or diagnostic protocol completed; this is not the full production V-E gate.")
    except Exception as exc:
        result["status"] = "FAIL"
        result["checks"].append({"name": "validation_execution", "status": "FAIL",
                                 "observed": {"error_type": type(exc).__name__, "error": str(exc)},
                                 "expected": "successful full-protocol execution"})
    result["wall_seconds"] = time.perf_counter() - start
    result["peak_process_rss_bytes"] = _peak_rss_bytes()
    _write_json(destination, result)
    _write_json(destination.parent / "engine_run_manifest.json", result)
    print(f"[V-E {result['status']}] {result.get('metrics', result['checks'])}", flush=True)
    return result
