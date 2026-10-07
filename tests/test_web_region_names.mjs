import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import {regionLabel,speciesLabel,COMPARTMENT_KEYS,REGION_NAMES,SPECIES_NAMES} from '../src/flybrain/web/brain-region-names.js';

test('all 96 released compartment identifiers have distinct readable labels',()=>{
  assert.equal(COMPARTMENT_KEYS.length,96);
  assert.equal(new Set(COMPARTMENT_KEYS).size,96);
  for (const key of COMPARTMENT_KEYS) assert.ok(Object.hasOwn(REGION_NAMES,key),key);
  assert.equal(new Set(COMPARTMENT_KEYS.map(key=>regionLabel(key))).size,96);
  assert.equal(COMPARTMENT_KEYS.filter(key=>key.startsWith('AL_')).length,59);
});
test('all released neuropil labels expand, including unassigned evidence',()=>{
  const names=['AL','AME','AMMC','AOTU','ATL','AVLP','BU','CAN','CRE','EPA','FLA','GA','GOR',
    'IB','ICL','IPS','LAL','LA','LH','LOP','LO','MB_CA','MB_ML','MB_PED','MB_VL','ME','PLP',
    'PVLP','SCL','SIP','SLP','SMP','SPS','VES','WED'].flatMap(x=>[`${x}_L`,`${x}_R`]);
  names.push('EB','FB','GNG','NO','None','OCG','PB','PRW','SAD');
  for (const key of names) assert.ok(Object.hasOwn(REGION_NAMES,key),key);
  const metadata=new URL('../build/visual_neuropil_weights.json',import.meta.url);
  if (existsSync(metadata)) for (const key of JSON.parse(readFileSync(metadata,'utf8')).neuropils) assert.ok(Object.hasOwn(REGION_NAMES,key),key);
});
test('anatomical and chemical namespaces remain distinct',()=>{
  assert.equal(regionLabel('NO'),'Noduli');
  assert.equal(speciesLabel('NO'),'Nitric oxide');
  assert.equal(regionLabel('LOP_R'),'Right lobula plate');
  assert.equal(regionLabel('MB-CA(L)'),'Left mushroom body calyx');
  assert.equal(regionLabel('g1'),'Mushroom body gamma 1 (model cluster)');
  assert.match(regionLabel('bp2'),/beta prime 2/);
  assert.match(regionLabel('ap3'),/alpha prime 3/);
  assert.match(regionLabel('AL_VM6'),/both sides/);
  assert.match(regionLabel('hemolymph'),/symbolic/);
  assert.match(regionLabel('CX_FB_unresolved'),/unresolved/);
});
test('optional identifiers support traceability and unknowns are never guessed',()=>{
  assert.equal(regionLabel('ME_L',{alias:true}),'Left medulla [ME_L]');
  assert.equal(speciesLabel('sNPF',{alias:true}),'Short neuropeptide F [sNPF]');
  assert.equal(Object.keys(SPECIES_NAMES).length,8);
  assert.equal(speciesLabel('TA'),'Tyramine');
  assert.match(regionLabel('unpublished-area'),/^Unknown region:/);
  assert.match(regionLabel('__proto__'),/^Unknown region:/);
  assert.match(speciesLabel('constructor'),/^Unknown chemical:/);
  assert.equal(regionLabel(null),'Unassigned brain region');
});
