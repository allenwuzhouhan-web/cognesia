import test from 'node:test';
import assert from 'node:assert/strict';
import express from 'express';
import {makeNetlifyHandler,countryPolicy} from '../netlify/adapter.mjs';

const origin='https://accounts.example.test';
const context={geo:{country:{code:'US'}},ip:'192.0.2.1'};
const app=express(); app.use(express.json());
app.all('/api/echo',(req,res)=>res.json({method:req.method,body:req.body,query:req.query,ip:req.ip}));
const invoke=makeNetlifyHandler(app,{origin,blockedCountries:countryPolicy('CN,CU,LA,KP,VN')});

test('Netlify adapter preserves the request contract and trusted IP',async()=>{
 const r=await invoke(new Request(origin+'/api/echo?check=yes',{method:'POST',headers:{'Content-Type':'application/json','X-Forwarded-For':'203.0.113.55'},body:'{"hello":"world"}'}),context);
 assert.equal(r.status,200); const data=await r.json(); assert.deepEqual(data.body,{hello:'world'});
 assert.equal(data.query.check,'yes'); assert.equal(data.method,'POST'); assert.equal(data.ip,context.ip);
 assert.equal(r.headers.get('Cache-Control'),'no-store, max-age=0');
});
test('location policy rejects blocked or unknown locations and ignores spoofed headers',async()=>{
 for (const country of ['CN','CU','LA','KP','VN',undefined,'ZZ','XX','ZZ-invalid']) {
  const r=await invoke(new Request(origin+'/api/echo',{headers:{'X-Country-Code':'US','X-NF-Geo':'US'}}),{...context,geo:{country:{code:country}}});
  assert.equal(r.status,403);
 }
 assert.equal((await invoke(new Request('https://preview.example.test/api/echo'),context)).status,403);
 assert.throws(()=>countryPolicy(undefined)); assert.throws(()=>countryPolicy('China'));
 assert.equal(countryPolicy('').size,0);
});
test('oversized bodies are rejected before the Express app runs',async()=>{
 const r=await invoke(new Request(origin+'/api/echo',{method:'POST',body:'x'.repeat(2049)}),context);
 assert.equal(r.status,413);
});
