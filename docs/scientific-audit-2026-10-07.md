# Cognesia scientific audit and messenger catalogue — 7 October 2026

Cognesia has an unusually useful separation between anatomical identity, optional chemical fields, model assumptions, and recorded runs. Its immediate scientific priority is to restore and pass model-specific numerical and biological validation before interpreting larger experiment batches. Additional compute and more repeated runs can reduce sampling error; neither repairs incorrect equations, uncertain receptor assignments, or systematic model bias.

This change adds a source-backed catalogue of **26 entries: eight existing normalized fields, eight existing endocrine proxies, and ten candidates for annotation**. Candidate tags are available to tools without silently activating uncalibrated dynamics. No chemical kinetic values, neuron assignments, or receptor expression maps are fabricated. The catalogue's existing capabilities were checked against the current source, not inferred from its display labels.

## What the current model actually implements

| Area | Inspected implementation | Consequence |
|---|---|---|
| Fast neural dynamics | `engine.py`, `hybrid_engine.py`, and `wholebrain_neuromod.py` use point-neuron graded/spiking dynamics, sparse connectivity, fixed scheduling, and optional guards. | These are not multicompartment ion-channel models. Connectivity alone does not determine physiological response. |
| Chemical fields | `neuromod/field.py` defines DA, OA, 5HT, NO, sNPF, peptide_pool, TA, ACh. Clearance is exponential; spatial exchange follows a coarse compartment adjacency. | All concentrations are arbitrary units. A field's presence does not imply a configured receptor effect. NO and TA have no dedicated enabled rows in the current receptor table. |
| Receptors | `config/receptors.csv` separates published/inferred signs from assumed expression and strength; the reader requires expression and magnitude to remain `ASSUMPTION`. | Preserve this separation in the API and agent GUI. Unknown expression is not measured absence. Uniform cell-class targeting is not an expression atlas. |
| Endocrine system | `neuromod/state.py` provides insulin, corazonin, DH44, ITP, DH31, myosuppressin, CAPA, and hugin as normalized proxies. It labels state equations and coupling coefficients as assumptions. | The insulin variable lumps DILP2/3/5. The generic peptide pool is not a distinct molecular concentration for every named hormone. Unknown endocrine cells remain unknown. |
| New-provider chemistry | `provider_chemistry.py` uses source-region membership and zero diffusion adjacency, excludes unsupported plasticity transfer, and returns zero named-hormone columns. | BANC or a reduced provider does not inherit the original FlyWire endocrine/receptor-compartment validation. Catalogue entries must not be advertised as enabled in every provider. |
| Enzymes | `enzymes.py` implements opt-in ChAT, AChE and Tbh pathways with explicit arbitrary-unit pools, rates, and limitations. | Reaction identity is biological; these kinetic coefficients are model assumptions. More enzymes require units, source/target provenance and mass-balance tests. |
| Source provenance | `neuromod/sources.py` selects positive `known_nt` tokens and never treats `top_nt` as measured chemistry; `docs/model-sources.md` labels cross-specimen transfer inferred. | A predicted transmitter or a cell-type name must not automatically activate a newly discovered peptide. Preserve negative and conflicting reports. |

`REPORT.md` currently records a failed-closed core stationarity gate because its historical prerequisite is unavailable. A 43 ms core transport check recorded 1,045 voltage-bound violations. The 60-second exact replay passed, while historical measured throughput was 0.635× real time against a 1.2× target. These are **existing recorded results**, not benchmarks rerun for this catalogue. A short exact selected-neuron replay is useful numerical evidence and does not validate the full model's visual behavior or long-term stability.

## Ten candidates and a receptor update

Evidence below supports biological identity or circuit function in the stated context. It does not supply a neuron-by-neuron expression map, kinetics, or validated parameters for the assembled Cognesia specimen.

| Candidate | Reported receptor(s) / context | Safe next use |
|---|---|---|
| NPF | NPFR; adult motivation and appetitive memory. [Krashes et al., 2009](https://pmc.ncbi.nlm.nih.gov/articles/PMC2780032/), DOI 10.1016/j.cell.2009.08.035. | Keep NPF separate from sNPF and annotate only supported source cells. |
| PDF | PDFR; clock output to AstA-expressing PLP neurons. [Chen et al., 2016](https://journals.plos.org/plosgenetics/article?id=10.1371/journal.pgen.1006346), DOI 10.1371/journal.pgen.1006346. | Use a clock-circuit hypothesis rather than equating the scalar circadian phase with PDF signaling. |
| Allatostatin A | AstA-R1/DAR-1 and AstA-R2/DAR-2; feeding, sleep, insulin/AKH-producing cells. [Hentze et al., 2015](https://pmc.ncbi.nlm.nih.gov/articles/PMC4485031/), DOI 10.1038/srep11680. | Do not import the juvenile-hormone inhibition of other insects into Drosophila based on the name. |
| Allatostatin C | AstC-R2 in the clock circuit; AstC-R1/R2 in IPC-related studies. [Díaz et al., 2019](https://pubmed.ncbi.nlm.nih.gov/30554904/), [DN1p–IPC oogenesis study](https://pmc.ncbi.nlm.nih.gov/articles/PMC7848730/). | Preserve photoperiod, sex, and reproductive-state constraints. |
| MIP / Allatostatin B | SPR; sleep stabilization via PDF neurons. [Oh et al., 2014](https://pubmed.ncbi.nlm.nih.gov/25333796/). | Keep central MIP distinct from seminal sex peptide despite the shared receptor. |
| Leucokinin | Lkr; lateral-horn neurons and IPCs in starvation-dependent sleep. [Yurgel et al., 2019](https://pubmed.ncbi.nlm.nih.gov/30759083/), DOI 10.1371/journal.pbio.2006409. | Existing pooled peptide annotations are not a dedicated LK pathway. |
| Tachykinin | TkR86C/TkR99D literature; male aggressive-arousal circuit. [Asahina et al., 2014](https://pmc.ncbi.nlm.nih.gov/articles/PMC3978814/), DOI 10.1016/j.cell.2013.11.045. | Male circuit evidence must not automatically become an adult-female BANC/FlyWire assignment. |
| SIFamide | SIFaR; hunger-related sensory and feeding modulation. [Martelli et al., 2017](https://www.sciencedirect.com/science/article/pii/S2211124717308574), DOI 10.1016/j.celrep.2017.06.043. | Requires source/target matching; behavioral output does not supply a universal gain coefficient. |
| CCHamide-2 | CCHa2-R; larval gut/fat-body-to-brain signaling. [Sano et al., 2015](https://pmc.ncbi.nlm.nih.gov/articles/PMC4447355/). | Treat adult transfer and the peripheral endocrine boundary as unvalidated. |
| Drosulfakinin | CCKLR-17D1/17D3; satiety and sugar-sensing studies. [Wu et al., 2021](https://journals.plos.org/plosgenetics/article?id=10.1371/journal.pgen.1009724), DOI 10.1371/journal.pgen.1009724. | Preserve peptide processing/sulfation; distinguish fly results from planthopper experiments in the same paper. |

An important refinement for the **existing ITP proxy** is the experimental identification of **Gyc76C**, a guanylate cyclase receptor, for amidated ITP. The [eLife study](https://elifesciences.org/articles/97043), DOI 10.7554/eLife.97043, combines receptor activation assays with organismal perturbations. Record that receptor identity and ligand form; do not silently invent a GPCR, treat all ITP splice products alike, or copy a heterologous assay dose-response into a neural compartment's kinetics.

Existing sNPF dynamics also need a narrower interpretation: [Root et al., 2011](https://pubmed.ncbi.nlm.nih.gov/21458672/), DOI 10.1016/j.cell.2011.02.008, supports starvation-dependent ORN modulation. This does not validate the present assumed adult KC-to-MBON sNPF coupling. The existing DH44 stress proxy similarly differs from the sugar-sensing brain–gut pathway studied by [Dus et al., 2015](https://pmc.ncbi.nlm.nih.gov/articles/PMC4697866/), DOI 10.1016/j.neuron.2015.05.032.

## Source data acquisition path

The maintainers' [Drosophila neuropeptide annotation repository](https://github.com/flyconnectome/drosophila_neuropeptides) provides a versioned `gt_np_data.csv`, references, confidence information, and cross-dataset cell-type matching. It is a valuable starting point for expression overlays. It is **not imported by this change**: first freeze the commit and file checksum, then retain positive/negative assertions and the original study. A curator's cell-class correspondence remains inferred when transferred between specimens. A general repository description is not a replacement for reading the cited experiment.

For each proposed new dynamics module, require these independently reviewable inputs:

1. Ligand identity and processing/isoform, stage, sex, tissue, and experiment.
2. Versioned source-cell annotation and specimen-specific identity mapping, including conflicts.
3. Target receptor evidence, localization, and target-cell mapping. Transcript detection alone is not a measured protein abundance or response amplitude.
4. Release, transport, clearance, receptor and downstream equations with units. Keep missing numbers unknown or explicitly assumed with sensitivity ranges.
5. Disabled-path equivalence, control predictions, stable integration, and held-out physiological data before asserting improved biological accuracy.

## Optimization priorities tied to current code

| Priority | Change to investigate | Required evidence before release |
|---|---|---|
| 1 | Restore model-specific stationarity artifacts and explain every clamp or guard event before making the model more complex. | Zero-input/dark controls, finite states, a declared stationary criterion, voltage-bound analysis, and a fresh manifest binding all prerequisites. |
| 2 | Profile `ProviderChemistry.advance()` and `WholeBrainChemistry.advance()` at realistic active-neuron counts. They allocate rate/count buffers, copy source rates, project sparse fields and recompute receptor effects every millisecond. Reuse private buffers and fuse exact operations where measured allocations dominate. | Compare voltages, spikes, chemical state, checkpoints, and clamp counts against the current deterministic reference. Buffer reuse must not alias recorded snapshots. |
| 3 | Preserve `FastReceptors`' existing grouping of mathematically identical release effects; precompile/cold-start the Numba kernels before timing. Share read-only model artifacts across sequential runs rather than repeatedly loading them. | Separate cold compilation, warm simulation throughput, recording cost and peak RSS. Maintain stable accumulation order and all original edges. |
| 4 | Use existing selected-neuron computation with recorded surrounding signals for hypothesis screening, and stream bounded recording chunks. | Check full-model vs selected replay for each intervention; changed boundary interactions may invalidate reuse. A replay check cannot establish biological equivalence. |
| 5 | Consider slower chemical ticks only after explicit multirate error studies. The current coupled runtime requires 0.1 ms neural and 1 ms chemical/plasticity ticks. | Convergence at progressively smaller steps; preserve start-slot semantics, delay handling, interventions and plasticity history. Never silently change timesteps based on a performance tier. |
| 6 | Add receptor-specific and release-site detail to a small calibrated circuit before expanding globally; consider glial buffering, graded synapse dynamics or conductance models where measured data constrain them. | Better held-out predictions plus parameter identifiability, uncertainty and ablation tests. More state variables alone are not evidence of realism. |

These are prioritized engineering/scientific proposals. One exact allocation improvement was subsequently implemented in both chemistry adapters: each tick retains its already newly allocated source-rate array instead of copying it a second time. Snapshot tests verify that it does not alias the running rate state or mutate previous ticks; existing chemistry and selected-replay tests still pass. This removes one neuron-sized float64 copy per chemical tick without changing the arithmetic. No whole-model speedup benchmark or new candidate dynamics is claimed.

Resource tiers control memory and threads, with explicitly selected resolution presets. They should not quietly alter the biological model, expose other applications' data, or assign a higher accuracy claim to expensive hardware. The local LLM and simulation must share the machine's actual memory; concurrent full-network replicas may be much less efficient than sequential replicas on a laptop.

## Replication contract for an agent

- Freeze model, source, parameter, software and stimulus hashes; record hardware/tier separately. A repeated checkpoint with the same inputs and deterministic seed is **technical replay**, not a new biological replicate.
- Choose a primary endpoint and a bounded experiment matrix before running. Include matched baseline/null controls, perturbation ablations and sham controls where relevant.
- Derive distinct reproducible child seeds from a saved master seed. Independent seeds only create independent stochastic realizations if those RNG streams actually affect the model; merely varying a manifest label changes nothing.
- For paired intervention/control comparisons, reuse the same stochastic inputs within each pair to reduce Monte Carlo variance; use independent child streams between pairs. Restart or restore the correct pre-intervention state rather than continuing unacknowledged learning between trials.
- Record every attempted run, including timeouts, numerical failures, clamp counts and exclusions. Report successful-run count alongside attempted count; do not silently discard unfavorable runs.
- Separate randomness from uncertainty: repeat across independent seeds **and** sweep uncertain expression, strength, clearance and boundary assumptions. Use more than one specimen/model when estimating biological variability.
- Use effect sizes and uncertainty at the independent-run level. Thousands of correlated time samples from one fly model are not thousands of independent replicates. Avoid optional stopping and report the full searched hypothesis family.
- Require model-specific validation before biological conclusions. More replicated runs reduce Monte Carlo error conditional on the model; systematic bias and missing mechanisms remain.

## Integration and verification

`flybrain.messenger_catalog` has no model-loading or mutation dependency. `catalog_payload()` returns detached JSON-ready metadata; `messenger_details(id)` accepts exact identifiers/aliases; `source_annotation_tags(known_nt, evidence_url=..., dataset=..., neuron_id=...)` parses declared tags and retains negatives, conflicts and unknown tokens. IDs are strings so connectome integers cannot be rounded by JavaScript. Caller-supplied evidence is explicitly unverified. Parsing does not fetch URLs or enable simulated chemistry.

The focused tests check real field/hormone inventory parity, stage/sex constraints, candidate evidence, absent kinetics, detached responses, exact matching, NPF/sNPF separation, conflicting source annotations and input bounds. This catalogue changes no existing numerical equations or historical validation outcomes.
