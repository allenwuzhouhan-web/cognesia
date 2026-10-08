# Visual-system experiment workspace — implementation plan

Created 2026-10-08, before feature implementation. This extends the current dirty working tree; it does not replace the concurrent ParaLimbo compiler/release work. No resets, stashes, model rebuilds, source replacements or modifications to active experiments are planned.

## Audit and scientific contract

Read: REPORT.md, VISUAL_SIMULATOR.md, docs/model-sources.md, docs/local-agent.md, docs/fly-model/README.md and PLAN.md; inspected model_eye, model_registry, model_anatomy, visual_experiment, experiment_session, session_stream, visual_server, workbench_api, api_tools, local_agent and existing frontend anatomy/analysis modules. No repository AGENTS.md was found in the workspace ancestry.

Existing working components: full native graph dynamics; versioned model artifacts; graded photoreceptor optical drive and paired constant-luminance control; recording selection without circuit truncation; journals, live frames, checkpoint controls and replay; provider-qualified anatomical anchors; real FlyWire morphology; Fourier/numerical chart tools; bounded authenticated research tools and saved studies/reports.

Missing: a single linked visual-system workspace, downstream mapping coverage ledger, spatial population panels tied to recordings, source-count/effective-weight matrix separation, structural footprint inspection, evidence capture tied to shared view state, direct image-capable research backend, and a calibrated neural-activity motion decoder.

ParaLimbo's optical adapter transfers a small number of FlyWire columns through checked cross-specimen correspondences and gives known-side remaining photoreceptors position-ranked columns. Neither transfer nor rank establishes measured BANC retinotopy. Unknown sides stay unassigned. Downstream visual-field coordinates remain absent unless actual mappings exist. FlyWire columns also use modeled field orientation. ParaLimbo/BANC currently provide anchors rather than reconstructed neurites or measured neuropil meshes; FlyWire source morphology must never appear under BANC identities. Coarse source cell labels must remain coarse.

Point-neuron branch coloring is one voltage per neuron. Anatomical counts, assumed fast signs, and effective modeled weights are separate. Existing V-C equilibration and later biological/performance failures remain visible. Normalized optical luminance is not photon flux, spectral/color or polarization vision. Displaying a neural activity sheet does not reconstruct subjective experience.

Reference: Lappalainen et al. Nature 2024, doi:10.1038/s41586-024-07939-3, supplied Figure 1 inspected. Official author implementation: https://github.com/TuragaLab/flyvis . Its 64-type task-optimized model and optic-flow decoder are distinct from Cognesia. Figure organization is an interaction reference, not reproduced results or substitute geometry.

## Dependencies and milestones

1. **Freeze contracts and audit (root + data/vision/UI audit).** Preserve existing working-tree changes. Save this plan. Pin every selected recording to its actual model hash. Establish limits and model/run/index contracts before UI integration.
2. **Scientific data layer (data worker).** New visual_workspace_data.py. Load immutable recorded/model identities; map recording columns explicitly; source-qualified mapping and coverage; bounded maps/traces, topology-derived matrices/footprints, and compatible comparisons. Tests cover absent coordinates, partial records, mismatched model/hash, sides, units and numeric equality.
3. **Workspace service and analysis (root, depends on 2).** New visual_workspace.py, authenticated routes and existing tool catalogue hooks. Durable per-run view state/revision, bounded query cache, validated captures and evidence links, numerical comparison and explicit follow-up options. Add a fitted activity-only motion readout with separate training/calibration/evaluation identities and honest unfitted/unsupported states.
4. **Interactive linked UI (UI worker, depends on contracts from 2–3).** New isolated visual-system page/modules. Resizable panels; provider-specific anatomy and schematic sheets; missing-aware population tiles; matrix/footprint; traces/stimulus/retinal input; single time, selection and quantity mode. Native-compatible navigation. Bounded live polling and replay must never change solver integration.
5. **Research vision and tool evidence (vision worker, depends on 3).** Keep GPT-OSS reasoning; add configurable real multimodal backend. Detect unsupported backends and perform an image-input verification request before claiming image capability. Supply rendered PNG plus bounded numeric provenance. Persist figures, inspections and evidence highlights with study support. Existing auth, operator and compute controls remain authoritative.
6. **Bounded end-to-end exercise (root, depends on 2–5).** Run actual full supported graph with limited recording selection, moving edge, paired control, opposite direction and supported intervention. Record finite/clamp/mapping diagnostics, original recordings, comparisons and any failures. Reopen recordings and check equality. Never manufacture a biological acceptance gate.
7. **UI and regression verification (all, then root).** Meaningful Python/JS failure cases; authenticated HTTP tests; actual browser and native workspace where available: resize, camera, selection linking, timestamps, live progress, pause/scrub/replay and capture. Real image inspection only if an image-capable runtime and credentials exist. Save exact blocker otherwise.
8. **Documentation and report (root).** Usage/configuration, verification report, representative captures and machine-readable evidence. Update REPORT.md with observed outcomes and independent software/numerical/biological status.

## Acceptance criteria

- Every science payload/export carries model ID/hash, run ID, qualified identity, quantity/units, raw/control/difference mode, actual recorded time, mapping and analysis provenance.
- No recording-local index is interpreted as a model index; incompatible comparisons and stale identity selections fail clearly.
- Missing mappings/recordings show missing rather than zero; known population labels and wiring retain original resolution and recurrence.
- Panels share one selection and time cursor. Matrix source/target selections link to anatomy/maps/traces. Camera/layout requests and evidence highlights can be issued by research tools.
- Numeric values independently match saved arrays; display downsampling is disclosed and does not mutate saved data or integration.
- Captures have immutable content hashes and sidecar metadata. Research conclusions cite captures, exact runs, populations and intervals.
- Decoder features contain simulated neural activity only; fitted parameters and held-out evaluation are separate from stimulus-reference motion. Untrained output is absent.
- Existing authentication and experiment leases remain enforced; active work is not cancelled to test the feature.
- Software operation, finite/reliable integration, and biological prediction claims are reported separately. Unavailable geometry, measured retinotopy, biological datasets and image credentials remain explicit limitations.

## Execution notes

Parallel ownership: mapping/data worker owns its new Python module/tests; UI worker owns new visual-system web files/tests; vision worker owns new agent module/tests/docs plus coordinated local-agent hooks. Root owns service, routes, tool registration, decoder, launch integration, acceptance artifacts and final verification. Existing shared files receive small scoped patches only.
