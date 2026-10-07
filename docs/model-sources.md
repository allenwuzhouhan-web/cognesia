# Cognesia model sources and fusion

The new model is a composite adult female *Drosophila melanogaster* model. Its
native brain–nerve-cord wiring comes from BANC materialization 888; selected
transmitter annotations are transferred through unique, curator-checked
FlyWire homologies. Neural dynamics, organ equations and enzyme parameters are
explicit model assumptions. Assembly is not biological validation.

## Acquired source and observed counts

The [BANC paper](https://www.nature.com/articles/s41586-026-10735-w), its
[author repository](https://github.com/htem/BANC-project), and the authors'
[data index](https://github.com/htem/BANC-project/blob/main/manuscript/print/banc_data_locations.md)
identify the official data products. Cognesia downloaded the metadata and v3
simple edgelist from the public author Google Cloud Storage mirror. The
Dataverse API returned HTTP 403 during this acquisition; the public mirror was
available. No authentication workaround was used.

| Artifact | Pinned object generation | Bytes |
|---|---:|---:|
| `banc_888_meta.feather` | 1787336614757441 | 57,503,026 |
| `banc_888_edgelist_simple_v3.feather` | 1786578377086929 | 359,161,658 |

Source URLs, object generations, observed byte lengths and SHA-256 checksums are
saved in `data/raw/models/banc-888/sources.json`. Subsequent reads reject changed
bytes. The v3 edgelist uses the authors' synapse-size filtering; this is not a
new minimum connection-weight cutoff added by Cognesia.

The acquired metadata contains **188,508 rows**, including non-neural entities.
The assembled neural graph contains **175,401 entities and 13,542,180 edges**.
Assembly excludes glia, trachea and rows labeled `not_a_neuron`, and excludes
78,685 edgelist rows with a removed/unmapped endpoint or zero count. These are
observed artifact counts, not substitutions for a paper's headline census.
Other unresolved neuron labels and the source proofreading/problem flags stay
in the metadata. Inclusion does not certify that a flagged reconstruction is
correct.

The source's current `root_id` can differ from its materialization-888 ID.
Assembly therefore joins on **`banc_888_id`** and uses `banc:888:<id>` as the
external entity identity. Latest root IDs remain available as provenance.
Integer simulation indices are local array locations, not universal identities.

## What has actually been fused

The compiled `cognesia-fused-v1` graph retains continuous native BANC wiring.
Its current ledger contains **55 transmitter-annotation overlays** from unique
`FAFB_MATCH_MANUALLY_CHECKED` correspondences where BANC lacked a verified
transmitter label. Of these, **27 contain positive annotations and 28 contain
only negative experimental reports**. Negative labels never become positive
chemical sources. Native BANC fast-synapse signs remain separately declared
model assumptions; a transferred peptide label does not rewrite them.
A cross-animal homology is labeled inferred; it is not a
measured connection in a hypothetical single merged specimen.

The model combines that anatomical foundation with Cognesia's graded/spiking
point-neuron equations and optional, explicitly modeled peripheral and enzyme
systems. It does **not** yet claim that an entire FlyWire optic-lobe circuit has
been replaced by a demonstrably more accurate donor sector. Such a replacement
requires an imported, checked circuit correspondence and auditable crossing
interfaces. Selecting an unsupported donor patch fails rather than silently
inventing a merge.

Sector source decisions record their comparison basis and evidence. Only
comparable quality vectors may be ranked; later publication wins a comparable
tie, followed by later data release. Unknown or incomparable regional accuracy
retains the continuous incumbent. The current FlyWire/BANC central-brain and
optic-lobe comparisons are explicitly **accuracy unresolved**. A newer paper,
more rows or more synapses alone does not prove more accurate physiology.

Each compiled model freezes its complete executable tables, matrices and
manifest under `build/model-versions/<model_hash>`. Copies are independent of
the current alias; compiling a later version cannot mutate earlier artifacts.
The `model_id@model_hash` loader validates the manifest and artifact checksums.
Current fused version:
`14a57b223bf7f1694fd84650a22a7e891a587056761ee3e763f443968cbaf8b1`.
The source ledger records sector-specific proofreading flags and defects,
verified and predicted transmitter coverage, source-anchor coverage, peripheral
annotations, and specimen compatibility. Missing matched precision/recall,
registration error and held-out physiological error remain unknown.

The historical `flywire-783` provider continues to use its original artifacts
and validation path. New-model metadata never rewrites old recordings or
silently treats old neuron indices as BANC identities.

## Anatomical and visual coverage

The assembled catalogue resolves **704 selectable anatomical modules**, including
**248 named muscle subdivisions and 69 organ/visceral interfaces**. These use
the source's side, nerve, body target and peripheral target annotations. They
are neural-interface identities; the state/feedback equations attached to them
are schematic normalized models. A body mesh does not prove a reconstructed
nerve, muscle volume or organ physiology.

Native source positions are converted from nanometres to micrometres. They are
BANC coordinates, not a measured registration to the existing NeuroMechFly
surface. Existing point-neuron anatomical anchors also do not establish full
neurite geometry or physical region boundaries.

The new-provider visual adapter targets only annotated photoreceptors. In the
current assembly, **216 photoreceptors receive optical input**: 4 use checked
FlyWire column transfers and 212 use explicitly modeled position-ranked optical
columns. **1,630 photoreceptors have no side annotation and stay optically
unassigned.** Assumed column spacing and spherical orientation do not establish
measured retinotopy, photoreceptor coverage, or visual selectivity. These counts
are stored in each optical audit and can change only with a new data/model
version or an explicit modeling rule.

## Scientific status

The source graph is acquired and assembled. The software can run its specified
equations. Neither fact establishes stable sensory-driven activity, correct
behavior, realistic organ mechanics or successful biological learning. Original
limitations and failed gates in `REPORT.md` and `LIMITATIONS.md` remain intact.
