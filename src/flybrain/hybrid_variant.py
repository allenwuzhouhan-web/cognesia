"""Separate normalized-gain hybrid variant; never changes the base Brian2 path.

The graded synaptic state is a unit-gain low-pass of gain*W*release. Thus gain
is the DC loop coefficient, unlike the base engine's tau_synapse*graded_gain.
Conductances match each signed current's initial driving force at V_rest;
that conversion and row normalization are explicit modeling assumptions.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import inspect
import json
import time

import numba as nb
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.linalg import eigs, ArpackNoConvergence
import yaml

from .build import load_network
from .engine import LIFEngine
from .fetch import checksum
from .inspect_data import atomic_write_json
from .memguard import check_memory

HUB_TYPES = ("CT1", "LPi13", "LPi14", "LPi15", "Li30", "Li31", "Li32", "Li33", "Am1", "Sm41", "Sm42", "LT1d")


def variant_parameters(root: Path) -> dict:
    rows = yaml.safe_load((Path(root) / "config/hybrid_variant.yaml").read_text())["parameters"]
    for name, row in rows.items():
        if not row.get("unit") or not row.get("source") or "value" not in row:
            raise ValueError(f"Missing variant parameter provenance: {name}")
        if row["source"] == "ASSUMPTION" and not row.get("sweep"):
            raise ValueError(f"Variant assumption lacks declared sweep: {name}")
    result = {name: row["value"] for name, row in rows.items()}
    validate_variant_parameters(result)
    return result


def validate_variant_parameters(p: dict):
    if p["graded_norm"] not in {"none", "in_weight", "in_degree_alpha"}:
        raise ValueError("Unknown graded normalization")
    if p["ct1_mode"] not in {"excluded", "point"} or p["syn_model"] not in {"current", "conductance"}:
        raise ValueError("Unknown CT1 or synaptic model; per_column is not implemented")
    if not np.isfinite(p["kappa"]) or not 0 < p["kappa"] < 1:
        raise ValueError("kappa must be strictly between zero and one")
    if not np.isfinite(p["in_degree_alpha"]) or p["in_degree_alpha"] < 0:
        raise ValueError("Normalization exponent must be finite and nonnegative")
    if not np.isfinite([p["E_exc"], p["E_inh"]]).all() or p["E_inh"] >= p["E_exc"]:
        raise ValueError("Reversal potentials must be finite and ordered")
    if not 0 < p["fixed_point_damping"] <= 1 or p["fixed_point_tolerance"] <= 0:
        raise ValueError("Invalid fixed-point iteration settings")
    for key in ("fixed_point_max_iterations", "arnoldi_max_iterations", "arnoldi_modes"):
        if not isinstance(p[key], int) or p[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    for key in ("growth_duration_ms", "diagnostic_interval_ms", "perturbation_mV", "arnoldi_tolerance"):
        if not np.isfinite(p[key]) or p[key] <= 0:
            raise ValueError(f"{key} must be positive and finite")


def normalize_graded(matrix, mode: str, alpha=.5):
    matrix = sparse.csr_matrix(matrix, dtype=np.float64, copy=True)
    matrix.sum_duplicates(); matrix.eliminate_zeros(); matrix.sort_indices()
    degree = np.diff(matrix.indptr).astype(np.int64)
    weight = np.asarray(abs(matrix).sum(axis=1)).ravel()
    if mode == "none":
        denominator = np.ones(matrix.shape[0])
    elif mode == "in_weight":
        denominator = np.maximum(weight, 1.)
    elif mode == "in_degree_alpha" and np.isfinite(alpha) and alpha >= 0:
        denominator = np.maximum(degree, 1.) ** alpha
    else:
        raise ValueError("Unknown graded normalization or invalid exponent")
    matrix.data /= np.repeat(denominator, degree)
    return matrix, denominator


def spectral_stats(matrix, *, tolerance=1e-7, max_iterations=3000, modes=6, seed=783):
    """Measure LR and LM eigenpairs separately, with explicit Ritz residuals."""
    a = sparse.csr_matrix(matrix, dtype=np.float64)
    if a.shape[0] != a.shape[1] or not np.isfinite(a.data).all():
        raise ValueError("Spectral matrix must be square and finite")
    if a.shape[0] < 3 or a.nnz == 0:
        values = np.linalg.eigvals(a.toarray()) if a.shape[0] else np.array([0.])
        return {"converged": True, "max_Re_lambda": float(values.real.max()), "max_abs_lambda": float(abs(values).max()),
                "solver": "dense tiny-matrix reference", "eigenvalues_LR": [[float(v.real), float(v.imag)] for v in values],
                "eigenvalues_LM": [[float(v.real), float(v.imag)] for v in values], "ritz_relative_residual_max": 0.}
    k = min(modes, a.shape[0] - 2)
    start = np.random.default_rng(seed).normal(size=a.shape[0]); start /= np.linalg.norm(start)
    results, residuals = {}, []
    for which in ("LR", "LM"):
        try:
            values, vectors = eigs(a, k=k, which=which, v0=start, tol=tolerance,
                                   maxiter=max_iterations, ncv=min(a.shape[0], max(2*k+1, 32)))
        except ArpackNoConvergence as exc:
            partial = [] if exc.eigenvalues is None else [[float(v.real), float(v.imag)] for v in exc.eigenvalues]
            return {"converged": False, "solver": "scipy ARPACK Arnoldi", "failed_selection": which,
                    "partial_eigenvalues": partial, "error": str(exc), "max_Re_lambda": None, "max_abs_lambda": None}
        order = np.lexsort((values.imag, values.real))
        values, vectors = values[order], vectors[:, order]
        for index, value in enumerate(values):
            vector = vectors[:, index]
            residuals.append(float(np.linalg.norm(a @ vector - value * vector) / max(abs(value), 1.)))
        results[which] = values
    residual = max(residuals)
    return {"converged": bool(residual <= max(tolerance * 100, 1e-6)),
            "solver": "scipy.sparse.linalg.eigs / ARPACK Arnoldi, distinct which=LR and which=LM solves",
            "max_Re_lambda": float(results["LR"].real.max()), "max_abs_lambda": float(abs(results["LM"]).max()),
            "eigenvalues_LR": [[float(v.real), float(v.imag)] for v in results["LR"]],
            "eigenvalues_LM": [[float(v.real), float(v.imag)] for v in results["LM"]],
            "ritz_relative_residual_max": residual, "tolerance": tolerance, "modes_requested": k,
            "max_iterations": max_iterations, "seed": seed}


@dataclass
class VariantNetwork:
    neurons: pd.DataFrame
    graded: sparse.csr_matrix
    spiking: sparse.csr_matrix
    graded_mask: np.ndarray
    excluded: np.ndarray
    denominator: np.ndarray
    spectrum: dict
    metadata: dict


def build_stability_variant(root: Path, *, overrides=None) -> VariantNetwork:
    root = Path(root).resolve()
    p = variant_parameters(root) | (overrides or {})
    validate_variant_parameters(p)
    built = load_network(root)
    neurons, graded, spiking = built["neurons"], built["graded"].copy(), built["spiking"].copy()
    mask = neurons.is_graded.to_numpy(bool)
    ct1 = neurons.cell_type.fillna("").eq("CT1").to_numpy()
    excluded = ct1 if p["ct1_mode"] == "excluded" else np.zeros(len(neurons), bool)
    output = root / "build/stability_variant"; output.mkdir(parents=True, exist_ok=True)
    degree = np.diff(graded.indptr)
    in_weight = np.asarray(abs(graded).sum(axis=1)).ravel()
    hubs = neurons.loc[neurons.cell_type.isin(HUB_TYPES), ["root_id", "cell_type", "is_graded"]].copy()
    hubs.insert(0, "model_index", hubs.index.to_numpy())
    hubs["graded_input_degree"] = degree[hubs.index]
    hubs["graded_input_abs_synapses"] = in_weight[hubs.index]
    hubs.to_csv(output / "hub_neurons.csv", index=False)
    ledger_parts = []
    if excluded.any():
        for name, matrix in (("graded", graded), ("spiking", spiking)):
            post = np.repeat(np.arange(len(neurons)), np.diff(matrix.indptr))
            dropped = excluded[post] | excluded[matrix.indices]
            pre_ids, post_ids = matrix.indices[dropped], post[dropped]
            ledger_parts.append(pd.DataFrame({"mode_matrix": name, "pre_index": pre_ids, "post_index": post_ids,
                                              "pre_root_id": neurons.root_id.to_numpy()[pre_ids], "post_root_id": neurons.root_id.to_numpy()[post_ids],
                                              "signed_synapses": matrix.data[dropped], "pre_CT1": excluded[pre_ids], "post_CT1": excluded[post_ids]}))
            matrix.data[dropped] = 0; matrix.eliminate_zeros()
    ledger = pd.concat(ledger_parts, ignore_index=True) if ledger_parts else pd.DataFrame(columns=["mode_matrix", "pre_index", "post_index", "pre_root_id", "post_root_id", "signed_synapses", "pre_CT1", "post_CT1"])
    ledger.to_csv(output / f"ct1_{p['ct1_mode']}_edge_ledger.csv", index=False)
    normalized, denominator = normalize_graded(graded, p["graded_norm"], p["in_degree_alpha"])
    active = mask & ~excluded
    recurrence = normalized[active][:, active]
    signature = {"base_output_hashes": built["summary"]["output_hashes"], "graded_norm": p["graded_norm"],
                 "alpha": p["in_degree_alpha"], "ct1_mode": p["ct1_mode"],
                 "solver_code": hashlib.sha256(inspect.getsource(spectral_stats).encode()).hexdigest(),
                 "normalization_code": hashlib.sha256(inspect.getsource(normalize_graded).encode()).hexdigest(),
                 "solver_parameters": {k: p[k] for k in ("arnoldi_tolerance", "arnoldi_max_iterations", "arnoldi_modes", "seed")}}
    cache_key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:16]
    cache = output / f"spectrum_{cache_key}.json"
    if cache.exists():
        saved = json.loads(cache.read_text())
        spectrum = saved["spectrum"] if saved.get("signature") == signature else None
    else:
        spectrum = None
    if spectrum is None:
        spectrum = spectral_stats(recurrence, tolerance=p["arnoldi_tolerance"], max_iterations=p["arnoldi_max_iterations"], modes=p["arnoldi_modes"], seed=p["seed"])
        atomic_write_json(cache, {"signature": signature, "spectrum": spectrum})
    metadata = {"parameters": p, "population": "actual configured neuron_modes.csv, not the larger first-pass partition",
                "neurons": len(neurons), "graded_neurons": int(mask.sum()), "active_graded_neurons": int(active.sum()),
                "graded_recurrent_edges": int(recurrence.nnz), "first_pass_graded_neurons": built["summary"]["first_pass_n_graded"],
                "first_pass_graded_recurrent_edges": built["summary"]["first_pass_edge_partition"]["graded_to_graded"],
                "excluded_CT1_neurons": int(excluded.sum()), "dropped_CT1_edges": len(ledger),
                "dropped_CT1_abs_synapses": float(ledger.signed_synapses.abs().sum()) if len(ledger) else 0.,
                "CT1_point_graded_input_abs_synapses": float(in_weight[ct1].sum()),
                "base_binding": built["summary"], "spectrum_file": str(cache.relative_to(root)),
                "normalization": "Each postsynaptic row denominator counts all incoming graded-source edges retained after CT1 exclusion",
                "gain_equation": "g_DC = kappa / max_Re_lambda; dg/dt = (-g + g_DC*W_normalized*r)/tau_synapse",
                "base_equation_difference": "Base dg/dt=-g/tau_synapse+graded_gain*W*r has DC gain tau_synapse*graded_gain; existing base code is unchanged"}
    return VariantNetwork(neurons, normalized, spiking, mask, excluded, denominator, spectrum, metadata)


def fixed_point(network: VariantNetwork, base: dict, variant: dict) -> dict:
    validate_variant_parameters(variant)
    if not network.spectrum.get("converged") or network.spectrum["max_Re_lambda"] <= 0:
        raise ValueError("A verified positive leading real eigenvalue is required for gain reparameterization")
    gain = variant["kappa"] / network.spectrum["max_Re_lambda"]
    rest = np.where(network.graded_mask, base["graded_rest"], base["v_rest"])
    if np.any(rest <= variant["E_inh"]) or np.any(rest >= variant["E_exc"]):
        raise ValueError("Rest voltage must lie strictly inside the reversal potentials")
    positive = network.graded.maximum(0)
    negative = (-network.graded.minimum(0))
    v = rest.copy()
    relative, absolute, converged = np.inf, np.inf, False
    for iteration in range(1, variant["fixed_point_max_iterations"] + 1):
        release = np.where(network.graded_mask & ~network.excluded, np.maximum(v - base["graded_release"], 0), 0)
        if variant["syn_model"] == "current":
            ge = gain * (network.graded @ release); gi = np.zeros_like(ge)
            target = rest + ge
        else:
            ge = gain * (positive @ release) / (variant["E_exc"] - rest)
            gi = gain * (negative @ release) / (rest - variant["E_inh"])
            target = (rest + ge * variant["E_exc"] + gi * variant["E_inh"]) / (1 + ge + gi)
        target[network.excluded] = rest[network.excluded]
        absolute = float(np.max(np.abs(target - v)))
        relative = absolute / max(1., float(np.max(np.abs(v))), float(np.max(np.abs(target))))
        if not np.isfinite(relative) or not np.isfinite(target).all():
            break
        if relative < variant["fixed_point_tolerance"]:
            converged = True
            break
        v += variant["fixed_point_damping"] * (target - v)
    suprathreshold = (~network.graded_mask & ~network.excluded) & (v > base["v_threshold"])
    return {"voltage": v, "g_exc": ge, "g_inh": gi, "converged": converged,
            "iterations": iteration, "absolute_residual_mV": absolute if np.isfinite(absolute) else None,
            "relative_residual": relative if np.isfinite(relative) else None, "gain": gain,
            "suprathreshold_spiking_neurons": np.flatnonzero(suprathreshold),
            "quiescent_fixed_point": converged and not suprathreshold.any(),
            "interpretation": "Solver nonconvergence is failure to establish a resting state, not proof that no equilibrium exists"}


@nb.njit(cache=True, parallel=True, fastmath=False)
def _advance_variant(v, ge, gi, graded, excluded, last_spike, refractory, active, firing,
                     ring, ring_counts, history, clamps, gp, gx, gd, sp, sx, sd,
                     start, stop, delay, dt, rest, tm, decay_g, threshold_release, gain,
                     v_threshold, reset, spike_weight, e_exc, e_inh, conductance,
                     minimum, maximum, trace_stride, trace_start, peaks, worst, minima, maxima, spike_total):
    for step in range(start, stop):
        for neuron in nb.prange(len(v)):
            history[step % len(history), neuron] = max(v[neuron] - threshold_release, 0.) if graded[neuron] and not excluded[neuron] else 0.
        delayed = (step - delay) % len(history)
        for neuron in nb.prange(len(v)):
            firing[neuron] = False
            active[neuron] = not excluded[neuron] and (graded[neuron] or step - last_spike[neuron] >= refractory[neuron])
            if not active[neuron]:
                continue
            pos, neg = 0., 0.
            for edge in range(gp[neuron], gp[neuron+1]):
                value = gd[edge] * history[delayed, gx[edge]]
                if conductance and value < 0:
                    neg -= value
                else:
                    pos += value
            if conductance:
                total = 1 + ge[neuron] + gi[neuron]
                equilibrium = (rest[neuron] + ge[neuron]*e_exc + gi[neuron]*e_inh) / total
                updated = equilibrium + (v[neuron] - equilibrium)*np.exp(-dt*total/tm[neuron])
                ge[neuron] = ge[neuron]*decay_g[neuron] + (1-decay_g[neuron])*gain*pos/(e_exc-rest[neuron])
                gi[neuron] = gi[neuron]*decay_g[neuron] + (1-decay_g[neuron])*gain*neg/(rest[neuron]-e_inh)
            else:
                dv = np.exp(-dt/tm[neuron])
                updated = rest[neuron] + (v[neuron]-rest[neuron])*dv + ge[neuron]*(1-dv)
                ge[neuron] = ge[neuron]*decay_g[neuron] + (1-decay_g[neuron])*gain*pos
            if updated < minimum:
                updated = minimum; clamps[neuron] += 1
            elif updated > maximum:
                updated = maximum; clamps[neuron] += 1
            v[neuron] = updated
            if not graded[neuron] and updated > v_threshold:
                firing[neuron] = True; active[neuron] = False; last_spike[neuron] = step
        future, count = (step + delay) % len(ring_counts), 0
        for neuron in range(len(v)):
            if firing[neuron]:
                ring[future, count] = neuron; count += 1; spike_total[neuron] += 1
        ring_counts[future] = count
        current = step % len(ring_counts)
        for event in range(ring_counts[current]):
            pre = ring[current, event]
            for edge in range(sp[pre], sp[pre+1]):
                post = sx[edge]
                if active[post]:
                    value = sd[edge]*spike_weight
                    if conductance:
                        if value >= 0: ge[post] += value/(e_exc-rest[post])
                        else: gi[post] -= value/(rest[post]-e_inh)
                    else: ge[post] += value
        ring_counts[current] = 0
        for neuron in nb.prange(len(v)):
            if firing[neuron]:
                v[neuron] = reset; ge[neuron] = 0; gi[neuron] = 0
        if (step + 1) % trace_stride == 0:
            row = (step + 1)//trace_stride - trace_start - 1
            peak, worst_index, low, high = 0., 0, np.inf, -np.inf
            for neuron in range(len(v)):
                if excluded[neuron]: continue
                dvdt = (rest[neuron]-v[neuron]+ge[neuron])/tm[neuron]
                if conductance:
                    dvdt = (rest[neuron]-v[neuron]+ge[neuron]*(e_exc-v[neuron])+gi[neuron]*(e_inh-v[neuron]))/tm[neuron]
                if not graded[neuron] and step+1-last_spike[neuron] < refractory[neuron]: dvdt = 0
                if abs(dvdt) > peak: peak, worst_index = abs(dvdt), neuron
                low = min(low, v[neuron]); high = max(high, v[neuron])
            peaks[row], worst[row], minima[row], maxima[row] = peak, worst_index, low, high


class HybridVariantEngine(LIFEngine):
    """Headless unforced stability runner; no eye or neuromod validation claim."""
    def __init__(self, network: VariantNetwork, base: dict, variant: dict, *, dt=None, threads=1):
        validate_variant_parameters(variant)
        if not network.spectrum.get("converged") or network.spectrum["max_Re_lambda"] <= 0:
            raise ValueError("Verified positive leading real eigenvalue is required")
        self.network, self.variant = network, dict(variant)
        self.gain = variant["kappa"] / network.spectrum["max_Re_lambda"]
        self.graded_mask, self.excluded = network.graded_mask, network.excluded
        self.rest = np.where(self.graded_mask, base["graded_rest"], base["v_rest"])
        self.tm = np.where(self.graded_mask, base["graded_tau_membrane"], base["tau_membrane"])
        self.ts = np.where(self.graded_mask, base["graded_tau_synapse"], base["tau_synapse"])
        if np.any(self.rest <= variant["E_inh"]) or np.any(self.rest >= variant["E_exc"]):
            raise ValueError("Rest must be inside reversal potentials")
        super().__init__(network.spiking, base, dt=dt, threads=threads, clamp=True)
        self.decay_g_each = np.exp(-self.dt/self.ts)

    def reset(self):
        super().reset()
        self.v[:] = self.rest
        self.ge = np.zeros(self.n_neurons); self.gi = np.zeros(self.n_neurons)
        release = np.where(self.graded_mask & ~self.excluded, np.maximum(self.v-self.parameters["graded_release"], 0), 0)
        self.history = np.tile(release, (self.delay_steps+1, 1))
        self.clamps = np.zeros(self.n_neurons, np.int64)
        self.spike_totals = np.zeros(self.n_neurons, np.int64)

    def initialize_fixed_point(self, point: dict, *, perturbation=0., seed=783):
        if not point["quiescent_fixed_point"]:
            raise ValueError("Cannot initialize from an unestablished quiescent fixed point")
        self.reset()
        self.v[:] = point["voltage"]; self.ge[:] = point["g_exc"]; self.gi[:] = point["g_inh"]
        release = np.where(self.graded_mask & ~self.excluded, np.maximum(self.v-self.parameters["graded_release"], 0), 0)
        self.history[:] = release
        if perturbation:
            noise = np.random.default_rng(seed).uniform(-perturbation, perturbation, self.n_neurons)
            self.v[~self.excluded] += noise[~self.excluded]

    def run(self, duration_ms, *, chunk_ms=100):
        steps, chunk = self._steps(duration_ms, "duration_ms"), self._steps(chunk_ms, "chunk_ms")
        stride = self._steps(self.variant["diagnostic_interval_ms"], "diagnostic_interval_ms")
        if chunk < 1 or stride < 1 or self.step % stride or steps % stride:
            raise ValueError("Variant diagnostics require whole aligned diagnostic intervals")
        start, end = self.step, self.step + steps
        peaks = np.empty(steps//stride); worst = np.empty(steps//stride, np.int32)
        minima, maxima = np.empty_like(peaks), np.empty_like(peaks)
        before = self.clamps.copy(); began = time.perf_counter()
        old_threads = nb.get_num_threads(); nb.set_num_threads(self.threads)
        try:
            for a in range(start, end, chunk):
                b = min(a+chunk, end)
                w = self.network.graded
                _advance_variant(self.v, self.ge, self.gi, self.graded_mask, self.excluded,
                                 self.last_spike, self.refractory_steps, self.active, self.firing,
                                 self.ring, self.ring_counts, self.history, self.clamps,
                                 w.indptr, w.indices, w.data, self.csc_indptr, self.csc_indices, self.csc_counts,
                                 a, b, self.delay_steps, self.dt, self.rest, self.tm, self.decay_g_each,
                                 self.parameters["graded_release"], self.gain, self.parameters["v_threshold"],
                                 self.parameters["v_reset"], self.parameters["spike_weight"], self.variant["E_exc"], self.variant["E_inh"],
                                 self.variant["syn_model"] == "conductance", self.parameters["voltage_min"], self.parameters["voltage_max"],
                                 stride, start//stride, peaks, worst, minima, maxima, self.spike_totals)
                self.step = b
                if not all(np.isfinite(x).all() for x in (self.v, self.ge, self.gi)):
                    raise FloatingPointError("Nonfinite variant state")
                check_memory()
        finally:
            nb.set_num_threads(old_threads)
        return {"times_ms": (np.arange(len(peaks))+1)*stride*self.dt + start*self.dt,
                "max_abs_dvdt": peaks, "worst_neuron_indices": worst, "voltage_min": minima, "voltage_max": maxima,
                "final_v": self.v.copy(), "final_g_exc": self.ge.copy(), "final_g_inh": self.gi.copy(),
                "per_neuron_clamps": self.clamps-before, "clamp_count": int((self.clamps-before).sum()),
                "spike_counts": self.spike_totals.copy(), "wall_seconds": time.perf_counter()-began, "completed": True}
