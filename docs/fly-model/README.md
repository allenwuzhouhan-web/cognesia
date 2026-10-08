# ParaLimbo release specification

ParaLimbo, the next Cognesia fly model, must demonstrate improved predictive accuracy on
specified biological experiments before it is released as a more accurate
model. The intended implementation combines BANC anatomy with supported
FlyWire annotations and, where justified, mapped circuit replacements.

**Status on 2026-10-08:** ParaLimbo 0.1.0-alpha.1 is implemented as an annotation
integration preview. Its 52-check construction/source audit, pinned input
reproduction, repeated compilation and bounded runtime check pass; conditions
are reported in [results](results.md). Independent biological improvement remains
pending; this preview is not a more-accurate biological model release.

Execution follows the [ParaLimbo implementation and release plan](PLAN.md).

## What accuracy means

Every accuracy claim must name the circuit, experimental conditions, measured
observable, comparator, effect size and uncertainty. Improvement in one circuit
supports a claim about that circuit under those conditions. Whole-fly accuracy
requires additional evidence across the claimed functions.

| Dimension | Evidence required | What it establishes |
| --- | --- | --- |
| Annotation coverage | Counts of supported, missing and conflicting properties | How much information the model represents |
| Anatomical integration | Audited correspondences, source records and circuit boundaries | Whether the intended evidence was integrated correctly |
| Numerical reliability | Convergence, reproducibility and stability under the stated conditions | Whether the implemented equations are solved reliably |
| Biological predictive accuracy | Predictions compared with independent experimental measurements | Whether the model better predicts the measured biology |

All four dimensions must be reported separately. Higher neuron, synapse or
chemical counts alone do not satisfy the predictive-accuracy requirement.

## Model structure

1. **Sources:** pin dataset versions, downloaded-file checksums and original
   evidence references. Keep native annotations available for inspection.
2. **Correspondences:** distinguish supported unique homologs, cell-type
   matches, ambiguous candidates and unresolved neurons. Record evidence for
   each decision; allow matches to remain unresolved.
3. **Properties:** preserve transmitter and peptide evidence separately,
   normalize naming, recover omitted native fields, and record accepted and
   rejected transfers with reasons. Preserve negative and conflicting reports.
4. **Physiology:** use a shared specification for electrical models, chemical
   effects and parameters. Record evidence and assumptions for each property.
5. **Connectivity:** retain BANC continuity by default. A circuit replacement
   requires mapped endpoints, justified donor quality and a complete account of
   incoming, outgoing and feedback connections. A type match alone cannot
   establish an individual connection.
6. **Compilation:** produce immutable model artifacts with a manifest linking
   every source, rule, parameter and connectivity change to its provenance.

Choose providers using comparable evidence for the particular property and
circuit. Publication recency is only a tie-breaker when comparative quality is
otherwise equivalent. Unresolved comparisons retain the existing provider.
The current implementation is described in [Model sources](../model-sources.md).

## Evaluation protocol

Freeze the following decisions in a versioned protocol before inspecting final
test results. All fields are currently **unresolved**; none may be silently
filled using favorable test outcomes.

| Required decision | Contents |
| --- | --- |
| Biological question | Circuit, stimulus or intervention, recording modality, response window and intended claim |
| Experimental data | Source, independent biological unit, eligibility rules, training and validation splits, sealed test set and sample-size justification |
| Comparators | Exact artifacts for the preceding Cognesia model and a BANC-only baseline on the same eligible cases; FlyWire comparison where the circuit is supported |
| Observation model | How simulated states become comparable to recordings, including units, filtering, alignment, scaling and noise assumptions |
| Primary endpoint | One declared primary prediction-error measure, aggregation rule and minimum meaningful improvement |
| Uncertainty | Confidence level, paired analysis, treatment of shared animals or experiments, and multiplicity policy |
| Regression limits | Secondary endpoints, maximum acceptable deterioration and numerical tolerances |
| Failure handling | Treatment of missing predictions, failed runs and exclusions; retain all cases and reasons in the report |

Fit the observation model and all adjustable parameters using development data
only. Give competing models equivalent tuning budgets and comparison procedures.
Use the same eligible biological cases and stimuli for each comparison; report
unsupported cases explicitly rather than allowing a model to improve its score
by dropping difficult cases.

Audit whether test measurements or labels influenced imported functional
annotations, neuron matching, circuit selection, fitting or metric selection.
Shared source experiments cannot count as independent evidence. Repeated
simulation seeds quantify simulation variability; they do not create new
biological replicates. If test results influence a revision, move those results
into development data and use an independent test set for a new confirmatory
claim.

## Acceptance rules

For a primary error measure where lower is better, define paired improvement
as `baseline error - candidate error`. Freeze its units and aggregation rule.
The lower confidence bound on improvement must exceed the predeclared minimum
meaningful improvement for each comparator required by the claim, using the
declared multiplicity policy. A favorable point estimate with insufficient
evidence is **inconclusive**.

| Gate | Pass requirement |
| --- | --- |
| Construction | Valid source identities, no accidental duplication, traceable transfers and accounted circuit interfaces |
| Numerical evaluation | Pass the declared convergence, stability and reproducibility checks for the exact candidate artifact and benchmark conditions |
| Biological improvement | Meet the primary improvement rule on independent test data and satisfy all declared secondary regression limits |
| Reproduction | Rebuild and rerun from pinned inputs using documented commands; results agree within declared tolerances |

Historical validation of a different model hash cannot satisfy these gates.
An unconfigured gate is pending, not passed. If biological improvement fails
or remains inconclusive, the candidate does not qualify for the more-accurate
model release. A development preview may describe completed software and
coverage improvements with its validation status stated explicitly.

Run controlled comparisons that isolate native-import fixes, homology-based
transfers, physiology changes and any wiring replacement. Their purpose is to
show which changes explain the result and whether combinations interact. Include
sensitivity to ambiguous correspondences and uncertain parameters, with the
analysis plan frozen before final testing.

## Documentation and release package

This specification is the documentation entry point. The companion documents
describe the implemented preview and distinguish its evidence from the pending
biological release requirements.

| Document | Contents |
| --- | --- |
| [Model card](model-card.md) | Scope, assumptions, limitations and exact artifact identity |
| [Provenance](provenance.md) | Source pins, correspondence categories, annotation schema and transfer decisions |
| [Validation protocol](validation-protocol.md) | Preview acceptance checks and unresolved biological evaluation requirements |
| [Results](results.md) | Before/after source coverage, regressions and gate outcomes |
| [Reproduction](reproduce.md) | Acquisition, build and evaluation commands, dependencies and expected outputs |
| [Release notes](release-notes.md) | Measured changes, limitations, attribution and release scope |

Keep model versions distinct from workbench versions within the existing
Cognesia repository. The proposed first preview tag is
`paralimbo-v0.1.0-alpha.1`; it is not created by this specification. Release
assets should include the manifest, transfer ledger, results and permitted
model artifacts or reproducible acquisition instructions. Preserve project and
third-party terms in [LICENSE](../../LICENSE) and
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

The GitHub presentation should lead with the supported result, one model
structure diagram, a readable comparison table and a reproducible demonstration.
Use placeholders only in drafts. Final accuracy wording must name the measured
improvement and its scope. A world-first claim additionally requires a dated
prior-art comparison covering that exact contribution.

## Implementation order

1. Recover native annotations and build the correspondence and provenance
   compiler, with construction checks and an explicit conflict report.
2. Select an accessible biological benchmark and freeze the evaluation protocol.
3. Implement and calibrate the candidate on development data, then freeze its
   model artifact and evaluation code before final testing.
4. Evaluate the baselines and candidate, explain differences through the planned
   controlled comparisons, and independently reproduce the results.
5. Publish an accuracy claim only at the scope supported by the completed gates.

Existing [scientific limitations](../../LIMITATIONS.md) and
[validation records](../../REPORT.md) remain part of the evidence readers must
consider alongside the new results.
