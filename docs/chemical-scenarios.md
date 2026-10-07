# Chemical names and scenario context

The interface names chemicals and anatomical regions in full. Its scenario text explains relevant research; it does not classify a fly’s behavior or physiological state from chemical sliders. Concentrations remain arbitrary model units. There is no measured endogenous baseline, cross-chemical equivalence, inferred fasting duration, probability of hunger, or sexual-arousal score.

## Region names

`brain-region-names.js` covers all 96 released chemical compartments and the 79 labels in the released neuropil metadata, including `None` as unassigned. Left and right remain explicit; labels can append their original identifier. Unknown identifiers remain visibly unknown. The `NO` region is **noduli**, while the `NO` chemical is **nitric oxide**.

The region nomenclature follows [Ito et al., 2014](https://pubmed.ncbi.nlm.nih.gov/24559671/), the primary [FlyWire wiring paper](https://www.nature.com/articles/s41586-024-07558-y), and its [annotation paper](https://www.nature.com/articles/s41586-024-07686-5). The official anatomical resource independently identifies the [gall](https://www.virtualflybrain.org/term/ga_l-on-jrc2018unisex-vfb_00107dn7/) and [antennal mechanosensory and motor center](https://www.virtualflybrain.org/term/ammc_l-on-jrc2018unisex-vfb_00107as5/).

Gamma, beta, beta prime, alpha and alpha prime labels expand the mushroom-body names used in [Li et al., 2020](https://elifesciences.org/articles/62576). The UI adds **model cluster** because these local memberships arise from empirical KC-partner clustering and do not establish anatomical recovery; see [compartments.md](compartments.md). Antennal-lobe glomeruli retain published identifiers and show **both sides** because this model pools hemispheres. Their naming follows the [hemibrain analysis](https://elifesciences.org/articles/57443); VM6 subglomeruli remain pooled here. Central-complex layer names follow the [primary central-complex connectome](https://elifesciences.org/articles/66039). Unresolved regions stay unresolved. Hemolymph is marked **symbolic endocrine pool**, not an imaged brain region.

## What a combination can reasonably suggest

- **Food-seeking experiment:** an explicitly chosen low-energy state plus dopamine, short neuropeptide F, or serotonin provides context for a hunger-related experiment. Specific dopamine pathways can have opposing effects on food seeking, so global dopamine alone cannot identify starvation. [Tsao et al., 2018](https://elifesciences.org/articles/35264)
- **Hunger-sensitive smell:** starvation altered local short-neuropeptide-F and insulin signaling in selected odor neurons. This supports a circuit-specific association, not a whole-brain chemical recipe. [Root et al., 2011](https://pmc.ncbi.nlm.nih.gov/articles/PMC3073827/)
- **Wakefulness/activity experiment:** activating octopamine neurons promoted waking. A slider does not establish wakefulness, flight, distress or courtship. [Crocker and Sehgal, 2008](https://pmc.ncbi.nlm.nih.gov/articles/PMC2742176/)
- **Serotonin is not a hunger scale:** a selected serotonergic subset promoted feeding; broader population activation did not reproduce that effect. [Albin et al., 2015](https://pubmed.ncbi.nlm.nih.gov/26344091/)
- **Memory updating:** nitric oxide affected retention and updating in particular mushroom-body dopamine pathways. Its global field is not a forgetting score. [Aso et al., 2019](https://elifesciences.org/articles/49257)
- **Acetylcholine depends on the receptor:** inhibitory muscarinic effects on mushroom-body odor responses differ from fast excitatory transmission. The slow chemical field cannot be read as overall excitation or attention. [Bielopolski et al., 2019](https://elifesciences.org/articles/48264)
- **Tyramine stays separate:** primary flight experiments distinguish tyramine from octopamine. This model does not infer motor readiness from either global value. [Brembs et al., 2007](https://pmc.ncbi.nlm.nih.gov/articles/PMC6672854/)
- **Peptide pool:** this is a model aggregation of distinct peptide sources. It is not one natural molecule and has no single hunger, stress or mating interpretation.

No concentration cutoffs are invented to distinguish these contexts: all positive values receive the same qualified research associations. The values themselves are returned separately. Zero means zero in the supplied model field, not proof that an animal has no such transmitter. A uniform intervention across compartments is different from natural release patterns.

## Sexual arousal is not identifiable here

Research on male courtship links specific dopamine pathways and P1 circuits to mating drive and state-dependent visual processing. These effects depend on circuit identity, sensory cues and history. They do not support a recipe such as “high dopamine plus high octopamine means sexual arousal.” [Zhang et al., 2016](https://www.sciencedirect.com/science/article/pii/S0896627316301994), [Sten et al., 2021](https://www.nature.com/articles/s41586-021-03714-w)

The FlyWire source is an adult **female** brain. A male P1 courtship interpretation is therefore not transferred to this model. Female receptivity would require its own supported circuit and behavioral readout. The UI always states that sexual arousal cannot be inferred. [Dorkenwald et al., 2024](https://www.nature.com/articles/s41586-024-07558-y)

## API and checks

`regionLabel(key, {alias: false})` and `speciesLabel(key, {alias: false})` return strings. The catalog exports `REGION_NAMES`, `SPECIES_NAMES`, `REGION_SOURCES`, and `COMPARTMENT_KEYS`.

`interpretChemicalContext(levels, state)` accepts a partial keyed chemical-control object (finite numbers on 0–2 a.u., matching the backend controls) and optional normalized state variables. It also accepts `{scenario, initial_state}`; explicit state values override preset values. It returns `summary`, `stateContext`, `possibleAssociations`, `limits`, `sourceURLs`, `inputIssues`, and the validated `concentrations`. Association objects have `id`, `label`, `text`, and `sourceURLs`. Source URLs are also exported as `SCENARIO_SOURCES`.

State descriptions compare only provided settings to model endpoints. No state is inferred when it is omitted. The starved preset uses energy 0, dehydrated uses hydration 0, stressed uses stress 1, and fed uses energy 1; these are implementation assumptions, not measurements. Intermediate values do not encode physiological severity. General arousal is explicitly separate from sexual arousal.

Invalid inputs are reported and omitted rather than coerced or clipped. Tests cover all region keys, left/right handling, namespace ambiguity, preservation of unknowns, endpoint overrides, missing state, nonfinite values, deterministic output and the absence of invented physiological thresholds. These are presentation tests; no neural simulation or biological gate is run by this module.
