import test from 'node:test';
import assert from 'node:assert/strict';
import {alignedDifference,recordedSpikeEvents,fullModelConnectivityRequest} from '../src/flybrain/web/research-data.js';
import {validateRegistration,registeredAnchors} from '../src/flybrain/web/instrument-registration.js';

test('branch differences only subtract exactly matching recorded timestamps',()=>{
  const a={timeMs:[0,1,2,3],values:[3,4,5,6],unit:'mV'},b={timeMs:[0,1.00000001,2,4],values:[9,5,8,10],unit:'mV'},delta=alignedDifference(a,b);
  assert.deepEqual([...delta.timeMs],[0,2]);assert.deepEqual([...delta.values],[6,3]);assert.equal(delta.unmatchedA,2);assert.equal(delta.unmatchedB,2);
  assert.throws(()=>alignedDifference(a,{...b,unit:'V'}),/units/);assert.throws(()=>alignedDifference(a,{...b,timeMs:[4,5,6,7]}),/No resampling/);
});
test('saved and live raster helper retains only actual finite indexed events',()=>{
  assert.deepEqual(recordedSpikeEvents({spike_indices:[2,4,5],spike_times_ms:[2,4,6]},2),[[4,4],[6,5]]);
  assert.deepEqual(recordedSpikeEvents({indices:[0,-1,NaN],times_ms:[1,2,3]}),[[1,0]]);
  assert.deepEqual(recordedSpikeEvents({spike_indices:[1],spike_times_ms:[]}),[]);
});
test('geometry connectivity uses full model indices and immutable hash, never a recording run mapping',()=>{
  const context={modelId:'full-model',modelHash:'full-hash',runId:'subset-recording',positions:new Float32Array(30),metadata:{model_hash:'full-hash'},recordingMetadata:{neuron_count:2},recordedToAnatomy:[8,4],recordedNeuronIndex:index=>index===8?0:index===4?1:-1};
  const request=fullModelConnectivityRequest(context,{sourceIndices:[8,8],targetIndices:[4]});
  assert.deepEqual(request,{limit:100,model_id:'full-model',model_hash:'full-hash',source_indices:[8],target_indices:[4]});
  assert.equal(Object.hasOwn(request,'run_id'),false);assert.deepEqual(context.recordedToAnatomy,[8,4]);
  assert.deepEqual(fullModelConnectivityRequest(context,{sourceRegions:['left','left'],targetRegions:['right']}),{limit:100,model_id:'full-model',model_hash:'full-hash',source_regions:['left'],target_regions:['right']});
});
test('geometry connectivity rejects missing/mismatched identity and indices outside full anatomy',()=>{
  const context={modelId:'m',modelHash:'h',metadata:{model_hash:'h'},positions:new Float32Array(9)};
  assert.throws(()=>fullModelConnectivityRequest({...context,modelHash:null,metadata:{}}),/source identity/);
  assert.throws(()=>fullModelConnectivityRequest({...context,modelHash:'wrong'}),/hashes disagree/);
  for(const index of [-1,3,1.5,NaN])assert.throws(()=>fullModelConnectivityRequest(context,{sourceIndices:[index],targetIndices:[1]}),/outside/);
});
const context={modelId:'flywire-783',modelHash:'source-hash',volumeHash:'file-hash',dims:[10,12,8,1]};
const registration={schema_version:1,model_id:context.modelId,model_hash:context.modelHash,volume_sha256:context.volumeHash,volume_dims:context.dims.slice(0,3),source_units:'um',target_units:'voxel',model_um_to_voxel:[[.5,0,0,-5],[0,1,0,-10],[0,0,2,-40],[0,0,0,1]]};
test('registration requires exact model hash, volume bytes, dimensions, explicit units and invertible affine',()=>{
  assert.deepEqual(validateRegistration(registration,context),registration);
  for(const changed of [{model_id:'other'},{model_hash:'old'},{volume_sha256:'other'},{source_units:'mm'},{volume_dims:[8,8,8]},{model_um_to_voxel:[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,1]]}])assert.throws(()=>validateRegistration({...registration,...changed},context));
});
test('registered anchors undo model normalization before applying physical transform and slice bounds',()=>{
  const result=registeredAnchors({positions:new Float32Array([0,0,0,.5,0,0,0,0,1]),visibleIndices:new Uint32Array([0,1,2]),centerUm:[20,15,22],scaleUm:4,registration,dims:context.dims,axis:2,slice:4});
  assert.deepEqual(result,[{index:0,voxel:[5,5,4]},{index:1,voxel:[6,5,4]}]);
  assert.throws(()=>registeredAnchors({positions:[0,0,0],centerUm:null,scaleUm:1,registration,dims:context.dims,axis:2,slice:0}),/transform/);
});
