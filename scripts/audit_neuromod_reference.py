#!/usr/bin/env python3
"""Audit the neuromodulation brief's reference; this is not a production engine.

Run from any directory with a Python environment containing NumPy::

    python scripts/audit_neuromod_reference.py --root .

Without --root, print JSON only. With --root, also save the JSON and its readable
findings under build/ and docs/. No biological parameters are fitted or tuned.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

INTERVALS_MS = np.array(
    [-2000, -1500, -1000, -750, -500, -250, 0, 250, 500, 1000, 1500, 2000],
    dtype=np.int64,
)
REFERENCE = np.array(
    [0.0293, 0.0367, 0.0364, 0.0260, -0.0011, -0.0527,
     -0.1104, -0.1480, -0.1563, -0.0908, -0.0395, -0.0171],
    dtype=np.float64,
)


def steps_for(milliseconds: float, dt_ms: float) -> int:
    """Require event times exactly representable on the integer integration grid."""
    count = round(milliseconds / dt_ms)
    if not math.isclose(count * dt_ms, milliseconds, abs_tol=1e-8, rel_tol=0):
        raise ValueError(f"{milliseconds} ms is not a multiple of {dt_ms} ms")
    return count


def integrate(
    intervals_ms: np.ndarray,
    *,
    normalized_traces: bool = False,
    dt_ms: float = 1.0,
    rate_hz: float = 10.0,
    end_ms: float = 30_000.0,
) -> dict:
    """Diagonal exponential Euler with all forcing evaluated before each update.

    Physical time is seconds; inputs are piecewise constant on integer steps.
    Exact exponential decays handle C, E_pre, and E_da. Weight forcing is frozen
    over each step; its linear coefficient is zero because forgetting is disabled.
    The weight update is consequently dt * forcing (the zero-decay exponential-
    Euler limit). This is a documented integrator convention, not a parameter fit.
    """
    dt = dt_ms / 1000.0
    if dt <= 0 or rate_hz < 0:
        raise ValueError("Require positive dt and non-negative rate")
    if not math.isclose(dt_ms / 0.1, round(dt_ms / 0.1), abs_tol=1e-9):
        raise ValueError("dt_plast must be an integer multiple of base dt=0.1 ms")
    if 400.0 < 10 * dt_ms:
        raise ValueError("DA clearance must be >=10*dt_mod")
    odor_on = steps_for(3000.0, dt_ms)
    odor_off = steps_for(4000.0, dt_ms)
    dopamine_on = np.array(
        [steps_for(3000.0 + int(v), dt_ms) for v in intervals_ms], dtype=np.int64
    )
    dopamine_off = dopamine_on + steps_for(500.0, dt_ms)
    end_step = steps_for(end_ms, dt_ms)
    if np.any(dopamine_on < 0) or np.any(dopamine_off >= end_step) or odor_off >= end_step:
        raise ValueError("Simulation horizon must contain all pulses")

    decay_pre = math.exp(-dt / 0.6)
    decay_da = math.exp(-dt / 1.5)
    decay_c = math.exp(-dt / 0.4)
    c = np.zeros(len(intervals_ms), dtype=np.float64)
    e_da = np.zeros_like(c)
    e_pre = 0.0
    w = np.ones_like(c)
    # Optional physical caps required by the brief. Neither activates here.
    concentration_clamps = 0
    weight_clamps = 0
    minimum_weight = 1.0
    maximum_weight = 1.0
    peak_concentration = 0.0
    for step in range(end_step):
        rate = rate_hz if odor_on <= step < odor_off else 0.0
        drive = ((dopamine_on <= step) & (step < dopamine_off)).astype(np.float64)
        candidate_w = w - dt * 0.055 * (c * e_pre - 0.55 * rate * e_da)
        weight_clamps += int(np.count_nonzero((candidate_w < 0) | (candidate_w > 2)))
        w = np.clip(candidate_w, 0.0, 2.0)
        minimum_weight = min(minimum_weight, float(w.min()))
        maximum_weight = max(maximum_weight, float(w.max()))
        # Update from old state. This is exponential Euler, not sequential
        # use of newly updated traces within the same integration step.
        pre_multiplier = 1.0 if normalized_traces else 0.6
        da_multiplier = 1.0 if normalized_traces else 1.5
        e_pre = decay_pre * e_pre + pre_multiplier * (1 - decay_pre) * rate
        e_da = decay_da * e_da + da_multiplier * (1 - decay_da) * c
        candidate_c = decay_c * c + (1 - decay_c) * drive
        concentration_clamps += int(np.count_nonzero((candidate_c < 0) | (candidate_c > 5)))
        c = np.clip(candidate_c, 0.0, 5.0)
        peak_concentration = max(peak_concentration, float(c.max()))
    return {
        "delta_w": (w - 1.0).tolist(),
        "concentration_clamp_events": concentration_clamps,
        "weight_clamp_events": weight_clamps,
        "minimum_weight_over_run": minimum_weight,
        "maximum_weight_over_run": maximum_weight,
        "peak_concentration_au": peak_concentration,
    }


def curve_metrics(normalized: bool) -> dict:
    result = integrate(INTERVALS_MS, normalized_traces=normalized)
    values = np.array(result["delta_w"])
    result["max_absolute_reference_error"] = float(np.max(np.abs(values - REFERENCE)))
    result["reference_numeric_tolerance_met"] = bool(
        result["max_absolute_reference_error"] <= 0.001
    )
    result["integration_refinement"] = []
    for dt_ms in (0.5, 0.1):
        refined = integrate(INTERVALS_MS, normalized_traces=normalized, dt_ms=dt_ms)
        result["integration_refinement"].append({
            "dt_ms": dt_ms,
            "max_absolute_delta_from_1ms": float(np.max(np.abs(values - refined["delta_w"]))),
            "max_absolute_reference_error": float(np.max(np.abs(REFERENCE - refined["delta_w"]))),
        })
    extended = integrate(INTERVALS_MS, normalized_traces=normalized, end_ms=60_000.0)
    result["max_absolute_delta_when_horizon_doubled"] = float(
        np.max(np.abs(values - extended["delta_w"]))
    )
    # Integer 1-ms onset scan; linearly interpolate only the reported root.
    grid = np.arange(-1000, 1, dtype=np.int64)
    sweep = np.array(integrate(grid, normalized_traces=normalized)["delta_w"])
    changes = np.flatnonzero(sweep[:-1] * sweep[1:] < 0)
    roots = []
    for index in changes:
        roots.append(float(grid[index] - sweep[index] / (sweep[index + 1] - sweep[index])))
    result["crossover_ms_from_1ms_onset_grid"] = roots
    return result


def build_audit() -> dict:
    return {
        "schema_version": 1,
        "purpose": "Independent specification preflight; not production plasticity or a V-NM-E pass",
        "status": "SPECIFICATION_MISMATCH",
        "parameter_tuning_performed": False,
        "reference_source": "NEUROMOD_BUILD_BRIEF.md sections 3.3, 6 and 10 (user supplied)",
        "parameters_from_brief": {
            "tau_pre_ms": 600, "tau_da_trace_ms": 1500, "tau_clear_da_ms": 400,
            "A1": 1.0, "A2": 0.55, "eta_numeric": 0.055, "dt_ms": 1,
            "odor_duration_ms": 1000, "dopamine_pulse_duration_ms": 500, "w0": 1,
        },
        "explicit_assumptions_not_supplied_by_reference": {
            "kc_rate_hz": 10.0,
            "kc_rate_is_not_normalized_to_unit_interval": True,
            "kc_rate_1hz_scaling": "All changes divide by ten; neither example clips weights",
            "odor_onset_ms": 3000,
            "horizon_ms": 30000,
            "dopamine_pulse_meaning": "Unit source drive into dC/dt=(drive-C)/0.4 seconds, not direct concentration clamp",
            "initial_state": "All traces and concentrations zero; all weights one",
            "forgetting": "Disabled (tau_forget=infinity); beta immaterial",
            "w_max_multiplier": 2.0,
            "weight_clipping": "Applied but never activated",
            "precision": "IEEE float64 diagnostic",
            "integration": "Exponential Euler, old-state forcing, integer-step pulse scheduling",
        },
        "literal_equations": {
            "E_pre": "dE_pre/dt=-E_pre/0.6+r",
            "E_da": "dE_da/dt=-E_da/1.5+C",
            "weight_without_forgetting": "dw/dt=-0.055*(C*E_pre-0.55*r*E_da)",
            "time_unit": "seconds",
        },
        "alternative_equations_diagnostic_only": {
            "E_pre": "dE_pre/dt=(-E_pre+r)/0.6",
            "E_da": "dE_da/dt=(-E_da+C)/1.5",
            "weight_without_forgetting": "dw/dt=-0.055*(C*E_pre-0.55*r*E_da)",
            "faithful_to_written_equations": False,
            "interpretation": "An algebraic normalization hypothesis, not a fitted model or approved correction",
        },
        "unit_issue": (
            "With r in s^-1 and C dimensionless, literal E_pre is dimensionless and E_da has units s; "
            "their weight-rule products are dimensionless, so eta has units s^-1 for dimensionless w. "
            "Normalized E_pre has units s^-1 and E_da is dimensionless; eta is then dimensionless. "
            "The same numeric eta therefore has different physical meaning. The reference gives no rate "
            "or eta unit. Switching a solver from seconds to milliseconds without converting eta can "
            "multiply literal weight change by 1000."
        ),
        "delay_ms": INTERVALS_MS.tolist(),
        "reference_delta_w": REFERENCE.tolist(),
        "literal": curve_metrics(False),
        "normalized_alternative": curve_metrics(True),
        "no_input_gate_conflicts": [
            "C=0 at present does not preclude potentiation from residual E_da and active KC",
            "r=0 at present does not preclude depression from residual E_pre and present DA",
            "Even with inputs and traces zero, finite forgetting moves any w != w0 toward baseline",
            "Zero changes can be asserted for input absent throughout the history, initial w=w0, and no other driver; these qualifications are absent in V-NM-E",
        ],
        "forgetting_counterexample": {
            "tau_forget_s": 600, "initial_w": 0.5, "w0": 1.0,
            "duration_s": 1, "C": 0, "r": 0, "E_pre": 0, "E_da": 0,
            "analytic_delta_w": float(0.5 * -math.expm1(-1.0 / 600.0)),
        },
        "gate_implication": (
            "The literal equation and table cannot both be claimed reproduced under the stated diagnostic "
            "assumptions. V-NM-E is not evaluated by this standalone preflight. Resolve/document the "
            "reference and history/forgetting semantics before implementing or asserting that gate."
        ),
    }


def findings_markdown(audit: dict) -> str:
    literal = audit["literal"]
    alternative = audit["normalized_alternative"]
    lines = [
        "# Neuromodulation reference specification preflight", "",
        "**SPECIFICATION MISMATCH — diagnostic only, not a production Layer 4 implementation or V-NM-E pass.**", "",
        "The supplied §3.3 reference table does not match the written trace equations under the explicit assumptions below. "
        "A normalized-trace alternative does meet its numerical tolerance, but changes both trace equations and the units of eta. "
        "It is recorded as a diagnosis, not substituted into the specification. No parameter fitting or tuning was performed.", "",
        "## Reproduce", "", "```sh",
        ".venv/bin/python scripts/audit_neuromod_reference.py --root .", "```", "",
        "The script prints JSON; `--root` additionally regenerates `build/neuromod_reference_audit.json` and this file. "
        "NumPy is the only external dependency. This audit imports no production engine code.", "",
        "## Assumptions and numerical method", "",
        "All differential equations use seconds. Odour starts at 3 s, lasts 1 s, and produces 10 Hz KC activity. "
        "This rate is an **unprovided assumption**, not a normalized [0,1] rate; a rate of 1 Hz divides all displayed changes by ten. "
        "DA onset is odour onset plus the given interval. The 500 ms DA pulse means unit source drive through "
        "`dC/dt = (drive-C)/0.4`, with steady state 1 a.u. Initial concentrations and traces are zero; initial weight is one. "
        "Forgetting is explicitly disabled (`tau_forget=infinity`), and the horizon is 30 s. Rate, pulse interpretation, forgetting settings, "
        "and the measurement horizon are missing from the reference. The illustrative weight cap of twice baseline is also an assumption; it never activates.", "",
        "The method follows §6: exponential Euler with precomputed exponential decays. Forcing uses the old state for each step. "
        "With forgetting disabled, the weight equation's zero linear decay makes its exponential-Euler update equal to `dt * forcing`. "
        "Pulse boundaries are integer step indices. Calculation uses float64 to audit the mathematics, not to demonstrate production float32 performance.", "",
        "## Measured curves", "",
        "| DA onset minus odour onset (ms) | Supplied reference | Literal equation Δw | Normalized alternative Δw |",
        "|---:|---:|---:|---:|",
    ]
    for delay, reference, measured, alt in zip(
        audit["delay_ms"], audit["reference_delta_w"], literal["delta_w"], alternative["delta_w"]
    ):
        lines.append(f"| {delay:+d} | {reference:+.4f} | {measured:+.7f} | {alt:+.7f} |")
    lines += [
        "",
        f"Maximum absolute reference errors: **{literal['max_absolute_reference_error']:.9f}** for the literal equations and "
        f"**{alternative['max_absolute_reference_error']:.9f}** for the normalized alternative; the requested tolerance is 0.001.", "",
        f"Crossover from a 1 ms onset scan, linearly interpolated within its bracketing step: "
        f"**{literal['crossover_ms_from_1ms_onset_grid'][0]:.3f} ms** (literal) and "
        f"**{alternative['crossover_ms_from_1ms_onset_grid'][0]:.3f} ms** (alternative). "
        "The alternative's agreement does not make it faithful to the specified equations.", "",
        "| Numerical check | Literal equation | Normalized alternative |", "|---|---:|---:|",
    ]
    for left, right in zip(literal["integration_refinement"], alternative["integration_refinement"]):
        lines.append(
            f"| Maximum change, 1 ms → {left['dt_ms']} ms | {left['max_absolute_delta_from_1ms']:.9g} | "
            f"{right['max_absolute_delta_from_1ms']:.9g} |"
        )
    lines += [
        f"| Maximum change, 30 s → 60 s horizon | {literal['max_absolute_delta_when_horizon_doubled']:.9g} | "
        f"{alternative['max_absolute_delta_when_horizon_doubled']:.9g} |",
        f"| Concentration clamp events | {literal['concentration_clamp_events']} | {alternative['concentration_clamp_events']} |",
        f"| Weight clamp events | {literal['weight_clamp_events']} | {alternative['weight_clamp_events']} |", "",
        "## Equation and unit mismatch", "", "Written equations:", "", "```text",
        "dE_pre/dt = -E_pre/tau_pre + r", "dE_da/dt  = -E_da/tau_da  + C", "```", "",
        "Diagnostic alternative:", "", "```text", "dE_pre/dt = (-E_pre + r)/tau_pre",
        "dE_da/dt  = (-E_da  + C)/tau_da", "```", "", audit["unit_issue"], "",
        "## No-input gate versus history and forgetting", "",
    ]
    lines += [f"- {conflict}." for conflict in audit["no_input_gate_conflicts"]]
    lines += ["", "An exact counterexample with both inputs and traces zero: `w=0.5`, `w0=1`, and `tau_forget=600 s` gives "
              f"`Δw = 0.5*(1-exp(-1/600)) = {audit['forgetting_counterexample']['analytic_delta_w']:.12f}` "
              "after one second. Thus the unconditional no-weight-change assertion conflicts with the specified forgetting term.", "",
              "Tests must distinguish absent input throughout the relevant history from input currently zero, and distinguish associative "
              "weight change from the independent relaxation term. This preflight does not silently redefine the requested gate.", "",
              "## Gate disposition", "", audit["gate_implication"], ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Also write build JSON and docs findings below this directory")
    args = parser.parse_args()
    audit = build_audit()
    serialized = json.dumps(audit, indent=2, allow_nan=False) + "\n"
    if args.root is not None:
        root = args.root.expanduser().resolve()
        (root / "build").mkdir(parents=True, exist_ok=True)
        (root / "docs").mkdir(parents=True, exist_ok=True)
        (root / "build/neuromod_reference_audit.json").write_text(serialized, encoding="utf-8")
        (root / "docs/neuromod_reference_findings.md").write_text(findings_markdown(audit), encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
