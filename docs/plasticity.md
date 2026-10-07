# Normalized plasticity: corrected reference

The final brief's Part III §1 explicitly replaces the original literal trace equations, units, update order, rate assumption and reference table. The corrected pinned float64 fixture reproduces all twelve supplied values; its maximum absolute error is **4.91487715×10⁻⁷**, below the 0.001 tolerance. No parameter fitting was performed. The old literal audit remains in `docs/neuromod_reference_findings.md` as a record of the superseded specification, not a current failure.

The standalone reference is exactly the supplied sequence:

```python
C = C * ac + dr * (1 - ac)
E_pre = E_pre * ap + r * (1 - ap)
E_da = E_da * ad + C * (1 - ad)  # NEW C
w -= ETA * (A1 * C * E_pre - A2 * r * E_da) * DT  # NEW traces
```

`r` and `dr` are dimensionless drive in [0,1]. Time is milliseconds; η is 0.00055 ms⁻¹. The three time constants are 400, 600 and 1500 ms; A1=1, A2=0.55. At dt=1 ms, the horizon is 0≤t<7000 ms, KC drive is one over [3000,4000), and DA source drive is one over [3000+delay,3500+delay). State starts at zero, with w=w0=1, and forgetting is disabled. Pulse boundaries are integer steps, not floating-point time comparisons.

The independent float64 reference uses the five lines directly. The production implementation stores float32 state and runs its edge update in a Numba kernel with `fastmath=False`. It agrees with the pinned float64 fixture within **1.09459699×10⁻⁵**, below the declared 0.0002 sub-tolerance. Halving dt changes the float64 result by **3.05767852×10⁻⁵**. Both reference clamp counts are zero.

| Delay ms | Supplied Δw | Float64 Δw |
|---:|---:|---:|
| -2000 | 0.029344 | 0.029344255 |
| -1500 | 0.036698 | 0.036697916 |
| -1000 | 0.036364 | 0.036363642 |
| -750 | 0.025960 | 0.025959632 |
| -500 | -0.001091 | -0.001090509 |
| -250 | -0.052654 | -0.052654061 |
| 0 | -0.110433 | -0.110432655 |
| 250 | -0.147949 | -0.147949325 |
| 500 | -0.156273 | -0.156273132 |
| 1000 | -0.090804 | -0.090803971 |
| 1500 | -0.039460 | -0.039460213 |
| 2000 | -0.017139 | -0.017138762 |

The measured crossover is **-510.078584 ms**, estimated by linear interpolation between the adjacent sampled signs. This interpolation is a numerical summary, not a smoothed experimental trace. Peak depression is at +500 ms. Positive-delay sum is -0.451625403; negative-delay sum is +0.074620875. These are fixture outcomes, not claims that network pairing biology passes.

## Production API

`NormalizedPlasticity(n_kc, n_compartments, pre_index, compartment_index, w0, parameters, compartment_sign=..., compartment_scale=...)` stores one eligibility trace per KC, one DA trace per compartment and one weight per explicitly listed edge. It does not create connectivity or inject current.

`step(kc_drive, dopamine_au, dt_ms)` receives normalized KC drive and the **already updated** Layer-2 DA concentration. The runtime must update the field first; the plasticity kernel does not integrate a duplicate dopamine field. Concentration input is allowed over [0,5] a.u. to accommodate the field's configured bolus/guard range; source drive in the pinned fixture remains [0,1].

`normalize_kc_rates(rate_hz, max_rate_hz)` returns `(drive, saturation_count)`, using `min(rate_hz,max_rate_hz)/max_rate_hz`. The maximum firing rate and temporal rate estimator are explicit runtime assumptions. Raw spikes/Hz are never silently interpreted as dimensionless drive.

`build_core_plasticity(root, core=None)` returns a `CorePlasticity` object containing `kernel`, `kc_indices`, `edge_data_indices`, `compartment_names` and metadata. It maps exactly **62,261 actual KC→MBON CSR entries, carrying 256,719 baseline synapses**, using the empirical MBON compartment assignment. Its indices let the caller write weights back to those existing CSR entries. Baseline weights retain synapse-count units, so the pinned absolute η changes synapse-count equivalents per edge; interpreting η as a fractional baseline change would be a different, unimplemented rule.

Empirical compartments with no MBON edges stay empty. In particular, the current empirical g1 has zero KC→MBON edges, despite its canonical label. No canonical reassignment is made to produce a learning effect. This distinction must remain visible in protocols and biological outcomes.

`config/compartment_rules.csv` supplies one signed multiplier and magnitude for each of the 15 MB compartments. All current numeric assignments are explicitly **ASSUMPTION**: the reference branch rule is extended uniformly pending independently sourced compartment-specific numeric rules. The cited Aso/Handler papers establish cell-type-dependent learning and temporal branch asymmetry; the citation is not presented as measurement of these numbers. The kernel supports independently changing signs/scales, and tests check that a change affects only its indexed compartment.

Production forgetting is configured separately: after the associative update, exact exponential relaxation toward w0 uses frozen `(1+beta*C)/tau_forget`. This follows §6's exponential integration instruction. The pinned reference always disables forgetting. `tau_forget_ms=None` disables it and serializes as JSON null, never Infinity.

## Software evidence and honest history assertions

`validate_plasticity(root)` runs the twelve-point reference first, production precision and timestep checks, bounds/clamp/logging tests, η linearity over a decade, analytic forgetting, history and compartment tests, then finite bounded updates on every actual core plastic edge. The latter uses a documented seeded uniform-drive software fixture, not invented biological activity. Evidence is saved in `build/validation_neuromod_plasticity.json` and `build/plasticity_reference_curve.csv` with source, code, configuration, dependencies and artifact hashes. Prerequisite checks recurse through receptors, field and compartment evidence.

The no-input assertions mean **absence throughout the relevant history**, with baseline weights (and forgetting disabled in associative fixtures). They do not assert that current zero DA or current KC silence erases a stored trace:

- Prior DA can potentiate later KC activity while current DA is zero.
- Prior KC activity can cause later DA to depress weights while current KC drive is zero.
- Finite forgetting changes nonbaseline weights even when both inputs and traces are zero.

Every proposed trace, forcing and weight is finite-checked before any state or log commit. Float32 overflow is rejected instead of being hidden by a clamp. Invalid coefficients, zero/underflowing timesteps, malformed delay axes and stale recursive provenance have regression tests. Weight clips and cumulative absolute movement are logged. The **39 focused tests** check implementation correctness; network biological gates remain separate measurements.

Executed full software gate: **V-NM-E PASS, 21 checks**, including the full actual edge map and seeded bounds exercise. The η-decade ratio was 10.00003624. This permits subsequent coupled-network experiments; it does not predeclare their biological results.
