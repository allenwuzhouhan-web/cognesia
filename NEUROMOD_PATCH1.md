# Patch 1 to the neuromodulation build brief — corrected core definition, resume at stage 2

> Paste this into the same Codex session, alongside `NEUROMOD_BUILD_BRIEF.md`. It supersedes the
> named sections of that brief. Everything not named here stands unchanged.
> Measurements below were recomputed on 2026-09-26 from `Connectivity_783.parquet` (15,091,983
> rows, synapse sum 54,492,922), `Completeness_783.csv` (138,639 rows) and
> `Supplemental_file1_neuron_annotations.tsv` (139,248 rows) with the script
> `core_recount.py`, which is attached.

---

## 0. Verdict on your stage-1 report

**Your stop was correct and your findings are accepted in full.** Every quantity in your census
table was reproduced independently here, to the neuron and to the synapse:

| quantity | your measurement | reproduced |
|---|---:|:---:|
| AL projection neurons | 685 | yes |
| AL projection-neuron named types | 182 | yes |
| central-complex neurons | 2,875 | yes |
| central-complex named types | 229 (+1 unknown = 230) | yes |
| deduplicated core neurons | 13,300 | yes |
| core internal edges | 1,161,917 | yes |
| core internal synapses | 4,581,576 | yes |
| PAM06 carries positive nitric-oxide annotations | 2 neurons | yes |
| Kenyon cells with positive sNPF annotation | 4,133 | yes |

**The error was in the brief, not in your build.** You also correctly identified the cause: the
brief's `AL_PN` count of 2,960 was a mixed population. Its mask was
`cell_type.startswith('ORN') | cell_type.startswith('VP') | cell_class=='ALPN' | cell_class=='olfactory_projection'`,
which swept ORN-named receptor neurons into the projection-neuron block and double-counted them
against the brief's own separate ORN block. Your refusal to trim neurons to hit a number was the
right call, and "green tests do not turn a failed data gate into a pass" is exactly the discipline
the brief asked for. Keep it.

**Do not restart.** `build/validation_neuromod_sources.json`, the source hashes, the audit stage and
its tests are accepted work. Apply the corrections below, re-run the stage-1 gate against the new
reference table, and continue at stage 2 (`compartments.py`).

---

## 1. Supersedes §2.5 — the modulated core, defined by selector

The brief defined two blocks by cell-type name prefix. That was wrong twice over: prefix matching on
`cell_type` both misses annotated members and sweeps in non-members. Measured, for the
central complex: the brief's prefix list **missed 176 annotated CX neurons** — FR1, FR2, GLNO,
IbSpsP, LNO1, LNO2, LNOa, LPsP, P6-8P9, PFGs, CB4171 and 9 untyped — and **wrongly included 2
non-CX neurons** (FB1A, FB2B), for the net −174 you reported.

**The selector is the definition.** From here on the blocks are defined by annotation columns, and
these twelve lines of code are normative — if a count below disagrees with the code, the code wins:

```python
# root_id order = Completeness_783.csv row order; ct/cc/sc = cell_type/cell_class/super_class
BLOCKS = {
    "ORN":        (cc == "olfactory") & (sc == "sensory"),
    "AL_PN":      (cc == "ALPN"),
    "AL_LN":      (cc == "ALLN"),
    "KC":         ct.str.startswith("KC"),
    "MBON":       ct.str.startswith("MBON"),
    "DAN_MB":     ct.str.startswith(("PAM", "PPL1", "PPL2", "PAL")),
    "APL_DPM":    ct.str.startswith(("APL", "DPM")),
    "OA_VPM_VUM": ct.str.startswith(("OA-", "VPM", "VUM")),
    "CSD":        ct.str.startswith("CSD"),
    "CX":         (cc == "CX"),
    "DN":         (sc == "descending"),
    "ENDOCRINE":  (sc == "endocrine"),
}
CORE = union of all twelve masks          # deduplicated; see the overlap note below
```

Corrected reference table (`cognesia_core_partition_v2.csv` is attached and is the machine-readable
form):

| block | selector | neurons | left | right | named types | untyped |
|---|---|---:|---:|---:|---:|---:|
| ORN | `cell_class=='olfactory' & super_class=='sensory'` | 2,279 | 1,116 | 1,133 | 53 | 4 |
| AL_PN | `cell_class=='ALPN'` | 685 | 341 | 344 | 182 | 0 |
| AL_LN | `cell_class=='ALLN'` | 429 | 214 | 213 | 94 | 1 |
| KC | `cell_type` startswith `KC` | 5,177 | 2,580 | 2,597 | 11 | 0 |
| MBON | startswith `MBON` | 96 | 48 | 48 | 35 | 0 |
| DAN_MB | startswith `PAM`/`PPL1`/`PPL2`/`PAL` | 337 | 169 | 168 | 30 | 0 |
| APL_DPM | startswith `APL`/`DPM` | 4 | 2 | 2 | 2 | 0 |
| OA_VPM_VUM | startswith `OA-`/`VPM`/`VUM` | 43 | 15 | 15 | 18 | 0 |
| CSD | startswith `CSD` | 2 | 1 | 1 | 1 | 0 |
| CX | `cell_class=='CX'` | 2,875 | 1,438 | 1,437 | 229 | 9 |
| DN | `super_class=='descending'` | 1,299 | 645 | 646 | 472 | 0 |
| ENDOCRINE | `super_class=='endocrine'` | 76 | 37 | 39 | 10 | 0 |
| **CORE (union)** | — | **13,300** | — | — | — | — |

| core connectivity | value |
|---|---:|
| internal edges | **1,161,917** |
| internal synapses | **4,581,576** |

**The blocks are not disjoint, and that is correct, not a bug.** Exactly one overlap exists:
`AL_LN ∩ OA_VPM_VUM = 2 neurons`, both **OA-VUMa5** — an octopaminergic VUM neuron annotated as an
antennal-lobe local neuron. The block sum is 13,302; the deduplicated union is 13,300. Assert both
numbers, and assert that the overlap is exactly those two neurons of that one type, so a future
annotation change surfaces instead of silently shifting the core.

Two handling rules, which your report already anticipated and got right:

- **Retain untyped neurons in the block** (they are annotated members of the class) but **count type
  categories two ways**: named types, and named + 1 unknown. Report both. The table above lists
  named only; your 230 CX categories is the same number counted the other way and is not a
  disagreement.
- **Keep ORN and AL_PN strictly separate.** 2,279 receptor neurons and 685 projection neurons are
  different populations at different stages. Nothing in the build should sum them.

### 1.1 Unchanged — do not re-audit, these all matched

Your report confirmed these and the recount confirms them again. They stand as written in the brief:

- all eleven mushroom-body motif counts, including **KC→MBON 62,261 edges / 256,719 synapses**,
  KC→DAN 81,057, DAN→KC 47,404, DAN→MBON 2,035, MBON→DAN 2,383, MBON→MBON 1,343,
  KC→APL/DPM 10,390 / 204,929, APL/DPM→KC 9,251 / 107,934, AL_PN→KC 27,848 / 329,394,
  KC→KC 293,762;
- the whole-brain positive-transmitter audit (dopamine 1,395 / 27.3 % recovered, octopamine 68 /
  57.4 %, serotonin 197 / 9.1 %, tyramine 104 and histamine 11,129 with no predictor class);
- Defect D (5,172 of 5,177 Kenyon cells predicted dopaminergic, all 5,177 cholinergic by
  ground truth);
- the DAN inventory (PAM 307 / PPL1 16 / PPL2 8 / PAL 6 = 337), MBON 96 in 35 types, KC 5,177 in
  11 subtypes, OA-* 43 in 18 types with OA-AL2b2 excluded from the octopamine set on tyramine
  grounds, endocrine 76 in 10 types.

### 1.2 New rule — how to treat a future reference mismatch

The brief's "assert exactly or stop" was too blunt and it cost you a stage. Replace it with:

- **Primary data mismatch → stop.** Row counts, index bounds, the synapse sum, motif edge and
  synapse counts, transmitter-audit counts. These are properties of the release; a mismatch means
  the data changed and the build must halt.
- **Population-definition mismatch → report and proceed on the selector.** Block membership counts
  are properties of a *definition*. If the selector code in §1 yields a different count from the
  table, write the discrepancy to `build/` with expected/observed, use the selector's answer, and
  continue. Do not stall the pipeline on a definitional disagreement, and do not adjust a selector
  to reach a target count.

---

## 2. Supersedes §2.3 on cotransmission — nitric oxide is per neuron, not per type

The brief named four DAN types with positive nitric-oxide annotation. Measured, there are **five
types, and the annotation is partial within a type**:

| type | neurons with positive nitric-oxide annotation | of total |
|---|---:|---:|
| PAM01 | 40 | 41 |
| PAM05 | 20 | 21 |
| **PAM06** | **2** | **30** |
| PPL101 | 2 | 2 |
| PPL103 | 2 | 2 |

You were right to preserve PAM06. The design consequence is larger than one row: **cotransmitter
identity must be a per-neuron boolean derived from `known_nt`, never a per-type flag.** A per-type
flag would either lose PAM06's two neurons or wrongly promote all thirty. Build the nitric-oxide
source mask by parsing `known_nt` per neuron with the brief's `-negative`-stripping rule, and assert
the five counts above.

---

## 3. Resolves your KC / sNPF conflict — the brief contained a contradiction

You are right that the brief simultaneously required a peptide contribution from Kenyon-cell sNPF
and "zero Kenyon cells in any modulator source set." That is a genuine contradiction in the brief
and your decision — exclude KCs from the aminergic masks, retain the sNPF annotation separately,
report the literal assertion as conflicting — was the correct resolution. It is now the
specification. Measured: **4,133 of 5,177 Kenyon cells carry a positive sNPF annotation**, in seven
subtypes (KCg-m, KCab, KCg-d, KCg-s1, KCg-s2, KCg-s3, KCa'b'-ap1); brain-wide there are 5,034
positive sNPF sources, so **Kenyon cells are 82 % of the fly's sNPF source population.** They are
not an edge case to be excluded.

Replace brief rule §1.1 with:

> A neuron may be an **aminergic** source (dopamine, octopamine, serotonin, tyramine) only if
> `known_nt` positively asserts that amine or its `cell_type` is in the curated list. **Kenyon cells
> are excluded from every aminergic source mask** (Defect D). A neuron may independently be a
> **peptide** source for any peptide its `known_nt` positively asserts, and Kenyon cells are the
> largest sNPF source in the brain.

Replace the corresponding clause of gate V-NM-C with:

> Assert zero Kenyon cells in the dopamine, octopamine, serotonin and tyramine source masks.
> Assert exactly 4,133 Kenyon cells in the sNPF source mask, and 5,034 sNPF sources brain-wide.

sNPF *dynamics* remain out of scope for this stage — carry it as a source mask and a compartment
field with no receptor coupling until Layer 3, exactly as you have it.

---

## 4. Missing prerequisite — there is no odour input, and the brief assumed one

This is the brief's most serious omission and your report surfaced it: the base build is
**eye-only**. Every non-visual afferent receives zero input by design. But §7's protocols, and the
whole learning experiment, present odours. There is nothing to present them with.

Add a new module, `neuromod/odour.py`, before stage 5:

1. **Odour = a vector of activation over the 53 named ORN types.** Not over glomeruli, not over
   receptors — over the ORN types the annotation table actually contains, so the input lands on
   identified neurons.
2. **Source the response vectors, do not invent them.** DoOR 2.0 (Münch & Galizia 2016,
   PMID 26912260, doi:10.1038/srep21841) is a consensus database of *Drosophila* odorant responses
   per receptor/ORN class and is the right source; Hallem & Carlson's receptor-repertoire
   recordings (PMID 15210116, doi:10.1016/j.cell.2004.05.012) are the underlying measurement style.
   Map receptor/glomerulus identifiers onto FlyWire ORN type names via the canonical
   receptor-to-glomerulus assignment (Couto 2005, PMID 16139208, doi:10.1016/j.cub.2005.07.034).
   **Every mapped pair goes in `build/odour_orn_map.csv` with its source, and every ORN type that
   cannot be mapped is listed with zero response rather than filled in.** Report the coverage
   fraction — that number is itself a result.
3. **If DoOR cannot be obtained in this environment, do not fabricate responses.** Fall back to
   `odour_mode = synthetic`, which draws a reproducible sparse random activation vector from the
   seed, label every figure produced with it `SYNTHETIC ODOUR`, and say so in `REPORT.md`. A
   synthetic odour is adequate for the plasticity gates (V-NM-E, V-NM-F, V-NM-G) because those test
   *timing*, not odour identity — but it is **not** adequate for any claim about odour
   discrimination, generalisation or identity coding. Write that restriction into `LIMITATIONS.md`.
4. **Transduction:** ORN firing rate from the response vector through the same rectified,
   adapting stage the eye uses, then the connectome carries it. No hand-built AL transform. The
   published nonlinear AL gain and lateral interactions (Bhandawat 2007, PMID 17922008,
   doi:10.1038/nn1976; Olsen 2007, PMID 17408580, doi:10.1016/j.neuron.2007.03.010) are validation
   *targets*, not things to implement directly.
5. **Sparseness gate.** With an odour on, assert Kenyon-cell coding sparseness lands in 2–12 % of
   cells, against the published ~5–10 % (Lin 2014, PMID 24561998, doi:10.1038/nn.3660). If APL's
   measured connectivity does not produce sparseness in that range, **report it and do not add a
   compensating gain** — the APL arithmetic is unusually strong in this dataset (median 19 synapses
   per KC→APL edge against a brain-wide median of 2) and whether that suffices is a real question.
   For context on how PN→KC connectivity structure shapes this, see Ellis 2024 (PMID 38849331,
   doi:10.1038/s41467-024-48839-4).

---

## 5. Missing prerequisite — no behaviour decoder in this checkout

You are right that the extension cannot claim to reuse a validated descending-neuron decoder that
is not present. Restructure the readout so nothing blocks on it:

- **Primary readout, always available: compartment-weighted MBON valence.** Sum MBON activity
  weighted by the published appetitive/aversive assignment of its compartment, tagged
  `INFERRED_SIGN`. This needs nothing outside the model and is what V-NM-H and the capacity
  measurement of §11 should use.
- **Body readout: optional.** If the user supplies `dn_decoder.py` (the project's planar
  three-degree-of-freedom decoder, whose handle table is transcribed from published perturbation
  experiments), wire it as a downstream consumer of descending-neuron drive and add the trajectory
  readout. If it is absent, the behaviour lane renders as an explicit gap and V-NM-H reports on the
  MBON valence readout alone, marked `body readout NOT-RUN`. **Do not write a replacement decoder**
  — its gains are unmeasured assumptions in the original and a second invented version adds nothing.
- The capacity measurement of §11 does not depend on the body layer. Do not defer it.

---

## 6. The failed base-build V-C gate — do not block on it

V-C (pre-equilibration stationarity) is a gate on the base whole-brain build, not on this layer.
Handling:

- **Do not block stages 2–10 on V-C.** Record its failure in `REPORT.md` with the numbers you have.
- **Re-scope stationarity to what this layer actually needs**: assert that the **13,300-neuron core**
  pre-equilibrates and is stationary before stimulus onset, at the tolerance the base build uses.
  The core may settle even where the whole brain does not, and if it does, that is a usable result
  and a reportable difference between the two.
- **Report which cell types fail to settle**, with their firing rates, in both cases. Do not add
  damping, do not clamp, do not silence anything to reach stationarity.
- The visual biology gates (V-F to V-I of the base build) remain NOT-RUN and that is acceptable
  here, with one consequence: **gate V-NM-I (octopamine visual gain) cannot be evaluated** in this
  checkout, because it tests the modulator layer against visual machinery that has not been
  validated. Mark V-NM-I `NOT-RUN — depends on base V-G/V-H` and do not substitute a different
  measurement for it. Everything else in §10 is reachable without the visual gates.

---

## 7. Resume here

1. Re-run the stage-1 source audit against §1's table. It must now pass. Keep the nonzero-exit
   behaviour on mismatch; it worked.
2. Apply §2 (per-neuron cotransmitter masks, five nitric-oxide types) and §3 (aminergic versus
   peptide source rule, 4,133 sNPF Kenyon cells) and extend the V-NM-C assertions accordingly.
3. Stage 2: `compartments.py`. The empirical mushroom-body clustering and its disagreement report
   are unchanged, and are now the first genuinely new result of the build.
4. Stage 3 onward as the brief's §12 order, with §4's `odour.py` inserted before stage 5 and §5's
   readout restructuring folded into the plasticity stage.
5. The §3.3 single-synapse reference curve is unchanged and remains the first test to write in
   stage 5. Your independent audit of it in `neuromod_reference_findings.md` is welcome input —
   if you found a discrepancy in those twelve values, state it plainly and I will recompute rather
   than have you fit around it.

Acceptance is unchanged except that `flybrain neuromod build` must now exit zero.
