# Cognesia implementation and measured results

These are the measured results of the smaller neuromodulation core. The default [Open Cognesia.command](Open%20Cognesia.command) launcher now opens the [unified whole-brain viewer](http://127.0.0.1:8794), idle, with [integrated chemistry and state controls](docs/wholebrain_chemistry.md). To run the earlier diagnostic core explicitly, use `.venv/bin/flybrain rt serve --core` and open its console at port 8795. Its measured results below do not validate the full-brain coupling.

The console runs the 13,300-neuron core with 927,567 effective released edges, measured odour inputs, eight modulator fields across 96 compartments, receptor effects, normalized plasticity, endocrine state and inferred MBON valence. Timeline, atlas, learning and divergence views expose the same recorded engine state. Manual controls and YAML protocols use model time; saved ZIP sessions replay deterministically. Held-out test blocks freeze memory. CSV and PNG exports save locally with persistent links.

## Verification

| Check | Observed result |
|---|---|
| Complete Python suite | 487 passed in 42.23 s |
| Normalized plasticity reference | All 12 points pass; maximum residual 4.915e-7 |
| Deterministic runtime replay | Full 60 s replay matches every spike and final internal state |
| Actual training protocol | Completed; held-out weights unchanged |
| Exported interactive session replay | 18.36 s saved GUI session replays exactly |
| Browser workflow | Live controls, pause/step, raster, atlas, raw weights, exports and ZIP playback exercised |
| Full capacity execution | 92 supported handles; 736 held-out observations; measurement checks pass |
| Separate whole-brain variant | Current and conductance resting-stability gates pass |

The complete suite preceded the final export/playback presentation fixes; their focused browser and Node checks also passed. See [the complete report](REPORT.md), [runtime methodology](docs/runtime_measurements.md), [console documentation](docs/live_console.md), and [variant assumptions](docs/hybrid_stability_variant.md).

## Scientific and performance findings

The implementation runs, but several requested acceptance gates fail on the measured model. They remain visible in the console and report.

- Measured speed is **0.635129× real time**, below the 1.2× target: 60 model seconds took 94.469 wall seconds. Sampled maximum RSS was 1.001 GB; all 3,000 frame advances exceeded the 20 ms budget.
- Current core runs exceed the configured voltage bounds without clamping. The historical odour-sparseness diagnostic measured about 68% KC activity, above the requested 2–12% range; that older gate is now marked stale because its inputs changed.
- Network pairing depresses weights at all 12 tested delays; the expected reversal is absent. Spatial specificity passes (ratio 25.739), while training direction, state-dependent decision change and extinction gates fail.
- Fed and starved inferred scores are 11.8549 and 11.0417. Both decode as approach, so the numerical difference does not pass the decision-change gate.
- All **92 handles** have measured task mutual information **0 bits**, 95% protocol-bootstrap intervals [0, 0], and p=q=1. The 96-type inventory also preserves four unsupported/mixed-annotation exclusions. Two trained assignments and two held-out seeds do not establish saturation or general biological capacity. Physical driver accessibility and interface bandwidth remain unknown.
- The separate normalized whole-brain variant passes resting stability under explicitly changed assumptions. The original base model's failed stability evidence is preserved. Visual biology, whole-brain neuromodulation and body decoding remain unvalidated.

No coefficients were fitted to turn these biological failures into passes.

## Measured figures and evidence

![Normalized plasticity reference](build/neuromod_figures/plasticity_reference.png)

![Actual network pairing](build/neuromod_figures/network_pairing.png)

![Separate whole-brain variant stability](build/neuromod_figures/wholebrain_stability.png)

![Measured task information curve](build/neuromod_figures/capacity_curve.png)

![All measured source handles](build/neuromod_figures/capacity_per_handle.png)

Raw results: [capacity evidence](build/validation_neuromod_capacity.json), [source inventory](build/neuromod_write_handles.csv), [held-out observations](build/neuromod_capacity_trials.csv), [capacity curve](build/neuromod_capacity_curve.csv), [test log](build/neuromod_final_tests.log), [interactive replay](build/neuromod_console_replay.log). Generated evidence and sessions remain in the local ignored `build/` and `runs/` directories; the versioned source, configurations, protocols and report reproduce and describe them.
