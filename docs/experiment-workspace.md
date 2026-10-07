# Cognesia experiment workspace

Open `./Open Cognesia.command`, or run `.venv/bin/flybrain view --port 8794`.
The server opens idle. Existing experiments and the legacy batch commands remain available.

## Current workspace (2026-10-02)

The left inspector has **Experiment**, **Sensory map**, and **Pre-simulation** tabs. Experiment starts with BANC, Cognesia, and FlyWire selection (BANC is the default), followed by chemical, visual, and electrode inputs. Existing checkpoints and imported experiments retain their source identity. Prior layout and setup preferences are backed up during the one-time migration.

**Sensory map** opens the selected model's compound-eye columns before a simulation. Click a facet or search by column, receptor, or root ID. Body & senses searches source anatomical interfaces by body part, nerve, and side. Optical assumptions, unassigned receptors, and modeled organ links remain explicit; the presence of a menu entry does not establish measured coverage.

**Pre-simulation** contains computation and recording scope checkboxes, body/enzyme options, duration, integration step, sample interval, and CPU threads. Check model size resolves the actual selected neuron and connection counts and estimates memory. Connections are determined by the source graph and selected tissue. **Run**, state-dependent pause/resume controls, actual engine progress, and **Emergency stop ALL** remain at the bottom of the inspector.

The adjustable **Timeline** shares one time ruler and playhead across input tracks, replay clips, response clips, and stacked curves. Double-click a clip to replay it; response clips include one recorded sample of context on either side. The **+** button opens stimulus editing, signal search, response threshold, and In/Out clip tools. Results and Next run distinguish saved output from the next experiment. Region response clips use recorded voltage threshold crossings; recordings without region averages show explicitly named cell-type responses where available. These crossings do not prove causal propagation. Live execution shows its phase and time; response clips and curves appear after results are saved.

Saved experiments and anatomy display tools are buttons above the brain. Detailed curve analysis and Parameters remain separate views. The older descriptions below document additional supported features and earlier arrangements.

## Using the workspace

The first screen has four views: **Fly body**, **Brain**, **Simulation settings**, and **Comparison**. Quick settings update the same experiment controls used by the full editor. Scroll below for grouped input, brain inspection, eye, chemistry, and timeline tools; open only the groups you need. **Parameters** is a separate page and completely replaces the simulation workspace. Switching pages or changing settings does not start execution.

1. Open **Simulate → Timeline & tissue → Design experiment**. Choose FlyWire v783, BANC v888, or the versioned combined model. The combined model contains 175,401 neurons and 13,542,180 directed edges, with continuous BANC brain/nerve-cord connectivity and evidence-qualified FlyWire annotation overlays. The model catalogue exposes availability and immutable hashes.
2. Choose **Compute scope** and **Recording scope** independently. Display isolation and clipping never alter either selection. For selected computation, the default surrounding inputs come from compatible reference recordings. If none exists, Run performs **Prepare reference → Run selected circuit**. Incoming neural signals, chemicals and peripheral contributions retain their original clocks and source denominators. Excluded tissue cannot react to your intervention.
3. Search **Body, senses, and organs**, enable individual anatomical modules, and set their normalized external drives. Select **Enzyme reactions** to adjust ChAT, AChE and TβH, compartments, substrates and kinetics. Enabled modules and enzyme pools are saved and chartable.
4. Add timeline events for visual input, rest, electrodes, chemical levels, enzyme activity, targeted interventions, recording windows and checkpoints. Drag event bodies to move them; drag their right handles to resize. Exact numeric timing and repetition are available. Preview resolved target identities and memory before running.
5. **Run simulation**, **Pause**, **Resume**, **Step**, **Save checkpoint** and **Stop** are in Simulate. Other tabs only edit drafts or navigate here. Live activity is raw numerical output; matched differences become available only after the sequential control finishes. Stop saves committed samples as an explicitly partial recording.
6. Choose a checkpoint under **Branches from saved states**. Optionally enter an earlier source time to reconstruct from the preceding state. Queue an unchanged continuation and a configured intervention sibling, then explicitly run the queue. Parents stay immutable. The comparison panel overlays saved signals and plots B − A at exact shared timestamps.
7. In any analysis chart, open **Tools**, enable interval selection and click two endpoints or drag across the trace. Handles and exact time fields adjust the same snapped samples. The formula uses an unwindowed Fourier series, initially eight harmonics, with coefficients, reconstruction, residuals and RMSE. Spectrum windowing is separate. Export retains the samples, units and source range.
8. Use the top-right **Layout** icon to edit a miniature workspace. Split, drag, resize, add, close or duplicate panels; Apply or Cancel the draft. Named layouts persist. Extra views have independent cameras/signals/selections while sharing recording identity and playback time.

Brain views support XYZ clipping/slabs, section projection, multiregion isolation and directed A→B/B→A connectivity. Anchor geometry is explicitly labeled where full morphology is unavailable. Instrument views import EEG CSV channel/time/unit data and NIfTI-1 MRI/fMRI volumes. Anatomical overlays require a model- and volume-hash-bound registration transform; independent viewing works without one. Synthetic EEG/fMRI is not invented from population means.

## Desktop notes and session archives

The macOS app uses its native menu bar for Simulate, Parameters, Settings, layout, and execution commands. **Simulation → Stop All — Emergency** remains enabled even while the workspace is loading. The Notes panel stays fixed on the right while the scientific tools below the main workspace scroll.

Press **⌘N**, drag an area of the brain, fly, chart, or another panel, then type the note. Notes save locally while typing. The linked-area button restores the saved recording/time and highlights the selected area. Chart notes retain the source recording and signal identities, including overlays from multiple recordings. Deleting a note offers Undo.

Press **⌘S** or choose **File → Save Session** to create a compressed `.cognesia-session.zip` and choose an export location in the native Save dialog. It contains the original notes, area/time links, current draft, display/layout/chart settings, and available linked recording files. `Summary.md` provides excerpts grouped by recording/view and links to the original notes; `connections.json` records those shared-context relationships. This is a local, extractive summary, not an inferred scientific conclusion. Missing recordings are listed in the manifest. Global source datasets and live engine memory are not bundled; complete engine restart still uses the existing checkpoint workflow.

## Original YAML protocols

**Import JSON / YAML protocol** accepts native timelines and the existing odour/DAN/learning protocols. Native timelines compile to integer neural steps. Legacy protocols retain their original controls, units, named source mappings, notes and exact YAML text, and run through the existing verified neuromodulatory core from the same Simulate toolbar. Known source/compartment mismatches and unexecuted sweep definitions remain visible.

The original core supports finite execution, live activity, pause/step/resume, saved raw traces and partial stop. Its historical snapshot is incomplete, so full-state restart branching is explicitly unavailable for that engine. The new full-model session engine provides complete checkpoints; the importer does not misrepresent a partial old snapshot as equivalent.

## Persistence and interfaces

- `build/model-versions/<hash>/`: frozen model manifests, identity tables, connection arrays and provenance ledgers.
- `checkpoints/<id>/`: versioned JSON/NPZ state, typed engine/component state, configuration fingerprints and parent identity. Incompatible restores fail before engine mutation.
- `boundaries/<id>/`: typed, model-qualified reference inputs and initial state for selected replay.
- `sessions/<id>/`: atomically committed numerical chunks and disk-backed voltage buffers. Committed chunks survive interrupted/stopped sessions.
- `runs/<id>/`: historical-compatible playback artifacts, exact recorded neuron order, activity, chemistry, enzyme and organ arrays, source manifests and warnings.
- Browser storage holds versioned experiment drafts and panel layouts. Imported instrument files must be reimported after reload.

New APIs include `/api/models`, `/api/peripheral`, `/api/selection/preview`, `/api/sessions`, `/api/sessions/<id>/commands`, `/api/checkpoints`, `/api/checkpoints/<id>/branches`, `/ws/sessions/<id>`, `/api/analysis/interval`, `/api/connectivity`, and `/api/protocols/import`. Creating a branch or preview never starts a worker. Session frames carry session/model identity, sequence, integer step, units, timing and actual diagnostic values. Display transport can drop old frames; it cannot skip integration steps.

## Evidence and limitations

See [scientific status](experiment-workspace-science.md), [source decisions](model-sources.md), [browser verification](workspace-ui-verification.md), and the top-level [execution report](../REPORT.md). Numerical agreement, source integrity and browser tests do not establish biological validity. Organ mechanics, receptor transfer magnitudes and enzyme kinetics are labeled model assumptions. Unresolved donor-sector accuracy retains the documented scaffold rather than claiming a universally most-accurate composite. Missing body registration, unassigned photoreceptors and unavailable empirical new-provider mushroom-body mappings remain explicit.
