# Core odour sparseness experiment

`flybrain.neuromod.odour_validation.validate_odour_sparseness(root)` measures **V-NM-ODSP**, a biology gate. The target is that 2–12% of KCs fire at least once during the stimulus window. A completed measurement outside that interval is a valid biological FAIL, not a reason to adjust gains or connectivity. The comparison cites Lin et al. 2014, PMID 24561998, doi:10.1038/nn.3660, as required by Patch 1. The selected any-spike definition and recording window remain model protocol assumptions, not a claim that the assay is identical to the published measurement.

The input follows DoOR responses onto 2,279 identified ORNs in the actual 13,300-neuron core. Events pass through the existing LIF sensory-input interface, whose amplitude is the unchanged base `spike_weight * poisson_factor`. The model's native ORN→AL→KC and recurrent connectome paths carry the input onward. No hand-built AL transform, compensating gain, damping, clamp or replacement behaviour decoder is introduced.

## Fixed protocol

The protocol dictionary in `odour_validation.py` is explicitly tagged **ASSUMPTION** and hashed into the result. It is fixed before measurement; no configuration parameter is adjusted from the observed sparseness.

- Separate fresh resting LIF runs for OCT and MCH, with seed 783 in each and identical source-SFR baseline prefixes.
- 1,000 ms baseline, 1,000 ms full-intensity odour, 500 ms recovery.
- Baseline statistics use the final 500 ms before odour; stimulus statistics use the full 1,000 ms odour window. All windows are half-open `[start,end)`.
- The coding fraction is the fraction of all 5,177 KCs with at least one actual simulated LIF spike in the window. Mean/max rates and full per-neuron rates accompany the fraction because unequal baseline/odour window lengths affect the chance of observing any spike.
- Core KC recurrence uses the requested default `thresholded` policy (KC→KC edges below two synapses are removed by the existing core loader). Its effective edge count and explicit KC cholinergic sign corrections are recorded. Other weights and dynamics remain unchanged.
- Source SFR baseline is required. **Missing measurements give zero evoked delta, not measured silence. An independently measured SFR may still drive tonic activity; unmapped, ambiguous and untyped neurons get zero input.**
- Base `dt` is retained, normally 0.1 ms; one thread; `clamp=False`.

Each run streams 100 ms through the unchanged `LIFEngine.run`. Input-event steps are converted from the saved global protocol log to the relative steps required by each continuation call. A focused test confirms exact spike/endpoint equality against one unsplit call on the same numerical fixture and event log.

## Recorded evidence and numerical limits

All neurons' voltages are sampled in the engine's start slot at every integration step. Each chunk is reduced to finite checks, extrema, per-neuron out-of-bound sample counts, selected traces, and chunk endpoint voltage/synaptic-state checks; the full temporary matrix is discarded. This keeps the working set bounded instead of retaining approximately 1.33 GB of full voltage records per odour.

`out_of_bound_voltage_samples` is distinct from `clamp_events`. With clamping disabled, zero clamps is expected and does **not** establish stable voltage. Endpoint and sampled finite/bounds failures prevent a biological PASS even if the observed fraction happens to fall in the target interval. The report explicitly limits numerical evidence to sampled integration-start voltages and chunk endpoint states: it does not inspect every internal pre-reset threshold overshoot, prove equilibrium, or certify arbitrary driven trajectories.

The run stops and preserves available evidence if states become nonfinite or the engine fails. Incomplete-window fractions are reported as unavailable, not as zero. Per-neuron files carry the completion flag.

Saved artifacts under `build/`:

- `validation_neuromod_odour_sparseness.json`: both odours, measured fractions/rates, finite/bounds/clamp evidence, protocol hash and provenance.
- `odour_sparseness_<OCT|MCH>_neurons.csv`: all core neuron identities, baseline/stimulus/recovery spike counts and Hz, voltage-bound and nonfinite sample counts.
- `odour_sparseness_<OCT|MCH>_types.csv`: rates and failures aggregated by actual cell type.
- `odour_sparseness_<OCT|MCH>_activity.npz`: every source event and network spike, input/model/root index mappings, sampled source rates, selected voltage traces, and final voltage, synaptic state, last-spike state and pending delay-ring events. Only initialized pending ring entries are stored.

The validator captures and then verifies unchanged source hashes/stat signatures, configuration, implementation, base artifacts and dependencies. It does not refresh earlier source gates or reinterpret an existing failed gate as a pass.

## Reproduce

After the source, odour and core prerequisites are current:

```python
from pathlib import Path
from flybrain.neuromod.odour_validation import validate_odour_sparseness
result = validate_odour_sparseness(Path('.'))
print(result['status'], result['runs'])
```

V-NM-ODSP is separate from the unresolved §3.3 reference-curve conflict. It does not execute plasticity, tune eligibility parameters, or claim V-NM-E success.

## Executed result

The saved run completed both 2.5-second protocols without an engine error, but **V-NM-ODSP FAILS**. All observed states were finite; neither run respected the base voltage bounds. No parameters were changed to improve the result.

| Measurement | OCT | MCH |
|---|---:|---:|
| KC active fraction during odour | 68.8236% | 68.3987% |
| KC active fraction during baseline | 67.8192% | 67.8192% |
| Mean KC firing rate during odour (Hz) | 36.456442 | 35.762411 |
| Mean KC baseline firing rate (Hz) | 34.974696 | 34.974696 |
| Source event count | 173,624 | 158,845 |
| Actual network spike count | 1,023,781 | 1,005,444 |
| Out-of-bound voltage samples | 278,639 | 272,660 |
| Neurons with out-of-bound samples | 1,170 | 1,147 |
| Minimum recorded voltage (mV) | -167.448776 | -168.070450 |
| Maximum recorded voltage (mV) | 154.395294 | 92.468483 |
| Nonfinite recorded voltage samples | 0 | 0 |
| Clamp events (clamping disabled) | 0 | 0 |

The target is 2–12%, while roughly 68% of KCs fire in both baseline and odour windows. Source-SFR tonic drive therefore already recruits most of the observed KC population in this model. Baseline and stimulus fractions use different window lengths; the saved rate comparison should accompany any interpretation. This result does not establish odour discrimination or useful learning.

Voltage bounds are [-90,20] mV. Violation counts cover the entire baseline/odour/recovery protocol, not only the stimulus window. The zero clamp count is a consequence of `clamp=False`, not an indicator of stability. The core's separate zero-input stationarity PASS therefore must not be generalized to these driven trajectories.

The effective core has 13,300 neurons and 927,567 edges after the fixed thresholded KC recurrence policy; 234,350 KC→KC edges below two synapses were removed. Protocol hash: `2b1b4def83e50284a9668883fcac6511331a3939189ef5ed3fcd2059ec50c8b8`.
