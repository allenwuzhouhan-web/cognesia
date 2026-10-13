# ParaLimbo 1 model card

## Identity and intended use

ParaLimbo 1 is the publication name for `paralimbo-visual-graded-v1`, a native Drosophila connectome simulation candidate. It is intended for exploratory scientific simulation and controlled comparisons within Cognesia. Biological validation remains **PENDING**. It is not an established predictor across cells, behaviors or datasets.

| Public label | Frozen model ID | Role in these benchmarks |
|---|---|---|
| ParaLimbo 1 | `paralimbo-visual-graded-v1` | Graded candidate |
| Original ParaLimbo 0.1 | `paralimbo-v0-1-0` | Original candidate comparator |
| BANC | `banc-888` | Fixed native BANC comparator |
| Zero-response reference | `zero-response` | Analytical reference; not a fourth native model |

Renaming is presentation-only. Model, graph, root-order and request identities remain frozen in the [evidence](evidence/audit-summary.json). The [runtime model package](../../models/paralimbo-1/) specifies the published entry point.

## What changes

The tested candidate retains the BANC graph topology and uses 175,401 neurons. Its graded population includes 26,597 neurons compared with 1,846 in the original configuration, reclassifying 24,751 neurons. An incoming-gain cap of 0.8 is applied jointly with the changed graded transmission. The comparison cannot attribute its effects to only one of those changes. The original ParaLimbo and BANC electrical implementations used here yield identical selected-T4 responses.

The scored candidate uses the reference graded membrane timescale (20 ms, scale 1.0). The optional half-timescale variant was not executed. Only the assumed T4c correspondence was executed; the alternate T4d correspondence was not.

## Evidence

The [five endpoint results](README.md#clear-comparative-results) come from a completed, sealed native retrospective study: 27 requests, one recorded cell, nine conditions and one selected paired trial per condition. ParaLimbo 1 clears numerical separation on four endpoints, with error reductions of 0.14–0.61%. Original ParaLimbo 0.1 exactly ties BANC on all five.

BANC and Original ParaLimbo 0.1 have exactly zero evoked selected-T4 predictions under this boundary. ParaLimbo 1 produces small responses: case peaks 0.007551–0.036074 mV compared with recorded case peaks 3.755536–23.403533 mV. The results do not establish accurate biological response reproduction. Every endpoint exceeds the frozen 0.05 mV reporting target.

## Assumptions and limitations

- Sensory gains, first-order kernels, receptive-field shape and holding potential are fixed assumptions shared across models. Neither comparator was fitted to these recordings.
- Anatomical correspondence between the recorded T4 cell and the chosen BANC T4c root is assumed. It is not independently measured registration.
- Previously exposed historical outcomes make this retrospective. Predictions were sealed before the present scoring phase; that does not create a previously unseen validation set.
- Five endpoints share one dataset and cell. They are not five independent biological replications.
- One matching recording trial per condition was selected by the frozen minimum-eligible-trial rule. There is no repeat averaging, SEM, confidence interval or statistical inference.
- The recorded and predicted observation operators are approximately aligned; unavailable acquisition phase prevents claiming identical filtering.
- The BANC comparator is fixed and uncalibrated. Sensory-gain uncertainty and alternate correspondence remain untested.
- Full-state checkpoints were created, restored and replayed during each request, then removed under the retention policy. Public summaries do not provide offline full-state campaign replay.

## Rights and citation

Cognesia code and original model contributions retain the repository's [license](../../LICENSE) and [third-party notices](../../THIRD_PARTY_NOTICES.md). Recorded data and adaptations retain [their separate CC BY-NC 4.0 terms](DATA_LICENSE.md). No endorsement by the experimental authors or data providers is implied.
