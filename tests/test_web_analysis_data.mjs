import test from 'node:test';
import assert from 'node:assert/strict';
import {createSignalAdapter} from '../src/flybrain/web/analysis-data.js';

function fixture() {
  const state = {metadata:{analysis:{receptors:[
    {index:0,root_id:'720575940596125868',cell_type:'R1-6',side:'left',column_index:0},
    {index:2,root_id:'720575940597856265',cell_type:'R7',side:'right',column_index:null}]}},
    summary:{id:'run-a',label:'fixture',frames:{count:3,time_ms:[0,10,20]},activity:{shape:[3,3]},
      eyes:{columns:[{hemisphere:'left',column_id:1},{hemisphere:'right',column_id:1},{hemisphere:'left',column_id:2}],shape:[4,3],time_ms:[0,2,4,6]},
      traces:[{name:'R1-6',values:[1,2,3],raw:[-50,-49,-48],baseline:[-51,-51,-51]}]},
    activity:{raw:Float32Array.from([10,11,12,20,21,22,30,31,32]),delta:Float32Array.from([1,2,3,4,5,6,7,8,9])},
    eyeLuminance:Float32Array.from([0,1,.2,.2,.8,.4,.4,.6,.6,.6,.4,.8])};
  return {state,adapter:createSignalAdapter({getState:()=>state,requestJSON:async()=>({cell_type:'Other',side:'both',root_id:'123'})})};
}

test('each neuron is extracted from the correct stride; IDs retain integer precision',async()=>{
  const {adapter}=fixture();const signal=await adapter.resolveSignal('neuron:2:raw');
  assert.deepEqual([...signal.values],[12,22,32]);assert.deepEqual([...signal.timeMs],[0,10,20]);
  assert.match(signal.description,/720575940597856265/);assert.equal(signal.side,'right');
  assert.ok(adapter.listSignals().some(s=>s.label.includes('720575940596125868')));
});
test('left eye average uses only left columns and retains optical sampling times',async()=>{
  const {adapter}=fixture();const signal=await adapter.resolveSignal('eye:left:mean');
  assert.deepEqual([...signal.timeMs],[0,2,4,6]);
  [0.1,0.3,0.5,0.7].forEach((v,i)=>assert.ok(Math.abs(v-signal.values[i])<1e-6));
  assert.equal(signal.unit,'normalized luminance');
});
test('pinned values remain snapshots when source recording mutates',async()=>{
  const {adapter,state}=fixture();const signal=await adapter.resolveSignal('trace:type:0:delta');
  state.summary.traces[0].values[0]=99;state.summary.frames.time_ms[0]=7;
  assert.equal(signal.values[0],1);assert.equal(signal.timeMs[0],0);
});
test('out-of-range and missing saved signals fail instead of using live preview',async()=>{
  const {adapter,state}=fixture();await assert.rejects(adapter.resolveSignal('neuron:3:raw'),/outside/);
  state.eyeLuminance=null;await assert.rejects(adapter.resolveSignal('eye:left:mean'),/unavailable/);
});
