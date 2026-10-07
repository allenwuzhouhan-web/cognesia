import test from 'node:test';
import assert from 'node:assert/strict';
import { CHEMICAL_SPECIES, validateChemistry, projectExposure, fieldValue, chemicalTrace, stateTrace } from '../src/flybrain/web/chemistry.js';
import { createSignalAdapter } from '../src/flybrain/web/analysis-data.js';
function fixture(){return {enabled:true,available:true,species:CHEMICAL_SPECIES,compartments:['g1','AL_L'],time_ms:[0,20],
  concentrations_au:Array.from({length:2},(_,f)=>CHEMICAL_SPECIES.map((_,s)=>[f+s,f+s+2])),
  baseline_concentrations_au:Array.from({length:2},()=>CHEMICAL_SPECIES.map(()=>[0,0])),
  neuron_membership:{indptr:[0,1,3,3],indices:[0,0,1],weights:[1,.25,.75]},
  state_names:['energy','hydration'],state_values:[[1,1],[.9,.8]],baseline_state_values:[[1,1],[1,1]],hormone_names:['AKH'],hormones_au:[[0],[.2]]};}
test('weighted chemical exposure uses actual full neuron membership; empty row is unknown',()=>{
  const c=validateChemistry(fixture(),3,[0,20]);
  assert.deepEqual([...projectExposure(c,1,0)],[1,2.5,-1]);
  assert.deepEqual([...projectExposure(c,1,0,true)],[0,0,-1]);
  assert.deepEqual([...chemicalTrace(c,0,1)],[2,3]);
  assert.equal(fieldValue(c,3,0,0),null);
});
test('state branch is explicit; missing baseline is a gap, never a stimulated substitution',()=>{
  const c=validateChemistry(fixture(),3,[0,20]);
  assert.ok(Math.abs(stateTrace(c,'energy')[1]-.9)<1e-6);
  assert.deepEqual([...stateTrace(c,'energy',true)],[1,1]);
  delete c.baseline_state_values;
  assert.ok([...stateTrace(c,'energy',true)].every(Number.isNaN));
});
test('malformed shape/order/weights and nonfinite chemical values fail closed',()=>{
  assert.throws(()=>validateChemistry(fixture(),4,[0,20]),/neuron order/);
  assert.throws(()=>validateChemistry(fixture(),3,[0,10]),/time samples/);
  let raw=fixture();raw.neuron_membership.weights[1]=.5;assert.throws(()=>validateChemistry(raw,3),/sum to one/);
  raw=fixture();raw.concentrations_au[0][0][0]=NaN;assert.throws(()=>validateChemistry(raw,3),/nonfinite/);
  raw=fixture();raw.neuron_membership.indices[0]=9;assert.throws(()=>validateChemistry(raw,3),/membership value/);
  raw=fixture();raw.baseline_concentrations_au.pop();assert.throws(()=>validateChemistry(raw,3),/shape/);
  assert.equal(validateChemistry({available:false},3),null);
});
test('original signal comparison can pin chemical and state data without changing voltage signals',async()=>{
  const chemistry=validateChemistry(fixture(),3),s={chemistry,summary:{id:'field-fixture',frames:{count:2,time_ms:[0,20]},activity:{shape:[2,3]}}};
  const adapter=createSignalAdapter({getState:()=>s,requestJSON:async()=>({})});
  const chemical=await adapter.resolveSignal('chemical:0:1:stimulated');
  assert.deepEqual([...chemical.values],[2,3]);assert.equal(chemical.unit,'a.u.');
  const baseline=await adapter.resolveSignal('state:energy:baseline');assert.deepEqual([...baseline.values],[1,1]);
  assert.equal(adapter.listSignals().filter(x=>x.kind==='chemical').length,32);
  chemistry.concentrations_au[1]=99;assert.equal(chemical.values[0],2);
  s.chemistry=null;await assert.rejects(adapter.resolveSignal('chemical:0:0:stimulated'),/not recorded/);
});
