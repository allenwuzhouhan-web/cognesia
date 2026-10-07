# Whole-brain chemistry and internal state

Open the unified viewer at http://127.0.0.1:8794 with either **Open Cognesia.command**
or **Open Flybrain.command**. It opens idle. Choose a scenario and run a bounded
experiment when ready; loading a recording does not start playback.

The chemical layer uses the original full brain and its released neuron order.
It shares neural time, the visual stimulus, electrodes and anatomical playback.
The smaller 13,300-neuron console remains a separate command-line diagnostic; it
is no longer the default Cognesia launcher.

## Experiment controls

Enable the chemical layer, choose **Fed**, **Starved**, **Dehydrated** or
**Stressed**, and adjust the initial internal state and external context. Presets
are explicit model assumptions. They initialize energy, hydration, arousal and
stress; they do not stand in for measured fly physiology. The model also retains
circadian phase, endocrine release and hormone state.

The **Chemicals** input tab exposes eight named concentration sliders: dopamine,
octopamine, serotonin, nitric oxide, short neuropeptide F, pooled peptide signal,
tyramine and acetylcholine. Moving a slider enables its manual override. Exact
numeric fields accept finite values from 0 to 2 arbitrary model units, including
zero. Unselected chemicals remain controlled by the model. **Set initial levels**
initializes each selected field before pre-equilibration, then lets it evolve.
**Hold these levels** reapplies the value after every field update and before
plasticity and receptor effects. Both apply uniformly to every compartment and
to both branches of the paired experiment. They do not edit a recording or start
an experiment. **Return to model control** removes all manual overrides.

Energy, hydration, general arousal, stress and daily clock phase have independent
sliders and exact numeric inputs. The scenario panel explains research context
and which internal state was explicitly configured. It cannot infer starvation,
sexual arousal or another animal state from global chemical concentrations.
See [chemical scenarios and sources](chemical-scenarios.md).

## Region labels and the whole fly

Brain-region selectors, chart labels and chemical readouts use full names.
Search can match either a name or a source identifier. The atlas combines the
released neuropil assignments with chemical compartments; duplicate optic-region
keys appear once. Selecting a region highlights its assigned neurons. Floating
labels are weighted centers of their annotation anchors, not anatomical region
boundaries. The symbolic hemolymph pool has no invented spatial label.

The whole-fly panel uses the complete, undecimated NeuroMechFly full-resolution
surface model: 447,417 triangles across 69 articulated parts. Transparent and
natural-surface modes, opacity, brain visibility, anatomical labels, orbit/zoom
and head focus are available. The original brain's relative geometry and neuron
order are retained in an approximate head alignment across different animals.
This is a display registration assumption, not a measured whole-animal nervous
system. [Asset provenance and license](../src/flybrain/web/assets/fly/NOTICE.md)
documents the scientific sources, transformations and file checksums.

The whole fly shares the same saved voltage/chemical frames, mode and playback
time as the original brain view. It has its own synchronized playback bar.
Without a recording it shows static anatomy; no electrical currents, motion or
chemical measurements are fabricated. Opening the page and editing controls
leave the simulation stopped. No fly movement or peripheral nerve activity is
inferred from the brain model.

Chemical fields change receptor gain, threshold, membrane time constant and
specified synaptic release. The existing plasticity rule updates actual
Kenyon-cell-to-MBON edges when enabled. Endocrine signals change specified source
release and receptor gain; they are not added as electrical currents. The
original compound eyes and electrical stimulation remain available.

## What the colours mean

The chemical selector exposes DA, OA, 5HT, NO, sNPF, peptide_pool, TA and ACh.
Recorded model concentrations are projected through each neuron's compartment
membership onto the existing anatomical points and branches. The timeline and
state readings use the same recorded time as the voltage view.

These are compartment concentrations in model units. Changes show model release,
clearance and the configured spread between compartments. They do not depict
individual molecules, measured physical diffusion trajectories, or a separate
concentration at every branch segment. A neuron's branches share its projected
exposure. Missing field data in an old recording remains missing.

Spiking sources use actual recorded activity. Graded neurons use an explicitly
assumed conversion from graded release to a normalized source drive; no spikes
are invented for those cells. Hormone and receptor coefficients retain their
assumption labels.

## Reproducibility and controls

Active experiments save their chemical concentrations, state/hormone time series,
compartment membership, scenario settings and implementation/configuration
hashes with the neural recording. The paired visual baseline starts from the
same neural and chemical state, so the visual difference is not confounded by a
different initial nutritional state. Disabling the chemical layer preserves the
original visual-experiment path.

**Stop** stops playback and requests cancellation of an active experiment at the
next bounded checkpoint. **Clear cache** removes regenerable display assets and
loaded browser buffers; it preserves source data, master anatomy, saved
recordings, configurations and validation evidence. Both launchers keep the
viewer service independent of the terminal, without starting a simulation.

## Scientific boundary

The original whole-brain model has failed numerical/biological validation. This
integration is an experimental extension, not a new biological validation pass.
The smaller core's replay and plasticity-reference checks do not validate this
full-brain coupling. State presets and chemical views make the implemented model
inspectable; they do not establish that a real fly responds the same way.
