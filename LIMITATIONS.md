# Scientific and implementation limitations

- Point neurons omit dendritic computation; a single CT1 compartment cannot represent its local column computations.
- The released connectome excludes electrical synapses (gap junctions). None are invented. Ammer 2022, PMID 35385694.
- Transmitter predictions are not measurements. Histamine is absent from the classifier; photoreceptor inhibitory overrides are explicit. Glutamate inhibition is an assumption outside verified receptor-specific cases. Eckstein 2024, DOI 10.1016/j.cell.2024.03.016.
- A repaired lamina changes the released graph. Such a variant needs traceable flyvis-derived counts and a complete added-edge ledger; it cannot be called strictly released-connectome-only wiring.
- Uniform 5.1-degree eye spacing is an assumption. Anatomical position alone is not a verified visual-field orientation.
- This is one adult female brain; variation across animals and sexes is not represented.
- Simulation is open loop, with no body or behavior feedback. NeuroMechFly coupling is future work.
- The original neural engine has no neuromodulation or plasticity; extension status is recorded below and in REPORT.md. There is no stochastic photoreceptor microvillus model.
- The brief's graded equation mixes membrane-current and voltage units. A hybrid implementation requires an explicitly documented unit convention; it cannot be implemented literally as dimensional biophysics.
- Flyvis fitted voltages are in arbitrary units and require explicit calibration assumptions before mapping to millivolts. Fitted parameters are not physiological measurements. Lappalainen 2024, DOI 10.1038/s41586-024-07939-3.
- The released Shiu model freezes both voltage and synaptic state during refractoriness, clears synaptic state on reset, and uses exact linear integration. These source details supersede the incomplete prose summary for a faithful reference comparison.
- Tonic release can produce spontaneous activity in a recurrent network. Zero central dark spikes and stationary equilibration are testable hypotheses, not guarantees from the absence of external input.
- At 240 Hz, four frames are 16.6667 ms, distinct from the nominal 17 ms prediction. A 5.1-degree step in four frames is 306 degrees/s.

## Primary sources inspected

- [Shiu released implementation](https://raw.githubusercontent.com/philshiu/Drosophila_brain_model/main/model.py)
- [Lappalainen neuronal dynamics](https://www.nature.com/articles/s41586-024-07939-3)
- [Maisak 2013](https://pubmed.ncbi.nlm.nih.gov/23925246/)
- [Takemura 2017 corroborating letter-to-direction mapping](https://pmc.ncbi.nlm.nih.gov/articles/PMC5435463/)
- [Brian2 refractory semantics](https://brian2.readthedocs.io/en/stable/user/refractoriness.html)

## Neuromodulation extension

| Attainable | Not attainable |
|---|---|
| Identified release sources, taken from ground-truth transmitter labels and named cell types | A per-synapse map of where dopamine acts |
| Published time constants for clearance, eligibility and memory decay | Absolute concentrations in molar units |
| Per-compartment plasticity **signs** measured in real flies (Aso 2016, PMID 27441388) | Per-synapse plasticity magnitudes |
| Receptor→effect couplings for the handful of receptors with published loss-of-function phenotypes | A quantitative receptor expression level per neuron |
| Reproducing published pairing curves the model was never fitted to | Claiming the model *is* a fly |

- This extension is a model, not a fly. Concentrations are normalized, dimensionless a.u.; no absolute concentration calibration is available.
- Receptor expression per neuron is unavailable. Expression evidence cannot establish quantitative receptor coupling strengths.
- Compartments are volumes without resolved geometry; nitric-oxide diffusion is not spatially resolved. Nitric-oxide annotations must remain in the source audit even before field dynamics are implemented.
- There are no gap junctions or glia; glial clearance and shaping of dopamine are omitted.
- The connectome is from one female; fast-transmitter signs outside explicit corrections are predicted.
- The requested endocrine interface is 76 model neurons, including two unidentified neurosecretory types. A cell type addressable in simulation is not automatically a published driver line.
- Whole-brain real time has not been achieved. No real-time factor is claimed without an executed, duration-qualified benchmark.
- The pre-existing V-C equilibration failure remains unresolved. The visual response gates and octopamine biology test cannot be described as validated on that basis.
- Odour response vectors now use pinned DoOR consensus measurements, with partial coverage. Consensus-to-Hz scaling, adaptation and the choice of stimulus intensity remain assumptions; this is not an odour-response calibration. There is no descending-neuron behaviour decoder.
- Patch 1 resolves the original KC source contradiction: KCs are excluded from aminergic sources and their positive sNPF peptide annotations are preserved independently. Nitric-oxide cotransmission is per neuron, not a whole-cell-type flag.
- Whole-brain V-C failure does not block this extension. The core requires a separate, unmodified-parameter stationarity check; no damping, silencing or compensating gain may be introduced to force a pass.
- V-NM-I remains NOT-RUN because base V-G/V-H are not validated. A receptor gain multiplier by itself is not a substitute for that visual biology measurement.
- Odour responses must come from named DoOR measurements when obtainable. Any synthetic fallback must be labeled SYNTHETIC ODOUR and cannot support claims about odour discrimination, generalisation or identity coding.
- Body trajectories remain unavailable without the separately supplied descending-neuron decoder. Compartment-weighted MBON valence is a distinct, inferred-sign readout, not measured body behaviour.
- The 15 empirical mushroom-body clusters do not reliably recover canonical anatomy. PPL101 aligns to g4 rather than its published g1; seven canonical cluster labels have no supporting label vote. An empirical-cluster perturbation must not be described as an anatomically validated compartment experiment.
- The 13,300-neuron core is stationary for one second from resting initialization with unchanged base parameters, zero input and clamping disabled. This does not establish stability under sensory stimulation or validate the whole-brain model.
- The fixed DoOR-driven diagnostic fails the 2–12% Kenyon-cell sparseness target: OCT activates 68.82% and MCH 68.40%, versus 67.82% during the preceding source-SFR baseline. Both runs remain finite but violate the configured voltage bounds with clamping disabled. They do not establish stable sensory-driven behaviour. See `build/validation_neuromod_odour_sparseness.json` and the saved per-type diagnostics; no compensating gain was added.
- Field sensitivity results are numerical fixtures. Default full-source drive has zero concentration clamps; deliberate stress fixtures that activate the concentration guard are counted separately. Concentration clipping is never silent.
- The frozen-effect receptor adapter and the coupled runtime are distinct validation scopes. The runtime adds evolving fields, actual-spike chemical release feedback, endocrine state, normalized plasticity, replay and the console. V-NM-A retains its original core/fixture scope; additional runtime and biological evidence appears separately in REPORT.md.
- Cited receptor identities were corrected to OAMB on PAM and mAChR-A on KCs. Requested unsupported alternatives remain disabled. Magnitudes and receptor expression coverage are assumptions. OA source-volume overlap reaches only 79 of 307 PAMs; 1,917 KC→MBON edges have no mapped DA source. These coverage gaps are not silently filled.
- The final supplied brief explicitly replaces the historical literal plasticity equation with normalized traces, fixed units, an update order and twelve reference targets. That software reference passes. Zero current DA or KC activity does not erase eligibility history or suppress finite forgetting. The isolated reference does not establish successful closed-loop learning.
- The separate normalized whole-brain variant passes the executed resting-stability tests for both current and conductance models. These results do not replace the historical base failure or establish visual selectivity. Additional sensitivity dynamics remain unrun; static fixed-point results can fail the quiescent criterion even when the continuous equations converge.
- Capacity measurements use an inferred MBON readout, held-out event seeds and unchanged test weights. A bounded two-odour/two-action task does not establish saturation or physical interface bandwidth. Unknown driver-line access remains unknown; numerical addressability is not genetic access.
