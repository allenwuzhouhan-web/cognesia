# Separate whole-brain stability variant

This track implements FINAL Part III without overwriting the original hybrid engine, base matrices, base parameters, Brian2 comparison, or neuromod source audit. Its configuration is `config/hybrid_variant.yaml`; its evidence is `build/validation_hybrid_variant.json` and `build/stability_variant/`. Earlier dynamics passes are not transferred to this changed model. Visual and direction-selectivity gates remain unexecuted.

## The actual population and equations

The saved configured hybrid has **85,472 graded neurons and 5,483,803 graded→graded edges**. The FINAL document's **96,674 neurons and 8,903,991 edges** describe the separately recorded all-visual first-pass selector. Both are legitimate definitions, but they are not the same matrix. The variant uses the actual configured mode table for dynamics and independently measures the first-pass spectrum as a comparison. It never substitutes the document's quoted eigenvalues for measurements of another matrix.

There is also an equation difference. The original hybrid engine uses

```
dg/dt = -g/tau_synapse + graded_gain * W * release
dv/dt = (v_rest - v + g) / tau_membrane
```

so its DC feedback coefficient is `tau_synapse * graded_gain`. The simpler one-state equation quoted in FINAL has no extra synaptic time constant. The isolated variant makes that convention explicit:

```
gain_DC = kappa / max_Re_lambda
dg/dt = (-g + gain_DC * W_normalized * release) / tau_synapse
release = max(v - graded_release, 0)
```

This is a changed model, not a silent reinterpretation of the old gain's units. Tonic release remains present. It is not subtracted to obtain a quiet network. The existing `engine.py` and `hybrid_engine.py` are unchanged.

The default is `graded_norm=in_weight`, `kappa=0.8`, `ct1_mode=excluded`, and `syn_model=current`. Gain configurations outside `0 < kappa < 1` are refused. The denominator for `in_weight` is each postsynaptic row's total absolute incoming graded-source weight after CT1 exclusion. `none` retains the signed counts; `in_degree_alpha` divides by the corresponding retained incoming graded degree raised to the declared exponent. Empty rows use denominator one. No global degree statistic replaces the individual row denominator.

Normalization, gain coefficient, conductance conversion, and exclusion are modeling assumptions. They do not alter the underlying released edge census or source masks.

## Spectral measurement

The code runs separate sparse Arnoldi solves for largest real part (`which=LR`) and largest magnitude (`which=LM`), with deterministic initial vectors, explicit tolerance/iteration count, complex eigenvalues, and relative Ritz residuals. ARPACK nonconvergence is retained as failure; partial eigenpairs are not promoted to a successful leading-eigenvalue measurement. The solver interface and distinction between LR and LM follow [SciPy's primary documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.eigs.html).

Initial measurements for the configured population with CT1 excluded were:

| Normalization | max Re(lambda) | max abs(lambda) |
| --- | ---: | ---: |
| none | 896.260074 | 932.719001 |
| in_weight | 1.000000 | 1.000000 |
| in_degree_alpha, alpha=0.5 | 14.070317 | 28.832964 |
| in_degree_alpha, alpha=1.0 | 8.366600 | 8.366600 |

The full eigenpair results and source-bound cache signatures are saved. Tiny differences from one in the normalized spectrum are numerical residuals, not evidence for exact symbolic equality. Neither `kappa < 1` nor the one-state stiffness formula alone certifies this hybrid: synaptic filtering, transmission delay, rectification, thresholds and resets remain in the dynamic tests.

The independently reconstructed first-pass comparison measured max Re(lambda) **1095.620705** and max abs(lambda) **1979.955809**, recovering the document's rounded numbers for that different population.

## CT1 and the other hub types

The default excludes both CT1 neurons from the variant's recurrence by removing every incident edge from the graded and spiking matrices. Their state remains at rest and they are omitted from perturbation and release. This is the requested exclusion approximation, not a reconstruction of per-column CT1 compartments. `ct1_mode=point` remains a comparison setting.

`ct1_excluded_edge_ledger.csv` identifies each dropped pre/post model index, root ID, signed count, originating mode matrix, and whether CT1 is pre, post, or both. Each edge is counted once. The original matrices remain unchanged. `hub_neurons.csv` reports every cell of CT1, LPi13, LPi14, LPi15, Li30, Li31, Li32, Li33, Am1, Sm41, Sm42 and LT1d, including configured mode, incoming graded degree and absolute incoming graded weight. Some named hubs are spiking under the refined saved mode table; they are reported with that actual mode.

The two configured CT1 graded-input weights are **66,672 and 65,921 synapses**, totaling **132,593**. The first-pass document's 138,325 total is not attached to the configured matrix. No other hub is silently excluded or damped.

The default exclusion ledger contains **39,931 incident edges**, with **336,843 absolute synapses** across incoming/outgoing graded and spiking matrices. This total has a different scope from the incoming-only graded weight above.

## Current and conductance models

The current setting uses the normalized synaptic state as a signed membrane drive. In the conductance setting, positive and negative states are separate, and

```
dv/dt = (v_rest - v + g_exc*(E_exc-v) + g_inh*(E_inh-v)) / tau_membrane
```

`E_exc=0 mV` and `E_inh=-80 mV` are assumptions. To make the comparison explicit, each signed current increment is converted to conductance using its driving force at that neuron's resting voltage. This matches the initial current at rest; it does not claim a measured conductance per synapse. Graded and spiking delivery both use the same conversion convention.

At each integration step, conductances are frozen for the voltage update and the exact exponential toward their weighted equilibrium is used. With nonnegative conductances, initial voltage inside the reversals, and reset/rest inside them, the unforced voltage remains inside the reversal interval by construction. Synaptic states use exponential updates. Refractory eligibility, delayed spike delivery and reset ordering are retained. This does not mean all recurrent conductance networks are stable: the growth gate still measures their coupled dynamics.

The stability runner is headless and unforced. It does not add a new visual driver or claim that direction selectivity survives either setting.

## Four distinct gates

Each synaptic model receives separate V-C1–V-C4 rows and a run manifest containing its measured spectrum, kappa, normalization and network time constant when resolved.

1. **V-C1:** damped rectified fixed-point iteration from resting voltage, maximum 10,000 iterations, damping 0.5. Relative residual is `max(abs(F(v)-v)) / max(1, max(abs(v)), max(abs(F(v))))`. A converged continuous solution above a spiking cell's threshold is not accepted as a quiescent hybrid fixed point. Nonconvergence means no resting state was established by this solver; it is not mathematical proof that no equilibrium exists. Failed cases are not integrated longer.
2. **V-C2:** initialize voltage and synaptic/delay history at the directly solved point, perturb nonexcluded voltages with seeded uniform noise in `[-1,1] mV`, and integrate 2,000 ms. Fit log maximum absolute voltage derivative over the second half. The manifest includes slope, R-squared, implied network time constant for negative slopes, leading neurons, and extrapolation at ten time constants. Values below a declared numerical floor are not used to invent a decay rate; insufficient resolvable samples yield an explicit unexecuted fit result, not a stability pass. Extrapolation is labeled as extrapolation.
3. **V-C3:** require zero rail-clamp events separately. Any clamped neuron is listed with root ID, type, configured mode, retained incoming graded degree/weight, and event count. Clamping is a gate failure, not a successful protective intervention.
4. **V-C4:** report and check the document's one-state stiffness proxy, then compare a half-timestep run from the same point and perturbation. The maximum 2,000 ms endpoint difference must be below 0.1 mV. Both timesteps also receive a separate unperturbed equilibrium-preservation check. The manifest states exactly which endpoint was compared rather than describing a still-converging trajectory as a newly solved fixed point.

The initial direct default solves converged in **63 iterations** for current (relative residual **8.83e-7**) and **47 iterations** for conductance (**9.94e-7**). Those are V-C1 measurements only; the saved gate JSON determines whether the remaining dynamic gates pass.

The completed default validation passed all eight model/gate combinations. Current had fitted slope **-0.00776552 per ms**, implied tau **128.77 ms**, and half-step endpoint difference **1.95e-9 mV**. Conductance had slope **-0.01002696 per ms**, tau **99.73 ms**, and endpoint difference **2.70e-11 mV**. Both had **zero clamps** at both timesteps. These measurements are for the specified unforced, seeded perturbation protocol and do not establish driven visual stability.

If either default model fails, this whole-brain track stops dynamic work. Direct fixed-point and spectral sensitivity measurements can still describe the failure, with their dynamic gates left NOT-RUN. This failure does not stop the separately validated all-LIF neuromod core.

## Sensitivities and API

The declared comparison set contains kappa `{0.1,0.25,0.5,0.8,0.95}`, all three normalization modes, alpha `{0.5,1.0}`, CT1 point/excluded, and both synaptic models. It does not choose a favorable setting to replace a failed default. Every saved sensitivity case says whether its dynamic validation ran or was stopped by the default gate boundary. Other assumption sweep values remain declarations unless a corresponding run is saved; no blanket sensitivity-completion claim is made.

In this execution, the parent task requested release of the machine after the required default dynamic runs so the core's formal timing measurement could run without competition. The extra dynamic sensitivity attempt was interrupted and remains NOT-RUN. **Sixteen direct fixed-point/spectral comparisons completed**; their V-C2–V-C4 are explicitly NOT-RUN. Kappa 0.95 and the none/degree-normalization cases converged to continuous solutions with suprathreshold spiking cells, failing the quiescent hybrid V-C1 criterion. Lower kappa values and point-CT1 comparisons established quiescent points. No failed comparison replaced the default. The source-bound completion script is saved alongside the artifacts.

```python
from flybrain.hybrid_variant import build_stability_variant
from flybrain.neuromod.stability import validate_stability

network = build_stability_variant(root)
report = validate_stability(root, threads=8)
```

The whole-brain runs are memory-bandwidth intensive and must finish before a formal core real-time benchmark, so competing workloads do not contaminate frame-budget measurements. This track makes no real-time claim.
