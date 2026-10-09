import test from 'node:test';
import assert from 'node:assert/strict';
import {once} from 'node:events';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {createRequire} from 'node:module';
import {makeApp} from '../functions/app.js';
import {identity} from '../functions/service.js';
import {makeNetlifyHandler,countryPolicy} from '../netlify/adapter.mjs';
const require = createRequire(new URL('../functions/package.json', import.meta.url));
const {initializeApp, deleteApp} = require('firebase-admin/app');
const {getAuth} = require('firebase-admin/auth');
const {initializeFirestore} = require('firebase-admin/firestore');

const projectId='demo-cognesia-accounts';
assert.equal(process.env.FIREBASE_AUTH_EMULATOR_HOST,'127.0.0.1:19099');
assert.equal(process.env.FIRESTORE_EMULATOR_HOST,'127.0.0.1:18080');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../..');
const firebase=initializeApp({projectId}), auth=getAuth(firebase), db=initializeFirestore(firebase,{preferRest:true});
let now=Date.now();
const origin='http://127.0.0.1:15000';
const server=makeApp({db,auth,origin,phoneEnabled:true,clock:()=>now}).listen(0,'127.0.0.1');
await once(server,'listening');
const base='http://127.0.0.1:'+server.address().port;
const authBase='http://127.0.0.1:19099/identitytoolkit.googleapis.com/v1/';
const password='test-only-long-password-918';
async function authRequest(route,body) {
  const r=await fetch(authBase+route+'?key=emulator-key',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await r.json(); assert.equal(r.ok,true,JSON.stringify(data.error)); return data;
}
async function request(route,token,body,extra={}) {
  const headers={...(token?{Authorization:'Bearer '+token}:{}),...(body!==undefined?{'Content-Type':'application/json',Origin:origin,'X-Cognesia-Account':'1'}:{}),...extra};
  const r=await fetch(base+route,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body)});
  return {status:r.status,data:await r.json(),headers:r.headers};
}
async function emailUser(name,verified=true) {
  const email=name+'@example.test';
  const user=await authRequest('accounts:signUp',{email,password,returnSecureToken:true});
  if (!verified) return user;
  await authRequest('accounts:sendOobCode',{requestType:'VERIFY_EMAIL',idToken:user.idToken});
  const codes=await (await fetch('http://127.0.0.1:19099/emulator/v1/projects/'+projectId+'/oobCodes')).json();
  const code=codes.oobCodes.filter(c=>c.email===email&&c.requestType==='VERIFY_EMAIL').at(-1);
  assert.ok(code); await authRequest('accounts:update',{oobCode:code.oobCode});
  return authRequest('accounts:signInWithPassword',{email,password,returnSecureToken:true});
}

test('verified public accounts issue revocable keys accepted by the actual Python app',async t=>{
  const alice=await emailUser('alice-'+Date.now());
  const bob=await emailUser('bob-'+Date.now());
  const pending=await emailUser('pending-'+Date.now(),false);
  let key,replacement;
  await t.test('unverified identity, missing token and cross-origin writes are rejected',async()=>{
    assert.equal((await request('/api/enroll',pending.idToken,{})).status,403);
    assert.equal((await request('/api/enroll',undefined,{})).status,401);
    assert.equal((await request('/api/enroll',alice.idToken,{}, {Origin:'https://untrusted.example'})).status,403);
    assert.equal((await request('/api/enroll',alice.idToken,{admin:true})).status,400);
  });
  await t.test('concurrent enrollment returns one secret and creates one account/key',async()=>{
    const outcomes=await Promise.all(Array.from({length:4},()=>request('/api/enroll',alice.idToken,{})));
    assert.equal(outcomes.filter(r=>r.status===201).length,1);
    assert.equal(outcomes.filter(r=>r.data.issued_key).length,1);
    key=outcomes.find(r=>r.data.issued_key).data.issued_key;
    const saved=(await db.collection('accessKeys').doc(key.key_id).get()).data();
    assert.equal(JSON.stringify(saved).includes(key.api_key),false);
    assert.equal((await request('/api/account',alice.idToken)).data.issued_key,undefined);
    assert.equal((await request('/api/enroll',alice.idToken,{})).data.issued_key,undefined);
  });
  await t.test('the existing native Python verifier accepts the issued key',async()=>{
    const check=await request('/v1/access',key.api_key);
    assert.equal(check.status,200); assert.deepEqual(check.data.scopes,['read','run']);
    assert.equal(check.data.hosted_compute,false);
    assert.equal(JSON.stringify(check.data).includes('@example.test'),false);
    const python=spawn(process.env.COGNESIA_PYTHON||path.join(root,'.venv/bin/python'),['-c',
      'import json,sys,tempfile\nfrom flybrain.app_access import AppAccess\nx=json.load(sys.stdin)\nwith tempfile.TemporaryDirectory() as root:\n a=AppAccess(root,endpoint=x["endpoint"])\n token,state=a.login(x["key"])\n assert state["authenticated"] and state["scopes"]==["read","run"]\n print("native app login passed")'],
      {cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'src'),COGNESIA_ACCESS_ALLOW_LOOPBACK_HTTP:'1'},stdio:['pipe','pipe','pipe']});
    let output='',errors=''; python.stdout.on('data',d=>output+=d); python.stderr.on('data',d=>errors+=d);
    python.stdin.end(JSON.stringify({endpoint:base+'/v1/access',key:key.api_key}));
    const [code]=await once(python,'close'); assert.equal(code,0,errors); assert.match(output,/passed/);
  });
  await t.test('another account cannot revoke or retrieve a key',async()=>{
    assert.equal((await request('/api/revoke',bob.idToken,{key_id:key.key_id})).status,404);
    assert.equal((await request('/api/account',bob.idToken)).data.key,null);
    assert.equal((await request('/v1/access',key.api_key.slice(0,-1)+(key.api_key.endsWith('A')?'B':'A'))).status,401);
    assert.equal((await request('/v1/access?key=forbidden',key.api_key)).status,400);
  });
  await t.test('browser database reads and writes are denied even after sign-in',async()=>{
    const url='http://127.0.0.1:18080/v1/projects/'+projectId+'/databases/(default)/documents/accounts/'+identity(alice.localId).customerId;
    for (const token of [null,alice.idToken]) {
      const headers=token?{Authorization:'Bearer '+token}:{};
      assert.equal((await fetch(url,{headers})).status,403);
      assert.equal((await fetch(url,{method:'PATCH',headers:{...headers,'Content-Type':'application/json'},body:'{"fields":{}}'})).status,403);
    }
  });
  await t.test('replacement is atomic, throttled, and invalidates the previous key',async()=>{
    assert.equal((await request('/api/replace',alice.idToken,{})).status,429);
    now+=31_000;
    const result=await request('/api/replace',alice.idToken,{}); assert.equal(result.status,201);
    replacement=result.data.issued_key;
    assert.equal((await request('/v1/access',key.api_key)).status,401);
    assert.equal((await request('/v1/access',replacement.api_key)).status,200);
    assert.equal((await request('/api/revoke',alice.idToken,{key_id:replacement.key_id})).status,200);
    assert.equal((await request('/v1/access',replacement.api_key)).status,401);
  });
  await t.test('phone verification also enrolls a separate valid account',async()=>{
    const phoneNumber='+15555550123';
    const sent=await authRequest('accounts:sendVerificationCode',{phoneNumber,recaptchaToken:'emulator'});
    const codes=await(await fetch('http://127.0.0.1:19099/emulator/v1/projects/'+projectId+'/verificationCodes')).json();
    const code=codes.verificationCodes.find(c=>c.sessionInfo===sent.sessionInfo);
    assert.ok(code);
    const user=await authRequest('accounts:signInWithPhoneNumber',{sessionInfo:sent.sessionInfo,code:code.code});
    const result=await request('/api/enroll',user.idToken,{}); assert.equal(result.status,201);
    const phoneKey=result.data.issued_key.api_key;
    assert.equal((await request('/v1/access',phoneKey)).status,200);
    await auth.updateUser(user.localId,{disabled:true});
    assert.equal((await request('/v1/access',phoneKey)).status,401);
  });
  await t.test('persistent daily issuance limits and password-reset revocation are enforced',async()=>{
    const user=await emailUser('limits-'+Date.now());
    let latest;
    for (let i=0;i<5;i++) {
      now+=31_000;
      const r=await request(i?'/api/replace':'/api/enroll',user.idToken,{});
      assert.equal(r.status,201); latest=r.data.issued_key;
    }
    now+=31_000;
    assert.equal((await request('/api/replace',user.idToken,{})).status,429);
    // Use a record created before the real provider revocation timestamp.
    await db.collection('accessKeys').doc(latest.key_id).update({created:Date.now()-60_000});
    await auth.revokeRefreshTokens(user.localId);
    assert.equal((await request('/v1/access',latest.api_key)).status,401);
  });
  await t.test('expired keys and stale sign-in cannot grant new access',async()=>{
    const result=await request('/api/enroll',bob.idToken,{}); assert.equal(result.status,201);
    now+=91*86400_000;
    assert.equal((await request('/v1/access',result.data.issued_key.api_key)).status,401);
    assert.equal((await request('/api/replace',bob.idToken,{})).status,401);
  });
});

test('Netlify routes verify identity, issue keys, enforce location and revoke against real emulators',async()=>{
  const accountOrigin='https://accounts.example.test';
  const invoke=makeNetlifyHandler(makeApp({db,auth,origin:accountOrigin,googleEnabled:true}),
    {origin:accountOrigin,blockedCountries:countryPolicy('CN,CU,LA,KP,VN')});
  const context={ip:'192.0.2.9',geo:{country:{code:'US'}}};
  const user=await emailUser('netlify-'+Date.now());
  const headers={'Content-Type':'application/json',Origin:accountOrigin,'X-Cognesia-Account':'1',Authorization:'Bearer '+user.idToken};
  const config=await invoke(new Request(accountOrigin+'/api/config'),context);
  assert.deepEqual(await config.json(),{available:true,phone_enabled:false,google_enabled:true});
  const enrolled=await invoke(new Request(accountOrigin+'/api/enroll',{method:'POST',headers,body:'{}'}),context);
  assert.equal(enrolled.status,201); const {issued_key:key}=await enrolled.json();
  const access=()=>new Request(accountOrigin+'/v1/access',{headers:{Authorization:'Bearer '+key.api_key,'X-Country-Code':'US'}});
  assert.equal((await invoke(access(),context)).status,200);
  assert.equal((await invoke(access(),{...context,geo:{country:{code:'CN'}}})).status,403);
  const revoked=await invoke(new Request(accountOrigin+'/api/revoke',{method:'POST',headers,body:JSON.stringify({key_id:key.key_id})}),context);
  assert.equal(revoked.status,200);
  assert.equal((await invoke(access(),context)).status,401);
});

test.after(async()=>{await new Promise(resolve=>server.close(resolve)); await db.terminate(); await deleteApp(firebase);});
