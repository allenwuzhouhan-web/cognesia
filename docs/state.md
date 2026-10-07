# Endocrine state and the inferred MBON readout

The endocrine boundary model changes source release and existing PAM gain. It adds no current, neuron, connectivity edge, or body decoder. All quantitative couplings and slow-state equations are `ASSUMPTION`, with parameter values and sweeps in `config/neuromod.yaml`.

## Source inventory and evidence

`config/endocrine_sources.csv` retains the measured 76 cells in 10 types: IPC 18, lNSC_unknown 14, mNSC_unknown 10, CRZ 6, DH44 6, DH31 6, DMS 6, ITP 4, Hugin-RG 4 and CAPA 2. The ITP count is for the model subset. Exactly 52 cells have an identified peptide; the other 24 receive no invented hormone. Positive `known_nt` tokens are required per cell. `top_nt` never selects sources. Empty driver-line columns mean no driver correspondence has been established.

[Bisen et al.](https://elifesciences.org/articles/98514) measured nutritional modulation of IPCs. [Yu et al.](https://elifesciences.org/articles/15693) found opposing insulin and AKH effects on a subset of octopaminergic cells. **The present uniform PAM gain extension is an assumption, not a measured PAM receptor map.** Corpora cardiaca and their AKH cells are absent from this brain subset. The exposed `akh_axis_proxy_au = 1-energy` is an explicitly external boundary signal, not release from an invented neuron. No organs are simulated.

The state-to-source associations are declared in the table: energy drives IPC/DILP, DMS and Hugin-RG; hunger/stress drives CRZ; stress drives DH44; thirst drives ITP and CAPA; arousal drives DH31. Except for the broad cited physiological context, these precise mappings and coefficients are assumptions. Their presence does not establish an observed thirst or stress behavior.

## Equations and units

All state values lie in [0,1]; circadian phase is in cycles on [0,1). The fixed update period defaults to 1000 ms and must be a multiple of the base 0.1 ms. For energy:

`dE/dt = feeding*(1-E)/tau_feeding - E/tau_depletion`.

Hydration uses the analogous drinking/loss equation. Arousal and stress relax toward supplied locomotion and aversive drives. Circadian phase advances by `dt/period` modulo one. Every affine equation uses its exact frozen-input exponential solution.

For each **identified endocrine source**, release drive is the measured source rate divided by the declared maximum source rate, plus `state_endocrine_tonic_drive * source_state_driver`. This is clipped to [0,1], with every source clamp counted. It represents normalized endocrine secretion; it is not a generated membrane current or spike. Hormone a.u. summaries relax toward the mean source drive of their own family. At reset, hormones start at the basal equilibrium for the declared state; control events subsequently evolve them with their time constant.

`PAM gain = clip(1 + hunger_gain*(1-energy) - insulin_suppression*insulin_au, gain_min, gain_max)`.

Octopaminergic **positive-annotation sources** receive an arousal-dependent rate scale. Positive DA/5HT sources receive a circadian rate scale. These scales multiply measured release-driving activity. Neither creates aminergic activity from silent cells. OA-AL2b2 remains tyraminergic and receives no OA arousal scaling. Changing endocrine state never writes a weight.

## Runtime API

```python
state = EndocrineState.from_root(root, core.neurons)
state.apply_control('nutritional_state', 'starved')  # recorded at current state time
out = state.step(1000., measured_rates_hz)
# Compose with the existing Layer-3 effects:
gain = receptor_effects.gain * out['gain_factor']
release_rates = measured_rates_hz * out['source_rate_scale']
release_rates[out['endocrine_mask']] = (
    out['endocrine_drive'][out['endocrine_mask']] * out['source_max_rate_hz'])
```

The runtime must log controls at its exact simulation time; the slow-state module logs its own update clock. Source vectors follow the supplied neuron order. `clone`, `reset`, `snapshot`, `restore` and `save` support deterministic continuation. Snapshots bind exact model order, parameters and source-table hashes. Replaying identical controls and measured rate vectors gives identical states. Rates or controls containing NaN, negatives, wrong dimensions or invalid update times are rejected before mutation.

## Readout

`config/mbon_valence.csv` covers all 35 annotated MBON types. Eighteen original named types receive `INFERRED_SIGN` from the transmitter-class/activation-valence association in [Aso et al. 2014, Table 1 and Figures 2/13/14](https://elifesciences.org/articles/4580): the mapped glutamatergic types have negative and mapped GABAergic/cholinergic types positive readout signs. This is an explicit inference; the paper's group activation effects are not claimed as an individually measured sign or strength for every cell. Seventeen newer, merged, or ambiguous labels remain unassigned, contributing zero to the partial readout rather than being declared behaviorally neutral.

The readout averages activity within each signed type and then averages signed type rates. Equal type weights are an assumption. Positive means inferred approach, negative inferred avoidance, in signed Hz. It is not a probability or a motor command. Canonical compartments, current empirical compartments and anatomical disagreement flags are retained separately; empirical clusters are never renamed to force canonical agreement. The existing annotation/compartment reference supplies type correspondence. No inferred driver lines are added. Body readout remains `NOT-RUN`.

`MBONValence(neurons, table).evaluate(rates_hz)` caches the vector for use in a loop; `valence_from_rates(neurons, rates_hz, root)` is a convenience adapter.

## Validation boundary

`validate_state(root, trial_runner, runtime_provenance=...)` refuses to run before the full corrected V-NM-E passes and verifies prerequisite provenance recursively. Callback-backed trials must carry the complete runtime dependency manifest, checked before and after execution and saved in the standalone J artifact. Software checks cover the 76/52/24 source census, identity-bound persistence, replay, finite source/gain outputs and all parameter sweeps. V-NM-J requires actual fed/starved network trials with the same odor, seed, parameters and frozen weights. A change in inferred MBON valence is reported as the measured effect. The gate requires different decoded sign categories (avoidance, exactly neutral, approach); a changed score within the same category remains a biology failure. No synthetic score is substituted if a network trial is unavailable, and coefficients are never fitted to force a sign change.
