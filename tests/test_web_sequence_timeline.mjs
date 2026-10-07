import test from 'node:test';
import assert from 'node:assert/strict';
import {checkedTimeline,expandTimeline,editTimelineEvent,nearestSampleIndex,recordedTimes,rulerTicks,timeAtPixel,curveCardGeometry,curveCardTime,curveCardId,signalSegments,recordedProtocol,regionResponseClips,clipReplayBounds,formatSignalValue} from '../src/flybrain/web/sequence-model.js';
import {initializeSequenceTimeline,defaultResponseSignals} from '../src/flybrain/web/sequence-timeline.js';
import {initializeExperimentControls} from '../src/flybrain/web/experiment-controls.js';

const timeline={schema_version:1,name:'Pulse experiment',repeat:{count:2,interval_ms:120},blocks:[{id:'pulse',kind:'visual',start_ms:10,duration_ms:25,options:{stimulus:'flash',contrast:.8}},{id:'save',kind:'checkpoint',start_ms:45,duration_ms:0}]};
test('repeated draft edits preserve native event parameters and update every repetition',()=>{
 const result=editTimelineEvent(timeline,0,{start_ms:18.4,duration_ms:35.6});
 assert.deepEqual(expandTimeline(result).map(b=>[b.id,b.start_ms,b.end_ms]),[['pulse',18,54],['save',45,45],['pulse',138,174],['save',165,165]]);
 assert.deepEqual(result.blocks[0].options,timeline.blocks[0].options);assert.equal(timeline.blocks[0].start_ms,10);
 assert.throws(()=>checkedTimeline({...timeline,repeat:{count:2,interval_ms:0}}),/positive/);
 assert.throws(()=>checkedTimeline({...timeline,repeat:101}),/Repeat count/);
 assert.throws(()=>editTimelineEvent(timeline,0,{start_ms:NaN}),/finite/);
});
test('seeking uses actual irregular sample times, with deterministic ties and no fabricated intermediate frame',()=>{
 const times=new Float64Array([0,20,41,85]);assert.equal(nearestSampleIndex(times,31),2);assert.equal(nearestSampleIndex(times,30.5),1);
 assert.equal(nearestSampleIndex(times,-100),0);assert.equal(nearestSampleIndex(times,999),3);assert.equal(nearestSampleIndex([],3),-1);
 assert.equal(recordedTimes({frames:{time_ms:times}}),times);
 assert.throws(()=>recordedTimes({frames:{time_ms:[0,20,20]}}),/invalid/);
 assert.equal(timeAtPixel(25,100,0,400),100);assert.equal(timeAtPixel(500,100,0,400),400);
 assert.deepEqual(rulerTicks(0,450,5),[0,100,200,300,400]);
});
test('curve decimation retains narrow extrema and breaks across missing recordings',()=>{
 const times=Float64Array.from({length:1000},(_,i)=>i),values=new Float64Array(1000);values[313]=7;values[314]=-9;
 const indices=signalSegments(times,values,0,999,10).flat();assert.ok(indices.includes(313));assert.ok(indices.includes(314));assert.ok(indices.length<30);
 assert.deepEqual(signalSegments([0,1,2,20,21,22],[0,1,NaN,2,3,4],0,22,100),[[0,1],[3,4,5]]);
 assert.deepEqual(signalSegments([0,1,2,20,21],[0,1,2,3,4],0,21,100),[[0,1,2],[3,4]]);
});
test('recorded protocol keeps simultaneous electrode identities and maps fork checkpoints to local recorded time',()=>{
 const summary={stimulus:{type:'flash',duration_ms:100},frames:{time_ms:[0,20,40,60,80]},metadata:{pre_equilibration_ms:100,input_origin_ms:500,session:{timeline:{...timeline,repeat:1}},session_events:[{phase:'stimulus',model_time_ms:650,checkpoint_id:'cp'},{phase:'baseline',model_time_ms:650,checkpoint_id:'baseline'}]},stimulation:{definitions:[{start_ms:510,end_ms:535,voltage_mv:1,target:{kind:'indices',indices:[1]}},{start_ms:510,end_ms:535,voltage_mv:1,target:{kind:'indices',indices:[2]}}]}};
 const events=recordedProtocol(summary);assert.equal(events.filter(e=>e.kind==='electrode').length,2);
 assert.equal(events.find(e=>e.checkpoint_id==='cp').start_ms,50);assert.ok(!events.some(e=>e.checkpoint_id==='baseline'));
 assert.equal(events[0].provenance,'saved input parameters');assert.equal(summary.metadata.session.timeline.blocks[0].start_ms,10);
});

// Small DOM fixture exercises controller behavior without assuming browser layout.
class Node {
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.attrs={};this.dataset={};this.style={setProperty:(k,v)=>{this.style[k]=v;}};this.className='';this.value='';this.textContent='';this.clientWidth=1000;this.scrollLeft=0;this.scrollTop=0;this.classList={add:(v)=>{this.className+=' '+v;},toggle:(v,on)=>{const names=new Set(this.className.split(' ').filter(Boolean));if(on)names.add(v);else names.delete(v);this.className=[...names].join(' ');}};}
 append(...nodes){for(const node of nodes){node.parent=this;this.children.push(node);}}
 add(node){this.append(node);if(this.children.length===1)this.value=node.value;}
 get options(){return this.children;}
 replaceChildren(...nodes){this.children=[];this.append(...nodes);}
 setAttribute(k,v){this.attrs[k]=String(v);}getAttribute(k){return this.attrs[k];}
 addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}removeEventListener(name,fn){this.listeners[name]=(this.listeners[name]||[]).filter(f=>f!==fn);}
 dispatch(name,fields={}){const e={target:this,currentTarget:this,button:0,pointerId:1,preventDefault(){},stopPropagation(){},type:name,...fields};for(const fn of [...this.listeners[name]||[]])fn(e);}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(node=>node!==this);}
 matches(selector){if(selector.startsWith('.'))return this.className.split(' ').includes(selector.slice(1));if(selector.startsWith('[')){const [,key,value]=selector.match(/\[([^=]+)="([^"]+)"\]/)||[];return this.attrs[key]===value;}return this.tagName===selector.toUpperCase();}
 closest(selector){return selector.split(',').some(s=>this.matches(s))?this:this.parent?.closest(selector)||null;}
 querySelectorAll(selector){return this.children.flatMap(node=>[...(node.matches(selector)?[node]:[]),...node.querySelectorAll(selector)]);}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 getBoundingClientRect(){return{left:0,width:826,height:84};}setPointerCapture(){}
 getContext(){return new Proxy({}, {get:()=>()=>{}});}
}
function dom(){
 const originals=Object.fromEntries(['document','window','Option','requestAnimationFrame','cancelAnimationFrame'].map(k=>[k,globalThis[k]])),frames=new Map();let clock=0;
 globalThis.document={createElement:tag=>new Node(tag)};globalThis.window={devicePixelRatio:1};globalThis.Option=class extends Node{constructor(text,value){super('option');this.textContent=text;this.value=value;}};
 globalThis.requestAnimationFrame=callback=>{frames.set(++clock,callback);return clock;};globalThis.cancelAnimationFrame=id=>frames.delete(id);
 return{host:new Node('div'),flush(){for(const [id,callback] of frames){frames.delete(id);callback();}},restore(){for(const [key,value] of Object.entries(originals)){if(value===undefined)delete globalThis[key];else globalThis[key]=value;}}};
}
function fixture({recording=true,resolveSignal,signals}={}){
 const env=dom(),subscribers=new Set();let doc=structuredClone(timeline),seek=[],saved=0;
 const state={summary:recording?{id:'run-a',label:'Saved flash',stimulus:{type:'flash',duration_ms:100},frames:{time_ms:[0,20,41,85]},metadata:{session:{timeline:{schema_version:1,blocks:[{kind:'rest',start_ms:0,duration_ms:20}]}}}}:null,time:0,playing:false};
 const controls={getTimeline:()=>structuredClone(doc),setTimeline(value){doc=checkedTimeline(value);saved++;for(const listener of subscribers)listener(doc);},subscribeTimeline(listener){subscribers.add(listener);return()=>subscribers.delete(listener);},getTimelineContext:()=>({duration_ms:100}),async addTimelineEvent(kind,{start_ms,duration_ms}){const index=doc.blocks.length;this.setTimeline({...doc,blocks:[...doc.blocks,{kind,start_ms,duration_ms}]});return index;}};
 const controller=initializeSequenceTimeline({host:env.host,experimentControls:controls,getTime:()=>state.time,getCurrentRunId:()=>state.summary?.id,getState:()=>state,listSignals:()=>state.summary?signals||[{id:'trace:type:0:raw',label:'T4 voltage',unit:'mV',runId:state.summary.id}]:[],resolveSignal:resolveSignal||((id)=>Promise.resolve({id,label:'T4 voltage',unit:'mV',timeMs:[0,20,41,85],values:[-52,-51,-50,-49],runId:state.summary.id})),onSeek:time=>{seek.push(time);state.time=time;},onPlay:playing=>{state.playing=playing;},onStatus:()=>{}});
 return{...env,state,controls,controller,seek,get doc(){return doc;},get saved(){return saved;}};
}
test('controller separates immutable recorded events from editable draft and scrubs to nearest real frame',async()=>{
 const f=fixture();try{
  await f.controller.refresh();await Promise.resolve();f.flush();
  const layers=f.host.querySelector('[aria-label="Sequence layers"]');layers.value='both';layers.dispatch('change');
  const ruler=f.host.querySelector('[role="slider"]');ruler.dispatch('pointerdown',{clientX:147});ruler.dispatch('pointerup');f.flush();
  // Entire sequence includes a repeated checkpoint at 165 ms: 147/826*165 ≈29.36 ->20.
  assert.equal(f.seek.at(-1),20);
  const recorded=f.host.querySelectorAll('.seq-event').find(node=>node.dataset.source==='recorded');recorded.dispatch('click');assert.equal(f.saved,0);
  const draftEvent=f.host.querySelectorAll('.seq-event').find(node=>node.dataset.source==='draft'&&String(node.dataset.index)==='0');
  draftEvent.dispatch('keydown',{key:'ArrowRight',shiftKey:true});assert.equal(f.doc.blocks[0].start_ms,20);assert.equal(f.saved,1);
  assert.equal(f.state.summary.metadata.session.timeline.blocks[0].start_ms,0);
  assert.ok(f.host.querySelectorAll('canvas').length===1);assert.ok(f.host.querySelector('.seq-recorded-group'));assert.ok(f.host.querySelector('.seq-draft-group'));
  f.controller.dispose();assert.equal(f.host.children.length,0);
 }finally{f.controller.dispose();f.restore();}
});
test('results use aligned stimulus, replay, and curve lanes on one zoomed time axis',async()=>{
 const f=fixture();try{
  await f.controller.refresh();await Promise.resolve();f.flush();
  assert.equal(f.host.querySelector('[aria-label="Sequence layers"]').value,'curves');
  const plane=f.host.querySelector('.seq-plane'),rows=plane.children.filter(node=>node.className.split(' ').includes('seq-row'));
  assert.ok(rows[0].className.includes('seq-ruler'));assert.ok(rows.some(row=>row.className.includes('seq-recorded')));assert.ok(rows.some(row=>row.className.includes('seq-clips')));
  const grid=f.host.querySelector('.seq-curve-grid');assert.equal(grid.parent,plane);assert.ok(plane.querySelector('canvas'));
  const card=grid.querySelector('.seq-curve-card');assert.equal(card.dataset.runId,'run-a');assert.equal(card.dataset.signalId,'trace:type:0:raw');assert.equal(card.id,curveCardId('run-a','trace:type:0:raw'));assert.notEqual(card.id,curveCardId('run-b','trace:type:0:raw'));
  assert.equal(grid.querySelector('canvas').style.height,'86px');assert.equal(f.host.querySelector('.seq-draft-group'),null);
  assert.equal(f.host.querySelector('.seq-tools').hidden,true);
  const zoom=f.host.querySelector('[aria-label="Timeline zoom"]');zoom.value='4';zoom.dispatch('input');
  const canvas=grid.querySelector('canvas'),body=card.querySelector('.seq-track-body');assert.equal(canvas.width,3312);
  const currentBody=grid.querySelector('.seq-track-body');currentBody.dispatch('pointerdown',{clientX:.41*826});currentBody.dispatch('pointerup');f.flush();assert.equal(f.seek.at(-1),41);
  assert.ok(Math.abs(parseFloat(f.host.querySelector('.seq-playhead').style.left)-(172+.41*3312))<1e-9);
 }finally{f.controller.dispose();f.restore();}
});
test('chart coordinate mapping excludes axis margins and remains valid at narrow widths',()=>{
 const wide=curveCardGeometry(430),narrow=curveCardGeometry(280);
 assert.equal(wide.plotHeight,150);assert.equal(narrow.plotHeight,150);
 for(const geometry of [wide,narrow]){assert.equal(curveCardTime(geometry.left,geometry,1000),0);assert.equal(curveCardTime(geometry.left+geometry.plotWidth/2,geometry,1000),500);assert.equal(curveCardTime(geometry.width+20,geometry,1000),1000);}
});
test('draft-only seeking never invents recorded brain frames and cancelled drags do not save',async()=>{
 const f=fixture({recording:false});try{
  await f.controller.refresh();const ruler=f.host.querySelector('[role="slider"]');ruler.dispatch('pointerdown',{clientX:100});ruler.dispatch('pointerup');assert.deepEqual(f.seek,[]);
  const event=f.host.querySelectorAll('.seq-event').find(node=>node.dataset.source==='draft');event.dispatch('pointerdown',{clientX:0});event.dispatch('pointermove',{clientX:100});event.dispatch('pointercancel');assert.equal(f.saved,0);assert.equal(f.doc.blocks[0].start_ms,10);
 }finally{f.controller.dispose();f.restore();}
});
test('signals resolving after a recording switch cannot contaminate current tracks',async()=>{
 let resolve;const pending=new Promise(done=>{resolve=done;});const f=fixture({resolveSignal:()=>pending});try{
  f.state.summary={...f.state.summary,id:'run-b',label:'New run'};const refresh=f.controller.refresh();
  resolve({id:'trace:type:0:raw',label:'Old run',unit:'mV',timeMs:[0,20],values:[1,2],runId:'run-a'});await refresh;await Promise.resolve();
  assert.equal(f.host.querySelectorAll('canvas').length,0);assert.match(f.host.querySelector('.seq-status').textContent,/different recording/);
 }finally{f.controller.dispose();f.restore();}
});
test('timeline API persists the executed draft and resolves neuron targets from the current anatomy selection',async()=>{
 const env=dom(),oldStorage=globalThis.localStorage,data=new Map(),nodes=new Map(['#run-button','#job-progress','#cancel-job'].map(id=>[id,new Node('button')]));
 globalThis.localStorage={getItem:key=>data.get(key),setItem:(key,value)=>data.set(key,value)};document.querySelector=selector=>nodes.get(selector)||null;
 let controls;try{
  controls=initializeExperimentControls({host:env.host,requestJSON:async url=>url==='/api/checkpoints'?{checkpoints:[]}:url==='/api/models'?{models:[{id:'flywire-783'}]}:{modules:[]},getBaseOptions:()=>({duration_ms:1000}),getSelectedNeuron:()=>12,getSelectedTarget:async()=>({kind:'root_ids',root_ids:['720575940123456789']}),onStatus:()=>{}});
  const messages=[],unsubscribe=controls.subscribeTimeline(doc=>{messages.push(doc);doc.blocks.length=0;});
  controls.setTimeline(timeline);assert.equal(controls.getTimeline().blocks.length,2);assert.equal(messages.length,1);
  assert.deepEqual(controls.options({duration_ms:1000}).timeline,timeline);
  assert.deepEqual(JSON.parse(data.get('cognesia.experiment.draft.v1')).timeline,timeline);
  const index=await controls.addTimelineEvent('electrode',{start_ms:60,duration_ms:30});assert.deepEqual(controls.getTimeline().blocks[index].electrode.target,{kind:'root_ids',root_ids:['720575940123456789']});
  unsubscribe();await controls.addTimelineEvent('enzyme',{start_ms:100,duration_ms:10});assert.equal(messages.length,2);
  assert.equal(controls.options({duration_ms:1000}).neuromod.enzymes.enabled,true);
  await new Promise(setImmediate);
 }finally{controls?.dispose();if(oldStorage===undefined)delete globalThis.localStorage;else globalThis.localStorage=oldStorage;env.restore();}
});
test('new recordings prefer Motor and visual population voltage over eye light, without replacing chosen curves',async()=>{
 const signals=[{id:'eye:left:mean',label:'Left eye light',unit:'normalized luminance'},{id:'eye:right:mean',label:'Right eye light',unit:'normalized luminance'},{id:'trace:region:0:raw',label:'Left antennal mechanosensory and motor center · voltage',unit:'mV',kind:'population'},{id:'trace:type:0:delta',label:'Motor · stimulus − baseline',unit:'mV',kind:'population'},{id:'trace:type:1:raw',label:'Other population voltage',unit:'mV',kind:'population'},{id:'trace:type:2:raw',label:'T4a voltage',unit:'mV',kind:'population'},{id:'trace:type:0:raw',label:'Motor · voltage',unit:'mV',kind:'population'}];
 assert.deepEqual(defaultResponseSignals(signals).map(s=>s.id),['trace:type:0:raw','trace:type:2:raw']);
 assert.deepEqual(defaultResponseSignals(signals.slice(0,2)).map(s=>s.id),['eye:left:mean','eye:right:mean']);
 const f=fixture({signals});try{
  await f.controller.refresh();await Promise.resolve();
  assert.deepEqual(f.host.querySelectorAll('.seq-curve-card').map(card=>card.dataset.signalId),['trace:type:0:raw','trace:type:2:raw']);
  f.host.querySelector('.seq-remove').dispatch('click');
  const picker=f.host.querySelector('[aria-label="Recorded signal to add"]');picker.value='eye:left:mean';
  f.host.querySelectorAll('button').find(button=>button.textContent==='+ Curve').dispatch('click');await Promise.resolve();await f.controller.refresh();
  assert.deepEqual(f.host.querySelectorAll('.seq-curve-card').map(card=>card.dataset.signalId),['trace:type:2:raw','eye:left:mean']);
 }finally{f.controller.dispose();f.restore();}
});


test('region response clips use saved paired differences and never invent crossings between samples',()=>{
 const summary={activity:{baseline_url:'/baseline'},frames:{time_ms:[0,10,20,30,100,110]},region_traces:[
  {name:'A_L',raw:[-52,-51,-49,-50,-50,-52],values:[0,.2,.4,0,.3,0]},
  {name:'B_R',raw:[-52,-40,-45,-50,-50,-52],values:[0,0,.05,0,0,0]}]};
 const areas=regionResponseClips(summary,{thresholdMv:.1});assert.equal(areas.length,1);assert.equal(areas[0].reference,'matched baseline');
 assert.deepEqual(areas[0].clips.map(c=>[c.start_ms,c.end_ms,c.sample_count,c.peak_mv]),[[10,20,2,.4],[100,100,1,.3]]);
 assert.equal(areas[0].signalId,'trace:region:0:delta');
 const unpaired=regionResponseClips({...summary,activity:{}},{thresholdMv:1});assert.equal(unpaired[0].reference,'first saved sample');assert.equal(unpaired[0].signalId,'trace:region:0:raw');
 assert.throws(()=>regionResponseClips(summary,{thresholdMv:0}),/positive/);
 assert.deepEqual(clipReplayBounds(summary.frames.time_ms,10,20,{context:true}),{start_ms:0,end_ms:30});
 assert.deepEqual(clipReplayBounds(summary.frames.time_ms,101,109),{start_ms:100,end_ms:110});assert.equal(clipReplayBounds([],0,1),null);
});
test('region clips break across missing values and sampling gaps',()=>{
 const areas=regionResponseClips({activity:{baseline_url:'/baseline'},frames:{time_ms:[0,1,2,3,40,41,42]},region_traces:[{name:'A',values:[0,.2,NaN,.3,.4,.5,0]}]});
 assert.deepEqual(areas[0].clips.map(c=>[c.start_ms,c.end_ms]),[[1,1],[3,3],[40,41]]);
});
test('double-click response replay stops at the saved bound and does not change experiment events',async()=>{
 const f=fixture();try{
  f.state.summary={...f.state.summary,activity:{baseline_url:'/baseline'},region_traces:[{name:'ME_L',values:[0,.2,0,0]}]};
  await f.controller.refresh();await Promise.resolve();f.flush();
  const response=f.host.querySelector('.seq-response-clip');assert.ok(response);response.dispatch('dblclick');
  assert.equal(f.seek.at(-1),0);assert.equal(f.state.playing,true);assert.match(response.title,/one sample context per side/);assert.match(response.getAttribute('aria-label'),/one sample context per side/);assert.match(f.host.querySelector('.seq-status').textContent,/one sample context per side/);
  f.state.time=85;f.controller.setTime(85);f.flush();assert.equal(f.state.playing,false);assert.equal(f.seek.at(-1),41);assert.equal(f.saved,0);
 }finally{f.controller.dispose();f.restore();}
});
test('marked clips persist per run and replay does not modify the next experiment',async()=>{
 const priorStorage=globalThis.localStorage,data=new Map();globalThis.localStorage={getItem:key=>data.get(key),setItem:(key,value)=>data.set(key,value)};
 const f=fixture();try{
  await f.controller.refresh();await Promise.resolve();f.flush();
  f.controller.setTime(20);f.flush();f.host.querySelectorAll('button').find(b=>b.textContent==='In').dispatch('click');
  f.controller.setTime(41);f.flush();f.host.querySelectorAll('button').find(b=>b.textContent==='Out').dispatch('click');
  f.host.querySelectorAll('button').find(b=>b.textContent==='+ Clip').dispatch('click');
  const clips=JSON.parse(data.get('cognesia.timeline.clips.v1:run-a'));assert.deepEqual(clips.map(c=>[c.start_ms,c.end_ms]),[[20,41]]);
  const saved=f.host.querySelectorAll('.seq-replay-clip').find(b=>b.textContent==='Clip 1');saved.dispatch('dblclick');assert.equal(f.seek.at(-1),20);assert.equal(f.state.playing,true);assert.equal(f.saved,0);
  f.state.summary={...f.state.summary,id:'run-b'};await f.controller.refresh();assert.equal(f.host.querySelectorAll('.seq-replay-clip').some(b=>b.textContent==='Clip 1'),false);
 }finally{f.controller.dispose();f.restore();if(priorStorage===undefined)delete globalThis.localStorage;else globalThis.localStorage=priorStorage;}
});

test('models without region aggregates use explicitly identified saved cell-type means',()=>{
 const areas=regionResponseClips({frames:{time_ms:[0,20,40]},activity:{baseline_url:'/baseline'},region_traces:[],traces:[{name:'R7/R8',values:[0,.1,.2]}]});
 assert.equal(areas[0].kind,'type');assert.equal(areas[0].name,'R7/R8');assert.equal(areas[0].signalId,'trace:type:0:delta');
 assert.deepEqual(regionResponseClips({frames:{time_ms:[0,20]},region_traces:[],traces:[]}),[]);
});
test('live frames hide prior results and disable replay until saved results are loaded',async()=>{
 const f=fixture();try{
  await f.controller.refresh();await Promise.resolve();f.flush();assert.ok(f.host.querySelector('canvas'));
  f.controller.setLiveFrame({phase:'stimulus',model_time_ms:25});f.flush();
  assert.equal(f.host.querySelector('canvas'),null);assert.equal(f.host.querySelector('.seq-replay-clip'),null);assert.ok(f.host.querySelector('.seq-live'));
  assert.equal(f.host.querySelector('[aria-label="Play recorded activity"]').disabled,true);assert.equal(f.host.querySelector('.seq-time').textContent,'25 ms');
  f.controller.setTime(60);f.flush();assert.equal(f.host.querySelector('.seq-time').textContent,'25 ms');
  f.controller.setLiveFrame(null);await Promise.resolve();f.flush();assert.ok(f.host.querySelector('canvas'));assert.equal(f.host.querySelector('[aria-label="Play recorded activity"]').disabled,false);
 }finally{f.controller.dispose();f.restore();}
});

test('partial result metadata does not invent a visual stimulus event',()=>{assert.deepEqual(recordedProtocol({stimulus:{type:'partial',duration_ms:40},frames:{time_ms:[0,20,40]}}),[]);});


test('preparation and queued refreshes keep previous recordings out of the active timeline',async()=>{
 const f=fixture();try{
  await f.controller.refresh();await Promise.resolve();f.flush();assert.ok(f.host.querySelector('canvas'));
  f.state.submitting=true;f.controller.setLiveFrame({phase:'preparing',model_time_ms:0});
  await f.controller.refresh();f.flush();assert.ok(f.host.querySelector('.seq-live'));assert.equal(f.host.querySelector('canvas'),null);assert.equal(f.host.querySelector('.seq-record-label').textContent,'Running');
  f.state.job='queued-job';f.state.submitting=false;await f.controller.refresh();f.flush();
  assert.ok(f.host.querySelector('.seq-live'));assert.equal(f.host.querySelector('[aria-label="Play recorded activity"]').disabled,true);
  f.state.job=null;f.controller.setLiveFrame(null);await Promise.resolve();f.flush();assert.ok(f.host.querySelector('canvas'));assert.equal(f.host.querySelector('.seq-live'),null);
 }finally{f.controller.dispose();f.restore();}
});
test('timeline result label uses the saved model identity, including metadata fallback',async()=>{
 const f=fixture();try{
  for(const [summary,name] of [[{model_id:'banc-888'},'BANC'],[{model_id:'cognesia-fused-v1'},'Cognesia'],[{model_id:'flywire-783'},'FlyWire'],[{metadata:{model_id:'flywire-783'}},'FlyWire']]){
   const next={...f.state.summary,...summary};if(!summary.model_id)delete next.model_id;f.state.summary=next;
   await f.controller.refresh();assert.ok(f.host.querySelector('.seq-record-label').textContent.startsWith(name+' · '));
  }
 }finally{f.controller.dispose();f.restore();}
});

test('reopening the same result after model preview restores default curves',async()=>{
 const f=fixture();try{
  await f.controller.refresh();await Promise.resolve();f.flush();const result=f.state.summary;assert.equal(f.host.querySelectorAll('canvas').length,1);
  f.state.summary=null;await f.controller.refresh();assert.equal(f.host.querySelectorAll('canvas').length,0);
  f.state.summary=result;await f.controller.refresh();await Promise.resolve();f.flush();assert.equal(f.host.querySelectorAll('canvas').length,1);
 }finally{f.controller.dispose();f.restore();}
});


test('narrow voltage spans retain distinct axis labels and cursor variation',async()=>{
 const ticks=rulerTicks(-52.0008,-52,3),labels=ticks.map(value=>formatSignalValue(value,.0008));
 assert.equal(new Set(labels).size,ticks.length);assert.ok(labels.length>=2);assert.notEqual(formatSignalValue(-52.00000001,.00000001),formatSignalValue(-52,.00000001));
 assert.equal(formatSignalValue(NaN,.01),'—');
 const f=fixture({resolveSignal:id=>Promise.resolve({id,label:'T4a voltage',unit:'mV',runId:'run-a',timeMs:[0,20,41,85],values:[-52,-52.0004,-52.0008,-52.0002]})});try{
  await f.controller.refresh();await Promise.resolve();f.flush();const initial=f.host.querySelector('.seq-curve-value').textContent;
  f.controller.setTime(41);f.flush();assert.notEqual(f.host.querySelector('.seq-curve-value').textContent,initial);assert.match(f.host.querySelector('.seq-curve-value').textContent,/-52\.0008/);
  const scale=f.host.querySelector('.seq-curve-card').title.match(/scale (.+)–(.+) mV/);assert.ok(scale);assert.notEqual(scale[1],scale[2]);
 }finally{f.controller.dispose();f.restore();}
});
