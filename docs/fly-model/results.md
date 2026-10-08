# ParaLimbo preview results

Recorded on 2026-10-08 for model
`251615940b84dad843d0cf85138c936e118b0890274231bb8e5720b5b381bb5c`.
The demonstrated improvement is recovery and traceability of source
annotations. Biological predictive superiority remains **PENDING**.

| Evaluation | Outcome | Scope |
| --- | --- | --- |
| Construction/source audit | PASS, 52 checks | Exact identities, unchanged wiring, preserved assertions and runtime source selection |
| Pinned input reproduction | PASS | Rebuilt BANC identity and FlyWire neuron-table hash match |
| Repeated compilation | PASS | Two complete manifests and model hashes identical |
| Bounded runtime | PASS | Two full-network 300 ms paired dark runs; finite saved arrays, exact replay and zero clamps |
| Stationarity and timestep convergence | NOT ESTABLISHED | Not implied by construction or replay |
| Independent biological improvement | PENDING | No completed held-out biological benchmark |

## Chemical source coverage

These are counts of neurons selected by the runtime's annotation rules. They
are not measured concentrations, effective receptor counts or prediction scores.
Comparator artifact identities are specified in the [protocol](validation-protocol.md).

| Runtime source | BANC baseline | Previous fused model | ParaLimbo |
| --- | ---: | ---: | ---: |
| Dopamine | 1,048 | 1,048 | 1,048 |
| Octopamine | 87 | 93 | 89 |
| Serotonin | 225 | 225 | 225 |
| Tyramine | 114 | 114 | 114 |
| Nitric oxide | 0 | 0 | 3,722 |
| sNPF | 0 | 0 | 4,913 |
| Acetylcholine | 45,373 | 45,381 | 45,373 |
| Generic endocrine peptide pool | 0 | 0 | 104 |

The baseline zeroes for NO and sNPF were importer/alias omissions, not evidence
that the source organism lacked them. Native peptide annotations are preserved
for **7,025 neurons**, comprising **7,772 distinct peptide assertions**.
All **78,766 distinct native assertions** across transmitter and peptide fields
are conserved. The peptide pool is the existing coarse endocrine selector;
the 104 selected neurons do not establish 104 validated hormonal mechanisms.

Stricter correspondence and conflict rules accept fewer old OA/ACh transfers.
Coverage therefore does not increase for every chemical. NO has no dedicated
enabled receptor effect, and the provider excludes the KC→MBON sNPF/plasticity
pathway. Recovering their source labels alone does not demonstrate improved
neural responses.

## Correspondences and transfers

| Category | BANC neurons |
| --- | ---: |
| Curator-supported individual | 712 |
| Type only | 124,998 |
| Ambiguous | 7,811 |
| Missing donor | 102 |
| Unresolved | 41,778 |
| Total | 175,401 |

The compiler accepts **59 property assertions across 39 neurons**: two positive
octopamine assertions and 57 negative assertions. It rejects 47,780 donor
assertions for reasons recorded in the ledger, including ineligible
correspondence; this number does not count 47,780 biological contradictions.
The previous model's 55 overlays counted neuron annotation strings and are
not directly comparable to 59 individual property assertions.

No circuits are replaced. All six connectivity array files and the electrical
mode partition match the BANC baseline exactly.

## Bounded runtime

The check integrates all **175,401 neurons**, records **32 neurons**, and repeats
a 300 ms paired dark protocol twice after a fixed 100 ms preparation. All 11
activity arrays and 13 chemistry arrays match exactly between repeats; every
saved numeric array is finite. All four stimulus/baseline arms and both
preparations report zero voltage-clamp events. Chemical field clamps and
receptor guards are also zero. Measured wall times are **13.42 s** and
**13.14 s** on the release machine, including each paired run's work; these
are observations rather than a hardware performance guarantee.

Both preparation endpoints report maximum absolute voltage derivative
**0.0001938498 mV/ms**, zero nonfinite derivatives and zero neurons above the
runtime's endpoint threshold. The endpoint diagnostic reports `stationary`.
This short check does not establish stationarity under other conditions,
long-term stability or timestep convergence.

The corrected `ALLN` class alias allows the existing serotonin receptor rule
to target **11 neurons**. The expression assignment and effect magnitude remain
assumptions. This is a verified runtime target-selection change, not independent
evidence of receptor expression or improved physiological prediction.

## Evidence files

The exact release reports are included here for inspection:

- [Construction and source fidelity](evidence/validation_paralimbo.json)
- [Pinned input reproduction](evidence/validation_paralimbo_inputs_reproduction.json)
- [Deterministic compilation](evidence/validation_paralimbo_determinism.json)
- [Bounded runtime and replay](evidence/validation_paralimbo_runtime.json)
- [Frozen model manifest](evidence/manifest.json)

These are copies of the final generated `build/validation_paralimbo*.json`
records and model manifest, with no intermediate candidate reports. Runtime
evidence is regenerated by the documented command. Raw source data and
generated neuron/edge tables are acquired or built locally. See
[reproduction](reproduce.md).

The [input bootstrap report](evidence/validation_paralimbo_bootstrap.json)
separately verifies the public acquisition script and its idempotent rerun.
