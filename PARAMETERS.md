# Parameter provenance

Sweep values are predeclared candidates. Only runs with saved evidence in REPORT.md were executed; a listed candidate is not a completed experiment.

| Parameter | Value | Unit | Source | Planned sensitivity values |
|---|---|---|---|---|
| dt | 0.1 | ms | ASSUMPTION | [0.05, 0.1] |
| dt_graded | 0.5 | ms | ASSUMPTION | [0.1, 0.5] |
| v_rest | -52.0 | mV | DOI:10.1038/s41586-024-07763-9; released model.py v_0 | — |
| v_reset | -52.0 | mV | DOI:10.1038/s41586-024-07763-9; released model.py v_rst | — |
| v_threshold | -45.0 | mV | DOI:10.1038/s41586-024-07763-9; released model.py v_th | — |
| tau_membrane | 20.0 | ms | DOI:10.1038/s41586-024-07763-9; released model.py t_mbr | — |
| tau_synapse | 5.0 | ms | DOI:10.1038/s41586-024-07763-9; released model.py tau | — |
| refractory | 2.2 | ms | DOI:10.1038/s41586-024-07763-9; released model.py t_rfc | — |
| synaptic_delay | 1.8 | ms | DOI:10.1038/s41586-024-07763-9; released model.py t_dly | — |
| spike_weight | 0.275 | mV/synapse | DOI:10.1038/s41586-024-07763-9; released model.py w_syn (free parameter of reference) | — |
| poisson_rate | 150.0 | Hz | DOI:10.1038/s41586-024-07763-9; reference cross-check only | — |
| poisson_factor | 250.0 | dimensionless | DOI:10.1038/s41586-024-07763-9; reference cross-check only | — |
| graded_tau_membrane | 20.0 | ms | ASSUMPTION | [10.0, 20.0, 40.0] |
| graded_tau_synapse | 5.0 | ms | ASSUMPTION | [2.5, 5.0, 10.0] |
| graded_rest | -52.0 | mV | ASSUMPTION | [-55.0, -52.0, -49.0] |
| graded_release | -54.0 | mV | ASSUMPTION | [-56.0, -54.0, -53.0] |
| graded_gain | 0.0001 | 1/(ms*synapse) | ASSUMPTION | [3e-05, 0.0001, 0.0003] |
| voltage_min | -90.0 | mV | ASSUMPTION | [-100.0, -90.0] |
| voltage_max | 20.0 | mV | ASSUMPTION | [10.0, 20.0] |
| pre_equilibration | 1000.0 | ms | ASSUMPTION | [1000.0, 2000.0] |
| stationary_tolerance | 0.001 | mV/ms | ASSUMPTION | [0.0005, 0.001, 0.002] |
| frame_rate | 240.0 | Hz | ASSUMPTION | [120.0, 240.0, 480.0] |
| eye_spacing | 5.1 | degrees | DOI:10.1016/j.neuron.2011.05.023 | — |
| eye_fwhm | 5.7 | degrees | DOI:10.1016/j.neuron.2011.05.023 | — |
| seed | 783 | integer | ASSUMPTION | [783, 784, 785] |

## Neuromodulation parameters

Generated from config/neuromod.yaml. Candidate sweeps are not completed sensitivity experiments. No eligibility parameters have been fitted to published data.

| Parameter | Value | Unit | Source | Sweep candidates | Notes / fit data |
|---|---|---|---|---|---|
| dt_base_ms | 0.1 | ms | ASSUMPTION | [0.05, 0.1] | Matches unchanged base integrator timestep; not a performance shortcut. |
| dt_mod_ms | 1.0 | ms | ASSUMPTION | [0.5, 1.0] | Integer multiple of base timestep. |
| concentration_max_au | 5.0 | a.u. | ASSUMPTION | [2.5, 5.0, 10.0] | Numerical guard; every activated clamp is counted. |
| tau_clear_ms_DA | 400.0 | ms | ASSUMPTION | [200.0, 400.0, 800.0] | DA400 is the supplied reference assumption, not a measured absolute concentration/clearance calibration. |
| spillover_per_ms_DA | 0.0 | 1/ms | ASSUMPTION | [0.0, 0.001, 0.01] | Symmetric compartment adjacency; multi-hop spread occurs over repeated steps. Default DA has no spillover. |
| max_source_rate_hz_DA | 50.0 | Hz | ASSUMPTION | [25.0, 50.0, 100.0] | Mean source firing rate normalization; full normalized drive has equilibrium 1a.u. at unit source gain. |
| source_gain_DA | 1.0 | dimensionless | ASSUMPTION | [0.5, 1.0, 2.0] | Dimensionless release gain; fields never add a membrane current. |
| tau_clear_ms_OA | 1500.0 | ms | ASSUMPTION | [750.0, 1500.0, 3000.0] | Provisional kinetics; no per-compartment concentration measurement exists in this build. |
| spillover_per_ms_OA | 0.0 | 1/ms | ASSUMPTION | [0.0, 0.001, 0.01] | Symmetric compartment adjacency; multi-hop spread occurs over repeated steps. Default DA has no spillover. |
| max_source_rate_hz_OA | 50.0 | Hz | ASSUMPTION | [25.0, 50.0, 100.0] | Mean source firing rate normalization; full normalized drive has equilibrium 1a.u. at unit source gain. |
| source_gain_OA | 1.0 | dimensionless | ASSUMPTION | [0.5, 1.0, 2.0] | Dimensionless release gain; fields never add a membrane current. |
| tau_clear_ms_5HT | 2000.0 | ms | ASSUMPTION | [1000.0, 2000.0, 4000.0] | Provisional kinetics; no per-compartment concentration measurement exists in this build. |
| spillover_per_ms_5HT | 0.0 | 1/ms | ASSUMPTION | [0.0, 0.001, 0.01] | Symmetric compartment adjacency; multi-hop spread occurs over repeated steps. Default DA has no spillover. |
| max_source_rate_hz_5HT | 50.0 | Hz | ASSUMPTION | [25.0, 50.0, 100.0] | Mean source firing rate normalization; full normalized drive has equilibrium 1a.u. at unit source gain. |
| source_gain_5HT | 1.0 | dimensionless | ASSUMPTION | [0.5, 1.0, 2.0] | Dimensionless release gain; fields never add a membrane current. |
| tau_clear_ms_NO | 50.0 | ms | ASSUMPTION | [25.0, 50.0, 100.0] | Provisional kinetics; no per-compartment concentration measurement exists in this build. |
| spillover_per_ms_NO | 0.01 | 1/ms | ASSUMPTION | [0.0, 0.005, 0.01] | Symmetric compartment adjacency; multi-hop spread occurs over repeated steps. Default DA has no spillover. |
| max_source_rate_hz_NO | 50.0 | Hz | ASSUMPTION | [25.0, 50.0, 100.0] | Mean source firing rate normalization; full normalized drive has equilibrium 1a.u. at unit source gain. |
| source_gain_NO | 1.0 | dimensionless | ASSUMPTION | [0.5, 1.0, 2.0] | Dimensionless release gain; fields never add a membrane current. |
| tau_clear_ms_sNPF | 10000.0 | ms | ASSUMPTION | [5000.0, 10000.0, 20000.0] | Provisional kinetics; no per-compartment concentration measurement exists in this build. |
| spillover_per_ms_sNPF | 0.0 | 1/ms | ASSUMPTION | [0.0, 0.001, 0.01] | Symmetric compartment adjacency; multi-hop spread occurs over repeated steps. Default DA has no spillover. |
| max_source_rate_hz_sNPF | 50.0 | Hz | ASSUMPTION | [25.0, 50.0, 100.0] | Mean source firing rate normalization; full normalized drive has equilibrium 1a.u. at unit source gain. |
| source_gain_sNPF | 1.0 | dimensionless | ASSUMPTION | [0.5, 1.0, 2.0] | Dimensionless release gain; fields never add a membrane current. |
| tau_clear_ms_peptide_pool | 60000.0 | ms | ASSUMPTION | [30000.0, 60000.0, 120000.0] | Provisional kinetics; no per-compartment concentration measurement exists in this build. |
| spillover_per_ms_peptide_pool | 0.0 | 1/ms | ASSUMPTION | [0.0, 0.001, 0.01] | Symmetric compartment adjacency; multi-hop spread occurs over repeated steps. Default DA has no spillover. |
| max_source_rate_hz_peptide_pool | 50.0 | Hz | ASSUMPTION | [25.0, 50.0, 100.0] | Mean source firing rate normalization; full normalized drive has equilibrium 1a.u. at unit source gain. |
| source_gain_peptide_pool | 1.0 | dimensionless | ASSUMPTION | [0.5, 1.0, 2.0] | Dimensionless release gain; fields never add a membrane current. |
| tau_clear_ms_TA | 1500.0 | ms | ASSUMPTION | [750.0, 1500.0, 3000.0] | Provisional kinetics; no per-compartment concentration measurement exists in this build. |
| spillover_per_ms_TA | 0.0 | 1/ms | ASSUMPTION | [0.0, 0.001, 0.01] | Symmetric compartment adjacency; multi-hop spread occurs over repeated steps. Default DA has no spillover. |
| max_source_rate_hz_TA | 50.0 | Hz | ASSUMPTION | [25.0, 50.0, 100.0] | Mean source firing rate normalization; full normalized drive has equilibrium 1a.u. at unit source gain. |
| source_gain_TA | 1.0 | dimensionless | ASSUMPTION | [0.5, 1.0, 2.0] | Dimensionless release gain; fields never add a membrane current. |
| tau_clear_ms_ACh | 100.0 | ms | ASSUMPTION | [50.0, 100.0, 200.0] | Provisional kinetics; no per-compartment concentration measurement exists in this build. |
| spillover_per_ms_ACh | 0.0 | 1/ms | ASSUMPTION | [0.0, 0.001, 0.01] | Symmetric compartment adjacency; multi-hop spread occurs over repeated steps. Default DA has no spillover. |
| max_source_rate_hz_ACh | 50.0 | Hz | ASSUMPTION | [25.0, 50.0, 100.0] | Mean source firing rate normalization; full normalized drive has equilibrium 1a.u. at unit source gain. |
| source_gain_ACh | 1.0 | dimensionless | ASSUMPTION | [0.5, 1.0, 2.0] | Dimensionless release gain; fields never add a membrane current. |
| odour_max_rate_hz | 150.0 | Hz | ASSUMPTION | [75.0, 150.0, 300.0] | Hz conversion and adapting transduction are model assumptions. Preserve DoOR signed consensus-minus-SFR deltas; default tonic baseline uses measured SFR where available, and unmapped/untyped cells remain zero. |
| odour_adaptation_tau_ms | 200.0 | ms | ASSUMPTION | [100.0, 200.0, 400.0] | Hz conversion and adapting transduction are model assumptions. Preserve DoOR signed consensus-minus-SFR deltas; default tonic baseline uses measured SFR where available, and unmapped/untyped cells remain zero. |
| odour_transduction_tau_ms | 12.0 | ms | ASSUMPTION | [6.0, 12.0, 24.0] | Hz conversion and adapting transduction are model assumptions. Preserve DoOR signed consensus-minus-SFR deltas; default tonic baseline uses measured SFR where available, and unmapped/untyped cells remain zero. |
| odour_half_saturation | 0.2 | a.u. | ASSUMPTION | [0.1, 0.2, 0.4] | Hz conversion and adapting transduction are model assumptions. Preserve DoOR signed consensus-minus-SFR deltas; default tonic baseline uses measured SFR where available, and unmapped/untyped cells remain zero. |
| odour_adaptation_strength | 0.5 | dimensionless | ASSUMPTION | [0.25, 0.5, 1.0] | Hz conversion and adapting transduction are model assumptions. Preserve DoOR signed consensus-minus-SFR deltas; default tonic baseline uses measured SFR where available, and unmapped/untyped cells remain zero. |
| odour_baseline_mode | source_sfr | method | ASSUMPTION | ["source_sfr", "zero"] | Hz conversion and adapting transduction are model assumptions. Preserve DoOR signed consensus-minus-SFR deltas; default tonic baseline uses measured SFR where available, and unmapped/untyped cells remain zero. |
| receptor_gain_min | 0 | dimensionless | ASSUMPTION | [0, 0.1] | Receptor numerical guard, not a measured biological magnitude; every activated guard is counted. |
| receptor_gain_max | 3 | dimensionless | ASSUMPTION | [2, 3, 4] | Receptor numerical guard, not a measured biological magnitude; every activated guard is counted. |
| receptor_threshold_factor_min | 0.25 | dimensionless | ASSUMPTION | [0.125, 0.25, 0.5] | Receptor numerical guard, not a measured biological magnitude; every activated guard is counted. |
| receptor_threshold_factor_max | 3 | dimensionless | ASSUMPTION | [2, 3, 4] | Receptor numerical guard, not a measured biological magnitude; every activated guard is counted. |
| receptor_tau_factor_min | 0.1 | dimensionless | ASSUMPTION | [0.05, 0.1, 0.2] | Receptor numerical guard, not a measured biological magnitude; every activated guard is counted. |
| receptor_tau_factor_max | 5 | dimensionless | ASSUMPTION | [2.5, 5, 10] | Receptor numerical guard, not a measured biological magnitude; every activated guard is counted. |
| receptor_release_min | 0 | dimensionless | ASSUMPTION | [0, 0.1] | Receptor numerical guard, not a measured biological magnitude; every activated guard is counted. |
| receptor_release_max | 2 | dimensionless | ASSUMPTION | [1.5, 2, 3] | Receptor numerical guard, not a measured biological magnitude; every activated guard is counted. |
| receptor_signal_abs_max | 5 | dimensionless | ASSUMPTION | [2.5, 5, 10] | Receptor numerical guard, not a measured biological magnitude; every activated guard is counted. |
| dt_plast_ms | 1.0 | ms | ASSUMPTION | [0.5, 1.0] | Final brief Part III normalized-rule fixture or explicitly declared runtime assumption; no biological fit. |
| plasticity_tau_pre_ms | 600.0 | ms | ASSUMPTION | [300.0, 600.0, 1200.0] | Final brief Part III normalized-rule fixture or explicitly declared runtime assumption; no biological fit. |
| plasticity_tau_da_trace_ms | 1500.0 | ms | ASSUMPTION | [750.0, 1500.0, 3000.0] | Final brief Part III normalized-rule fixture or explicitly declared runtime assumption; no biological fit. |
| plasticity_eta_per_ms | 0.00055 | 1/ms | ASSUMPTION | [0.000275, 0.00055, 0.0011] | Final brief Part III normalized-rule fixture or explicitly declared runtime assumption; no biological fit. |
| plasticity_A1 | 1.0 | dimensionless | ASSUMPTION | [0.5, 1.0, 1.5] | Final brief Part III normalized-rule fixture or explicitly declared runtime assumption; no biological fit. |
| plasticity_A2 | 0.55 | dimensionless | ASSUMPTION | [0.275, 0.55, 0.825] | Final brief Part III normalized-rule fixture or explicitly declared runtime assumption; no biological fit. |
| plasticity_w_max_multiplier | 2.0 | dimensionless | ASSUMPTION | [1.5, 2.0, 3.0] | Final brief Part III normalized-rule fixture or explicitly declared runtime assumption; no biological fit. |
| plasticity_tau_forget_ms | 600000.0 | ms | ASSUMPTION | [300000.0, 600000.0, 1200000.0] | Final brief Part III normalized-rule fixture or explicitly declared runtime assumption; no biological fit. |
| plasticity_beta | 1.0 | dimensionless | ASSUMPTION | [0.0, 1.0, 2.0] | Final brief Part III normalized-rule fixture or explicitly declared runtime assumption; no biological fit. |
| max_kc_rate_hz | 50.0 | Hz | ASSUMPTION | [25.0, 50.0, 100.0] | Final brief Part III normalized-rule fixture or explicitly declared runtime assumption; no biological fit. |
| runtime_rate_tau_ms | 20.0 | ms | ASSUMPTION | [10.0, 20.0, 40.0] | Final brief Part III normalized-rule fixture or explicitly declared runtime assumption; no biological fit. |
| runtime_chunk_ms | 10.0 | ms | ASSUMPTION | [5.0, 10.0, 20.0] | Final brief Part III normalized-rule fixture or explicitly declared runtime assumption; no biological fit. |
| runtime_seed | 7 | integer | ASSUMPTION | [7, 11, 23] | Final brief Part III normalized-rule fixture or explicitly declared runtime assumption; no biological fit. |
| runtime_threads | 1 | integer | ASSUMPTION | [1] | Final brief Part III normalized-rule fixture or explicitly declared runtime assumption; no biological fit. |
| state_dt_ms | 1000 | ms | ASSUMPTION | [500.0, 1000, 2000] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |
| state_energy_depletion_tau_ms | 3600000 | ms | ASSUMPTION | [1800000.0, 3600000, 7200000] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |
| state_feeding_tau_ms | 300000 | ms | ASSUMPTION | [150000.0, 300000, 600000] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |
| state_hydration_loss_tau_ms | 1800000 | ms | ASSUMPTION | [900000.0, 1800000, 3600000] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |
| state_drinking_tau_ms | 60000 | ms | ASSUMPTION | [30000.0, 60000, 120000] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |
| state_arousal_tau_ms | 5000 | ms | ASSUMPTION | [2500.0, 5000, 10000] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |
| state_stress_tau_ms | 60000 | ms | ASSUMPTION | [30000.0, 60000, 120000] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |
| state_circadian_period_ms | 86400000 | ms | ASSUMPTION | [43200000.0, 86400000, 172800000] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |
| state_hormone_tau_ms | 10000 | ms | ASSUMPTION | [5000.0, 10000, 20000] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |
| state_source_max_rate_hz | 50 | Hz | ASSUMPTION | [25.0, 50, 100] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |
| state_endocrine_tonic_drive | 0.25 | dimensionless | ASSUMPTION | [0, 0.25, 0.5] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |
| state_pam_hunger_gain | 0.35 | dimensionless | ASSUMPTION | [0.175, 0.35, 0.7] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |
| state_pam_insulin_suppression | 0.2 | dimensionless | ASSUMPTION | [0.1, 0.2, 0.4] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |
| state_oa_arousal_gain | 0.5 | dimensionless | ASSUMPTION | [0.25, 0.5, 1.0] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |
| state_circadian_tone_amplitude | 0.1 | dimensionless | ASSUMPTION | [0.05, 0.1, 0.2] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |
| state_gain_min | 0.25 | dimensionless | ASSUMPTION | [0.1, 0.25, 0.5] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |
| state_gain_max | 3.0 | dimensionless | ASSUMPTION | [2, 3, 5] | Explicit state dynamics assumption; no measured coupling strength or biological fitting. |

### Source-audit policies

These are descriptive selection and failure policies, not tunable simulation parameters or completed sensitivity sweeps.

| Policy | Value | Unit | Provenance | Interpretation |
|---|---|---|---|---|
| identity | positive_known_nt_only | selection_rule | DOI:10.1038/s41586-024-07686-5 | Split known_nt on comma/semicolon; drop fragments ending in -negative. top_nt is audit evidence only. |
| kc_aminergic_exclusion | True | assertion | PMID:26948892 | Defect D: known cholinergic KCs cannot become aminergic sources through top_nt. |
| kc_peptide_conflict | retain_positive_snpf_independently | audit_interpretation | ASSUMPTION | NEUROMOD_PATCH1.md section 3 resolves the conflict: exclude KCs from aminergic sources, retain 4133 KC sNPF and 5034 whole-annotation sNPF sources. |
| expected_counts | primary_data_exact_population_selector_authoritative | assertion | ASSUMPTION | NEUROMOD_PATCH1.md section 1.2: stop on primary-data or software-integrity mismatch; report definition-count disagreements and proceed using normative selectors. |

### Compartment construction assumptions

```json
{
  "clustering": {
    "value": "average_linkage_Jaccard_15",
    "unit": "method",
    "source": "ASSUMPTION",
    "note": "DAN to KC outputs and KC to MBON inputs; binary partner vectors, lexicographic type order, hemispheres pooled. Clustering fixed before canonical label alignment."
  },
  "canonical_alignment": {
    "value": "Hungarian_fractional_type_votes",
    "unit": "method",
    "source": "ASSUMPTION",
    "note": "One over published compartment-count vote; keep zero-support labels and disagreements visible. Published anatomy never changes empirical cluster membership."
  },
  "membership": {
    "value": "KC_partner_proxy",
    "unit": "selection_rule",
    "source": "ASSUMPTION",
    "note": "KC belongs to each empirical compartment containing an observed DAN/MBON partner. This is not a measured release-site map."
  },
  "adjacency": {
    "value": "coarse_neighbor_graph",
    "unit": "topology",
    "source": "ASSUMPTION",
    "note": "Consecutive MB lobe slices, consecutive FB layers and coarse optic neighbors; no AL adjacency without geometry."
  }
}
```

### Receptor coefficients

Generated from config/receptors.csv. Every numerical magnitude and expression coverage is ASSUMPTION. Biological sign evidence does not calibrate the coefficient; the sweep column lists candidates, not executed sweeps.

| Row | Active | Magnitude at C=1 (dimensionless) | Kernel | History | Sign evidence | Candidate magnitudes |
|---|---|---:|---|---|---|---|
| DA_Dop1R1_forward | true | -1.0 | linear | kc_before_da | PUBLISHED | -0.5;-1.0;-1.5 |
| DA_Dop1R2_backward | true | 0.55 | linear | da_before_kc | PUBLISHED | 0.275;0.55;0.8250000000000001 |
| DA_Dop2R_gain | true | -0.2 | hill(1,1) | instant | INFERRED_SIGN | -0.1;-0.2;-0.30000000000000004 |
| DA_Dop2R_release_prob | true | -0.2 | hill(1,1) | instant | INFERRED_SIGN | -0.1;-0.2;-0.30000000000000004 |
| OA_OAMB_PAM | true | 0.35 | hill(1,1) | instant | PUBLISHED | 0.175;0.35;0.5249999999999999 |
| OA_Octbeta2R_PAM_requested | false | 0.35 | hill(1,1) | instant | ASSUMPTION | 0.175;0.35;0.5249999999999999 |
| OA_VS_gain | true | 0.35 | hill(1,1) | instant | PUBLISHED | 0.175;0.35;0.5249999999999999 |
| OA_HS_gain | true | 0.35 | hill(1,1) | instant | INFERRED_SIGN | 0.175;0.35;0.5249999999999999 |
| OA_HSVS_tau | true | -0.25 | linear | instant | ASSUMPTION | -0.125;-0.25;-0.375 |
| ACh_mAChRA_KC | true | -0.2 | hill(1,1) | instant | PUBLISHED | -0.1;-0.2;-0.30000000000000004 |
| ACh_mAChRB_KC_requested | false | -0.2 | hill(1,1) | instant | ASSUMPTION | -0.1;-0.2;-0.30000000000000004 |
| sNPF_sNPFR_KC_release | true | 0.15 | hill(2,0.5) | instant | ASSUMPTION | 0.075;0.15;0.22499999999999998 |
| 5HT_5HT7_GABA_ALLN | true | 0.2 | hill(1,1) | instant | PUBLISHED | 0.1;0.2;0.30000000000000004 |

[Receptor identities, cited signs, assumed coverage and limitations](docs/receptors.md).

### Stage-5 reference fixture

These immutable diagnostic assumptions are declared in plasticity.py; they are not calibrated model defaults. The final brief supplies the normalized equation and all twelve reference targets. No coefficients were fitted to the table or to network biology.

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
