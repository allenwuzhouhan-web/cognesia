# Neuromodulation reference specification preflight

**SPECIFICATION MISMATCH — diagnostic only, not a production Layer 4 implementation or V-NM-E pass.**

The supplied §3.3 reference table does not match the written trace equations under the explicit assumptions below. A normalized-trace alternative does meet its numerical tolerance, but changes both trace equations and the units of eta. It is recorded as a diagnosis, not substituted into the specification. No parameter fitting or tuning was performed.

## Reproduce

```sh
.venv/bin/python scripts/audit_neuromod_reference.py --root .
```

The script prints JSON; `--root` additionally regenerates `build/neuromod_reference_audit.json` and this file. NumPy is the only external dependency. This audit imports no production engine code.

## Assumptions and numerical method

All differential equations use seconds. Odour starts at 3 s, lasts 1 s, and produces 10 Hz KC activity. This rate is an **unprovided assumption**, not a normalized [0,1] rate; a rate of 1 Hz divides all displayed changes by ten. DA onset is odour onset plus the given interval. The 500 ms DA pulse means unit source drive through `dC/dt = (drive-C)/0.4`, with steady state 1 a.u. Initial concentrations and traces are zero; initial weight is one. Forgetting is explicitly disabled (`tau_forget=infinity`), and the horizon is 30 s. Rate, pulse interpretation, forgetting settings, and the measurement horizon are missing from the reference. The illustrative weight cap of twice baseline is also an assumption; it never activates.

The method follows §6: exponential Euler with precomputed exponential decays. Forcing uses the old state for each step. With forgetting disabled, the weight equation's zero linear decay makes its exponential-Euler update equal to `dt * forcing`. Pulse boundaries are integer step indices. Calculation uses float64 to audit the mathematics, not to demonstrate production float32 performance.

## Measured curves

| DA onset minus odour onset (ms) | Supplied reference | Literal equation Δw | Normalized alternative Δw |
|---:|---:|---:|---:|
| -2000 | +0.0293 | +0.0452940 | +0.0293827 |
| -1500 | +0.0367 | +0.0593745 | +0.0367445 |
| -1000 | +0.0364 | +0.0694669 | +0.0364039 |
| -750 | +0.0260 | +0.0667324 | +0.0259788 |
| -500 | -0.0011 | +0.0501890 | -0.0011208 |
| -250 | -0.0527 | +0.0120469 | -0.0527475 |
| +0 | -0.1104 | -0.0352776 | -0.1105553 |
| +250 | -0.1480 | -0.0712636 | -0.1480634 |
| +500 | -0.1563 | -0.0873220 | -0.1563503 |
| +1000 | -0.0908 | -0.0544830 | -0.0908050 |
| +1500 | -0.0395 | -0.0236782 | -0.0394637 |
| +2000 | -0.0171 | -0.0102905 | -0.0171508 |

Maximum absolute reference errors: **0.076736421** for the literal equations and **0.000155333** for the normalized alternative; the requested tolerance is 0.001.

Crossover from a 1 ms onset scan, linearly interpolated within its bracketing step: **-186.164 ms** (literal) and **-507.112 ms** (alternative). The alternative's agreement does not make it faithful to the specified equations.

| Numerical check | Literal equation | Normalized alternative |
|---|---:|---:|
| Maximum change, 1 ms → 0.5 ms | 4.60280633e-05 | 3.0721556e-05 |
| Maximum change, 1 ms → 0.1 ms | 8.28244771e-05 | 5.52640763e-05 |
| Maximum change, 30 s → 60 s horizon | 0 | 0 |
| Concentration clamp events | 0 | 0 |
| Weight clamp events | 0 | 0 |

## Equation and unit mismatch

Written equations:

```text
dE_pre/dt = -E_pre/tau_pre + r
dE_da/dt  = -E_da/tau_da  + C
```

Diagnostic alternative:

```text
dE_pre/dt = (-E_pre + r)/tau_pre
dE_da/dt  = (-E_da  + C)/tau_da
```

With r in s^-1 and C dimensionless, literal E_pre is dimensionless and E_da has units s; their weight-rule products are dimensionless, so eta has units s^-1 for dimensionless w. Normalized E_pre has units s^-1 and E_da is dimensionless; eta is then dimensionless. The same numeric eta therefore has different physical meaning. The reference gives no rate or eta unit. Switching a solver from seconds to milliseconds without converting eta can multiply literal weight change by 1000.

## No-input gate versus history and forgetting

- C=0 at present does not preclude potentiation from residual E_da and active KC.
- r=0 at present does not preclude depression from residual E_pre and present DA.
- Even with inputs and traces zero, finite forgetting moves any w != w0 toward baseline.
- Zero changes can be asserted for input absent throughout the history, initial w=w0, and no other driver; these qualifications are absent in V-NM-E.

An exact counterexample with both inputs and traces zero: `w=0.5`, `w0=1`, and `tau_forget=600 s` gives `Δw = 0.5*(1-exp(-1/600)) = 0.000832639275` after one second. Thus the unconditional no-weight-change assertion conflicts with the specified forgetting term.

Tests must distinguish absent input throughout the relevant history from input currently zero, and distinguish associative weight change from the independent relaxation term. This preflight does not silently redefine the requested gate.

## Gate disposition

The literal equation and table cannot both be claimed reproduced under the stated diagnostic assumptions. V-NM-E is not evaluated by this standalone preflight. Resolve/document the reference and history/forgetting semantics before implementing or asserting that gate.
