"""Exercise recording isolation in the real browser script with a tiny DOM adapter."""
from pathlib import Path
import shutil
import subprocess

import pytest


NODE = shutil.which('node')


@pytest.mark.skipif(NODE is None, reason='Node is needed for browser-script state regression')
def test_recording_state_and_late_live_responses_are_isolated():
    script = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(), pending=[], timers=[];
function node(id){if(!nodes.has(id))nodes.set(id,{value:'10000',textContent:'',innerHTML:'',style:{},hidden:false,disabled:false,width:100,height:100,
 classList:{add(){},remove(){},toggle(){}},addEventListener(){},setAttribute(){},getBoundingClientRect(){return {width:400,height:200}},
 querySelector(s){return node(id+s)},getContext(){return new Proxy({},{get(){return ()=>{}}})}});return nodes.get(id)}
const context=vm.createContext({console,URLSearchParams,structuredClone,Float32Array,ArrayBuffer,TextDecoder,
 document:{getElementById:node,querySelector:node,querySelectorAll(){return []},activeElement:{tagName:'BODY'},addEventListener(){}},
 matchMedia(){return {matches:false}},ResizeObserver:class{observe(){}},devicePixelRatio:1,
 requestAnimationFrame(){},setTimeout(){},clearTimeout(){},setInterval(f){timers.push(f);return timers.length},clearInterval(){},
 fetch(url){return new Promise(resolve=>pending.push({url,resolve}))},
 WebSocket:class{close(){}},location:{protocol:'http:',host:'localhost'}});
vm.runInContext(fs.readFileSync('console/console.js','utf8'),context);
(async()=>{
 let chooserCalls=0;node('recording-file').click=()=>chooserCalls++;node('load-recording').onclick();assert.equal(chooserCalls,1);
 vm.runInContext(`snapshot={total_absolute_weight_change:987,atlas_rates_hz:[77],atlas_voltage_mV:[-33],valence:2};rasterData={live:true};weightData={rows:[{live:true}]};atlasPoints=[{i:999}];evidence={gates:[{gate:'live'}]};metadata={neurons:999};enterRecording([{t_sim_ms:0},{t_sim_ms:1,valence:.2}],null,'bare.jsonl');`,context);
 assert.equal(vm.runInContext('snapshot.total_absolute_weight_change',context),undefined);
 assert.equal(vm.runInContext('snapshot.atlas_rates_hz',context),undefined);
 assert.equal(vm.runInContext('rasterData',context),null);
 assert.equal(vm.runInContext('weightData',context),null);
 assert.equal(vm.runInContext('atlasPoints.length',context),0);
 assert.equal(vm.runInContext('metadata.neurons',context),undefined);
 assert.equal(vm.runInContext('evidence.gates',context),undefined);
 assert.equal(node('valence-marker').style.visibility,'hidden');
 assert.equal(node('weight-change').textContent,'—');
 assert.equal(node('step').textContent,'Next frame');
 assert.equal(node('play').textContent,'▶ Play');
 assert.match(node('voltage-warning').textContent,/unavailable/);
 assert.match(node('self-checkp').textContent,/No matching fixture/);
 assert.match(node('field-self-checkp').textContent,/No matching field fixture/);
 vm.runInContext('snapshot.total_absolute_weight_change=5;showRecorded(1)',context);
 assert.equal(vm.runInContext('snapshot.total_absolute_weight_change',context),undefined);
 // The initial HTTP boot was started before recording selection. Its late
 // success must not overwrite the recording's metadata, time or evidence.
 for(const job of pending)job.resolve({json:async()=>job.url.includes('metadata')?{neurons:999}:job.url.includes('status')?{t_sim_ms:999}: {gates:[{gate:'live'}]}});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(vm.runInContext('snapshot.t_sim_ms',context),1);
 assert.equal(vm.runInContext('metadata.neurons',context),undefined);
 assert.equal(vm.runInContext('evidence.gates',context),undefined);
 // Each new recording starts empty, even after another recording had values.
 vm.runInContext("enterRecording([{t_sim_ms:5}],null,'second.jsonl')",context);
 assert.equal(node('valence-marker').style.visibility,'hidden');
 assert.equal(vm.runInContext('snapshot.valence',context),undefined);
 // Export rendering uses only the supplied bounds and does not alter the live
 // history, current selection or canvas. KC marks reveal which rows were drawn.
 const marks=[];
 context.exportPlot=new Proxy({fillRect(...args){marks.push({color:this.fillStyle,args})}},
   {get(target,key){return key in target?target[key]:()=>{}}});
 vm.runInContext(`history=[0,100,200,300].map(t_sim_ms=>({t_sim_ms,kc_rates_hz:[10]}));selection=[50,250];drawTimeline({context:exportPlot,width:400,height:200,bounds:[100,200]});`,context);
 const kcMarks=marks.filter(x=>x.color==='rgba(100,223,200,0.1)');
 assert.equal(kcMarks.length,2);
 assert.equal(kcMarks[0].args[0],100);
 assert.equal(kcMarks[1].args[0],384);
 assert.equal(vm.runInContext('history.length',context),4);
 assert.equal(vm.runInContext('selection.join(",")',context),'50,250');

})().catch(error=>{console.error(error);process.exitCode=1});
'''
    result = subprocess.run([NODE, '-e', script], cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
