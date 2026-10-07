# Neuromodulation specification findings

**Historical initial audit.** [Patch 1](../NEUROMOD_PATCH1.md) accepts these findings and corrects the source definitions, nitric-oxide inventory and KC sNPF rule. The original brief is preserved in `docs/specifications/neuromod_build_brief_original.md`; `NEUROMOD_BUILD_BRIEF.md` now contains the supplied revision. Current implementation and gate status are in `REPORT.md`.

These findings explain the original source-audit stop. They remain evidence of the initial specification errors, not unresolved census blockers after the patch.

## Census mismatch

The raw annotation table was joined one-to-one onto `Completeness_783.csv` in its original row order. The join agrees exactly with the existing base neuron table. The source hashes and complete assertions are in `build/validation_neuromod_sources.json`.

| Quantity | Brief | Annotation-defined measurement |
|---|---:|---:|
| AL projection neurons | 2,960 | 685 |
| AL projection-neuron named types | 235 | 182 |
| Central-complex neurons | 2,701 | 2,875 |
| Central-complex named types | 211 | 229 |
| Deduplicated modulated-core neurons | 13,126 | 13,300 |
| Released internal core edges | 1,136,053 | 1,161,917 |
| Released internal core synapses | 4,433,962 | 4,581,576 |

The biological masks use `cell_class == ALPN` for projection neurons and `cell_class == CX` for central-complex neurons. Both annotation and model subsets contain 685 ALPN neurons; this is not an annotation-versus-model count difference. All eleven mushroom-body motif counts match the brief, including ALPN→KC: 27,848 edges and 329,394 synapses. The whole-brain positive-transmitter audit also matches the brief.

The executable gate retains missing cell-type labels as an explicit unknown category, so it records 230 CX categories (229 named plus unknown), rather than dropping untyped neurons. The named-type count above excludes that category.

Two independent investigations reproduced 2,960/235 with `(cell_class == 'ALPN') OR cell_type.startswith('ORN')`: 685 projection neurons plus 2,275 named olfactory receptor neurons. The prompt separately counts the olfactory receptor population, so the alleged projection-neuron count uses a mixed population. The additional four unnamed olfactory cells explain 2,279 total olfactory cells and 54 categories when missing type is retained explicitly.

A restricted CX name selector can reproduce 2,701 neurons/211 types: `cell_class == 'CX'` and (`cell_type == 'EPG'` or prefixes `PEG`, `PEN`, `PF`, `FB`, `FC`, `FS`, `FR`, `ER`, `ExR`, `hDelta`, `vDelta`). That omits 174 annotated CX neurons, including Delta7, EPGt, LNO1/2, EL and IbSpsP. Its union has 13,126 neurons, but only 1,135,313 internal edges and 4,411,591 synapses: it still fails the brief's connectivity references. It is not adopted by the build.

The original census scripts named by the brief were not supplied. Their exact population selectors, or an explicitly revised biological definition with new reference counts, are needed before a matching core can be accepted. Silently trimming neurons to obtain the requested count would not establish correct identity or connectivity.

## Cotransmission conflicts

The brief lists four MB dopamine types with positive nitric-oxide annotations. The actual set also includes PAM06: two of its neurons have positive nitric-oxide annotations. The audit preserves them.

There are 4,133 positively annotated KC sNPF sources. The brief requires their peptide contribution and simultaneously requires zero KCs in any modulator source set. KCs are excluded from the aminergic source masks; sNPF annotations are retained separately and the literal all-modulator assertion is reported as conflicting. No peptide dynamics are inferred from this audit.

## Downstream prerequisites

The base V-A data gate passes, but V-C equilibration remains failed and the visual biology gates remain NOT-RUN. This checkout contains neither an odour-response calibration nor an existing descending-neuron behaviour decoder. The extension cannot claim to reuse already validated versions of those components.

The independent single-synapse specification audit is documented in [neuromod_reference_findings.md](neuromod_reference_findings.md). It is a diagnostic of the supplied reference, not a completed plasticity engine or V-NM-E pass.

## Implemented boundary

At the original stop, `flybrain neuromod build` implemented only the source-audit stage and wrote a nonzero exit status plus durable expected/observed evidence. Patch 1 authorizes continuing from this work. Primary-data and software-integrity failures still stop the build; population-definition disagreements are recorded as warnings and the normative selector wins. Green tests never substitute for the recorded data/biology gates.
