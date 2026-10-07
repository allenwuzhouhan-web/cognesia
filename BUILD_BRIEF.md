# Build prompt: an eye-driven, whole-brain *Drosophila* simulator from the FlyWire connectome

> Paste everything below the line into Claude Code or Codex, run from an empty directory.
> Every number in the **Verified facts** section was measured directly from the released data
> files or copied from the cited paper's full text on 2026-09-25. Do not "correct" them from memory.

---

## 0. Mission

Build `flybrain`, a Python package that simulates the **entire adult *Drosophila* brain
(138,639 neurons, 15,091,983 connections, 54,492,922 synapses; FlyWire v783)** as a network of
biophysical point neurons, with **the two compound eyes as the only source of input**.

A visual stimulus (movie) is rendered onto the ~800 ommatidia of each eye. It is converted to
photoreceptor voltages, and from there **every signal travels only as membrane-potential
dynamics transmitted through connectome synapses, with synaptic delays**. That covers retina →
lamina → medulla → lobula / lobula plate → visual projection neurons → central brain →
descending neurons. Every other sensory afferent (olfactory, gustatory, mechanosensory,
thermo-/hygrosensory) receives zero input. **No neuron is ever clamped or silenced to keep it
quiet.** Which non-visual brain areas become active is an *output* of the simulation. It is
never enforced.

The program runs autonomously end to end: fetch data → build the network → validate → run the
stimulus battery → write a report. Target machine: macOS on Apple Silicon (arm64), 18 CPU cores,
64 GB RAM, no GPU. **Hard memory ceiling: 40 GB resident.** Expected peak is far below that
(see §7). The ceiling is a guard, not a target.

---

## 1. Non-negotiable rules

1. **Connectome is the only wiring.** No hand-built Reichardt detector, no learned or
   backpropagated weights, no artificial shortcuts between areas. Direction selectivity, if it
   appears, must emerge from connectome wiring plus per-cell-type biophysics.
2. **No shortcut propagation.** No linear influence propagation, matrix powers, or steady-state
   solves in place of time-stepped dynamics. Signals move one time step at a time, through
   synapses, after the synaptic delay.
3. **Spiking where neurons spike, graded where they don't** (see §3.2). Forcing spikes onto
   photoreceptors, lamina cells or T4/T5 would be biologically wrong. These cells signal with
   graded potentials. The published connectome-constrained visual model uses
   *"passive leaky linear non-spiking voltage dynamics"* because *"many neurons in the early
   visual system are non-spiking"* (Lappalainen et al. 2024). T4 direction selectivity is
   reproduced by a *passive, conductance-based* model (Gruntman et al. 2018). An `all_lif` mode
   (every neuron LIF, as in Shiu et al. 2024) must also exist, for comparison only.
4. **Every parameter has a provenance.** `config/parameters.yaml` records, for every parameter,
   its value, unit, and either a citation (PMID/DOI) or the literal tag `ASSUMPTION`. Anything
   tagged `ASSUMPTION` gets a sensitivity sweep in the report.
5. **Never fabricate data.** If a download fails, a schema differs from what this prompt says,
   or a validation test fails, stop that stage and record it in `REPORT.md`. Do not substitute
   synthetic data, do not silently change the stimulus, and **do not tune parameters to make a
   validation test pass**. A failed test reported honestly is an acceptable outcome. A test
   passed by tuning is not.
6. **Inspect before assuming.** For every downloaded table, print its schema, dtypes, row count
   and three rows before writing code that depends on it. Fail loudly on any mismatch.
7. **Deterministic.** Given a seed, the same config produces bit-identical spike trains.

---

## 2. Verified facts (measured from the release files — use these as assertions)

### 2.1 Data files and their measured contents

| File | Source | Size | Verified content |
|---|---|---|---|
| `Connectivity_783.parquet` | `https://raw.githubusercontent.com/philshiu/Drosophila_brain_model/main/Connectivity_783.parquet` | 100.8 MB | 15,091,983 rows; columns `Presynaptic_ID, Postsynaptic_ID, Presynaptic_Index, Postsynaptic_Index, Connectivity, Excitatory, Excitatory x Connectivity`; `Connectivity` = synapse count, min 1, sum 54,492,922; `Excitatory` ∈ {+1: 9,059,302 rows, −1: 6,032,681 rows} |
| `Completeness_783.csv` | same repo, `Completeness_783.csv` | 3.3 MB | 138,639 rows; columns `Unnamed: 0` (= root_id), `Completed`. **Row order defines `*_Index`.** |
| `Supplemental_file1_neuron_annotations.tsv` | `https://raw.githubusercontent.com/flyconnectome/flywire_annotations/main/supplemental_files/Supplemental_file1_neuron_annotations.tsv` | 31.7 MB | 139,248 rows, 31 columns including `root_id, super_class, cell_class, cell_sub_class, cell_type, top_nt, top_nt_conf, side, vfb_id` |
| `per_neuron_neuropil_count_post_783.feather` / `_pre_783.feather` | Zenodo record 10676866 (`https://zenodo.org/api/records/10676866`) | 233.8 / 16.9 MB | per-neuron synapse counts per neuropil — use for area-level readout |
| `proofread_connections_783.feather` | Zenodo 10676866 | 852.0 MB | optional; inspect schema (likely per-neuropil connections) |
| `flywire_synapses_783.feather` | Zenodo 10676866 | 9,493 MB | optional, only for §3.5 column fallback / CT1 compartments; **stream by record batch, never load whole** |
| reference LIF model | `https://raw.githubusercontent.com/philshiu/Drosophila_brain_model/main/model.py` | — | Brian2 reference implementation used for the engine cross-check (§6, V-E) |
| `flyvis` (PyPI 1.2.0, MIT, requires Python <3.13) | `pip install flyvis` | — | pretrained connectome-constrained optic-lobe model (Lappalainen 2024); source of optional per-cell-type priors (§3.3) and column-averaged lamina connectivity (§3.4) |

`super_class` counts over the 138,639 model neurons: optic 77,530 · central 32,379 ·
sensory 16,352 · visual_projection 8,038 · ascending 1,736 · descending 1,299 ·
sensory_ascending 581 · visual_centrifugal 524 · motor 110 · endocrine 76 · missing 14.

### 2.2 The eye in this dataset

| Cell type | Left | Right | Median out-synapses | Note |
|---|---|---|---|---|
| R1-6 | 4,044 | 3,888 | 19 | outer photoreceptors → lamina; 277 have **zero** output synapses |
| R7 | 668 | 668 | 20 | inner, UV; 77 of the R7s (both eyes) are dorsal-rim (DRA) |
| R8 | 662 | 652 | 18 | inner, blue/green; 77 DRA |
| L1 | 802 | 789 | 285 | ≈ one per column |
| Mi1 | 788 | 796 | 973 | ≈ one per column; **use as the column anchor** |
| T4a–d | 3,137 | 3,104 | 137 | ON motion detectors |
| T5a–d | 3,009 | 2,996 | 147 | OFF motion detectors |
| HS / VS | 3+3 | 16+16 | — | wide-field motion cells |
| LPLC2 | 108 | 102 | — | looming detectors |
| DNa02 | 1 | 1 | — | steering descending neuron; median of the two ≈ 12,700 input synapses (only ~750 from visual projection neurons — most visual drive arrives via central neurons) |
| DNp01 (giant fibre) | 1 | 1 | — | escape |

Anatomy: *"roughly 800 ommatidia"* per eye (Matsliah 2024); *"around 750"* (Zhao 2025). Each
ommatidium has 8 photoreceptors, R1–R8. R1–R6 terminate in the lamina. R7 and R8 pass through to
the medulla. Interommatidial angle 5.1°, acceptance angle 5.7° FWHM (Clark 2011, citing
Stavenga 2003). There are also 273 **ocellar** afferents (the three simple eyes on the vertex).
They are *not* compound-eye inputs and stay dark by default.

### 2.3 Three defects in the released data that the build MUST handle

**Defect A — photoreceptor signs are wrong.** Photoreceptors release **histamine**. Their
target on L1/L2 is a *histamine-gated chloride channel* (`ort`; Gengs et al. 2002, PMID
12196539), so light depolarizes the photoreceptor and **hyperpolarizes** L1/L2. The
neurotransmitter classifier behind `top_nt` has only six classes (acetylcholine, dopamine, gaba,
glutamate, octopamine, serotonin) and no histamine. As a result, the `Excitatory` column signs
**81.1% of R1-6 synapses (226,881 synapses), 32.1% of R7 and 68.3% of R8 as excitatory.**
→ Override: every synapse whose presynaptic `cell_type ∈ {R1-6, R7, R8}` gets sign −1
(configurable per postsynaptic type, and recorded as an override in the report).

**Defect B — the lamina is under-reconstructed.** R1-6 → L1/L2 has a **median of 34 synapses per
L cell, and 20.0% of L1/L2 receive zero R1-6 input**. The FlyWire optic-lobe paper notes that
photoreceptor synapses were added to a detector training set, *"but the results were not ready
in time for this publication"*. The male optic-lobe connectome also calls its lamina
*"incomplete"* (Nern 2025). Implement `lamina_mode`:
- `connectome` — use the released edges as they are;
- `cartridge` (**default**) — see §3.4.
Run the full validation in both modes and report the difference.

**Defect C — glutamate sign is an assumption.** Following Shiu et al. (2024), glutamate is
treated as inhibitory by default (acting through GluCl). This is correct for key visual
synapses, for example L1 → Mi1, which makes Mi1 an ON cell, and Mi9 → T4. It is not universally
correct. Keep it as a configurable per-type override table.

Not in the data at all: **electrical synapses** (gap junctions). They matter in the visual
system: removing `shakB` from HS/VS produces spontaneous voltage oscillations (Ammer 2022,
PMID 35385694). List this as a limitation. Do not invent gap junctions.

### 2.4 Anchoring dynamics and results from the literature (use as validation targets)

- T4/T5: four subtypes per pathway, tuned to the four cardinal directions and projecting to the
  four lobula-plate layers. Verify the subtype-to-direction mapping (a = front-to-back,
  b = back-to-front, c = upward, d = downward) against Maisak et al. 2013 (PMID 23925246)
  before encoding it in a test.
- T4 is ON-selective and T5 OFF-selective. Their inputs: Mi1, Tm3, Mi4, Mi9 → T4; Tm1, Tm2,
  Tm4, Tm9 → T5 (Behnia 2014 PMID 25043016; Arenz 2017 PMID 28343964, which reports *"large
  differences in temporal dynamics"* among these inputs).
- Behavioural and T4/T5 correlation-interval optimum: ~17 ms, *"virtually no modulation"* at
  0 ms, extending to ~80 ms (Salazar-Gatzimas 2016, PMID 27710784).
- LPLC2 is selective for looming over translation (Klapoetke 2017, PMID 29120418).

---

## 3. Model specification

### 3.1 Network assembly

1. Neuron table = `Completeness_783.csv` order, left-joined to annotations on `root_id`.
   Assert 138,639 rows and that every index in the connectivity table is `< 138,639`.
2. Weights: `W[post, pre] = sign(pre→post) × Connectivity × w_unit(pre_mode)`, stored as
   **CSR float32 with int32 indices, rows = postsynaptic** (≈122 MB). Build two sub-matrices by
   presynaptic mode (graded vs spiking) so each can be applied its own way.
3. Apply sign overrides (Defects A, C) *before* building CSR. Write
   `build/sign_overrides.csv` listing each overridden (pre_type, post_type, n_synapses).

### 3.2 Neuron modes (config table `config/neuron_modes.csv`, one row per cell type)

Default assignment, each row tagged with a source or `ASSUMPTION`:

| Mode | Cell types |
|---|---|
| `graded` | R1-6, R7, R8; all lamina types (L1–L5, C2, C3, T1, Lawf, Lai); all medulla intrinsic (Mi, Dm, Pm, Sm); Tm, TmY, T2, T3, T4a–d, T5a–d; lobula/lobula-plate intrinsic (LPi, Li, Y); CT1; HS, VS |
| `spiking` | everything else: remaining visual projection neurons (LC, LPLC, LT, MeTu …), visual centrifugal, all central, descending, ascending, motor, endocrine, non-visual sensory |

This split is 96,674 graded and 41,965 spiking neurons (measured with the rule
`super_class ∈ {optic, visual_projection, visual_centrifugal} ∪ photoreceptors` as a first
pass; refine per type). Measured edge partition under that first-pass rule:
graded→graded 8,903,991 edges; graded→spiking 464,989; spiking→graded 185,308;
spiking→spiking 5,537,695. Report a sensitivity run with VPNs switched to graded.

### 3.3 Dynamics (all in mV, ms)

**Spiking neurons** — exactly the Shiu et al. 2024 LIF (verify against the downloaded
`model.py`):
`dv/dt = (v_0 − v + g) / t_mbr`, `dg/dt = −g / tau`, with `v_0 = −52`, `v_rst = −52`,
`v_th = −45`, `t_mbr = 20`, `tau = 5`, `t_rfc = 2.2`, delay `t_dly = 1.8`,
`w_syn = 0.275 mV` per synapse. A spike at `pre` adds `W[post,pre]` to `g[post]` after
`t_dly`. Spiking neurons have no spontaneous input (no Poisson drive) unless an experiment
explicitly adds it.

**Graded neurons** — passive leaky integrator with continuous, rectified transmitter release:
`C dV/dt = (V_rest − V)/τ_m + g_syn`, with `dg_syn/dt = −g_syn/τ_syn + Σ_pre W[post,pre] · r(V_pre(t − d))`,
where `r(V) = max(0, V − V_release)`. `V_release` sits a few mV **below** `V_rest`, so
synapses release tonically at rest. This is what lets unrectified cells such as R1–R8, L1 and
L2 signal both light increments and decrements. `τ_m`, `V_rest`, `V_release` and the
graded-synapse gain are per cell type:
- `params=uniform` — one value each, tagged `ASSUMPTION`, swept in the report;
- `params=flyvis` — per-type values mapped by cell-type name from the pretrained `flyvis`
  ensemble. Record the ensemble/model ID. **These values were fitted by task optimization, not
  measured.** Tag them `FLYVIS_FIT`, never as measurements.
- `params=literature` — overrides from papers where the agent can cite a PMID (e.g. relative
  fast/slow ordering of Mi1/Tm3 vs Mi4/Mi9 from Arenz 2017).
Graded→spiking: the continuous release term feeds the spiking neuron's `g`.
Spiking→graded: each spike adds `W` to `g_syn` after the delay. The relative scale between
graded release and spike-driven input (`graded_gain`) is a single global `ASSUMPTION`. Sweep it
over ≥ 1 decade.

**Numerics.** Exponential-Euler. `dt = 0.1 ms` for spiking; graded state may update at
`dt_graded = 0.5 ms` (configurable; justify from min `τ_m`). Delays are implemented with ring
buffers. Clamp V to [−90, +20] mV and **count every clamp event**. A non-zero count is a
reported warning, not something to hide. Before each stimulus, pre-equilibrate for 1,000 ms at
the stimulus's mean luminance, and assert the network is stationary (max |dV/dt| below
tolerance) before stimulus onset. If it never settles, report the unstable cell types; do not
add damping silently.

### 3.4 The eye

1. **Columns.** Each Mi1 defines one column per side (≈790). Assign every columnar neuron to a
   column by its strongest synaptic partner with a known column. Seed with L1→Mi1, then iterate
   (L2–L5, Mi4, Mi9, Tm1–Tm4, Tm9, Tm20, T4/T5 dendrites). Assign R1-6 to the cartridge of their
   strongest L1/L2/L3 target; assign R7/R8 by their strongest medulla partner. Log unassigned
   cells.
2. **Retinotopy.** Give every column a 2-D hexagonal coordinate and a viewing direction.
   - Preferred: if the user places the FlyWire Codex visual-column assignment export in
     `data/raw/codex/`, use it (inspect its schema first).
   - Fallback: stream `flywire_synapses_783.feather` by record batch. Compute each Mi1's
     medulla synapse centroid. Build the 6-neighbour graph (Delaunay, prune by distance). Assign
     axial hex coordinates by breadth-first walk from the most central column, clustering edge
     directions into three axes.
   - Viewing direction: uniform 5.1° hexagonal spacing on a sphere per eye (default,
     `ASSUMPTION`). Optional: non-uniform sampling from the micro-CT eye map of Zhao et al. 2025
     (PMID 40702177), if its data can be obtained.
3. **Optics.** Each column samples the stimulus through a Gaussian of 5.7° FWHM around its
   viewing direction. **Neural superposition:** the six R1-6 cells that converge on one lamina
   cartridge come from six different ommatidia but share one optical axis. So drive every
   R1-6 assigned to cartridge *c* with column *c*'s sample. R7 and R8 of a column get the same
   sample.
4. **Photoreceptor transduction.** Luminance → photoreceptor voltage through a divisive
   (Naka–Rushton) adaptation stage followed by a low-pass filter. Parameters are `ASSUMPTION`
   unless cited. Optional spectral mode: R1-6 Rh1 (broadband), R7 UV, R8 blue/green, with
   R7p/R7y pairing per Wernet 2006 (PMID 16525464). Default is greyscale. The stochastic
   microvillus model (Song 2012, PMID 22704990) is out of scope; list it as future work.
5. **`lamina_mode = cartridge`** (Defect B). For each cartridge, ensure L1, L2 and L3 each
   receive input from the R1-6 of that cartridge's optical axis. Where released edges are
   missing or below the per-type median, add edges up to the per-type column-average synapse
   count taken from the `flyvis` connectome (cite the flyvis connectome version). Every added
   edge is written to `build/synthetic_lamina_edges.csv` and counted in the report. Released
   edges are never deleted.
6. **Ocelli.** Stay dark by default; flag `--ocelli on` feeds them a whole-field luminance
   signal. (Context: in this dataset DNp28's visual drive is ocellar, not compound-eye —
   651 of its input synapses come from ocellar afferents.)

### 3.5 Readout

- Spikes: every spiking neuron, stored sparse (neuron index int32, time float32).
- Voltages at 1 kHz for a configurable set. Default: all T4/T5, HS, VS, LPLC2, all descending
  neurons, and every neuron in the three most central columns of each eye.
- **Area activity**: for each neuropil, weight each neuron's activity (spike rate, or
  ΔV above rest for graded cells) by the fraction of its synapses in that neuropil, using the
  `per_neuron_neuropil_count_*` files. This produces the "which brain areas lit up" map.
- Storage: Zarr or NPZ per run, plus `run_manifest.json` (config hash, git hash, seed, versions,
  wall time, peak RSS).

---

## 4. Stimulus battery

All stimuli are defined in visual degrees and ms, rendered at 240 Hz (4.17 ms frames), and
sampled by the optics in §3.4.

1. Dark → full-field ON flash, and OFF flash.
2. Square-wave gratings, 4 cardinal directions + diagonals, wavelength 30°,
   temporal frequency sweep {0.5, 1, 2, 4, 8} Hz.
3. ON and OFF moving edges, 4 cardinal directions, 80°/s.
4. Looming disc (l/v sweep) vs. same-size translating disc.
5. **Two-point apparent motion (the "minimum motion vector" experiment).** Two point flashes
   (one column each) separated by Δφ ∈ {0, 1, 2, 3, 4} columns (0–20.4°) and Δt ∈ {0, 4.17,
   8.33, …, 100} ms in 240 Hz frames. Run in preferred and null order, ON-ON, OFF-OFF, and the
   two reverse-phi contrast combinations. Read out: T4/T5 direction-selectivity index (DSI) by
   subtype, HS/VS response, DNa02 left–right asymmetry. Compare the (Δφ, Δt) optimum with the
   phenomenological prediction from the project's earlier correlator fit:
   **Δφ = 5.1° (one ommatidial step), Δt = 17 ms, 300°/s**.
6. **Dark control.** 5 s at constant luminance with no change. Expected: zero spikes anywhere
   in the central brain.

---

## 5. Architecture and CLI

```
flybrain/
  pyproject.toml            # Python 3.12 (flyvis needs <3.13); numpy, scipy, numba, pandas,
                            # pyarrow, zarr, pyyaml, psutil, matplotlib, brian2 (cross-check only)
  config/parameters.yaml    # every parameter: value, unit, source | ASSUMPTION | FLYVIS_FIT
  config/neuron_modes.csv
  config/sign_overrides.csv
  src/flybrain/
    fetch.py        # downloads + sha256 + schema assertions (§2.1)
    build.py        # neuron table, sign overrides, CSR, columns, lamina repair
    eye.py          # retinotopy, optics, phototransduction
    engine.py       # numba kernels: graded update, LIF update, spike delivery, ring buffers
    stimuli.py
    record.py       # sparse spikes, voltage subsets, neuropil aggregation
    validate.py
    report.py
    memguard.py     # background RSS monitor, graceful abort above limit
  tests/            # pytest: unit + validation
  flybrain_cli.py   # flybrain fetch | build | validate | run <stimulus> | sweep | report
```

The engine is a custom `numba` kernel (`parallel=True`, `fastmath=False` for determinism).
Brian2 is used **only** to cross-check the `all_lif` mode (V-E). Brian2's continuous summed
synapses over 9 M graded edges would be too slow.

---

## 6. Validation gates (run by `flybrain validate`; each writes PASS / FAIL / NOT-RUN with numbers)

- **V-A data integrity**: row counts, index bounds, synapse sum (54,492,922), super_class counts
  (§2.1), photoreceptor counts (§2.2). All must match exactly.
- **V-B sign sanity**: after Defect A override, a light increment depolarizes R1-6 and
  hyperpolarizes L1 and L2 in ≥ 95% of columns.
- **V-C numerical**: halving `dt` changes T4/T5 peak responses by < 5%. Zero clamp events in the
  default config. Stationary after pre-equilibration.
- **V-D dark control**: zero central-brain spikes during the 5 s dark control.
- **V-E engine cross-check**: in `all_lif` mode, drive the same 20 randomly chosen neurons with
  identical Poisson input in both this engine and the downloaded Brian2 reference for 1 s ×
  10 trials. Per-neuron firing rates must correlate r ≥ 0.95 over all neurons that fire.
- **V-F ON/OFF split**: Mi1 and Tm3 depolarize to ON, Tm1 and Tm2 to OFF flashes.
- **V-G direction selectivity**: for each of T4a–d and T5a–d, median DSI > 0 for its expected
  direction (§2.4) and T4 prefers ON edges, T5 OFF edges.
- **V-H wide-field**: HS responds more strongly to horizontal than vertical gratings, VS the
  reverse.
- **V-I looming**: LPLC2 looming response > translation response.

V-A to V-E test the **software**; they must pass, or the build is not finished. V-F to V-I test
the **model's biology**; they may fail. A failure there is a scientific result. Report it with
numbers and do not tune to fix it. The report compares `params=uniform` against `params=flyvis`
on V-F to V-I, which directly measures how much of fly motion vision the connectome alone
explains.

---

## 7. Performance and memory budget

Measured sizes: CSR ≈ 122 MB; one float32 state vector ≈ 0.55 MB; full-brain voltage
recording at 1 kHz ≈ 0.555 GB per simulated second.

- Budget: model + buffers < 4 GB. Recording is the only thing that can grow; `memguard` aborts
  cleanly (saving everything so far) if RSS exceeds the 40 GB limit (`--mem-limit-gb`, default
  40). Full-brain voltage recording is off by default.
- Target speed: ≥ 1 simulated second per 5 wall-clock minutes on 16 threads in hybrid mode.
  Report the achieved speed; do not trade correctness for speed.
- Parameter sweeps run as independent processes, never exceeding the memory limit in total.
  Default is 3 concurrent workers.

---

## 8. Deliverables

1. The package, passing `pytest` (unit tests plus V-A–V-E).
2. `REPORT.md` with figures:
   - the validation table;
   - column map of each eye;
   - T4/T5 polar tuning plots;
   - HS/VS responses;
   - the **(Δφ, Δt) apparent-motion map** vs the 5.1°/17 ms prediction;
   - the neuropil activation map per stimulus (which non-visual areas activate, how strongly,
     how late);
   - `lamina_mode` and `params` comparisons;
   - sensitivity sweeps for every `ASSUMPTION`;
   - clamp and warning counts.
3. `PARAMETERS.md`, generated from `parameters.yaml`: every value with its source.
4. `LIMITATIONS.md` must cover at least:
   - point neurons (no dendritic computation; CT1 as a single compartment unless the optional
     per-column CT1 extension is done);
   - no gap junctions;
   - predicted, not measured, transmitter signs (Eckstein 2024, PMID 38729112);
   - lamina repair;
   - uniform eye sampling;
   - one female brain;
   - open loop (no body; closed-loop coupling with NeuroMechFly v2 is future work);
   - no neuromodulation or plasticity.

---

## 9. Work order (commit after each)

1. `fetch` + V-A.
2. `build` (signs, CSR, modes) + V-B scaffolding.
3. `engine` in `all_lif` mode + V-E.
4. Graded neurons + hybrid coupling + V-C, V-D.
5. `eye` (columns, retinotopy, optics, lamina repair).
6. Stimuli + V-F–V-I.
7. Apparent-motion sweep.
8. Report.

Do not start step *n+1* until step *n*'s software gates pass. If a gate cannot pass, write down
why in `REPORT.md` and stop.

## 10. Key sources (all retrieved and checked)

Dorkenwald 2024 doi:10.1038/s41586-024-07558-y · Schlegel 2024 doi:10.1038/s41586-024-07686-5 ·
Matsliah 2024 doi:10.1038/s41586-024-07981-1 · Shiu 2024 doi:10.1038/s41586-024-07763-9 ·
Lappalainen 2024 doi:10.1038/s41586-024-07939-3 · Nern 2025 doi:10.1038/s41586-025-08746-0 ·
Zhao 2025 doi:10.1038/s41586-025-09276-5 · Gruntman 2018 doi:10.1038/s41593-017-0046-4 ·
Maisak 2013 doi:10.1038/nature12320 · Behnia 2014 doi:10.1038/nature13427 ·
Arenz 2017 doi:10.1016/j.cub.2017.01.051 · Salazar-Gatzimas 2016 doi:10.1016/j.neuron.2016.09.017 ·
Clark 2011 doi:10.1016/j.neuron.2011.05.023 · Klapoetke 2017 doi:10.1038/nature24626 ·
Gengs 2002 doi:10.1074/jbc.m207133200 · Ammer 2022 doi:10.1016/j.cub.2022.03.040 ·
Eckstein 2024 doi:10.1016/j.cell.2024.03.016 · Rivera-Alba 2011 doi:10.1016/j.cub.2011.10.022 ·
Wernet 2006 doi:10.1038/nature04615 · Song 2012 doi:10.1016/j.cub.2012.05.047 ·
Namiki 2018 doi:10.7554/elife.34272 · Yang 2024 doi:10.1016/j.cell.2024.08.033
