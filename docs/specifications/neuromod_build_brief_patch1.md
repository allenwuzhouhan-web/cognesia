# Build prompt: neuromodulator state, endocrine state, three-factor plasticity and a real-time console for `flybrain`

> Paste everything below the line into Codex or Claude Code. It assumes the `flybrain` package from
> `cognesia_flybrain_build_prompt.md` already exists (or will be built from it first); §2.0 says what
> to do if it does not.
> Every number in **§2 Verified facts** was measured directly from the released data files on
> 2026-09-26, in this environment, with the scripts named beside it. Every citation in §12 was
> resolved against PubMed the same day. **Do not "correct" any of them from memory.**
>
> **Read `cognesia_neuromod_patch1.md` with this file.** It supersedes rule §1.1, the cotransmission
> paragraph of §2.3, the core table in §2.5 and gates V-NM-C and V-NM-I; it adds an odour input
> module (this brief wrongly assumed one existed — the base build is eye-only) and restructures the
> behaviour readout so nothing blocks on an absent descending-neuron decoder.

---

## 0. Mission

Add a **neuromodulatory and endocrine layer** to the connectome-constrained *Drosophila* brain
model, together with **three-factor plasticity** on the mushroom-body output synapses and a
**real-time console** for driving and reading the result.

The point of the addition is a single capability the base model does not have: the base model is a
fixed function from sensory input to descending-neuron output. After this build, the same input can
produce a different output because of (a) what modulator is present in which compartment, (b) what
the animal's internal state is, and (c) what happened to the network earlier in the session. That is
the difference between a circuit simulator and a **programmable** brain model, and it is the whole
project.

Concretely, when this build is finished the following must be possible, live, on one Mac:

1. Present odour A, pulse a dopaminergic compartment 500 ms later, and watch the KC→MBON weights in
   that compartment depress while the rest of the matrix stays put.
2. Present odour A again and watch the modelled behaviour change, with nothing else altered.
3. Reverse the pairing order (dopamine first, odour second) and get plasticity of **the opposite
   sign**, because the two dopamine receptor pathways have different temporal kernels
   (Handler 2019, PMID 31230716).
4. Raise octopamine and watch visual gain rise (Suver 2012, PMID 23142045) without touching a
   synaptic weight.
5. Flip the animal from fed to starved and watch the same odour produce a different decision,
   through the insulin/AKH-driven state layer acting on the PAM dopaminergic neurons.
6. Do all of it at **≥1.0 × real time** for the 13,126-neuron modulated core, and log every knob
   turn so the session replays bit-exactly.

Target machine: macOS on Apple Silicon, 18 CPU cores, 64 GB RAM, no CUDA GPU. Hard memory ceiling
40 GB resident. Real-time targets and the measured budget are in §8.

### 0.1 How to execute this in one pass

This prompt is written to be completed without asking questions. Work through §12's order and obey
the following:

1. **Do not ask for clarification.** Every decision this build needs is either specified below or is
   explicitly yours to make; where it is yours, make it, write it in `config/neuromod.yaml` with the
   tag `ASSUMPTION`, and move on.
2. **Inspect every downloaded file before writing code against it** (schema, dtypes, row count,
   three rows), and assert the counts in §2 exactly. If an assertion fails, stop that stage and
   record it in `REPORT.md` — a changed upstream release is a finding, not something to work around.
3. **Every stage ends with its own test passing.** The gate list in §10 maps one-to-one onto the work
   order in §12. Do not move to the next stage with a red software gate. `pytest -q` must be green
   at every commit.
4. **Build headless first, console last.** Stages 1–7 have no UI. If time runs short, a complete
   headless engine with a recorded session and no console is a better outcome than a console over an
   unvalidated engine.
5. **Reference numbers are provided so you can self-verify without me.** §2 has the data counts,
   §3.3 has a twelve-point pairing-curve reference table, §8 has the measured performance budget.
   Write each of them into a test.
6. **Acceptance, in one command:** `flybrain neuromod build && pytest -q && flybrain train
   protocols/forward_pairing_gamma1.yaml && flybrain capacity && flybrain rt serve --core` must run
   clean from a fresh checkout, and `REPORT.md` must exist with every §10 gate given a row and a
   number. Print the measured real-time factor and the pairing-curve crossover to stdout at the end.

### 0.2 What this build must not claim

The project brief for this work asked for neuromodulator dynamics that "resemble perfectly those of
a fly." **That is not attainable and the build must not be written as though it were.** The
measurements in §2.1 show why: the released connectome does not know where dopamine is released, it
does not contain a single receptor, and no published work gives absolute modulator concentrations in
any fly brain compartment. What *is* attainable, and what this build delivers, is:

| Attainable | Not attainable |
|---|---|
| Identified release sources, taken from ground-truth transmitter labels and named cell types | A per-synapse map of where dopamine acts |
| Published time constants for clearance, eligibility and memory decay | Absolute concentrations in molar units |
| Per-compartment plasticity **signs** measured in real flies (Aso 2016, PMID 27441388) | Per-synapse plasticity magnitudes |
| Receptor→effect couplings for the handful of receptors with published loss-of-function phenotypes | A quantitative receptor expression level per neuron |
| Reproducing published pairing curves the model was never fitted to | Claiming the model *is* a fly |

Write that table into `LIMITATIONS.md` in the first commit, not the last.

---

## 1. Non-negotiable rules

These extend, and do not replace, the rules in the base build prompt.

1. **Modulator sources come from ground truth, never from the EM transmitter predictor.**
   A neuron may be a dopaminergic, octopaminergic or serotonergic *source* only if it satisfies one
   of: (a) `known_nt` positively asserts that transmitter (see §2.1 for the parsing rule), or (b) its
   `cell_type` is in the curated source list in §2.3. Using `top_nt` for modulators is a measured
   error of the size documented in §2.1 and §2.2, and the build must actively assert against it.
2. **Every concentration is dimensionless and normalized.** No field is in nM or µM. Each
   modulator field is scaled so that 1.0 = the peak reached by maximal drive of that modulator's own
   source population in its own compartment. Any code that prints a concentration prints it as
   `a.u.`. Any figure axis says `a.u.`
3. **Modulation acts on parameters, not by injecting current.** A modulator changes a gain, a
   threshold, a release probability, a time constant or a plasticity rate. It never appears as a
   synaptic current term. Adding "dopamine current" to a neuron is the failure mode this rule exists
   to forbid.
4. **Volume transmission is not a synapse.** Modulator spread is a compartment field (§4), not
   propagation along connectome edges. Do not add modulatory edges to the connectivity matrix. Where
   a modulatory neuron *also* has conventional fast synapses in the connectome (many DANs do), those
   stay in the base matrix and do their normal job.
5. **Plasticity is bounded, signed per compartment, and logged.** Every weight change is clipped to
   `[0, w_max]`, the sign rule per compartment comes from a citation or is tagged `ASSUMPTION`, and
   the total absolute weight change per trial is written to the run log.
6. **Provenance on every parameter, same discipline as the base build.** `config/neuromod.yaml`
   carries, per parameter: value, unit, and `source: <PMID|DOI>` or the literal `ASSUMPTION`.
   Anything `ASSUMPTION` gets a sensitivity sweep in the report. Add two new tags for this layer:
   `SCRNA` (expression-derived, semi-quantitative) and `INFERRED_SIGN` (sign from a behavioural
   phenotype, magnitude free).
7. **Never tune to pass a biology gate.** §10 separates software gates (must pass) from biology
   gates (may fail; a failure is a result). The pairing-curve gates in particular are the model's
   falsification test. If the model cannot reproduce the asymmetry of forward vs backward pairing,
   that is the finding — write it down.
8. **The UI is not allowed to invent.** Any quantity the console displays is either computed by the
   engine this session or loaded from a named file. The console never interpolates, smooths for
   looks, or displays a plausible default in place of a missing value. A missing value renders as an
   explicit gap. (The existing `cognesia_control_panel.html` already sets this precedent: its
   stimulus tab stays empty until real descending-neuron activity is loaded. Keep that behaviour.)
9. **Determinism under interaction.** Every user action in the console is recorded as
   `(t_sim_ms, control_id, value)`. Replaying that event list with the same seed and config must
   reproduce the run bit-exactly. A knob-twiddling session that cannot be replayed is not an
   experiment.

---

## 2. Verified facts

### 2.0 Prerequisite

This build needs, from the base build: the neuron table in `Completeness_783.csv` row order
(138,639 neurons), the CSR connectivity matrix, and the annotation table
`Supplemental_file1_neuron_annotations.tsv` (139,248 rows, 31 columns). If `flybrain` does not exist
yet, build it from `cognesia_flybrain_build_prompt.md` first and do not start this layer until its
V-A gate passes. The measurements below were made with three short scripts that the build should
keep and re-run as tests: `neuromod_census.py`, `mb_edges.py`, `nt_positive.py`.

### 2.1 The transmitter predictor fails specifically on the modulators (measured)

`known_nt` is the ground-truth column (populated from immunostaining, RT-PCR, FISH and scRNA-seq;
51,411 of 139,248 rows are empty). `top_nt` is the EM-image prediction of Eckstein et al. 2024
(PMID 38729112), which has **six classes: acetylcholine, dopamine, gaba, glutamate, octopamine,
serotonin.** Parsing rule used below, and the one the build must use: split `known_nt` on `;` and
`,`, drop every fragment ending in `-negative`, then match the remaining fragments. Counting a
`dopamine-negative` annotation as evidence of dopamine is the obvious bug here; assert against it.

| transmitter | neurons with positive `known_nt` | neurons predicted by `top_nt` | agree | **% of ground truth recovered** |
|---|---|---|---|---|
| acetylcholine | 52,053 | 86,193 | 44,999 | 86.4 % |
| GABA | 9,089 | 19,171 | 7,438 | 81.8 % |
| glutamate | 11,378 | 24,875 | 9,139 | 80.3 % |
| **dopamine** | **1,395** | **5,909** | **381** | **27.3 %** |
| **octopamine** | **68** | **216** | **39** | **57.4 %** |
| **serotonin** | **197** | **2,282** | **18** | **9.1 %** |
| tyramine | 104 | 0 (no class) | 0 | 0 % |
| histamine | 11,129 | 0 (no class) | 0 | 0 % |

Read the last column. The predictor is good for the three fast transmitters that carry the wiring
diagram and **poor to useless for every modulator** — it recovers one in four known dopaminergic
neurons and one in eleven known serotonergic neurons, while over-calling both by roughly 4× and 12×
respectively. Tyramine and histamine cannot be predicted at all because the classifier has no class
for them, which is also the root cause of Defect A in the base build (the 11,129 known histaminergic
neurons include the photoreceptors).

**This is the single most important fact in this build prompt.** It means a neuromodulation layer
built on `top_nt` would put dopamine in mostly the wrong places. It also means the audit above is a
reportable result in its own right: any connectome model that reads modulator identity off the EM
prediction inherits this error.

### 2.2 Defect D — the mushroom body is predicted to be dopaminergic (measured)

| quantity | value |
|---|---|
| Kenyon cells in v783 | 5,177 |
| of those, `top_nt == dopamine` | **5,172** |
| of those, `known_nt` positively asserts acetylcholine | **5,177** (all of them) |
| share of all predicted-dopaminergic neurons that are Kenyon cells | **87.6 %** (5,172 of 5,905) |

Kenyon cells are cholinergic and co-release sNPF (`known_nt` = `acetylcholine; sNPF` for KCg and
KCab subtypes; sources cited in the annotation file include Barnstedt 2016 PMID 26948892 and
Aso 2019). The prediction is wrong for every one of them. A model that reads `top_nt` therefore
turns the entire mushroom body into a dopamine source — the exact opposite of the architecture,
where dopamine is the teaching signal *arriving at* Kenyon-cell terminals.

Handle it exactly as Defects A–C are handled in the base build: an explicit override table, written
to `build/neuromod_overrides.csv`, with the count of affected neurons, and a test that fails if the
override is not applied.

### 2.3 The modulatory source inventory (measured)

Counts are over the 139,248-row annotation table; `n_left`/`n_right` from the `side` column.

**Mushroom-body dopaminergic neurons — 337 neurons, 30 types:**

| cluster | neurons | types | per-type counts |
|---|---|---|---|
| PAM | 307 | 15 | PAM08 45, PAM01 41, PAM04 32, PAM06 30, PAM12 23, PAM05 21, PAM07 18, PAM02 16, PAM11 16, PAM14 16, PAM10 15, PAM13 12, PAM03 10, PAM09 9, PAM15 3 |
| PPL1 | 16 | 8 | PPL101–PPL108, 2 each (1 left, 1 right) |
| PPL2 | 8 | 4 | PPL201–PPL204, 2 each |
| PAL | 6 | 3 | PAL01–PAL03, 2 each |

All 337 have `known_nt` positively asserting dopamine. Four of these types additionally carry
`dopamine, nitric oxide` in `known_nt` — **PAM01, PAM05, PPL101, PPL103** — which matches the
cotransmission result of Aso et al. 2019 (PMID 31724947, doi:10.7554/eLife.49257). PPL105 carries
`dopamine, sNPF`. Implement nitric oxide as a fifth modulator species with its own (much shorter,
freely diffusing) compartment kernel, or omit it and say so in `LIMITATIONS.md` — but do not
silently drop the annotation.

**Whole-brain dopaminergic ground truth: 1,395 neurons** — 980 in `super_class = optic`, 408
`central`, 7 `visual_centrifugal`. The optic ones matter: they mean dopaminergic modulation of the
visual front end is in scope, not just the mushroom body.

**Octopaminergic / tyraminergic — 43 neurons in 18 `OA-*` types**, including OA-VPM3 (2), OA-VPM4
(2), OA-VUMa1–a8 (2 each, a8 has 1), OA-AL2i1–i4, OA-AL2b1, OA-AL2b2, OA-ASM1–ASM3. Note
**OA-AL2b2 (4 neurons) has `known_nt = tyramine`, not octopamine** — do not put it in the
octopamine source set because of its name. Whole-brain octopamine ground truth is 68 neurons;
tyramine 104.

**Serotonergic — 197 neurons of positive ground truth**, including the named types CSD (2),
DPM (2), 5-HTPMPD01, 5-HTPMPV01, 5-HTPMPV03, and a long tail in the fan-shaped body (FB1H, FB2B,
FB4M, FB4Y, FB6H, FB7B), central complex (ExR3, Delta7) and descending population (DNg26, DNg28,
DNg30). DPM's `known_nt` also carries `amnesiac`, the neuropeptide gene product required for
middle-term memory.

**Endocrine — 76 neurons in the model subset (80 in the annotation file), 10 named types:**

| cell_class | cell_type | n | peptide(s) in `known_nt` |
|---|---|---|---|
| pars intercerebralis | IPC | 18 | DILP2, DILP3, DILP5; dARC1 |
| pars intercerebralis | mNSC_unknown | 10 | — |
| pars intercerebralis | DH44 | 6 | Dh44 |
| pars intercerebralis | DMS | 6 | myosuppressin |
| pars intercerebralis | lNSC_unknown | 2 | — |
| pars lateralis | lNSC_unknown | 12 | — |
| pars lateralis | ITP | 8 | ITP, tachykinin, sNPF, leucokinin |
| pars lateralis | CRZ | 6 | corazonin, sNPF |
| pars lateralis | DH31 | 6 | Dh31 |
| (none) | CAPA | 2 | capability, myosuppressin |
| (none) | Hugin-RG | 4 | hugin |

These 76 neurons are the entire hormonal write-interface of the brain in this dataset, and two of
the eleven rows are unidentified neurosecretory cells. That is the honest size of the endocrine
layer: eight identified peptide families, four of them co-expressed in one cell type (ITP).

### 2.4 The mushroom-body circuit, measured from `Connectivity_783.parquet`

Blocks: `KC` 5,177 neurons (11 subtypes: KCg-m 2,189, KCab 1,643, KCapbp-m 338, KCapbp-ap2 298,
KCg-d 295, KCapbp-ap1 280, KCab-p 128, KCg-s1/s2/s3 and KCa'b'-ap1 1–2 each); `MBON` 96 neurons in
35 types; `DAN_MB` 337; `APL` 2; `DPM` 2.

| motif | edges | synapses | median syn/edge |
|---|---|---|---|
| **KC → MBON** (the plastic matrix) | **62,261** | **256,719** | 3 |
| KC → DAN | 81,057 | 125,134 | 1 |
| DAN → KC | 47,404 | 60,657 | 1 |
| KC → APL/DPM | 10,390 | 204,929 | 19 |
| APL/DPM → KC | 9,251 | 107,934 | 12 |
| MBON → MBON | 1,343 | 19,983 | 3 |
| MBON → DAN | 2,383 | 9,009 | 2 |
| DAN → MBON | 2,035 | 15,325 | 3 |
| APL/DPM → MBON | 193 | 6,910 | 11 |
| AL projection neurons → KC | 27,848 | 329,394 | 11 |
| KC → KC | 293,762 | 379,338 | 1 |

Four consequences for the design:

- The plastic matrix is **62,261 float32 weights = 249 kB.** Updating all of them every 0.1 ms step
  costs nothing. Plasticity is not the performance problem; nothing about it needs approximation.
- **KC → DAN (81,057 edges) is larger than KC → MBON.** The Kenyon cells drive their own teaching
  signal. Together with MBON → DAN (2,383) this closes the recurrent loop that makes memory
  dynamics interesting (Eschbach 2020, PMID 32203499; Felsenberg 2018, PMID 30245010) — and it means
  plasticity changes the teaching signal, so the loop must be simulated, not fed an open-loop
  dopamine schedule.
- **KC → KC has 293,762 edges** at a median of 1 synapse. Most of it is likely reconstruction noise
  at the threshold. Make it a switch (`kc_kc_mode = off | as_released | thresholded`), default
  `thresholded` at ≥2 synapses, and report the difference. Do not leave this unexamined; it is a
  third of a million edges inside the structure you are studying.
- APL is the sparseness enforcer, and its arithmetic is lopsided: 10,390 KC→APL edges carrying
  204,929 synapses in, 9,251 edges and 107,934 synapses back out, i.e. a median of 19 and 12
  synapses per edge against a brain-wide median of 2. APL's inhibition is strong and global by
  construction (Lin 2014, PMID 24561998).

### 2.5 The modulated core (measured)

**Corrected 2026-09-26 — see `cognesia_neuromod_patch1.md` §1.** An earlier version of this table
defined the AL-projection-neuron and central-complex blocks by cell-type name prefix, which swept
ORN-named receptor neurons into the projection-neuron block and missed 176 annotated central-complex
neurons. The selector column below is normative; if a count disagrees with the selector, the
selector wins.

| block | selector | neurons | named types | untyped |
|---|---|---:|---:|---:|
| olfactory receptor neurons | `cell_class=='olfactory' & super_class=='sensory'` | 2,279 | 53 | 4 |
| AL projection neurons | `cell_class=='ALPN'` | 685 | 182 | 0 |
| AL local neurons | `cell_class=='ALLN'` | 429 | 94 | 1 |
| Kenyon cells | `cell_type` startswith `KC` | 5,177 | 11 | 0 |
| MBON | startswith `MBON` | 96 | 35 | 0 |
| DAN (MB) | startswith `PAM`/`PPL1`/`PPL2`/`PAL` | 337 | 30 | 0 |
| APL + DPM | startswith `APL`/`DPM` | 4 | 2 | 0 |
| OA-* | startswith `OA-`/`VPM`/`VUM` | 43 | 18 | 0 |
| CSD | startswith `CSD` | 2 | 1 | 0 |
| central complex | `cell_class=='CX'` | 2,875 | 229 | 9 |
| descending | `super_class=='descending'` | 1,299 | 472 | 0 |
| endocrine | `super_class=='endocrine'` | 76 | 10 | 0 |
| **union (deduplicated)** | — | **13,300** | — | — |

Blocks are not disjoint: `AL_LN ∩ OA_VPM_VUM` = 2 neurons, both **OA-VUMa5**, an octopaminergic VUM
annotated as an antennal-lobe local neuron. Block sum 13,302, union 13,300 — assert both.

Internal connectivity of that core: **1,161,917 edges, 4,581,576 synapses.** CSR float32 with int32
indices ≈ **9.3 MB.** This is the network the real-time mode simulates. The whole brain is
138,639 neurons / 15,091,983 edges / 121.3 MB CSR, and §8 shows it does not run at real time here.
The §8 performance numbers were measured on the 13,126-neuron earlier core; the corrected core is
2.3 % larger in edge count, so read those figures as accurate to ~3 % and re-measure.

---

## 3. Architecture

Five layers. Layers 0 and 1 exist; 2–4 are this build. Keep them in separate modules with narrow
interfaces, the same way `dn_decoder.py` and `flybrain` were kept independent.

```
Layer 0  fast network        connectome edges, LIF + graded, dt = 0.1 ms          (base build)
Layer 1  sensory front end   eye, antennal lobe                                    (base build)
─────────────────────────────────────────────────────────────────────────────────────────────
Layer 2  modulator field     C[modulator, compartment](t), dt_mod = 1 ms          THIS BUILD
Layer 3  receptor → effect   C  ->  gain, threshold, release prob, tau            THIS BUILD
Layer 4  plasticity          three-factor rule on 62,261 KC→MBON weights          THIS BUILD
Layer 5  endocrine state     hunger, thirst, arousal, circadian; dt_state = 1 s   THIS BUILD
```

Data flows down (state modulates the network) and up (network activity drives release), and the only
coupling between layers is through explicitly named arrays. The engine must be runnable headless
with every layer above 1 disabled, and must then reproduce the base build's output bit-exactly. Make
that a test (V-NM-A).

### 3.1 Layer 2 — the modulator field

For modulator *m* and compartment *k*:

```
dC[m,k]/dt  =  −C[m,k] / τ_clear[m]  +  α[m] · Σ_{i ∈ sources[m,k]} r_i(t)  +  σ[m] · Σ_{k' ~ k} (C[m,k'] − C[m,k])
```

- `r_i(t)` is the source neuron's instantaneous rate (spiking sources) or rectified release
  (graded sources) — the same quantity the base engine already computes.
- `τ_clear[m]` is the modulator's clearance time constant. Dopamine's is set by reuptake through
  DAT; use the fastest published estimate available and tag it, because the whole timing story
  depends on it. Octopamine and serotonin are slower, peptides slower still, hormonal signals
  slowest.
- `σ[m]` is spillover to adjacent compartments — small for dopamine (compartment boundaries in the
  mushroom body are functionally tight: Cohn 2015, PMID 26687359), larger for nitric oxide, and for
  hemolymph-borne peptides the "compartment" is a single global pool so σ is irrelevant.
- `α[m]` is normalized so that full drive of the source population gives `C = 1.0` at steady state
  (rule §1.2).

Size: 6 modulator species × ~120 compartments ≈ 720 float32. Updating it at 1 kHz is free. **This is
the entire reason the design is tractable:** the expensive part of a fly brain is the 15 million fast
edges, and the modulatory state that makes it programmable is under a kilobyte.

Suggested species list: `DA`, `OA`, `5HT`, `NO`, `sNPF`, `peptide_pool` (with the hormonal peptides
resolved individually inside Layer 5). Add `TA` (tyramine) if the 104 known tyraminergic neurons are
included as sources — recommended, since OA-AL2b2 is in the OA-named set but is tyraminergic.

### 3.2 Layer 3 — receptor → effect

A table, `config/receptors.csv`, one row per (modulator, receptor, target cell-type pattern, effect):

| column | meaning |
|---|---|
| `modulator` | DA, OA, 5HT, … |
| `receptor` | Dop1R1, Dop1R2, Dop2R, DopEcR, OAMB, Octβ1R, Octβ2R, Octβ3R, 5-HT1A/1B/2A/2B/7, mAChR-A/B, sNPFR, … |
| `target` | cell-type regex (`^KC`, `^MBON1[0-9]$`, `^PAM`, `^HS|^VS`) |
| `effect` | `gain`, `v_th`, `release_prob`, `tau_m`, `plasticity_rate`, `plasticity_sign` |
| `edge_scope` | for `release_prob`: which edge set the change applies to (`KC->MBON`, `all_out`, …) |
| `magnitude` | signed, dimensionless; the fractional change at `C = 1.0` |
| `kernel` | `linear`, `hill(n,K)`, `biphasic` |
| `provenance` | PMID/DOI, or `SCRNA`, `INFERRED_SIGN`, `ASSUMPTION` |

Seed rows the build must include, each with the citation in §12:

- **Dop1R1 on KC presynaptic terminals** → depression of `KC->MBON` release when dopamine follows KC
  activity (Handler 2019; Hige 2015, PMID 26637800). Fast kernel.
- **Dop1R2 (DAMB) on KC terminals** → plasticity of the opposite sign, and the substrate of
  dopamine-driven forgetting (Handler 2019; Himmelreich 2017, PMID 29166600; Shuai 2015,
  PMID 26627257). Slower, Gq/Ca²⁺-coupled kernel.
- **Dop2R** → autoreceptor, reduces DAN excitability and release. `INFERRED_SIGN`.
- **Octβ2R on PAM dopaminergic neurons** → the octopamine→dopamine reward relay (Burke 2012,
  PMID 23103875).
- **Octopamine on wide-field visual neurons (HS/VS)** → gain and temporal-frequency tuning shift
  during flight (Suver 2012, PMID 23142045). This is the one modulator effect in the model that the
  base build's *visual* validation gates can test directly.
- **mAChR-B on Kenyon cells** → inhibitory muscarinic autoreceptor, required for aversive learning
  (Bielopolski 2019, PMID 31215865). This is the honest place for acetylcholine in a *modulatory*
  layer: ACh's fast ionotropic action is already Layer 0; only the metabotropic receptors belong
  here. If the project brief says "acetylcholine-stimulated," this row is what that means.
- **sNPF from Kenyon cells** → presynaptic modulation within the mushroom body; sources for KC sNPF
  are in the annotation file (`known_nt = acetylcholine; sNPF`), receptor coupling `ASSUMPTION`.
- **5-HT on antennal-lobe processing via CSD** → gain/lateral-inhibition change. `INFERRED_SIGN`.

Expression, i.e. *which* neurons carry which receptor, is not in the connectome. Sources, in order of
preference: the Fly Cell Atlas single-nucleus data (Li 2022, PMID 35239393, doi:10.1126/science.abk2432)
for per-cell-type expression; the chemoconnectome genetic toolkit (Deng 2019, PMID 30799021) for
ligand/receptor gene coverage; mushroom-body-specific transcriptomics (Crocker 2016, PMID 27160913).
Every row so derived is tagged `SCRNA` and **must not be presented as a measured coupling strength.**
If a receptor's expression cannot be sourced, the row is `ASSUMPTION` and gets swept.

### 3.3 Layer 4 — three-factor plasticity

On the 62,261 KC→MBON edges only, by default. (`plastic_scope` may extend it to `MBON->DAN` and
`PN->KC`; both off by default, each a separate sensitivity run.)

Per synapse *j* from KC *p* to MBON *q* in compartment *k*:

```
dE_pre[p]/dt  = −E_pre[p]/τ_pre      + r_p(t)             # KC eligibility, read by the Dop1R1 branch
dE_da[k]/dt   = −E_da[k]/τ_da_trace  + C[DA,k](t)         # dopamine trace, read by the Dop1R2 branch
dw[j]/dt = −η · ( A1 · C[DA,k](t) · E_pre[p]  −  A2 · r_p(t) · E_da[k] )
           − (w[j] − w0[j]) / τ_forget · (1 + β · C[DA,k])
w[j] ← clip(w[j], 0, w_max · w0[j])
```

**Read the two terms carefully — this is the one equation in the build that is easy to get wrong.**
The first term fires only when Kenyon-cell activity *preceded* dopamine (the KC trace is still
decaying when dopamine arrives) and it **depresses**. The second fires only when dopamine *preceded*
Kenyon-cell activity (the dopamine trace is still decaying when the odour arrives) and it
**potentiates**. A rule built from two presynaptically-driven eligibility traces — the obvious first
guess, and the shape a naive reading of "two receptors, two time constants" suggests — **cannot
produce backward-pairing plasticity at all**: with no prior KC activity both traces are zero when
dopamine arrives, so `dw = 0` and the pairing curve is one-sided. Do not implement that version.

Note also what carries the traces. `E_pre` is indexed by **presynaptic neuron, not by synapse**
(5,177 floats), because the presynaptic factor is the only synapse-specific quantity in it, and
`E_da` is indexed by **compartment** (15 floats). So the whole plasticity state is
5,177 + 15 + 62,261 floats ≈ 270 kB, and the inner loop is one pass over the 62,261 edges.

What is cited versus assumed:

- **The existence, sign and temporal asymmetry** of the two branches is measured: Handler et al.
  2019 (PMID 31230716) is titled for exactly this, and Dop1R1 and Dop1R2 have different kinetics and
  opposite consequences for forward versus backward pairing. `τ_pre`, `τ_da_trace`, `A1`, `A2` are
  `ASSUMPTION` and must be fitted **only** to the published pairing curve, once, then held fixed for
  every other gate. Record which data were used for the fit in `PARAMETERS.md`.
- **Reference values to test against.** With `τ_pre = 600 ms`, `τ_da_trace = 1500 ms`,
  `τ_clear[DA] = 400 ms`, `A1 = 1.00`, `A2 = 0.55`, `η = 0.055`, a 1,000 ms odour, a 500 ms dopamine
  pulse, `w0 = 1`, `dt = 1 ms`, and **Δt defined as dopamine onset minus odour onset**, the rule
  above integrates to (computed 2026-09-26; use as a unit test, tolerance 1e-3):

  | Δt (ms) | −2000 | −1500 | −1000 | −750 | −500 | −250 | 0 | +250 | +500 | +1000 | +1500 | +2000 |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|
  | Δw | +0.0293 | +0.0367 | +0.0364 | +0.0260 | −0.0011 | −0.0527 | −0.1104 | −0.1480 | −0.1563 | −0.0908 | −0.0395 | −0.0171 |

  Peak depression at Δt ≈ +500 ms, potentiation for Δt ≤ −750 ms, **crossover at Δt ≈ −510 ms.**
  The crossover sits left of zero because a 500 ms dopamine pulse starting 500 ms before the odour
  still overlaps it; full temporal separation is what lets the potentiating branch win. **That
  crossover position is a model output, not a target — do not tune it toward zero.** Report it and
  compare its position with the published curve in the DIVERGENCE view.
- **The multiplicative `C[DA,k]` term** is the third factor and is what makes the rule
  compartment-specific: dopamine in γ1 changes γ1 synapses and nothing else (Cohn 2015; Aso 2016).
- **Per-compartment sign and magnitude.** Aso & Rubin 2016 (PMID 27441388) is titled for exactly
  this: dopaminergic neurons write and update memories *with cell-type-specific rules*. Encode the
  per-compartment rule as a table with one citation per row, not as a single global constant.
- **The decay term with the `β · C[DA,k]` factor** is dopamine-driven forgetting through Dop1R2
  (Berry/Davis line of work; Shuai 2015; Himmelreich 2017). `τ_forget` is `ASSUMPTION`, order
  minutes to hours; it is what makes a session's memory fade while you watch, which the console must
  display honestly rather than hide.

Cost: two traces plus a weight per edge = 3 × 62,261 float32 = 747 kB, three vector operations per
step. Negligible (measured in §8).

### 3.4 Layer 5 — endocrine and behavioural state

A small state vector, updated at 1 Hz, with its own slow dynamics and its own write-interface:

| state | driven by | acts on |
|---|---|---|
| `energy` (fed ↔ starved) | simulated feeding minus metabolic drain | IPC DILP release ↑, corazonin/AKH axis ↓; gates PAM excitability |
| `hydration` | simulated drinking minus loss | ITP and leucokinin release; gates water-seeking valence |
| `arousal` | flight/walking state from the body layer | octopamine source drive (closes the Suver 2012 loop) |
| `circadian_phase` | clock, free-running | baseline dopamine and serotonin tone |
| `stress` | prolonged aversive input | DH44, corazonin |

Each state variable acts **only** by scaling source drive or a Layer-3 row — never directly on a
neuron. Then `energy` changing the meaning of an odour is an emergent consequence of the same
machinery, not a special case. The one fact the build must respect: the endocrine write-interface is
76 neurons (§2.3), not a free-floating global multiplier, so each state variable must name the
cell types it drives.

---

## 4. Compartments

The compartment set is the spatial grid of Layer 2, and getting it right matters more than any
single parameter.

1. **Mushroom body — 15 compartments** (γ1–γ5, β'1, β'2, β1, β2, α1, α2, α3, α'1, α'2, α'3), the
   canonical division of Aso et al. 2014 (PMID 25535793, doi:10.7554/eLife.04577).
   **Assign them empirically, do not hard-code neuron lists.** Procedure: for each DAN type and each
   MBON type, take its KC partner vector from the connectivity matrix; cluster DANs and MBONs
   jointly on KC-partner overlap (Jaccard); the resulting blocks are the compartments. Then check the
   clustering against the published DAN/MBON-to-compartment assignment and **report the
   disagreements** — the count of mismatches is a real measurement about the dataset, and finding
   none is also informative. Write `build/mb_compartments.csv` with, per compartment: DAN types, MBON
   types, KC count, KC→MBON edge count.
2. **Antennal lobe — one compartment per glomerulus**, from ORN and PN type names (~54 ORN types are
   in the core inventory). Needed for CSD serotonergic modulation of olfactory gain.
3. **Central complex** — EB ring, FB layers, PB, NO, as separate compartments (~10–15).
4. **Optic lobe** — coarse: lamina, medulla, lobula, lobula plate per side, which is enough for the
   octopamine flight-gain effect and for the 980 known dopaminergic optic neurons.
5. **Hemolymph** — one global pool for the endocrine peptides. Its "clearance" is the slowest time
   constant in the model.

Total ~120 compartments. Each compartment declares its neuron membership (a boolean mask) and its
adjacency (for σ spillover). Write it once at build time into `build/compartments.npz` and hash it
into the run manifest.

---

## 5. Module layout

Add to the existing package; do not restructure it.

```
src/flybrain/
  neuromod/
    __init__.py
    sources.py        # ground-truth source selection (§2.1 parsing rule, §2.3 lists), Defect D override
    compartments.py   # §4, incl. the empirical MB clustering and its disagreement report
    field.py          # Layer 2 integrator (numba)
    receptors.py      # Layer 3 table loader + effect application
    plasticity.py     # Layer 4 (numba)
    state.py          # Layer 5
    protocol.py       # training protocols as data: odour blocks, DAN pulses, tests, ITIs
    capacity.py       # §11 write-capacity measurement
  rt/
    engine_rt.py      # real-time loop, fixed-lag scheduler, frame budget accounting
    bridge.py         # WebSocket server, binary frame encoder, control-event recorder
    replay.py         # deterministic replay from an event log
config/
  neuromod.yaml       # every parameter with provenance
  receptors.csv
  compartment_rules.csv
console/              # §9
  index.html
  app.js
  gl/                 # shaders for the atlas and raster views
tests/
  test_neuromod.py    # V-NM-A … V-NM-E
  test_learning.py    # V-NM-F … V-NM-J
```

CLI additions: `flybrain neuromod build`, `flybrain rt serve [--core|--whole-brain]`,
`flybrain train <protocol.yaml>`, `flybrain capacity`, `flybrain replay <events.jsonl>`.

---

## 6. Numerics

- `dt = 0.1 ms` for spiking, `dt_graded = 0.5 ms`, `dt_mod = 1.0 ms`, `dt_plast = 1.0 ms`,
  `dt_state = 1000 ms`. All must be integer multiples of `dt`; assert it.
- Exponential-Euler throughout, as in the base build. Precompute every `exp(−dt/τ)`.
- The modulator field is stiff only if `τ_clear` approaches `dt_mod`; assert
  `τ_clear[m] ≥ 10 · dt_mod` for every species and fail loudly otherwise.
- Clamp every concentration to `[0, C_max]` with `C_max = 5.0` and **count clamp events**, same
  discipline as the voltage clamp in the base build. A nonzero count is a reported warning.
- Determinism: fixed thread count, `fastmath=False`, no atomics with nondeterministic order in the
  plasticity kernel. The replay test (V-NM-B) is the check.

---

## 7. Protocols as data

A training protocol is a YAML file, not code. This is what makes the console and the batch runner
the same experiment.

```yaml
name: forward_pairing_gamma1
seed: 7
blocks:
  - {t_ms: 0,     kind: rest,      dur_ms: 5000}
  - {t_ms: 5000,  kind: odour,     id: OCT, dur_ms: 1000, intensity: 1.0}
  - {t_ms: 5500,  kind: dan_pulse, compartment: g1, source: PPL101, dur_ms: 500, drive: 1.0}
  - {t_ms: 15000, kind: test,      odours: [OCT, MCH], dur_ms: 1000, readout: [MBON, DN, body]}
sweeps:
  pairing_interval_ms: [-2000, -1000, -500, -250, 0, 250, 500, 1000, 2000]
```

Negative pairing intervals mean dopamine before odour. The sweep in that one field is the
falsification test in §10 (V-NM-F). Every console session writes the equivalent YAML so that any
interactive discovery can be re-run headless.

---

## 8. Real time: the measured budget

Measured in this environment on 2026-09-26 with `rt_benchmark.py` — event-driven LIF delivery plus
the Layer-2 field plus the Layer-4 update, NumPy/SciPy float32 CSR, single-threaded, Python step
loop, **no compilation**:

| network | neurons | edges | dt | model s / wall s | steps/s |
|---|---|---|---|---|---|
| modulated core | 13,126 | 1,136,053 | 0.1 ms | **0.45 ×** | 4,467 |
| modulated core | 13,126 | 1,136,053 | 0.5 ms | **1.90 ×** | 3,797 |
| whole brain | 138,639 | 15,091,983 | 0.1 ms | 0.12 × | 1,176 |
| whole brain | 138,639 | 15,091,983 | 0.5 ms | 0.38 × | 756 |

and the cost of one *dense* sparse-matrix–vector product, which is what the graded optic-lobe path
needs every step:

| network | per spMV | implied real-time factor at dt = 0.1 ms |
|---|---|---|
| modulated core | 0.57 ms | 0.18 × |
| whole brain | 8.81 ms | 0.011 × |

Read these as follows, and put this reading in `REPORT.md`:

- **The modulated core at real time is a 2.2× optimisation problem, not a research problem.**
  Uncompiled Python already reaches 0.45 × at `dt = 0.1 ms`; at 4,467 steps/s the step loop is
  ~224 µs for 13,126 neurons, which is interpreter overhead, not arithmetic. A numba kernel of the
  kind the base build already uses closes that gap with room to spare. **Target: ≥ 1.2 × real time
  at `dt = 0.1 ms` for the core, single process, ≤ 4 GB RSS.** Report the achieved number; if it
  falls short, report it rather than shrinking the core.
- **Whole-brain real time is out of reach on this machine and must not be promised.** The binding
  cost is the graded optic-lobe path: 8.81 ms per spMV against a 0.1 ms budget is 88× short
  single-threaded, and memory-bandwidth-bound spMV does not recover 88× from 18 cores. Options,
  in order of honesty: (a) run the core in real time and drive the antennal lobe and the visual
  channel from *pre-computed* whole-brain runs (recommended; the base build already writes exactly
  this kind of activity table); (b) run whole-brain at 0.1–0.4 × and say so on the console clock;
  (c) port the graded path to Metal via MLX and re-measure before claiming anything. Do not
  implement (c) as a promise; implement it as a measurement.
- The console must display the *measured* real-time factor every frame, and must not silently
  substitute wall-clock time for model time. A run that dips below 1.0 × shows an explicit
  "slower than real time" state.

Engine/UI contract: the engine owns a fixed-lag scheduler and never blocks on the UI. Rendering
state goes into a double-buffered shared array; the bridge samples it at 30 Hz and drops frames
under load. Downsample **server-side** — the browser must never receive 13,126 per-neuron values per
frame when it is drawing 1,200 pixels of raster.

---

## 9. The console

This is a first-class deliverable, not a viewer bolted on at the end. Three reasons it carries
scientific weight: the experiment *is* an interaction (pairing intervals, compartment choice,
state), a modulator field is invisible in any static plot, and the project's credibility depends on
a judge being able to see what is measured and what is assumed without asking.

A **working single-file prototype of this console ships alongside this prompt** as
`cognesia_neuromod_console.html` — open it in a browser, no server. It runs a reduced but real
model (1,200 Kenyon cells, sparse coding with global APL inhibition, the §3.3 plasticity rule, a
15-compartment dopamine field) at ~60 fps, and it already implements the layout, the provenance
badge vocabulary, the self-check card, the divergence table and the session export described below.
**Treat it as the visual and interaction target, not as code to copy**: its numbers come from the
same measurements as §2, but its engine is a browser toy and the real engine is Python. Where this
section and the prototype disagree, this section wins.

### 9.1 Design principles

1. **One screen, no navigation to reach the experiment.** A visitor sees stimulus, brain, modulator
   state and behaviour simultaneously. Tabs may switch the *centre* view only.
2. **Time is the substrate.** The central object is a synchronised multi-lane timeline, because every
   result in this project is about an interval: 17 ms for apparent motion, hundreds of ms for
   dopamine pairing, seconds for clearance, minutes for forgetting. A UI that shows only "now"
   cannot express this project's findings.
3. **Provenance is rendered, not documented.** Every displayed number carries one of five badges —
   `measured`, `predicted`, `scRNA`, `inferred sign`, `assumption` — using the badge vocabulary
   already in `cognesia_control_panel.html`. Assumption-derived traces are drawn with a dashed
   stroke and hatched fills. A screenshot must be self-incriminating: you should not be able to
   present a fitted parameter as a measurement by cropping.
4. **The write interface is the left rail, the read interface is the right rail.** The left rail
   contains only things a real experiment could do (activate a named cell type, present an odour,
   change the animal's state). The right rail contains only things a real experiment could measure
   (MBON activity, descending drive, behaviour). Anything in the centre that is neither — the
   modulator field, the weight matrix — is marked `not experimentally accessible`. This layout
   teaches the project's actual thesis, which is about interface bandwidth.
5. **Direct manipulation of the invisible.** The one thing a simulation can do that no experiment
   can is set a modulator concentration directly. Give it a real control: a pipette that injects a
   bolus into a chosen compartment, and a clamp that holds a compartment at a fixed concentration.
   Both are logged as protocol events, both marked `not experimentally accessible`.
6. **Never fake smoothness.** Frame drops show as gaps. Missing data shows as gaps. No interpolation
   in any view. (Rule §1.8.)
7. **Reproducibility is a visible feature.** A session-recording indicator, a config hash in the
   header, and one button that exports the session as a protocol YAML plus an event log that
   replays bit-exactly.

### 9.2 Layout

```
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ MODEL — NOT A FLY   t = 12.480 s   1.31 × real time   dt 0.1 ms   core 13,126n   RSS 2.1G │
│ [▶/⏸] [◀ step] [step ▶] [reset]   protocol: forward_pairing_γ1   seed 7   cfg a91f2c   ⏺ │
├──────────────────┬────────────────────────────────────────────────────┬───────────────────┤
│ WRITE            │  ATLAS │ TIMELINE │ LEARNING │ DIVERGENCE          │ READ              │
│                  │                                                    │                   │
│ odour            │  ── centre view, see 9.3 ──                        │ MBON 35 meters    │
│  [OCT][MCH][air] │                                                    │  grouped by       │
│  intensity ▓▓▓░  │                                                    │  compartment      │
│                  │                                                    │                   │
│ visual           │                                                    │ DN drive          │
│  Δφ ▓▓░  Δt ▓░░  │                                                    │  4 handles        │
│                  │                                                    │                   │
│ DAN compartments │                                                    │ body arena        │
│  γ1 PPL101  ▓▓░  │                                                    │  + trail          │
│  γ2 PAM12   ▓░░  │                                                    │                   │
│  … 15 rows       │                                                    │ valence score     │
│  [pulse] Δt ±ms  │                                                    │                   │
│                  │                                                    │ ── divergence ──  │
│ modulator tone   │                                                    │ vs published:     │
│  OA ▓▓▓░ 5HT ▓░░ │                                                    │  4 gates, live    │
│                  │                                                    │                   │
│ state            │                                                    │                   │
│  energy ▓▓░      │                                                    │                   │
│  hydration ▓▓▓   │                                                    │                   │
│  circadian ◔     │                                                    │                   │
│                  │                                                    │                   │
│ pipette ⚗ [inj]  │                                                    │                   │
│  compartment ▾   │                                                    │                   │
│  not accessible  │                                                    │                   │
└──────────────────┴────────────────────────────────────────────────────┴───────────────────┘
```

### 9.3 The four centre views

**ATLAS.** A 2-D anatomical projection of the 13,126 core neurons, soma positions from the
annotation table's `soma_x/y/z` columns (they are present; use them rather than a made-up layout).
Points coloured by rate or ΔV on a perceptually uniform scale, drawn in WebGL as a single point
buffer. Over them, translucent compartment hulls tinted by `C[m,k]` for the selected modulator, with
a species selector. Hover a neuron: cell type, `super_class`, `known_nt`, `top_nt` with its
confidence, and — when the two disagree — an explicit `predictor disagrees with ground truth` flag.
That last detail turns §2.1 from a paragraph in a report into something a visitor discovers by
pointing at a Kenyon cell.

**TIMELINE.** The primary view. Lanes, all sharing one x-axis, scrolling at real time with a
draggable playhead and a fixed-window mode for figures:

1. stimulus (odour identity as a colour band; visual stimulus as a strip)
2. KC raster — 5,177 rows is more than the pixel height, so bin by subtype and show 11 density
   bands, with a drill-down that shows individual rows for a selected subtype
3. DAN rate, one trace per compartment, colour-keyed to the left rail
4. **modulator concentration**, one trace per (species, selected compartment) — the layer nothing
   else can show
5. MBON rate, grouped into the published appetitive/aversive sets
6. **mean KC→MBON weight per compartment**, i.e. the memory, as 15 traces
7. behaviour: forward velocity and yaw from the existing decoder
8. an event lane: every knob turn, pulse and injection, as a tick with a tooltip

Two interactions make it an instrument rather than a monitor. First, a **pairing cursor**: drag a
bracket between the odour block and the DAN pulse and it reads out Δt while re-arming the protocol —
the single parameter the science is about. Second, **shift-drag any lane region** to export that
window as a figure-ready CSV plus a PNG, with the config hash in the caption.

**LEARNING.** The protocol builder and the memory view. Drag odour blocks, DAN pulses and test
blocks onto a track; the track *is* the YAML of §7, shown side by side and editable either way. Run
train → test → run and show: the KC→MBON weight matrix as a **compartment × KC-subtype heatmap**
(15 × 11, so it is legible, with a drill-down to raw edges), before/after/difference; the learning
curve across trials; and the behavioural score with its bootstrap CI. A "forgetting" clock shows the
memory decaying in real time — that must be visible, because it is the honest behaviour of the rule.

**DIVERGENCE.** One row per biology gate in §10: model value, published value, the citation, and a
PASS/FAIL/NOT-RUN badge, computed live from the current run. This is the view that answers "how do
you know it resembles a fly at all", and it is the view a judge should be shown first.

### 9.4 Implementation

- **Engine in Python, console in the browser, connected by a WebSocket on localhost.** Not a native
  app: the project already has an HTML panel whose visual language should be extended, iteration
  speed matters more than native polish, and a browser gives WebGL for free.
- **Binary frames, not JSON.** One `Float32Array` per frame with a fixed header (schema version,
  t_sim, dt, real-time factor, frame counter) and a documented layout; 30 Hz. JSON at 30 Hz with
  thousands of values will not hold the frame budget. Write the layout in `docs/frame_format.md`
  and version it.
- **Server-side downsampling** to what each view can draw: raster densities, per-compartment means,
  a selected subset of full-resolution traces. The browser renders; it does not reduce.
- **Rendering:** WebGL for the atlas point cloud and the raster; 2-D canvas for traces (redraw the
  visible window only, never the full history); DOM only for controls, badges and tables. No
  per-neuron DOM nodes.
- **Controls:** every control emits `(t_sim_ms, control_id, value)` to the engine *and* to the
  session log. Keyboard: space pause, `[`/`]` step, `1`–`9` presets, `p` pulse the selected
  compartment. Optional Web MIDI mapping for the modulator knobs — genuinely useful when exploring a
  6-species field, and about 30 lines of code.
- **Accessibility and colour:** the five modulator species need distinguishable hues that survive
  deuteranopia; do not encode anything in red-versus-green alone; every colour-coded value also
  appears as a number. Respect `prefers-reduced-motion` by defaulting the timeline to stepped
  updates.
- **Degradation:** if the engine is not running, the console loads a recorded session from a file and
  says so in the header. It never shows a synthetic default (rule §1.8).
- **Self-check card**, as in the existing panel: on load, re-run a set of reference cases (field
  integration, plasticity asymmetry, sparseness) in the browser against values exported from the
  Python engine, and display PASS/FAIL. The browser must not be able to drift from the engine
  silently.

---

## 10. Validation gates

Software gates — must pass, or the build is not finished.

- **V-NM-A disable-equivalence.** With Layers 2–5 disabled, the engine reproduces the base build's
  spike trains bit-exactly for the standard stimulus battery.
- **V-NM-B replay determinism.** A 60 s interactive session, replayed from its event log with the
  same seed, reproduces every spike time and every final weight bit-exactly.
- **V-NM-C source integrity.** Assert the counts in §2.3 exactly: 337 MB DANs (PAM 307 / PPL1 16 /
  PPL2 8 / PAL 6), 96 MBONs in 35 types, 5,177 KCs in 11 subtypes, 43 OA-* neurons with OA-AL2b2
  excluded from the octopamine set on tyramine grounds, 76 endocrine neurons in the model subset.
  Assert the §2.4 motif counts exactly (KC→MBON 62,261 edges / 256,719 synapses, …). Assert Defect D
  is overridden: zero Kenyon cells in any modulator source set.
- **V-NM-D field numerics.** Every `τ_clear ≥ 10 · dt_mod`; zero concentration-clamp events in the
  default config; a single source pulse in one compartment leaves every non-adjacent compartment at
  exactly zero; halving `dt_mod` changes peak concentration by < 1 %.
- **V-NM-E plasticity bounds and reference curve.** No weight leaves `[0, w_max·w0]`; with
  `C[DA,·] = 0` no weight changes; with all KCs silent no weight changes; total absolute weight
  change scales linearly with `η` over a decade. **And: the single-synapse integration of the §3.3
  rule at the reference parameters reproduces all twelve values of the §3.3 table to within 1e-3.**
  This one test catches the wrong-rule failure mode described in §3.3 before any network is built —
  write it first.
- **V-NM-F' real-time budget.** The core hits its stated real-time factor for 60 s continuously with
  no frame-budget violation above 1 % of frames, at ≤ 4 GB RSS. Report the number.

Biology gates — **may fail; a failure is a result, and tuning to pass is forbidden** (rule §1.7).

- **V-NM-F pairing asymmetry.** Sweep the pairing interval from −2 s to +2 s. Forward pairing
  (odour → dopamine) must depress the paired compartment's KC→MBON weights; backward pairing must
  produce the opposite sign; the crossover must sit near zero. Compare the shape with the published
  curve (Handler 2019, PMID 31230716). **This is the model's falsification test.** Fit at most the
  four eligibility parameters here, once, and freeze them for every other gate.
- **V-NM-G compartment specificity.** A dopamine pulse confined to one compartment changes weights
  in that compartment by > 10 × the change in any other (Cohn 2015, PMID 26687359).
- **V-NM-H behavioural sign.** After aversive training in a compartment whose MBONs are in the
  published aversive set, the decoded behaviour moves away from the trained odour, and appetitive
  training moves it toward (Aso 2014, PMID 25535794; Owald 2015, PMID 25864636). Report the effect
  size, not a yes/no.
- **V-NM-I octopamine gain.** Raising `C[OA, lobula plate]` increases HS/VS gain and shifts the
  temporal-frequency optimum upward, matching the direction reported by Suver 2012 (PMID 23142045).
  This gate is valuable because it tests the modulator layer against the base build's *visual*
  machinery, which was validated independently.
- **V-NM-J state dependence.** The same odour produces a different decoded decision in the fed and
  starved states, with no weight change and no parameter edit — only Layer 5.
- **V-NM-K extinction / second-order structure.** Re-exposing the trained odour without
  reinforcement partially reverses the weight change through the MBON→DAN loop (Felsenberg 2018,
  PMID 30245010; Eschbach 2020, PMID 32203499). Report whether the connectome-derived loop is
  sufficient for this without a dedicated mechanism. A negative answer here is one of the more
  interesting possible outcomes of the whole build.

Every gate writes a row into `REPORT.md` with numbers, the citation it is tested against, and
PASS / FAIL / NOT-RUN. The DIVERGENCE view renders that same table live.

---

## 11. The measurement that is the contribution

Building the layer is engineering. The result to report is this:

> **How many bits of new input–output mapping can be written into this brain through the handles a
> real experiment could actually grab?**

Procedure (`flybrain capacity`):

1. **Enumerate the write handles.** A handle is an addressable cell type: the 30 DAN types, the 18
   OA types, the serotonergic types, and the 10 endocrine types — with the caveat the project has
   already established for descending neurons, that a cell type in the connectome is not
   automatically a driver line. Report handle count separately for "addressable in the connectome"
   and "addressable with a published driver line", and do not conflate them.
2. **Enumerate the read handles.** The 35 MBON types and the descending handles the decoder already
   supports.
3. **Define the task family.** *N* odours × *M* actions. Train with protocols that differ only in
   which handle is pulsed and when.
4. **Measure achieved mutual information** between the intended mapping and the decoded behaviour,
   in bits per trial, with a bootstrap CI, against a shuffled-protocol null using ≥ 1,000
   randomisations (the project's existing statistics standard: an empirical p-value floors at
   1/(B+1); Benjamini–Hochberg at q < 0.05 across handles).
5. **Report the capacity curve** as a function of the number of handles used, and the saturation
   point. Then report the same curve for handles that are *only* addressable in simulation, and
   quantify the gap. **That gap is the interface-bandwidth number the feasibility memo identified as
   the project's actual contribution.**

Two further results fall out of this build for free, and both should be written up:

- **The transmitter-prediction audit of §2.1** — a concrete, checkable statement about every
  connectome model that reads modulator identity from `top_nt`, with Defect D as its sharpest case.
- **Whether the connectome's MBON→DAN loop is sufficient for extinction** (V-NM-K), which is a
  clean structural question that nobody can ask without exactly this combination of connectome,
  plasticity rule and closed loop.

---

## 12. Work order

Commit after each. Do not start *n+1* until *n*'s software gates pass.

1. `sources.py` + Defect D override + V-NM-C. **Start here**: it is one day's work and it produces
   the audit table that is the most defensible result in the build.
2. `compartments.py` + the empirical MB clustering and its disagreement report.
3. `field.py` + V-NM-D. Headless, no UI.
4. `receptors.py` + V-NM-A (disable-equivalence) + V-NM-I (octopamine gain — the cheapest biology
   gate, and it reuses validated visual machinery).
5. `plasticity.py` + V-NM-E, then V-NM-F (the pairing sweep). This is the scientific core; expect to
   spend most of the time here.
6. `state.py` + V-NM-J.
7. `rt/` engine + V-NM-B, V-NM-F'. Measure and report the real-time factor before building any UI.
8. Console: header and transport first, then TIMELINE, then ATLAS, then LEARNING, then DIVERGENCE.
   TIMELINE before ATLAS — the timeline is the instrument, the atlas is the poster.
9. `capacity.py` + §11.
10. `REPORT.md`, `PARAMETERS.md`, `LIMITATIONS.md`.

---

## 13. Deliverables

1. The extended package, `pytest` green on V-NM-A–E and F'.
2. `REPORT.md`: the §2.1 audit table; the compartment clustering and its disagreements; the pairing
   curve against Handler 2019; the compartment-specificity matrix; the octopamine gain measurement;
   the state-dependence result; the extinction result; the capacity curve of §11; every
   `ASSUMPTION` sweep; every clamp and warning count; the measured real-time factor.
3. `PARAMETERS.md` generated from `neuromod.yaml` — value, unit, provenance tag, and for every
   fitted parameter, exactly which published data it was fitted to.
4. `LIMITATIONS.md`, containing §0.2's table verbatim plus at least: no receptor expression per
   neuron; concentrations dimensionless; compartments are volumes without geometry; nitric oxide
   diffusion not spatially resolved; no gap junctions; no glia (which clear and shape dopamine in
   vivo); one female connectome; predicted fast-transmitter signs; the endocrine interface is 76
   neurons of which two types are unidentified; whole-brain real time not achieved.
5. `console/`, plus `docs/frame_format.md` and one recorded session that the console can replay with
   no engine running.
6. A one-minute demo script: fed fly, odour A, pair with the aversive compartment, test, watch the
   behaviour flip, flip the animal to starved, watch the same odour read differently — with the
   DIVERGENCE tab open the whole time.

---

## 14. Sources

Every entry below was resolved against PubMed on 2026-09-26; the PMID and DOI pairs are as returned
by E-utilities, not from memory.

**Plasticity and the dopamine timing rule** — Handler 2019, PMID 31230716,
doi:10.1016/j.cell.2019.05.040 · Hige 2015, PMID 26637800, doi:10.1016/j.neuron.2015.11.003 ·
Cohn 2015, PMID 26687359, doi:10.1016/j.cell.2015.11.019 · Aso 2016, PMID 27441388,
doi:10.7554/eLife.16135 · Shuai 2015, PMID 26627257, doi:10.1073/pnas.1512792112 ·
Himmelreich 2017, PMID 29166600, doi:10.1016/j.celrep.2017.10.108

**Mushroom-body architecture and output** — Aso 2014a (compartment map), PMID 25535793,
doi:10.7554/eLife.04577 · Aso 2014b (MBON valence), PMID 25535794, doi:10.7554/eLife.04580 ·
Owald 2015, PMID 25864636, doi:10.1016/j.neuron.2015.03.025 · Barnstedt 2016 (MBON synapses are
cholinergic), PMID 26948892, doi:10.1016/j.neuron.2016.02.015 · Ichinose 2021, PMID 33476556,
doi:10.1016/j.cub.2020.12.032 · Lin 2014 (APL sparseness), PMID 24561998, doi:10.1038/nn.3660

**Recurrence, extinction, models** — Felsenberg 2018, PMID 30245010,
doi:10.1016/j.cell.2018.08.021 · Eschbach 2020, PMID 32203499, doi:10.1038/s41593-020-0607-9 ·
Gkanias 2022 (incentive circuit), PMID 35363138, doi:10.7554/eLife.75611 · Jürgensen 2023,
PMID 38269060, doi:10.3389/fphys.2023.1326307

**Other modulators** — Burke 2012 (octopamine→dopamine reward), PMID 23103875,
doi:10.1038/nature11614 · Suver 2012 (octopamine flight gain), PMID 23142045,
doi:10.1016/j.cub.2012.10.034 · Bielopolski 2019 (mAChR-B in Kenyon cells), PMID 31215865,
doi:10.7554/eLife.48264 · Aso 2019 (nitric oxide cotransmission), PMID 31724947,
doi:10.7554/eLife.49257

**Peptides and endocrine state** — Nässel 2019 (review), PMID 30905728,
doi:10.1016/j.pneurobio.2019.02.003 · Deng 2019 (chemoconnectome), PMID 30799021,
doi:10.1016/j.neuron.2019.01.045 · Zandawala 2018 (leucokinin), PMID 30457986,
doi:10.1371/journal.pgen.1007767 · Liessem 2023 (IPC state modulation), PMID 36580915,
doi:10.1016/j.cub.2022.12.005 · Bisen 2025 (IPC nutritional state), PMID 39878318,
doi:10.7554/eLife.98514 · Held 2025 (aminergic/peptidergic modulation of IPCs), PMID 40063677,
doi:10.7554/eLife.99548

**Expression atlases** — Li 2022 (Fly Cell Atlas), PMID 35239393, doi:10.1126/science.abk2432 ·
Crocker 2016 (MB transcriptomics), PMID 27160913, doi:10.1016/j.celrep.2016.04.046

**Connectome, annotation, transmitter prediction** — Dorkenwald 2024,
doi:10.1038/s41586-024-07558-y · Schlegel 2024, PMID 39358521, doi:10.1038/s41586-024-07686-5 ·
Lin 2024 (network statistics), PMID 39358527, doi:10.1038/s41586-024-07968-y · Eckstein 2024,
PMID 38729112, doi:10.1016/j.cell.2024.03.016 · Scheffer 2020 (hemibrain), PMID 32880371,
doi:10.7554/eLife.57443 · Shiu 2024, doi:10.1038/s41586-024-07763-9

**Tools** — Sun 2018 (GRAB-DA sensor, the reason dopamine dynamics are ΔF/F and not molar),
PMID 30007419, doi:10.1016/j.cell.2018.06.042 · Wang-Chen 2024 (NeuroMechFly v2, the body layer if
the loop is ever closed), PMID 39533006, doi:10.1038/s41592-024-02497-y

**Central complex** — Kim 2017, PMID 28473639, doi:10.1126/science.aal4835
