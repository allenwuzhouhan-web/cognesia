import test from 'node:test';
import assert from 'node:assert/strict';
import {defaultExperimentDraft,initialExperimentDraft,simulationProgress,initializeExperimentControls} from '../src/flybrain/web/experiment-controls.js';

test('BANC becomes the ordinary default once without changing checkpoint or imported source identity',()=>{
  assert.equal(defaultExperimentDraft().model_id,'banc-888');
  const old={...defaultExperimentDraft(),model_id:'flywire-783',model_picker_version:undefined};
  assert.equal(initialExperimentDraft(old).model_id,'banc-888');
  assert.equal(old.model_id,'flywire-783');
  assert.equal(initialExperimentDraft({...old,from_checkpoint:'saved-state'}).model_id,'flywire-783');
  assert.equal(initialExperimentDraft({...old,legacy_protocol:{phases:[]}}).model_id,'flywire-783');
  assert.equal(initialExperimentDraft({...old,model_picker_version:2}).model_id,'flywire-783');
});
test('progress preserves actual zero, unknown progress, model time, and terminal status',()=>{
  assert.equal(simulationProgress({status:'queued',progress:0}).fraction,0);
  assert.equal(simulationProgress({status:'running',phase:'stimulus',model_time_ms:31.25}).fraction,null);
  assert.deepEqual(simulationProgress({status:'paused',phase:'stimulus',progress:.42,model_time_ms:31.25}),{fraction:.42,label:'Experiment',modelTime:31.25,active:true});
  assert.equal(simulationProgress({status:'failed',phase:'stimulus',progress:.42}).label,'Failed');
  assert.equal(simulationProgress({status:'complete',phase:'saving',progress:.99}).fraction,1);
  assert.equal(simulationProgress({status:'cancelled',phase:'paired_baseline',progress:.72}).label,'Stopped');
});

class Node {
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.attrs={};this.style={};this.className='';this.value='';this.textContent='';this.classList={add:value=>{this.className+=' '+value;}};}
  append(...nodes){for(const node of nodes.filter(Boolean)){node.remove?.();node.parent=this;this.children.push(node);}}
  add(node){this.append(node);}
  get options(){return this.children;}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(node=>node!==this);this.parent=null;}
  setAttribute(key,value){this.attrs[key]=String(value);}getAttribute(key){return this.attrs[key];}
  addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
  async dispatch(name){for(const fn of this.listeners[name]||[])await fn({target:this});}
  matches(selector){return selector[0]==='.'?this.className.split(' ').includes(selector.slice(1)):selector[0]==='#'?this.id===selector.slice(1):this.tagName===selector.toUpperCase();}
  querySelectorAll(selector){return this.children.flatMap(node=>[...(node.matches(selector)?[node]:[]),...node.querySelectorAll(selector)]);}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
}
function fixture({saved,preview}={}){
  const originals=Object.fromEntries(['document','Option','localStorage'].map(key=>[key,globalThis[key]]));
  const host=new Node('div'),nodes=new Map();
  for(const id of ['run-button','job-progress','cancel-job','stop-all','compute-duration','compute-snapshot','compute-timestep','compute-threads']){const node=new Node(id==='job-progress'?'div':'button');node.id=id;nodes.set('#'+id,node);}
  const track=new Node('div'),fill=new Node('span'),message=new Node('p');track.append(fill);nodes.get('#job-progress').append(track,message);
  const stored=new Map(saved?[['cognesia.experiment.draft.v1',JSON.stringify(saved)]]:[]),requests=[];
  globalThis.document={createElement:tag=>new Node(tag),querySelector:selector=>nodes.get(selector)||host.querySelector(selector)};
  globalThis.Option=class extends Node{constructor(text,value){super('option');this.textContent=text;this.value=value;}};
  globalThis.localStorage={getItem:key=>stored.get(key),setItem:(key,value)=>stored.set(key,value)};
  let controls;
  controls=initializeExperimentControls({host,requestJSON:async(url,options)=>{requests.push({url,options});if(url==='/api/models')return[{id:'banc-888',label:'BANC 888',available:true,neurons:15,edges:40},{id:'flywire-783',label:'FlyWire 783',available:true}];if(url==='/api/checkpoints')return{checkpoints:[]};if(url==='/api/selection/preview')return preview?preview():{selection:{simulated_neurons:7,incoming_cut_edges:2},simulated_connections:11,sequence:['Run simulation'],targets:[],memory_estimate:{total_working_bytes:1000000000,note:'Estimate'}};if(url.includes('/commands'))return{accepted:true};return{modules:[]};},getBaseOptions:()=>({duration_ms:100}),getRunOptions:()=>controls.options({duration_ms:100})});
  return{controls,host,nodes,track,fill,stored,requests,restore(){controls.dispose();for(const[key,value]of Object.entries(originals)){if(value===undefined)delete globalThis[key];else globalThis[key]=value;}}};
}
function check(host,label){return host.querySelectorAll('label').find(node=>node.children[0]?.textContent===label)?.querySelector('input');}
test('checkbox scope uses backend selections and execution controls remain bound after relocation',async()=>{
  const f=fixture();try{
    await f.controls.ready;
    assert.equal(f.controls.draft().model_id,'banc-888');
    assert.equal(f.controls.elements.preSimulation.querySelector('#compute-timestep'),f.nodes.get('#compute-timestep'));
    const full=check(f.controls.elements.preSimulation,'Simulate the entire model');full.checked=false;await full.dispatch('change');
    const selected=f.host.querySelector('.simulation-selected-tissue');assert.equal(selected.hidden,false);
    const cells=selected.querySelectorAll('input')[1];cells.value='T4a, T5a';await cells.dispatch('change');
    const record=check(f.controls.elements.preSimulation,'Save voltage for all simulated neurons');record.checked=false;await record.dispatch('change');
    const saveCells=f.host.querySelector('.simulation-selected-recording').querySelectorAll('input')[1];saveCells.value='T4a';await saveCells.dispatch('change');
    const options=f.controls.options({duration_ms:100});assert.deepEqual(options.research_selection.cell_types,['T4a','T5a']);assert.deepEqual(options.recording_selection.cell_types,['T4a']);
    await f.controls.preview();assert.deepEqual(f.host.querySelector('.simulation-size-grid').querySelectorAll('output').map(node=>node.textContent),['7','11','1.00 GB']);
    const request=JSON.parse(f.requests.find(item=>item.url==='/api/selection/preview').options.body);assert.equal(request.model_id,'banc-888');assert.equal(request.selection.mode,'selected');
    const destination=new Node('footer');destination.append(f.controls.elements.execution,f.controls.elements.emergency);
    f.controls.updateJob({id:'run one',status:'running',phase:'stimulus',progress:0,model_time_ms:0});assert.equal(f.fill.style.width,'0%');assert.equal(f.track.getAttribute('aria-valuenow'),'0');
    await destination.querySelectorAll('button').find(node=>node.textContent==='Pause').dispatch('click');
    const command=f.requests.find(item=>item.url.includes('/commands'));assert.equal(command.url,'/api/sessions/run%20one/commands');assert.equal(JSON.parse(command.options.body).action,'pause');
    assert.equal(destination.querySelector('#stop-all').textContent,'■ Emergency stop ALL');
  }finally{f.restore();}
});
test('changing configuration while an estimate is loading cannot display stale counts',async()=>{
  let resolve;const f=fixture({preview:()=>new Promise(done=>{resolve=done;})});try{
    await f.controls.ready;const pending=f.controls.preview();
    const full=check(f.controls.elements.preSimulation,'Simulate the entire model');full.checked=false;await full.dispatch('change');
    resolve({selection:{simulated_neurons:15,incoming_cut_edges:0},simulated_connections:40,sequence:[],targets:[],memory_estimate:{total_working_bytes:10,note:''}});
    assert.equal(await pending,null);assert.deepEqual(f.host.querySelector('.simulation-size-grid').querySelectorAll('output').map(node=>node.textContent),['—','—','—']);
  }finally{f.restore();}
});

test('a saved ParaLimbo selection survives refresh and uses provider chemistry options',async()=>{
  const saved={...defaultExperimentDraft(),model_id:'paralimbo-v0-1-0'};
  const f=fixture({saved});try{
    await f.controls.ready;
    assert.equal(f.controls.draft().model_id,'paralimbo-v0-1-0');
    const picker=f.controls.elements.model.querySelector('select');
    assert.equal(picker.value,'paralimbo-v0-1-0');
    assert.equal(picker.options.find(option=>option.value==='paralimbo-v0-1-0').textContent,'ParaLimbo 0.1 · BANC × FlyWire');
    const options=f.controls.options({duration_ms:300,neuromod:{enabled:true}});
    assert.equal(options.model_id,'paralimbo-v0-1-0');
    assert.equal(options.neuromod.plasticity_enabled,false);
    assert.equal(initialExperimentDraft({...saved,from_checkpoint:'paralimbo-state'}).model_id,'paralimbo-v0-1-0');
  }finally{f.restore();}
});
