# Workspace UI verification — 2026-10-01

This record covers the interval-analysis, layout, and instrument-viewer changes. It does not claim biological validation of the neural model.

## Automated checks

`node --test tests/test_web_signals.mjs tests/test_web_interval_analysis.mjs tests/test_web_layout_model.mjs tests/test_web_instrument_data.mjs`: **25 passed, 0 failed**.

Coverage includes signed DC, sine phase, odd/even Nyquist, original unwindowed reconstruction despite Hann display settings, arbitrary-N reconstruction, interval endpoint normalization and inclusive snapping, immutable sample copies, malformed intervals, cropped nonzero time origins, residual/R² calculations, server coefficient conversion to a seconds-based equation, split/move/swap/collapse operations, duplicate/unknown panel rejection, legacy layout migration, minimum usable pane sizes, CSV channel/time preservation, and NIfTI endian/scaling/affine/storage validation.

All changed frontend modules were also checked explicitly as ES modules with `node --input-type=module --check < path`.

## Browser verification

Verified through the Codex in-app browser against the integrated server at `http://127.0.0.1:8796`:

- Layout icon opens a miniature workspace showing the actual five original panels. Added views appear as real docked panels; Apply uses the draft, and layouts restore after reload.
- Numeric interval 100–500 ms on the saved left-eye trace selects 97 original samples, with an eight-harmonic fit reporting R² approximately 0.9942.
- Two endpoint clicks and a drag with the same screen endpoints both produced requested bounds 217.374067–774.743470 ms. The analysis snapped these to 135 actual samples from 216.666667–775 ms and reported RMSE 0.0004296246 normalized luminance, R² approximately 0.9929.
- Duplicating Signal analysis retained both immutable signal snapshots and the selected interval. Setting the duplicate's harmonic count to 3 left the original at 8.
- An independently added brain view rendered 138,625 located neuron anchors. Its dataset-Z slab plus left-medulla selection displayed 5,232 anchors without changing the primary brain view or simulation scope.
- Fit JSON was saved to `~/Downloads/cognesia-signal-chart-1-1-fit.json`. Read-back verified 135 original time values, fitted samples and residuals; source run `20261001T032519Z_visual_grating_f41d6e`, source signal `eye:left:mean`, seconds-based equation time units, and the selected interval.
- No new browser console errors occurred after the initial development syntax error was corrected.

The same frontend at the earlier `8794` server was additionally verified with local synthetic import fixtures:

- EEG CSV: 128 samples, two named channels, declared millisecond times; channel values preserved. Opening its channel as a chart recovered `-52 + 3 cos(2π·15.625·(t − 0.7) + 0.3)` with RMSE approximately `5.98e-14`.
- NIfTI: an 8 × 8 × 6 × 12 float volume imported and rendered as a 4D series. Changing from voxel-XY to voxel-YZ and selecting frame 6 produced the expected voxel value 98.32664 at (4, 4, 3). Slice and frame controls operated independently of the other panels.

Both browser origins were returned to their original five-panel Default layout, and the temporary verification tab was closed. No simulation was launched by these UI checks.

Additional integrated checks after the protocol and imaging updates:

- Two saved 1,000-ms grating recordings were compared using their R1-6 absolute-voltage traces. The panel rendered A/B overlays plus a second B − A chart at all 50 exact shared timestamps, with 0/0 unmatched samples. No interpolation was used.
- The synthetic 8 × 8 × 6 × 12 NIfTI imported with a SHA-256 identity. A supplied synthetic transform bound to `cognesia-fused-v1`, its immutable model hash, the exact NIfTI hash and dimensions rendered 144,667 source anchors in the selected ±0.5-voxel slab. This verifies transform plumbing only; the synthetic matrix is not a biological registration.
- `tests/test_web_research_data.mjs` adds four passing tests for exact timestamp differences, actual saved/live spike extraction, model/volume/hash/units registration checks, and recovery of source micrometer coordinates before projection.

## Original YAML protocol execution

`pytest -q tests/test_protocol_adapter.py tests/test_legacy_protocol_session.py`: **17 passed, 0 failed**. Native imports resolve exact source indices, retain original JSON/YAML, normalize clock aliases, and reject ambiguous YAML. Legacy imports retain the original odour, named DAN, and frozen-learning test controls instead of converting Hz inputs to mV or field clamps.

The finite session tests verify a 43-ms protocol stops at 43 ms (20 + 20 + 3), actual owned voltage frames and core-to-parent mappings, pause/1-ms step/resume, saved partial stop, explicit unsupported checkpoint response, unchanged frozen test weights, and source-gate failure preservation.

The public pinned DoOR sources were acquired through the existing `fetch_door` validator, with all five expected SHA-256 hashes checked. The shipped `forward_pairing_gamma1.yaml` then resolved 2,279 normative ORNs for OCT/MCH and two positive-known-DA PPL101 neurons. Its nominal g1 versus empirical g4 discrepancy remains visible and unchanged. An actual short core run reached the original dependency gate and stopped because `build/validation_neuromod_field.json` was missing; that attempt did not produce a completed simulation. The original protocol and failure record were retained, and no gate was bypassed.

After the original field/receptor/plasticity prerequisites were prepared, a real 3-ms core transport run completed as `20261001T080207Z_core_protocol_aae7d758`: 13,300 source-verified core neurons, actual raw frames at 0 and 3 ms, 160 logged spikes, no voltage-bound violations, field clamps or weight clamps in that short run. This confirms finite execution and recording, not biological validity or long-term stability. Playback uses exact frame timestamps, because single-stepping and final remainders can yield irregular spacing.

Browser Simulate verification additionally imported the shipped YAML and exported a JSON document that compared equal to all four original blocks, notes, seed and sweep values. A 43-ms finite core fixture launched from the single Run control; Pause was acknowledged at 0 ms, Step advanced to exactly 1 ms, and Resume reached exactly 43 ms. The live display identified raw core activity. A checkpoint request was rejected by the backend because complete core restart state is not available; the initial UI did not surface that rejection, and the integration owner was notified to make it actionable.

That browser run is `20261001T080402Z_core_protocol_7f50528d`, with exact frames `[0, 1, 21, 41, 43]` ms and 11,487 actual spikes. It recorded **1,045 voltage-bound violations**, despite zero clamp events; it must not be described as stable or biologically validated. Its saved spike raster subsequently displayed all 11,487 events in local core indices 0–13,298.

After integration fixes and reload, importing a legacy protocol and loading the saved 3-ms core recording completed without console errors. The import status displayed the PPL101 nominal-g1/empirical-g4 discrepancy and the unexecuted sweep note. The exported `cognesia-protocol.yaml` compared byte-for-byte equal to the original file. Terminal metrics returned to Idle. The active draft was restored to the visual timeline, the workspace to five Default panels, and the complete 1,000-ms grating recording was selected before closing the temporary tab.

The paired recording `20261001T080227Z_visual_dark_1e5507` also loaded in the integrated browser. Separate added panels offered recorded enzyme reaction flux and peripheral organ dynamics. ChAT compartment flux and left antennal chordotonal activation each rendered 15 original samples from 0–280 ms. This checks real exported signal availability; it does not validate the assumed enzyme or organ kinetics.

The final targeted frontend suite comprises **30 passing Node tests** (the original 25, four research/registration helpers, and NIfTI declared time-offset preservation). The protocol/session suite remains **17 passing Python tests**.

## Large-window service check

A real POST to `/api/analysis/interval` on port 8796 analyzed 9,000 synthetic samples with time origin 700 ms. The frontend server adapter reconstructed the equation `-52 + 3 cos(2π·0.33333333·(t − 0.7) + 0.3)`, with RMSE `4.89707785508039e-15` and R² 1. This checks the service path used above the 8,192-sample browser-worker limit.

## Deliberate boundaries

- EEG is an imported measured/supplied recording; MRI/fMRI panels render imported scalar NIfTI-1 volumes. No neural mean is relabeled as an instrument signal.
- NIfTI views use file-native voxel axes and the file's affine for coordinate reporting. Anchor overlays require an explicit finite nonsingular affine from model micrometers to voxel coordinates, matching model ID/hash, volume byte hash and dimensions; the viewer never infers registration from bounds.
- Browser-local imported files remain in memory. Named layouts persist panel arrangement and supported signal references; users reimport their files after reload.
- Independent body views show a neural overlay only for the existing approximate FlyWire alignment. Other model sources remain body anatomy only until a registered transform exists.
- Spike raster displays actual published spike events only, with a visible latest-15,000-event retention limit.

## Final integration acceptance (2026-10-01)

The final full Python suite passed **634 tests**, with **2 explicitly skipped**. All **58 JavaScript module tests** passed. Syntax checks and `git diff --check` passed.

The normal loopback service at `http://127.0.0.1:8794` was restarted after confirming no active job or morphology writer. An actual 175,401-neuron session paused at **140 ms**, stepped by exactly **1 ms**, and stopped with a committed partial recording. The partial output retained 3 voltage samples and its actual 41 ms stimulus duration. Two independent processes restored the same stopped checkpoint and finished as `20261001T081525Z_visual_dark_efe856` and `20261001T081548Z_visual_dark_cf8fa6`. Raw, baseline and difference voltage arrays matched **exactly** between siblings. Full HTTP evidence is saved in `build/session-http-final-verification.json`.

Disk recovery tests also covered ordinary preparation and every reference phase, including exact neural/chemical/organ-state verification during prefix reconstruction. API-created branch drafts round-trip through the execution normalizer, including electrode definitions. Focused regressions verify historical source identity, reordered region connectivity, partial spikes/clamps between voltage samples, and display truncation counts. Slow socket writes happen outside the engine-state lock.

These are numerical and software checks. The biological limitations and original failed stability evidence in this report remain applicable.

## Four-view overview and Parameters page

The default workspace now places Fly body and Brain above Simulation settings and Comparison. Detailed experiment controls follow in document flow, then Measurements and any added instruments. The layout editor retains Custom tiling alongside this overview mode. The old Default arrangement is backed up as Previous Default; named layouts, added-panel descriptors and saved chart references survive the one-time migration. Metadata-only chart references wait for their matching recording rather than silently binding to a different run. Existing panel elements/controllers are moved intact during retiling.

The integration owner inspected the rendered workspace at **1166 × 852**: all four main panel bounds lay between **y = 190 and y = 834**, without outer-panel overflow. Parameters replaced the workspace and Simulate toolbar; returning to Simulate retained the four views. The explicit hidden selector prevents the layout host's display rule from leaking the workspace onto Parameters. Detailed controls retain their original IDs and event bindings; compact settings mirror those controls.

`node --test tests/test_web_*.mjs`: **62 passed, 0 failed** after this update. Nine layout tests cover the original split operations plus primary/secondary grouping, migration backup, named-layout and chart-reference retention, migration idempotence, legacy defaults and recording-qualified restoration. The updated layout modules also passed ES-module syntax checks. This section supersedes the earlier five-panel default arrangement and earlier JavaScript test counts.

The final layout pass also tested the normal Parameters navigation and its Review in Simulate return action, quick pattern disabling of irrelevant motion controls, duration propagation, collapsed secondary-tool access, and full historical 138,639-neuron recording playback with two comparison charts. Numeric quick edits use the original input/change handlers; source bounds are refreshed after model configuration. Targeted server/analysis/API regressions: **44 passed**. Secondary tool groups are collapsed initially to keep all categories close to the overview.


## Native editing workspace, area notes, and session archives

This section supersedes the earlier four-pane visual arrangement. The installed macOS app now uses its native menu bar, a major brain viewport with an interactive fly inset, a resizable experiment inspector, two-column rectangular response charts, and a fixed full-height Notes rail. Parameters remains a separate page. Browser navigation remains available when opened outside the desktop app.

Native UI verification used the installed `/Applications/Cognesia.app` at a 1512 × 917 content viewport. The 138,639-neuron Grating recording and the 175,401-neuron combined context with eight recorded cells both rendered; missing activity remained visibly unavailable. The fly rendered in the brain corner. The final inspector width was 345px (two adjustments per row), with a 397px timeline area and side-by-side Motor/T4a voltage charts. Keyboard resizing persisted across reload. Command-2/Command-1 changed pages without starting the engine.

Command-N opened area selection; dragging created a normalized region with recording/model/time metadata. Original note text persisted, and Show linked area returned to the saved recording/time with a visible highlight. Command-S opened the native Save dialog and exported `build/desktop-notes-verification.cognesia-session.zip`: 21,909 bytes containing two notes and nine recording files (68,492 uncompressed recording bytes). Exact test-note text and every recorded-file SHA-256 were independently verified. The archive retains full notes plus an extractive, context-linked summary; it excludes global source datasets and live engine memory. The temporary test note was removed through the normal Undo-capable control after export.

Simulation → Stop All — Emergency remained enabled while ordinary idle-only controls were disabled. Invoking it while idle returned the visible confirmation “All simulation jobs stopped. Saved recordings are preserved.” Health still reported no running simulation. Active-worker stopping and native fallback are covered by existing engine/bridge checks; this particular UI test did not start a new full-network simulation.

Help → Rendering Diagnostics measured 121 animation frames and 85 timer callbacks over about 2.2 seconds in visible WKWebView. Both canvases reported successful draws, live WebGL contexts, and no captured shader/runtime errors. Native buffers preserve static frames and request redraw on visibility/focus restoration. The earlier transient blank state was not assigned an unsupported root cause.

Final automated verification: 115 web tests plus 7 native bridge/diagnostic tests; 80 targeted Python archive/server/assets/model-version/API/integration tests. Swift compilation used warnings-as-errors; the installed build passed strict code-signature verification. These results validate software behavior, not biological model accuracy or previously unresolved stability gates.


## Display modes, reachable controls, and optional Notes (2026-10-01)

A shared display policy now drives saved and live frames. Mode changes reset channel uniforms and redraw immediately; live frames respect Anatomy and Chemical selection. Missing channels stay gray with an unavailable label. Null-bootstrap anatomy, repeated Chemical → Anatomy switches, paused updates, mapped subsets, and malformed display frames have focused regressions. Changing the draft model clears the displaced recording's playback state and captions.

Fly surface, opacity, labels and provenance now live in Inspect → Fly controls. Chemical mode reveals Inspect → Chemical display. Toolbars wrap and inspectors scroll; the morphology toolbar no longer reserves an accidental vertical gap. Visible descriptions were shortened while retaining data/evidence distinctions.

Notes can be hidden with its close button, View → Hide Notes, or Command-Shift-N. Visibility persists independently of note content. Command-N reopens the rail before selecting an area. Native UI checks confirmed hide/show, menu state, reload persistence, preserved existing note content, working Fly opacity/labels, and Chemical → Anatomy redraw with unavailable chemical data. Notes-hidden layout frees the right-hand workspace; its restore button sits in the header, clear of plot controls.

`node --test tests/test_web_*.mjs macos/test_desktop_bridge.mjs`: **132 passed, 0 failed**. Module syntax and `git diff --check` passed. The native app was rebuilt and installed with warnings-as-errors and strict code-signature verification. These are software checks; no new biological validation is claimed.


## Experiment workflow and track timeline (2026-10-02)

Verified in the installed native Cognesia app and a separate local browser view. The native inspector shows Experiment, Sensory map, and Pre-simulation; BANC is selected, the real BANC result badge remains source-qualified, and the inspector footer keeps Run and Emergency stop ALL visible. Idle-only disabled transport buttons no longer reserve space. The default inspector is 320 px wide, with 52% of the right workspace assigned to the draggable timeline. Chemical controls use compact name/manual/value rows; qualifications remain available in expandable details.

The BANC eye endpoint returned 216 columns and 216 assigned photoreceptors, with 1,630 unassigned explicitly reported. Searching and selecting a modeled column retained its exact string root ID and assumed optical angles. Body & senses returned 704 source anatomical interfaces; antenna search resolved named nerves and sensory/motor counts. Source-qualified eye endpoints were checked against the engine mapping without advancing simulation or writing source assets.

Check model size resolved 175,401 neurons, 13,542,180 directed connections, and a 0.84 GB estimate for the inspected 600-ms configuration. A separate 60-ms verification request was paused during preequilibration, and the visible emergency control stopped it. Session `b3fb2392d3b248d389f405387e9edb79` ended `cancelled`, at 0 ms preequilibration, with no completed recording claimed. Existing results were preserved. This verifies command/progress plumbing, not simulation stability.

The existing FlyWire result `20261001T110601Z_visual_grating_082700` displayed 17 responsive regions. Double-clicking its 20–140 ms response clip replayed 0–160 ms including one recorded sample of context and stopped at 160 ms. The actual FlyWire source remained visible even with BANC selected for the next run. Native BANC result `20261002T084600Z_visual_grating_af7e8f` showed its R7/R8 cell-type response and aligned Motor/T4a curves; no absent regional averages were invented. Keyboard resizing changed the timeline height, and source-scoped curve restoration, bounded replay, stale preview races, and preparation-state isolation have focused regressions.

Targeted backend suite: 42 passed. Final web/native module totals are recorded in `build/workflow-ui-verification-20261002.json`. These are software checks; biological limitations in REPORT.md remain unchanged.
