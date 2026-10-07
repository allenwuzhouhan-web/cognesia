import { CHEMICAL_SPECIES } from './chemistry.js';
import { speciesLabel } from './brain-region-names.js';
import { interpretChemicalContext } from './scenario-context.js';

const STATE_FIELDS = [
  ['energy', 'Energy reserves'], ['hydration', 'Hydration'],
  ['arousal', 'General arousal / wakefulness'], ['stress', 'Stress drive'],
  ['circadian_phase', 'Daily clock phase'],
];
const INITIAL = {energy:1, hydration:1, arousal:0, stress:0, circadian_phase:0};
export function presetState(name) {
  return {...INITIAL, ...(name==='starved'?{energy:0}:name==='dehydrated'?{hydration:0}:name==='stressed'?{stress:1}:{})};
}
export function collectChemicalLevels(rows) {
  const result={};
  for(const {species, enabled, value} of rows) {
    if(!CHEMICAL_SPECIES.includes(species)) throw Error('Unknown chemical species.');
    if(enabled) {
      if(typeof value!=='number'||!Number.isFinite(value)||value<0||value>2) throw Error(`${speciesLabel(species)} must be between 0 and 2 model units.`);
      result[species]=value;
    }
  }
  return result;
}

export function initializeChemicalControls({host, onEdited=()=>{}}) {
  const $=selector=>host.querySelector(selector);
  const lastLevels=Object.fromEntries(CHEMICAL_SPECIES.map(key=>[key,0]));
  const lastState={...INITIAL};
  const sliders=$('#chemical-level-sliders'), stateSliders=$('#initial-state-sliders');
  for(const species of CHEMICAL_SPECIES) {
    const row=document.createElement('div');row.className='chemical-level-row';
    const name=speciesLabel(species);
    row.innerHTML=`<div class="chemical-level-head"><label for="level-${species}" title="${name}">${name}</label>
      <label class="chemical-manual-toggle" title="Unchecked: source release and clearance control this chemical"><input type="checkbox" id="override-${species}" aria-label="Set ${name} manually"> Manual</label>
      <input type="number" id="number-${species}" aria-label="${name} exact concentration" title="${name}, model units (a.u.)" min="0" max="2" step="any" value="0" required></div>
      <input type="range" id="level-${species}" min="0" max="2" step="0.01" value="0" aria-label="${name} concentration" title="${name}, model units (a.u.)">
      <output id="level-output-${species}" class="chemical-mode-status">Model controlled</output>`;
    sliders.append(row);
    const range=$(`#level-${species}`),number=$(`#number-${species}`),override=$(`#override-${species}`);
    const change=input=>{
      if(input===number && (!number.validity.valid || number.value==='')) return;
      (input===number?range:number).value=input.value;lastLevels[species]=Number(input.value);override.checked=true;update();onEdited();
    };
    range.addEventListener('input',()=>change(range));number.addEventListener('input',()=>change(number));
    override.addEventListener('change',()=>{update();onEdited();});
  }
  for(const [key,label] of STATE_FIELDS) {
    const row=document.createElement('label');row.className='initial-state-row';
    row.innerHTML=`<span>${label}<input id="initial-number-${key}" type="number" aria-label="${label} exact value" min="0" max="${key==='circadian_phase'?'.9999999999999999':'1'}" step="any" value="${INITIAL[key]}" required></span><input id="initial-${key}" aria-label="${label}" type="range" min="0" max="1" step=".01" value="${INITIAL[key]}">`;
    stateSliders.append(row);
    const range=$(`#initial-${key}`),number=$(`#initial-number-${key}`);
    range.addEventListener('input',()=>{number.value=key==='circadian_phase'?Math.min(.99,Number(range.value)):range.value;lastState[key]=Number(number.value);update();onEdited();});
    number.addEventListener('input',()=>{if(!number.validity.valid||number.value==='')return;range.value=number.value;lastState[key]=Number(number.value);update();onEdited();});
  }
  // Keep scientific qualifications available without repeating them beside every slider.
  const explanation=document.createElement('details');explanation.className='chemical-explanation';
  const explanationTitle=document.createElement('summary');explanationTitle.textContent='Assumptions and context';explanation.append(explanationTitle);
  for(const node of [...host.children])if(node.tagName==='P'||node.classList.contains('scenario-context'))explanation.append(node);
  host.append(explanation);
  const heading=host.querySelector('h3');if(heading)heading.textContent='Chemical levels (a.u.)';
  $('#chemical-set-all').textContent='Set all manually';$('#chemical-model-reset').textContent='Use model control';
  const validInput=input=>input.value!==''&&input.validity.valid;
  function getOptions(strict=false) {
    if(strict)for(const [key,label] of STATE_FIELDS)if(!validInput($(`#initial-number-${key}`)))throw Error(`${label} needs a valid value from 0 ${key==='circadian_phase'?'up to, but below,':'to'} 1.`);
    if(strict)for(const key of ['feeding','drinking','aversive','locomotion'])if(!validInput($('#state-'+key)))throw Error(`${key} drive needs a valid value from 0 to 1.`);
    return {enabled:$('#chemical-enabled').checked, scenario:$('#state-scenario').value,
      plasticity_enabled:$('#chemical-plasticity').checked, initial_state:{...lastState},
      chemical_control_mode:$('#chemical-control-mode').value,
      chemical_levels:collectChemicalLevels(CHEMICAL_SPECIES.map(species=>{const number=$(`#number-${species}`);return {species,enabled:$(`#override-${species}`).checked,value:strict&&!validInput(number)?NaN:lastLevels[species]};})),
      ...Object.fromEntries(['feeding','drinking','aversive','locomotion'].map(key=>[key,Number($('#state-'+key).value)]))};
  }
  function setState(values) {for(const [key] of STATE_FIELDS){lastState[key]=values[key]??INITIAL[key];$(`#initial-${key}`).value=lastState[key];$(`#initial-number-${key}`).value=lastState[key];}}
  function update() {
    const options=getOptions();
    for(const species of CHEMICAL_SPECIES) {
      const value=options.chemical_levels[species];
      $(`#level-output-${species}`).textContent=value===undefined?'Model controlled':`${Number(value.toPrecision(5))} a.u.`;
      $(`#level-${species}`).closest('.chemical-level-row').classList.toggle('manually-set',value!==undefined);
    }
    const matches=Object.entries(presetState(options.scenario)).every(([k,v])=>options.initial_state[k]===v);
    $('#scenario-note').textContent=`${matches?'Preset':'Custom state'} · energy ${options.initial_state.energy.toFixed(2)}, hydration ${options.initial_state.hydration.toFixed(2)}, general arousal ${options.initial_state.arousal.toFixed(2)}, stress ${options.initial_state.stress.toFixed(2)}. Applies to the next run.`;
    const manual=Object.keys(options.chemical_levels).length;
    $('#chemical-intervention-note').textContent=!options.enabled?'Chemical modulation is disabled. These settings will not affect the next run.':manual?`${manual} chemical${manual===1?'':'s'} ${options.chemical_control_mode==='clamped'?'held at your values throughout the next run':'initialized at your values, then allowed to evolve'}. Values apply across all model compartments, including the matched baseline.`:'All chemicals follow the model’s source release and clearance. Move a slider to set that chemical manually.';
    const context=interpretChemicalContext(options.chemical_levels,options.initial_state);
    $('#scenario-context-summary').textContent=context.summary;
    const items=[...(context.stateContext||[]),...(context.possibleAssociations||[])];
    $('#scenario-context-items').replaceChildren(...items.map(item=>{const li=document.createElement('li');const strong=document.createElement('strong');strong.textContent=item.label;li.append(strong,document.createTextNode(' — '+item.text));return li;}));
    $('#scenario-context-limits').replaceChildren(...(context.limits||[]).map(text=>{const p=document.createElement('p');p.textContent=text;return p;}));
    $('#scenario-context-sources').replaceChildren(...(context.sourceURLs||[]).map((url,i)=>{const a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener';a.textContent=`Study ${i+1}`;return a;}));
  }
  $('#state-scenario').addEventListener('change',()=>{setState(presetState($('#state-scenario').value));update();onEdited();});
  for(const id of ['chemical-enabled','chemical-plasticity','chemical-control-mode','state-feeding','state-drinking','state-aversive','state-locomotion'])$('#'+id).addEventListener('change',()=>{update();onEdited();});
  $('#chemical-model-reset').addEventListener('click',()=>{for(const species of CHEMICAL_SPECIES)$(`#override-${species}`).checked=false;update();onEdited();});
  $('#chemical-set-all').addEventListener('click',()=>{for(const species of CHEMICAL_SPECIES)$(`#override-${species}`).checked=true;update();onEdited();});
  function restore(options={}) {
    const c=options.neuromod||{};
    $('#chemical-enabled').checked=!!c.enabled;$('#chemical-plasticity').checked=c.plasticity_enabled!==false;
    $('#state-scenario').value=['fed','starved','dehydrated','stressed'].includes(c.scenario)?c.scenario:'fed';
    setState(c.initial_state||presetState($('#state-scenario').value));
    $('#chemical-control-mode').value=c.chemical_control_mode==='clamped'?'clamped':'initial';
    for(const species of CHEMICAL_SPECIES) {
      const value=c.chemical_levels?.[species];$(`#override-${species}`).checked=value!==undefined;
      lastLevels[species]=value??0;
      $(`#level-${species}`).value=value??0;$(`#number-${species}`).value=value??0;
    }
    for(const key of ['feeding','drinking','aversive','locomotion'])$('#state-'+key).value=c[key]??0;
    update();
  }
  update();
  return {getOptions,restore,update};
}
