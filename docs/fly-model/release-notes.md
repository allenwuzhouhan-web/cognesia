# ParaLimbo 0.1.0-alpha.1

ParaLimbo is Cognesia's BANC–FlyWire integration preview. It restores omitted
native chemical annotations and makes conservative cross-specimen property
transfers inspectable and reproducible. It preserves BANC connectivity.

## Measured changes

- Recover peptide annotations for 7,025 neurons, including 4,913 sNPF source
  neurons; normalize NO labels to recover 3,722 source neurons.
- Classify every one of the 175,401 BANC neurons in an auditable correspondence
  table. Only 712 unique curator-supported matches qualify for transfer.
- Accept 59 property assertions across 39 neurons, comprising two positive
  octopamine assertions and 57 negatives; retain rejection reasons.
- Preserve all 78,766 distinct native assertions, original IDs, electrical modes
  and all six BANC connectivity arrays.
- Add the ParaLimbo provider to the CLI and Cognesia model selection.

The 52-check construction audit passes. Pinned input reproduction and two
identical compiled manifests pass. Two full-network 300 ms paired dark runs
also pass their bounded execution check: finite saved arrays, exact replay and
zero experiment/preparation clamps. See [results](results.md) for conditions
and the distinction from global numerical or biological validation.

## Boundaries

This is an alpha preview with improved source fidelity. Independent biological
predictive improvement is pending; no world-first claim is made. No circuit is
replaced. Existing physiology, synaptic-sign, graded/spiking, chemical-unit and
receptor assumptions remain explicit. More source labels do not automatically
add physiological pathways. Stricter rules reduce accepted OA and ACh source
coverage relative to the preceding fused model; see the comparison table.

Model hash:
`251615940b84dad843d0cf85138c936e118b0890274231bb8e5720b5b381bb5c`.
Provider: `paralimbo-v0-1-0`. Tag: `paralimbo-v0.1.0-alpha.1`.
Cognesia app versions are separate from model versions.

The source release and aggregate evidence support local reproduction. Raw
datasets and generated neuron/edge tables are not bundled. Fetch pinned inputs
using the [reproduction guide](reproduce.md), retaining [upstream attribution](provenance.md).
Original Cognesia code/documentation remain all rights reserved; public source
availability does not grant additional modification or redistribution rights.

Read the [model card](model-card.md), [validation protocol](validation-protocol.md),
[results](results.md) and [implementation plan](PLAN.md).
