# ParaLimbo transmission v1 — completed experimental campaign

**Biological validation: PENDING. Engineering incomplete; predictive comparison inconclusive.**

The finite schedule completed on **15 October 2026, 17:13:18 CEST (Swiss time)**. No jobs remain. **Overall ParaLimbo versus BANC superiority is inconclusive.** All five registered endpoint comparisons are incomplete because the selected BANC candidate failed final timestep qualification in four conditions.

## Three separate outcomes

- **Engineering correctness: incomplete.** Frozen-file integrity and independent score recomputation passed. ParaLimbo qualified in all nine T4 conditions; BANC qualified in five. Four clamp-rejected sensitivity jobs and eight BANC correspondence-specific qualification failures remain visible. These are different failure inventories.
- **Predictive comparison: inconclusive.** ParaLimbo has lower waveform error in the five conditions where both arms are scoreable, including two motion conditions, but the full BANC endpoint scores are unavailable. No missing result is replaced with zero or hidden in an average.
- **Biological evidence: limited retrospective T4 fallback.** This is one recorded cell, five calibration flashes and four evaluation motions. Each condition uses one minimum-index eligible recording trial; there is no repeat averaging or confidence interval. T4c/T4d correspondence and the sensory input boundary are assumed and fixed. Population-imaging registration was unsupported. Downstream recruitment, animal-level generalization, full-brain transmission and biological superiority remain unestablished.

## All registered endpoints

Errors are in mV; lower is better. Motion waveform RMSE is the registered mean of four condition RMSEs, not a pooled-MSE square root. Calibration endpoints are not held-out evaluation. The alternate T4d correspondence is sensitivity evidence only and cannot replace the registered primary result.

| Endpoint | Phase | ParaLimbo primary | BANC primary | ParaLimbo alternate T4d | BANC alternate T4d |
|---|---|---:|---|---:|---|
| Flash spatial peak RMSE | Calibration | 15.335799115 | Incomplete | 15.175143837 | Incomplete |
| Flash duration peak RMSE | Calibration | 16.933520629 | Incomplete | 16.737814130 | Incomplete |
| Motion waveform RMSE | Evaluation | 2.935088440 | Incomplete | 2.893329153 | Incomplete |
| Direction contrast RMSE | Evaluation | 7.962119613 | Incomplete | 7.973631787 | Incomplete |
| Speed contrast RMSE | Evaluation | 0.788249057 | Incomplete | 0.762056372 | Incomplete |

The alternate mapping worsens ParaLimbo direction-contrast error by 0.011512174 mV. The other four endpoint errors are lower under that mapping; this does not select a preferred mapping.

## Every condition and comparison

Waveform RMSE in mV. Positive BANC minus ParaLimbo means lower ParaLimbo error. Full case IDs preserve exact condition identity.

| Case ID | Phase | BANC RMSE (both mappings) | ParaLimbo primary | BANC minus primary | ParaLimbo alternate | BANC minus alternate |
|---|---|---:|---:|---:|---:|---:|
| T4-01-2602ac761b2f5902 | Evaluation | 4.171087401 | 4.092524429 | 0.078562971 | 4.046264914 | 0.124822487 |
| T4-01-4b1df4fe36ea6a3c | Evaluation | Unqualified | 1.649739522 | Unqualified | 1.614924729 | Unqualified |
| T4-01-51fa5db4acd09248 | Evaluation | 1.473308021 | 1.454029614 | 0.019278406 | 1.452398859 | 0.020909162 |
| T4-01-59209913440bed0c | Calibration | 6.651091935 | 6.564321866 | 0.086770069 | 6.526104785 | 0.124987150 |
| T4-01-6c9ee7e0c8cd8003 | Calibration | 1.944778650 | 1.918005833 | 0.026772817 | 1.890185657 | 0.054592993 |
| T4-01-6d76cbbe65f026d5 | Calibration | 6.473789397 | 6.408102514 | 0.065686883 | 6.312939994 | 0.160849403 |
| T4-01-a93bc8d103abecbd | Evaluation | Unqualified | 4.544060194 | Unqualified | 4.459728112 | Unqualified |
| T4-01-b93f1fb51e92ee02 | Calibration | Unqualified | 8.459868860 | Unqualified | 8.358921828 | Unqualified |
| T4-01-ce1c1a4de64ba9ec | Calibration | Unqualified | 12.631821586 | Unqualified | 12.477542772 | Unqualified |

No scoreable paired condition regressed against BANC. This is a selected subset of five of nine conditions and does not establish a complete advantage. Across the primary mapping, ParaLimbo predicted peaks are only 0.062–0.254 mV versus measured peaks of 3.756–23.404 mV. The response magnitude and direction-contrast fit remain poor despite its small paired waveform improvements. BANC predicts zero response in the five scoreable conditions.

## Numerical qualification failures

All listed native trajectories finished with finite states and zero clamps. Their timestep refinement exceeded the frozen **0.001 mV** maximum difference, so they were excluded from scoring. They were not retried or replaced after outcome access.

| BANC case ID | Phase | Primary timestep difference (mV) | Alternate T4d difference (mV) |
|---|---|---:|---:|
| T4-01-4b1df4fe36ea6a3c | Evaluation | 0.011507472452 | 0.052355630915 |
| T4-01-a93bc8d103abecbd | Evaluation | 0.008361444726 | 0.052871446097 |
| T4-01-b93f1fb51e92ee02 | Calibration | 0.005274263962 | 0.012911361510 |
| T4-01-ce1c1a4de64ba9ec | Calibration | 0.015851175433 | 0.021763714619 |

Four separate pooled +10 mV sensitivity probes were rejected for clamps: both arms at spike weight 0.55 produced 98 clamp events, and both arms at membrane time constant 10 ms produced 38. All had finite endpoints and zero nonfinite/invalid-delay counters. Their effects remain unknown and the affected parameters stay active. The single authorized predecessor replay confirmed the original 98-event rejection and was not rerun. Clamp events are not counts of distinct neurons.

## Exact selected experimental candidate

Experimental model identity: `a1dc383bf210ab73111bcf424ebcbbabc48405fd645da70e5dc9282ebcca4c5f`. Shared development-selected input multiplier: **2**. Both arms received eight default-first proposals. BANC selected proposal index 4; ParaLimbo selected index 7 (zero-based). All six parameters remained active. ParaLimbo graded gain cap stays **0.8**.

| Parameter | ParaLimbo | BANC |
|---|---:|---:|
| spike_weight | 0.3953125 | 0.446875 |
| tau_membrane | 28.75 | 17.5 |
| tau_synapse | 9.0625 | 4.375 |
| graded_gain | 0.00019874999999999995 | 9.749999999999998e-05 |
| graded_tau_membrane | 13.75 | 32.5 |
| graded_tau_synapse | 9.0625 | 8.125 |

Spike weight is in mV per synapse; time constants are in ms. Graded gain uses the frozen model convention. Exact floating-point parameter values are retained above.

Original model identities, existing defaults and published claims remain unchanged. The registered candidate is EXPERIMENTAL. BANC selection passed the calibration-run checks but failed final refinement in four conditions; no alternate candidate was substituted.

## Transmission diagnosis and limits

The deterministic inventory probes 64 sites and covers 63 of 235 anatomical/mode/side strata; all **175,401** neurons remain in every native experiment. Matched controls and three pulses per site were completed. For each arm, silencing and rescue support source contribution to a selected directly connected target at 59 sites; five sites remain unestablished. This is not proof that a signal propagates to every neuron. Longer-path counterfactuals and responses beyond the 900 ms observation window remain untested. No equations or cell-mode assignments were changed automatically.

## Execution, verification and evidence limits

The active ledger retains **1,105 completed jobs and four failed sensitivity jobs**, including 829 completed predecessor jobs imported through the reviewed source-only bridge. No native worker remains, and all heavy-compute locks are free. The recorded worker used 16 threads and a 24 GB cap; reported peak RSS was 5.387 decimal GB. Combined campaign storage at terminal inspection was 11.683 GB before approximately 4.2 MB of final-review copies, within the 20 GB cap. The original deadline remains 20 October 2026, 15:23:07 CEST.

- Frozen source, inputs and dependencies passed byte verification. Both correspondence score packages passed independent recomputation from sealed predictions. Such verification validates the retained result, including incompleteness; it does not make failed cases pass.
- No fresh final paired cold-start/cache-equivalence or hard-crash recovery run is evidenced in the final bundle. Exact checkpoint replay evidence covers four direct pilots; all 108 final T4 native receipts have replay=null.
- T4 serialized-checkpoint exact-replay fields are null: do not claim exact per-T4-request checkpoint replay from those receipts. Existing direct/fixture checks have narrower scope.
- Alternate T4d predictions were generated after primary outcomes had been loaded. The alternate mapping and selected candidate were fixed, and the alternate predictions were sealed before their own scoring; do not describe this as both prediction sets being sealed before any evaluation access.
- Two inherited metadata statements are inaccurate without these disclosures: benchmark metadata claims exact checkpoint replay for every request, and the alternate prediction seal reports evaluation_outcomes_read=false despite the primary outcomes already having been loaded. The historical artifacts are preserved; the actual evidence and chronology above govern interpretation.
- The predecessor diagnostic replay retained only eight denied I/O entries. They were verified absent dependency bytecode lookups; the denial inventory is incomplete and the Python audit boundary is not an OS sandbox.
- A durable sensitivity-review copy lacked its final supervision paragraph. Final review recovered and hash-verified the exact originally pinned document; both versions and a reconciliation receipt are preserved. This was a documentation-copy discrepancy, with no scientific change.
- Original attempts, the diagnostic replay and failed cases remain preserved. The numerical guard, search bounds and fixed schedule were not relaxed after seeing outcomes.

## Evidence and independent review

- [Frozen campaign report](evidence/report.json)
- [Primary sealed scores](evidence/scores.json)
- [Alternate T4d sealed scores](evidence/scores-t4d.json)
- [Verification receipt](evidence/verification.json)
- [Experimental model and exact evidence](evidence/experimental-model.json)
- [Transmission diagnosis](evidence/transmission-diagnosis.json)
- [Site coverage and omissions](evidence/site-inventory.json)
- [Independent scientific review](reviews/scientific-review.md)
- [Independent engineering review](reviews/engineering-review.md)

Final independent scientific and engineering reviews **PASS for honest completion and reporting of this inconclusive result**. Independent arithmetic reproduced all 268 checks within 1e-12 and all 16 candidate development objectives. The engineering review closes all reported findings while retaining the numerical and evidence limitations above. This acceptance does not change engineering status to complete or establish biological superiority.

## Public package scope

This is a publication derivative of the completed local campaign. See [provenance](public-provenance.json), [reproduction instructions](REPRODUCING.md) and [attribution](ATTRIBUTION.md). The offline verifier recomputes arithmetic from retained traces; it does not rerun the 175,401-neuron simulation or certify omitted hidden states. Original prediction seals and score files remain byte-identical. Host-path-normalized documents retain historical identifiers solely as provenance and are not represented as the original sealed bytes.
