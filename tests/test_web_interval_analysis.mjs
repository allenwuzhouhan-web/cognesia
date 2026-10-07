import test from 'node:test';
import assert from 'node:assert/strict';
import {analyzeSignal,selectSignalInterval,describeFourierFit,serverFourierResult} from '../src/flybrain/web/signals.js';
const close=(a,b,epsilon=1e-9)=>assert.ok(Math.abs(a-b)<epsilon,`${a} != ${b}`);

test('interval selection normalizes reversed bounds, snaps inclusively and never resamples',()=>{
  const times=Float64Array.from([100,102,104,106,108]),values=Float64Array.from([1,2,3,4,5]);
  const a=selectSignalInterval(times,values,[107,101.1]);
  assert.deepEqual([...a.timeMs],[102,104,106,108]);assert.deepEqual([...a.values],[2,3,4,5]);assert.equal(a.startIndex,1);assert.equal(a.endIndex,4);
  const all=selectSignalInterval(times,values,[-100,1000]);assert.deepEqual([...all.timeMs],[...times]);
  values[1]=99;assert.equal(a.values[0],2);
});
test('single sample, nonfinite, out-of-range and malformed intervals fail explicitly',()=>{
  for(const interval of [[1,1],[NaN,2],[0],[4,5]])assert.throws(()=>selectSignalInterval([0,1,2],[1,2,3],interval));
  assert.throws(()=>selectSignalInterval([0,0,1],[1,2,3]),/increasing/);
  const selected=selectSignalInterval([0,1,2.1],[1,2,3]);assert.throws(()=>analyzeSignal(selected.timeMs,selected.values),/uniform/);
});
test('cropped nonzero-origin sine equation retains signed DC and reconstructs original samples',()=>{
  const n=32,dt=5,origin=735,phase=-.3;
  const times=Float64Array.from({length:n+8},(_,i)=>origin+(i-4)*dt),values=Float64Array.from(times,t=>-52+7*Math.cos(2*Math.PI*3*(t-origin)/(n*dt)+phase));
  const selected=selectSignalInterval(times,values,[origin,origin+(n-1)*dt]),analysis=analyzeSignal(selected.timeMs,selected.values,{window:'hann',demean:true}),fit=describeFourierFit(analysis,selected.values,3,'mV');
  close(fit.mean,-52);close(fit.rmse,0);close(fit.rSquared,1);close(fit.timeOriginMs,origin);assert.equal(fit.timeUnit,'seconds');assert.match(fit.equation,/− 0.735/);assert.match(fit.equation,/-52/);
  for(let i=0;i<n;i++){const t=selected.timeMs[i]/1000,formula=fit.mean+fit.terms.reduce((sum,term)=>sum+term.amplitude*Math.cos(2*Math.PI*term.frequencyHz*(t-fit.timeOriginMs/1000)+term.phaseRadians),0);close(formula,selected.values[i]);}
});
test('residual metrics reflect omitted high harmonics and Nyquist is not doubled',()=>{
  const n=64,times=Float64Array.from({length:n},(_,i)=>i*2),values=Float64Array.from({length:n},(_,i)=>-4+2*Math.cos(2*Math.PI*2*i/n)+3*(i%2?-1:1));
  const analysis=analyzeSignal(times,values),low=describeFourierFit(analysis,values,2),all=describeFourierFit(analysis,values,n/2);
  close(low.rmse,3);close(all.rmse,0);close(all.terms.at(-1).amplitude,3);assert.equal(all.terms.at(-1).nyquist,true);
  for(let i=0;i<n;i++)close(low.residual[i],3*(i%2?-1:1));
});
test('constant-signal fit reports finite quality and preserves negative mean',()=>{
  const values=new Float64Array(8).fill(-65),analysis=analyzeSignal([0,1,2,3,4,5,6,7],values),fit=describeFourierFit(analysis,values,0,'mV');
  assert.equal(fit.equation,'y(t) ≈ -65');assert.equal(fit.rSquared,1);assert.equal(fit.rmse,0);
});
test('server sine/cosine coefficients normalize to worker phases and seconds, including constant R squared',()=>{
  const response={sample_count:4,time_ms:[700,702,704,706],sample_interval_ms:2,nyquist_hz:250,resolution_hz:125,
    period_ms:8,time_origin_ms:700,frequencies_hz:[0,125,250],amplitudes:[52,3,0],coefficients:[{k:1,frequency_hz:125,cos:0,sin:3}],dc:-52,
    reconstruction:[-52,-49,-52,-55],residuals:[0,0,0,0],rmse:0,r_squared:null,harmonics:1,range:{start_ms:700,end_ms:706}};
  const result=serverFourierResult(response,'mV');close(result.fit.terms[0].phaseRadians,-Math.PI/2);close(result.fit.terms[0].amplitude,3);assert.match(result.fit.equation,/t − 0.7/);assert.equal(result.fit.timeUnit,'seconds');assert.equal(result.fit.rSquared,1);assert.equal(result.analysis.n,4);
});
