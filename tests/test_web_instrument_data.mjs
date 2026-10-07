import test from 'node:test';
import assert from 'node:assert/strict';
import {parseEEGCsv,parseNifti,niftiVoxelSeries} from '../src/flybrain/web/instrument-data.js';
function nii({little=true,dims=[2,3,2,2],slope=2,intercept=-5,type=4}={}){
  const bytes=type===16?4:2,count=dims.reduce((a,b)=>a*b,1),buffer=new ArrayBuffer(352+count*bytes),view=new DataView(buffer);view.setInt32(0,348,little);view.setInt16(40,4,little);dims.forEach((v,i)=>view.setInt16(42+i*2,v,little));view.setInt16(70,type,little);view.setInt16(72,bytes*8,little);[1,2,3,4].forEach((v,i)=>view.setFloat32(80+i*4,v,little));view.setFloat32(108,352,little);view.setFloat32(112,slope,little);view.setFloat32(116,intercept,little);view.setUint8(123,10);view.setInt16(254,1,little);for(let i=0;i<3;i++){view.setFloat32(280+(i*4+i)*4,i+1,little);view.setFloat32(280+(i*4+3)*4,10,little);}new Uint8Array(buffer,344,4).set([110,43,49,0]);for(let i=0;i<count;i++)view[type===16?'setFloat32':'setInt16'](352+i*bytes,i,little);return buffer;
}
test('EEG importer preserves numeric values, quoted headers and time units',()=>{
  const data=parseEEGCsv('time_s,"Left, temporal",Right\r\n0,-2.5,3\r\n0.002,4,5\r\n',{unit:'µV'});
  assert.deepEqual([...data.timeMs],[0,2]);assert.equal(data.channels[0].label,'Left, temporal');assert.deepEqual([...data.channels[0].values],[-2.5,4]);assert.equal(data.unit,'µV');
});
test('EEG requires explicit ambiguous time units and rejects malformed/invalid samples',()=>{
  assert.throws(()=>parseEEGCsv('time,A\n0,1\n1,2'),/Choose seconds/);
  assert.deepEqual([...parseEEGCsv('time,A\n0,1\n1,2',{timeUnit:'ms'}).timeMs],[0,1]);
  for(const csv of ['time_ms,A\n0,1\n0,2','time_ms,A\n0,1\n1,','time_ms,A\n0,1\n1,2,3','time_ms,A\n0,1\n1,NaN'])assert.throws(()=>parseEEGCsv(csv));
});
test('NIfTI scalar access obeys endian, x-fastest storage, affine and scaling',()=>{
  for(const little of[true,false]){const volume=parseNifti(nii({little}));assert.deepEqual(volume.dims,[2,3,2,2]);assert.equal(volume.valueAt(1,2,1,1),41);assert.equal(volume.valueAt(0,0,0,0),-5);assert.equal(volume.timeStepMs,4000);assert.equal(volume.spatialUnit,'mm');assert.deepEqual(volume.voxelToWorld(1,2,1),[11,14,13]);assert.throws(()=>volume.valueAt(2,0,0),/outside/);}
});
test('zero slope disables NIfTI scaling and float volumes retain precision',()=>{
  assert.equal(parseNifti(nii({slope:0,intercept:999})).valueAt(1,0,0),1);
  const buffer=nii({type:16,slope:1,intercept:0});new DataView(buffer).setFloat32(352,3.125,true);assert.equal(parseNifti(buffer).valueAt(0,0,0),3.125);
});
test('NIfTI preserves its declared time offset in milliseconds',()=>{
  const buffer=nii();new DataView(buffer).setFloat32(136,1.25,true);assert.equal(parseNifti(buffer).timeOriginMs,1250);
});
test('charted voxels preserve declared seconds/milliseconds origins and original sample values',()=>{
  for(const[units,offset,expected]of [[10,1.25,[1250,5250]],[18,12.5,[12.5,16.5]],[10,-1.25,[-1250,2750]]]){
    const buffer=nii(),header=new DataView(buffer);header.setUint8(123,units);header.setFloat32(136,offset,true);
    const volume=parseNifti(buffer),selection=[1,2,1],series=niftiVoxelSeries(volume,selection);
    assert.deepEqual([...series.timeMs],expected);assert.deepEqual([...series.values],[17,41]);assert.deepEqual(selection,[1,2,1]);
    series.values[0]=999;assert.equal(volume.valueAt(...selection,0),17);
  }
  const buffer=nii();new DataView(buffer).setUint8(123,2);assert.throws(()=>niftiVoxelSeries(parseNifti(buffer),[0,0,0]),/declared finite time/);
});
test('NIfTI parser rejects truncated data, unsupported formats and invalid dimensions',()=>{
  assert.throws(()=>parseNifti(nii().slice(0,360)),/truncated/);
  const magic=nii();new Uint8Array(magic)[344]=0;assert.throws(()=>parseNifti(magic),/single-file/);
  const dims=nii();new DataView(dims).setInt16(42,0,true);assert.throws(()=>parseNifti(dims),/positive/);
  const datatype=nii();new DataView(datatype).setInt16(70,128,true);assert.throws(()=>parseNifti(datatype),/datatype/);
});
