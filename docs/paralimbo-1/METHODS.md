# Benchmark definitions and execution

All five endpoints measure error in **mV; lower is better**. Every model is compared with the same selected recorded trial for each condition. The zero-response reference predicts zero evoked voltage throughout.

| Endpoint | Definition | Contribution count | Numerical separation |
|---|---|---:|---:|
| Flash spatial peak RMSE | Root mean squared difference between predicted and observed signed peaks for positions −1, 0, +1 at 80 ms | 3 positions | 0.002 mV |
| Flash duration peak RMSE | Root mean squared peak error at the central position for 20, 80, 160 ms flashes | 3 durations | 0.002 mV |
| Motion waveform RMSE | Compute post-onset waveform RMSE within each motion condition, then average the four condition RMSEs with equal weights | 4 motion conditions | 0.002 mV |
| Direction contrast RMSE | Root mean squared error of positive-axis minus negative-axis peak contrasts, paired at each dwell duration | 2 direction pairs | 0.004 mV |
| Speed contrast RMSE | Root mean squared error of 20 ms-dwell minus 80 ms-dwell peak contrasts, paired within each direction | 2 speed pairs | 0.004 mV |

The measurement window begins at physical onset (0 ms) and ends at nominal stimulus duration +200 ms, inclusive. A peak is the maximum **signed** evoked voltage in that window. The motion score is an equal-condition mean of RMSEs, not pooled-sample RMSE. Contrast endpoints reuse the four motion conditions. The five measurements are related views of one recorded cell and dataset.

Candidate error must be more than the stated numerical separation below BANC to receive the lower-error verdict; exact equality to the threshold remains within separation in the frozen strict-inequality implementation. These rules are numerical thresholds, not confidence bounds or biological effect-size margins. No formally registered primary endpoint is claimed.

## Selection, pairing and historical exposure

The final frozen protocol selected nine conditions from input metadata and the minimum eligible matching trial for each condition. Each model used that trial's actual stimulus events. Three recording repeats were eligible per condition, but only one was scored. The exact IDs are in `protocol.json` and `results.json`.

Historical T4 outcomes were already exposed before this study. All new native predictions were sealed before the current scoring phase read the retained observations. The study is descriptive and retrospective. Earlier V1 failures and V2 pilots remain preserved locally; they are not counted as these 27 successful requests. The V3 schedule and subsequent resource-only amendment were frozen before current outcome access.

## Native execution and qualification

The study used three native models on the full 175,401-neuron graph. Each of the 27 requests included primary integration, timestep refinement, an optical-reference run, full-state disk serialize/restore/replay, input and observation checks, and whole-population diagnostics. The maximum audited timestep discrepancy was 0.000019250886211352736 mV, below the 0.001 mV qualification limit.

The resource-only annex changed retained/first-copy/temporary storage caps from 20/20/28 MB to 25/25/18 MB, retaining the same 68 MB total. It did not change scientific requests, numeric rules or model identities. Complete checkpoint files were temporary; retained selected-root traces and state digests do not enable offline full-state replay.

## Fixed assumed boundary

Input gain was +10 mV per contrast for Mi1, Tm3 and Mi4 and −10 for Mi9, with first-order time constants 40, 40, 100 and 100 ms respectively. Holding potential was normalized to 0 mV. The optical boundary used 5.7° FWHM and 2.25° per pixel with a pixel-integrated isotropic Gaussian, three-sigma cutoff and finite-arena normalization. These are source-informed modeling assumptions, not measured per-neuron BANC kernels or currents.

Recorded outputs were previously acquisition-filtered and baseline-subtracted. Predictions used centered FIR filtering at physical output times. The legacy acquisition-origin resampling and unavailable acquisition phase make the two observation operators approximate rather than identical.

## Reproduction boundaries

Run `python3 scripts/verify_paralimbo_1_publication.py` from the repository root to verify public evidence and recalculate endpoint arithmetic from published scored traces. The complete protocol, prediction seal and resource-annex manifest are byte-identical copies in `evidence/`.

These files disclose identities for the original study inputs and source code. Many manifest-relative paths refer to the original retained study and are intentionally not packaged here. Full native reproduction requires separately obtaining or rebuilding those pinned graphs and inputs under their source licenses; the public score check does not claim a full-graph rerun.
