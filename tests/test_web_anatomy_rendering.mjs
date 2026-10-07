import test from 'node:test';
import assert from 'node:assert/strict';
import {centeredAnatomy,fittedCameraDistance,recordingRowMap,projectRecordingFrame} from '../src/flybrain/web/anatomy-rendering.js';

test('centering excludes omitted coordinates and never mutates source positions',()=>{
  const source=new Float32Array([10,2,0,12,4,2,0,0,0,NaN,1,2]),before=source.slice();
  const result=centeredAnatomy(source,new Uint32Array([0,1,3]));
  assert.deepEqual(source,before);assert.deepEqual(result.offset,[11,3,1]);
  assert.deepEqual([...result.visibleIndices],[0,1]);
  assert.deepEqual([...result.positions.slice(0,6)],[-1,-1,-1,1,1,1]);
  assert.ok(Math.abs(result.radius-Math.sqrt(3))<1e-7);
});
test('camera fit accounts for aspect, depth and field of view',()=>{
  const bounds=[[-2,-1,-.5],[2,1,.5]],wide=fittedCameraDistance(bounds,[0,0,1],[0,1,0],36,2);
  const narrow=fittedCameraDistance(bounds,[0,0,1],[0,1,0],36,.5);
  assert.ok(narrow>wide*3);
  for(const aspect of [.5,1,2,4]) {
    const distance=fittedCameraDistance(bounds,[0,0,1],[0,1,0],36,aspect),tan=Math.tan(18*Math.PI/180);
    assert.ok(2/(distance-.5)/tan/aspect<1);assert.ok(1/(distance-.5)/tan<1);
  }
});
const identities=['banc:888:11','banc:888:22','banc:888:33'].map(entity_id=>({entity_id}));
test('recording-local rows map by source identities and missing activity stays unknown',()=>{
  const map=recordingRowMap({fullCount:3,recordedCount:2,fullIdentities:identities,recordedIdentities:[identities[2],identities[0]],fullModelHash:'same',recordedModelHash:'same'});
  assert.deepEqual([...map.recordedToAnatomy],[2,0]);assert.deepEqual([...map.anatomyToRecorded],[1,-1,0]);
  const values=projectRecordingFrame(new Float32Array([-50,-60,-51,-61]),1,map.recordedToAnatomy,3);
  assert.equal(values[0],-61);assert.ok(Number.isNaN(values[1]));assert.equal(values[2],-51);
});
test('nested research and recording subsets map once; incompatible identities fail closed',()=>{
  const map=recordingRowMap({fullCount:8,recordedCount:2,parentIndices:[3,7,1],recordedIndices:[2,0]});
  assert.deepEqual([...map.recordedToAnatomy],[1,3]);
  assert.throws(()=>recordingRowMap({fullCount:3,recordedCount:3}),/verified mapping/);
  assert.throws(()=>recordingRowMap({fullCount:3,recordedCount:3,allowReleasedOrder:true,fullModelHash:'a',recordedModelHash:'b'}),/different source/);
  assert.throws(()=>recordingRowMap({fullCount:3,recordedCount:1,fullIdentities:identities,recordedIdentities:[{entity_id:'flywire:783:11'}]}),/uniquely/);
  assert.throws(()=>recordingRowMap({fullCount:3,recordedCount:2,recordedIndices:[1,1]}),/uniquely/);
});

test('class averages use only recorded source members and preserve unavailable channels',async()=>{
  const {recordedClassTraces}=await import('../src/flybrain/web/anatomy-rendering.js');
  const result=recordedClassTraces({groups:[{id:0,name:'central',count:100},{id:1,name:'motor',count:30}],
    groupIds:[1,0,0,1],mapping:[2,0],frameCount:2,activity:{raw:new Float32Array([-60,-50,NaN,-40])}});
  assert.deepEqual(result[0].raw.slice(0,1),[-60]);assert.ok(Number.isNaN(result[0].raw[1]));
  assert.equal(result[0].n_recorded,1);assert.equal(result[0].n_total,100);assert.equal(result[0].baseline,null);
  assert.deepEqual(result[1].raw,[-50,-40]);assert.equal(result[1].values,null);
});

test('unavailable full version opens only its matching saved anatomy snapshot',async()=>{
  const {recordingAnatomySource}=await import('../src/flybrain/web/anatomy-rendering.js');
  const saved={model_id:'flywire-783',model_hash:'historical-config',neuron_count:2,
    metadata_url:'/saved/metadata.json',positions_url:'/saved/positions.bin',groups_url:'/saved/groups.bin',
    visible_indices_url:'/saved/visible_indices.bin',identities_url:'/saved/identities.json'};
  const summary={model_id:'flywire-783',model_hash:'historical-config',activity:{shape:[5,2]},anatomy:saved};
  let requested;
  const result=await recordingAnatomySource(summary,async version=>{requested=version;throw Error('Historical FlyWire source identity differs');});
  assert.deepEqual(requested,{modelId:'flywire-783',modelHash:'historical-config'});
  assert.equal(result.scope,'recorded_historical');assert.match(result.warning,/historical recorded anatomy only/);
  assert.equal(result.anatomy.positions_url,saved.positions_url);assert.equal(result.anatomy.model_hash,'historical-config');
  assert.equal(saved.anatomy_scope,undefined); // saved metadata remains unchanged
  const identities=[{entity_id:'flywire:783:11'},{entity_id:'flywire:783:33'}];
  const map=recordingRowMap({fullCount:2,recordedCount:2,fullIdentities:identities,recordedIdentities:identities,
    fullModelHash:result.anatomy.model_hash,recordedModelHash:summary.model_hash});
  assert.deepEqual([...projectRecordingFrame(new Float32Array([-60,-50]),0,map.recordedToAnatomy,2)],[-60,-50]);
  const full={model_id:'flywire-783',model_hash:'historical-config',neuron_count:100};
  assert.deepEqual(await recordingAnatomySource(summary,async()=>full),{anatomy:full,scope:'full',warning:null});
});

test('saved anatomy fallback rejects mismatched identity, rows, and incomplete assets',async()=>{
  const {recordingAnatomySource}=await import('../src/flybrain/web/anatomy-rendering.js');
  const saved={model_id:'old-model',model_hash:'old-hash',neuron_count:2,
    metadata_url:'/saved/m',positions_url:'/saved/p',groups_url:'/saved/g',visible_indices_url:'/saved/v',identities_url:'/saved/i'};
  const summary={model_id:'old-model',model_hash:'old-hash',activity:{shape:[5,2]},anatomy:saved};
  const unavailable=async()=>{throw Error('Full source unavailable');};
  await assert.rejects(()=>recordingAnatomySource({...summary,anatomy:null},unavailable),/Full source unavailable/);
  await assert.rejects(()=>recordingAnatomySource({...summary,anatomy:{...saved,model_hash:'different'}},unavailable),/identity differs/);
  await assert.rejects(()=>recordingAnatomySource({...summary,anatomy:{...saved,model_id:'different'}},unavailable),/identity differs/);
  await assert.rejects(()=>recordingAnatomySource({...summary,anatomy:{...saved,neuron_count:3}},unavailable),/recorded neuron rows/);
  await assert.rejects(()=>recordingAnatomySource({...summary,anatomy:{...saved,identities_url:null}},unavailable),/lacks complete/);
});
