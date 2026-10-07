import test from 'node:test';
import assert from 'node:assert/strict';
import {interpretChemicalContext,SCENARIO_SOURCES} from '../src/flybrain/web/scenario-context.js';

test('global dopamine and octopamine never identify hunger or sexual arousal',()=>{
  const result=interpretChemicalContext({DA:2,OA:2});
  assert.equal(result.stateContext.length,0);
  assert.match(result.summary,/No internal state is inferred/);
  assert.ok(!result.possibleAssociations.some(x=>x.id==='food-seeking-combination'));
  const courtship=result.possibleAssociations.find(x=>x.id==='sexual-arousal-unresolved');
  assert.match(courtship.text,/female FlyWire/);
  assert.ok(courtship.sourceURLs.includes(SCENARIO_SOURCES.courtship));
  assert.ok(result.limits.some(x=>x.includes('no measured natural baseline')));
});
test('explicit low energy enables only a qualified food-seeking experiment context',()=>{
  const result=interpretChemicalContext({DA:1,sNPF:1},{scenario:'starved'});
  assert.equal(result.stateContext.find(x=>x.id==='energy').label,'Starvation-like model input');
  assert.match(result.stateContext[0].text,/not from the chemical combination/);
  assert.match(result.possibleAssociations[0].text,/do not predict approach/);
  const fed=interpretChemicalContext({DA:1,sNPF:1},{scenario:'starved',initial_state:{energy:1}});
  assert.equal(fed.stateContext.find(x=>x.id==='energy').label,'Fed-energy model input');
  assert.ok(!fed.possibleAssociations.some(x=>x.id==='food-seeking-combination'));
});
test('intermediate state inputs do not invent fasting duration or a sexual state',()=>{
  const result=interpretChemicalContext({}, {energy:.41,hydration:.5,arousal:1,stress:.5,circadian_phase:.3});
  assert.match(result.stateContext.find(x=>x.id==='energy').text,/does not specify how long/);
  assert.match(result.stateContext.find(x=>x.id==='arousal').text,/not a sexual-arousal/);
  assert.match(result.stateContext.find(x=>x.id==='circadian_phase').text,/without calibration/);
});
test('arbitrary-unit magnitudes produce no fabricated natural threshold or confidence',()=>{
  const low=interpretChemicalContext({DA:.0001,OA:.2}),high=interpretChemicalContext({DA:2,OA:1.8});
  assert.deepEqual(low.possibleAssociations,high.possibleAssociations);
  assert.deepEqual(low.stateContext,high.stateContext);
  assert.ok(!('confidence' in high) && !('probability' in high));
  const zero=interpretChemicalContext({DA:0});
  assert.match(zero.summary,/zero in model units/);
  assert.ok(!zero.possibleAssociations.some(x=>x.id==='dopamine'));
});
test('invalid values remain unknown rather than being clamped or coerced into states',()=>{
  const result=interpretChemicalContext({DA:NaN,OA:-1,'5HT':true,NO:Infinity,sNPF:2.001,TA:'2',fake:1},
    {energy:NaN,hydration:-1,arousal:true,stress:2,circadian_phase:1,scenario:'sexual'});
  assert.equal(result.concentrations.length,0);
  assert.equal(result.stateContext.length,0);
  assert.ok(result.inputIssues.length>=12);
  assert.doesNotThrow(()=>JSON.stringify(result));
  assert.ok(interpretChemicalContext(null,null).inputIssues.length===2);
});
test('all eight controls get honest context and source links stay bounded and unique',()=>{
  const result=interpretChemicalContext({DA:1,OA:1,'5HT':1,NO:1,sNPF:1,peptide_pool:1,TA:1,ACh:1});
  assert.equal(result.concentrations.length,8);
  assert.equal(result.possibleAssociations.length,9);
  assert.match(result.possibleAssociations.find(x=>x.id==='peptide-pool').text,/no single natural chemical identity/);
  assert.match(result.possibleAssociations.find(x=>x.id==='serotonin').text,/did not have the same effect/);
  assert.ok(result.sourceURLs.every(x=>x.startsWith('https://')));
  assert.equal(new Set(result.sourceURLs).size,result.sourceURLs.length);
  assert.ok(JSON.stringify(result).length<11000);
});
test('interpretation is deterministic and cannot mutate controls or shared references',()=>{
  const levels=Object.freeze({OA:1,TA:0}),state=Object.freeze({scenario:'dehydrated'});
  const a=interpretChemicalContext(levels,state),b=interpretChemicalContext(levels,state);
  assert.deepEqual(a,b);
  a.possibleAssociations[0].sourceURLs.push('changed');
  assert.deepEqual(b,interpretChemicalContext(levels,state));
});
