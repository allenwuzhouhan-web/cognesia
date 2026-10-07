# Receptor effects and the all-LIF adapter

The receptor stage converts compartment concentrations into named parameter arrays. It changes gain, threshold distance, membrane time constant, or scoped release factors. It never converts a concentration into additive membrane current. Dop1R1 and Dop1R2 produce separate history-dependent plasticity channels for the next layer; this stage does not integrate eligibility traces or change weights.

`V-NM-A` certifies disable-equivalence on the released **13,300-neuron all-LIF core**, plus explicit active software fixtures. It is not certification of the whole-brain hybrid engine, evolving field/network feedback, or Layers 4/5. `V-NM-I` remains **NOT-RUN — depends on base V-G/V-H**, as required by Patch 1. A synthetic gain fixture cannot substitute for that visual biology gate.

## Evidence and corrections to the requested seed identities

Every `config/receptors.csv` row separates sign provenance, expression provenance, numerical magnitude provenance, and a declared magnitude sweep. All expression coverage and numerical magnitudes are `ASSUMPTION`. No expression atlas was imported, and no row is tagged `SCRNA`. A published sign does not establish receptor abundance, uniform type coverage, or a quantitative model coefficient.

Two supplied citations name a different receptor from the brief. The requested rows are retained, explicitly disabled, while source-correct rows provide the active effect:

- The PAM reward relay is **OAMB**, not Octβ2R, in Burke et al. The Octβ2R experiments concern MB-MP1/PPL1 motivational neurons. The active row is OAMB/PAM; the requested Octβ2R/PAM row is a disabled assumption. [Burke 2012, PMID 23103875](https://pmc.ncbi.nlm.nih.gov/articles/PMC3528794/)
- The inhibitory muscarinic KC receptor is **mAChR-A**, not mAChR-B, in Bielopolski et al. The study reports dendritic localization and inhibitory modulation of KC odor responses, especially gamma KCs. It does not establish a presynaptic mAChR-B autoreceptor. The active gain row is mAChR-A/KC; the requested B row is a disabled assumption. [Bielopolski 2019, PMID 31215865](https://elifesciences.org/articles/48264)

Other seed interpretations are similarly bounded:

| Coupling | Evidence used | Modeling assumption |
| --- | --- | --- |
| Dop1R1 KC-before-DA branch | Forward-pairing depression | Uniform KC coverage, extension beyond the measured gamma4 context, numerical coefficient and history timescale |
| Dop1R2 DA-before-KC branch | Backward-pairing potentiation and Gq-dependent forgetting | Numerical coefficient, temporal trace and generalization across compartments |
| Dop2R on named DANs | Reduced evoked DA release in larval CNS | Adult named-DAN expression, gain reduction, fast-edge release factor and magnitude |
| OA on VS | Positive flight-associated response gain | Specific receptor identity, expression and magnitude |
| OA on HS and HS/VS tau | Visual modulation context | Uniform HS extension and a shorter membrane tau as an implementation of temporal tuning |
| sNPFR on adult KC→MBON edges | Related larval recurrent KC→pPAM reward biology | Adult receptor coverage, edge scope, sign and magnitude |
| 5-HT7 on positive-GABA ALLNs | Serotonin excitation of GABAergic LNs can suppress PN output | Coverage of the exact selected ALLN cells, gain coefficient and concentration kernel |

The opposite dopamine consequences come from [Handler 2019, PMID 31230716](https://pmc.ncbi.nlm.nih.gov/articles/PMC9012144/). The channels remain separate and do not cause unconditional instantaneous release changes. [Himmelreich 2017, PMID 29166600](https://pmc.ncbi.nlm.nih.gov/articles/PMC6168074/) supports DAMB/Gq-mediated forgetting and describes fast calcium kinetics; it does not justify a universally slower receptor response. A slower model DA-history trace remains an assumption. [Shuai 2015, PMID 26627257](https://pmc.ncbi.nlm.nih.gov/articles/PMC4672816/) provides related forgetting-pathway evidence.

The Dop2R release sign comes from [Vickrey and Venton, PMID 22308204](https://pmc.ncbi.nlm.nih.gov/articles/PMC3269839/). VS gain direction comes from [Suver 2012, PMID 23142045](https://pubmed.ncbi.nlm.nih.gov/23142045/). The sNPF context is explicitly larval in [Lyutova 2019, PMID 31308381](https://pmc.ncbi.nlm.nih.gov/articles/PMC6629635/). The 5-HT row follows the GABAergic-LN pathway in [Suzuki 2020, PMID 32142699](https://pmc.ncbi.nlm.nih.gov/articles/PMC7133499/); that study also distinguishes basal serotonin from high exogenous serotonin/CSD conditions, so no universal inhibitory PN receptor row is asserted.

## Concentration, targeting, and parameter semantics

The field species order is the explicit `FIELD_SPECIES` tuple. `ReceptorModel` verifies root-ID ordering, targets cell-type regexes, optionally intersects exact cell class and positive ground-truth transmitter tokens, and constructs the same sorted CSC edge order as `LIFEngine`.

Neuron-level effects use the **mean concentration over all assigned model volumes**. This mixing rule is an assumption. An unassigned neuron receives zero exposure; missing anatomical coverage is not negative receptor-expression evidence.

For a `KC->MBON` row, the target regex must match the **presynaptic KC**, and concentration is read from the **postsynaptic MBON's empirical compartment** for each edge. The same KC can therefore have different factors on edges to different MBON compartments. Other outputs from that KC remain unchanged. `all_out` changes only selected presynaptic columns, using the source neuron's mean concentration. The names remain the empirical aligned labels from the compartment stage, including unsupported alignments and PPL101's reported anatomical disagreement; receptor code does not repair or override them.

For neuron and instantaneous release parameters, the unbounded factor is `1 + sum(magnitude * response(C))`, followed by declared bounds. Gain scales existing synaptic drive and explicit stimulus-event amplitude. Threshold is `v_rest + (v_threshold - v_rest) * threshold_factor`, avoiding a sign error from multiplying a negative voltage directly. Membrane tau is `tau_membrane * tau_factor`. A release factor multiplies only the selected fast-edge conductance delivery. It is a deterministic relative release multiplier, not a measured absolute probability, a change in anatomical synapse count, or a chemical source-release term in the field integrator.

Kernel shapes are normalized to zero at `C=0` and one at `C=1`:

- `linear`: `C`.
- `hill(n,K)`: `(1 + K**n) * C**n / (K**n + C**n)`; positive finite `n,K` are required.
- `biphasic`: `C * (2 - C)`, including a sign change above 2. This explicit assumed concentration shape is **not** the temporal dopamine pairing rule.

The table declares each default magnitude and sweep values. The existence of a sweep column does not mean that a sweep was executed. Receptor sensitivity experiments are not reported as completed by this stage.

## History channels and fast-engine integration

`ReceptorEffects.plasticity_channels` contains separate `PlasticityChannel` objects with receptor identity, history direction, effect name, CSC edge indices, signed signal, and provenance. The default Dop1R1 signal is negative and tagged `kc_before_da`; the Dop1R2 signal is positive and tagged `da_before_kc`. The next layer must retain the distinct presynaptic-KC and compartment-DA histories. Summing these into an instantaneous weight or membrane change would lose the required temporal asymmetry.

`ReceptorLIFEngine` subclasses the base all-LIF engine without editing it. With `enabled=False`, `run` directly delegates to `LIFEngine.run`, including its validation, event scheduling, recording phase, delayed-event ring and continuation state. With `enabled=True`, explicit effect arrays are required. The deterministic active kernel uses per-neuron decay/coupling/threshold/gain and per-CSC-edge release factors, while preserving threshold → delayed/input delivery → reset scheduling and ascending-neuron summation.

Effects are fixed during each `run` call. A caller can update them between 1 ms field intervals and continue the same fast-engine state. This stage provides that bridge, but does not certify a complete source-rate → field → receptor feedback scheduler. In particular, automatic field source-rate feedback, chemical release modulation, plasticity weight updates, endocrine state, graded neurons, and visual-pathway tuning are outside this adapter's validation scope.

```python
from flybrain.neuromod.core import load_core
from flybrain.neuromod.compartments import load_compartments
from flybrain.neuromod.receptors import ReceptorModel, read_receptors, receptor_bounds
from flybrain.neuromod.receptor_engine import ReceptorLIFEngine

core = load_core(root, kc_kc_mode="as_released")
mapping = load_compartments(root)
model = ReceptorModel(read_receptors(root / "config/receptors.csv"),
                      core.neurons, mapping, core.counts,
                      model_indices=core.model_indices, bounds=receptor_bounds(root))
engine = ReceptorLIFEngine(core.counts, base_parameters, enabled=True,
                           model_root_ids=core.neurons.root_id.to_numpy(),
                           clamp=False, threads=1)
effects = model.evaluate(field.C)
engine.set_effects(effects)
activity = engine.run(1.0, input_neurons, input_events)
# Update the field/effects explicitly between intervals in the later scheduler.
```

## Reachability and guards

The saved audit checks direct overlap between selected targets and positive source populations in coarse volumes. This establishes possible exposure, not measured receptor expression, observed source firing, or a physiological effect. Scoped KC→MBON edges are additionally audited using their exact postsynaptic compartment; KC membership elsewhere does not make an edge reachable.

The initial released-data audit found source-volume overlap for only **79 of 307 PAM neurons** in the active OAMB row. The other 228 PAM neurons are not given invented OA release sites. The 5-HT7 row selects **14 positive-GABA ALLNs**, all sharing `AL_unresolved` with CSD. Their gain can affect PNs through existing signed edges; no broadcast into the 58 named glomeruli was fabricated, and no DPM→MB effect is claimed. All 38 HS/VS-labelled targets share an OA source volume, but this overlap is not the missing visual biology validation.

For the actual scoped plastic edges, **60,344 of 62,261** have a DA source in their target MBON's empirical compartment. The remaining **1,917** target `g2`, `g5`, or `bp1`, which have no mapped DA source under this empirical construction. This is distinct from every KC sharing some DA-containing volume elsewhere. All 62,261 scoped edges have mapped sNPF sources in their target compartment. These are source-coverage results, not invented concentrations or proof that the sources fire during an experiment.

Concentrations must be finite and nonnegative. Signal, gain, threshold factor, tau factor and release bounds are explicit assumption parameters in `neuromod.yaml`. Every clipped element is counted by guard type for that **effect evaluation**. Parameter arrays are read-only. Active nonfinite network state causes an error with counted invalid state entries and a partial result; it is not converted into a successful bounded run. Voltage clamp events remain separately reported by the base scheduling semantics. Default unit-concentration evaluation has zero parameter guards; an explicit excessive-signal fixture demonstrates counted guards.

## Saved evidence

`validate_receptors(root)` requires current source, compartment and field evidence and writes:

- `validation_neuromod_receptors.json`: scoped `V-NM-A` checks, source/config/code/artifact hashes, coverage, reachability and explicit `V-NM-I NOT-RUN`.
- `neuromod_receptor_equivalence.npz`: spike trains, sampled voltages and endpoints for six fixed core cases with two continuation calls each.
- `neuromod_receptor_coverage.csv`: row-level core target counts and missing-volume coverage.
- `neuromod_receptor_reachability.json`: full-model target overlap and core edge-specific source coverage.

The six core cases are rest, ORN, PN, KC, DAN and combined explicit event inputs. The initial validation recorded 201 total spikes across the case parts, with bit-exact spike trains, voltages, live state and pending delays against the original engine. Small diagnostic fixtures separately verify gain, tau, threshold, correct release direction and compartment scope, no current at rest, finite guards and kernel normalization. These fixtures are labeled numerical checks; they are not substitutes for biology gates or claims of driven whole-brain stability.
