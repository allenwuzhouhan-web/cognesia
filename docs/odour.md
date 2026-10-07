# Odour input prerequisite

The input vector follows the **53 named FlyWire ORN types**, in sorted type order, and expands onto the 2,279 normative ORNs in model row order. Four untyped neurons remain present and receive zero input. The selector is `cell_class == 'olfactory'` and `super_class == 'sensory'`. It never includes AL projection neurons.

This module supplies assumed afferent firing rates and optional seeded source-event counts. It does not supply an AL transform, alter the measured connectivity, fit KC sparseness, or implement a body decoder. The saved `V-NM-ODOUR` evidence is a software/data prerequisite; **KC sparseness remains NOT-RUN until the real network is exercised**.

## Source and reproduction

DoOR.data is pinned to commit `db323a496577c4b4a72b5c2fcd1859e07521ffb5`. Five downloaded files are cached under `data/raw/neuromod/door/`; each has an embedded SHA256 in the loader. [Primary DoOR project](https://github.com/ropensci/DoOR.data), [DoOR 2.0 paper](https://www.nature.com/articles/srep21841).

| File | Observed rows × columns | Purpose |
|---|---:|---|
| door_response_matrix.csv | 691 × 78 | Globally normalized consensus, including spontaneous firing SFR |
| door_mappings.csv | 96 × 20 | Responding unit, receptor, OSN and anatomical mappings |
| odor.csv | 691 × 22 | Name, CAS, InChIKey and chemical metadata |
| door_dataset_info.csv | 42 × 15 | Underlying studies, assays, concentrations and sources |
| door_response_range.csv | 42 × 4 | Underlying study response ranges |

These CSVs use semicolons and an implicit R row index. The matrix index is the chemical InChIKey; positional row-number joins are forbidden. The observed 691 rows differ from older rendered documentation saying 693; we pin and inspect actual bytes. The response matrix has float64 values in [0,1] and NaN where unknown. Every load validates cached hashes before fetching anything, inspects dtypes/schema/three rows, and writes `build/schema_inspection_odour.json` before mapping. Checksum/schema corruption is an error, never a synthetic-fallback trigger.

From the project root:

```python
from pathlib import Path
from flybrain.neuromod.odour import build_odours, OdourLibrary
result = build_odours(Path('.'))  # fetches missing pinned files, validates source gate
assert result['status'] == 'PASS', result['failed_checks']
library = OdourLibrary.from_root(Path('.'), download=False)
delta_au, metadata = library.responses('OCT')
```

`build_odours` writes `build/odour_orn_map.csv`, `build/odour_coverage.json`, and `build/validation_neuromod_odour.json`. The map contains 106 type×odour rows for OCT/MCH, with raw consensus, SFR, signed evoked delta, chemical identity, status and source URLs. Missing values stay explicit in the raw measurement columns, including raw SFR. `baseline_input_au` separately records the usable baseline after unresolved mappings have been assigned zero; it is not mislabeled as a measured SFR. The usable evoked delta is zero when the measurement or mapping is missing.

## Chemical identities and coverage

| Protocol name | Identity in downloaded DoOR odor.csv | InChIKey | Named type coverage | Neuron coverage |
|---|---|---|---:|---:|
| OCT | 3-octanol; CAS 589-98-0 | NMRPBPVERJPACX-UHFFFAOYSA-N | 28/53 = 52.83% | 1207/2279 = 52.96% |
| MCH | 4-methylcyclohexanol; CAS 589-91-3 | MQWCXKGKQLNYQG-UHFFFAOYSA-N | 22/53 = 41.51% | 975/2279 = 42.78% |

Coverage means an actual finite response and spontaneous baseline in the selected responding-unit profile. It is not a count of neurons biologically responsive to that odour. OCT has 24 positive and 4 negative signed responses; MCH has 18 positive and 4 negative. The MCH entry does not identify a stereoisomer; none is substituted.

**Missing measurements give zero evoked delta, not measured silence. An independently measured SFR may still drive tonic activity; unmapped, ambiguous and untyped neurons get zero input.** This statement is repeated in every map/coverage artifact. A measured response equal to its measured SFR is labeled `measured_zero_evoked_response`, never confused with a missing measurement or total silence.

## Mapping provenance and ambiguity

The exact `door_mappings.code` matches the suffix of `ORN_<code>`. This uses DoOR's own chosen single responding-unit profile for each anatomical label, as in its [atlas implementation](https://github.com/ropensci/DoOR.functions/blob/master/R/dplot_al_map.R). We never sum coexpressed receptor profiles or select a different profile for each odour just to increase coverage. The machine-readable provenance is the exact pinned mapping URL per pair; [Couto 2005](https://pubmed.ncbi.nlm.nih.gov/16139208/) supplies canonical Or mapping context, while DoOR incorporates later IR work. The [Task 2022 primary mapping tables](https://elifesciences.org/articles/72599/figures) provide explicit underlying references.

- No mapping is invented from older VM6/VP labels to `ORN_VM6l`, `ORN_VM6m`, or `ORN_VM6v`.
- VA7m's receptor is explicitly unknown (`?`).
- DL2d and DL2v share an ac3A profile with explicitly unresolved separation in the source. We retain that ambiguity and assign zero evoked input and zero baseline to both, rather than duplicating it. OCT/MCH ac3A measurements are missing anyway.
- Unknown odour identity raises an error; it does not silently switch to random input.
- A known chemical with missing responses retains the measurements that exist and flags each gap; missing measurement does not imply biological absence of an effect.

## Baseline and transduction assumptions

The official [DoOR normalized-response function](https://docs.ropensci.org/DoOR.functions/reference/get_normalized_responses.html) subtracts SFR. `responses(name).values` therefore returns **signed `raw_consensus - SFR` in a.u.**, not Hz and not all-positive activation. Raw values and baseline remain available in metadata.

Default `odour_baseline_mode = source_sfr` computes effective receptor activation

```text
activation = max(source_SFR + intensity * signed_delta, 0)
adaptation += (1 - exp(-dt/tau_adapt)) * (activation - adaptation)
target_Hz = max_rate_Hz * activation /
            (activation + half_saturation + adaptation_strength * adaptation)
rate_Hz += (1 - exp(-dt/tau_transduction)) * (target_Hz - rate_Hz)
```

This is the same rectified Naka–Rushton/adapting passive-filter form as `eye.Phototransduction`, with a unit-appropriate firing-rate scale. It does not send Hz through the eye's mV parameter or imply identical sensory physiology. Adaptation and output initialize at equilibrium under the selected baseline. The ordered exponential updates match the eye's numerical convention. `intensity` must lie in [0,1].

The parameters below are **ASSUMPTION**, not DoOR measurements: maximum rate 150 Hz; adaptation time constant 200 ms; transduction time constant 12 ms; half-saturation 0.2 a.u.; adaptation strength 0.5; baseline mode `source_sfr`. Values/provenance come from `config/neuromod.yaml`; this module does not insert hidden production defaults. Declared sensitivity ranges are not claimed completed by the odour prerequisite.

Inhibitory measurements reduce firing relative to the same baseline. Optional `zero` baseline mode rectifies negative deltas to zero; its metadata explicitly records that inhibition is discarded. This is an experimental alternative, not the default.

```python
from flybrain.neuromod.odour import OdourTransduction, OdourEventSampler, read_odour_parameters
transduction = OdourTransduction(library, read_odour_parameters(Path('.')))
source_events = OdourEventSampler(seed=7)
orn_rates_hz = transduction.step('OCT', intensity=1.0, dt_ms=0.1)
counts = source_events.sample(orn_rates_hz, dt_ms=0.1)
# rates/counts correspond to full-model indices library.neuron_indices.
```

The sampler uses Poisson counts with expectation `rate_Hz * dt_ms / 1000`. Multiple events per step are retained. These are source-event counts, **not already simulated network spike trains**. The caller must apply them through the network's sensory-input interface and record seed/timing. No hand-built AL gain is added.

## Synthetic fallback

Only `allow_synthetic=True` after an actual failed download enables seeded sparse random input. Merely disabling downloads does not establish that DoOR is unobtainable. The failure reason is recorded; checksum/schema errors always fail. Each `(seed, odour name)` identifies a deterministic vector independent of call order. Exactly round(10% of named types), at least one, are selected uniformly without replacement; selected amplitudes are uniform in [0.25,1] a.u. These are explicit synthetic assumptions.

Every returned metadata object and mapping row says **SYNTHETIC ODOUR**. Such input is usable for timing/software experiments only; it cannot support odour discrimination, generalisation or identity-coding claims. No measured coverage is attributed to synthetic inputs.

## Existing stage 5 specification conflict

Patch 1 leaves §3.3 unchanged. Sourcing these odours does not resolve the audited equation/reference-table mismatch or permit tuning around it. See `docs/neuromod_reference_findings.md`; no V-NM-E or behavioural result is claimed here.
