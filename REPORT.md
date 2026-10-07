# Flybrain execution report

## Integrated experiment workspace (2026-10-01)

Final integration checks: **634 Python tests passed, 2 skipped; 58 JavaScript tests passed**. Real API pause/step/stop/partial recovery and two identical restored sibling runs passed. [Acceptance evidence](docs/workspace-ui-verification.md#final-integration-acceptance-2026-10-01).

The versioned model and experiment workspace is implemented locally: selective neural computation with recorded surroundings, live sessions and disk journals, complete main-engine checkpoints and branches, timeline interventions, enzymes and peripheral dynamics, graph-interval formulas, configurable panels, and imported instruments. [User guide](docs/experiment-workspace.md) · [Source audit](docs/model-sources.md) · [Scientific limits](docs/experiment-workspace-science.md) · [Browser verification](docs/workspace-ui-verification.md).

A 300 ms combined-model test compared full 175,401-neuron integration against an eight-neuron selected replay. Recorded raw/baseline/difference voltage, chemical fields, enzyme pools and organ states matched exactly. `build/runtime_paired_benchmark.json` retains exact run IDs, options, timing and numerical comparisons. This is a short numerical replay check, not new biological or long-term stability validation.

Original field, receptor, plasticity and odour prerequisites were rerun successfully. The core stationarity gate currently fails closed because its historical `build/validation_hybrid.json` prerequisite is unavailable. A 43 ms original-core protocol transport check completed but recorded 1,045 voltage-bound violations; this is explicitly not a stable biological result. Existing historical evidence below remains unchanged.

## Current neuromodulation implementation

The corrected normalized plasticity, coupled 13,300-neuron core, endocrine state, protocol runner, session recording/replay and browser console are implemented. The default `./Open\ Cognesia.command` launcher opens the unified whole-brain viewer, idle, at http://127.0.0.1:8794. Use `.venv/bin/flybrain rt serve --core` explicitly for the smaller diagnostic console at http://127.0.0.1:8795. [Whole-brain chemical integration](docs/wholebrain_chemistry.md) is an experimental extension; the core checks below do not validate that coupling.

The 60-second exact-replay gate is **PASS**. Measured throughput is **0.635× real time**; the performance gate is **FAIL** against the 1.2× target. No integration steps are skipped to improve the displayed speed.

The driven core's voltage bounds and biological validation remain failures where measured. The separate normalized whole-brain variant has its own resting-stability evidence below; it does not replace the original base model or validate visual/motor behaviour.

[Console and controls](docs/live_console.md) · [Measurement methods](docs/runtime_measurements.md) · [Evidence figures](build/neuromod_figures/index.json)

## Experimental visual simulator

The subsequent request to build a visual simulator is implemented as a separate exploratory continuation. The unchanged neural core runs actual eye-driven input and a matched constant-luminance control, then displays recorded raw, baseline and difference voltages. The original failed gate remains unchanged; these recordings do not complete the biological validation battery.

10 saved visual recordings are available through `flybrain view --open`. See [VISUAL_SIMULATOR.md](VISUAL_SIMULATOR.md) for launch instructions, assumptions, provenance, and measurement definitions.

This report records executed checks. NOT-RUN is not a pass. A historical PASS with changed or unverified inputs is shown as NOT-RUN until validation is repeated.

| Gate | Check | Status |
|---|---|---|
| V-A | Data integrity | PASS |
| V-B | Photoreceptor sign response | NOT-RUN |
| V-C | Numerics and equilibration | NOT-RUN |
| V-D | Five-second dark control | NOT-RUN |
| V-E | Brian2 reference cross-check | PASS |
| V-F | ON/OFF split | NOT-RUN |
| V-G | Direction selectivity | NOT-RUN |
| V-H | Wide-field responses | NOT-RUN |
| V-I | Looming selectivity | NOT-RUN |

## Recorded runs

These are recorded experiments, not substitutes for the validation gates.

| Experiment | Spikes | Clamps | Wall seconds | Peak RSS GB | Evidence |
|---|---:|---:|---:|---:|---|
| hybrid_preequilibration | 7846 | 39945 | 11.910 | 0.765 | [20260925T163917Z_hybrid_preequilibration_7e571c](runs/20260925T163917Z_hybrid_preequilibration_7e571c/run_manifest.json) |
| hybrid_preequilibration | 7846 | 39945 | 12.022 | 0.763 | [20260925T164238Z_hybrid_preequilibration_0d98f1](runs/20260925T164238Z_hybrid_preequilibration_0d98f1/run_manifest.json) |
| visual grating | 4769 | 23537 | 43.148 | not recorded | [20260926T004905Z_visual_grating_d50a3c](runs/20260926T004905Z_visual_grating_d50a3c/run_manifest.json) |
| visual dark | 2520 | 11827 | 19.524 | not recorded | [20260926T005050Z_visual_dark_f2f023](runs/20260926T005050Z_visual_dark_f2f023/run_manifest.json) |
| visual apparent_motion | 2345 | 11762 | 24.268 | 1.380 | [20260926T005716Z_visual_apparent_motion_3474b8](runs/20260926T005716Z_visual_apparent_motion_3474b8/run_manifest.json) |
| visual grating | 4386 | 22263 | 37.296 | 1.979 | [20260926T010330Z_visual_grating_f58f81](runs/20260926T010330Z_visual_grating_f58f81/run_manifest.json) |
| visual apparent_motion | 2345 | 11762 | 28.807 | 2.076 | [20260926T010417Z_visual_apparent_motion_d3db12](runs/20260926T010417Z_visual_apparent_motion_d3db12/run_manifest.json) |
| visual grating | 4769 | 23537 | 37.380 | 2.126 | [20260926T010808Z_visual_grating_098ed2](runs/20260926T010808Z_visual_grating_098ed2/run_manifest.json) |
| visual grating | 22248 | 244798 | 298.864 | 2.614 | [20260926T012715Z_visual_grating_748575](runs/20260926T012715Z_visual_grating_748575/run_manifest.json) |
| visual looming | 74923 | 1497510 | 1732.923 | 4.423 | [20260926T021246Z_visual_looming_15c528](runs/20260926T021246Z_visual_looming_15c528/run_manifest.json) |
| visual flash | 7760 | 40141 | 55.527 | 2.474 | [20260927T022225Z_visual_flash_04b5c6](runs/20260927T022225Z_visual_flash_04b5c6/run_manifest.json) |
| visual flash | 7760 | 40141 | 55.756 | 2.921 | [20260927T022323Z_visual_flash_f687f1](runs/20260927T022323Z_visual_flash_f687f1/run_manifest.json) |

## Reference comparison

![Mean firing rates against Brian2](build/figures/reference_comparison.png)

Firing-rate agreement passed (r = 0.9999959), with **276,226 voltage-clamp events**. This is not a zero-clamp or biological-validation pass; it checks the specified firing-rate statistic under the explicit Poisson comparison protocol.

## V-A: Data integrity

[Complete measurements and provenance](build/validation_data.json)

```json
{
  "gate": "V-A",
  "status": "PASS",
  "checks": {
    "total_items": 60,
    "first_12": [
      {
        "name": "source_manifest_sha256_Completeness_783.csv",
        "status": "PASS",
        "observed": "bbb847a4cc2caaa7a16349722d220c087317b946d148d4d592d94d250617a311",
        "expected": "bbb847a4cc2caaa7a16349722d220c087317b946d148d4d592d94d250617a311"
      },
      {
        "name": "source_manifest_sha256_Connectivity_783.parquet",
        "status": "PASS",
        "observed": "efeb23fb99098e9c390f6869969b2a121a2ee92c833cfc45ecb2c1d8e1af0347",
        "expected": "efeb23fb99098e9c390f6869969b2a121a2ee92c833cfc45ecb2c1d8e1af0347"
      },
      {
        "name": "source_manifest_sha256_Supplemental_file1_neuron_annotations.tsv",
        "status": "PASS",
        "observed": "9a4f8b2f843196074431ebd7cd883536afa1be86c8a4ce90970441e8be81d1be",
        "expected": "9a4f8b2f843196074431ebd7cd883536afa1be86c8a4ce90970441e8be81d1be"
      },
      {
        "name": "completeness_rows",
        "status": "PASS",
        "observed": 138639,
        "expected": 138639
      },
      {
        "name": "completeness_columns",
        "status": "PASS",
        "observed": [
          "Unnamed: 0",
          "Completed"
        ],
        "expected": [
          "Unnamed: 0",
          "Completed"
        ]
      },
      {
        "name": "annotations_rows",
        "status": "PASS",
        "observed": 139248,
        "expected": 139248
      },
      {
        "name": "annotations_column_count",
        "status": "PASS",
        "observed": 31,
        "expected": 31
      },
      {
        "name": "annotations_required_columns",
        "status": "PASS",
        "observed": [],
        "expected": []
      },
      {
        "name": "connectivity_rows",
        "status": "PASS",
        "observed": 15091983,
        "expected": 15091983
      },
      {
        "name": "connectivity_data_columns",
        "status": "PASS",
        "observed": [
          "Presynaptic_ID",
          "Postsynaptic_ID",
          "Presynaptic_Index",
          "Postsynaptic_Index",
          "Connectivity",
          "Excitatory",
          "Excitatory x Connectivity"
        ],
        "expected": [
          "Presynaptic_ID",
          "Postsynaptic_ID",
          "Presynaptic_Index",
          "Postsynaptic_Index",
          "Connectivity",
          "Excitatory",
          "Excitatory x Connectivity"
        ]
      },
      {
        "name": "connectivity_column_dtypes",
        "status": "PASS",
        "observed": {
          "Presynaptic_ID": "int64",
          "Postsynaptic_ID": "int64",
          "Presynaptic_Index": "int64",
          "Postsynaptic_Index": "int64",
          "Connectivity": "int64",
          "Excitatory": "int64",
          "Excitatory x Connectivity": "int64"
        },
        "expected": {
          "Presynaptic_ID": "int64",
          "Postsynaptic_ID": "int64",
          "Presynaptic_Index": "int64",
          "Postsynaptic_Index": "int64",
          "Connectivity": "int64",
          "Excitatory": "int64",
          "Excitatory x Connectivity": "int64"
        }
      },
      {
        "name": "completeness_root_dtype",
        "status": "PASS",
        "observed": "int64",
        "expected": "int64"
      }
    ],
    "note": "Full list in the linked JSON evidence."
  },
  "created_at": "2026-09-27T02:21:47.086329+00:00",
  "source": "BUILD_BRIEF.md sections 2.1, 2.2, 3.1, and 6",
  "notes": [
    "The Parquet pandas index is physical storage metadata, not an eighth data column.",
    "HS / VS row is interpreted as HS = 3 left + 3 right and VS = 16 left + 16 right. Its two table cells describe families rather than the stated left/right headers. VS family includes VS1-8, VST1, VST2 and VSm; member counts are reported below."
  ],
  "parquet_stored_index_columns": [
    "__index_level_0__"
  ],
  "widefield_family_members": {
    "total_items": 28,
    "first_12": [
      {
        "cell_type": "HSE",
        "side": "left",
        "count": 1
      },
      {
        "cell_type": "HSE",
        "side": "right",
        "count": 1
      },
      {
        "cell_type": "HSN",
        "side": "left",
        "count": 1
      },
      {
        "cell_type": "HSN",
        "side": "right",
        "count": 1
      },
      {
        "cell_type": "HSS",
        "side": "left",
        "count": 1
      },
      {
        "cell_type": "HSS",
        "side": "right",
        "count": 1
      },
      {
        "cell_type": "VS1",
        "side": "left",
        "count": 1
      },
      {
        "cell_type": "VS1",
        "side": "right",
        "count": 1
      },
      {
        "cell_type": "VS2",
        "side": "left",
        "count": 1
      },
      {
        "cell_type": "VS2",
        "side": "right",
        "count": 1
      },
      {
        "cell_type": "VS3",
        "side": "left",
        "count": 1
      },
      {
        "cell_type": "VS3",
        "side": "right",
        "count": 1
      }
    ],
    "note": "Full list in the linked JSON evidence."
  },
  "edge_measurements": {
    "rows": 15091983,
    "null_count": 0,
    "synapse_sum": 54492922,
    "synapse_min": 1,
    "positive_edges": 9059302,
    "negative_edges": 6032681,
    "invalid_signs": 0,
    "signed_product_mismatches": 0,
    "Presynaptic_index_min": 0,
    "Presynaptic_index_max": 138638,
    "Presynaptic_out_of_bounds": 0,
    "Presynaptic_root_mismatches": 0,
    "Postsynaptic_index_min": 0,
    "Postsynaptic_index_max": 138638,
    "Postsynaptic_out_of_bounds": 0,
    "Postsynaptic_root_mismatches": 0
  },
  "failed_checks": []
}
```

## V-E: Brian2 reference cross-check

[Complete measurements and provenance](build/validation_engine.json)

```json
{
  "gate": "V-E",
  "status": "PASS",
  "checks": [
    {
      "name": "mean_firing_rate_correlation",
      "status": "PASS",
      "observed": 0.9999959214190753,
      "expected": ">=0.95"
    },
    {
      "name": "deterministic_spike_trains",
      "status": "PASS",
      "observed": "e4fb0a6ff7eb17767baeb1cea9fb2f79a23f6632b98116ce1498bdb31dc2cff4",
      "expected": "e4fb0a6ff7eb17767baeb1cea9fb2f79a23f6632b98116ce1498bdb31dc2cff4"
    }
  ],
  "warnings": [
    "Production voltage limits clamped 276226 events during V-E."
  ],
  "created_at": "2026-09-25T16:33:47.559497+00:00",
  "protocol": {
    "trials": 10,
    "duration_ms": 1000,
    "n_driven": 20,
    "threads": 16,
    "custom_integrator": "exponential_euler",
    "reference_integrator": "linear (released create_model)",
    "full_protocol": true,
    "primary_metric": "Pearson r of mean per-neuron firing rate over trials, union of firing neurons",
    "threshold": 0.95,
    "dt_ms": 0.1,
    "input_rate_hz": 150.0,
    "input_voltage_increment_mV": 68.75,
    "driven_refractory_ms": 0,
    "reference_signs": "unmodified classifier signs"
  },
  "trial_results": [
    {
      "trial": 0,
      "input_events": 3075,
      "custom_spikes": 3611,
      "reference_spikes": 3596,
      "custom_clamp_count": 25828,
      "custom_wall_seconds": 3.440431874994829,
      "reference_wall_seconds": 3.322973333997652,
      "custom_spike_hash": "e4fb0a6ff7eb17767baeb1cea9fb2f79a23f6632b98116ce1498bdb31dc2cff4",
      "reference_spike_hash": "1efa12bfa2a37d958244d91bcf9b75145f3c2102bd0279aab7670e0e025a11d1",
      "custom_file_sha256": "0ea40ed229ee1de965c467d6dc1490dc0073d93bbedb05fee9c8de3566f43f4a",
      "reference_file_sha256": "87e8153c3611c5098cdf87c9ecdcf6cb493929c147f44c538bbf94234ca31731",
      "peak_process_rss_bytes": 3618586624
    },
    {
      "trial": 1,
      "input_events": 2948,
      "custom_spikes": 3457,
      "reference_spikes": 3455,
      "custom_clamp_count": 25651,
      "custom_wall_seconds": 3.3703160830045817,
      "reference_wall_seconds": 3.302557375005563,
      "custom_spike_hash": "bd8065af320c1f25133fedaf1bc74c82dd2f420bde4ee446a7bede16a32bb0e9",
      "reference_spike_hash": "1fa92e3ba5868396e7e5457b1949ef26299fcb02702bbd1d16b3b008283c3536",
      "custom_file_sha256": "c05fccdfd84262b559afeca01038ecfc5a86f8e94a3168c758f4cef5449c5d00",
      "reference_file_sha256": "99592ad83a72f1b7e37a258d5560a8a927eab5199263686d3b595e10f34a5e1b",
      "peak_process_rss_bytes": 3618586624
    },
    {
      "trial": 2,
      "input_events": 2954,
      "custom_spikes": 3413,
      "reference_spikes": 3398,
      "custom_clamp_count": 27317,
      "custom_wall_seconds": 3.350842708001437,
      "reference_wall_seconds": 3.294047542003682,
      "custom_spike_hash": "a3c39a52de404d952a803328b3de87584b68a2cbb62f1595c24d7bdb380007cd",
      "reference_spike_hash": "fa29f973e2825ea3e4171bdac0223c3488de14773a05864f5e0612b6e19b1f89",
      "custom_file_sha256": "86f694bd2615ca6e22289f9d2e349f82684087cb54cdb046c3bf231cc53da433",
      "reference_file_sha256": "9dd858de38cc3d71be792a94ee1f56c040a07b1b37998064201e4506adc2a509",
      "peak_process_rss_bytes": 3618586624
    },
    {
      "trial": 3,
      "input_events": 3016,
      "custom_spikes": 3472,
      "reference_spikes": 3450,
      "custom_clamp_count": 28111,
      "custom_wall_seconds": 3.358455082998262,
      "reference_wall_seconds": 3.294861333000881,
      "custom_spike_hash": "970715cf875ec291c543fc3270871f7acd081ba9e3df0df73a685da7f6912025",
      "reference_spike_hash": "74dde216c76aa59a4b0b0398116bfbca4d24419851def760bd045b571fdeb3e5",
      "custom_file_sha256": "f62dad3383b2cea839198ff4dfe13e664b39dccb63053beacbd62a5bb17b4d04",
      "reference_file_sha256": "1f1b82c1ce0c93084612cc11ab43a81b3900167f629c1e80d7a5602528e4d107",
      "peak_process_rss_bytes": 3618586624
    },
    {
      "trial": 4,
      "input_events": 3056,
      "custom_spikes": 3657,
      "reference_spikes": 3647,
      "custom_clamp_count": 28449,
      "custom_wall_seconds": 3.360123708000174,
      "reference_wall_seconds": 3.290606166003272,
      "custom_spike_hash": "cbe438b3a3a3bd0fafd2a6b1ddbfcf2964562f15003c6a34556dfb1124c1932c",
      "reference_spike_hash": "6fa456c0b53109cb57640414b248d3e1dcf4f9d3a53162a833511939153e036a",
      "custom_file_sha256": "887eb7cfc4f3c5befa44065abb08a4d816820e17234a7e35c305183caa5d6cec",
      "reference_file_sha256": "5ab7d54368f2becbb50213e6c87b9e8bb0d38b94968d49d15d4008f4a85b4a94",
      "peak_process_rss_bytes": 3618586624
    },
    {
      "trial": 5,
      "input_events": 3029,
      "custom_spikes": 3498,
      "reference_spikes": 3479,
      "custom_clamp_count": 28568,
      "custom_wall_seconds": 3.3688620419998188,
      "reference_wall_seconds": 3.3139106669987086,
      "custom_spike_hash": "28861167dd6e24a688febfa576ff3ce21205ab482656b312c8bc32ecd283a080",
      "reference_spike_hash": "01ba5b72cdfdde581c216cfb01fb6db3a2c3b66ca46221fb4bcaea3bbef208f9",
      "custom_file_sha256": "dfbf94029bc3a5449cdd5ebb1bd94ad7cc25cb5f18656a567c6a0f78917eab83",
      "reference_file_sha256": "697f297842415009b677b1af468dc0a02908228320243a3aea3f2f8c85eb013f",
      "peak_process_rss_bytes": 3618586624
    },
    {
      "trial": 6,
      "input_events": 2946,
      "custom_spikes": 3499,
      "reference_spikes": 3490,
      "custom_clamp_count": 27596,
      "custom_wall_seconds": 3.3868222500022966,
      "reference_wall_seconds": 3.3146477500049514,
      "custom_spike_hash": "48a505d203eecfb53399f810629d3570dee2c65be03bdf9e65c48b7b5e461aae",
      "reference_spike_hash": "39c884663680a430c28a9b11d042bd9ae5651322f76fed0ce351d97d178b6b3f",
      "custom_file_sha256": "af3ee8b9464f7a8dd8b91dd639f4fa47b471996d1d9afdd3f2f80def63083fcb",
      "reference_file_sha256": "726a3d6454c5e04a65adcc5788ad2736d983bafa60f30467cf61e9f6c97a8161",
      "peak_process_rss_bytes": 3618586624
    },
    {
      "trial": 7,
      "input_events": 3053,
      "custom_spikes": 3504,
      "reference_spikes": 3493,
      "custom_clamp_count": 27753,
      "custom_wall_seconds": 3.3584691249998286,
      "reference_wall_seconds": 3.338954124999873,
      "custom_spike_hash": "84c6d7324444fe14e48066b4ace8f4f0464b389d8d8eb5a9b311d0796297e359",
      "reference_spike_hash": "5a14033e823530d60300f109b6c88eba76d8a1072844a8fd6319df92bca0e884",
      "custom_file_sha256": "6f022fdfa1d836a92b8441df8e8d204499a86a9c5e3258b3817070de4662b6d3",
      "reference_file_sha256": "610868e1615e86bac8e2ca7ab74f1db1ad2e4d98b9e83d7abefc474fd457edb0",
      "peak_process_rss_bytes": 3618586624
    },
    {
      "trial": 8,
      "input_events": 2977,
      "custom_spikes": 3442,
      "reference_spikes": 3441,
      "custom_clamp_count": 28617,
      "custom_wall_seconds": 3.361167041999579,
      "reference_wall_seconds": 3.338383916998282,
      "custom_spike_hash": "da9571c4b60c3dbe03dd670db0f77ea11b795b19af45ca3c8fc8e66eb4817c44",
      "reference_spike_hash": "e0164c2ce7bc1eb48793de98c3f6ad0abf0a8917c7e3e20d012c6aa4c7e6fc7d",
      "custom_file_sha256": "1e636110b992c254e026ab57d52aaef701831a91b1c0e88a41d4054929890990",
      "reference_file_sha256": "921ce3c07d006a70f55b06b6e42ebeda5973c411e37587e11504cde42097f77f",
      "peak_process_rss_bytes": 3618586624
    },
    {
      "trial": 9,
      "input_events": 3046,
      "custom_spikes": 3630,
      "reference_spikes": 3622,
      "custom_clamp_count": 28336,
      "custom_wall_seconds": 3.35156008299964,
      "reference_wall_seconds": 3.3464953749935376,
      "custom_spike_hash": "9a6955ebe311604afad20f50f7accdd1671b65468d2f66feb45c1db62be82638",
      "reference_spike_hash": "823d0db57af3cbbb828832b76fe85b651eaaa011f0bfaf1759e29bb8c7f8432c",
      "custom_file_sha256": "3b4ddeafad21178a5a4a80b4b9e7d018467400234ef34569566f71f20562fe26",
      "reference_file_sha256": "b396e0e213c85bad2e0be9c4fd2fada60b5b7774817f31290eeb3a32c13c2026",
      "peak_process_rss_bytes": 3618586624
    }
  ],
  "versions": {
    "numpy": "2.5.3",
    "scipy": "1.18.1",
    "brian2": "2.10.1",
    "numba": "0.67.0",
    "python": "3.12.13"
  },
  "git_hash": "de0af06ee9ade6c93dc65f0689afd2d4e2339306",
  "seed": 783,
  "driven_neuron_indices": {
    "total_items": 20,
    "first_12": [
      128197,
      41976,
      67145,
      77020,
      101604,
      109954,
      1873,
      65161,
      133436,
      15801,
      35645,
      34656
    ],
    "note": "Full list in the linked JSON evidence."
  },
  "input_events_sha256": "dd259bafc20b40365ebbdc549c5f9760cd3a55dcc948402f12bb6d1f8186a25d",
  "determinism": {
    "status": "PASS",
    "first_trial_spike_hash": "e4fb0a6ff7eb17767baeb1cea9fb2f79a23f6632b98116ce1498bdb31dc2cff4",
    "repeat_spike_hash": "e4fb0a6ff7eb17767baeb1cea9fb2f79a23f6632b98116ce1498bdb31dc2cff4"
  },
  "metrics": {
    "mean_rate_correlation": 0.9999959214190753,
    "follower_mean_rate_correlation": 0.9999060081745329,
    "pooled_trial_neuron_correlation": 0.9999743483095944,
    "follower_pooled_correlation": 0.9992731287487728,
    "active_union_neurons": 105,
    "follower_active_union_neurons": 85,
    "custom_active_neurons": 105,
    "reference_active_neurons": 104,
    "custom_spikes": 35183,
    "reference_spikes": 35071,
    "mean_rate_absolute_error_hz": 0.11047619047619056,
    "follower_mean_rate_absolute_error_hz": 0.13647058823529423,
    "max_mean_rate_absolute_error_hz": 0.6999999999999993
  },
  "clamp_count": 276226,
  "wall_seconds": 74.39723249999952,
  "peak_process_rss_bytes": 3618586624
}
```

## V-C: Numerics and equilibration

[Complete measurements and provenance](build/validation_hybrid.json)

```json
{
  "gate": "V-C",
  "status": "NOT-RUN",
  "created_at": "2026-09-25T16:42:25.142224+00:00",
  "checks": [
    {
      "name": "per_neuron_clamp_accounting",
      "status": "PASS",
      "observed": 39945,
      "expected": 39945
    },
    {
      "name": "stationary_after_preequilibration",
      "status": "FAIL",
      "observed": 4.528432349941357,
      "expected": "max |dV/dt| <= 0.001 mV/ms; all derivatives finite"
    },
    {
      "name": "zero_preequilibration_clamps",
      "status": "FAIL",
      "observed": 39945,
      "expected": 0
    },
    {
      "name": "T4_T5_peak_response_dt_convergence",
      "status": "NOT-RUN",
      "observed": null,
      "expected": "<5% change on halving dt; requires stage-5 eye/transduction and full-field ON/OFF input"
    }
  ],
  "warnings": [],
  "protocol": {
    "mode": "hybrid",
    "lamina_mode": "connectome",
    "params": "uniform",
    "dt_ms": 0.1,
    "external_input": "zero",
    "threads": 16,
    "graded_dynamics": "DESIGN_NOTES.md normalized passive voltage-state equation",
    "actual_dt_graded_ms": 0.1,
    "requested_dt_graded_ms": 0.5
  },
  "equilibration": {
    "stationary": false,
    "max_abs_dvdt_mV_per_ms": 4.528432349941357,
    "nonfinite_derivatives": 0,
    "unstable_neurons": 47385,
    "unstable_by_mode": {
      "graded": 28020,
      "spiking": 19365
    },
    "clamp_events": 39945,
    "clamped_neurons": 32,
    "affected_cell_types": {
      "total_items": 6109,
      "first_12": [
        {
          "cell_type": "T2a",
          "super_class": "optic",
          "mode": "graded",
          "n_neurons": 1772,
          "n_unstable": 1334,
          "clamp_events": 0,
          "max_abs_dvdt_mV_per_ms": 0.019302349067929193
        },
        {
          "cell_type": "T3",
          "super_class": "optic",
          "mode": "graded",
          "n_neurons": 1675,
          "n_unstable": 1301,
          "clamp_events": 0,
          "max_abs_dvdt_mV_per_ms": 0.044738761662598554
        },
        {
          "cell_type": "T2",
          "super_class": "optic",
          "mode": "graded",
          "n_neurons": 1466,
          "n_unstable": 1278,
          "clamp_events": 0,
          "max_abs_dvdt_mV_per_ms": 0.04835072481558862
        },
        {
          "cell_type": "TmY5a",
          "super_class": "optic",
          "mode": "graded",
          "n_neurons": 1175,
          "n_unstable": 1093,
          "clamp_events": 0,
          "max_abs_dvdt_mV_per_ms": 0.09280580755705288
        },
        {
          "cell_type": "Tm3",
          "super_class": "optic",
          "mode": "graded",
          "n_neurons": 1756,
          "n_unstable": 1060,
          "clamp_events": 0,
          "max_abs_dvdt_mV_per_ms": 0.02010828400535659
        },
        {
          "cell_type": "Tm21",
          "super_class": "optic",
          "mode": "graded",
          "n_neurons": 1296,
          "n_unstable": 1024,
          "clamp_events": 0,
          "max_abs_dvdt_mV_per_ms": 0.025092985749431806
        },
        {
          "cell_type": "Mi1",
          "super_class": "optic",
          "mode": "graded",
          "n_neurons": 1584,
          "n_unstable": 852,
          "clamp_events": 0,
          "max_abs_dvdt_mV_per_ms": 0.008196150802279822
        },
        {
          "cell_type": "Tm2",
          "super_class": "optic",
          "mode": "graded",
          "n_neurons": 1551,
          "n_unstable": 831,
          "clamp_events": 0,
          "max_abs_dvdt_mV_per_ms": 0.02932665407704771
        },
        {
          "cell_type": "T5b",
          "super_class": "optic",
          "mode": "graded",
          "n_neurons": 1513,
          "n_unstable": 821,
          "clamp_events": 0,
          "max_abs_dvdt_mV_per_ms": 0.027419732370442006
        },
        {
          "cell_type": "T5c",
          "super_class": "optic",
          "mode": "graded",
          "n_neurons": 1541,
          "n_unstable": 787,
          "clamp_events": 0,
          "max_abs_dvdt_mV_per_ms": 0.023783996368933025
        },
        {
          "cell_type": "T5d",
          "super_class": "optic",
          "mode": "graded",
          "n_neurons": 1467,
          "n_unstable": 781,
          "clamp_events": 0,
          "max_abs_dvdt_mV_per_ms": 0.025695274022485594
        },
        {
          "cell_type": "T5a",
          "super_class": "optic",
          "mode": "graded",
          "n_neurons": 1484,
          "n_unstable": 778,
          "clamp_events": 0,
          "max_abs_dvdt_mV_per_ms": 0.0255546182976622
        }
      ],
      "note": "Full list in the linked JSON evidence."
    },
    "duration_ms": 1000.0,
    "spikes_by_super_class": {
      "ascending": 0,
      "central": 6324,
      "descending": 787,
      "endocrine": 0,
      "missing": 0,
      "motor": 7,
      "optic": 11,
      "sensory": 0,
      "sensory_ascending": 0,
      "visual_centrifugal": 200,
      "visual_projection": 517
    },
    "evidence": "runs/20260925T164238Z_hybrid_preequilibration_0d98f1"
  },
  "stage4_subgate_status": "FAIL",
  "previous_status": "FAIL",
  "stale_evidence_reasons": [
    "Implementation or configuration changed since validation: src/flybrain/hybrid_engine.py"
  ]
}
```

## V-D: Five-second dark control

[Complete measurements and provenance](build/validation_hybrid.json)

```json
{
  "gate": "V-D",
  "status": "NOT-RUN",
  "created_at": "2026-09-25T16:42:25.142224+00:00",
  "checks": [],
  "warnings": [],
  "protocol": {
    "mode": "hybrid",
    "lamina_mode": "connectome",
    "params": "uniform",
    "dt_ms": 0.1,
    "external_input": "zero",
    "threads": 16,
    "graded_dynamics": "DESIGN_NOTES.md normalized passive voltage-state equation",
    "actual_dt_graded_ms": 0.1,
    "requested_dt_graded_ms": 0.5
  },
  "reason": "Not started: fixed-parameter pre-equilibration failed V-C; later stages stopped."
}
```

## Network build

```json
{
  "status": "PASS",
  "stage": "released_network_assembly",
  "mode": "hybrid",
  "created_at": "2026-09-25T16:26:42.167731+00:00",
  "n_neurons": 138639,
  "n_edges_released": 15091983,
  "n_graded": 85472,
  "n_spiking": 53167,
  "edge_partition": {
    "graded_to_graded": 5483803,
    "graded_to_spiking": 1773007,
    "spiking_to_graded": 962905,
    "spiking_to_spiking": 6872268
  },
  "first_pass_n_graded": 96674,
  "first_pass_n_spiking": 41965,
  "first_pass_edge_partition": {
    "graded_to_graded": 8903991,
    "graded_to_spiking": 464989,
    "spiking_to_graded": 185308,
    "spiking_to_spiking": 5537695
  },
  "matrix_orientation": "rows=postsynaptic; columns=presynaptic",
  "matrix_units": "signed synapse counts; apply per-mode engine gain exactly once",
  "matrix_dtype": "float32",
  "matrix_index_dtype": "int32",
  "graded_nnz": 7256810,
  "spiking_nnz": 7835173,
  "reference_nnz": 15091983,
  "csr_hybrid_bytes": 121844984,
  "sign_overridden_edges": 38373,
  "sign_overridden_synapses": 225078,
  "synthetic_edges": 0,
  "lamina_mode": "connectome",
  "cartridge_repair_status": "NOT-RUN (requires stage 5 priors and columns)",
  "source_hashes": {
    "Completeness_783.csv": "bbb847a4cc2caaa7a16349722d220c087317b946d148d4d592d94d250617a311",
    "Connectivity_783.parquet": "efeb23fb99098e9c390f6869969b2a121a2ee92c833cfc45ecb2c1d8e1af0347",
    "Supplemental_file1_neuron_annotations.tsv": "9a4f8b2f843196074431ebd7cd883536afa1be86c8a4ce90970441e8be81d1be"
  },
  "source_stats": {
    "Completeness_783.csv": {
      "size": 3327347,
      "mtime_ns": 1790353217275849803,
      "ctime_ns": 1790353217275849803,
      "inode": 109914551
    },
    "Connectivity_783.parquet": {
      "size": 100804642,
      "mtime_ns": 1790353264459881910,
      "ctime_ns": 1790353264459881910,
      "inode": 109914552
    },
    "Supplemental_file1_neuron_annotations.tsv": {
      "size": 31718505,
      "mtime_ns": 1790353227286969943,
      "ctime_ns": 1790353227286969943,
      "inode": 109914547
    }
  },
  "config_hashes": {
    "neuron_modes.csv": "ea0ff19c1b632b357dad7f5c1345c0b3c700eaa279c9a44450db937a175ce2a0",
    "sign_overrides.csv": "647c5f169e973c4570582c5047c3b15e23bca6d60f5bd7c173ccacb6dba8e7d8"
  },
  "wall_seconds": 17.019913624993933,
  "output_hashes": {
    "neurons.parquet": "432901d18d2a5b44fd44dd558668589b81103344eeb8f44b2637cbd6b5f8889e",
    "graded_counts.npz": "4047d989ad4ad7d9f1d7f3a2296bf2cd8d5fc437bb9532bec57ee8c897d40b52",
    "spiking_counts.npz": "f9f1472572e6468324e8866d43c902939498cb62e5348beee33a4527ed3019b5",
    "reference_counts.npz": "830ecb2f50e56dccee482de41ff080c5b2b3e5e5539a6ad8a652a035acdadcb9",
    "sign_overrides.csv": "e8585667cf24271ca26d6c4ec9f1fa4294f280db388137f880412838fb222081"
  }
}
```

## Evidence files

- `build/schema_inspection.json`: observed schemas and three source rows.
- `build/downloads.json`: URLs, byte counts, SHA-256, file signatures and publisher checksums where supplied.
- `BUILD_BRIEF.md`: unmodified input brief.

## Scope and scientific limitations

See [LIMITATIONS.md](LIMITATIONS.md). Biological validation, parameter sweeps and figures are pending unless accompanied by run evidence above.


## Neuromodulation extension

Requested specification: [NEUROMOD_BUILD_BRIEF.md](NEUROMOD_BUILD_BRIEF.md). [Final corrections](NEUROMOD_FINAL.md) supersede the original plasticity equation; Patch 1 corrects source policies. Primary-data/software failures stop dependent stages; population-definition discrepancies are reported while normative selectors remain authoritative. No absent measurement is a pass.

[Accepted findings from the initial audit](docs/neuromod_specification_findings.md).

| Gate | Kind | Check / source | Status | Measurement |
|---|---|---|---|---|
| V-NM-A | software | Disabled-layer equivalence | PASS | 47/47 exact checks passed |
| V-NM-B | software | 60 s event-log replay determinism | PASS | {"duration_ms": 60000} |
| V-NM-C | software | Sources, overrides and released connectivity census | PASS | 115/115 exact checks passed |
| V-NM-COMP | software | Empirical compartment construction and assignment audit | PASS | 24/24 exact checks passed |
| V-NM-CORE | software | Core zero-input resting equilibrium (Patch 1) | PASS | {"neurons": 13300, "edges": 1161917, "duration_ms": 1000.0, "dt_ms": 0.1, "threads": 1, "max_abs_dvdt_mV_per_ms": 0.0, "tolerance_mV_per_ms": 0.001, "spikes": 0, "clamps": 0, "wall_seconds": 1.8102914579940261} |
| V-NM-ODOUR | software | Source-backed ORN response mapping and transduction | PASS | 35/35 exact checks passed |
| V-NM-ODSP | biology | Odour-driven core dynamics and Kenyon-cell sparseness | NOT-RUN | OCT: KC active 68.82% (FAIL); MCH: KC active 68.40% (FAIL) |
| V-NM-D | software | Compartment field numerics | PASS | 36/36 exact checks passed |
| V-NM-E | software | Plasticity bounds and twelve-point reference curve | PASS | {"max_absolute_reference_error": 4.914877153507774e-07, "reference_tolerance": 0.001, "reference_points_within_tolerance": 12, "max_error_float32_against_pinned_float64": 1.0945969917797171e-05, "independent_float32_tolerance": 0.0002, "max_delta_halving_dt": 3.057678519868823e-05, "weight_clamp_events": 0, "concentration_clamp_events": 0, "total_absolute_weight_change": 0.7755163908004761, "crossover_ms": -510.0785844603025, "crossover_method": "linear interpolation between measured adjacent delays", "peak_depression_delay_ms": 500, "forward_sum": -0.4516254030892669, "backward_sum": 0.07462087458527955, "eta_decade_ratio": 10.000036239624023, "zero_input_forgetting_delta": 0.0008326172828674316} |
| V-NM-F' | software | 60 s real-time budget and resident memory | FAIL | {"real_time_factor": 0.6351292182986253, "duration_ms": 60000, "over_budget_fraction": 1.0, "rss_sampled_max_bytes": 1001078784} |
| V-NM-F | biology | Pairing asymmetry against Handler 2019, PMID:31230716 | FAIL | {"forward_sum": -0.9990192800760269, "backward_sum": -1.1960499733686447} |
| V-NM-G | biology | Compartment specificity, PMID:26687359 | PASS | {"paired_mean_absolute_change": 0.035155411809682846, "ratio": 25.73906794003374} |
| V-NM-H | biology | Behavioural sign, PMID:25535794; PMID:25864636 | FAIL | {"valence_change": 6.765432098765432, "appetitive_valence_change": 7.0925925925925934} |
| V-NM-I | biology | Octopamine visual gain, PMID:23142045 | NOT-RUN | not measured |
| V-NM-J | biology | Fed/starved state dependence | FAIL | {"valence_difference_starved_minus_fed": -0.813271604938274, "decoded_decisions": {"fed": 1, "starved": 1}} |
| V-NM-K | biology | Extinction through recurrence, PMID:30245010; PMID:32203499 | FAIL | {"relative_reversal": -0.23932632290077824} |

### V-NM-F evidence

[Complete recorded evidence](build/validation_neuromod_biology.json)

Closed-loop network curve; distinct from the prescribed single-synapse reference


### V-NM-G evidence

[Complete recorded evidence](build/validation_neuromod_biology.json)

Treatment minus same-seed no-pulse control; direct field clamp is simulation-only


### V-NM-H evidence

[Complete recorded evidence](build/validation_neuromod_biology.json)


### V-NM-K evidence

[Complete recorded evidence](build/validation_neuromod_biology.json)

Repeated unrewarded odor, compared with passive forgetting and an explicit MBON→DAN ablation diagnostic


### V-NM-J evidence

[Complete recorded evidence](build/validation_neuromod_state.json)

| Assertion | Expected | Observed | Status |
|---|---|---|---|
| endocrine_neurons | 76 | 76 | PASS |
| identified_peptide_sources | 52 | 52 | PASS |
| unknown_endocrine_retained_without_hormone | 24 | 24 | PASS |
| no_akh_source_invented | False | False | PASS |
| control_replay_bit_exact | True | True | PASS |
| snapshot_restore_exact | True | True | PASS |
| parameter_gains_only_on_PAM | True | True | PASS |
| no_release_in_unidentified_cells | True | True | PASS |
| default_state_clamps | 0 | 0 | PASS |
| sensitivity_all_finite | True | True | PASS |
| same_odor_stimulus | 2110f85d6c34139bfbc8269ce4cd5b8f19d2f28706da0a2016d0f572ae15b2ac | 2110f85d6c34139bfbc8269ce4cd5b8f19d2f28706da0a2016d0f572ae15b2ac | PASS |
| same_parameters | 391aa0ad915f58c3bf6948f4473826bbd6838bc4333f3de5ccfd63809ded11b7 | 391aa0ad915f58c3bf6948f4473826bbd6838bc4333f3de5ccfd63809ded11b7 | PASS |
| same_initial_weights | 31da63d082a2b4b49bde2b35ff1f2c1b96ed597288e24f9e536be9cf5ba87e32 | 31da63d082a2b4b49bde2b35ff1f2c1b96ed597288e24f9e536be9cf5ba87e32 | PASS |
| fed_weights_unchanged | 31da63d082a2b4b49bde2b35ff1f2c1b96ed597288e24f9e536be9cf5ba87e32 | 31da63d082a2b4b49bde2b35ff1f2c1b96ed597288e24f9e536be9cf5ba87e32 | PASS |
| starved_weights_unchanged | 31da63d082a2b4b49bde2b35ff1f2c1b96ed597288e24f9e536be9cf5ba87e32 | 31da63d082a2b4b49bde2b35ff1f2c1b96ed597288e24f9e536be9cf5ba87e32 | PASS |
| finite_network_valence | True | True | PASS |

Executed **51** endocrine-state sensitivity fixtures. [All measured state runs](build/neuromod_state_sensitivity.csv). These software fixtures do not establish a biological decision change.

### V-NM-COMP evidence

[Complete recorded evidence](build/validation_neuromod_compartments.json)

| Assertion | Expected | Observed | Status |
|---|---|---|---|
| prerequisite_source_gate | PASS | PASS | PASS |
| joint_DAN_MBON_types | 65 | 65 | PASS |
| empirical_clusters | 15 | 15 | PASS |
| reference_covers_each_type_with_explicit_status | True | True | PASS |
| model_row_order | True | True | PASS |
| membership_shape | [96, 138639] | [96, 138639] | PASS |
| symmetric_nonnegative_adjacency | True | True | PASS |
| no_self_adjacency | 0 | 0 | PASS |
| all_required_ROIs_available | [] | [] | PASS |
| empty_partner_types_unassigned | True | True | PASS |
| plastic_edge_count | 62261 | 62261 | PASS |
| plastic_synapse_count | 256719 | 256719 | PASS |
| every_plastic_edge_has_empirical_assignment | 0 | 0 | PASS |
| unchanged_config_hashes_neuromod.yaml | 56d4fd1a1ed8de73398d9b672ffb1851fc7971d82fc5db9923db270ecad75cd8 | 56d4fd1a1ed8de73398d9b672ffb1851fc7971d82fc5db9923db270ecad75cd8 | PASS |
| unchanged_config_hashes_mb_compartment_reference.csv | 5a47427f2d0d4b6aa47634226f0c821dee1bf4177aeaeb170f97915db9d14c1e | 5a47427f2d0d4b6aa47634226f0c821dee1bf4177aeaeb170f97915db9d14c1e | PASS |
| unchanged_implementation_hashes_src/flybrain/neuromod/compartments.py | 72bc1c934c0d13d952940718ff88b751b1eec67e401a011282159e1646fa8521 | 72bc1c934c0d13d952940718ff88b751b1eec67e401a011282159e1646fa8521 | PASS |
| unchanged_implementation_hashes_src/flybrain/neuromod/sources.py | 87fa160859fcfdce2476cc281efb57d413b670cf13424befc20fab563bbbcdcd | 87fa160859fcfdce2476cc281efb57d413b670cf13424befc20fab563bbbcdcd | PASS |
| unchanged_implementation_hashes_src/flybrain/visual_neuropils.py | cd79d42c25db84fc325181f3b2da56379bbce501154e2a9bfa7808d41fb46f0a | cd79d42c25db84fc325181f3b2da56379bbce501154e2a9bfa7808d41fb46f0a | PASS |
| unchanged_dependency_hashes_build/validation_neuromod_sources.json | 3e140e86db7e81463f25e7b3d4670c5acca0f7df92b2a9185c08f7475be8b7d8 | 3e140e86db7e81463f25e7b3d4670c5acca0f7df92b2a9185c08f7475be8b7d8 | PASS |
| unchanged_dependency_hashes_build/visual_neuropil_weights.npz | c01ca818b00082dc5cb078cfa3364168dfb7c0e2cd4c93da92e3e67dfb5778df | c01ca818b00082dc5cb078cfa3364168dfb7c0e2cd4c93da92e3e67dfb5778df | PASS |
| unchanged_dependency_hashes_build/visual_neuropil_counts.npz | 037654b9d27bbbefd4a89cb638a986ed897071f81b110723a5c0d6c4f2c6a90e | 037654b9d27bbbefd4a89cb638a986ed897071f81b110723a5c0d6c4f2c6a90e | PASS |
| unchanged_neuropil_source_hashes_build/neurons.parquet | 432901d18d2a5b44fd44dd558668589b81103344eeb8f44b2637cbd6b5f8889e | 432901d18d2a5b44fd44dd558668589b81103344eeb8f44b2637cbd6b5f8889e | PASS |
| unchanged_neuropil_source_hashes_data/raw/per_neuron_neuropil_count_pre_783.feather | 35442a46f076892dff91bd6e55fa1489b3acc64fda1d35cee7dbbbbc509a3dff | 35442a46f076892dff91bd6e55fa1489b3acc64fda1d35cee7dbbbbc509a3dff | PASS |
| unchanged_neuropil_source_hashes_data/raw/per_neuron_neuropil_count_post_783.feather | e2418f4794fe47984bb4bc15ffc194003ea8e349a428551f30af94947d85d712 | e2418f4794fe47984bb4bc15ffc194003ea8e349a428551f30af94947d85d712 | PASS |

**Empirical clustering versus published anatomy**

| Comparison | Types |
|---|---:|
| disagreement | 23 |
| match | 14 |
| multi compartment disagrees | 11 |
| multi compartment contains cluster | 5 |
| unmapped reference | 5 |
| empty partner vector | 4 |
| outside 15 | 1 |
| ambiguous reference label | 1 |
| unsupported cluster label | 1 |

[Every type and its disagreement](build/mb_compartment_comparison.csv); [15-compartment inventory](build/mb_compartments.csv); [method and anatomical sources](docs/compartments.md). The connectivity-derived label for PPL101 is g4; the published anatomical assignment is g1. This disagreement is retained, so a command targeting an empirical cluster cannot be presented as anatomically verified γ1 stimulation.

**Coverage**

```json
{
  "unassigned_neurons": 25969,
  "n_compartments": 96,
  "membership_neurons": {
    "total_items": 96,
    "first_12": [
      105,
      385,
      158,
      5307,
      922,
      554,
      2192,
      531,
      533,
      3,
      2707,
      367
    ],
    "note": "Full list in the linked JSON evidence."
  },
  "AL_named_territory_cells": 2601,
  "AL_cells_considered": 2964,
  "AL_unresolved_cells": 363,
  "AL_glomeruli": 58
}
```

**Warnings**

```json
[
  "Canonical alignment is a label comparison, not validation of anatomical compartments.",
  "Binary KC-partner overlap discards positions along KC axons; matching or mismatching labels is the result, not a fitting objective.",
  "Published mapping is from the hemibrain; correspondence of identically named FlyWire types is a cross-dataset assumption.",
  "Source membership in a compartment does not establish its modulator release location.",
  "Unsupported canonical label bp1 for empirical cluster 4",
  "Unsupported canonical label g3 for empirical cluster 8",
  "Unsupported canonical label a1 for empirical cluster 10",
  "Unsupported canonical label a3 for empirical cluster 11",
  "Unsupported canonical label ap1 for empirical cluster 12",
  "Unsupported canonical label ap2 for empirical cluster 13",
  "Unsupported canonical label ap3 for empirical cluster 14"
]
```

### V-NM-CORE evidence

[Complete recorded evidence](build/validation_neuromod_core.json)

Zero-input equilibrium from base resting initialization, not driven/recurrent stability or a real-time benchmark

| Assertion | Expected | Observed | Status |
|---|---|---|---|
| completed | True | True | PASS |
| finite_state | True | True | PASS |
| stationary_neurons | 0 | 0 | PASS |
| zero_input_spikes | 0 | 0 | PASS |
| clamping_disabled | False | False | PASS |
| unchanged_config_hashes_parameters.yaml | af489b36dbe1c330bbe9e5a772d262c740a62ea1e4a0ba3d551ca3a3e6955bdb | af489b36dbe1c330bbe9e5a772d262c740a62ea1e4a0ba3d551ca3a3e6955bdb | PASS |
| unchanged_config_hashes_neuromod.yaml | 56d4fd1a1ed8de73398d9b672ffb1851fc7971d82fc5db9923db270ecad75cd8 | 56d4fd1a1ed8de73398d9b672ffb1851fc7971d82fc5db9923db270ecad75cd8 | PASS |
| unchanged_implementation_hashes_src/flybrain/engine.py | 087bc83a4602f12fd349b7a92ce4bdf9ce5e24663198247272cdfe15d45d5dc5 | 087bc83a4602f12fd349b7a92ce4bdf9ce5e24663198247272cdfe15d45d5dc5 | PASS |
| unchanged_implementation_hashes_src/flybrain/neuromod/core.py | 0e95f195ae487590cf7bf27ff88d7f6fae436edd9ae3900a3f12830abd12e2e2 | 0e95f195ae487590cf7bf27ff88d7f6fae436edd9ae3900a3f12830abd12e2e2 | PASS |
| unchanged_implementation_hashes_src/flybrain/neuromod/sources.py | 87fa160859fcfdce2476cc281efb57d413b670cf13424befc20fab563bbbcdcd | 87fa160859fcfdce2476cc281efb57d413b670cf13424befc20fab563bbbcdcd | PASS |
| unchanged_dependency_hashes_build/validation_neuromod_sources.json | 3e140e86db7e81463f25e7b3d4670c5acca0f7df92b2a9185c08f7475be8b7d8 | 3e140e86db7e81463f25e7b3d4670c5acca0f7df92b2a9185c08f7475be8b7d8 | PASS |
| unchanged_dependency_hashes_runs/20260925T164238Z_hybrid_preequilibration_0d98f1/activity.npz | 04e5c890caf5e6eee92bf63ce5f593098e0a2fa0189fca5ff8cd82c6b5ca5ec6 | 04e5c890caf5e6eee92bf63ce5f593098e0a2fa0189fca5ff8cd82c6b5ca5ec6 | PASS |
| unchanged_dependency_hashes_runs/20260925T164238Z_hybrid_preequilibration_0d98f1/endpoint_state.npz | c09c9987a63e3f0cee73a69c61e7c761f44c1829a1644f4130e5f53f5ba03039 | c09c9987a63e3f0cee73a69c61e7c761f44c1829a1644f4130e5f53f5ba03039 | PASS |
| unchanged_dependency_hashes_runs/20260925T164238Z_hybrid_preequilibration_0d98f1/run_manifest.json | 42723ede250e3212b81f44349c7ee0cb934b097fd5c92e3d033bc58ed2bcebfe | 42723ede250e3212b81f44349c7ee0cb934b097fd5c92e3d033bc58ed2bcebfe | PASS |

**Wholebrain comparison**

```json
{
  "status": "FAIL",
  "rerun": false,
  "evidence": "runs/20260925T164238Z_hybrid_preequilibration_0d98f1",
  "max_abs_dvdt_mV_per_ms": 4.528432349941357,
  "unstable_neurons": 47385,
  "clamp_events": 39945,
  "spikes": 7846,
  "failed_type_groups": 6109,
  "per_type_rates_file": "build/neuromod_wholebrain_failed_types.csv",
  "dependency_hashes": {
    "runs/20260925T164238Z_hybrid_preequilibration_0d98f1/activity.npz": "04e5c890caf5e6eee92bf63ce5f593098e0a2fa0189fca5ff8cd82c6b5ca5ec6",
    "runs/20260925T164238Z_hybrid_preequilibration_0d98f1/endpoint_state.npz": "c09c9987a63e3f0cee73a69c61e7c761f44c1829a1644f4130e5f53f5ba03039",
    "runs/20260925T164238Z_hybrid_preequilibration_0d98f1/run_manifest.json": "42723ede250e3212b81f44349c7ee0cb934b097fd5c92e3d033bc58ed2bcebfe"
  }
}
```

### V-NM-D evidence

[Complete recorded evidence](build/validation_neuromod_field.json)

Headless field integrator only; not a modulated network, receptor or behaviour validation

| Assertion | Expected | Observed | Status |
|---|---|---|---|
| tau_at_least_10_dt | >= 10 | 50.0 | PASS |
| integer_timestep_ratio | positive integer | 10.0 | PASS |
| default_concentration_clamps | 0 | 0 | PASS |
| field_float32 | float32 | float32 | PASS |
| analytic_pulse_decay_DA | < 1e-5 a.u. | 1.2574712501822738e-07 | PASS |
| half_dt_peak_DA | < 0.01 | 0.0 | PASS |
| full_drive_normalization_DA | source_gain (1 a.u. by default), error < 0.003 | 0.9999880790710449 | PASS |
| analytic_pulse_decay_OA | < 1e-5 a.u. | 1.4494302591483432e-07 | PASS |
| half_dt_peak_OA | < 0.01 | 5.256724770296898e-07 | PASS |
| full_drive_normalization_OA | source_gain (1 a.u. by default), error < 0.003 | 0.9999552965164185 | PASS |
| analytic_pulse_decay_5HT | < 1e-5 a.u. | 1.0847668371893882e-07 | PASS |
| half_dt_peak_5HT | < 0.01 | 1.347307244794409e-07 | PASS |
| full_drive_normalization_5HT | source_gain (1 a.u. by default), error < 0.003 | 0.9999403953552246 | PASS |
| analytic_pulse_decay_NO | < 1e-5 a.u. | 1.3801884590769475e-07 | PASS |
| half_dt_peak_NO | < 0.01 | 1.1921471834449858e-07 | PASS |
| full_drive_normalization_NO | source_gain (1 a.u. by default), error < 0.003 | 0.9999937415122986 | PASS |
| analytic_pulse_decay_sNPF | < 1e-5 a.u. | 1.2703691806836837e-08 | PASS |
| half_dt_peak_sNPF | < 0.01 | 2.291519118296772e-07 | PASS |
| full_drive_normalization_sNPF | source_gain (1 a.u. by default), error < 0.003 | 0.999701976776123 | PASS |
| analytic_pulse_decay_peptide_pool | < 1e-5 a.u. | 3.0600587740819973e-08 | PASS |
| half_dt_peak_peptide_pool | < 0.01 | 0.0 | PASS |
| full_drive_normalization_peptide_pool | source_gain (1 a.u. by default), error < 0.003 | 0.9982118606567383 | PASS |
| analytic_pulse_decay_TA | < 1e-5 a.u. | 1.4494302591483432e-07 | PASS |
| half_dt_peak_TA | < 0.01 | 5.256724770296898e-07 | PASS |
| full_drive_normalization_TA | source_gain (1 a.u. by default), error < 0.003 | 0.9999552965164185 | PASS |
| analytic_pulse_decay_ACh | < 1e-5 a.u. | 6.006954855752866e-08 | PASS |
| half_dt_peak_ACh | < 0.01 | 4.800718859642043e-07 | PASS |
| full_drive_normalization_ACh | source_gain (1 a.u. by default), error < 0.003 | 0.9999934434890747 | PASS |
| default_DA_other_compartments_exact_zero | 0 | 0 | PASS |
| single_step_nonadjacent_exact_zero | 0.0 | 0.0 | PASS |
| symmetric_diffusion_mass_after_clearance | 0.9801986733067553 | 0.9801986813545227 | PASS |
| unchanged_config_hashes_neuromod.yaml | 56d4fd1a1ed8de73398d9b672ffb1851fc7971d82fc5db9923db270ecad75cd8 | 56d4fd1a1ed8de73398d9b672ffb1851fc7971d82fc5db9923db270ecad75cd8 | PASS |
| unchanged_implementation_hashes_src/flybrain/neuromod/field.py | e37337469fcd92580ea742024afd8debab96f2edabffb38f7c2c83d6e1b3e629 | e37337469fcd92580ea742024afd8debab96f2edabffb38f7c2c83d6e1b3e629 | PASS |
| unchanged_dependency_hashes_build/validation_neuromod_sources.json | 3e140e86db7e81463f25e7b3d4670c5acca0f7df92b2a9185c08f7475be8b7d8 | 3e140e86db7e81463f25e7b3d4670c5acca0f7df92b2a9185c08f7475be8b7d8 | PASS |
| unchanged_dependency_hashes_build/validation_neuromod_compartments.json | ec954a5ce9a0ef0ef1589457e8e8041d27f7aafcd906f80b5f8c25be6fc0d7af | ec954a5ce9a0ef0ef1589457e8e8041d27f7aafcd906f80b5f8c25be6fc0d7af | PASS |
| unchanged_dependency_hashes_build/compartments.npz | ca6b5db397f57e8c5d809c3fc398b49dee371cc709e5444711e15b7ce36500b5 | ca6b5db397f57e8c5d809c3fc398b49dee371cc709e5444711e15b7ce36500b5 | PASS |

Executed **152** field sensitivity fixtures. Stress fixtures produced **2601** clamps in **8** runs; these are separate from the default-drive clamp assertion above. [All measured runs](build/neuromod_field_sensitivity.csv). Candidate sweeps for other layers are not completed measurements.

**Notes**

```json
[
  "DA zero spillover makes nonadjacent concentrations exactly zero by assumption.",
  "One explicit frozen-neighbor step reaches adjacent volumes only; repeated nonzero NO spillover reaches multiple hops.",
  "Every clearance, source gain, maximal source rate and adjacency spillover coefficient is ASSUMPTION."
]
```

### V-NM-ODOUR evidence

[Complete recorded evidence](build/validation_neuromod_odour.json)

| Assertion | Expected | Observed | Status |
|---|---|---|---|
| normative_named_orn_types | 53 | 53 | PASS |
| normative_orn_neurons | 2279 | 2279 | PASS |
| normative_untyped_orn_neurons | 4 | 4 | PASS |
| finite_usable_evoked_deltas | True | True | PASS |
| missing_responses_zero_evoked_delta | True | True | PASS |
| unique_type_odor_pairs | True | True | PASS |
| finite_nonnegative_rates | True | True | PASS |
| untyped_zero_rates | True | True | PASS |
| source_event_seed_determinism | True | True | PASS |
| unchanged_config_hashes_neuromod.yaml | 56d4fd1a1ed8de73398d9b672ffb1851fc7971d82fc5db9923db270ecad75cd8 | 56d4fd1a1ed8de73398d9b672ffb1851fc7971d82fc5db9923db270ecad75cd8 | PASS |
| unchanged_implementation_hashes_src/flybrain/neuromod/odour.py | 7b61ee6d09ead4d8a03e4b87bef11b4c9320ec33f2836835514db0c5b4b0b8b7 | 7b61ee6d09ead4d8a03e4b87bef11b4c9320ec33f2836835514db0c5b4b0b8b7 | PASS |
| unchanged_dependency_hashes_build/validation_neuromod_sources.json | 3e140e86db7e81463f25e7b3d4670c5acca0f7df92b2a9185c08f7475be8b7d8 | 3e140e86db7e81463f25e7b3d4670c5acca0f7df92b2a9185c08f7475be8b7d8 | PASS |
| unchanged_source_hashes_Completeness_783.csv | bbb847a4cc2caaa7a16349722d220c087317b946d148d4d592d94d250617a311 | bbb847a4cc2caaa7a16349722d220c087317b946d148d4d592d94d250617a311 | PASS |
| unchanged_source_hashes_Connectivity_783.parquet | efeb23fb99098e9c390f6869969b2a121a2ee92c833cfc45ecb2c1d8e1af0347 | efeb23fb99098e9c390f6869969b2a121a2ee92c833cfc45ecb2c1d8e1af0347 | PASS |
| unchanged_source_hashes_Supplemental_file1_neuron_annotations.tsv | 9a4f8b2f843196074431ebd7cd883536afa1be86c8a4ce90970441e8be81d1be | 9a4f8b2f843196074431ebd7cd883536afa1be86c8a4ce90970441e8be81d1be | PASS |
| unchanged_source_hashes_neuromod/door/door_response_matrix.csv | bc2aa5414ff54d3a1399f5fe171e154bcadc754bcf323a3c27711a54f70848e2 | bc2aa5414ff54d3a1399f5fe171e154bcadc754bcf323a3c27711a54f70848e2 | PASS |
| unchanged_source_hashes_neuromod/door/door_mappings.csv | 1197c492e769b1b587c907c5b750ffa2507d7e6c9fe9dfcb2ee8603871e00912 | 1197c492e769b1b587c907c5b750ffa2507d7e6c9fe9dfcb2ee8603871e00912 | PASS |
| unchanged_source_hashes_neuromod/door/odor.csv | a31d1841cf90ce23ec149760a5efa38eae02de7820bb2300c3a7dba221745940 | a31d1841cf90ce23ec149760a5efa38eae02de7820bb2300c3a7dba221745940 | PASS |
| unchanged_source_hashes_neuromod/door/door_dataset_info.csv | 6ab8bc1c843ffe4763e563eb763029c421898dce7889c31dc2c21b544c9be269 | 6ab8bc1c843ffe4763e563eb763029c421898dce7889c31dc2c21b544c9be269 | PASS |
| unchanged_source_hashes_neuromod/door/door_response_range.csv | 5499f1d7bf3217f9af8bc45ee90c85ef09c9f2afd11ca833fae1ad055d97a7f4 | 5499f1d7bf3217f9af8bc45ee90c85ef09c9f2afd11ca833fae1ad055d97a7f4 | PASS |
| unchanged_base_artifact_hashes_neurons.parquet | 432901d18d2a5b44fd44dd558668589b81103344eeb8f44b2637cbd6b5f8889e | 432901d18d2a5b44fd44dd558668589b81103344eeb8f44b2637cbd6b5f8889e | PASS |
| unchanged_base_artifact_hashes_graded_counts.npz | 4047d989ad4ad7d9f1d7f3a2296bf2cd8d5fc437bb9532bec57ee8c897d40b52 | 4047d989ad4ad7d9f1d7f3a2296bf2cd8d5fc437bb9532bec57ee8c897d40b52 | PASS |
| unchanged_base_artifact_hashes_spiking_counts.npz | f9f1472572e6468324e8866d43c902939498cb62e5348beee33a4527ed3019b5 | f9f1472572e6468324e8866d43c902939498cb62e5348beee33a4527ed3019b5 | PASS |
| unchanged_base_artifact_hashes_reference_counts.npz | 830ecb2f50e56dccee482de41ff080c5b2b3e5e5539a6ad8a652a035acdadcb9 | 830ecb2f50e56dccee482de41ff080c5b2b3e5e5539a6ad8a652a035acdadcb9 | PASS |
| unchanged_base_artifact_hashes_sign_overrides.csv | e8585667cf24271ca26d6c4ec9f1fa4294f280db388137f880412838fb222081 | e8585667cf24271ca26d6c4ec9f1fa4294f280db388137f880412838fb222081 | PASS |
| unchanged_base_config_hashes_neuron_modes.csv | ea0ff19c1b632b357dad7f5c1345c0b3c700eaa279c9a44450db937a175ce2a0 | ea0ff19c1b632b357dad7f5c1345c0b3c700eaa279c9a44450db937a175ce2a0 | PASS |
| unchanged_base_config_hashes_sign_overrides.csv | 647c5f169e973c4570582c5047c3b15e23bca6d60f5bd7c173ccacb6dba8e7d8 | 647c5f169e973c4570582c5047c3b15e23bca6d60f5bd7c173ccacb6dba8e7d8 | PASS |
| unchanged_source_signature_Completeness_783.csv | {"size": 3327347, "mtime_ns": 1790353217275849803, "ctime_ns": 1790353217275849803, "inode": 109914551} | {"size": 3327347, "mtime_ns": 1790353217275849803, "ctime_ns": 1790353217275849803, "inode": 109914551} | PASS |
| unchanged_source_signature_Connectivity_783.parquet | {"size": 100804642, "mtime_ns": 1790353264459881910, "ctime_ns": 1790353264459881910, "inode": 109914552} | {"size": 100804642, "mtime_ns": 1790353264459881910, "ctime_ns": 1790353264459881910, "inode": 109914552} | PASS |
| unchanged_source_signature_Supplemental_file1_neuron_annotations.tsv | {"size": 31718505, "mtime_ns": 1790353227286969943, "ctime_ns": 1790353227286969943, "inode": 109914547} | {"size": 31718505, "mtime_ns": 1790353227286969943, "ctime_ns": 1790353227286969943, "inode": 109914547} | PASS |
| unchanged_source_signature_neuromod/door/door_response_matrix.csv | {"size": 295852, "mtime_ns": 1790428520289462828, "ctime_ns": 1790428520289513953, "inode": 110156498} | {"size": 295852, "mtime_ns": 1790428520289462828, "ctime_ns": 1790428520289513953, "inode": 110156498} | PASS |
| unchanged_source_signature_neuromod/door/door_mappings.csv | {"size": 12824, "mtime_ns": 1790428520289858996, "ctime_ns": 1790428520289898329, "inode": 110156499} | {"size": 12824, "mtime_ns": 1790428520289858996, "ctime_ns": 1790428520289898329, "inode": 110156499} | PASS |
| unchanged_source_signature_neuromod/door/odor.csv | {"size": 155880, "mtime_ns": 1790428520290270622, "ctime_ns": 1790428520290306080, "inode": 110156500} | {"size": 155880, "mtime_ns": 1790428520290270622, "ctime_ns": 1790428520290306080, "inode": 110156500} | PASS |
| unchanged_source_signature_neuromod/door/door_dataset_info.csv | {"size": 11105, "mtime_ns": 1790428520290549456, "ctime_ns": 1790428520290586748, "inode": 110156501} | {"size": 11105, "mtime_ns": 1790428520290549456, "ctime_ns": 1790428520290586748, "inode": 110156501} | PASS |
| unchanged_source_signature_neuromod/door/door_response_range.csv | {"size": 1550, "mtime_ns": 1790428520290786832, "ctime_ns": 1790428520290820165, "inode": 110156502} | {"size": 1550, "mtime_ns": 1790428520290786832, "ctime_ns": 1790428520290820165, "inode": 110156502} | PASS |

**Coverage**

```json
{
  "OCT": {
    "requested_name": "OCT",
    "units": "a.u.",
    "value_meaning": "signed evoked consensus minus SFR",
    "mode": "door",
    "types": {
      "total_items": 53,
      "first_12": [
        "ORN_D",
        "ORN_DA1",
        "ORN_DA2",
        "ORN_DA3",
        "ORN_DA4l",
        "ORN_DA4m",
        "ORN_DC1",
        "ORN_DC2",
        "ORN_DC3",
        "ORN_DC4",
        "ORN_DL1",
        "ORN_DL2d"
      ],
      "note": "Full list in the linked JSON evidence."
    },
    "baseline_note": "Missing measurements give zero evoked delta, not measured silence. An independently measured SFR may still drive tonic activity; unmapped, ambiguous and untyped neurons get zero input.",
    "source_commit": "db323a496577c4b4a72b5c2fcd1859e07521ffb5",
    "label": "DoOR consensus",
    "chemical_name": "3-octanol",
    "CAS": "589-98-0",
    "InChIKey": "NMRPBPVERJPACX-UHFFFAOYSA-N",
    "status": {
      "total_items": 53,
      "first_12": [
        "measured_consensus",
        "missing_odor_measurement",
        "measured_consensus",
        "missing_odor_measurement",
        "missing_odor_measurement",
        "measured_consensus",
        "measured_consensus",
        "measured_consensus",
        "measured_consensus",
        "missing_odor_measurement",
        "measured_consensus",
        "ambiguous_ac3A_split"
      ],
      "note": "Full list in the linked JSON evidence."
    },
    "raw_consensus_au": {
      "total_items": 53,
      "first_12": [
        0.740786240786241,
        null,
        0.305927684033243,
        null,
        null,
        0.180975442441156,
        0.473859077540008,
        0.658400874807494,
        0.124423963133641,
        null,
        0.169727859499921,
        null
      ],
      "note": "Full list in the linked JSON evidence."
    },
    "spontaneous_au": {
      "total_items": 53,
      "first_12": [
        0.0,
        null,
        0.0648594697405211,
        0.0193166138419072,
        0.0952840397914614,
        0.0484519594259682,
        0.100068632791183,
        0.0798033726361042,
        0.0783410138248848,
        0.0,
        0.0516610256503943,
        0.0686498715043326
      ],
      "note": "Full list in the linked JSON evidence."
    },
    "baseline_input_au": {
      "total_items": 53,
      "first_12": [
        0.0,
        0.0,
        0.0648594697405211,
        0.0193166138419072,
        0.0952840397914614,
        0.0484519594259682,
        0.100068632791183,
        0.0798033726361042,
        0.0783410138248848,
        0.0,
        0.0516610256503943,
        0.0
      ],
      "note": "Full list in the linked JSON evidence."
    },
    "measured_named_types": 28,
    "named_types": 53,
    "named_type_coverage": 0.5283018867924528,
    "measured_neurons": 1207,
    "total_orn_neurons": 2279,
    "neuron_coverage": 0.5296182536200088,
    "untyped_neurons": 4
  },
  "MCH": {
    "requested_name": "MCH",
    "units": "a.u.",
    "value_meaning": "signed evoked consensus minus SFR",
    "mode": "door",
    "types": {
      "total_items": 53,
      "first_12": [
        "ORN_D",
        "ORN_DA1",
        "ORN_DA2",
        "ORN_DA3",
        "ORN_DA4l",
        "ORN_DA4m",
        "ORN_DC1",
        "ORN_DC2",
        "ORN_DC3",
        "ORN_DC4",
        "ORN_DL1",
        "ORN_DL2d"
      ],
      "note": "Full list in the linked JSON evidence."
    },
    "baseline_note": "Missing measurements give zero evoked delta, not measured silence. An independently measured SFR may still drive tonic activity; unmapped, ambiguous and untyped neurons get zero input.",
    "source_commit": "db323a496577c4b4a72b5c2fcd1859e07521ffb5",
    "label": "DoOR consensus",
    "chemical_name": "4-methylcyclohexanol",
    "CAS": "589-91-3",
    "InChIKey": "MQWCXKGKQLNYQG-UHFFFAOYSA-N",
    "status": {
      "total_items": 53,
      "first_12": [
        "measured_consensus",
        "missing_odor_measurement",
        "measured_consensus",
        "missing_odor_measurement",
        "missing_odor_measurement",
        "missing_odor_measurement",
        "measured_consensus",
        "measured_consensus",
        "measured_consensus",
        "missing_odor_measurement",
        "measured_consensus",
        "ambiguous_ac3A_split"
      ],
      "note": "Full list in the linked JSON evidence."
    },
    "raw_consensus_au": {
      "total_items": 53,
      "first_12": [
        0.635135135135135,
        null,
        0.339176173367663,
        null,
        null,
        null,
        0.0517759403323907,
        0.157418357276083,
        0.15668202764977,
        null,
        0.182335725095656,
        null
      ],
      "note": "Full list in the linked JSON evidence."
    },
    "spontaneous_au": {
      "total_items": 53,
      "first_12": [
        0.0,
        null,
        0.0648594697405211,
        0.0193166138419072,
        0.0952840397914614,
        0.0484519594259682,
        0.100068632791183,
        0.0798033726361042,
        0.0783410138248848,
        0.0,
        0.0516610256503943,
        0.0686498715043326
      ],
      "note": "Full list in the linked JSON evidence."
    },
    "baseline_input_au": {
      "total_items": 53,
      "first_12": [
        0.0,
        0.0,
        0.0648594697405211,
        0.0193166138419072,
        0.0952840397914614,
        0.0484519594259682,
        0.100068632791183,
        0.0798033726361042,
        0.0783410138248848,
        0.0,
        0.0516610256503943,
        0.0
      ],
      "note": "Full list in the linked JSON evidence."
    },
    "measured_named_types": 22,
    "named_types": 53,
    "named_type_coverage": 0.41509433962264153,
    "measured_neurons": 975,
    "total_orn_neurons": 2279,
    "neuron_coverage": 0.4278192189556823,
    "untyped_neurons": 4
  }
}
```

**Limitations**

```json
[
  "Missing measurements give zero evoked delta, not measured silence. An independently measured SFR may still drive tonic activity; unmapped, ambiguous and untyped neurons get zero input.",
  "Consensus-to-Hz conversion and adaptation parameters are assumptions; no AL transform is added",
  "Measured odour response coverage is partial"
]
```

### V-NM-ODSP evidence

[Complete recorded evidence](build/validation_neuromod_odour_sparseness.json)

Historical FAIL evidence is stale: ["Implementation or configuration changed since validation: neuromod.yaml"]


**Limitations**

```json
[
  "No parameter fitted to the sparseness range; no damping, clamp or compensating AL gain",
  "PASS covers this finite protocol only, not general driven stability or whole-brain validity",
  "Different baseline and stimulus windows affect any-spike fractions; per-neuron rates are also reported"
]
```

**Runs**

```json
[
  {
    "odour": "OCT",
    "status": "FAIL",
    "completed": true,
    "failure": null,
    "simulated_ms": 2500.0,
    "seed": 783,
    "kc_neurons": 5177,
    "kc_active_fraction": 0.6882364303650763,
    "baseline_kc_active_fraction": 0.678192003090593,
    "kc_fraction_change": 0.010044427274483292,
    "mean_kc_rate_hz": 36.45644195480008,
    "baseline_mean_kc_rate_hz": 34.974695769750824,
    "max_kc_rate_hz": 107.0,
    "max_neuron_rate_hz": 356.0,
    "biological_fraction_target_met": false,
    "numerics": {
      "finite_observed_state": true,
      "sampled_voltage_bounds_met": false,
      "out_of_bound_voltage_samples": 278639,
      "neurons_with_out_of_bound_samples": 1170,
      "endpoint_out_of_bound_neurons": 10,
      "nonfinite_voltage_samples": 0,
      "minimum_sample_voltage_mV": -167.4487762451172,
      "maximum_sample_voltage_mV": 154.39529418945312,
      "clamp_enabled": false,
      "clamp_events": 0,
      "sample_dt_ms": 0.1,
      "bounds_mV": [
        -90.0,
        20.0
      ],
      "scope": "Every integration-start voltage plus chunk endpoint states; does not inspect internal pre-reset threshold overshoot, prove equilibrium, or establish general driven stability"
    },
    "source_event_count": 173624,
    "network_spike_count": 1023781,
    "wall_seconds_engine": 6.336350665034843,
    "core": {
      "kc_kc_mode": "thresholded",
      "released_edges": 1161917,
      "KC_fast_sign_corrected_edges": 0,
      "removed_KC_KC_edges": 234350,
      "removed_KC_KC_synapses": 234350,
      "effective_edges": 927567,
      "neurons": 13300,
      "mode": "all_spiking",
      "source_validation_sha256": "4484f1fabbf8f6f2e5957e57de9fee7a42503660d4b288b2115ca299aa5ca584",
      "base_artifact_hashes": {
        "neurons.parquet": "432901d18d2a5b44fd44dd558668589b81103344eeb8f44b2637cbd6b5f8889e",
        "graded_counts.npz": "4047d989ad4ad7d9f1d7f3a2296bf2cd8d5fc437bb9532bec57ee8c897d40b52",
        "spiking_counts.npz": "f9f1472572e6468324e8866d43c902939498cb62e5348beee33a4527ed3019b5",
        "reference_counts.npz": "830ecb2f50e56dccee482de41ff080c5b2b3e5e5539a6ad8a652a035acdadcb9",
        "sign_overrides.csv": "e8585667cf24271ca26d6c4ec9f1fa4294f280db388137f880412838fb222081"
      }
    },
    "coverage": {
      "requested_name": "OCT",
      "units": "a.u.",
      "value_meaning": "signed evoked consensus minus SFR",
      "mode": "door",
      "types": {
        "total_items": 53,
        "first_12": [
          "ORN_D",
          "ORN_DA1",
          "ORN_DA2",
          "ORN_DA3",
          "ORN_DA4l",
          "ORN_DA4m",
          "ORN_DC1",
          "ORN_DC2",
          "ORN_DC3",
          "ORN_DC4",
          "ORN_DL1",
          "ORN_DL2d"
        ],
        "note": "Full list in the linked JSON evidence."
      },
      "baseline_note": "Missing measurements give zero evoked delta, not measured silence. An independently measured SFR may still drive tonic activity; unmapped, ambiguous and untyped neurons get zero input.",
      "source_commit": "db323a496577c4b4a72b5c2fcd1859e07521ffb5",
      "label": "DoOR consensus",
      "chemical_name": "3-octanol",
      "CAS": "589-98-0",
      "InChIKey": "NMRPBPVERJPACX-UHFFFAOYSA-N",
      "status": {
        "total_items": 53,
        "first_12": [
          "measured_consensus",
          "missing_odor_measurement",
          "measured_consensus",
          "missing_odor_measurement",
          "missing_odor_measurement",
          "measured_consensus",
          "measured_consensus",
          "measured_consensus",
          "measured_consensus",
          "missing_odor_measurement",
          "measured_consensus",
          "ambiguous_ac3A_split"
        ],
        "note": "Full list in the linked JSON evidence."
      },
      "raw_consensus_au": {
        "total_items": 53,
        "first_12": [
          0.740786240786241,
          null,
          0.305927684033243,
          null,
          null,
          0.180975442441156,
          0.473859077540008,
          0.658400874807494,
          0.124423963133641,
          null,
          0.169727859499921,
          null
        ],
        "note": "Full list in the linked JSON evidence."
      },
      "spontaneous_au": {
        "total_items": 53,
        "first_12": [
          0.0,
          null,
          0.0648594697405211,
          0.0193166138419072,
          0.0952840397914614,
          0.0484519594259682,
          0.100068632791183,
          0.0798033726361042,
          0.0783410138248848,
          0.0,
          0.0516610256503943,
          0.0686498715043326
        ],
        "note": "Full list in the linked JSON evidence."
      },
      "baseline_input_au": {
        "total_items": 53,
        "first_12": [
          0.0,
          0.0,
          0.0648594697405211,
          0.0193166138419072,
          0.0952840397914614,
          0.0484519594259682,
          0.100068632791183,
          0.0798033726361042,
          0.0783410138248848,
          0.0,
          0.0516610256503943,
          0.0
        ],
        "note": "Full list in the linked JSON evidence."
      },
      "measured_named_types": 28,
      "named_types": 53,
      "named_type_coverage": 0.5283018867924528,
      "measured_neurons": 1207,
      "total_orn_neurons": 2279,
      "neuron_coverage": 0.5296182536200088,
      "untyped_neurons": 4
    },
    "baseline_note": "Missing measurements give zero evoked delta, not measured silence. An independently measured SFR may still drive tonic activity; unmapped, ambiguous and untyped neurons get zero input.",
    "checkpoints": {
      "total_items": 25,
      "first_12": [
        {
          "t_ms": 100.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -153.17579986885517,
          "maximum_v_mV": 20.26650031087695,
          "maximum_abs_g_mV": 390.3823343352429
        },
        {
          "t_ms": 200.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -157.3699906571717,
          "maximum_v_mV": 21.498637186574776,
          "maximum_abs_g_mV": 311.0369809915921
        },
        {
          "t_ms": 300.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -158.0967509575383,
          "maximum_v_mV": 21.96658839264368,
          "maximum_abs_g_mV": 200.9645110020799
        },
        {
          "t_ms": 400.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -162.69573233492292,
          "maximum_v_mV": 18.362001808104345,
          "maximum_abs_g_mV": 293.87553224246096
        },
        {
          "t_ms": 500.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -159.0342372235785,
          "maximum_v_mV": 20.252064369457912,
          "maximum_abs_g_mV": 317.8022876795415
        },
        {
          "t_ms": 600.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -156.17662420793496,
          "maximum_v_mV": 21.315879073369622,
          "maximum_abs_g_mV": 346.8656116381203
        },
        {
          "t_ms": 700.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -162.38348190559287,
          "maximum_v_mV": 22.16882313559742,
          "maximum_abs_g_mV": 309.4787881928826
        },
        {
          "t_ms": 800.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -158.46270373447558,
          "maximum_v_mV": 19.370239573751405,
          "maximum_abs_g_mV": 277.4343439210642
        },
        {
          "t_ms": 900.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -157.6616629891033,
          "maximum_v_mV": 18.300665888398925,
          "maximum_abs_g_mV": 224.70023544522715
        },
        {
          "t_ms": 1000.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -159.76927154061045,
          "maximum_v_mV": 22.730496276223256,
          "maximum_abs_g_mV": 506.68774012704773
        },
        {
          "t_ms": 1100.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -161.04537490487974,
          "maximum_v_mV": 18.843464273424694,
          "maximum_abs_g_mV": 237.45759354126437
        },
        {
          "t_ms": 1200.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -161.14534691943138,
          "maximum_v_mV": 22.87214605004172,
          "maximum_abs_g_mV": 468.243440919927
        }
      ],
      "note": "Full list in the linked JSON evidence."
    },
    "artifact_hashes": {
      "odour_sparseness_OCT_neurons.csv": "8f87ecd611763cb05b39d76b39a43631df454373dea836366502b8f9d6979ebf",
      "odour_sparseness_OCT_types.csv": "59118c43f1f9acf781b9001ed2805fa83056fdbc0b227abc8512b6a44c89c12b",
      "odour_sparseness_OCT_activity.npz": "b26359947e34ffcbabb998a37244a928bccaae20f2b0fc3630e8dc943bc816da"
    }
  },
  {
    "odour": "MCH",
    "status": "FAIL",
    "completed": true,
    "failure": null,
    "simulated_ms": 2500.0,
    "seed": 783,
    "kc_neurons": 5177,
    "kc_active_fraction": 0.683986864979718,
    "baseline_kc_active_fraction": 0.678192003090593,
    "kc_fraction_change": 0.005794861889124925,
    "mean_kc_rate_hz": 35.762410662545875,
    "baseline_mean_kc_rate_hz": 34.974695769750824,
    "max_kc_rate_hz": 105.0,
    "max_neuron_rate_hz": 354.0,
    "biological_fraction_target_met": false,
    "numerics": {
      "finite_observed_state": true,
      "sampled_voltage_bounds_met": false,
      "out_of_bound_voltage_samples": 272660,
      "neurons_with_out_of_bound_samples": 1147,
      "endpoint_out_of_bound_neurons": 10,
      "nonfinite_voltage_samples": 0,
      "minimum_sample_voltage_mV": -168.07044982910156,
      "maximum_sample_voltage_mV": 92.4684829711914,
      "clamp_enabled": false,
      "clamp_events": 0,
      "sample_dt_ms": 0.1,
      "bounds_mV": [
        -90.0,
        20.0
      ],
      "scope": "Every integration-start voltage plus chunk endpoint states; does not inspect internal pre-reset threshold overshoot, prove equilibrium, or establish general driven stability"
    },
    "source_event_count": 158845,
    "network_spike_count": 1005444,
    "wall_seconds_engine": 5.417907376002404,
    "core": {
      "kc_kc_mode": "thresholded",
      "released_edges": 1161917,
      "KC_fast_sign_corrected_edges": 0,
      "removed_KC_KC_edges": 234350,
      "removed_KC_KC_synapses": 234350,
      "effective_edges": 927567,
      "neurons": 13300,
      "mode": "all_spiking",
      "source_validation_sha256": "4484f1fabbf8f6f2e5957e57de9fee7a42503660d4b288b2115ca299aa5ca584",
      "base_artifact_hashes": {
        "neurons.parquet": "432901d18d2a5b44fd44dd558668589b81103344eeb8f44b2637cbd6b5f8889e",
        "graded_counts.npz": "4047d989ad4ad7d9f1d7f3a2296bf2cd8d5fc437bb9532bec57ee8c897d40b52",
        "spiking_counts.npz": "f9f1472572e6468324e8866d43c902939498cb62e5348beee33a4527ed3019b5",
        "reference_counts.npz": "830ecb2f50e56dccee482de41ff080c5b2b3e5e5539a6ad8a652a035acdadcb9",
        "sign_overrides.csv": "e8585667cf24271ca26d6c4ec9f1fa4294f280db388137f880412838fb222081"
      }
    },
    "coverage": {
      "requested_name": "MCH",
      "units": "a.u.",
      "value_meaning": "signed evoked consensus minus SFR",
      "mode": "door",
      "types": {
        "total_items": 53,
        "first_12": [
          "ORN_D",
          "ORN_DA1",
          "ORN_DA2",
          "ORN_DA3",
          "ORN_DA4l",
          "ORN_DA4m",
          "ORN_DC1",
          "ORN_DC2",
          "ORN_DC3",
          "ORN_DC4",
          "ORN_DL1",
          "ORN_DL2d"
        ],
        "note": "Full list in the linked JSON evidence."
      },
      "baseline_note": "Missing measurements give zero evoked delta, not measured silence. An independently measured SFR may still drive tonic activity; unmapped, ambiguous and untyped neurons get zero input.",
      "source_commit": "db323a496577c4b4a72b5c2fcd1859e07521ffb5",
      "label": "DoOR consensus",
      "chemical_name": "4-methylcyclohexanol",
      "CAS": "589-91-3",
      "InChIKey": "MQWCXKGKQLNYQG-UHFFFAOYSA-N",
      "status": {
        "total_items": 53,
        "first_12": [
          "measured_consensus",
          "missing_odor_measurement",
          "measured_consensus",
          "missing_odor_measurement",
          "missing_odor_measurement",
          "missing_odor_measurement",
          "measured_consensus",
          "measured_consensus",
          "measured_consensus",
          "missing_odor_measurement",
          "measured_consensus",
          "ambiguous_ac3A_split"
        ],
        "note": "Full list in the linked JSON evidence."
      },
      "raw_consensus_au": {
        "total_items": 53,
        "first_12": [
          0.635135135135135,
          null,
          0.339176173367663,
          null,
          null,
          null,
          0.0517759403323907,
          0.157418357276083,
          0.15668202764977,
          null,
          0.182335725095656,
          null
        ],
        "note": "Full list in the linked JSON evidence."
      },
      "spontaneous_au": {
        "total_items": 53,
        "first_12": [
          0.0,
          null,
          0.0648594697405211,
          0.0193166138419072,
          0.0952840397914614,
          0.0484519594259682,
          0.100068632791183,
          0.0798033726361042,
          0.0783410138248848,
          0.0,
          0.0516610256503943,
          0.0686498715043326
        ],
        "note": "Full list in the linked JSON evidence."
      },
      "baseline_input_au": {
        "total_items": 53,
        "first_12": [
          0.0,
          0.0,
          0.0648594697405211,
          0.0193166138419072,
          0.0952840397914614,
          0.0484519594259682,
          0.100068632791183,
          0.0798033726361042,
          0.0783410138248848,
          0.0,
          0.0516610256503943,
          0.0
        ],
        "note": "Full list in the linked JSON evidence."
      },
      "measured_named_types": 22,
      "named_types": 53,
      "named_type_coverage": 0.41509433962264153,
      "measured_neurons": 975,
      "total_orn_neurons": 2279,
      "neuron_coverage": 0.4278192189556823,
      "untyped_neurons": 4
    },
    "baseline_note": "Missing measurements give zero evoked delta, not measured silence. An independently measured SFR may still drive tonic activity; unmapped, ambiguous and untyped neurons get zero input.",
    "checkpoints": {
      "total_items": 25,
      "first_12": [
        {
          "t_ms": 100.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -153.17579986885517,
          "maximum_v_mV": 20.26650031087695,
          "maximum_abs_g_mV": 390.3823343352429
        },
        {
          "t_ms": 200.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -157.3699906571717,
          "maximum_v_mV": 21.498637186574776,
          "maximum_abs_g_mV": 311.0369809915921
        },
        {
          "t_ms": 300.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -158.0967509575383,
          "maximum_v_mV": 21.96658839264368,
          "maximum_abs_g_mV": 200.9645110020799
        },
        {
          "t_ms": 400.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -162.69573233492292,
          "maximum_v_mV": 18.362001808104345,
          "maximum_abs_g_mV": 293.87553224246096
        },
        {
          "t_ms": 500.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -159.0342372235785,
          "maximum_v_mV": 20.252064369457912,
          "maximum_abs_g_mV": 317.8022876795415
        },
        {
          "t_ms": 600.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -156.17662420793496,
          "maximum_v_mV": 21.315879073369622,
          "maximum_abs_g_mV": 346.8656116381203
        },
        {
          "t_ms": 700.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -162.38348190559287,
          "maximum_v_mV": 22.16882313559742,
          "maximum_abs_g_mV": 309.4787881928826
        },
        {
          "t_ms": 800.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -158.46270373447558,
          "maximum_v_mV": 19.370239573751405,
          "maximum_abs_g_mV": 277.4343439210642
        },
        {
          "t_ms": 900.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -157.6616629891033,
          "maximum_v_mV": 18.300665888398925,
          "maximum_abs_g_mV": 224.70023544522715
        },
        {
          "t_ms": 1000.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -159.76927154061045,
          "maximum_v_mV": 22.730496276223256,
          "maximum_abs_g_mV": 506.68774012704773
        },
        {
          "t_ms": 1100.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -159.9513860501517,
          "maximum_v_mV": 21.793901701082554,
          "maximum_abs_g_mV": 318.6427175922464
        },
        {
          "t_ms": 1200.0,
          "finite_voltage": true,
          "finite_synaptic_state": true,
          "minimum_v_mV": -159.1839042694275,
          "maximum_v_mV": 22.850222018543192,
          "maximum_abs_g_mV": 332.6058124609087
        }
      ],
      "note": "Full list in the linked JSON evidence."
    },
    "artifact_hashes": {
      "odour_sparseness_MCH_neurons.csv": "2d4ac88c4a17b2ac0f7bcba231b0467caecf7a387c588e5088d484b57dbf33bc",
      "odour_sparseness_MCH_types.csv": "25a73577479b97d2e325295612cc821d4e01df297f7f7af531181c1ecfe8a6ef",
      "odour_sparseness_MCH_activity.npz": "560909e8dbb8c958a7be254e949ee720e058bb65c3045109ee7261e5598fcd2d"
    }
  }
]
```

### V-NM-E evidence

[Complete recorded evidence](build/validation_neuromod_plasticity.json)

| Assertion | Expected | Observed | Status |
|---|---|---|---|
| twelve_point_reference_within_1e-3 | True | True | PASS |
| float32_matches_pinned_float64_within_2e-4 | True | True | PASS |
| float32_state | float32 | float32 | PASS |
| zero_reference_clamps | 0 | 0 | PASS |
| half_dt_reference_within_2e-4 | True | True | PASS |
| no_DA_throughout_history_no_association | 1.0 | 1.0 | PASS |
| no_KC_throughout_history_no_association | 1.0 | 1.0 | PASS |
| history_forward_depresses_backward_potentiates | True | True | PASS |
| current_zero_input_does_not_erase_trace_history | True | True | PASS |
| eta_decade_linear_unclipped | True | True | PASS |
| eta_decade_zero_clamps | 0 | 0 | PASS |
| lower_and_upper_bounds | [0.0, 2.0] | [0.0, 2.0] | PASS |
| clamps_and_absolute_change_are_logged | [1, 1, 1.0, 1.0] | [1, 1, 1.0, 1.0] | PASS |
| zero_input_forgetting_matches_analytic_not_invariance | True | True | PASS |
| unexposed_compartment_unchanged | True | True | PASS |
| actual_KC_MBON_edges | 62261 | 62261 | PASS |
| actual_KC_MBON_synapses | 256719 | 256719 | PASS |
| actual_KC_count | 5177 | 5177 | PASS |
| fifteen_compartment_rules | 15 | 15 | PASS |
| all_actual_edges_finite_and_bounded | True | True | PASS |
| actual_edge_fixture_zero_clamps | 0 | 0 | PASS |

**Fixture**

```json
{
  "identity": "Final brief Part III section 1: pinned normalized unit-gain float64 fixture",
  "source": "NEUROMOD_FINAL.md Part III section 1; supplied fixture, no fitting",
  "given": {
    "dt_ms": 1.0,
    "tau_clear_da_ms": 400.0,
    "tau_pre_ms": 600.0,
    "tau_da_trace_ms": 1500.0,
    "A1": 1.0,
    "A2": 0.55,
    "eta_per_ms": 0.00055,
    "w0": 1.0,
    "odor_onset_ms": 3000.0,
    "odor_duration_ms": 1000.0,
    "dopamine_duration_ms": 500.0,
    "horizon_ms": 7000.0,
    "kc_drive": 1.0,
    "dopamine_drive": 1.0,
    "tau_forget_ms": null
  },
  "unprovided_assumptions": {},
  "integration": "C, E_pre, E_da using NEW C, then weight using NEW traces; integer-grid pulses",
  "initial_state": "C=E_pre=E_da=0; w=w0=1",
  "units": "r and dr dimensionless [0,1]; traces and C a.u.; eta 1/ms; time ms",
  "historical_audit": "docs/neuromod_reference_findings.md describes superseded literal equations only"
}
```

### V-NM-A evidence

[Complete recorded evidence](build/validation_neuromod_receptors.json)

Disable-equivalence on the released all-LIF core, recurrent numerical fixtures and frozen-effect active adapter; not whole-brain hybrid or Layers 4/5 certification

| Assertion | Expected | Observed | Status |
|---|---|---|---|
| zero_C_identity_parameters | True | True | PASS |
| zero_C_history_channels | True | True | PASS |
| unit_C_default_guard_events | 0 | 0 | PASS |
| two_separate_dopamine_history_channels | ["da_before_kc", "kc_before_da"] | ["da_before_kc", "kc_before_da"] | PASS |
| plastic_edge_identity_count | 62261 | 62261 | PASS |
| Dop1R1_channel_negative | True | True | PASS |
| Dop1R2_channel_positive | True | True | PASS |
| numerical_magnitudes_assumption | True | True | PASS |
| expression_is_not_scRNA_measurement | True | True | PASS |
| disabled_exact_rest_part0 | True | True | PASS |
| disabled_exact_rest_part1 | True | True | PASS |
| disabled_exact_ORN_part0 | True | True | PASS |
| disabled_exact_ORN_part1 | True | True | PASS |
| disabled_exact_PN_part0 | True | True | PASS |
| disabled_exact_PN_part1 | True | True | PASS |
| disabled_exact_KC_part0 | True | True | PASS |
| disabled_exact_KC_part1 | True | True | PASS |
| disabled_exact_DAN_part0 | True | True | PASS |
| disabled_exact_DAN_part1 | True | True | PASS |
| disabled_exact_combined_part0 | True | True | PASS |
| disabled_exact_combined_part1 | True | True | PASS |
| disabled_battery_has_nonzero_spikes | True | True | PASS |
| active_no_current_at_rest | True | True | PASS |
| active_gain_changes_evoked_response | True | True | PASS |
| active_release_specific_postsynaptic_compartment | True | True | PASS |
| active_release_preserves_other_edge_scope | True | True | PASS |
| active_tau_transform | 0.9933555062550344 | 0.9933555062550344 | PASS |
| active_threshold_transform | -46.75 | -46.75 | PASS |
| active_threshold_changes_firing | True | True | PASS |
| guards_counted_and_outputs_bounded | True | True | PASS |
| kernel_normalization_linear | True | True | PASS |
| kernel_normalization_hill(1,1) | True | True | PASS |
| kernel_normalization_hill(2,0.5) | True | True | PASS |
| kernel_normalization_biphasic | True | True | PASS |
| unchanged_config_hashes_neuromod.yaml | 56d4fd1a1ed8de73398d9b672ffb1851fc7971d82fc5db9923db270ecad75cd8 | 56d4fd1a1ed8de73398d9b672ffb1851fc7971d82fc5db9923db270ecad75cd8 | PASS |
| unchanged_config_hashes_parameters.yaml | af489b36dbe1c330bbe9e5a772d262c740a62ea1e4a0ba3d551ca3a3e6955bdb | af489b36dbe1c330bbe9e5a772d262c740a62ea1e4a0ba3d551ca3a3e6955bdb | PASS |
| unchanged_config_hashes_receptors.csv | 048c94dcca5782c8d982018bdc2984f99b66fd67200e8e956722770db34cde64 | 048c94dcca5782c8d982018bdc2984f99b66fd67200e8e956722770db34cde64 | PASS |
| unchanged_implementation_hashes_src/flybrain/neuromod/receptors.py | 7ddf753c7a2a52021c26e28a22261916d385f5bf493f9954a40375e33d3c6d7b | 7ddf753c7a2a52021c26e28a22261916d385f5bf493f9954a40375e33d3c6d7b | PASS |
| unchanged_implementation_hashes_src/flybrain/neuromod/receptor_engine.py | 8a58417e516e4d5853dd4a9fd38da7afe179ec7386c38e8b923236fc511c2eb3 | 8a58417e516e4d5853dd4a9fd38da7afe179ec7386c38e8b923236fc511c2eb3 | PASS |
| unchanged_implementation_hashes_src/flybrain/engine.py | 087bc83a4602f12fd349b7a92ce4bdf9ce5e24663198247272cdfe15d45d5dc5 | 087bc83a4602f12fd349b7a92ce4bdf9ce5e24663198247272cdfe15d45d5dc5 | PASS |
| unchanged_implementation_hashes_src/flybrain/neuromod/core.py | 0e95f195ae487590cf7bf27ff88d7f6fae436edd9ae3900a3f12830abd12e2e2 | 0e95f195ae487590cf7bf27ff88d7f6fae436edd9ae3900a3f12830abd12e2e2 | PASS |
| unchanged_implementation_hashes_src/flybrain/neuromod/field.py | e37337469fcd92580ea742024afd8debab96f2edabffb38f7c2c83d6e1b3e629 | e37337469fcd92580ea742024afd8debab96f2edabffb38f7c2c83d6e1b3e629 | PASS |
| unchanged_dependency_hashes_build/validation_neuromod_sources.json | 3e140e86db7e81463f25e7b3d4670c5acca0f7df92b2a9185c08f7475be8b7d8 | 3e140e86db7e81463f25e7b3d4670c5acca0f7df92b2a9185c08f7475be8b7d8 | PASS |
| unchanged_dependency_hashes_build/validation_neuromod_compartments.json | ec954a5ce9a0ef0ef1589457e8e8041d27f7aafcd906f80b5f8c25be6fc0d7af | ec954a5ce9a0ef0ef1589457e8e8041d27f7aafcd906f80b5f8c25be6fc0d7af | PASS |
| unchanged_dependency_hashes_build/validation_neuromod_field.json | 803c0d3935727356a211c7c678572c6fef5e219e59affca5ff39ad9f32bd13a0 | 803c0d3935727356a211c7c678572c6fef5e219e59affca5ff39ad9f32bd13a0 | PASS |
| unchanged_dependency_hashes_build/compartments.npz | ca6b5db397f57e8c5d809c3fc398b49dee371cc709e5444711e15b7ce36500b5 | ca6b5db397f57e8c5d809c3fc398b49dee371cc709e5444711e15b7ce36500b5 | PASS |
| unchanged_dependency_hashes_build/neurons.parquet | 432901d18d2a5b44fd44dd558668589b81103344eeb8f44b2637cbd6b5f8889e | 432901d18d2a5b44fd44dd558668589b81103344eeb8f44b2637cbd6b5f8889e | PASS |

**Notes**

```json
[
  "Source-correct OAMB/PAM and mAChR-A/KC rows are active; requested Octbeta2R/PAM and mAChR-B/KC rows remain disabled assumptions because their cited receptor identities differ.",
  "All expression coverage, numerical magnitudes, kernel shapes and bounds are ASSUMPTION. No single-cell RNA measurement was used.",
  "Effects are frozen over each run; callers can update at field boundaries. No autonomous field-network feedback scheduler is certified here.",
  "Separate Dop1R1/Dop1R2 history channels are emitted for Layer 4; this stage does not integrate eligibility traces or change weights."
]
```

**Disabled equivalence**

```json
{
  "core_neurons": 13300,
  "core_edges": 1161917,
  "clamping": false,
  "dt_ms": 0.1,
  "trials": [
    {
      "stimulus": "rest",
      "part": 0,
      "duration_ms": 4.3,
      "input_neurons": [],
      "spikes": 0,
      "exact_spikes_voltages_state_pending_delays": true
    },
    {
      "stimulus": "rest",
      "part": 1,
      "duration_ms": 5.7,
      "input_neurons": [],
      "spikes": 0,
      "exact_spikes_voltages_state_pending_delays": true
    },
    {
      "stimulus": "ORN",
      "part": 0,
      "duration_ms": 4.3,
      "input_neurons": [
        25,
        27,
        38,
        56
      ],
      "spikes": 12,
      "exact_spikes_voltages_state_pending_delays": true
    },
    {
      "stimulus": "ORN",
      "part": 1,
      "duration_ms": 5.7,
      "input_neurons": [
        25,
        27,
        38,
        56
      ],
      "spikes": 12,
      "exact_spikes_voltages_state_pending_delays": true
    },
    {
      "stimulus": "PN",
      "part": 0,
      "duration_ms": 4.3,
      "input_neurons": [
        21,
        28,
        29,
        30
      ],
      "spikes": 12,
      "exact_spikes_voltages_state_pending_delays": true
    },
    {
      "stimulus": "PN",
      "part": 1,
      "duration_ms": 5.7,
      "input_neurons": [
        21,
        28,
        29,
        30
      ],
      "spikes": 14,
      "exact_spikes_voltages_state_pending_delays": true
    },
    {
      "stimulus": "KC",
      "part": 0,
      "duration_ms": 4.3,
      "input_neurons": [
        1,
        2,
        3,
        7
      ],
      "spikes": 12,
      "exact_spikes_voltages_state_pending_delays": true
    },
    {
      "stimulus": "KC",
      "part": 1,
      "duration_ms": 5.7,
      "input_neurons": [
        1,
        2,
        3,
        7
      ],
      "spikes": 14,
      "exact_spikes_voltages_state_pending_delays": true
    },
    {
      "stimulus": "DAN",
      "part": 0,
      "duration_ms": 4.3,
      "input_neurons": [
        124,
        159,
        175,
        213
      ],
      "spikes": 12,
      "exact_spikes_voltages_state_pending_delays": true
    },
    {
      "stimulus": "DAN",
      "part": 1,
      "duration_ms": 5.7,
      "input_neurons": [
        124,
        159,
        175,
        213
      ],
      "spikes": 12,
      "exact_spikes_voltages_state_pending_delays": true
    },
    {
      "stimulus": "combined",
      "part": 0,
      "duration_ms": 4.3,
      "input_neurons": {
        "total_items": 16,
        "first_12": [
          1,
          2,
          3,
          7,
          21,
          25,
          27,
          28,
          29,
          30,
          38,
          56
        ],
        "note": "Full list in the linked JSON evidence."
      },
      "spikes": 48,
      "exact_spikes_voltages_state_pending_delays": true
    },
    {
      "stimulus": "combined",
      "part": 1,
      "duration_ms": 5.7,
      "input_neurons": {
        "total_items": 16,
        "first_12": [
          1,
          2,
          3,
          7,
          21,
          25,
          27,
          28,
          29,
          30,
          38,
          56
        ],
        "note": "Full list in the linked JSON evidence."
      },
      "spikes": 53,
      "exact_spikes_voltages_state_pending_delays": true
    }
  ],
  "scope": "Six fixed core stimulus cases with two continuation calls each; no whole-brain or visual battery claim"
}
```

**Active fixtures**

```json
{
  "gain_baseline_spikes": 0,
  "gain_active_spikes": 1,
  "excess_signal_guard_events": {
    "signal": 1,
    "gain": 1,
    "threshold_factor": 0,
    "tau_factor": 0,
    "release": 0
  },
  "interpretation": "Explicit diagnostic coefficients; not biology, sensitivity-sweep, visual or dynamic-feedback gate results"
}
```

**5ht al scope**

```json
{
  "shared_target_neurons": 14,
  "mechanism": "CSD shares AL_unresolved with GABA-positive ALLNs; 5HT7 raises assumed LN gain, then existing signed LN->PN edges carry inhibition. No fabricated broadcast to named glomeruli and no DPM->MB claim."
}
```

**Core target coverage**

```json
{
  "total_items": 13,
  "first_12": [
    {
      "id": "DA_Dop1R1_forward",
      "enabled": true,
      "target_neurons": 5177,
      "target_edges": 62261,
      "target_neurons_without_volume": 0,
      "target_edges_without_empirical_compartment": 0,
      "expression_provenance": "ASSUMPTION"
    },
    {
      "id": "DA_Dop1R2_backward",
      "enabled": true,
      "target_neurons": 5177,
      "target_edges": 62261,
      "target_neurons_without_volume": 0,
      "target_edges_without_empirical_compartment": 0,
      "expression_provenance": "ASSUMPTION"
    },
    {
      "id": "DA_Dop2R_gain",
      "enabled": true,
      "target_neurons": 337,
      "target_edges": 0,
      "target_neurons_without_volume": 4,
      "target_edges_without_empirical_compartment": 0,
      "expression_provenance": "ASSUMPTION"
    },
    {
      "id": "DA_Dop2R_release_prob",
      "enabled": true,
      "target_neurons": 337,
      "target_edges": 53160,
      "target_neurons_without_volume": 4,
      "target_edges_without_empirical_compartment": 0,
      "expression_provenance": "ASSUMPTION"
    },
    {
      "id": "OA_OAMB_PAM",
      "enabled": true,
      "target_neurons": 307,
      "target_edges": 0,
      "target_neurons_without_volume": 0,
      "target_edges_without_empirical_compartment": 0,
      "expression_provenance": "ASSUMPTION"
    },
    {
      "id": "OA_Octbeta2R_PAM_requested",
      "enabled": false,
      "target_neurons": 307,
      "target_edges": 0,
      "target_neurons_without_volume": 0,
      "target_edges_without_empirical_compartment": 0,
      "expression_provenance": "ASSUMPTION"
    },
    {
      "id": "OA_VS_gain",
      "enabled": true,
      "target_neurons": 0,
      "target_edges": 0,
      "target_neurons_without_volume": 0,
      "target_edges_without_empirical_compartment": 0,
      "expression_provenance": "ASSUMPTION"
    },
    {
      "id": "OA_HS_gain",
      "enabled": true,
      "target_neurons": 0,
      "target_edges": 0,
      "target_neurons_without_volume": 0,
      "target_edges_without_empirical_compartment": 0,
      "expression_provenance": "ASSUMPTION"
    },
    {
      "id": "OA_HSVS_tau",
      "enabled": true,
      "target_neurons": 0,
      "target_edges": 0,
      "target_neurons_without_volume": 0,
      "target_edges_without_empirical_compartment": 0,
      "expression_provenance": "ASSUMPTION"
    },
    {
      "id": "ACh_mAChRA_KC",
      "enabled": true,
      "target_neurons": 5177,
      "target_edges": 0,
      "target_neurons_without_volume": 0,
      "target_edges_without_empirical_compartment": 0,
      "expression_provenance": "ASSUMPTION"
    },
    {
      "id": "ACh_mAChRB_KC_requested",
      "enabled": false,
      "target_neurons": 5177,
      "target_edges": 0,
      "target_neurons_without_volume": 0,
      "target_edges_without_empirical_compartment": 0,
      "expression_provenance": "ASSUMPTION"
    },
    {
      "id": "sNPF_sNPFR_KC_release",
      "enabled": true,
      "target_neurons": 5177,
      "target_edges": 62261,
      "target_neurons_without_volume": 0,
      "target_edges_without_empirical_compartment": 0,
      "expression_provenance": "ASSUMPTION"
    }
  ],
  "note": "Full list in the linked JSON evidence."
}
```

### V-NM-B evidence

[Complete recorded evidence](build/validation_neuromod_runtime.json)

Identical seed and full control event list; every spike and final weight hashed


### V-NM-F' evidence

[Complete recorded evidence](build/validation_neuromod_runtime.json)


### V-NM-C evidence

[Complete recorded evidence](build/validation_neuromod_sources.json)

| Assertion | Expected | Observed | Status |
|---|---|---|---|
| prerequisite_V-A | PASS | PASS | PASS |
| prerequisite_base_build | PASS | PASS | PASS |
| base_neuron_row_order | True | True | PASS |
| annotation_empty_known_nt | 51411 | 51411 | PASS |
| audit_acetylcholine | [52053, 86193, 44999] | [52053, 86193, 44999] | PASS |
| audit_gaba | [9089, 19171, 7438] | [9089, 19171, 7438] | PASS |
| audit_glutamate | [11378, 24875, 9139] | [11378, 24875, 9139] | PASS |
| audit_dopamine | [1395, 5909, 381] | [1395, 5909, 381] | PASS |
| audit_octopamine | [68, 216, 39] | [68, 216, 39] | PASS |
| audit_serotonin | [197, 2282, 18] | [197, 2282, 18] | PASS |
| audit_tyramine | [104, 0, 0] | [104, 0, 0] | PASS |
| audit_histamine | [11129, 0, 0] | [11129, 0, 0] | PASS |
| block_ORN_neurons | 2279 | 2279 | PASS |
| block_ORN_left | 1116 | 1116 | PASS |
| block_ORN_right | 1133 | 1133 | PASS |
| block_ORN_named_types | 53 | 53 | PASS |
| block_ORN_untyped | 4 | 4 | PASS |
| block_PN_neurons | 685 | 685 | PASS |
| block_PN_left | 341 | 341 | PASS |
| block_PN_right | 344 | 344 | PASS |
| block_PN_named_types | 182 | 182 | PASS |
| block_PN_untyped | 0 | 0 | PASS |
| block_ALLN_neurons | 429 | 429 | PASS |
| block_ALLN_left | 214 | 214 | PASS |
| block_ALLN_right | 213 | 213 | PASS |
| block_ALLN_named_types | 94 | 94 | PASS |
| block_ALLN_untyped | 1 | 1 | PASS |
| block_KC_neurons | 5177 | 5177 | PASS |
| block_KC_left | 2580 | 2580 | PASS |
| block_KC_right | 2597 | 2597 | PASS |
| block_KC_named_types | 11 | 11 | PASS |
| block_KC_untyped | 0 | 0 | PASS |
| block_MBON_neurons | 96 | 96 | PASS |
| block_MBON_left | 48 | 48 | PASS |
| block_MBON_right | 48 | 48 | PASS |
| block_MBON_named_types | 35 | 35 | PASS |
| block_MBON_untyped | 0 | 0 | PASS |
| block_DAN_neurons | 337 | 337 | PASS |
| block_DAN_left | 169 | 169 | PASS |
| block_DAN_right | 168 | 168 | PASS |
| block_DAN_named_types | 30 | 30 | PASS |
| block_DAN_untyped | 0 | 0 | PASS |
| block_APL_DPM_neurons | 4 | 4 | PASS |
| block_APL_DPM_left | 2 | 2 | PASS |
| block_APL_DPM_right | 2 | 2 | PASS |
| block_APL_DPM_named_types | 2 | 2 | PASS |
| block_APL_DPM_untyped | 0 | 0 | PASS |
| block_OA_named_neurons | 43 | 43 | PASS |
| block_OA_named_left | 15 | 15 | PASS |
| block_OA_named_right | 15 | 15 | PASS |
| block_OA_named_named_types | 18 | 18 | PASS |
| block_OA_named_untyped | 0 | 0 | PASS |
| block_CSD_neurons | 2 | 2 | PASS |
| block_CSD_left | 1 | 1 | PASS |
| block_CSD_right | 1 | 1 | PASS |
| block_CSD_named_types | 1 | 1 | PASS |
| block_CSD_untyped | 0 | 0 | PASS |
| block_CX_neurons | 2875 | 2875 | PASS |
| block_CX_left | 1438 | 1438 | PASS |
| block_CX_right | 1437 | 1437 | PASS |
| block_CX_named_types | 229 | 229 | PASS |
| block_CX_untyped | 9 | 9 | PASS |
| block_DN_neurons | 1299 | 1299 | PASS |
| block_DN_left | 645 | 645 | PASS |
| block_DN_right | 646 | 646 | PASS |
| block_DN_named_types | 472 | 472 | PASS |
| block_DN_untyped | 0 | 0 | PASS |
| block_endocrine_neurons | 76 | 76 | PASS |
| block_endocrine_left | 37 | 37 | PASS |
| block_endocrine_right | 39 | 39 | PASS |
| block_endocrine_named_types | 10 | 10 | PASS |
| block_endocrine_untyped | 0 | 0 | PASS |
| ORN_PN_disjoint | 0 | 0 | PASS |
| DAN_annotation_per_type | {"PAM01": 41, "PAM02": 16, "PAM03": 10, "PAM04": 32, "PAM05": 21, "PAM06": 30, "PAM07": 18, "PAM08": 45, "PAM09": 9, "PAM10": 15, "PAM11": 16, "PAM12": 23, "PAM13": 12, "PAM14": 16, "PAM15": 3, "PPL101": 2, "PPL102": 2, "PPL103": 2, "PPL104": 2, "PPL105": 2, "PPL106": 2, "PPL107": 2, "PPL108": 2, "PPL201": 2, "PPL202": 2, "PPL203": 2, "PPL204": 2, "PAL01": 2, "PAL02": 2, "PAL03": 2} | {"PAM08": 45, "PAM01": 41, "PAM04": 32, "PAM06": 30, "PAM12": 23, "PAM05": 21, "PAM07": 18, "PAM11": 16, "PAM14": 16, "PAM02": 16, "PAM10": 15, "PAM13": 12, "PAM03": 10, "PAM09": 9, "PAM15": 3, "PPL107": 2, "PPL204": 2, "PPL105": 2, "PPL108": 2, "PAL01": 2, "PPL103": 2, "PPL202": 2, "PAL03": 2, "PPL101": 2, "PPL203": 2, "PPL106": 2, "PPL102": 2, "PPL201": 2, "PAL02": 2, "PPL104": 2} | PASS |
| DAN_PAM | 307 | 307 | PASS |
| DAN_PPL1 | 16 | 16 | PASS |
| DAN_PPL2 | 8 | 8 | PASS |
| DAN_PAL | 6 | 6 | PASS |
| all_MB_DAN_positive_dopamine | 337 | 337 | PASS |
| dopamine_super_classes | {"optic": 980, "central": 408, "visual_centrifugal": 7} | {"optic": 980, "central": 408, "visual_centrifugal": 7} | PASS |
| MB_DAN_nitric_oxide_per_neuron_counts | {"PAM01": 40, "PAM05": 20, "PAM06": 2, "PPL101": 2, "PPL103": 2} | {"PAM01": 40, "PAM05": 20, "PAM06": 2, "PPL103": 2, "PPL101": 2} | PASS |
| endocrine_annotation | 80 | 80 | PASS |
| OA-AL2b2_neurons | 4 | 4 | PASS |
| OA-AL2b2_octopamine_sources | 0 | 0 | PASS |
| OA-AL2b2_tyramine_sources | 4 | 4 | PASS |
| KC_known_acetylcholine | 5177 | 5177 | PASS |
| KC_predicted_dopamine | 5172 | 5172 | PASS |
| defect_D_override_rows | 5177 | 5177 | PASS |
| KC_aminergic_sources | 0 | 0 | PASS |
| KC_sNPF_sources | 4133 | 4133 | PASS |
| brain_sNPF_sources | 5034 | 5034 | PASS |
| motif_KC->MBON | [62261, 256719, 3] | [62261, 256719, 3.0] | PASS |
| motif_KC->DAN | [81057, 125134, 1] | [81057, 125134, 1.0] | PASS |
| motif_DAN->KC | [47404, 60657, 1] | [47404, 60657, 1.0] | PASS |
| motif_KC->APL_DPM | [10390, 204929, 19] | [10390, 204929, 19.0] | PASS |
| motif_APL_DPM->KC | [9251, 107934, 12] | [9251, 107934, 12.0] | PASS |
| motif_MBON->MBON | [1343, 19983, 3] | [1343, 19983, 3.0] | PASS |
| motif_MBON->DAN | [2383, 9009, 2] | [2383, 9009, 2.0] | PASS |
| motif_DAN->MBON | [2035, 15325, 3] | [2035, 15325, 3.0] | PASS |
| motif_APL_DPM->MBON | [193, 6910, 11] | [193, 6910, 11.0] | PASS |
| motif_PN->KC | [27848, 329394, 11] | [27848, 329394, 11.0] | PASS |
| motif_KC->KC | [293762, 379338, 1] | [293762, 379338, 1.0] | PASS |
| core_neurons | 13300 | 13300 | PASS |
| core_edges | 1161917 | 1161917 | PASS |
| core_synapses | 4581576 | 4581576 | PASS |
| core_block_sum | 13302 | 13302 | PASS |
| core_overlap_membership | [{"blocks": ["ALLN", "OA_named"], "neurons": 2, "cell_types": {"OA-VUMa5": 2}}] | [{"blocks": ["ALLN", "OA_named"], "neurons": 2, "cell_types": {"OA-VUMa5": 2}}] | PASS |
| source_unchanged_Completeness_783.csv | {"size": 3327347, "mtime_ns": 1790353217275849803, "ctime_ns": 1790353217275849803, "inode": 109914551} | {"size": 3327347, "mtime_ns": 1790353217275849803, "ctime_ns": 1790353217275849803, "inode": 109914551} | PASS |
| source_unchanged_Connectivity_783.parquet | {"size": 100804642, "mtime_ns": 1790353264459881910, "ctime_ns": 1790353264459881910, "inode": 109914552} | {"size": 100804642, "mtime_ns": 1790353264459881910, "ctime_ns": 1790353264459881910, "inode": 109914552} | PASS |
| source_unchanged_Supplemental_file1_neuron_annotations.tsv | {"size": 31718505, "mtime_ns": 1790353227286969943, "ctime_ns": 1790353227286969943, "inode": 109914547} | {"size": 31718505, "mtime_ns": 1790353227286969943, "ctime_ns": 1790353227286969943, "inode": 109914547} | PASS |
| base_artifact_unchanged_neurons.parquet | 432901d18d2a5b44fd44dd558668589b81103344eeb8f44b2637cbd6b5f8889e | 432901d18d2a5b44fd44dd558668589b81103344eeb8f44b2637cbd6b5f8889e | PASS |
| base_artifact_unchanged_graded_counts.npz | 4047d989ad4ad7d9f1d7f3a2296bf2cd8d5fc437bb9532bec57ee8c897d40b52 | 4047d989ad4ad7d9f1d7f3a2296bf2cd8d5fc437bb9532bec57ee8c897d40b52 | PASS |
| base_artifact_unchanged_spiking_counts.npz | f9f1472572e6468324e8866d43c902939498cb62e5348beee33a4527ed3019b5 | f9f1472572e6468324e8866d43c902939498cb62e5348beee33a4527ed3019b5 | PASS |
| base_artifact_unchanged_reference_counts.npz | 830ecb2f50e56dccee482de41ff080c5b2b3e5e5539a6ad8a652a035acdadcb9 | 830ecb2f50e56dccee482de41ff080c5b2b3e5e5539a6ad8a652a035acdadcb9 | PASS |
| base_artifact_unchanged_sign_overrides.csv | e8585667cf24271ca26d6c4ec9f1fa4294f280db388137f880412838fb222081 | e8585667cf24271ca26d6c4ec9f1fa4294f280db388137f880412838fb222081 | PASS |

**Transmitter-prediction audit (full annotation table)**

| Transmitter | Positive known_nt | Predicted top_nt | Agree | Ground truth recovered |
|---|---:|---:|---:|---:|
| acetylcholine | 52,053 | 86,193 | 44,999 | 86.4% |
| gaba | 9,089 | 19,171 | 7,438 | 81.8% |
| glutamate | 11,378 | 24,875 | 9,139 | 80.3% |
| dopamine | 1,395 | 5,909 | 381 | 27.3% |
| octopamine | 68 | 216 | 39 | 57.4% |
| serotonin | 197 | 2,282 | 18 | 9.1% |
| tyramine | 104 | 0 | 0 | 0.0% |
| histamine | 11,129 | 0 | 0 | 0.0% |

**Inventory**

```json
{
  "PN": {
    "neurons": 685,
    "named_types": 182,
    "type_categories": 182,
    "types": 182,
    "untyped": 0,
    "left": 341,
    "right": 344,
    "side_counts": {
      "right": 344,
      "left": 341
    },
    "selection": "cell_class == 'ALPN'"
  },
  "ALLN": {
    "neurons": 429,
    "named_types": 94,
    "type_categories": 95,
    "types": 95,
    "untyped": 1,
    "left": 214,
    "right": 213,
    "side_counts": {
      "left": 214,
      "right": 213,
      "center": 2
    },
    "selection": "cell_class == 'ALLN'"
  },
  "CX": {
    "neurons": 2875,
    "named_types": 229,
    "type_categories": 230,
    "types": 230,
    "untyped": 9,
    "left": 1438,
    "right": 1437,
    "side_counts": {
      "left": 1438,
      "right": 1437
    },
    "selection": "cell_class == 'CX'"
  },
  "ORN": {
    "neurons": 2279,
    "named_types": 53,
    "type_categories": 54,
    "types": 54,
    "untyped": 4,
    "left": 1116,
    "right": 1133,
    "side_counts": {
      "right": 1133,
      "left": 1116,
      "na": 30
    },
    "selection": "(cell_class == 'olfactory') & (super_class == 'sensory')"
  },
  "KC": {
    "neurons": 5177,
    "named_types": 11,
    "type_categories": 11,
    "types": 11,
    "untyped": 0,
    "left": 2580,
    "right": 2597,
    "side_counts": {
      "right": 2597,
      "left": 2580
    },
    "selection": "cell_type.startswith('KC')"
  },
  "MBON": {
    "neurons": 96,
    "named_types": 35,
    "type_categories": 35,
    "types": 35,
    "untyped": 0,
    "left": 48,
    "right": 48,
    "side_counts": {
      "right": 48,
      "left": 48
    },
    "selection": "cell_type.startswith('MBON')"
  },
  "DAN": {
    "neurons": 337,
    "named_types": 30,
    "type_categories": 30,
    "types": 30,
    "untyped": 0,
    "left": 169,
    "right": 168,
    "side_counts": {
      "left": 169,
      "right": 168
    },
    "selection": "cell_type.startswith(('PAM', 'PPL1', 'PPL2', 'PAL'))"
  },
  "APL_DPM": {
    "neurons": 4,
    "named_types": 2,
    "type_categories": 2,
    "types": 2,
    "untyped": 0,
    "left": 2,
    "right": 2,
    "side_counts": {
      "right": 2,
      "left": 2
    },
    "selection": "cell_type.startswith(('APL', 'DPM'))"
  },
  "OA_named": {
    "neurons": 43,
    "named_types": 18,
    "type_categories": 18,
    "types": 18,
    "untyped": 0,
    "left": 15,
    "right": 15,
    "side_counts": {
      "right": 15,
      "left": 15,
      "center": 13
    },
    "selection": "cell_type.startswith(('OA-', 'VPM', 'VUM'))"
  },
  "CSD": {
    "neurons": 2,
    "named_types": 1,
    "type_categories": 1,
    "types": 1,
    "untyped": 0,
    "left": 1,
    "right": 1,
    "side_counts": {
      "left": 1,
      "right": 1
    },
    "selection": "cell_type.startswith('CSD')"
  },
  "DN": {
    "neurons": 1299,
    "named_types": 472,
    "type_categories": 472,
    "types": 472,
    "untyped": 0,
    "left": 645,
    "right": 646,
    "side_counts": {
      "right": 646,
      "left": 645,
      "center": 8
    },
    "selection": "super_class == 'descending'"
  },
  "endocrine": {
    "neurons": 76,
    "named_types": 10,
    "type_categories": 10,
    "types": 10,
    "untyped": 0,
    "left": 37,
    "right": 39,
    "side_counts": {
      "right": 39,
      "left": 37
    },
    "selection": "super_class == 'endocrine'"
  }
}
```

**Motifs**

```json
{
  "KC->MBON": {
    "edges": 62261,
    "synapses": 256719,
    "median_synapses_per_edge": 3.0
  },
  "KC->DAN": {
    "edges": 81057,
    "synapses": 125134,
    "median_synapses_per_edge": 1.0
  },
  "DAN->KC": {
    "edges": 47404,
    "synapses": 60657,
    "median_synapses_per_edge": 1.0
  },
  "KC->APL_DPM": {
    "edges": 10390,
    "synapses": 204929,
    "median_synapses_per_edge": 19.0
  },
  "APL_DPM->KC": {
    "edges": 9251,
    "synapses": 107934,
    "median_synapses_per_edge": 12.0
  },
  "MBON->MBON": {
    "edges": 1343,
    "synapses": 19983,
    "median_synapses_per_edge": 3.0
  },
  "MBON->DAN": {
    "edges": 2383,
    "synapses": 9009,
    "median_synapses_per_edge": 2.0
  },
  "DAN->MBON": {
    "edges": 2035,
    "synapses": 15325,
    "median_synapses_per_edge": 3.0
  },
  "APL_DPM->MBON": {
    "edges": 193,
    "synapses": 6910,
    "median_synapses_per_edge": 11.0
  },
  "PN->KC": {
    "edges": 27848,
    "synapses": 329394,
    "median_synapses_per_edge": 11.0
  },
  "KC->KC": {
    "edges": 293762,
    "synapses": 379338,
    "median_synapses_per_edge": 1.0,
    "threshold_2_edges": 59412,
    "threshold_2_synapses": 144988
  }
}
```

**Core**

```json
{
  "neurons": 13300,
  "edges": 1161917,
  "synapses": 4581576,
  "selection": "deduplicated union of the explicit block selections",
  "csr_float32_int32_bytes": 9348540,
  "block_sum": 13302,
  "overlaps": [
    {
      "blocks": [
        "ALLN",
        "OA_named"
      ],
      "neurons": 2,
      "cell_types": {
        "OA-VUMa5": 2
      },
      "root_ids": [
        720575940626741552,
        720575940628861188
      ]
    }
  ]
}
```

**Mb dan nitric oxide counts**

```json
{
  "PAM01": 40,
  "PAM05": 20,
  "PAM06": 2,
  "PPL103": 2,
  "PPL101": 2
}
```

**Notes**

```json
[
  "Named types, named plus unknown category, and untyped neurons are counted separately.",
  "All annotation source rows are retained; model_index=-1 means outside Completeness.",
  "Patch 1 preserves KC sNPF independently while excluding every KC from aminergic sources.",
  "Population-reference differences warn and proceed using the normative selector; primary-data differences fail.",
  "Source acceptance does not certify a runnable or validated simulation engine."
]
```

### Historical equation preflight

This audit records the original specification. The final brief explicitly supersedes its equation with the normalized rule validated by current V-NM-E. Using the explicit diagnostic assumptions (10 Hz KC activity, no forgetting, 30 s horizon), the written trace equations differ from the supplied table by up to **0.076736421** against its **0.001** tolerance. Normalizing both trace equations reduces the error to **0.000155333**, but changes the specified equations and eta units. No alternative was silently adopted.

[Method, all twelve values, convergence and history/forgetting conflicts](docs/neuromod_reference_findings.md).

Measured real-time factor: **0.635 model s / wall s (FAIL)**. Network pairing-curve crossover: **no sign crossing observed**.
[Coupled runtime, console, recording and interpretation](docs/live_console.md). Executed software and biological measurements have separate gates; absent measurements remain NOT-RUN. V-NM-I remains NOT-RUN pending base V-G/V-H. Body readout remains NOT-RUN without a validated motor decoder.


### Separate normalized whole-brain stability variant

Overall current status: **PASS**. Original base V-C evidence remains unchanged.

| Synaptic model | Gate | Status | Measurement |
|---|---|---|---|
| current | V-C1 | PASS | {"relative_residual": 8.829490945238767e-07} |
| current | V-C2 | PASS | {"slope_per_ms": -0.007765517082227528, "tau_net_ms": 128.77442537453686} |
| current | V-C3 | PASS | {"clamp_count": 0} |
| current | V-C4 | PASS | {"max_perturbed_endpoint_difference_mV": 1.95027638483225e-09} |
| conductance | V-C1 | PASS | {"relative_residual": 9.938045903944686e-07} |
| conductance | V-C2 | PASS | {"slope_per_ms": -0.010026959721659921, "tau_net_ms": 99.73112765575708} |
| conductance | V-C3 | PASS | {"clamp_count": 0} |
| conductance | V-C4 | PASS | {"max_perturbed_endpoint_difference_mV": 2.7036151095671812e-11} |

[Methods and limits](docs/hybrid_stability_variant.md); [complete evidence](build/validation_hybrid_variant.json). Additional normalization and kappa sweeps have fixed-point/spectral evidence only; dynamic sweeps are NOT-RUN.

### Measured write-handle capacity

Current result: **PASS**. [Complete trial, null and confidence-interval evidence](build/validation_neuromod_capacity.json). Inferred MBON readout, short-protocol power, unknown driver-line access and saturation limits remain explicit.

Measured **92 handles** and **736 held-out trials**. Per-handle information ranged from **0 to 0 bits per observation**; **0** survived BH correction at q < 0.05. PASS here certifies execution and provenance, not successful biological writing.

NOT-ESTABLISHED: bounded N=2, M=2 task does not identify saturation over task complexity or handle combinations

### Measured figures

![Normalized isolated reference fixture](build/neuromod_figures/plasticity_reference.png)

![Measured closed-loop pairing curve](build/neuromod_figures/network_pairing.png)

![Separate whole-brain perturbation recovery](build/neuromod_figures/wholebrain_stability.png)

![Measured bounded-task information curve](build/neuromod_figures/capacity_curve.png)

![Per-handle information with uncertainty](build/neuromod_figures/capacity_per_handle.png)
