import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fitBrainToHead, validateFlyFrame} from '../src/flybrain/web/fly-body.js';

const asset=new URL('../src/flybrain/web/assets/fly/',import.meta.url);
const bounds=[[.5,-.4,1],[1.1,.4,1.8]];
test('brain fit preserves original indices, relative geometry, uniform scale and input arrays',()=>{
  const positions=new Float32Array([-1,-2,-1,0,0,0,1,2,1,NaN,0,0]);
  const before=positions.slice(),ids=new Uint32Array([2,0,1,3]);
  const result=fitBrainToHead({positions,visibleIndices:ids,headBounds:bounds});
  assert.deepEqual(positions,before);assert.deepEqual([...ids],[2,0,1,3]);
  assert.deepEqual([...result.visibleIndices],[2,0,1]);assert.equal(result.neuronCount,4);
  for(const i of result.visibleIndices)for(let j=0;j<3;j++)assert.ok(result.positions[3*i+j]>bounds[0][j]&&result.positions[3*i+j]<bounds[1][j]);
  assert.ok(Math.abs((result.positions[6]-result.positions[0])/4-result.scale)<1e-7);
  assert.ok(Math.abs((result.positions[7]-result.positions[1])/-2-result.scale)<1e-7);
  assert.ok(Math.abs((result.positions[8]-result.positions[2])/2-result.scale)<1e-7);
});
test('invalid anatomical inputs fail instead of creating substitute brain geometry',()=>{
  assert.throws(()=>fitBrainToHead({positions:[0,1],headBounds:bounds}),/xyz/);
  assert.throws(()=>fitBrainToHead({positions:[NaN,0,0],headBounds:bounds}),/No finite/);
  assert.throws(()=>fitBrainToHead({positions:[0,0,0],headBounds:[[0,0,0],[0,1,1]]}),/Head bounds/);
});
test('a recording and aligned frame are required to display activity',()=>{
  const frame={values:new Float32Array([-1,0,1]),timeMs:200,mode:'chemical',hasRecording:true};
  assert.equal(validateFlyFrame(frame,3).active,true);
  assert.equal(validateFlyFrame({...frame,hasRecording:false},3).active,false);
  assert.equal(validateFlyFrame({...frame,timeMs:NaN},3).active,false);
  assert.equal(validateFlyFrame(frame,4).active,false);
  assert.equal(validateFlyFrame({...frame,mode:'invented'},3).active,false);
  assert.equal(validateFlyFrame({...frame,mode:'anatomy'},3).active,false);
  assert.deepEqual([...frame.values],[-1,0,1]);
});
test('full-resolution mesh buffer matches manifest and retains every original source triangle',async()=>{
  const m=JSON.parse(await readFile(new URL('manifest.json',asset),'utf8'));
  const binary=await readFile(new URL(m.binary,asset));
  assert.equal(binary.length,m.bytes);assert.equal(createHash('sha256').update(binary).digest('hex'),m.binary_sha256);
  assert.equal(m.segments.length,69);assert.equal(m.total_triangles,447417);assert.ok(m.neutral_pose_reference_max_error_mm<1e-6);
  let count=0;
  for(const [name,g] of Object.entries(m.geometries)){
    const source=await readFile(new URL('source/'+name,asset));
    const item=m.sources.find(x=>x.key.endsWith('/'+name));
    assert.equal(createHash('sha256').update(source).digest('hex'),item.sha256);
    assert.equal(source.readUInt32LE(80),g.triangles);
    assert.equal(g.indices.count,g.triangles*3);
    for(const a of ['positions','normals','indices'])assert.ok(g[a].byte_offset+g[a].count*4<=binary.length);
    for(let i=0;i<g.indices.count;i++)assert.ok(binary.readUInt32LE(g.indices.byte_offset+i*4)<g.vertices);
  }
  for(const s of m.segments){assert.ok(s.matrix.every(Number.isFinite));count+=m.geometries[s.geometry].triangles;}
  assert.equal(count,m.total_triangles);
});
