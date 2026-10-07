"""Part III normalized plasticity, with the independently pinned float64 fixture.

The original literal-ODE audit is historical evidence. The final brief explicitly
supersedes that equation, its units, its update order and its reference values.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

from ..fetch import checksum, stat_signature
from ..inspect_data import atomic_write_json
from .sources import require_source_gate

REFERENCE_DELAYS_MS = (-2000, -1500, -1000, -750, -500, -250, 0, 250, 500, 1000, 1500, 2000)
REFERENCE_DELTA_W = (.029344, .036698, .036364, .025960, -.001091, -.052654,
                     -.110433, -.147949, -.156273, -.090804, -.039460, -.017139)
REFERENCE_TOLERANCE = .001
INDEPENDENT_FLOAT32_TOLERANCE = .0002
REFERENCE_FIXTURE = {
    "identity": "Final brief Part III section 1: pinned normalized unit-gain float64 fixture",
    "source": "NEUROMOD_FINAL.md Part III section 1; supplied fixture, no fitting",
    "given": {"dt_ms": 1., "tau_clear_da_ms": 400., "tau_pre_ms": 600.,
              "tau_da_trace_ms": 1500., "A1": 1., "A2": .55, "eta_per_ms": .00055,
              "w0": 1., "odor_onset_ms": 3000., "odor_duration_ms": 1000.,
              "dopamine_duration_ms": 500., "horizon_ms": 7000.,
              "kc_drive": 1., "dopamine_drive": 1., "tau_forget_ms": None},
    "unprovided_assumptions": {},
    "integration": "C, E_pre, E_da using NEW C, then weight using NEW traces; integer-grid pulses",
    "initial_state": "C=E_pre=E_da=0; w=w0=1",
    "units": "r and dr dimensionless [0,1]; traces and C a.u.; eta 1/ms; time ms",
    "historical_audit": "docs/neuromod_reference_findings.md describes superseded literal equations only",
}


def _float32(value, name):
    original = np.asarray(value, dtype=np.float64)
    if not np.isfinite(original).all() or np.any(np.abs(original) > np.finfo(np.float32).max):
        raise ValueError(f"{name} must be finite and representable as float32")
    converted = original.astype(np.float32)
    if np.any((original != 0) & (converted == 0)):
        raise ValueError(f"{name} underflows float32")
    return converted


def normalize_kc_rates(rate_hz, max_rate_hz):
    """Explicit assumed Hz-to-drive conversion; return drive and saturation count."""
    # Filtered rates naturally decay below float32's smallest subnormal. State
    # quantization rounds those rates to zero; coefficient guards stay strict.
    original = np.asarray(rate_hz,dtype=np.float64)
    if not np.isfinite(original).all() or np.any(original<0):
        raise ValueError('KC firing rates must be finite and nonnegative')
    maximum = _float32(max_rate_hz, "KC maximum rate")
    if maximum.ndim != 0 or maximum <= 0:
        raise ValueError("KC rates must be nonnegative and normalization rate positive")
    saturated = int(np.count_nonzero(original > maximum))
    # Clip before division to avoid overflow for an extreme but finite ratio.
    rate = np.minimum(original,maximum).astype(np.float32)
    return (np.minimum(rate, maximum) / maximum).astype(np.float32), saturated


@dataclass(frozen=True)
class PlasticityParameters:
    tau_pre_ms: float = 600.
    tau_da_trace_ms: float = 1500.
    eta_per_ms: float = .00055
    A1: float = 1.
    A2: float = .55
    w_max_multiplier: float = 2.
    tau_forget_ms: float | None = 600000.
    beta: float = 1.

    def validate(self):
        for name, value in asdict(self).items():
            if name == "tau_forget_ms" and value is None:
                continue
            if isinstance(value, bool):
                raise ValueError(f"Boolean plasticity coefficient: {name}")
            _float32(value, name)
        if self.tau_pre_ms <= 0 or self.tau_da_trace_ms <= 0:
            raise ValueError("Eligibility time constants must be positive")
        if self.tau_forget_ms is not None and self.tau_forget_ms <= 0:
            raise ValueError("Forgetting time constant must be positive or None")
        if min(self.eta_per_ms, self.A1, self.A2, self.beta) < 0 or self.w_max_multiplier < 1:
            raise ValueError("Coefficients must be nonnegative and the weight cap must contain w0")


def reference_parameters():
    return PlasticityParameters(tau_forget_ms=None, beta=0.)


def parameters_from_root(root):
    import yaml
    document = yaml.safe_load((Path(root)/"config/neuromod.yaml").read_text())["parameters"]
    values = {name: entry["value"] for name, entry in document.items()}
    # Names correspond to root-owned config; absence never invents production values.
    return PlasticityParameters(**{name: values["plasticity_" + name] for name in asdict(PlasticityParameters())})


@njit(cache=True, fastmath=False)
def _normalized_step(rate, c, pre, compartment, weights, w0, e_pre, e_da,
                     ap, bp, ad, bd, eta, a1, a2, dt, cap, tau_forget, beta, signs, scales):
    """Propose the complete float32 state before commit; overflow never becomes a clamp."""
    new_pre = e_pre * ap + rate * bp
    new_da = e_da * ad + c * bd
    candidate = np.empty_like(weights)
    upper = np.empty_like(weights)
    for i in range(len(new_pre)):
        if not np.isfinite(new_pre[i]):
            raise FloatingPointError("Nonfinite KC trace proposal")
    for k in range(len(new_da)):
        if not np.isfinite(new_da[k]):
            raise FloatingPointError("Nonfinite DA trace proposal")
    for j in range(len(weights)):
        k, p = compartment[j], pre[j]
        forward = a1 * c[k] * new_pre[p]
        backward = a2 * rate[p] * new_da[k]
        forcing = eta * signs[k] * scales[k] * (forward - backward)
        proposed = weights[j] - forcing * dt
        if tau_forget > 0:
            forgetting = (np.float32(1.) + beta * c[k]) * dt / tau_forget
            if not np.isfinite(forgetting):
                raise FloatingPointError("Nonfinite forgetting proposal")
            # Exact forgetting after the specified associative weight update.
            proposed = proposed + (w0[j] - proposed) * -np.expm1(-forgetting)
        upper[j] = cap * w0[j]
        if not (np.isfinite(forward) and np.isfinite(backward) and np.isfinite(forcing)
                and np.isfinite(proposed) and np.isfinite(upper[j])):
            raise FloatingPointError("Nonfinite normalized plasticity proposal before clipping")
        candidate[j] = proposed
        if not np.isfinite(candidate[j]):
            raise FloatingPointError("Weight proposal overflows float32")
    clamps, movement = 0, 0.
    for j in range(len(weights)):
        proposed = candidate[j]
        if proposed < 0:
            proposed = np.float32(0.)
            clamps += 1
        elif proposed > upper[j]:
            proposed = upper[j]
            clamps += 1
        movement += abs(np.float64(proposed) - np.float64(weights[j]))
        weights[j] = proposed
    e_pre[:] = new_pre
    e_da[:] = new_da
    return clamps, movement


class NormalizedPlasticity:
    """Float32 per-KC/per-compartment traces and indexed plastic edge weights.

    The field is owned by Layer 2: call field.step first, then pass its new DA
    concentration here. KC input is dimensionless normalized drive, never raw Hz.
    """
    def __init__(self, n_kc, n_compartments, pre_index, compartment_index, w0,
                 parameters=None, *, compartment_sign=None, compartment_scale=None):
        if not isinstance(n_kc, int) or not isinstance(n_compartments, int) or min(n_kc, n_compartments) < 1:
            raise ValueError("Positive KC and compartment counts are required")
        self.parameters = parameters or PlasticityParameters()
        self.parameters.validate()
        pre, compartment = np.asarray(pre_index), np.asarray(compartment_index)
        if pre.ndim != 1 or compartment.shape != pre.shape or not np.issubdtype(pre.dtype, np.integer) or not np.issubdtype(compartment.dtype, np.integer):
            raise ValueError("Plastic edge indices must be matching integer vectors")
        if np.any((pre < 0) | (pre >= n_kc)) or np.any((compartment < 0) | (compartment >= n_compartments)):
            raise ValueError("Plastic edge indices out of bounds")
        self.pre_index, self.compartment_index = pre.astype(np.int32), compartment.astype(np.int32)
        self.w0 = _float32(w0, "Baseline weights").copy()
        if self.w0.shape != pre.shape or np.any(self.w0 < 0):
            raise ValueError("Each edge requires one nonnegative baseline weight")
        _float32(self.parameters.w_max_multiplier * self.w0.astype(np.float64), "Upper weight bounds")
        self.compartment_sign = _float32(np.ones(n_compartments) if compartment_sign is None else compartment_sign, "Compartment signs")
        self.compartment_scale = _float32(np.ones(n_compartments) if compartment_scale is None else compartment_scale, "Compartment scales")
        if self.compartment_sign.shape != (n_compartments,) or not np.isin(self.compartment_sign, [-1., 1.]).all():
            raise ValueError("Each compartment sign must be -1 or +1")
        if self.compartment_scale.shape != (n_compartments,) or np.any(self.compartment_scale < 0):
            raise ValueError("Each compartment scale must be nonnegative")
        self.weights = self.w0.copy()
        self.e_pre, self.e_da = np.zeros(n_kc, np.float32), np.zeros(n_compartments, np.float32)
        self.weight_clamp_events, self.total_absolute_weight_change = 0, 0.
        self._coefficients = {}

    def step(self, kc_drive, dopamine_au, dt_ms):
        rate, c = _float32(kc_drive, "KC drive"), _float32(dopamine_au, "DA concentration")
        if rate.shape != self.e_pre.shape or c.shape != self.e_da.shape:
            raise ValueError("Drive/concentration shape differs from trace state")
        if np.any((rate < 0) | (rate > 1)) or np.any((c < 0) | (c > 5)):
            raise ValueError("KC drive must be in [0,1], field concentration in [0,5] a.u.")
        dt = _float32(dt_ms, "Plasticity timestep")
        if dt.ndim != 0 or isinstance(dt_ms, bool) or dt <= 0:
            raise ValueError("Plasticity timestep must be finite and positive")
        if not all(np.isfinite(v).all() for v in (self.weights, self.w0, self.e_pre, self.e_da)):
            raise FloatingPointError("Nonfinite state before plasticity step")
        if np.any((self.e_pre < 0) | (self.e_pre > 1)) or np.any((self.e_da < 0) | (self.e_da > 5)):
            raise ValueError("Trace state outside normalized input bounds")
        p = self.parameters
        key = float(dt)
        if key not in self._coefficients:
            ap, ad = np.exp(-key / p.tau_pre_ms), np.exp(-key / p.tau_da_trace_ms)
            self._coefficients[key] = tuple(np.float32(v) for v in (ap, 1.-ap, ad, 1.-ad))
        ap, bp, ad, bd = self._coefficients[key]
        if bp <= 0 or bd <= 0:
            raise ValueError("Plasticity timestep loses the normalized trace increment")
        clamps, movement = _normalized_step(rate, c, self.pre_index, self.compartment_index,
            self.weights, self.w0, self.e_pre, self.e_da, ap, bp, ad, bd,
            np.float32(p.eta_per_ms), np.float32(p.A1), np.float32(p.A2), np.float32(dt),
            np.float32(p.w_max_multiplier), np.float32(0. if p.tau_forget_ms is None else p.tau_forget_ms),
            np.float32(p.beta), self.compartment_sign, self.compartment_scale)
        self.weight_clamp_events += clamps
        self.total_absolute_weight_change += movement
        return self.weights.copy()


def _steps(time_ms, dt_ms):
    steps = int(round(time_ms / dt_ms))
    if not np.isclose(steps * dt_ms, time_ms, rtol=0, atol=1e-8):
        raise ValueError("Reference timing must fit integer timestep grid")
    return steps


def reference_curve(dt_ms=1., delays_ms=REFERENCE_DELAYS_MS, *, production=False):
    """Independent float64 five-line fixture, or separately implemented production kernel."""
    if not np.isfinite(dt_ms) or dt_ms <= 0 or not np.isclose(dt_ms / .1, round(dt_ms / .1), atol=1e-8, rtol=0):
        raise ValueError("Reference dt must be a positive integer multiple of 0.1 ms")
    f = REFERENCE_FIXTURE["given"]
    n = len(delays_ms)
    if n == 0:
        raise ValueError("Reference requires at least one delay")
    dtype = np.float32 if production else np.float64
    c, ep, ed, w = np.zeros(n, dtype), dtype(0.), np.zeros(n, dtype), np.ones(n, dtype)
    kernel = NormalizedPlasticity(1, n, np.zeros(n, np.int32), np.arange(n, dtype=np.int32), w, reference_parameters()) if production else None
    ac, ap, ad = (dtype(np.exp(-dt_ms/f[key])) for key in ("tau_clear_da_ms", "tau_pre_ms", "tau_da_trace_ms"))
    bc, bp, bd = (dtype(1.-np.exp(-dt_ms/f[key])) for key in ("tau_clear_da_ms", "tau_pre_ms", "tau_da_trace_ms"))
    on, end = _steps(f["odor_onset_ms"], dt_ms), _steps(f["odor_onset_ms"] + f["odor_duration_ms"], dt_ms)
    pulse_on = np.array([_steps(f["odor_onset_ms"] + d, dt_ms) for d in delays_ms])
    pulse_end = pulse_on + _steps(f["dopamine_duration_ms"], dt_ms)
    total = _steps(f["horizon_ms"], dt_ms)
    if np.any(pulse_on < 0) or np.any(pulse_end >= total):
        raise ValueError("Reference pulse outside pinned horizon")
    movement, peak = 0., 0.
    for tick in range(total):
        r = dtype(float(on <= tick < end))
        dr = ((pulse_on <= tick) & (tick < pulse_end)).astype(dtype)
        c = c * ac + dr * bc
        if production:
            kernel.step(np.array([r], dtype), c, dt_ms)
        else:
            ep = ep * ap + r * bp
            ed = ed * ad + c * bd
            change = f["eta_per_ms"] * (f["A1"] * c * ep - f["A2"] * r * ed) * dt_ms
            w -= change
            movement += float(np.abs(change).sum())
        peak = max(peak, float(c.max()))
    if production:
        w, movement = kernel.weights, kernel.total_absolute_weight_change
    measured = w.astype(float) - 1.
    expected = np.array(REFERENCE_DELTA_W) if tuple(delays_ms) == REFERENCE_DELAYS_MS else None
    return {"dt_ms": dt_ms, "delays_ms": list(delays_ms), "delta_w": measured.tolist(), "peak_da_au": peak,
            "weight_clamp_events": kernel.weight_clamp_events if production else 0, "concentration_clamp_events": 0,
            "total_absolute_weight_change": movement, "state_dtype": np.dtype(dtype).name,
            "max_absolute_reference_error": float(np.abs(measured-expected).max()) if expected is not None else None}


def production_reference_curve(dt_ms=1., delays_ms=REFERENCE_DELAYS_MS):
    return reference_curve(dt_ms, delays_ms, production=True)


def assert_reference_curve(curve):
    if "delays_ms" not in curve or tuple(curve["delays_ms"]) != REFERENCE_DELAYS_MS:
        raise AssertionError("Reference curve requires the exact ordered reference delays")
    measured = np.asarray(curve["delta_w"], float)
    if measured.shape != (12,) or not np.isfinite(measured).all():
        raise AssertionError("Reference curve requires twelve finite values")
    residual = np.abs(measured-REFERENCE_DELTA_W)
    if np.any(residual > REFERENCE_TOLERANCE):
        raise AssertionError(f"Normalized Part III reference mismatch: max absolute error {residual.max():.9g}")


def pairing_summary(curve):
    delays, values = np.asarray(curve["delays_ms"]), np.asarray(curve["delta_w"])
    crossing = np.flatnonzero(values[:-1] * values[1:] < 0)
    crossover = None
    if len(crossing) == 1:
        i = crossing[0]
        crossover = float(delays[i] - values[i] * (delays[i+1]-delays[i])/(values[i+1]-values[i]))
    return {"crossover_ms": crossover, "crossover_method": "linear interpolation between measured adjacent delays",
            "peak_depression_delay_ms": int(delays[np.argmin(values)]),
            "forward_sum": float(values[delays > 0].sum()), "backward_sum": float(values[delays < 0].sum())}


def load_compartment_rules(root, names):
    """Per-compartment assumptions remain a table; literature is not a magnitude fit."""
    rows = pd.read_csv(Path(root) / "config/compartment_rules.csv", keep_default_na=False)
    required = {"compartment", "sign", "magnitude", "provenance", "citation", "note"}
    if not required.issubset(rows.columns) or rows.compartment.duplicated().any():
        raise ValueError("Invalid per-compartment plasticity rule schema")
    by_name = rows.set_index("compartment")
    if set(by_name.index) != set(names):
        raise ValueError("Plasticity rule table must cover exactly the fifteen MB compartments")
    signs, magnitudes = [], []
    for name in names:
        row = by_name.loc[name]
        if row.provenance != "ASSUMPTION" or not row.citation or not row.note:
            raise ValueError("Current compartment rules require explicit assumption and citation")
        signs.append(float(row.sign))
        magnitudes.append(float(row.magnitude))
    if not np.isin(signs, [-1., 1.]).all() or not np.isfinite(magnitudes).all() or min(magnitudes) < 0:
        raise ValueError("Invalid per-compartment sign or magnitude")
    return np.asarray(signs, np.float32), np.asarray(magnitudes, np.float32), rows.to_dict("records")


@dataclass
class CorePlasticity:
    kernel: NormalizedPlasticity
    kc_indices: np.ndarray
    edge_data_indices: np.ndarray
    compartment_names: tuple[str, ...]
    metadata: dict


def build_core_plasticity(root, core=None, *, parameters=None):
    """Map the actual retained core CSR entries; never create or remap an edge."""
    from .core import load_core
    from .compartments import load_compartments
    root = Path(root)
    core = load_core(root) if core is None else core
    mapping = load_compartments(root)
    names = tuple(mapping.names[:15])
    ct = core.neurons.cell_type.fillna("")
    kc, mbon = ct.str.startswith("KC").to_numpy(bool), ct.str.startswith("MBON").to_numpy(bool)
    kc_indices = np.flatnonzero(kc).astype(np.int32)
    pre_position = np.full(len(kc), -1, np.int32)
    pre_position[kc_indices] = np.arange(len(kc_indices), dtype=np.int32)
    rows = np.repeat(np.arange(len(kc), dtype=np.int32), np.diff(core.counts.indptr))
    chosen = np.flatnonzero(mbon[rows] & kc[core.counts.indices]).astype(np.int32)
    edge_compartment = mapping.mb_assignment[core.model_indices[rows[chosen]]]
    if len(chosen) != 62261 or int(core.counts.data[chosen].sum()) != 256719 or np.any((edge_compartment < 0) | (edge_compartment >= 15)):
        raise ValueError("Actual plastic edge census or empirical compartment assignment changed")
    signs, scales, rules = load_compartment_rules(root, names)
    p = parameters_from_root(root) if parameters is None else parameters
    kernel = NormalizedPlasticity(len(kc_indices), 15, pre_position[core.counts.indices[chosen]],
                                 edge_compartment, core.counts.data[chosen], p,
                                 compartment_sign=signs, compartment_scale=scales)
    metadata = {"edges": len(chosen), "baseline_synapses": 256719, "KCs": len(kc_indices),
                "kc_kc_mode": core.metadata["kc_kc_mode"], "rules": rules,
                "compartment_edge_counts": {name: int(np.count_nonzero(edge_compartment == k)) for k, name in enumerate(names)},
                "weight_unit": "synapse-count equivalent; supplied eta gives absolute per-edge count changes",
                "normalization": "KC firing rate / explicitly configured max_kc_rate_hz, capped at 1; saturation counted",
                "assignment": "empirical MBON cluster from compartments.npz; no canonical remapping"}
    return CorePlasticity(kernel, kc_indices, chosen, names, metadata)
def require_receptor_gate(root):
    from .receptors import require_field_gate
    root = Path(root)
    require_source_gate(root)
    require_field_gate(root)
    record = json.loads((root / "build/validation_neuromod_receptors.json").read_text())
    if record.get("gate") != "V-NM-A" or record.get("status") != "PASS" or not record.get("checks") or any(c["status"] != "PASS" for c in record["checks"]):
        raise ValueError("Stage 4 V-NM-A is not a complete PASS")
    for field, base in (("implementation_hashes", root), ("dependency_hashes", root),
                        ("config_hashes", root / "config"), ("artifact_hashes", root / "build"),
                        ("base_artifact_hashes", root / "build"), ("base_config_hashes", root / "config")):
        if not record.get(field):
            raise ValueError(f"Stage 4 lacks provenance: {field}")
        for name, digest in record[field].items():
            if checksum(base / name) != digest:
                raise ValueError(f"Stage 4 evidence changed: {name}")
    return record



def software_checks():
    """Executable bounds/history/eta checks, independent of a network outcome."""
    from dataclasses import replace
    checks = []
    def record(name, observed, expected):
        observed = observed.item() if isinstance(observed, np.generic) else observed
        expected = expected.item() if isinstance(expected, np.generic) else expected
        checks.append({"name": name, "observed": observed, "expected": expected,
                       "status": "PASS" if observed == expected else "FAIL"})
    def single(**changes):
        return NormalizedPlasticity(1, 1, np.array([0]), np.array([0]), [1.], replace(reference_parameters(), **changes))
    absent_da, absent_kc = single(), single()
    for _ in range(1000):
        absent_da.step([1], [0], 1.)
        absent_kc.step([0], [1], 1.)
    record("no_DA_throughout_history_no_association", float(absent_da.weights[0]), 1.)
    record("no_KC_throughout_history_no_association", float(absent_kc.weights[0]), 1.)
    forward, backward = single(), single()
    forward.step([1], [0], 100.)
    forward.step([0], [1], 100.)
    backward.step([0], [1], 100.)
    backward.step([1], [0], 100.)
    record("history_forward_depresses_backward_potentiates", bool(forward.weights[0] < 1 < backward.weights[0]), True)
    record("current_zero_input_does_not_erase_trace_history", bool(forward.weights[0] != 1 and backward.weights[0] != 1), True)
    low, high = single(eta_per_ms=.000055), single(eta_per_ms=.00055)
    for obj in (low, high):
        obj.e_pre[:] = .7
        obj.step([0], [1], 100.)
    ratio = float((1.-high.weights[0])/(1.-low.weights[0]))
    record("eta_decade_linear_unclipped", abs(ratio-10.) < .001, True)
    record("eta_decade_zero_clamps", low.weight_clamp_events + high.weight_clamp_events, 0)
    depression, potentiation = single(eta_per_ms=10.), single(eta_per_ms=10.)
    depression.e_pre[:] = 1.
    depression.step([0], [1], 1.)
    potentiation.e_da[:] = 1.
    potentiation.step([1], [0], 1.)
    record("lower_and_upper_bounds", [float(depression.weights[0]), float(potentiation.weights[0])], [0., 2.])
    record("clamps_and_absolute_change_are_logged", [depression.weight_clamp_events, potentiation.weight_clamp_events,
           depression.total_absolute_weight_change, potentiation.total_absolute_weight_change], [1, 1, 1., 1.])
    forget = single(tau_forget_ms=600000., beta=1.)
    forget.weights[:] = .5
    forget.step([0], [0], 1000.)
    expected = 1. - .5*np.exp(-1000./600000.)
    record("zero_input_forgetting_matches_analytic_not_invariance", abs(float(forget.weights[0])-expected) < 1e-7, True)
    isolated = NormalizedPlasticity(1, 2, np.array([0, 0]), np.array([0, 1]), [1., 1.], reference_parameters())
    isolated.step([1], [1, 0], 100.)
    record("unexposed_compartment_unchanged", bool(isolated.weights[0] < 1 and isolated.weights[1] == 1), True)
    return checks, {"eta_decade_ratio": ratio, "zero_input_forgetting_delta": float(forget.weights[0]-.5)}


def validate_plasticity(root: Path) -> dict:
    """V-NM-E: corrected reference, full software checks, and actual edge mapping."""
    root = Path(root).resolve()
    output = root / "build"
    output.mkdir(parents=True, exist_ok=True)
    result = {"gate": "V-NM-E", "kind": "software", "status": "FAIL", "stage": "normalized_plasticity",
              "created_at": datetime.now(timezone.utc).isoformat(), "checks": [], "fixture": REFERENCE_FIXTURE,
              "fixture_sha256": hashlib.sha256(json.dumps(REFERENCE_FIXTURE, sort_keys=True, allow_nan=False).encode()).hexdigest(),
              "fitting_performed": False, "network_training_executed": False,
              "history_caveat": "Zero input throughout relevant history at baseline is invariant; current zero input alone is not. Finite forgetting changes nonbaseline weights.",
              "supersedes": "Final brief Part III section 1 explicitly replaces the old literal equations and reference; historical audit remains unchanged.",
              "artifact_hashes": {}}
    path = output / "validation_neuromod_plasticity.json"
    atomic_write_json(path, result)
    def check(name, observed, expected):
        result["checks"].append({"name": name, "observed": observed, "expected": expected,
                                 "status": "PASS" if observed == expected else "FAIL"})
    try:
        source = require_source_gate(root)
        require_receptor_gate(root)
        for field in ("source_hashes", "source_stats", "base_artifact_hashes", "base_config_hashes"):
            result[field] = source[field]
        result["config_hashes"] = {name: checksum(root / "config" / name) for name in
                                   ("parameters.yaml", "neuromod.yaml", "receptors.csv", "compartment_rules.csv")}
        result["implementation_hashes"] = {"src/flybrain/neuromod/plasticity.py": checksum(Path(__file__))}
        result["dependency_hashes"] = {name: checksum(root/name) for name in (
            "build/validation_neuromod_sources.json", "build/validation_neuromod_receptors.json",
            "build/validation_neuromod_compartments.json", "build/compartments.npz", "NEUROMOD_FINAL.md")}
        curve = reference_curve()
        assert_reference_curve(curve)  # First stage-5 assertion, before actual edge mapping.
        check("twelve_point_reference_within_1e-3", True, True)
        production, refined = production_reference_curve(), reference_curve(.5)
        assert_reference_curve(production)
        measured = np.asarray(curve["delta_w"])
        production_error = float(np.max(np.abs(measured-production["delta_w"])))
        check("float32_matches_pinned_float64_within_2e-4", production_error <= INDEPENDENT_FLOAT32_TOLERANCE, True)
        check("float32_state", production["state_dtype"], "float32")
        check("zero_reference_clamps", production["weight_clamp_events"] + production["concentration_clamp_events"], 0)
        check("half_dt_reference_within_2e-4", float(np.max(abs(measured-refined["delta_w"]))) < .0002, True)
        checks, extra_metrics = software_checks()
        result["checks"].extend(checks)
        actual = build_core_plasticity(root)
        check("actual_KC_MBON_edges", actual.metadata["edges"], 62261)
        check("actual_KC_MBON_synapses", actual.metadata["baseline_synapses"], 256719)
        check("actual_KC_count", actual.metadata["KCs"], 5177)
        check("fifteen_compartment_rules", len(actual.metadata["rules"]), 15)
        # Exercise every mapped edge using a fixed explicit random drive fixture.
        rng = np.random.default_rng(783)
        for _ in range(100):
            actual.kernel.step(rng.random(len(actual.kc_indices)), rng.random(15), 1.)
        check("all_actual_edges_finite_and_bounded", bool(np.isfinite(actual.kernel.weights).all()
              and np.all(actual.kernel.weights >= 0) and np.all(actual.kernel.weights <= actual.kernel.parameters.w_max_multiplier*actual.kernel.w0)), True)
        check("actual_edge_fixture_zero_clamps", actual.kernel.weight_clamp_events, 0)
        result["core_edge_fixture"] = actual.metadata | {"drive": "ASSUMPTION: NumPy default_rng seed783, 100 uniform drive steps; software bounds only, not biological activity"}
        result["metrics"] = {"max_absolute_reference_error": curve["max_absolute_reference_error"],
            "reference_tolerance": REFERENCE_TOLERANCE, "reference_points_within_tolerance": 12,
            "max_error_float32_against_pinned_float64": production_error,
            "independent_float32_tolerance": INDEPENDENT_FLOAT32_TOLERANCE,
            "max_delta_halving_dt": float(np.max(abs(measured-refined["delta_w"]))),
            "weight_clamp_events": production["weight_clamp_events"], "concentration_clamp_events": 0,
            "total_absolute_weight_change": production["total_absolute_weight_change"],
            **pairing_summary(curve), **extra_metrics}
        result["curve"], result["production_curve"], result["half_dt_curve"] = curve, production, refined
        table = pd.DataFrame({"delay_ms": REFERENCE_DELAYS_MS, "reference_delta_w": REFERENCE_DELTA_W,
            "normalized_float64_delta_w": measured, "production_float32_delta_w": production["delta_w"],
            "signed_residual": measured-REFERENCE_DELTA_W, "absolute_residual": abs(measured-REFERENCE_DELTA_W),
            "within_1e_3": abs(measured-REFERENCE_DELTA_W) <= REFERENCE_TOLERANCE, "half_dt_delta_w": refined["delta_w"]})
        table.to_csv(output/"plasticity_reference_curve.csv", index=False)
        result["artifact_hashes"] = {"plasticity_reference_curve.csv": checksum(output/"plasticity_reference_curve.csv")}
        for field, base in (("config_hashes", root/"config"), ("implementation_hashes", root), ("dependency_hashes", root)):
            for name, digest in result[field].items():
                if checksum(base/name) != digest:
                    raise ValueError(f"Input changed during plasticity validation: {name}")
        for name, digest in result["source_hashes"].items():
            if checksum(root/"data/raw"/name) != digest or stat_signature(root/"data/raw"/name) != result["source_stats"][name]:
                raise ValueError(f"Source changed during plasticity validation: {name}")
        require_receptor_gate(root)
    except Exception as exc:
        check("plasticity_gate_execution", {"type": type(exc).__name__, "error": str(exc)}, "no errors")
    result["failed_checks"] = [c["name"] for c in result["checks"] if c["status"] != "PASS"]
    result["status"] = "FAIL" if result["failed_checks"] else "PASS"
    atomic_write_json(path, result)
    return result
