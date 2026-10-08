# ParaLimbo provenance

All assertions retain source identity, original text and the compiler decision.
Pinned inputs and output checksums are recorded in the generated model's
`manifest.json`, `input_hashes.json`, `compiler_hashes.json` and `policy.json`.

## Pinned inputs

| Input | Pin |
| --- | --- |
| BANC model | `60d220182e6f65b98a78b008c764bb13b802d1dc5b85a798cc9028a6557665de` |
| BANC metadata | Author GCS generation `1787336614757441`; SHA-256 `86ccf5df0c67419f8c5f43e93a7ed38d23a080e9f7fde26737290252f3780098` |
| BANC v3 edgelist | Author GCS generation `1786578377086929`; SHA-256 `8c296e946f3c69a8c7222f30ad75fa8a98eeb189124fec6df829c9125f4be64b` |
| FlyWire annotation TSV | `flyconnectome/flywire_annotations` commit `17fc57722002e1a7d38cdd0c89ac382bf92718da` |
| FlyWire completeness table | `philshiu/Drosophila_brain_model` commit `91bdd1e7dcf193f3e7ca5a8933497fcef63b7960` |
| Compiled FlyWire neuron table | SHA-256 `432901d18d2a5b44fd44dd558668589b81103344eeb8f44b2637cbd6b5f8889e` |

Exact acquisition URLs, sizes and remaining checksums are embedded in
[`paralimbo.py`](../../src/flybrain/paralimbo.py), the BANC acquisition code and
the generated input manifest. Source IDs are parsed as exact integers; they
never pass through floating point.

## Correspondence and property rules

`crosswalk.parquet` contains one row per BANC neuron. Categories are
`curator_supported_individual`, `type_only`, `ambiguous`, `missing_donor` and
`unresolved`. Only a unique, curator-checked donor without known type or side
conflict qualifies for property transfer. This is a classification of available
evidence, not proof of individual biological identity. Type-level matches and
repeated exemplars never authorize individual wiring or annotation transfer in
this release.

Native `neurotransmitter_verified` and `neuropeptide_verified` fields remain
unchanged. Parsed properties distinguish fast transmitters, neuromodulators,
peptides, unclassified labels, negatives, conflicts and inferred annotations.
Aliases normalize names, including `nitric_oxide` to `nitric oxide`; unknown
donor names are not guessed. The cell-class alias for antennal-lobe local neurons
becomes `ALLN` for the existing runtime target rule.

Native positive/negative self-conflicts remain in the evidence ledger and are
excluded from positive release annotations. Conflicting donor assertions are
rejected while native evidence is retained. Native negative evidence vetoes
positive transfer; a generic peptide-negative assertion vetoes peptide transfer.
A different donor fast transmitter is not added to a nonempty native positive
fast-transmitter set. Eligible nonconflicting holes are filled per property,
even when the destination already has other annotations.

`annotation_ledger.parquet` records source, source field, donor and recipient,
raw text, canonical token, polarity, evidence category, decision and reason.
`conflicts.parquet` includes **all rejected transfers** and preserved native
conflicts; its row count is not the number of biological contradictions.

## Attribution and terms

The [BANC authors](https://github.com/htem/BANC-project) request citation of the
[paper](https://doi.org/10.1038/s41586-026-10735-w) and
[Dataverse deposit](https://doi.org/10.7910/DVN/7WTH1N), and state CC BY 4.0
for the deposited data. Consult archive-specific terms for additional code.

Use the [FlyWire annotation repository's version-specific citation guidance](https://github.com/flyconnectome/flywire_annotations)
and cite the [annotation paper](https://doi.org/10.1038/s41586-024-07686-5)
and [connectome paper](https://doi.org/10.1038/s41586-024-07558-y).
[FlyWire's general guidelines](https://flywire.ai/guidelines) state CC BY-NC 4.0;
the separate [connectivity deposit](https://doi.org/10.5281/zenodo.10676866)
reports CC BY 4.0 in its record metadata. Preserve per-artifact terms rather
than treating every FlyWire product as uniformly licensed.

The GitHub source release does not bundle raw datasets or generated neuron and
edge tables. The acquisition script downloads upstream inputs separately.
ParaLimbo does not relicense those inputs. Original Cognesia material remains
[all rights reserved](../../LICENSE).
