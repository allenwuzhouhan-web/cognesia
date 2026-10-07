import test from 'node:test';
import assert from 'node:assert/strict';
import {collectChemicalLevels,presetState} from '../src/flybrain/web/chemical-controls.js';
test('manual zero is an intervention while unchecked concentrations stay endogenous',()=>{
  assert.deepEqual(collectChemicalLevels([{species:'DA',enabled:true,value:0},{species:'OA',enabled:false,value:1.5},{species:'ACh',enabled:true,value:.0037}]),{DA:0,ACh:.0037});
});
test('sliders cannot submit invalid concentrations or unknown species',()=>{
  for(const value of [NaN,Infinity,-.01,2.01,true,'1'])assert.throws(()=>collectChemicalLevels([{species:'DA',enabled:true,value}]));
  assert.throws(()=>collectChemicalLevels([{species:'unknown',enabled:true,value:1}]));
});
test('state presets remain independent inputs instead of invented chemical recipes',()=>{
  const starved=presetState('starved');assert.equal(starved.energy,0);assert.equal(starved.arousal,0);assert.equal(starved.DA,undefined);
  starved.hydration=0;assert.equal(presetState('starved').hydration,1);
  assert.equal(presetState('stressed').stress,1);assert.equal(presetState('dehydrated').hydration,0);
});
