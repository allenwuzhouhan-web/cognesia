# ParaLimbo validation protocol

This preview evaluates construction, source fidelity and bounded execution.
It does not satisfy the independent biological-improvement gate in the
[release specification](README.md).

Candidate: `251615940b84dad843d0cf85138c936e118b0890274231bb8e5720b5b381bb5c`.
Anatomical baseline: `60d220182e6f65b98a78b008c764bb13b802d1dc5b85a798cc9028a6557665de`.
Historical fused comparison: `14a57b223bf7f1694fd84650a22a7e891a587056761ee3e763f443968cbaf8b1`.

## Construction and source fidelity

Pass requires exact input/output checksums; preserved BANC identity, row order,
native fields and electrical partitions; and byte equality of all six sparse
connectivity arrays. The `ALLN` cell-class alias is the only allowed change to
the existing class column.

Every native raw assertion must be represented in the ledger. Every accepted
donor property must have an eligible correspondence and satisfy negative and
conflict rules. Reported counts must agree with observed records. Actual runtime
source masks must equal the compiled positive annotations, including the
existing explicit Kenyon-cell exclusion from aminergic source masks.

The compiler audit recomputes decisions using compiler functions, supplemented
by raw-assertion conservation, runtime-selector comparisons and hand-specified
adversarial fixtures. These are software/source-integrity checks. Shared source
annotations do not become independent biological test evidence.

## Reproduction

Reconstruct the pinned BANC and FlyWire input artifacts and compare their exact
hashes. Compile twice with the same pinned code, inputs and dependency versions;
the complete manifests, including the model hash, must match. Input drift,
code drift or artifact corruption must fail validation rather than silently
changing the claimed model identity.

## Bounded runtime protocol

[`validate_paralimbo_runtime.py`](../../scripts/validate_paralimbo_runtime.py)
runs the exact candidate twice. Each run uses the complete 175,401-neuron
network, a 100 ms preparation, then a 300 ms dark stimulus with matched baseline,
four threads, chemistry enabled and plasticity disabled. It records 32
evenly selected neurons at 20 ms intervals and the chemical outputs.

Pass requires exact candidate identity, finite saved numeric arrays, exact
equality of every saved replay array, zero stimulus/baseline and preparation
clamp events, and no nonfinite preparation derivatives. Preparation
stationarity diagnostics are reported separately.
Finite recorded traces do not establish that every neuron's complete trajectory
was recorded. This protocol establishes neither stationarity, timestep
convergence, driven stability nor biological accuracy.

## Independent biological evaluation: pending

No sealed quantitative recording corpus or completed observation model is
provided by this release. Circuit, experimental conditions, independent units,
development/test split, observation model, primary error metric, meaningful
improvement threshold, confidence procedure and regression limits remain
unresolved. These decisions must be frozen before examining confirmatory test
results. Imported annotations and their source experiments require a leakage
audit before they can serve as validation data.

Until that protocol is completed and passed, the permitted improvement claim is
**greater fidelity to specified source annotations**, not greater biological
predictive accuracy. Outcomes are recorded in [results](results.md).
