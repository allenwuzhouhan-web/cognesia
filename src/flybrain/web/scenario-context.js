// Research context, not a behavior decoder. Slider magnitudes are arbitrary units.
import { SPECIES_NAMES } from './brain-region-names.js';

export const SCENARIO_SOURCES = Object.freeze({
  hunger: 'https://elifesciences.org/articles/35264',
  snpf: 'https://pmc.ncbi.nlm.nih.gov/articles/PMC3073827/',
  wake: 'https://pmc.ncbi.nlm.nih.gov/articles/PMC2742176/',
  serotonin: 'https://pubmed.ncbi.nlm.nih.gov/26344091/',
  nitricOxide: 'https://elifesciences.org/articles/49257',
  acetylcholine: 'https://elifesciences.org/articles/48264',
  tyramine: 'https://pmc.ncbi.nlm.nih.gov/articles/PMC6672854/',
  courtship: 'https://www.nature.com/articles/s41586-021-03714-w',
  matingDrive: 'https://www.sciencedirect.com/science/article/pii/S0896627316301994',
  femaleConnectome: 'https://www.nature.com/articles/s41586-024-07558-y',
});

const ASSOCIATIONS = Object.freeze({
  DA: {id:'dopamine',label:'Learning and food-seeking context',
    text:'Specific dopamine pathways can promote or suppress food seeking. Their effects depend on mushroom-body region and timing; a global dopamine value does not identify hunger or reward.',
    sourceURLs:[SCENARIO_SOURCES.hunger]},
  OA: {id:'octopamine',label:'Wakefulness and activity context',
    text:'Activating octopamine neurons promoted wakefulness in fly experiments. A nonzero global field is relevant to testing arousal-sensitive circuits, but does not establish wakefulness, stress or sexual arousal.',
    sourceURLs:[SCENARIO_SOURCES.wake]},
  '5HT': {id:'serotonin',label:'Circuit-dependent feeding context',
    text:'Activating one serotonergic subset promoted feeding; activating the broader serotonin population did not have the same effect. A global serotonin setting cannot specify hunger or calmness.',
    sourceURLs:[SCENARIO_SOURCES.serotonin]},
  NO: {id:'nitric-oxide',label:'Memory-updating context',
    text:'In particular mushroom-body dopamine pathways, nitric oxide shortened memory retention and supported updating. This does not make a global nitric-oxide level a forgetting or mood score.',
    sourceURLs:[SCENARIO_SOURCES.nitricOxide]},
  sNPF: {id:'short-neuropeptide-f',label:'Hunger-sensitive smell context',
    text:'Starvation enhanced food-odor sensitivity through local short-neuropeptide-F signaling and insulin regulation in selected odor neurons. The effect is circuit-specific; this global field is not a starvation measurement.',
    sourceURLs:[SCENARIO_SOURCES.snpf]},
  peptide_pool: {id:'peptide-pool',label:'Mixed peptide model signal',
    text:'This field pools distinct peptide sources. It has no single natural chemical identity or validated mapping to hunger, stress or sexual state.',sourceURLs:[]},
  TA: {id:'tyramine',label:'Movement-modulation context',
    text:'Tyramine and octopamine have distinct roles in fly flight experiments. Tyramine is kept separate; its global value is not a measure of flight readiness or arousal.',
    sourceURLs:[SCENARIO_SOURCES.tyramine]},
  ACh: {id:'acetylcholine',label:'Receptor-dependent sensory processing',
    text:'Muscarinic acetylcholine signaling can suppress mushroom-body odor responses, unlike fast excitatory transmission. This slow field does not directly measure attention or overall neural activity.',
    sourceURLs:[SCENARIO_SOURCES.acetylcholine]},
});

const STATE_KEYS = ['energy','hydration','arousal','circadian_phase','stress'];
const PRESETS = Object.freeze({
  baseline:{energy:1,hydration:1,arousal:0,circadian_phase:0,stress:0},
  fed:{energy:1,hydration:1,arousal:0,circadian_phase:0,stress:0},
  starved:{energy:0,hydration:1,arousal:0,circadian_phase:0,stress:0},
  dehydrated:{energy:1,hydration:0,arousal:0,circadian_phase:0,stress:0},
  stressed:{energy:1,hydration:1,arousal:0,circadian_phase:0,stress:1},
});

const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const validNumber = value => typeof value === 'number' && Number.isFinite(value);

/**
 * levels: partial {DA,OA,'5HT',NO,sNPF,peptide_pool,TA,ACh}, each 0..2 a.u.
 * state: partial normalized state, or {scenario, initial_state}; explicit values win.
 * The same research context applies to every positive magnitude: no invented
 * physiological thresholds, cross-chemical rankings, probabilities or diagnoses.
 */
export function interpretChemicalContext(levels={}, state={}) {
  const inputIssues=[], concentrations=[], stateContext=[], possibleAssociations=[];
  if (!isObject(levels)) { inputIssues.push('Chemical levels must be a keyed object.'); levels={}; }
  if (Object.keys(levels).some(key=>!Object.hasOwn(SPECIES_NAMES,key))) inputIssues.push('Unknown chemical keys were ignored.');
  for (const [key,label] of Object.entries(SPECIES_NAMES)) {
    if (!Object.hasOwn(levels,key)) continue;
    const value=levels[key];
    if (!validNumber(value) || value<0 || value>2) {
      inputIssues.push(`${label}: expected a finite number from 0 to 2 a.u.`); continue;
    }
    concentrations.push({key,label,value,unit:'a.u.'});
    if (value>0) possibleAssociations.push({...ASSOCIATIONS[key],sourceURLs:[...ASSOCIATIONS[key].sourceURLs]});
  }
  if (!isObject(state)) {inputIssues.push('State inputs must be an object.');state={};}
  let supplied={};
  if (Object.hasOwn(state,'scenario')) {
    if (typeof state.scenario==='string' && Object.hasOwn(PRESETS,state.scenario)) supplied={...PRESETS[state.scenario]};
    else inputIssues.push('Unknown state preset was ignored.');
  }
  if (Object.hasOwn(state,'initial_state')) {
    if (isObject(state.initial_state)) supplied={...supplied,...state.initial_state};
    else inputIssues.push('Initial state must be an object.');
  }
  for (const key of STATE_KEYS) if (Object.hasOwn(state,key)) supplied[key]=state[key];
  const normalized={};
  for (const key of STATE_KEYS) {
    if (!Object.hasOwn(supplied,key)) continue;
    const value=supplied[key];
    if (!validNumber(value) || value<0 || value>1 || (key==='circadian_phase' && value===1)) {
      inputIssues.push(`${key}: expected a finite normalized state value${key==='circadian_phase'?' below 1':''}.`);continue;
    }
    normalized[key]=value;
  }
  if (Object.hasOwn(normalized,'energy')) {
    const value=normalized.energy;
    stateContext.push({id:'energy', label:value===0?'Starvation-like model input':value===1?'Fed-energy model input':'Intermediate energy model input',
      text:value===0?'Energy is set to the model’s low-energy endpoint. This resembles its starvation preset by construction, not from the chemical combination.':
        value===1?'Energy is set to the model’s fed endpoint. This is a configured boundary state, not measured satiety.':
        'Energy lies between the model’s low-energy and fed endpoints. It does not specify how long a fly has fasted.'});
  }
  if (Object.hasOwn(normalized,'hydration')) {
    const value=normalized.hydration;
    stateContext.push({id:'hydration',label:value===0?'Dehydration-like model input':value===1?'Full-hydration model input':'Intermediate hydration model input',
      text:'Hydration is an assumed internal-state input. It is not inferred from these chemicals or calibrated to body water loss.'});
  }
  if (Object.hasOwn(normalized,'arousal')) stateContext.push({id:'arousal',label:normalized.arousal===0?'Quiet arousal input':'General arousal input',
    text:'The arousal variable is a general activity setting. It is not a sexual-arousal variable.'});
  if (Object.hasOwn(normalized,'stress')) stateContext.push({id:'stress',label:normalized.stress===0?'Zero stress-axis input':'Stress-axis model input',
    text:'The stress axis is an assumed control. Its value does not establish distress or any particular natural stressor.'});
  if (Object.hasOwn(normalized,'circadian_phase')) stateContext.push({id:'circadian_phase',label:'Circadian phase input',
    text:'This is the model’s cycle position, without calibration to observed sleep or local clock time.'});
  if (normalized.energy<1 && concentrations.some(x=>x.value>0 && ['DA','sNPF','5HT'].includes(x.key))) {
    possibleAssociations.unshift({id:'food-seeking-combination',label:'Food-seeking hypothesis to explore',
      text:'The chosen low-energy input and these signaling pathways provide context for a food-seeking experiment. They do not predict approach without an odor, circuit activity and a tested readout.',
      sourceURLs:[SCENARIO_SOURCES.hunger,SCENARIO_SOURCES.snpf]});
  }
  possibleAssociations.push({id:'sexual-arousal-unresolved',label:'Sexual arousal cannot be inferred',
    text:'Male courtship studies involve specific dopamine and P1 circuits, sensory cues and mating history. This female FlyWire brain and eight global chemical values do not identify sexual arousal or mating drive.',
    sourceURLs:[SCENARIO_SOURCES.courtship,SCENARIO_SOURCES.matingDrive,SCENARIO_SOURCES.femaleConnectome]});
  const limits=[
    'Qualitative research context only; no validated state or behavior diagnosis is produced.',
    'Arbitrary units have no measured natural baseline. Larger values are not calibrated as physiological high levels; zero does not establish chemical absence in an animal.',
    'Location, receptor type, timing, sensory input and history matter. Different chemicals cannot be compared by slider magnitude alone.',
    'A uniform whole-brain chemical intervention does not reproduce natural localized release or a complete animal state.',
    'State presets and pooled peptide values are model assumptions. Behavioral associations are not validation of this simulator.',
  ];
  const positive=concentrations.filter(x=>x.value>0);
  const chemicalSummary=positive.length?`${positive.map(x=>x.label).join(', ')} ${positive.length===1?'is':'are'} set above zero in model units.`:
    concentrations.length?'All supplied chemical levels are zero in model units.':'No chemical levels were supplied.';
  const stateSummary=stateContext.length?' Configured state inputs are described separately below.':' No internal state is inferred from these values.';
  const sourceURLs=[...new Set(possibleAssociations.flatMap(x=>x.sourceURLs))];
  return {summary:chemicalSummary+stateSummary,stateContext,possibleAssociations,limits,sourceURLs,inputIssues,concentrations};
}
