import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {brainDisplayPolicy,applyBrainDisplayUniforms,writeBrainActivity} from '../src/flybrain/web/brain-display.js';
import {projectRecordingFrame} from '../src/flybrain/web/anatomy-rendering.js';

const uniforms=()=>Object.fromEntries(['uActive','uAbsolute','uChemical','uSectionLive','uRange'].map(key=>[key,{value:91}]));
test('each transition resets all channel uniforms for cloud and neurites',()=>{
  for(const shader of [uniforms(),uniforms()])for(const mode of ['chemical','anatomy','absolute','delta','baseline','chemical','anatomy']){
    applyBrainDisplayUniforms(shader,brainDisplayPolicy(mode,{hasValues:true,hasChemistry:true}),2);
    assert.equal(shader.uActive.value,mode==='anatomy'?0:1);
    assert.equal(shader.uChemical.value,mode==='chemical'?1:0);
    assert.equal(shader.uAbsolute.value,['absolute','baseline'].includes(mode)?1:0);
    assert.equal(shader.uSectionLive.value,0);assert.equal(shader.uRange.value,2);
  }
});
test('live values cannot masquerade as a paired difference or mapped chemistry',()=>{
  for(const liveSignal of ['raw','baseline'])for(const mode of ['delta','absolute','baseline','anatomy','chemical']){
    const display=brainDisplayPolicy(mode,{live:true,liveSignal,hasValues:true,hasChemistry:true});
    assert.equal(display.available,mode==='anatomy'||mode==='absolute'||mode==='baseline'&&liveSignal==='baseline');
    assert.equal(display.chemical,mode==='chemical'?1:0);
  }
});
test('missing channels retain their chosen mode and clear stale activity',()=>{
  for(const mode of ['chemical','absolute','baseline','delta']){
    const display=brainDisplayPolicy(mode),buffer=new Float32Array([1,2]);
    assert.equal(display.active,1);assert.equal(display.available,false);assert.ok(display.unavailable);
    writeBrainActivity(buffer,null,display.available);assert.ok(buffer.every(v=>v < -1e20));
  }
  const values=new Float32Array([-60,NaN,Infinity,0]),target=new Float32Array(4);
  writeBrainActivity(target,values,true);
  assert.equal(target[0],-60);assert.equal(target[3],0);assert.ok(target[1] < -1e20 && target[2] < -1e20);
  assert.throws(()=>writeBrainActivity(target,new Float32Array(3),true),/anatomical rows/);
  assert.throws(()=>brainDisplayPolicy('invalid'),/Unknown/);
});

// Exercise the production event/update functions with a small renderer/DOM stand-in.
// No WebGL pixel claims: these regressions verify immediate draws and shader inputs.
const source=readFileSync(new URL('../src/flybrain/web/app.js',import.meta.url),'utf8');
function productionFunction(name){const start=source.indexOf(`function ${name}(`);assert.ok(start>=0);return source.slice(start,source.indexOf('\n}',start)+2);}
function harness(){
  const nodes=new Map(),buttons=['chemical','anatomy','absolute','baseline','delta'].map(mode=>({dataset:{mode},classList:{toggle(_,on){this.active=on;}},setAttribute(key,value){this[key]=value;}}));
  const $=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',value:'DA',style:{},replaceChildren(...children){this.children=children;}});return nodes.get(id);};
  const context={brainDisplayPolicy,applyBrainDisplayUniforms,writeBrainActivity,projectRecordingFrame,Float32Array,Number,Array,
    state:{mode:'chemical',summary:null,bootstrap:null,metadata:null,activity:{},frame:0,time:0,selectedNeuron:null},
    pointCount:3,geometry:{attributes:{aActivity:{array:new Float32Array(3),needsUpdate:false}}},material:{uniforms:uniforms()},
    morphologyLines:null,overviewLines:null,$,$$:()=>buttons,document:{createElement:()=>({style:{}})},
    chemicalFrame:()=>new Float32Array([1,2,-1]),chemicalRange:()=>2,plotColor:color=>color,
    drawTraces(){},drawChemicalReadout(){},updateInspectorValue(){},updateMorphologyColor(){},updateOverviewActivity(){},
    updateFlyFrame(values){context.flyValues=values;},drawBrainScene(){context.draws++;context.state.sceneDirty=false;},
    workspaceOverview:{showChemicalInspector(){context.inspectorOpens++;}},formatNumber:String,layoutWorkbench:{setTime(){}},
    sequenceTimeline:{setLiveFrame(frame){context.timelineFrame=frame;}},draws:0,inspectorOpens:0};
  vm.createContext(context);
  vm.runInContext(['currentValues','updateActivity','setMode','applyLiveFrame'].map(productionFunction).join('\n'),context);
  return Object.assign(context,{nodes,buttons});
}
test('saved paused recording switches chemical → anatomy → voltage immediately',()=>{
  const h=harness();h.state.summary={activity:{color_range_mv:5}};h.state.metadata={groups:[{color:'#ffffff'}]};h.state.chemistry={};
  h.state.recordedToAnatomy=new Uint32Array([2,0]);h.state.activity.raw=new Float32Array([-60,-40]);
  h.setMode('chemical');assert.equal(h.material.uniforms.uChemical.value,1);assert.equal(h.nodes.get('#scale-low').textContent,'0 a.u.');
  h.setMode('anatomy');assert.equal(h.material.uniforms.uActive.value,0);assert.equal(h.material.uniforms.uChemical.value,0);
  h.setMode('absolute');assert.equal(h.material.uniforms.uAbsolute.value,1);assert.equal(h.material.uniforms.uChemical.value,0);
  assert.equal(h.geometry.attributes.aActivity.array[0],-40);assert.ok(h.geometry.attributes.aActivity.array[1] < -1e20);assert.equal(h.geometry.attributes.aActivity.array[2],-60);
  h.setMode('chemical');h.setMode('anatomy');assert.equal(h.state.mode,'anatomy');
  assert.equal(h.buttons.find(b=>b.dataset.mode==='anatomy')['aria-pressed'],'true');
  assert.equal(h.buttons.find(b=>b.dataset.mode==='chemical')['aria-pressed'],'false');
  assert.equal(h.draws,5);assert.equal(h.inspectorOpens,2);
});

test('empty source preserves selected channel and anatomy tolerates absent bootstrap',()=>{
  const h=harness();
  for(const mode of ['chemical','delta','baseline','absolute']){
    h.setMode(mode);assert.equal(h.state.mode,mode);assert.equal(h.material.uniforms.uActive.value,1);
    assert.ok(h.geometry.attributes.aActivity.array.every(v=>v < -1e20));
    assert.match(h.nodes.get('#scale-low').textContent,/unavailable/);
  }
  h.setMode('anatomy');assert.equal(h.material.uniforms.uActive.value,0);assert.equal(h.nodes.get('#scale-low').textContent,'Cell class');
  assert.equal(h.draws,5);
});
test('new live frames and paused mode clicks use the same policy without resetting the selected mode',()=>{
  const h=harness();h.state.job='paused-or-running';
  h.setMode('anatomy');h.applyLiveFrame({indices:[0,2],voltage_mv:[-60,-40],signal:'raw',model_time_ms:20});
  assert.equal(h.timelineFrame.model_time_ms,20);
  assert.equal(h.state.mode,'anatomy');assert.equal(h.material.uniforms.uActive.value,0);
  h.setMode('chemical');assert.equal(h.material.uniforms.uChemical.value,1);assert.ok(h.geometry.attributes.aActivity.array.every(v=>v < -1e20));
  h.applyLiveFrame({indices:[0,2],voltage_mv:[-61,-41],signal:'raw',model_time_ms:21});
  assert.equal(h.material.uniforms.uChemical.value,1);assert.equal(h.material.uniforms.uAbsolute.value,0);
  h.setMode('absolute');assert.equal(h.geometry.attributes.aActivity.array[0],-61);assert.equal(h.material.uniforms.uChemical.value,0);
  h.setMode('baseline');assert.ok(h.geometry.attributes.aActivity.array.every(v=>v < -1e20));
  h.applyLiveFrame({indices:[0,2],voltage_mv:[-62,-42],signal:'baseline',model_time_ms:22});
  assert.equal(h.state.mode,'baseline');assert.equal(h.geometry.attributes.aActivity.array[0],-62);
  h.setMode('delta');assert.ok(h.geometry.attributes.aActivity.array.every(v=>v < -1e20));
  assert.equal(h.material.uniforms.uAbsolute.value,0);assert.equal(h.draws,8);
});
test('malformed display frame clears old values and still paints the chosen channel',()=>{
  const h=harness();h.state.chemistry={};h.chemicalFrame=()=>new Float32Array([100]);
  h.setMode('chemical');assert.equal(h.material.uniforms.uChemical.value,1);assert.ok(h.geometry.attributes.aActivity.array.every(v=>v < -1e20));
  assert.match(h.nodes.get('#color-scale').title,/anatomical rows/);assert.equal(h.draws,1);
  h.setMode('anatomy');assert.equal(h.material.uniforms.uChemical.value,0);assert.equal(h.material.uniforms.uActive.value,0);assert.equal(h.draws,2);
});
