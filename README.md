# Cognesia

**v0.0.1 · Experimental computational neuroscience workbench**

Cognesia is a local research workbench for exploring *Drosophila melanogaster*
(fruit fly) connectomes, neural simulation, visual stimulation and neuromodulation.
It combines a Python simulation engine with an interactive 3D browser interface
and an optional native macOS window. Supported source pathways include FlyWire
and BANC, with model assumptions and data provenance documented separately.

The Python package and command remain named `flybrain` for compatibility.
Cognesia v0.0.1 is an early experimental source release; it does not establish
biologically validated vision, learning or behavior.

[Installation](#installation) · [Workspace guide](docs/experiment-workspace.md) ·
[Model sources](docs/model-sources.md) · [Scientific limitations](LIMITATIONS.md) ·
[Release notes](CHANGELOG.md) · [Public GitHub setup](docs/PUBLISHING.md)

## What you can explore

- View fly anatomy and connectome-based neural models in 3D.
- Configure visual stimuli, virtual electrodes, chemical fields and timelines.
- Record and compare model signals, pause experiments and branch supported checkpoints.
- Inspect source provenance, measured anatomy, modeled links and numerical diagnostics.

## Installation

Use **Python 3.12** from a source checkout. The browser interface requires WebGL;
the optional macOS wrapper requires macOS 13 or later and Apple Command Line Tools.
Large model builds and simulations need substantial disk space and memory. The
default process-tree memory guard is 40 GB; inspect model size before running.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/flybrain --help
.venv/bin/flybrain fetch
.venv/bin/flybrain validate --gate V-A
.venv/bin/flybrain build
.venv/bin/flybrain view --open
```

Run from the repository root and stop if any preparation command fails. A fresh
checkout has no downloaded connectome or saved experiments. The current viewer
requires the initial FlyWire fetch, integrity check and build above even when
you plan to use BANC. Startup also acquires visual-column metadata if missing.
Once prepared, it opens idle at <http://127.0.0.1:8794>. In
**Experiment → Model sources**, use **Acquire BANC sources** for the default
BANC model. The Cognesia composite also requires its documented
source inputs; see [model sources](docs/model-sources.md). The historical
FlyWire data/build commands are listed under [Run locally](#run-locally).
Network downloads and model preparation may take time and require additional
memory. A missing input or failed gate is reported rather than replaced with
fabricated data.

On macOS, after installation, you can also double-click **Open Cognesia.command**
or [build the native window](macos/README.md).

## Evidence and release contents

The unmodified original specification is in [BUILD_BRIEF.md](BUILD_BRIEF.md).
[REPORT.md](REPORT.md) retains historical execution evidence; missing gates are
explicitly NOT-RUN. Links in that report to `build/`, `runs/` or `data/raw/` refer
to local artifacts **not bundled in this source release**. The historical counts
and timings are not a fresh v0.0.1 validation run. Reproduction requires acquiring
the original inputs and rerunning the relevant checks.

**License: All rights reserved** for original Cognesia code and documentation;
see [LICENSE](LICENSE). Third-party assets retain their licenses and attribution; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Current workbench and scientific status

**The unified whole-brain visualizer runs locally.** Double-click **Open Cognesia.command** or **Open Flybrain.command**, then visit [127.0.0.1:8794](http://127.0.0.1:8794). It opens stopped. Visual stimuli, electrodes, chemical fields and internal-state scenarios use the same full 138,639-neuron network and 3D anatomy. Choose a fed, starved, dehydrated or stressed state; run a bounded experiment; then inspect recorded voltage or chemical exposure. See [whole-brain chemistry](docs/wholebrain_chemistry.md) and [visual controls](VISUAL_SIMULATOR.md).

The app and browser automatically refresh when interface files in this checkout change. Python, configuration and protocol edits restart the viewer once all experiments and preparation have finished; paused experiments also defer updates. Drafts and layout preferences remain saved. The footer reports live-update status. See [desktop live updates](macos/README.md) for details and `flybrain view --no-watch` to disable watching.

The expanded lab includes **real branching anatomy for every model neuron**, up to five million displayed source segments, full selected-neuron arbors, **34 editable model controls**, **16 virtual electrodes**, live CPU/RAM readings, and sustained **BEAST / Maximum detail** compute presets. Place electrodes on the schematic fly or select individual neurons. Branch colors show each neuron's recorded voltage; certified axon/dendrite labels and spatial cable electrophysiology are not supplied by this model.

[Whole-brain merge results](WHOLEBRAIN_MERGE_RESULTS.md) records the full test suite and real fed/starved integration checks. In Chemicals mode, branches show the owner's recorded compartment exposure instead of voltage.

**Scientific status: experimental.** V-A data integrity and V-E ten-trial Brian2 comparison pass. The default uniform hybrid fails V-C after 1,000 ms: 39,945 clamps and max |dV/dt| 4.5284 mV/ms, above the 0.001 limit. The original validation pipeline remains stopped. The visual simulator is an explicitly requested exploratory continuation using the unchanged neural core, matched baseline runs, and visible instability diagnostics. It does not claim biological validation.

On this Mac, double-click **Run Hybrid Check.command** to reproduce the stopped run. The command returns failure honestly and refreshes the report; no parameter tuning occurs.

## Neuromodulation extension

The [final specification](NEUROMOD_FINAL.md) explicitly corrects the plasticity equation. The coupled 13,300-neuron core, measured DoOR odours, empirical compartments, receptor fields, normalized plasticity, endocrine state, protocol runner and diagnostic console are implemented. The default launcher now opens the integrated full-brain viewer; use these commands for the smaller diagnostic core:

```sh
.venv/bin/flybrain neuromod build
.venv/bin/pytest -q
.venv/bin/flybrain train protocols/forward_pairing_gamma1.yaml
.venv/bin/flybrain capacity
.venv/bin/flybrain rt serve --core
```

If explicitly started with `rt serve --core`, the [diagnostic console](http://127.0.0.1:8795) shows actual model time, measured speed, memory, controls and recorded results. Timeline, atlas, learning and divergence views share that core engine. [Runtime and recording details](docs/live_console.md) explain the event clock, JSONL replay, ZIP export and assumptions. `capacity --full` measures all enumerated source-type handles; the shorter default is a labeled pilot. These earlier core measurements do not certify the new full-brain chemical coupling.

[Completed implementation and measured results](NEUROMOD_RESULTS.md) summarizes the 487 passing tests, exact 60-second replay, full 92-handle sweep, measured performance shortfall and biological failures.

The corrected source gate verifies per-neuron nitric-oxide cotransmission, 4,133 KC sNPF sources and the two-neuron OA-VUMa5 overlap. The [compartment comparison](docs/compartments.md) preserves PPL101's empirical g4 versus published g1 assignment. [Odour coverage](docs/odour.md) is 28/53 named ORN types for OCT and 22/53 for MCH. Missing measurements are not fabricated.

The [normalized plasticity reference](docs/plasticity.md) now passes all twelve points. The historical literal-equation failure is preserved in [the superseded audit](docs/neuromod_reference_findings.md). It is no longer the active equation. Biological training, state, extinction, replay and measured speed have separate evidence in [REPORT.md](REPORT.md); a software pass does not certify the biology.

The historical [odour-driven diagnostic](docs/odour_sparseness.md) failed: approximately 68% of KCs fired rather than the requested 2–12%. Its changed-input evidence is marked stale in the report. Current runtime measurements still exceed configured voltage bounds with clamping disabled; the console retains these diagnostics. Reproduce the measurements with:

```sh
.venv/bin/flybrain validate --gate V-NM-ODSP
.venv/bin/flybrain validate --gate neuromod-runtime
.venv/bin/flybrain validate --gate stability --threads 8
```

The [normalized whole-brain variant](docs/hybrid_stability_variant.md) is independently measured and preserves the original base engine/evidence. Its resting-stability checks do not establish a validated visual pathway or body decoder. The core readout is an explicitly inferred MBON valence, with unsupported MBON types left unassigned.

## Run locally

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/flybrain fetch
.venv/bin/flybrain validate --gate V-A
.venv/bin/flybrain build
.venv/bin/flybrain validate --gate V-E
.venv/bin/flybrain run reference --duration-ms 1000
.venv/bin/flybrain run dark
.venv/bin/pytest -q
.venv/bin/flybrain report
```

Run these commands from this directory, or pass `--root /absolute/project/path` before the subcommand. Downloads are cached in `data/raw/`; hashes and schema inspections are saved in `build/`. No fabricated replacement connectome is used. The optional full synapse file is 9.49 GB and is fetched only with `fetch --synapses`.

## Reproducibility and interpretation

- [PARAMETERS.md](PARAMETERS.md) is generated from the provenance-bearing parameter configuration.
- [DESIGN_NOTES.md](DESIGN_NOTES.md) records explicit resolutions of ambiguities in the brief.
- [LIMITATIONS.md](LIMITATIONS.md) describes scientific boundaries.
- `requirements.lock` records the installed versions from this machine.
- The default resident-memory guard is 40 GB over the process and its children. Stages check it cooperatively and retain failure diagnostics.

Do not interpret successful package tests or a data-integrity pass as proof of direction selectivity or complete biological validation. See the current validation table for exactly what ran.

`run reference` is the explicitly requested all-LIF comparison experiment: it supplies Poisson events to 20 neurons and records the full network's spikes. It is not an eye stimulus or evidence that the hybrid visual model has passed. Full V-E uses ten one-second trials; shorter smoke runs cannot satisfy that gate.

`run dark` tests the hybrid model with no external input: 1,000 ms equilibration followed by the 5,000 ms dark control only if equilibration passes. A failed gate stops the stage and returns a nonzero exit code; see the saved report and diagnostic arrays. `validate --gate hybrid` runs the same protocol.
