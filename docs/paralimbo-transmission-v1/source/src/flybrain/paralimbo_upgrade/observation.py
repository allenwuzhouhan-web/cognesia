"""Physical-time observation, separate from neural dynamics and response fitting.

T4: point voltage is an explicitly labelled hypothesis for an electrode readout.
The centered acquisition FIR is noncausal; causal responses are integrated first.
No holding-current conversion or voltage-to-calcium conversion is implicit here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

import numpy as np
from scipy.signal import firwin

from .interfaces import INTERFACE_VERSION, ObservationSpec, identity

OBSERVATION_VERSION = "area05-observation-v1"
T4_GRID_MS = 2.0
T4_BASELINE_MS = (-200.0, -20.0)


def _array(value, name, ndim=None):
    result = np.asarray(value, dtype=np.float64)
    if (ndim is not None and result.ndim != ndim) or not result.size or not np.isfinite(result).all():
        raise ValueError(f"invalid finite {name}")
    return result


def _times(value, name):
    result = _array(value, name, 1)
    if np.any(np.diff(result) <= 0):
        raise ValueError(f"{name} must be strictly increasing")
    return result


@dataclass(frozen=True)
class CellAssignment:
    """One condition-invariant latent assignment per recorded cell.

    Unknowns must be named assumptions, never inferred from each case's outcome.
    Physical pA holding current is retained as metadata, not interpreted as mV.
    """
    cell_id: str
    registration_id: str
    root_ids: tuple[str, ...]
    weights: tuple[float, ...]
    subtype: str
    receptive_field: str
    holding_state: str
    evidence_class: str
    scope: str
    assumptions: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ("cell_id", "registration_id", "subtype", "receptive_field", "holding_state"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"declare {name}, including unknown treatment")
        object.__setattr__(self, "root_ids", tuple(str(x) for x in self.root_ids))
        object.__setattr__(self, "weights", tuple(float(x) for x in self.weights))
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        weights = _array(self.weights, "membership weights", 1)
        if not self.root_ids or len(set(self.root_ids)) != len(self.root_ids) or len(weights) != len(self.root_ids):
            raise ValueError("unique root membership required")
        if np.any(weights < 0) or not np.isclose(weights.sum(), 1., rtol=0, atol=1e-12):
            raise ValueError("membership weights must sum to one")
        if self.scope not in {"fixture", "restricted_hypothesis", "supported_native"}:
            raise ValueError("unknown observation scope")
        if self.evidence_class not in {"measured", "independently_supported", "transferred", "development_estimated", "assumed", "unsupported", "synthetic"}:
            raise ValueError("unknown evidence class")
        if self.scope == "supported_native" and self.evidence_class not in {"measured", "independently_supported"}:
            raise ValueError("supported native observation requires supported evidence")
        if self.scope != "supported_native" and not self.assumptions:
            raise ValueError("fixture/hypothesis needs explicit assumptions")

    @property
    def digest(self):
        return identity(asdict(self))


def validate_cell_assignments(assignments: Sequence[CellAssignment]):
    """Reject condition-specific changes to membership or latent treatment."""
    known = {}
    for assignment in assignments:
        if assignment.cell_id in known and known[assignment.cell_id] != assignment.digest:
            raise ValueError("cell identity changed across conditions")
        known[assignment.cell_id] = assignment.digest
    if not known:
        raise ValueError("empty cell registry")
    return known


def t4_observation_spec(observation_id: str, assignment: CellAssignment, *, filter_step_ms=.25):
    """New observation identity; retain historical grid/baseline/FIR definition.

    Filter quadrature must be refined by area 06 before biological use; .25 ms
    is a fixture default, not a numerical certificate for a real experiment.
    """
    return ObservationSpec(
        observation_id=observation_id, units="mV", root_ids=assignment.root_ids,
        state_variable="voltage_mv",
        filter_spec={"kind": "centered_kaiser_fir", "half_width_ms": 20., "cutoff_hz": 250.,
                     "beta": 5., "step_ms": float(filter_step_ms)},
        baseline_spec={"kind": "mean", "window_ms": list(T4_BASELINE_MS), "end_exclusive": True},
        repeat_aggregation="equal_eligible_repeat_mean",
        parameters={"version": OBSERVATION_VERSION, "sample_ms": T4_GRID_MS,
                    "target": "baseline_relative_membrane_voltage", "assignment": asdict(assignment),
                    "assignment_identity": assignment.digest,
                    "soma_to_point_neuron": "supported" if assignment.scope == "supported_native" else "explicit_hypothesis",
                    "resampling": "linear_in_physical_time_no_extrapolation"})


def observation_contract(spec: ObservationSpec):
    """Serializable equations and scope for the coordinator's budgeted writer."""
    return {"interface_version": INTERFACE_VERSION, "specification": spec.to_dict(),
            "observation_identity": spec.digest,
            "equations": {"membership": "v(t)=sum_j w_j V_j(t); sum_j w_j=1",
                          "event_response": "r(t)=sum_i a_i [H(t-on_i)-H(t-off_i)]; H(s)=1-exp(-max(s,0)/tau)",
                          "acquisition": "z(t)=sum_k h_k v(t-offset_k)",
                          "baseline": "b_r=mean(z_r(t): -200<=t<-20); y_r(t)=z_r(t)-b_r",
                          "repeats": "y(t)=sum_r y_r(t)/R; SEM=sample_sd(y_r(t))/sqrt(R)"},
            "limits": ["baseline subtraction does not identify holding current",
                       "centered acquisition filter may use samples up to 20 ms after output time",
                       "point-neuron voltage is not automatically a somatic electrode measurement",
                       "calcium percentage points never converted to voltage",
                       "existing T4 outcomes remain retrospective"]}


def causal_interval_response(on_ms, off_ms, levels, sample_ms, tau_ms):
    """Exact exponential-kernel integral over actual nonoverlapping intervals.

    Levels and output have the same unit; kernel exp(-s/tau)/tau has unit 1/ms.
    No snapping to observation bins, nominal dwell or condition IDs is used.
    """
    on, off = _array(on_ms, "onset", 1), _array(off_ms, "offset", 1)
    levels = _array(levels, "levels")
    times = _times(sample_ms, "sample times")
    tau = float(tau_ms)
    if not np.isfinite(tau) or tau <= 0 or levels.ndim not in (1, 2):
        raise ValueError("positive finite tau and vector/matrix levels required")
    if len(on) != len(off) or len(on) != len(levels) or np.any(off <= on) or np.any(on[1:] < off[:-1]):
        raise ValueError("controller intervals must be ordered and nonoverlapping")
    # Use expm1 for short intervals to avoid catastrophic cancellation in tails.
    elapsed = times[:, None] - on
    duration = off - on
    active_length = np.minimum(np.maximum(elapsed, 0.), duration)
    decay = np.maximum(times[:, None] - off, 0.)
    mass = -np.expm1(-active_length / tau) * np.exp(-decay / tau)
    return mass @ levels


def acquisition_fir(filter_spec: Mapping):
    if filter_spec.get("kind") == "none":
        return np.array([0.]), np.array([1.])
    if filter_spec.get("kind") != "centered_kaiser_fir":
        raise ValueError("unregistered observation filter")
    step = float(filter_spec["step_ms"])
    if not np.isfinite(step) or not 0 < step < 2.:
        raise ValueError("FIR step must be finite, positive and below 2 ms")
    if any(float(filter_spec[k]) != v for k, v in (("half_width_ms", 20.), ("cutoff_hz", 250.), ("beta", 5.))):
        raise ValueError("changed acquisition filter requires a new implementation contract")
    half = int(round(20. / step))
    if not np.isclose(half * step, 20., rtol=0, atol=1e-10) or half > 1_000_000:
        raise ValueError("FIR step must divide its support within the bounded workspace")
    return np.arange(-half, half + 1) * step, firwin(2 * half + 1, .5 * step, window=("kaiser", 5.))


def baseline_relative(time_ms, values, window_ms=T4_BASELINE_MS):
    time = _times(time_ms, "baseline grid")
    data = _array(values, "baseline values")
    lo, hi = map(float, window_ms)
    if not np.isfinite([lo, hi]).all() or lo >= hi or data.shape[0] != len(time):
        raise ValueError("invalid baseline window or shape")
    selected = (time >= lo) & (time < hi)
    if not selected.any() or time[0] > lo or time[-1] < hi:
        raise ValueError("missing complete baseline support")
    base = data[selected].mean(axis=0)
    return data - base, base


def observe_trace(time_ms, states, root_ids, spec: ObservationSpec, sample_time_ms, *,
                  source_units: str, event_onset_ms=0.):
    """Map one repeat of explicit physical state into one registered observable.

    ``time_ms`` and onset share the controller clock; output times are relative
    to onset. States are time by root; source support must include FIR margins.
    No clipping, padding, extrapolation, implicit unit conversion or outcome I/O.
    """
    times, samples = _times(time_ms, "state clock"), _times(sample_time_ms, "observation grid")
    roots = tuple(str(x) for x in root_ids)
    if len(roots) != len(set(roots)) or source_units != spec.units:
        raise ValueError("unique roots and identical explicit physical units required")
    if not np.isfinite(event_onset_ms):
        raise ValueError("finite physical onset required")
    if spec.state_variable not in states:
        raise ValueError("missing registered state variable")
    if spec.state_variable == "voltage_mv" and source_units != "mV":
        raise ValueError("voltage requires physical mV")
    if spec.units == "deltaF/F_percentage_points" and spec.state_variable != "calcium_percentage_points":
        raise ValueError("calcium observation requires an explicit calcium state")
    values = _array(states[spec.state_variable], "state values", 2)
    if values.shape != (len(times), len(roots)):
        raise ValueError("state shape must be time by root")
    if not set(spec.root_ids).issubset(roots):
        raise ValueError("missing registered observation member")
    assignment_data = spec.parameters.get("assignment")
    if assignment_data is None:
        raise ValueError("observation requires a fixed cell assignment")
    assignment = CellAssignment(**assignment_data)
    if assignment.digest != spec.parameters.get("assignment_identity") or tuple(spec.root_ids) != assignment.root_ids:
        raise ValueError("observation assignment identity changed")
    sample_step = float(spec.parameters.get("sample_ms", T4_GRID_MS))
    if not np.isfinite(sample_step) or sample_step <= 0 or not np.allclose(np.diff(samples), sample_step, rtol=0, atol=1e-9):
        raise ValueError("observation grid differs from registered sampling interval")
    trace = values[:, [roots.index(r) for r in spec.root_ids]] @ np.asarray(assignment.weights)
    offsets, weights = acquisition_fir(spec.filter_spec)
    targets = samples + float(event_onset_ms)
    if targets[0] - offsets[-1] < times[0] - 1e-9 or targets[-1] - offsets[0] > times[-1] + 1e-9:
        raise ValueError("source trace does not cover observation and FIR support")
    # One output at a time bounds workspace even for the historical fine FIR.
    filtered = np.array([weights @ np.interp(t - offsets, times, trace) for t in targets])
    baseline = 0.
    if spec.baseline_spec.get("kind") == "mean":
        if spec.baseline_spec.get("end_exclusive") is not True:
            raise ValueError("baseline must declare exclusive end")
        filtered, baseline = baseline_relative(samples, filtered, spec.baseline_spec["window_ms"])
    elif spec.baseline_spec.get("kind") != "none":
        raise ValueError("unknown baseline operation")
    return {"time_ms": samples, "values": filtered, "baseline": float(baseline),
            "units": spec.units, "observation_identity": spec.digest,
            "assignment_identity": assignment.digest, "scope": assignment.scope}


def aggregate_repeats(repeats: Mapping[str, Mapping], eligible_repeat_ids, spec: ObservationSpec):
    """Equal eligible-repeat mean; unavailable repeats fail instead of disappearing."""
    ids = tuple(eligible_repeat_ids)
    if spec.repeat_aggregation != "equal_eligible_repeat_mean" or not ids or len(set(ids)) != len(ids):
        raise ValueError("unique nonempty eligible repeat inventory required")
    if set(repeats) != set(ids):
        raise ValueError("repeat coverage differs from the frozen eligible inventory")
    first = repeats[ids[0]]
    rows = []
    for rid in ids:
        item = repeats[rid]
        if item["units"] != spec.units or item["observation_identity"] != spec.digest or not np.array_equal(item["time_ms"], first["time_ms"]):
            raise ValueError("repeat observation contract or grid differs")
        rows.append(_array(item["values"], "repeat", 1))
    matrix = np.stack(rows)
    return {"time_ms": np.asarray(first["time_ms"]), "mean": matrix.mean(axis=0),
            "sem": matrix.std(axis=0, ddof=1) / np.sqrt(len(ids)) if len(ids) > 1 else None,
            "repeats": matrix, "eligible_repeat_ids": ids, "repeat_count": len(ids),
            "units": spec.units, "observation_identity": spec.digest,
            "sem_interpretation": "repeat variability; no animal independence claim"}


def synthetic_integration():
    """Analytic two-repeat observation fixture on the retained T4 convention."""
    assignment = CellAssignment("fixture-cell", "area05-analytic-v1", ("1", "2"), (.25, .75),
                                "unknown_fixed", "unknown_fixed", "unknown_fixed_no_pA_conversion",
                                "synthetic", "fixture", ("analytic voltage fixture only",))
    spec = t4_observation_spec("area05-t4-observation-fixture-v1", assignment)
    grid = np.arange(-200., 102., 2.)
    clock = np.arange(-225., 126., .25)
    rows = {}
    for index, amplitude in enumerate((2., 4.)):
        voltage = causal_interval_response([.375], [10.875], [amplitude], clock, 5.)
        states = {"voltage_mv": np.stack([-60. + voltage, -50. + 2. * voltage], axis=1)}
        rows[str(index)] = observe_trace(clock, states, assignment.root_ids, spec, grid, source_units="mV")
    combined = aggregate_repeats(rows, ("0", "1"), spec)
    return {"scope": "fixture", "contract": observation_contract(spec),
            "source_clock_ms": clock.tolist(), "controller_on_ms": [.375], "controller_off_ms": [10.875],
            "tau_ms": 5., "amplitudes_mv": [2., 4.], "resting_voltage_mv": [-60., -50.],
            "root_gains": [1., 2.], "output": {k: v.tolist() if isinstance(v, np.ndarray) else v for k, v in combined.items()}}


def observe_for_calibration(*args, **kwargs):
    """Full processed trace receipt for the v2 calibration window-binding API.

    Filtering and baseline use the complete registered observation grid before
    calibration selects a sample window. This does not assert native evidence.
    """
    result = observe_trace(*args, **kwargs)
    return {"time_ms": result["time_ms"].tolist(), "values": result["values"].tolist(),
            "units": result["units"], "observation_identity": result["observation_identity"],
            "processing_stage": "after_observation_filter_and_baseline"}
