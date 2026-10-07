import test from 'node:test';
import assert from 'node:assert/strict';
import {createSignalAdapter} from '../src/flybrain/web/analysis-data.js';
import {validateChemistry} from '../src/flybrain/web/chemistry.js';
function fixture(){
 const c={enabled:true,species:['DA','OA','5HT','NO','sNPF','peptide_pool','TA','ACh'],compartment_names:['a'],time_ms:[0,20],concentrations_au:new Float32Array(16),baseline_concentrations_au:new Float32Array(16),membership:{indptr:[0,1],indices:[0],weights:[1]},state_names:[],hormone_names:[],enzymes:{enabled:true,pool_names:['choline','tyramine'],flux_names:['ChAT']},enzyme_pools_au:[[[1],[2]],[[.9],[1.8]]],baseline_enzyme_pools_au:[[[1],[2]],[[1],[2]]],enzyme_flux_au_per_ms:[[[.01]],[[.02]]],baseline_enzyme_flux_au_per_ms:[[[0]],[[0]]]};
 return {summary:{id:'test',label:'Test',frames:{count:2,time_ms:[0,20]},activity:{shape:[2,1]},peripheral:{enabled:true,time_ms:[0,20],modules:[{id:'organ',label:'Antenna'}],state_names:['activation'],state_values:[[[.1]],[[.2]]],baseline_state_values:[[[0]],[[0]]]}},activity:{raw:new Float32Array([-52,-51])},metadata:{},chemistry:validateChemistry(c,1,[0,20])};
}
test('enzyme pools, fluxes, and organ outputs retain recorded axes, units, and conditions',async()=>{
 const state=fixture(),adapter=createSignalAdapter({getState:()=>state,requestJSON:()=>{throw Error('Unexpected network');}});
 const ids=adapter.listSignals().map(x=>x.id);
 for(const id of ['enzyme:pools:1:0:stimulated','enzyme:flux:0:0:baseline','organ:0:0:stimulated'])assert.ok(ids.includes(id));
 const pool=await adapter.resolveSignal('enzyme:pools:1:0:stimulated');assert.equal(pool.unit,'a.u.');assert.deepEqual([...pool.timeMs],[0,20]);assert.ok(Math.abs(pool.values[1]-1.8)<1e-6);
 const flux=await adapter.resolveSignal('enzyme:flux:0:0:baseline');assert.equal(flux.unit,'a.u./ms');assert.deepEqual([...flux.values],[0,0]);
 const organ=await adapter.resolveSignal('organ:0:0:stimulated');assert.deepEqual([...organ.values],[.1,.2]);assert.match(organ.description,/not calibrated/);
 await assert.rejects(adapter.resolveSignal('enzyme:pools:99:0:stimulated'),/not recorded/);
});
test('missing or invalid enabled enzyme arrays fail instead of yielding zero pools',()=>{
 const record=fixture().chemistry;
 assert.throws(()=>validateChemistry({...record,enzyme_pools_au:undefined},1,[0,20]),/shape/);
 assert.throws(()=>validateChemistry({...record,enzyme_flux_au_per_ms:[NaN,0]},1,[0,20]),/nonfinite/);
});
