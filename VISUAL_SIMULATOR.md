# Cognesia visual simulator

An interactive local viewer for visual input and recorded activity in the FlyWire v783 whole-brain network. All **138,639 neurons** participate in each full visual run. The neural core is unchanged; the visual layer adds eye input, paired experiments, playback, and readouts.

**Scientific status: experimental and unvalidated.** The original V-C stability check remains **FAIL**. The viewer does not establish biological motion selectivity or complete the full visual-validation battery.

## Open and explore

Double-click **Open Flybrain.command** in the project folder. Alternatively, from that folder run:

```sh
.venv/bin/flybrain view --open
```

The viewer opens at [localhost:8794](http://localhost:8794). Keep its terminal open while using it; press Control-C there to stop the server. If the server is already running, open the address directly.

The flat, light workbench has two keyboard-accessible workspace tabs. **Simulation** contains visual input, electrodes, the brain viewport, playback, and measurements. **Parameters** contains compute presets and neural/optical settings. Arrow keys switch tabs when a tab has focus. White drawing areas, restrained category colors, and discrete voltage-scale swatches keep controls separate from recorded data.

## Customize the workspace and compare signals

Drag the dividers between panes to change their widths, or the handles beneath panes to change their heights. Focused handles also accept arrow keys; double-click resets one handle and **Reset layout** restores the whole layout. Sizes are saved locally in this browser and are clamped to fit the current window.

**Compare signals** opens the chart workspace. Search by cell type, neuron index, root ID, or optical column; filter by source and anatomical side. **Chart** beside a readout or in a neuron inspector pins that signal. Up to six independent charts can be resized using their lower-right corners and reordered with **Move left/right**. Up to four signals of the same units can be overlaid in one chart. Pinned charts retain copied values and their run identities when another recording loads. CSV export saves the currently plotted data, units, run IDs, and Fourier settings. Crosshairs and click-to-seek apply to signals from the active recording only.

All **10,582 annotated photoreceptors** are searchable by exact identity. Their membrane-voltage curves include the **1,859 receptors without a mapped optical column**, explicitly marked as unmapped. Eye-column curves instead show the saved Gaussian-smoothed normalized luminance. The two default eye curves average 785 left and 796 right optical columns; these are light-input means, not receptor-voltage means. Click the eye diagram to choose a column, then chart its light input or choose one of its mapped receptor neurons.

Each chart offers **Time curve**, **Fourier spectrum**, and **Fourier reconstruction**. The spectrum is a one-sided amplitude spectrum in the original signal units, with optional mean removal and a periodic Hann window corrected for coherent gain. It is not a power spectral density. Reconstruction uses the original unwindowed Fourier-series coefficients and original mean, with harmonics 1 through K; **All** reconstructs every original sample. No zero padding or extrapolated samples are added. Sample interval, Nyquist frequency, and frequency-bin spacing are shown. The finite record is treated as one period, so boundaries, transients, aliasing, and model instability can affect interpretation; Fourier components do not establish biological frequency tuning.

**Left side / Right side** camera views and moving **L / R** markers use the median physical positions of the corresponding annotated optic neurons. They indicate the fly's anatomical sides, not fixed screen edges. The eye-display orientation selector swaps left/right display order when facing the fly; it does not change stimulation or neuron identity.

The customizable interface passed **144 Python tests and 13 JavaScript signal tests**, plus browser checks of pointer and keyboard resizing, saved dimensions, receptor search, overlays, Fourier controls, and orientation. Independent extraction from the completed BEAST recording matched the displayed neuron and eye-mean arrays exactly. Full Fourier reconstruction differed by less than 6e-13 mV for neuron 10 and 1.5e-14 normalized luminance for the eye means.

## Simulation lab and heavy workloads

The workbench exposes **34 neural and optical controls** and up to **16 virtual electrodes**. Runtime settings are saved with each recording and do not overwrite the original parameter files. The **BEAST** preset uses all available CPU threads, 0.05 ms integration, 8,192 optical rays per column, a 3,000 ms stimulus plus its paired control, and 10 ms voltage recordings. **Maximum detail** extends this to 10,000 ms per branch, 0.025 ms integration, and 16,384 rays. These presets perform additional neural integration and optical computation; no dummy CPU load is added.

The live CPU and memory gauges show measured machine and process usage. macOS controls fan speed; workload selection does not override thermal protection or guarantee a particular fan speed. **Stop experiment** requests cancellation at the next optical or neural checkpoint. The server permits one paired experiment at a time. The process memory guard remains 40 GB; full raw/baseline/delta voltage recordings have a separate 3 GB allocation limit. Invalid combinations explain the constraint before the experiment starts.

Choose **Electrodes**, select a site on the schematic fly, and set signed input amplitude, frequency, duty percentage, timing, and phase. Zero frequency means DC; other frequencies produce square pulses. Multiple electrodes add together, including where their targets overlap. Individual-neuron stimulation is available from the neuron inspector. Exact targets and full neural-timestep waveforms are saved in `electrode_targets.npz` and `electrode_waveforms.npz`.

The body is a selection diagram, not a simulated animal or tissue conductor. Eye sites target the annotated photoreceptors (5,374 left; 5,208 right). Antennae select 3,424 sensory neurons annotated with nerve AN. Legs and wings each select the same 2,317 ascending/body-afferent proxy neurons: this brain dataset has no complete ventral nerve cord, muscles, or limb mechanics. Input amplitudes are **model mV-equivalent membrane drive**, not a prediction of what a physical battery or electrode would do. The paired control has constant mean luminance and all virtual electrodes off.

## Real branching anatomy

The branching view uses the [official FlyWire v783 morphology archive](https://zenodo.org/records/10877326), not invented branching decorations. The 5,355,543,468-byte archive contains 268,281,651 source skeleton nodes. Source coordinates are physical nanometers and are converted to micrometers; the annotation voxel correction must not be applied again. The downloaded archive is checked against its publisher MD5, `a4c104776f33ec539ef859064c4de3df`, before import.

All available model-neuron geometry is retained in packed files on disk. Whole-brain display samples 500,000, 1,000,000, or 5,000,000 actual source segments; each segment retains its exact neuron owner for activity coloring. Full source detail for an individual neuron can be loaded separately. Coverage and missing neurons are reported explicitly, including partial coverage while the archive is being prepared.

The completed local import covers **138,639 / 138,639 model neurons**, with **268,127,063 vertices**, **267,988,424 parent edges**, **zero missing roots**, and **zero unresolved parents**. Every 500k, 1M, and 5M overview was checked to contain all 138,639 distinct neuron owners and finite coordinates. Preparation peaked at **13.506 GB resident memory**. Exact source verification, coverage, and binary checks are saved in `build/visual/morphology/verification.json`.

These are reconstructed, healed neurites. The source does **not** provide certified axon/dendrite labels. The electrical model still has one membrane-voltage state per neuron, shown along that neuron's branches; it is not a spatial cable simulation with independently solved compartments. Branches make the anatomy inspectable without inventing compartment labels or local voltages.

1. Select a **Saved experiment** to replay a completed run, or choose a pattern and press **Run simulation**. Runs compute locally and save automatically. Only one new simulation runs at a time.
2. Choose among **Moving grating**, **Full-field flash**, **Moving edge**, **Looming disc**, **Apparent motion**, and **Dark control**. Adjust the applicable direction, speed, contrast, and duration controls. Apparent motion uses two one-frame point flashes; its interval is quantized to the 240 Hz stimulus clock.
3. Drag the brain to orbit, scroll to zoom, and right-drag to pan. Use Overview, XY, XZ, or YZ to change the view. Select a point to inspect its neuron identity and annotations.
4. Play, pause, or scrub the recorded response. Switch among **Stimulus − baseline**, **Absolute voltage**, **Baseline**, and **Anatomy**. Playback speed changes replay, not the simulation.
5. Use **Cell types**, **Brain areas**, or **Cell classes** for population traces. **Run details** and **Model & provenance** expose the parameters, warnings, and saved-run evidence.

By default, the scene and compound-eye luminance are generated at **240 frames/s**, neural voltages are recorded every **20 ms**, and neural integration uses **0.1 ms** steps. The lab controls and compute presets can change these rates; each saved recording retains its actual settings. A smooth browser animation does not imply a higher recorded neural sampling rate. Previewing a changed pattern does not recompute the displayed neural response: press **Run simulation** to create a matching recording.

## Read the measurements

All voltage views and traces use **millivolts (mV)**:

| View | Meaning |
| --- | --- |
| Absolute voltage / raw | Simulated membrane voltage during the selected stimulus. |
| Baseline | Voltage in a paired run under constant mean luminance. |
| Stimulus − baseline / delta | Raw voltage minus baseline voltage for the same neuron and recorded time. |
| Anatomy | Annotation classes and positions, independent of activity. |

Before each pair, the model runs for a fixed **1,000 ms** at the selected mean luminance. The stimulus and baseline branches then start from the same complete neural and phototransduction states. This is a fixed preparation interval, **not a claim that the network has reached equilibrium**. The baseline retains its own ongoing dynamics. Subtracting it does not stabilize the model or turn a difference into a validated biological response.

Brain-area traces use the actual pre- and postsynaptic neuropil endpoint counts. For each neuron, its weight in an area is the fraction of all its recorded endpoints belonging to that area. Each area's trace is `sum(weight × voltage) / sum(weight)`. A neuron can contribute to several areas. These are **endpoint-fraction weighted mean membrane voltages**, not firing rates, calcium signals, or synapse-local voltages. Counts include endpoints involving partners outside the modeled neuron set and should not be read as the number of unique modeled synapses.

There are **79 source labels**, including the literal source label `None`. The viewer calls that label **Unassigned**; it is not an anatomical brain area. All model neurons have endpoint weights, including neurons omitted from the point display.

## Anatomy, eyes, and assumptions

The point cloud contains **138,625 annotation anchors**. The other **14 neurons** lack finite display positions and remain in the simulation and readouts. Anchors are not reconstructed neuron morphology, soma-only positions, or synapse locations. Original **4 × 4 × 40 nm** voxel coordinates are converted to physical units before uniform centering and scaling, preserving the source's anisotropic geometry. The display retains dataset XYZ orientation. Coordinate definitions are documented in the [FlyWire annotation schema](https://raw.githubusercontent.com/flyconnectome/flywire_annotations/main/supplemental_files/README.md).

Eye mapping assigns **8,723 of 10,582 photoreceptors** to optical columns. The remaining **1,859** receive no light input because their optical assignment is ambiguous or absent; they remain connected in the model. Light drives mapped graded photoreceptors only. The simulation adds no synthetic connectivity or downstream response forcing.

Retinotopic orientation, eye placement, angular mapping, and phototransduction amplitude and kinetics include explicit assumptions. Visual parameters and their provenance are saved in [config/visual_parameters.yaml](config/visual_parameters.yaml); neural parameters remain in [config/parameters.yaml](config/parameters.yaml). Luminance is normalized to 0–1, not calibrated photon flux. The input uses an assumed normalized membrane drive, not a measured physical photocurrent.

New runs integrate Gaussian optics using 4,096 deterministic scrambled-Sobol rays per column by default, with 8,192 or 16,384 rays available in the heavier presets. Each run checks up to 128 columns and eight representative frames against a four-times-denser reference, requiring maximum absolute luminance disagreement at most 0.005 by default. This is a sampled numerical check, not a global error bound or biological validation. The method, seed, sample counts, and measured error are recorded under `optics` in the run manifest. Early recordings used coarse 5 × 5 quadrature and are marked as legacy in playback warnings; their stored activity is preserved.

## What has actually been demonstrated

The saved **300 ms dark control** (`20260926T005050Z_visual_dark_f2f023`) has exactly zero delta across all **15 × 138,639** recorded voltage values. Both branches nevertheless contain **2,520 spikes** and **11,827 clamp events**. This verifies an identical paired control; it does not show a silent or stable brain, and it is not the formal five-second V-D test.

The saved **600 ms sinusoidal grating** (`20260926T004905Z_visual_grating_d50a3c`) produces nonzero paired differences: a maximum absolute delta of **36.1922 mV**, with **58,872 neurons** exceeding 0.001 mV at least once. This demonstrates stimulus-dependent numerical activity through the connected model. It does not validate direction selectivity, realistic response magnitudes, or biological behavior.

The original dark V-C check failed with a maximum endpoint `|dV/dt|` of **4.52843 mV/ms** against a **0.001 mV/ms** tolerance, plus **39,945 clamp events**. Formal V-D and the complete visual-validation battery remain unpassed. Clamp and instability diagnostics are retained in the viewer and run records; the visual layer does not tune the core to remove them.

## Final application checks

The initial visual application passed **124 automated tests**, plus interactive browser checks of stimulus submission, job completion, recorded playback, saved settings, baseline/absolute/delta modes, neuron inspection, and brain-area traces. The brief-flash recording was scrubbed to exactly **125 ms** and displayed input frame **30**, including the visible flash pixels and the full-rate 1,581-column eye recording. The expanded laboratory has additional electrode, configuration, resource-monitoring, and morphology checks described below.

Two final whole-brain runs used the refined optics from clean revision `359079a9ec8202843a966bd3efc53fd766507b26`:

| Recording | Wall time | Process peak RSS | Sampled optical disagreement |
| --- | ---: | ---: | ---: |
| `20260926T010330Z_visual_grating_f58f81` — square grating, 600 ms | 37.30 s | 1.979 GB | 0.001123 |
| `20260926T010417Z_visual_apparent_motion_d3db12` — point flashes, 300 ms, 25 ms interval | 28.81 s | 2.076 GB | 0.000269 |

Peak RSS is the process-lifetime high-water measurement; it is not an isolated per-run allocation estimate. Both optical checks met their 0.005 sampled numerical tolerance. These checks do not change the failed neural stability gate.

## BEAST integration evidence

The completed electrode-driven recording `20260926T012715Z_visual_grating_748575` ran **3,000 ms** of square-grating input plus its matched control, using **18 threads**, **0.05 ms** integration, **8,192 optical rays**, and **10 ms** recordings. The left-eye electrode supplied **25 mV-equivalent, 50 Hz, 50% duty pulses from 100–2,900 ms** to exactly **5,374 neurons**. All 138,639 neurons were recorded in each of 300 frames, with roughly **499 MB** of raw/baseline/delta float data.

The recorded experiment took **298.864 seconds**. Measured process peak RSS was **2.614 GB**; external samples observed up to **765.3% process CPU** (about 7.65 CPU cores, not a whole-machine percentage). CPU and memory evidence is saved in `build/beast_resource_samples.json`. The full anatomy preparation separately reached 13.506 GB RSS. No fan-speed measurement or guarantee is claimed.

The completed laboratory passed **141 automated tests**. Browser checks verified all-neuron 5M-segment rendering, full selected-neuron geometry, saved pulse-waveform restoration, individual-neuron electrodes, parameter presets, reconnecting to active jobs, and stopping a newly started dark run while retaining completed recordings. The original failed neural stability gate remains visible.

## Saved evidence

Each experiment has a directory under `runs/`. `activity.npz` contains neuron indices, sample times, raw/baseline/delta voltages, both spike trains, and per-neuron clamp counts. `eye_input.npz` records the optical input and photoreceptor drive. `run_manifest.json` records parameters, source and output hashes, timing, mapping coverage, and stability diagnostics. `visual_result.json` and browser playback files provide the displayed summaries and traces.

Neuropil weights are cached in `build/visual_neuropil_weights.npz`, with endpoint counts and source-hash metadata beside it. Existing recordings retain the parameters of their own run; changing configuration affects newly generated experiments.
