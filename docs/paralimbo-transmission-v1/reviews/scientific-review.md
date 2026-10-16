# Independent scientific acceptance — transmission successor 0003

**PASS for faithful completion, sealed-score reproducibility, and retention of an inconclusive comparison. Biological superiority is not established.** This audit does not certify all requested trajectories numerically: engineering remains INCOMPLETE, and all five aggregate comparisons with BANC are INCOMPLETE. `COMPLETE` means that the finite schedule finished; `TERMINAL_VERIFIED` means integrity/scoring checks passed. Neither means ParaLimbo surpassed BANC.

The ledger contains 1105 complete and 4 failed jobs. Source identity: `d8e027ebb3b71bfb32fbaa43b958ae641a103010f06f90d8b7a37012274b0671`. No native simulation, search, replay, candidate change, frozen-file edit, or original-response-source access was performed for this review. Only retained exports and predictions were used for arithmetic. The accepted continuation preserved the finite clamp rejections as unknown, kept uncertain dimensions active for both arms, and supplied eight proposals per arm.

## Every registered endpoint

All entries are errors in mV; **lower is better**. T4c is the registered primary correspondence; T4d is a separate fixed sensitivity check. Flash endpoints describe calibration, not held-out evaluation. Every BANC endpoint in both mappings is unscored because at least one required condition failed final numerical qualification. No missing value is zero.

| Endpoint | Role | BANC T4c / T4d | ParaLimbo T4c | ParaLimbo T4d | T4d minus T4c |
|---|---|---|---:|---:|---:|
| flash_spatial_peak_rmse | CALIBRATION | INCOMPLETE / INCOMPLETE | 15.3357991145472 | 15.1751438372673 | -0.160655277280 |
| flash_duration_peak_rmse | CALIBRATION | INCOMPLETE / INCOMPLETE | 16.9335206289718 | 16.7378141296732 | -0.195706499299 |
| motion_waveform_rmse | EVALUATION | INCOMPLETE / INCOMPLETE | 2.93508844011837 | 2.89332915322706 | -0.041759286891 |
| direction_contrast_rmse | EVALUATION | INCOMPLETE / INCOMPLETE | 7.96211961277937 | 7.97363178667134 | +0.011512173892 |
| speed_contrast_rmse | EVALUATION | INCOMPLETE / INCOMPLETE | 0.788249056784567 | 0.762056371613487 | -0.026192685171 |

The T4d direction-contrast error increases by 0.011512173892 mV; its other four endpoint errors decrease. This regression must remain visible, and the alternate correspondence cannot replace the registered T4c result. The registered motion-waveform endpoint is the **mean of four condition RMSEs**, not the square root of a pooled MSE. The separate nine-condition balanced RMSE mixes calibration and evaluation: ParaLimbo 6.335071913492006 mV (T4c) and 6.258821183964998 mV (T4d); BANC remains incomplete. It is not a held-out headline metric.

## Every condition and subgroup

Each case is from T4-01. The table gives post-onset waveform RMSE in mV (lower is better). Both BANC mappings have identical scores for the five eligible cases and the same four ineligible cases. A positive BANC-minus-ParaLimbo difference favors ParaLimbo on that condition only.

| Case suffix | Condition | Role | BANC both mappings | ParaLimbo T4c | ParaLimbo T4d | BANC minus T4c |
|---|---|---|---:|---:|---:|---:|
| 2602ac761b2f5902 | motion sign -1, dwell 20 ms | EVALUATION | 4.171087400721 | 4.092524429499 | 4.046264913539 | +0.078562971222 |
| 4b1df4fe36ea6a3c | motion sign +1, dwell 80 ms | EVALUATION | INELIGIBLE | 1.649739522258 | 1.614924728977 | INCOMPLETE |
| 51fa5db4acd09248 | motion sign +1, dwell 20 ms | EVALUATION | 1.473308020726 | 1.454029614291 | 1.452398858519 | +0.019278406435 |
| 59209913440bed0c | flash position -1, 80 ms | CALIBRATION | 6.651091934770 | 6.564321865630 | 6.526104785201 | +0.086770069140 |
| 6c9ee7e0c8cd8003 | flash position +0, 20 ms | CALIBRATION | 1.944778650281 | 1.918005833194 | 1.890185656784 | +0.026772817087 |
| 6d76cbbe65f026d5 | flash position +1, 80 ms | CALIBRATION | 6.473789397032 | 6.408102514066 | 6.312939994299 | +0.065686882966 |
| a93bc8d103abecbd | motion sign -1, dwell 80 ms | EVALUATION | INELIGIBLE | 4.544060194425 | 4.459728111874 | INCOMPLETE |
| b93f1fb51e92ee02 | flash position +0, 80 ms | CALIBRATION | INELIGIBLE | 8.459868860033 | 8.358921828046 | INCOMPLETE |
| ce1c1a4de64ba9ec | flash position +0, 160 ms | CALIBRATION | INELIGIBLE | 12.631821586114 | 12.477542771926 | INCOMPLETE |

There are no ParaLimbo error regressions among the five conditions with valid paired scores, in either correspondence. There are **two** valid paired evaluation conditions and **three** valid paired calibration conditions; the other four paired results remain incomplete. Reporting these five gains as a whole-benchmark win would hide the failed comparison coverage. No animal-level subgroup or cross-animal generalization can be estimated from this single recorded cell.

Absolute response fit remains weak: primary ParaLimbo predicted peaks span 0.062043703502–0.253510440356 mV, whereas observed peaks span 3.755536405832–23.403533412714 mV. The exact per-condition peaks are retained in the verification receipt. Small improvements over the five eligible BANC traces do not establish an adequate biological response model.

## Why the BANC prediction rows are ineligible

All coarse, refined and optical native runs underlying these rows completed with finite full-population states and zero clamps. Their **0.1 versus 0.05 ms timestep** response differences exceeded the unchanged 0.001 mV criterion. Observation-filter differences remained below 0.001 mV and optical differences were zero. These are final prediction qualification failures, separate from the four failed sensitivity jobs in the ledger.

| Case suffix | Primary timestep maximum (mV) | T4d timestep maximum (mV) | Criterion |
|---|---:|---:|---:|
| 4b1df4fe36ea6a3c | 0.0115074724515054 | 0.0523556309147324 | ≤0.001 |
| a93bc8d103abecbd | 0.00836144472648215 | 0.0528714460965958 | ≤0.001 |
| b93f1fb51e92ee02 | 0.00527426396181596 | 0.0129113615102838 | ≤0.001 |
| ce1c1a4de64ba9ec | 0.0158511754332693 | 0.0217637146185297 | ≤0.001 |

All nine ParaLimbo cases passed the same final qualification in both mappings. The four BANC failures comprise both 80-ms-dwell motion directions and center flashes of 80 and 160 ms. Those missing cases cover every registered endpoint, so every aggregate BANC-minus-ParaLimbo comparison must stay null/INCOMPLETE. The retained coarse BANC predictions were not substituted into official scores, and no post-evaluation retuning or re-ranking was performed.

## Exact frozen selected parameters

Both arms received eight identical default-first Sobol opportunities over the same six active dimensions. All 16 coarse calibration candidates completed. The minimum balanced development-MSE winners were proposal index 4 for BANC and index 7 for ParaLimbo (indices start at zero). Both used the shared input multiplier **2.0**, selected from 1.0, 0.5 and 2.0 by equal-arm mean development error.

| Parameter | BANC index 4 | ParaLimbo index 7 |
|---|---:|---:|
| spike_weight | 0.446875 | 0.3953125 |
| tau_membrane | 17.5 | 28.75 |
| tau_synapse | 4.375 | 9.0625 |
| graded_gain | 9.749999999999998e-05 | 0.00019874999999999995 |
| graded_tau_membrane | 32.5 | 13.75 |
| graded_tau_synapse | 8.125 | 9.0625 |

Spike weight is mV/synapse; the four time constants are ms; graded gain retains its registered model units. The ParaLimbo graded cap remains 0.8. BANC graded-only parameters are proposal fields whose effective role depends on its pinned electrical modes. Exact binary-float JSON values are shown above.

Selected development MSE: BANC 62.68797855127387 mV²; ParaLimbo 63.7930286949791 mV². BANC's lower coarse training error does not rescue its later failed refinement. This is why selecting a different BANC candidate after seeing evaluation results is not an allowed repair.

ParaLimbo is retained as **EXPERIMENTAL**, model identity `a1dc383bf210ab73111bcf424ebcbbabc48405fd645da70e5dc9282ebcca4c5f`, based on `paralimbo-visual-graded-v1` / `229f9970e0b67cfa14658142dbc3adae8614d49887cd131521bf02e4d86cd884`. Its full selected parameter set and evidence are bound in `experimental-model.json`; existing defaults and published claims remain unchanged.

## Retained sensitivity failures and evidence limits

| Arm | Nondefault pooled 64-site sensitivity setting | Clamp events | First failure step |
|---|---|---:|---:|
| banc-888 | tau_membrane=10.0 ms | 38 | 962 |
| paralimbo-visual-graded-v1 | tau_membrane=10.0 ms | 38 | 962 |
| paralimbo-visual-graded-v1 | spike_weight=0.55 | 98 | 633 |
| banc-888 | spike_weight=0.55 | 98 | 633 |

Every sensitivity rejection retained finite endpoints, all 175,401 neurons and zero nonfinite/delayed-event fault counters. Spike weight and membrane time constant remained uncertain/active for both arms. These clamp counts are events, not distinct neurons, and are not biological inferiority scores. The inherited BANC 0.55 failure remains a failed imported case with its diagnostic replay provenance.

The descending-population benchmark remains **UNSUPPORTED_OBSERVATION_MAPPING**; its physiological responses were not used. The approved fallback is one previously exposed recorded T4 cell, one date group and one dataset, with one minimum-index eligible trial per condition. Five related endpoints are not five independent experiments. There is no repeat averaging, confidence interval, animal-level leave-one-out result, identified downstream recruitment measurement or independent biological replication.

Both the T4c/T4d correspondence and sensory boundary remain assumptions: cross-specimen mapping, hemisphere mirroring, relay kernels/gains, receptive-field geometry and optical support constrain interpretation. Recorded and predicted observation operators are approximate because acquisition phase is unavailable. The fixed boundary is not a fully optimized strong BANC baseline.

The primary selected parameters and prediction seal preceded evaluation response access. The fixed T4d sensitivity predictions were generated **after primary scoring**, then separately sealed before their own scoring; neither their mapping nor their parameters were chosen from those responses. This order must not be described as both sets being generated before any evaluation exposure.

The inherited native-contract sentence claiming every request underwent checkpoint restore and exact replay is broader than this campaign evidence: final T4 receipts contain `serialized_checkpoint_replay_exact: null`, and the T4 worker does not request per-case replay. Replay evidence is scoped to the actual verified pilot/checkpoint cases; this audit performed no neural replay. Frozen historical wording was preserved, with the limitation disclosed here.

## Independent verification

The frozen scorer recomputed both reports exactly. Separate arithmetic independently checked every eligible case, every endpoint, all final timestep/optical/observation qualification values, all paired condition deltas, and all 16 calibration objectives: **268 checks at absolute tolerance 1e-12**. An additional independent calculation reproduced every shared-input arm loss, equal-arm mean and the selected multiplier. Failed rows stayed excluded and incomplete endpoints stayed null. The tracked manifest, state, ledger, selections, model identity, score files, both seals, benchmark and scientific-plan seal were byte-identical before and after the check.

Bounded evidence: [scientific-verification.json](scientific-verification.json); SHA256 `ceae32a70c85289bb10f9a0e520498c053b2bd22c116a26bfcf4c0bb39bbc0f3`. Primary score identity `7d042ee4abdc2ef719e936b2fe2254560a8ff10c078393741ba6daef231569c4`; alternate score identity `248d0b5feae74603b4bf0a5ef026b789a4778f7fd477261b023eda3fba1df5a6`. Audit PASS concerns reproducibility and faithful outcome interpretation. The scientific result is a completed, **inconclusive comparative campaign**, not established superiority or downstream biological validation.


## Final report recheck

The final `RESULTS.md` endpoint tables, all nine condition rows, both mapping results, qualification differences, selected parameters, and inconclusive conclusion match this independent audit. Its requested single-trial/no-repeat-inference and assumed-correspondence/boundary disclosures are now present. The five qualified BANC traces were also checked directly: every retained sample is exactly zero in both mappings. No scientific corrections remain open. Audited final-report SHA256: `b2fe2037bf11def7468076f7c3a6e5f5c7f4cb7b9ded68b43ee47e93b139f3d3`. Final scientific acceptance: **PASS for the completed inconclusive outcome**, with the stated numerical and biological limitations.
