/* Model selection, scientific run settings, and one execution surface. */
import {checkedTimeline} from './sequence-model.js';
const DRAFT_KEY = 'cognesia.experiment.draft.v1';
const clone = value => JSON.parse(JSON.stringify(value));
export function defaultExperimentDraft() {
  return {version:1, model_picker_version:2, model_id:'banc-888', timeline:{schema_version:1,name:'Untitled experiment',blocks:[]},
    interventions:[], research_selection:{mode:'full',boundary:'recorded',regions:[],cell_types:[],root_ids:[],modules:[]},
    recording_selection:{mode:'full',regions:[],cell_types:[],root_ids:[]},
    peripheral:{enabled:false,modules:[]}, enzymes:{enabled:false,activities:{ChAT:1,AChE:1,Tbh:1}}, from_checkpoint:null};
}
export function checkedDraft(value) {
  if (!value || value.version !== 1 || !Array.isArray(value.timeline?.blocks)) throw Error('Unsupported experiment draft');
  const result = {...defaultExperimentDraft(),...clone(value)};
  for (const block of result.timeline.blocks) {
    if (!Number.isFinite(block.start_ms) || block.start_ms < 0 || !Number.isFinite(block.duration_ms) || block.duration_ms < 0)
      throw Error('Timeline times must be finite and nonnegative');
  }
  return result;
}
export function initialExperimentDraft(saved) {
  if (!saved) return defaultExperimentDraft();
  const value=checkedDraft(saved);
  // Keep source identity for checkpoints and imported experiments.
  if (saved.model_picker_version !== 2 && !saved.from_checkpoint && !saved.legacy_protocol) value.model_id='banc-888';
  value.model_picker_version=2;
  return value;
}
export function simulationProgress(value) {
  const names={queued:'Queued',preparing:'Preparing model',loading:'Loading model',preequilibration:'Settling initial state',stimulus:'Experiment',paired_baseline:'Matched baseline',baseline:'Matched baseline',reference_stimulus:'Boundary reference',reference_baseline:'Reference baseline',saving:'Saving results',complete:'Complete',cancelled:'Stopped',failed:'Failed'};
  const raw=value?.progress, fraction=value?.status==='complete'?1:Number.isFinite(raw)?Math.max(0,Math.min(1,raw)):null;
  const phase=['complete','failed','cancelled'].includes(value?.status)?value.status:value?.phase||value?.status||'ready';
  return {fraction,label:names[phase]||phase.replaceAll('_',' '),modelTime:Number.isFinite(value?.model_time_ms)?value.model_time_ms:null,active:!!value&&!['complete','failed','cancelled'].includes(value.status)};
}
const modelNames={'paralimbo-v0-1-0':'ParaLimbo 0.1 · BANC × FlyWire','banc-888':'BANC','cognesia-fused-v1':'Cognesia','flywire-783':'FlyWire'};
function element(tag, text, className) {
  const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;
}
function button(text,handler){const node=element('button',text);node.type='button';node.addEventListener('click',handler);return node;}
function input(type,value,onChange,attrs={}) {
  const node=document.createElement('input');node.type=type;node.value=value??'';
  Object.assign(node,attrs);node.addEventListener('change',()=>onChange(type==='number'?Number(node.value):node.value));return node;
}
function field(label,control){const node=element('label',undefined,'experiment-field');node.append(element('span',label),control);return node;}
const kindNames={visual:'Visual stimulus',rest:'Rest',electrode:'Electrode',chemical:'Chemical level',enzyme:'Enzyme activity',intervention:'Targeted intervention',recording:'Recording window',checkpoint:'Checkpoint'};
function select(options,value,onChange) {
  const node=document.createElement('select');for(const [key,label] of options)node.add(new Option(label,key));node.value=value;
  node.addEventListener('change',()=>onChange(node.value));return node;
}
function split(value){return value.split(',').map(x=>x.trim()).filter(Boolean);}

export function initializeExperimentControls({host,requestJSON,onStatus,onLiveFrame,getSelectedNeuron,getSelectedTarget,getBaseOptions,onModelChanged,runDraft,getRunOptions,onRestoreOptions}) {
  let draft=defaultExperimentDraft(),job=null,socket=null,frameTimer=null,pendingFrame=null,modelCatalog=null,organCatalog=[],lastCommandError=null,configurationRevision=0;
  const timelineSubscribers=new Set();
  try {const saved=localStorage.getItem(DRAFT_KEY);if(saved){const parsed=JSON.parse(saved);if(parsed.model_picker_version!==2)localStorage.setItem('cognesia.experiment.before-model-picker-v2',saved);draft=initialExperimentDraft(parsed);}localStorage.setItem(DRAFT_KEY,JSON.stringify(draft));}catch{}
  host.classList.add('experiment-session');
  const execution=element('section',undefined,'simulation-execution');execution.id='simulation-execution';host.append(execution);
  const toolbar=element('div',undefined,'session-toolbar');toolbar.setAttribute('aria-label','Simulation execution');
  const run=document.querySelector('#run-button'),progress=document.querySelector('#job-progress');
  toolbar.append(run);
  const pause=button('Pause',()=>command('pause')),resume=button('Resume',()=>command('resume')),
    step=button('Step 1 ms',()=>command('step',{duration_ms:1})),checkpoint=button('Save checkpoint',()=>command('checkpoint',{label:'Saved from Simulate'})),
    stop=button('Stop',()=>command('stop'));
  const metrics=element('span','Ready','session-metrics');metrics.setAttribute('role','status');
  toolbar.append(pause,resume,step,checkpoint,stop,metrics);execution.append(toolbar,progress);
  const progressTrack=progress?.querySelector('div');
  progressTrack?.setAttribute('role','progressbar');progressTrack?.setAttribute('aria-label','Simulation progress');progressTrack?.setAttribute('aria-valuemin','0');progressTrack?.setAttribute('aria-valuemax','100');
  const emergency=document.querySelector('#stop-all');
  const emergencyFooter=element('div',undefined,'simulation-emergency');emergencyFooter.id='simulation-emergency';
  if(emergency){emergency.textContent='■ Emergency stop ALL';emergency.title='Immediately stop every active simulation worker. Already saved results are retained.';emergencyFooter.append(emergency);host.append(emergencyFooter);}
  // The legacy cancellation button is retained for compatibility but no longer
  // offers a second execution surface inside the progress display.
  const oldCancel=document.querySelector('#cancel-job');if(oldCancel){oldCancel.hidden=true;oldCancel.classList.add('legacy-session-cancel');}
  const editor=document.createElement('details');editor.className='experiment-editor';
  editor.id='experiment-advanced-settings';editor.append(element('summary','Advanced settings'));
  const content=element('div',undefined,'experiment-design-grid');editor.append(content);host.append(editor);
  const status=element('p','','experiment-draft-status');status.setAttribute('role','status');content.append(status);

  function save(){try{localStorage.setItem(DRAFT_KEY,JSON.stringify(draft));}catch{}status.textContent='';invalidatePreview();for(const listener of timelineSubscribers)listener(clone(draft.timeline));}
  function report(error){status.textContent=error.message||String(error);onStatus?.(status.textContent);}
  async function command(action,extra={}) {
    if(!job?.id)return;
    try {
      const result=await requestJSON(`/api/sessions/${encodeURIComponent(job.id)}/commands`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,...extra})});
      metrics.textContent=`${action} requested · waiting for the engine`;
      return result;
    }catch(error){report(error);}
  }
  function updateJob(value) {
    job=value&&!['complete','failed','cancelled'].includes(value.status)?value:null;
    renderQueue();
    const active=!!job&&!['complete','failed','cancelled'].includes(job.status),paused=job?.status==='paused';
    pause.disabled=!active||paused;resume.disabled=!active||!paused;step.disabled=!active||!paused;checkpoint.disabled=!active||!!job?.options?.legacy_protocol;stop.disabled=!active;
    checkpoint.title=job?.options?.legacy_protocol?'Legacy engine: restart checkpoints unavailable.':'';
    const state=simulationProgress(value);
    if(progress){progress.hidden=!value;const fill=progressTrack?.querySelector('span');if(fill)fill.style.width=`${(state.fraction??0)*100}%`;progressTrack?.setAttribute('aria-valuenow',String(Math.round((state.fraction??0)*100)));progressTrack?.setAttribute('aria-valuetext',`${state.label}${state.fraction===null?'':` · ${Math.round(state.fraction*100)}%`}`);const message=progress.querySelector('p');if(message)message.textContent=value?.error||value?.message||state.label;}
    if(job)metrics.textContent=`${state.label}${paused?' · paused':''}${state.modelTime===null?'':` · ${state.modelTime.toLocaleString()} ms`}${state.fraction===null?'':` · ${Math.round(state.fraction*100)}%`}`;
    else{metrics.textContent=value?state.label:'Ready';pendingFrame=null;if(frameTimer){cancelAnimationFrame(frameTimer);frameTimer=null;}}
    if(value?.checkpoint_id)status.textContent='Checkpoint saved.';
    const reply=value?.last_command;
    if(reply?.status==='rejected'&&reply.request_id!==lastCommandError){lastCommandError=reply.request_id;report(new Error(reply.error||'The engine rejected this command.'));}
  }
  function stream(id) {
    socket?.close();socket=null;pendingFrame=null;if(frameTimer){cancelAnimationFrame(frameTimer);frameTimer=null;}
    if(!id)return;
    socket=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws/sessions/${encodeURIComponent(id)}`);
    const activeSocket=socket;
    socket.addEventListener('message',event=>{
      if(socket!==activeSocket)return;
      try {
        const message=JSON.parse(event.data);
        if(message.type==='session')updateJob(message.session);
        if(message.type==='frame') {
          pendingFrame=message.frame;
          if(!frameTimer)frameTimer=requestAnimationFrame(()=>{
            frameTimer=null;const frame=pendingFrame;pendingFrame=null;if(!frame)return;
            onLiveFrame?.(frame);
            const speed=frame.speed_ratio??frame.real_time_factor;
            const live=simulationProgress({...job,...frame});metrics.textContent=`${live.label}${job?.status==='paused'?' · paused':''} · ${Number(frame.model_time_ms||0).toLocaleString()} ms${Number.isFinite(speed)?` · ${speed.toFixed(2)}× speed`:''}`;
          });
        }
      }catch(error){report(error);}
    });
    socket.addEventListener('error',()=>{status.textContent='Stream disconnected; simulation continues. Saved recordings remain available.';});
  }

  const modelSection=element('section',undefined,'experiment-model-settings');modelSection.id='experiment-model-settings';
  const models=select([['paralimbo-v0-1-0','ParaLimbo 0.1 · BANC × FlyWire'],['banc-888','BANC'],['cognesia-fused-v1','Cognesia'],['flywire-783','FlyWire']],draft.model_id,value=>{draft.model_id=value;save();onModelChanged?.(value);loadCatalogs();});
  models.id='experiment-model';models.setAttribute('aria-label','Connectome model');
  const modelDescription=element('p','','model-description');
  const sourceTools=element('details',undefined,'model-source-tools');sourceTools.append(element('summary','Model sources'),modelDescription,button('Refresh models',loadCatalogs),button('Acquire BANC sources',()=>modelAction('acquire-banc')),button('Build Cognesia model',()=>modelAction('compile-fused')));
  modelSection.append(field('Model',models),sourceTools);host.append(modelSection);

  const setup=element('section',undefined,'experiment-design-section pre-simulation-settings');setup.id='pre-simulation-settings';setup.append(element('h3','Simulation settings'));host.append(setup);
  const clocks=element('div',undefined,'simulation-clock-grid');
  for(const[id,label]of [['compute-duration','Duration (ms)'],['compute-timestep','Time step (ms)'],['compute-snapshot','Save a sample every (ms)'],['compute-threads','CPU threads']]){
    const control=document.querySelector(`#${id}`);if(control){clocks.append(field(label,control));control.addEventListener('change',invalidatePreview);}
  }
  setup.append(clocks);
  const scope=element('div',undefined,'simulation-goals');scope.append(element('h3','Compute and save'));
  const fullModel=input('checkbox','',()=>{});fullModel.checked=draft.research_selection.mode==='full';
  const selectedTissue=element('div',undefined,'simulation-selected-tissue');
  const selectionMode={get value(){return fullModel.checked?'full':'selected';},set value(value){fullModel.checked=value==='full';selectedTissue.hidden=fullModel.checked;}};
  fullModel.addEventListener('change',()=>{draft.research_selection.mode=fullModel.checked?'full':'selected';selectedTissue.hidden=fullModel.checked;save();});
  scope.append(field('Simulate the entire model',fullModel));
  const regions=input('text',(draft.research_selection.regions||[]).join(', '),value=>{draft.research_selection.regions=split(value);save();},{placeholder:'Region names'});
  const cellTypes=input('text',(draft.research_selection.cell_types||[]).join(', '),value=>{draft.research_selection.cell_types=split(value);save();},{placeholder:'e.g. T4a, T5a'});
  const rootIds=input('text',(draft.research_selection.root_ids||[]).join(', '),value=>{draft.research_selection.root_ids=split(value);save();},{placeholder:'Exact neuron IDs, comma separated'});
  const reference=input('text',draft.research_selection.reference_id||'',value=>{draft.research_selection.reference_id=value||null;save();},{placeholder:'Compatible reference result ID'});
  const boundary=select([['recorded','Replay saved surroundings'],['isolated','Isolate selected tissue'],['full_context','Simulate surrounding tissue']],draft.research_selection.boundary||'recorded',value=>{draft.research_selection.boundary=value;reference.hidden=value!=='recorded';save();});
  selectedTissue.append(field('Regions',regions),field('Cell types',cellTypes),field('Neuron IDs',rootIds),field('Surrounding tissue',boundary),field('Reference result',reference));
  selectedTissue.append(element('p','Replayed surroundings cannot respond to changes in the selected tissue.'));
  selectedTissue.hidden=fullModel.checked;scope.append(selectedTissue);
  const allNeurons=input('checkbox','',()=>{});allNeurons.checked=draft.recording_selection.mode==='full';
  const selectedRecording=element('div',undefined,'simulation-selected-recording');selectedRecording.hidden=allNeurons.checked;
  const recordScope={get value(){return allNeurons.checked?'full':'selected';},set value(value){allNeurons.checked=value==='full';selectedRecording.hidden=allNeurons.checked;}};
  allNeurons.addEventListener('change',()=>{draft.recording_selection.mode=allNeurons.checked?'full':'selected';selectedRecording.hidden=allNeurons.checked;save();});
  scope.append(field('Save voltage for all simulated neurons',allNeurons));
  const recordFields={};
  for(const[key,label]of [['regions','Save regions'],['cell_types','Save cell types'],['root_ids','Save neuron IDs']]){recordFields[key]=input('text',(draft.recording_selection[key]||[]).join(', '),value=>{draft.recording_selection[key]=split(value);save();});selectedRecording.append(field(label,recordFields[key]));}
  scope.append(selectedRecording);
  const prepareReference=input('checkbox','',()=>{});prepareReference.checked=!!draft.prepare_reference;
  prepareReference.addEventListener('change',()=>{draft.prepare_reference=prepareReference.checked;save();});
  const referenceDetails=element('details');referenceDetails.append(element('summary','Boundary reference'),field('Save full-model reference for a later selected-tissue run',prepareReference));scope.append(referenceDetails);
  scope.append(element('p','Every run saves an experiment and its matched baseline.','simulation-baseline-note'));setup.append(scope);
  let lastPreview=null;const previewOutput=element('p','Check the selected model before starting.','target-preview');previewOutput.setAttribute('role','status');
  const previewStats=element('div',undefined,'simulation-size-grid');
  const neuronCount=element('output','—'),connectionCount=element('output','—'),memoryCount=element('output','—');
  for(const[label,node]of [['Neurons',neuronCount],['Connections',connectionCount],['Estimated memory',memoryCount]]){const item=element('div');item.append(node,element('span',label));previewStats.append(item);}
  const previewButton=button('Check model size',()=>preview().catch(report));previewButton.className='simulation-preview-button';
  const previewDetails=element('details');previewDetails.append(element('summary','Size and target details'),previewOutput,button('Export target IDs',()=>{if(lastPreview)download('cognesia-target-preview.json',lastPreview);else report(Error('Check model size first.'));}));
  setup.append(previewStats,previewButton,previewDetails);
  function invalidatePreview(){configurationRevision++;lastPreview=null;neuronCount.textContent='—';connectionCount.textContent='—';memoryCount.textContent='—';previewOutput.textContent='Check model size after changing settings.';}
  async function preview(){
    const revision=configurationRevision;
    previewButton.disabled=true;previewButton.textContent='Checking…';
    try{const options=getRunOptions?.()||getBaseOptions?.()||{},targets=[];
      for(const block of draft.timeline.blocks){if(block.electrode?.target)targets.push(block.electrode.target);if(block.intervention?.target)targets.push(block.intervention.target);if(block.intervention?.pre)targets.push(block.intervention.pre);if(block.intervention?.post)targets.push(block.intervention.post);}
      const requestKey=JSON.stringify({model_id:draft.model_id,selection:options.prepare_reference?{mode:'full'}:draft.research_selection,options,targets});
      const value=await requestJSON('/api/selection/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:requestKey});
      if(revision!==configurationRevision||draft.model_id!==JSON.parse(requestKey).model_id)return null;
      neuronCount.textContent=Number(value.selection.simulated_neurons).toLocaleString();
      const edges=value.simulated_connections??value.selection.simulated_connections;connectionCount.textContent=Number.isFinite(edges)?edges.toLocaleString():'Unavailable';
      memoryCount.textContent=`${(value.memory_estimate.total_working_bytes/1e9).toFixed(2)} GB`;
      previewOutput.textContent=`${value.selection.incoming_cut_edges.toLocaleString()} incoming boundary connections. ${value.sequence.join(' → ')}. ${value.targets.map((target,i)=>`Target ${i+1}: ${target.count} neurons`).join('; ')} ${value.memory_estimate.note}`;
      lastPreview=value;return value;
    }catch(error){neuronCount.textContent='—';connectionCount.textContent='—';memoryCount.textContent='—';previewOutput.textContent=error.message||String(error);previewDetails.open=true;throw error;}
    finally{previewButton.disabled=false;previewButton.textContent='Check model size';}
  }

  const organs=element('section',undefined,'experiment-design-section');organs.id='experiment-organ-settings';organs.append(element('h3','Body modules'));
  const organEnabled=input('checkbox','',()=>{});organEnabled.checked=!!draft.peripheral.enabled;
  organEnabled.addEventListener('change',()=>{draft.peripheral.enabled=organEnabled.checked;save();});scope.append(field('Include selected body modules',organEnabled));
  const organSearch=input('search','',renderOrgans,{placeholder:'Find body module…'}),organList=element('div',undefined,'organ-catalogue');
  organSearch.addEventListener('input',renderOrgans);organs.append(organSearch,organList);host.append(organs);
  function renderOrgans() {
    const query=organSearch.value.toLowerCase();organList.replaceChildren();
    const entries=organCatalog.filter(item=>`${item.name||item.label||item.id} ${item.system||''}`.toLowerCase().includes(query));
    for(const item of entries.slice(0,150)) {
      const check=input('checkbox','',()=>{});check.checked=draft.peripheral.modules.includes(item.id);
      check.addEventListener('change',()=>{draft.peripheral.modules=draft.peripheral.modules.filter(x=>x!==item.id);if(check.checked)draft.peripheral.modules.push(item.id);draft.peripheral.enabled=true;organEnabled.checked=true;save();renderOrgans();});
      const row=field(item.name||item.label||item.id,check);row.title=`${item.status||item.support_status||'modeled'} · ${item.description||item.model||''}`;
      row.append(element('small',item.status||item.support_status||'explicit model'));organList.append(row);
      if(check.checked){
        const stimulus=input('number',draft.peripheral.external_inputs?.[item.id]??0,value=>{draft.peripheral.external_inputs||={};draft.peripheral.external_inputs[item.id]=value;save();},{min:'0',max:'1',step:'.05'});
        organList.append(field('External sensory drive · normalized 0–1',stimulus));
        const evidence=element('details');evidence.append(element('summary','Ports, dynamics & sources'),element('pre',JSON.stringify({id:item.id,ports:item.ports,source:item.source||item.sources,equations:item.equations,assumptions:item.assumptions,input_neurons:item.input_indices?.length,output_neurons:item.output_indices?.length},null,2)));organList.append(evidence);
      }
    }
    if(entries.length>150)organList.append(element('p',`${entries.length} matches · narrow your search`));
    if(!entries.length)organList.append(element('p',organCatalog.length?'No matching anatomy':'Loading anatomical catalogue…'));
  }

  const enzymes=element('section',undefined,'experiment-design-section');enzymes.append(element('h3','Enzyme reactions'));
  const enzymeEnabled=input('checkbox','',()=>{});enzymeEnabled.checked=draft.enzymes.enabled;
  const enzymeInputs={};
  enzymeEnabled.addEventListener('change',()=>{draft.enzymes.enabled=enzymeEnabled.checked;save();});scope.append(field('Simulate enzyme reactions',enzymeEnabled));
  for(const [key,label] of [['ChAT','ChAT · acetylcholine synthesis'],['AChE','AChE · acetylcholine degradation'],['Tbh','TβH · octopamine synthesis']]) {
    enzymeInputs[key]=input('number',draft.enzymes.activities[key]??1,value=>{draft.enzymes.activities[key]=value;save();},{min:'0',max:'10',step:'0.1'});enzymes.append(field(`${label} (relative activity)`,enzymeInputs[key]));
  }
  const enzymeDetails=element('details');enzymeDetails.append(element('summary','Compartments & kinetics'));
  enzymeDetails.append(field('Target compartments (comma separated; empty means all)',input('text',(draft.enzymes.compartments||[]).join(', '),value=>{draft.enzymes.compartments=split(value);save();})));
  for(const [name,initial] of Object.entries({choline:1,acetyl_coa:1,ach_vesicle:.5,tyramine:1,oa_vesicle:.5}))enzymeDetails.append(field(`${name.replaceAll('_',' ')} starting pool (a.u.)`,input('number',draft.enzymes.initial_pools?.[name]??initial,value=>{draft.enzymes.initial_pools||={};draft.enzymes.initial_pools[name]=value;save();},{min:'0',max:'100',step:'.1'})));
  for(const [name,vmax] of [['ChAT',.002],['AChE',.01],['Tbh',.002]])for(const [parameter,initial] of [['vmax_au_per_ms',vmax],['km_au',.5]])enzymeDetails.append(field(`${name} ${parameter.replaceAll('_',' ')}`,input('number',draft.enzymes.kinetics?.[name]?.[parameter]??initial,value=>{draft.enzymes.kinetics||={};draft.enzymes.kinetics[name]||={};draft.enzymes.kinetics[name][parameter]=value;save();},{min:'0.000000001',max:'100',step:'.001'})));
  enzymes.append(enzymeDetails);
  enzymes.append(element('p','Modeled kinetics · activity 0 = off, 1 = baseline. Synthesis pools are separate.'));
  content.append(enzymes);

  const timelineSection=element('section',undefined,'experiment-design-section timeline-section');timelineSection.append(element('h3','Input events'));
  const timeline=element('div',undefined,'experiment-timeline');timeline.setAttribute('aria-label','Drag events to change their start time');
  const rows=element('div',undefined,'timeline-block-list');
  const kindPicker=select(Object.entries(kindNames),'visual',()=>{});
  async function addTimelineEvent(kind,{start_ms=0,duration_ms=100}={}) {
    const block={id:crypto.randomUUID(),kind,start_ms,duration_ms:kind==='checkpoint'?0:duration_ms};
    if(kind==='visual')block.options={stimulus:'grating',contrast:1};
    let picked={kind:'indices',indices:[0]};
    if(['electrode','intervention'].includes(kind)&&getSelectedNeuron?.()!=null&&getSelectedTarget)picked=await getSelectedTarget(draft.model_id);
    if(kind==='electrode')block.electrode={target:picked,voltage_mv:10,frequency_hz:0};
    if(kind==='chemical'){block.species='DA';block.level=.5;}
    if(kind==='enzyme'){block.enzyme_id='AChE';block.activity=1;}
    if(kind==='intervention')block.intervention={kind:'silence',target:picked};
    if(kind==='checkpoint')block.label='Timeline checkpoint';
    const updated=checkedTimeline({...draft.timeline,blocks:[...draft.timeline.blocks,block]});
    draft.timeline=updated;delete draft.legacy_protocol;delete draft.legacy_protocol_text;save();renderTimeline();return updated.blocks.length-1;
  }
  timelineSection.append(field('Experiment name',input('text',draft.timeline.name,value=>{draft.timeline.name=value;save();})),kindPicker,button('Add event',()=>addTimelineEvent(kindPicker.value).catch(report)),button('Export experiment',()=>draft.legacy_protocol_text?downloadText('cognesia-protocol.yaml',draft.legacy_protocol_text):download('cognesia-protocol.json',draft.legacy_protocol||draft.timeline)),button('Import experiment',()=>protocolFile.click()),button('Use timeline inputs',()=>{delete draft.legacy_protocol;delete draft.legacy_protocol_text;save();renderTimeline();}));
  const repeats=input('number',draft.timeline.repeat?.count||draft.timeline.repeat||1,value=>{draft.timeline.repeat=value;save();},{min:'1',max:'100',step:'1'});
  timelineSection.append(field('Repetitions',repeats),timeline,rows);
  const protocolFile=input('file','',()=>{}, {accept:'.json,application/json'});protocolFile.hidden=true;
  protocolFile.accept='.json,.yaml,.yml,application/json,text/yaml';
  protocolFile.addEventListener('change',async()=>{try{
    const file=protocolFile.files[0];if(!file)return;if(file.size>256*1024)throw Error('Experiment file exceeds 256 KiB');
    const imported=await requestJSON('/api/protocols/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({document:await file.text(),model_id:draft.model_id})});
    if(imported.compatible&&imported.timeline){draft.timeline=imported.timeline;delete draft.legacy_protocol;delete draft.legacy_protocol_text;save();renderTimeline();}
    else if(imported.legacy_execution){draft.legacy_protocol=imported.original_document;draft.legacy_protocol_text=imported.original_text;draft.model_id='flywire-783';models.value=draft.model_id;save();renderTimeline();status.textContent='YAML loaded with its original engine, mappings and units. Full-state branching is unavailable. '+[...(imported.errors||[]),...(imported.warnings||[])].map(x=>typeof x==='string'?x:x.message||JSON.stringify(x)).join(' ');}
    else throw Error((imported.errors||[]).map(x=>x.message).join(' ')||'Experiment file is incompatible');
  }catch(error){report(error);}finally{protocolFile.value='';}});timelineSection.append(protocolFile);content.append(timelineSection);
  function targetEditor(target,onChange) {
    const box=element('div',undefined,'timeline-target');
    let kind=target?.kind||'indices';
    const chooser=select([['indices','Simulated neuron indices'],['root_ids','Exact neuron identifiers'],['entity_ids','Source-qualified identifiers'],['group','Cell type / group'],['region','Brain region'],['body_zone','Body afferents']],kind,value=>{kind=value;commit();});
    const text=input('text',target?.indices?.join(', ')??target?.root_ids?.join(', ')??target?.entity_ids?.join(', ')??target?.values?.join(', ')??target?.name??'',()=>commit());
    function commit(){onChange(kind==='indices'?{kind,indices:split(text.value).map(Number)}:['root_ids','entity_ids'].includes(kind)?{kind,[kind]:split(text.value)}:kind==='group'?{kind,field:'cell_type',values:split(text.value)}:{kind,name:text.value});save();}
    box.append(chooser,text,button('Use selected neuron',async()=>{try{if(!getSelectedTarget)throw Error('Select a neuron in the anatomy view first');const target=await getSelectedTarget(draft.model_id);kind=target.kind;chooser.value=kind;text.value=target[kind].join(', ');commit();}catch(error){report(error);}}));return box;
  }
  function renderTimeline() {
    timeline.replaceChildren();rows.replaceChildren();
    const max=Math.max(Number(getBaseOptions?.()?.duration_ms)||1000,...draft.timeline.blocks.map(b=>b.start_ms+b.duration_ms),1);
    timeline.append(element('span',`0 ms → ${max.toLocaleString()} ms`,'timeline-ruler'));
    draft.timeline.blocks.forEach((block,index)=>{
      const lane=element('div',undefined,'timeline-lane');lane.append(element('span',kindNames[block.kind]||block.kind,'timeline-lane-label'));
      const track=element('div',undefined,'timeline-track'),bar=element('button',block.label||kindNames[block.kind]||block.kind,'timeline-event');
      bar.type='button';bar.style.left=`${100*block.start_ms/max}%`;bar.style.width=`${Math.max(1,100*block.duration_ms/max)}%`;bar.title=`${block.start_ms}–${block.start_ms+block.duration_ms} ms`;
      const handle=element('span','↔','timeline-event-handle');handle.title='Drag to resize';bar.append(handle);track.append(bar);lane.append(track);timeline.append(lane);
      bar.addEventListener('pointerdown',event=>{
        if(event.button!==0)return;event.preventDefault();bar.setPointerCapture(event.pointerId);
        const origin=event.clientX,start=block.start_ms,duration=block.duration_ms,width=track.getBoundingClientRect().width,resizing=event.target===handle;
        const move=next=>{const delta=Math.round((next.clientX-origin)*max/Math.max(1,width));if(resizing)block.duration_ms=block.kind==='checkpoint'?0:Math.max(1,duration+delta);else block.start_ms=Math.max(0,start+delta);bar.style.left=`${100*block.start_ms/max}%`;bar.style.width=`${Math.max(1,100*block.duration_ms/max)}%`;};
        const finish=()=>{bar.removeEventListener('pointermove',move);bar.removeEventListener('pointerup',finish);bar.removeEventListener('pointercancel',finish);save();renderTimeline();};
        bar.addEventListener('pointermove',move);bar.addEventListener('pointerup',finish);bar.addEventListener('pointercancel',finish);
      });
      const row=element('div',undefined,'timeline-block');row.append(element('strong',`${index+1}. ${kindNames[block.kind]||block.kind}`),field('Start (ms)',input('number',block.start_ms,value=>{block.start_ms=value;save();renderTimeline();},{min:'0',step:'1'})),field('Duration (ms)',input('number',block.duration_ms,value=>{block.duration_ms=value;save();renderTimeline();},{min:'0',step:'1'})),button('Remove',()=>{draft.timeline.blocks.splice(index,1);save();renderTimeline();}));
      if(block.kind==='visual') {
        block.options ||= {stimulus:'grating'};
        row.append(field('Stimulus',select([['grating','Moving grating'],['flash','Flash'],['edge','Moving edge'],['looming','Looming disc'],['dark','Dark']],block.options.stimulus,value=>{block.options.stimulus=value;save();})),field('Contrast',input('number',block.options.contrast??1,value=>{block.options.contrast=value;save();},{min:'0',max:'1',step:'.05'})));
      }
      if(block.kind==='chemical')row.append(field('Chemical',select(['DA','OA','5HT','NO','sNPF','peptide_pool','TA','ACh'].map(x=>[x,x]),block.species,value=>{block.species=value;save();})),field('Held level (a.u.)',input('number',block.level,value=>{block.level=value;save();},{min:'0',max:'2',step:'.1'})));
      if(block.kind==='enzyme')row.append(field('Enzyme',select([['AChE','AChE'],['ChAT','ChAT'],['Tbh','TβH']],block.enzyme_id||block.enzyme,value=>{block.enzyme_id=value;delete block.enzyme;save();})),field('Relative activity',input('number',block.activity,value=>{block.activity=value;save();},{min:'0',step:'.1'})));
      if(block.kind==='checkpoint')row.append(field('Label',input('text',block.label||'',value=>{block.label=value;save();})));
      if(block.kind==='electrode')row.append(targetEditor(block.electrode?.target,value=>{block.electrode.target=value;}),field('Drive (mV)',input('number',block.electrode?.voltage_mv??10,value=>{block.electrode.voltage_mv=value;save();},{step:'.1'})));
      if(block.kind==='intervention') {
        const effect=block.intervention;
        row.append(field('Effect',select([['silence','Silence future output'],['edge_scale','Scale connection strength'],['receptor_block','Block receptor']],effect.kind,value=>{block.intervention=value==='silence'?{kind:value,target:effect.target||effect.pre||{kind:'indices',indices:[0]}}:value==='edge_scale'?{kind:value,pre:effect.target||{kind:'indices',indices:[0]},factor:0}: {kind:value,receptor_id:'',factor:0};save();renderTimeline();})));
        if(effect.kind==='silence')row.append(targetEditor(effect.target,value=>{effect.target=value;}));
        if(effect.kind==='edge_scale')row.append(field('Presynaptic selection',targetEditor(effect.pre,value=>{effect.pre=value;})),field('Postsynaptic selection (optional)',targetEditor(effect.post,value=>{effect.post=value;})),field('Strength multiplier',input('number',effect.factor??0,value=>{effect.factor=value;save();},{min:'0',step:'.1'})));
        if(effect.kind==='receptor_block')row.append(field('Receptor row identifier',input('text',effect.receptor_id||'',value=>{effect.receptor_id=value;save();})),field('Remaining receptor gain',input('number',effect.factor??0,value=>{effect.factor=value;save();},{min:'0',max:'1',step:'.1'})));
      }
      rows.append(row);
    });
    if(!draft.timeline.blocks.length)timeline.append(element('p','No events; standard inputs apply.'));
  }
  const branches=element('section',undefined,'experiment-design-section');branches.append(element('h3','Branches from saved states'));
  const checkpointPicker=select([['','New experiment']],draft.from_checkpoint||'',async value=>{
    draft.from_checkpoint=value||null;delete draft.branch_time_ms;branchTime.value='';
    if(value)try{
      const saved=await requestJSON(`/api/checkpoints/${encodeURIComponent(value)}/branches`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      draft.model_id=saved.options.model_id||'flywire-783';models.value=draft.model_id;
      draft.research_selection=clone(saved.options.research_selection||defaultExperimentDraft().research_selection);
      selectionMode.value=draft.research_selection.mode||'selected';boundary.value=draft.research_selection.boundary||'recorded';reference.hidden=boundary.value!=='recorded';regions.value=(draft.research_selection.regions||[]).join(', ');cellTypes.value=(draft.research_selection.cell_types||[]).join(', ');rootIds.value=(draft.research_selection.root_ids||[]).join(', ');reference.value=draft.research_selection.reference_id||'';
      draft.recording_selection=clone(saved.options.recording_selection||defaultExperimentDraft().recording_selection);draft.recording_selection.mode||='selected';recordScope.value=draft.recording_selection.mode;for(const [key,node] of Object.entries(recordFields))node.value=(draft.recording_selection[key]||[]).join(', ');
      draft.peripheral=clone(saved.options.modules||saved.options.peripheral||defaultExperimentDraft().peripheral);if(Array.isArray(draft.peripheral))draft.peripheral={enabled:true,modules:draft.peripheral};organEnabled.checked=!!draft.peripheral.enabled;
      const inheritedEnzymes=saved.options.neuromod?.enzymes;
      draft.enzymes=clone(inheritedEnzymes||defaultExperimentDraft().enzymes);enzymeEnabled.checked=!!draft.enzymes.enabled;for(const [key,node] of Object.entries(enzymeInputs))node.value=draft.enzymes.activities[key]??1;
      const advancedInputs=Array.from(enzymeDetails.querySelectorAll('input'));advancedInputs[0].value=(draft.enzymes.compartments||[]).join(', ');let cursor=1;
      for(const [name,initial] of Object.entries({choline:1,acetyl_coa:1,ach_vesicle:.5,tyramine:1,oa_vesicle:.5}))advancedInputs[cursor++].value=draft.enzymes.initial_pools?.[name]??initial;
      for(const [name,vmax] of [['ChAT',.002],['AChE',.01],['Tbh',.002]])for(const [parameter,initial] of [['vmax_au_per_ms',vmax],['km_au',.5]])advancedInputs[cursor++].value=draft.enzymes.kinetics?.[name]?.[parameter]??initial;
      parentDetails.textContent=JSON.stringify({input_origin_ms:saved.parent_input_origin_ms,protocol:saved.parent_protocol,interventions:saved.parent_interventions},null,2);
      onRestoreOptions?.(saved.options);onModelChanged?.(draft.model_id);loadCatalogs();
    }catch(error){report(error);}else parentDetails.textContent='No parent checkpoint selected.';save();
  });
  const branchTime=input('number',draft.branch_time_ms??'',value=>{if(branchTime.value==='')delete draft.branch_time_ms;else draft.branch_time_ms=value;save();},{min:'0',step:'1',placeholder:'Use the exact checkpoint time'});
  const branchNote=element('p','Inherits parent inputs and interventions. New events use time from branch start. Run starts the branch.');
  const inheritedView=element('details'),parentDetails=element('pre','Select a checkpoint to view its inputs.');inheritedView.append(element('summary','Inherited inputs'),parentDetails);
  branches.append(field('Start from',checkpointPicker),field('Reconstruct source time (ms, optional)',branchTime),button('Refresh checkpoints',loadCheckpoints),branchNote,inheritedView,button('Reset experiment',()=>{draft=defaultExperimentDraft();save();location.reload();}));content.append(branches);
  const branchQueue=[];let queueRunning=false;
  const queueList=element('ol',undefined,'branch-queue');
  const queueRun=button('Run queued branches',async()=>{
    if(queueRunning||job)return;queueRunning=true;queueRun.disabled=true;
    try{while(branchQueue.length){const item=branchQueue[0];status.textContent=`Running ${item.label}`;if(!await runDraft(item.options))break;branchQueue.shift();renderQueue();}}
    finally{queueRunning=false;renderQueue();}
  });
  function renderQueue(){queueList.replaceChildren(...branchQueue.map(item=>element('li',item.label)));queueRun.disabled=queueRunning||!!job||!branchQueue.length;}
  branches.append(button('Queue unchanged + intervention siblings',async()=>{
    try{if(!draft.from_checkpoint)throw Error('Choose a saved checkpoint first.');
      const inherited=await requestJSON(`/api/checkpoints/${encodeURIComponent(draft.from_checkpoint)}/branches`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      const changed=clone(getRunOptions());
      branchQueue.push({label:'Unchanged continuation',options:{from_checkpoint:draft.from_checkpoint,...(Number.isFinite(draft.branch_time_ms)?{branch_time_ms:draft.branch_time_ms}:{})}},{label:'Configured intervention branch',options:changed});renderQueue();
      status.textContent='Two branches queued from one checkpoint. Run queued branches executes them in order.';
    }catch(error){report(error);}
  }),queueRun,queueList,button('Clear branch queue',()=>{if(!queueRunning){branchQueue.length=0;renderQueue();}}));
  renderQueue();
  async function loadCheckpoints() {
    try{const data=await requestJSON('/api/checkpoints');checkpointPicker.replaceChildren(new Option('New experiment',''),...data.checkpoints.map(item=>new Option(`${item.label||item.id.slice(0,8)} · ${item.model_time_ms??0} ms · ${item.phase||''}`,item.id)));checkpointPicker.value=draft.from_checkpoint||'';}catch(error){report(error);}
  }
  async function modelAction(action) {
    try{
      const value=await requestJSON(`/api/models/${action}`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});status.textContent='Preparing model data…';
      while(true){await new Promise(resolve=>setTimeout(resolve,1500));const item=await requestJSON(`/api/models/jobs/${value.id}`);status.textContent=item.error||JSON.stringify(item.event||{status:item.status});if(item.status==='failed')throw Error(item.error);if(item.status==='complete')break;}
      await loadCatalogs();
    }catch(error){report(error);}
  }
  async function loadCatalogs() {
    const requestedModel=draft.model_id;
    const results=await Promise.allSettled([requestJSON('/api/models'),requestJSON(`/api/peripheral?model_id=${encodeURIComponent(draft.model_id)}`)]);
    if(requestedModel!==draft.model_id)return;
    if(results[0].status==='fulfilled') {
      modelCatalog=results[0].value;const list=Array.isArray(modelCatalog)?modelCatalog:modelCatalog.models||modelCatalog.providers||[];
      const ordered=[...list].sort((a,b)=>['paralimbo-v0-1-0','banc-888','cognesia-fused-v1','flywire-783'].indexOf(a.id)-['paralimbo-v0-1-0','banc-888','cognesia-fused-v1','flywire-783'].indexOf(b.id));
      models.replaceChildren(...ordered.map(item=>new Option(`${modelNames[item.id||item.model_id]||item.label||item.name||item.id}${item.available===false?' · not installed':''}`,item.id||item.model_id)));
      if(![...models.options].some(option=>option.value===draft.model_id))models.add(new Option(modelNames[draft.model_id]||draft.model_id,draft.model_id));models.value=draft.model_id;
      const selected=list.find(item=>(item.id||item.model_id)===draft.model_id);
      modelDescription.textContent=selected?`${selected.label||selected.name||draft.model_id}${selected.available===false?' · source data not installed':''}. Sources and assumptions are saved with every result.`:'Model availability has not been verified.';
      if(draft.research_selection.mode==='full'&&selected?.available!==false){neuronCount.textContent=Number.isFinite(selected?.neurons)?selected.neurons.toLocaleString():'—';connectionCount.textContent=Number.isFinite(selected?.edges)?selected.edges.toLocaleString():'—';}
    }else report(results[0].reason);
    if(results[1].status==='fulfilled'){const value=results[1].value;organCatalog=Array.isArray(value)?value:value.modules||value.organs||[];renderOrgans();}else report(results[1].reason);
  }
  function download(name,value){downloadText(name,JSON.stringify(value,null,2));}
  function downloadText(name,value){const url=URL.createObjectURL(new Blob([value],{type:'text/plain'}));const a=element('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function options(base) {
    const value=checkedDraft(draft),result={...base,model_id:value.model_id};
    if(value.legacy_protocol)return {model_id:'flywire-783',legacy_protocol:value.legacy_protocol_text||clone(value.legacy_protocol)};
    if(value.timeline.blocks.length)result.timeline=clone(value.timeline);
    if(value.interventions.length)result.interventions=clone(value.interventions);
    if(value.from_checkpoint){result.from_checkpoint=value.from_checkpoint;if(Number.isFinite(value.branch_time_ms))result.branch_time_ms=value.branch_time_ms;}
    if(value.research_selection.mode==='selected')result.research_selection=clone(value.research_selection);
    if(value.recording_selection.mode==='selected')result.recording_selection=clone(value.recording_selection);
    else if(value.from_checkpoint)result.recording_selection={mode:'full'};
    if(value.prepare_reference){result.prepare_reference=true;result.reference_selection=clone(value.research_selection);delete result.research_selection;}
    if(value.peripheral.enabled&&value.peripheral.modules.length)result.peripheral=clone(value.peripheral);
    const needsEnzymes=value.enzymes.enabled||value.timeline.blocks.some(block=>block.kind==='enzyme');
    const needsChemistry=needsEnzymes||value.timeline.blocks.some(block=>block.kind==='chemical'||block.intervention?.kind==='receptor_block');
    if(needsChemistry)result.neuromod={...result.neuromod,enabled:true};
    if(needsEnzymes)result.neuromod.enzymes={...clone(value.enzymes),enabled:true};
    if(value.model_id!=='flywire-783'&&result.neuromod)result.neuromod.plasticity_enabled=false;
    return result;
  }
  updateJob(null);renderTimeline();renderOrgans();const ready=Promise.all([loadCatalogs(),loadCheckpoints()]);
  return {ready,preview,elements:{model:modelSection,preSimulation:setup,organs,advanced:editor,execution,emergency:emergencyFooter},options,updateJob,stream,refresh:()=>{loadCheckpoints();loadCatalogs();},draft:()=>clone(draft),
    getTimeline:()=>clone(draft.timeline),
    setTimeline(value){draft.timeline=checkedTimeline(value);delete draft.legacy_protocol;delete draft.legacy_protocol_text;repeats.value=draft.timeline.repeat?.count||draft.timeline.repeat||1;save();renderTimeline();},
    addTimelineEvent,
    subscribeTimeline(listener){timelineSubscribers.add(listener);return()=>timelineSubscribers.delete(listener);},
    getTimelineContext:()=>({duration_ms:Number(getBaseOptions?.()?.duration_ms)||1000,from_checkpoint:draft.from_checkpoint,legacy:!!draft.legacy_protocol}),
    openTimelineEditor(index){editor.open=true;timelineSection.scrollIntoView({block:'nearest'});rows.children[index]?.scrollIntoView({block:'nearest'});},
    dispose(){socket?.close();if(frameTimer)cancelAnimationFrame(frameTimer);timelineSubscribers.clear();},
    setVisible(visible){host.hidden=!visible;}};
}
