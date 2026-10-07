"""Isolated whole-brain stability track for FINAL Part III.

All output is separate from the original hybrid validation and neuromod gates.
Reported eigenvalues are measured for the configured population, with a separate
first-pass comparison. Failed branches retain evidence and never tune defaults.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import scipy
import yaml

from ..build import load_network, VISUAL_CLASSES, PHOTORECEPTORS
from ..config import parameters
from ..fetch import checksum
from ..hybrid_variant import (HybridVariantEngine, build_stability_variant, fixed_point,
                              spectral_stats, variant_parameters)
from ..inspect_data import atomic_write_json


def fit_growth(times_ms, derivative, duration_ms, *, numerical_floor=1e-12):
    times, values = np.asarray(times_ms), np.asarray(derivative)
    second = times >= duration_ms/2
    usable = second & np.isfinite(values) & (values > numerical_floor)
    result = {"window_ms": [duration_ms/2, duration_ms], "numerical_floor_mV_per_ms": numerical_floor,
              "second_half_samples": int(second.sum()), "samples_above_floor": int(usable.sum())}
    if usable.sum() < 20:
        return result | {"resolved": False, "slope_per_ms": None, "tau_net_ms": None,
                         "reason": "Insufficient second-half derivatives above the numerical floor; no negative slope invented"}
    x, y = times[usable], np.log(values[usable])
    slope, intercept = np.polyfit(x, y, 1)
    residual = y-(intercept+slope*x)
    r2 = 1-float(np.dot(residual, residual))/max(float(np.dot(y-y.mean(), y-y.mean())), np.finfo(float).tiny)
    tau = -1/float(slope) if slope < 0 else None
    extrapolated = float(np.exp(np.clip(intercept+slope*10*tau, -700, 700))) if tau else None
    return result | {"resolved": True, "slope_per_ms": float(slope), "tau_net_ms": tau,
                     "r_squared": r2, "extrapolated_at_10_tau_mV_per_ms": extrapolated,
                     "extrapolation_is_not_a_simulated_measurement": True}


def _first_pass_comparison(root, p):
    built = load_network(root)
    neurons = built["neurons"]
    mask = (neurons.super_class.isin(VISUAL_CLASSES) | neurons.cell_type.isin(PHOTORECEPTORS)).to_numpy()
    matrix = (built["graded"]+built["spiking"])[mask][:, mask]
    signature = {"base_output_hashes": built["summary"]["output_hashes"],
                 "spectral_code": hashlib.sha256(inspect.getsource(spectral_stats).encode()).hexdigest(),
                 "parameters": {k: p[k] for k in ("arnoldi_tolerance", "arnoldi_max_iterations", "arnoldi_modes", "seed")}}
    path = root / "build/stability_variant/first_pass_spectrum.json"
    if path.exists():
        old = json.loads(path.read_text())
        if old.get("signature") == signature:
            return old
    stats = spectral_stats(matrix, tolerance=p["arnoldi_tolerance"], max_iterations=p["arnoldi_max_iterations"], modes=p["arnoldi_modes"], seed=p["seed"])
    result = {"signature": signature, "graded_neurons": int(mask.sum()), "graded_recurrent_edges": int(matrix.nnz),
              "spectrum": stats, "scope": "Original all-visual first-pass selector, point CT1, signed counts with saved overrides; comparison only, never substituted for configured dynamics",
              "quoted_comparison": {"max_Re_lambda": 1095.6, "max_abs_lambda": 1980.0}}
    atomic_write_json(path, result)
    return result


def _case(root, network, base, options, label, threads, *, dynamic=True):
    folder = root / "build/stability_variant" / label
    folder.mkdir(parents=True, exist_ok=True)
    gates = [{"gate": f"V-C{i}", "status": "NOT-RUN"} for i in range(1, 5)]
    result = {"label": label, "parameters": options, "gates": gates,
              "max_Re_lambda": network.spectrum.get("max_Re_lambda"),
              "max_abs_lambda": network.spectrum.get("max_abs_lambda"),
              "kappa": options["kappa"], "graded_norm": options["graded_norm"], "tau_net_ms": None,
              "syn_model": options["syn_model"], "ct1_mode": options["ct1_mode"],
              "status": "NOT-RUN", "dynamic_validation_requested": dynamic}
    try:
        point = fixed_point(network, base, options)
        details = {k: v for k, v in point.items() if k not in {"voltage", "g_exc", "g_inh", "suprathreshold_spiking_neurons"}}
        details["suprathreshold_spiking_neurons"] = len(point["suprathreshold_spiking_neurons"])
        result["fixed_point"] = details
        np.savez_compressed(folder / "fixed_point.npz", voltage=point["voltage"], g_exc=point["g_exc"], g_inh=point["g_inh"], root_ids=network.neurons.root_id.to_numpy())
        supra = network.neurons.iloc[point["suprathreshold_spiking_neurons"]][["root_id", "cell_type"]].copy()
        supra.to_csv(folder / "suprathreshold_spiking_neurons.csv", index=False)
        gates[0].update(status="PASS" if point["quiescent_fixed_point"] else "FAIL", **details)
        if not point["quiescent_fixed_point"]:
            result["stop_reason"] = "No converged quiescent hybrid fixed point established; this case was not integrated longer"
            result["status"] = "FAIL"
            return result
        if not dynamic:
            result["stop_reason"] = "Fixed-point sensitivity measurement only; dynamic gates stopped because a default whole-brain branch failed"
            return result
        engine = HybridVariantEngine(network, base, options, threads=threads)
        engine.initialize_fixed_point(point, perturbation=options["perturbation_mV"], seed=options["seed"])
        print(f"[STABILITY] {label}: 2000 ms perturbed run", flush=True)
        coarse = engine.run(options["growth_duration_ms"])
        np.savez_compressed(folder / "growth_coarse.npz", **{k: v for k, v in coarse.items() if isinstance(v, np.ndarray)})
        growth = fit_growth(coarse["times_ms"], coarse["max_abs_dvdt"], options["growth_duration_ms"])
        result["growth"] = growth
        result["tau_net_ms"] = growth.get("tau_net_ms")
        gates[1].update(status=("PASS" if growth["slope_per_ms"] < 0 else "FAIL") if growth["resolved"] else "NOT-RUN", **growth)
        peaks = np.bincount(coarse["worst_neuron_indices"], minlength=len(network.neurons))
        leaders = network.neurons.loc[peaks > 0, ["root_id", "cell_type", "is_graded"]].copy()
        leaders["worst_derivative_samples"] = peaks[peaks > 0]
        leaders.sort_values("worst_derivative_samples", ascending=False).to_csv(folder / "growth_leading_neurons.csv", index=False)
        clamped = coarse["per_neuron_clamps"] > 0
        ledger = network.neurons.loc[clamped, ["root_id", "cell_type", "is_graded"]].copy()
        ledger["clamp_events"] = coarse["per_neuron_clamps"][clamped]
        # Denormalized retained matrix recovers the actual graded-input degree/weight.
        ledger["graded_input_degree"] = np.diff(network.graded.indptr)[clamped]
        ledger["graded_input_abs_synapses"] = np.asarray(abs(network.graded).sum(axis=1)).ravel()[clamped] * network.denominator[clamped]
        ledger.to_csv(folder / "clamped_neurons.csv", index=False)
        gates[2].update(status="PASS" if coarse["clamp_count"] == 0 else "FAIL",
                        clamp_count=coarse["clamp_count"], clamped_neurons=int(clamped.sum()),
                        ledger=str((folder / "clamped_neurons.csv").relative_to(root)),
                        voltage_range_mV=[float(coarse["voltage_min"].min()), float(coarse["voltage_max"].max())])
        result["coarse_wall_seconds"] = coarse["wall_seconds"]
        bound = 2*min(base["tau_membrane"], base["graded_tau_membrane"])/(1+point["gain"]*network.spectrum["max_abs_lambda"])
        result["quoted_one_state_stiffness_bound_ms"] = bound
        result["bound_scope"] = "FINAL's one-state linearized proxy; the actual variant also has synaptic filtering, delays and threshold/reset. Dynamic V-C2 and dt comparison remain necessary."
        if gates[1]["status"] != "PASS" or gates[2]["status"] != "PASS":
            result["status"] = "FAIL" if "FAIL" in [g["status"] for g in gates] else "NOT-RUN"
            result["stop_reason"] = "Growth or clamp gate did not pass; half-timestep continuation stopped for this case"
            return result
        fine = HybridVariantEngine(network, base, options, dt=base["dt"]/2, threads=threads)
        fine.initialize_fixed_point(point, perturbation=options["perturbation_mV"], seed=options["seed"])
        print(f"[STABILITY] {label}: half timestep", flush=True)
        halved = fine.run(options["growth_duration_ms"])
        np.savez_compressed(folder / "growth_half_dt.npz", **{k: v for k, v in halved.items() if isinstance(v, np.ndarray)})
        difference = float(np.max(np.abs(coarse["final_v"]-halved["final_v"])))
        # Independent equilibrium-preservation check: the mathematical fixed point
        # is dt-independent, and both numerical steppers must preserve it.
        stationary_errors = []
        for dt in (base["dt"], base["dt"]/2):
            steady = HybridVariantEngine(network, base, options, dt=dt, threads=threads)
            steady.initialize_fixed_point(point)
            endpoint = steady.run(10.)
            stationary_errors.append(float(np.max(np.abs(endpoint["final_v"]-point["voltage"]))))
        gates[3].update(status="PASS" if base["dt"] < bound and difference < .1 and max(stationary_errors) < .1 and halved["clamp_count"] == 0 else "FAIL",
                        dt_ms=base["dt"], half_dt_ms=base["dt"]/2, stiffness_proxy_bound_ms=bound,
                        max_perturbed_endpoint_difference_mV=difference, fixed_point_preservation_error_mV=stationary_errors,
                        half_dt_clamps=halved["clamp_count"], tolerance_mV=.1,
                        comparison_scope="Same directly solved fixed point and seeded perturbation; 2000 ms endpoint difference plus 10 ms unperturbed equilibrium preservation")
        result["half_dt_wall_seconds"] = halved["wall_seconds"]
        result["status"] = "PASS" if all(g["status"] == "PASS" for g in gates) else "FAIL"
        return result
    except Exception as exc:
        result["status"] = "FAIL"
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        return result
    finally:
        result["artifact_hashes"] = {str(path.relative_to(root / "build")): checksum(path)
                                     for path in folder.iterdir() if path.is_file() and path.name != "manifest.json"}
        atomic_write_json(folder / "manifest.json", result)


def validate_stability(root: Path, threads: int = 8, *, sensitivities=True) -> dict:
    root = Path(root).resolve(); output = root / "build/stability_variant"
    output.mkdir(parents=True, exist_ok=True)
    p, base = variant_parameters(root), parameters(root)
    result = {"gate": "V-C-VARIANT", "status": "NOT-RUN", "created_at": datetime.now(timezone.utc).isoformat(),
              "scope": "Separate FINAL Part III whole-brain stability track; original V-C and V-E evidence and neuromod source audit remain unchanged",
              "parameters": p, "defaults": [], "sensitivity_runs": [], "gates": [],
              "software_versions": {"numpy": np.__version__, "scipy": scipy.__version__},
              "stale_dynamics_policy": "No earlier dynamics PASS is transferred to this changed model; eye/direction-selectivity gates remain NOT-RUN"}
    destination = root / "build/validation_hybrid_variant.json"
    atomic_write_json(destination, result)
    started = time.perf_counter()
    try:
        network = build_stability_variant(root)
        result["network"] = {k: v for k, v in network.metadata.items() if k != "base_binding"}
        binding = network.metadata["base_binding"]
        result["source_hashes"], result["source_stats"] = binding["source_hashes"], binding["source_stats"]
        result["base_artifact_hashes"] = binding["output_hashes"]
        result["config_hashes"] = binding["config_hashes"] | {name: checksum(root / "config" / name) for name in ("parameters.yaml", "hybrid_variant.yaml")}
        result["implementation_hashes"] = {name: checksum(root / name) for name in
                                           ("src/flybrain/hybrid_variant.py", "src/flybrain/neuromod/stability.py", "src/flybrain/engine.py", "src/flybrain/hybrid_engine.py")}
        result["spectrum"] = network.spectrum
        result["first_pass_comparison"] = _first_pass_comparison(root, p)
        for model in ("current", "conductance"):
            case = _case(root, network, base, p | {"syn_model": model}, "default_"+model, threads)
            result["defaults"].append(case)
            result["gates"].extend([g | {"syn_model": model} for g in case["gates"]])
            atomic_write_json(destination, result)
        default_pass = all(case["status"] == "PASS" for case in result["defaults"])
        if sensitivities:
            declarations = yaml.safe_load((root / "config/hybrid_variant.yaml").read_text())["parameters"]
            changes = [{"kappa": value} for value in declarations["kappa"]["sweep"] if value != p["kappa"]]
            changes += [{"graded_norm": "none"}, *[{"graded_norm": "in_degree_alpha", "in_degree_alpha": a}
                                                    for a in declarations["in_degree_alpha"]["sweep"]], {"ct1_mode": "point"}]
            for index, change in enumerate(changes):
                variant_network = network if set(change) == {"kappa"} else build_stability_variant(root, overrides=change)
                for model in ("current", "conductance"):
                    options = p | change | {"syn_model": model}
                    label = f"sensitivity_{index:02d}_{model}"
                    case = _case(root, variant_network, base, options, label, threads, dynamic=default_pass)
                    result["sensitivity_runs"].append(case)
                    atomic_write_json(destination, result)
        result["status"] = "PASS" if default_pass else "FAIL"
        result["stop_reason"] = None if default_pass else "One or more default V-C1–V-C4 branches did not pass; only direct fixed-point/spectral sensitivity measurements were permitted afterward"
        for group, prefix in (("config_hashes", root / "config"), ("implementation_hashes", root), ("base_artifact_hashes", root / "build")):
            for name, expected in result[group].items():
                if checksum(prefix / name) != expected:
                    raise ValueError(f"Stability input changed during validation: {name}")
        result["artifact_hashes"] = {str(path.relative_to(root / "build")): checksum(path) for path in output.rglob("*") if path.is_file()}
    except Exception as exc:
        result["status"] = "FAIL"
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    result["wall_seconds"] = time.perf_counter()-started
    atomic_write_json(destination, result)
    return result
