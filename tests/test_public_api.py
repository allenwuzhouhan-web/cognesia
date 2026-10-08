"""Password-only gateway boundaries, private secret files and at-most-once tools."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sqlite3
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from flybrain.api_tools import ToolError, build_tool_request, execute_tool, tool_schemas, validate_backend_url, validate_tool
from flybrain.public_api import (APIError, Config, Ledger, LEDGER_KEY, PasswordVerifier,
                                create_app, initialize_password, main)


def credentials(tmp_path):
    verifier,output=tmp_path/'password-hash.json',tmp_path/'password.json'
    initialize_password(verifier,output)
    return verifier,json.loads(output.read_text())['password']


def test_generated_password_uses_salted_scrypt_and_private_separate_files(tmp_path,capsys):
    verifier=tmp_path/'password-hash.json';output=tmp_path/'password.json'
    main(['--password-file',str(verifier),'init-password','--output',str(output)])
    password=json.loads(output.read_text())['password']
    value=json.loads(verifier.read_text())
    assert len(password)==43 and value['algorithm']=='scrypt'
    assert value['n']==32768 and value['r']==8 and value['p']==1
    assert password not in verifier.read_text() and password not in capsys.readouterr().out
    assert PasswordVerifier.load(verifier).verify(password)
    assert not PasswordVerifier.load(verifier).verify(password+'wrong')
    assert not PasswordVerifier.load(verifier).verify('')
    assert not PasswordVerifier.load(verifier).verify('x'*257)
    assert all(path.stat().st_mode&0o777==0o600 for path in (verifier,output))
    assert not (tmp_path/'tool-gateway.sqlite3').exists()


def test_password_creation_never_overwrites_or_leaves_partial_plaintext(tmp_path):
    verifier,password=credentials(tmp_path)
    original=verifier.read_bytes()
    with pytest.raises(FileExistsError):initialize_password(verifier,tmp_path/'new-password.json')
    assert not (tmp_path/'new-password.json').exists() and verifier.read_bytes()==original
    with pytest.raises(ValueError):initialize_password(verifier,verifier)
    verifier.chmod(0o644)
    with pytest.raises(ValueError,match='permissions'):PasswordVerifier.load(verifier)


def test_verifier_rejects_unbounded_or_invalid_hash_configuration(tmp_path):
    verifier,_=credentials(tmp_path);record=json.loads(verifier.read_text())
    for update in ({'n':2**60},{'algorithm':'plaintext'},{'salt':'invalid!!!'},{'digest':'YQ=='}):
        verifier.write_text(json.dumps(record|update))
        with pytest.raises(ValueError):PasswordVerifier.load(verifier)


def test_ledger_never_loads_unrelated_archived_schema(tmp_path):
    path=tmp_path/'archive.sqlite3'
    with sqlite3.connect(path) as db:db.execute('CREATE TABLE archived_application(id TEXT)')
    before=path.read_bytes()
    with pytest.raises(ValueError,match='different ledger'):Ledger(path)
    assert path.read_bytes()==before


def test_calls_are_persistent_atomic_and_at_most_once(tmp_path):
    ledger=Ledger(tmp_path/'tools.sqlite3')
    payload={'name':'cognesia_models','arguments':{}}
    def reserve(_):
        try:return ledger.reserve('unique-call-request',payload)
        except APIError as error:return error.status
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(reserve,range(8)))
    assert results.count(None)==1 and results.count(409)==7
    ledger.finish('unique-call-request',200,{'result':{'models':[]}})
    restarted=Ledger(tmp_path/'tools.sqlite3')
    assert restarted.reserve('unique-call-request',payload)==(200,{'result':{'models':[]}})
    with pytest.raises(APIError) as error:restarted.reserve('unique-call-request',payload|{'name':'cognesia_sessions'})
    assert error.value.code=='idempotency_conflict'
    assert (tmp_path/'tools.sqlite3').stat().st_mode&0o777==0o600


def test_restart_recovers_unknown_call_without_executing_again(tmp_path):
    ledger=Ledger(tmp_path/'tools.sqlite3');payload={'name':'cognesia_start','arguments':{'options':{'duration_ms':300}}}
    ledger.reserve('interrupted-request',payload)
    ledger=Ledger(tmp_path/'tools.sqlite3');ledger.recover_interrupted()
    status,result=ledger.reserve('interrupted-request',payload)
    assert status==409 and result['error']['code']=='execution_unknown'
    with ledger.connect() as db:
        assert db.execute('SELECT cache_bytes FROM gateway_state').fetchone()[0]<1024


def test_cache_capacity_reserved_atomically_and_expiry_retains_tombstones(tmp_path,monkeypatch):
    import flybrain.public_api as api
    monkeypatch.setattr(api,'MAX_RESULT_BYTES',1024)
    monkeypatch.setattr(api,'MAX_CACHE_BYTES',1500)
    ledger=Ledger(tmp_path/'state');payload={'name':'cognesia_models','arguments':{}}
    ledger.reserve('first-cache-request',payload)
    ledger.finish('first-cache-request',200,{'result':'x'*900})
    with pytest.raises(APIError) as error:ledger.reserve('second-cache-request',payload)
    assert error.value.code=='result_capacity'
    with ledger.connect(write=True) as db:db.execute('UPDATE gateway_calls SET created=0')
    ledger.expire_results()
    status,result=ledger.reserve('first-cache-request',payload)
    assert status==410 and result['error']['code']=='result_expired'
    assert ledger.reserve('second-cache-request',payload) is None
    with ledger.connect() as db:assert db.execute('SELECT cache_bytes FROM gateway_state').fetchone()[0]==1024


def test_metadata_capacity_and_workload_leases_are_bounded(tmp_path,monkeypatch):
    import flybrain.public_api as api
    monkeypatch.setattr(api,'MAX_IDEMPOTENCY_RECORDS',1)
    ledger=Ledger(tmp_path/'state');payload={'name':'cognesia_models','arguments':{}}
    ledger.reserve('first-metadata-key',payload);ledger.finish('first-metadata-key',200,{'result':{}})
    with pytest.raises(APIError) as error:ledger.reserve('second-metadata-key',payload)
    assert error.value.status==503
    ledger.lease_job(100);ledger.lease_job(200);assert ledger.job_deadline()==100
    ledger.lease_job(300,replace=True);ledger.clear_lease(100);assert ledger.job_deadline()==300
    ledger.clear_lease(300);assert ledger.job_deadline() is None


@pytest.mark.parametrize('url',['https://127.0.0.1:8794','http://example.com:8794','http://localhost:8794','http://127.0.0.1:8794/api','http://a:b@127.0.0.1:8794','http://127.0.0.1:8794?url=x','file:///etc/passwd'])
def test_backend_url_cannot_be_used_for_ssrf(url):
    with pytest.raises(ValueError):validate_backend_url(url)


def test_config_requires_real_password_and_https_for_production(tmp_path):
    verifier,_=credentials(tmp_path)
    with pytest.raises(FileNotFoundError):Config(tmp_path/'db',tmp_path/'missing').validate()
    with pytest.raises(ValueError,match='HTTPS'):Config(tmp_path/'db',verifier,production=True).validate()
    with pytest.raises(ValueError):Config(tmp_path/'db',verifier,public_origin='https://user:secret@example.com').validate()
    with pytest.raises(ValueError,match='customer keys'):
        Config(tmp_path/'db',verifier,public_origin='https://api.example.test',production=True).validate()


def test_catalog_routes_no_arbitrary_paths_and_native_step_duration():
    assert len(tool_schemas())>=34
    assert 'cognesia_prepare_model' not in [x['function']['name'] for x in tool_schemas(allow_operator=False)]
    assert build_tool_request('cognesia_command',{'experiment_id':'abc','command':{'action':'step','duration_ms':5}})==('POST','/api/sessions/abc/commands',{'action':'step','duration_ms':5})
    assert build_tool_request('cognesia_read_asset',{'kind':'morphology_overview','id':'100000','asset':'owners.bin','partial':True})[1]=='/api/morphology/assets/overview/100000/partial/owners.bin'
    for name,args in [('shell',{}),('cognesia_model',{'model_id':'../../etc/passwd'}),('cognesia_models',{'url':'http://evil'}),('cognesia_start',{'options':{'contrast':float('nan')}}),('cognesia_neuron',{'index':True,'model_id':'flywire-783'}),('cognesia_read_asset',{'kind':'workspace','id':'abc','asset':'raw.bin'}),('cognesia_command',{'experiment_id':'a','command':{'action':'exec'}})]:
        with pytest.raises(ToolError):validate_tool(name,args)


def test_http_requires_password_even_for_discovery_and_uses_explicit_shared_worker(tmp_path):
    async def scenario():
        verifier,password=credentials(tmp_path);calls=[]
        async def executor(name,args,base_url,**kwargs):calls.append((name,args,base_url));return {'models':[]}
        app=create_app(Config(tmp_path/'db',verifier,backend_url='http://127.0.0.1:18800'),executor=executor)
        async with TestClient(TestServer(app)) as client:
            health=await (await client.get('/health')).json()
            assert health=={'service':'cognesia-tool-api','api_version':1,'authentication':'password','billing':False}
            for path in ('/v1/tools','/v1/access'):
                response=await client.get(path);assert response.status==401
                response=await client.get(path,headers={'Authorization':'Bearer wrong'});assert response.status==401
            headers={'Authorization':'Bearer '+password,'Idempotency-Key':'first-request-key'}
            response=await client.get('/v1/access',headers=headers)
            assert await response.json()=={'authenticated':True,'workspace':'shared_private','billing':False}
            assert (await (await client.get('/v1/tools',headers=headers)).json())['tools']
            body={'name':'cognesia_models','arguments':{}}
            first=await client.post('/v1/tools/call',json=body,headers=headers)
            assert first.status==200 and await first.json()=={'result':{'models':[]}}
            again=await client.post('/v1/tools/call',json=body,headers=headers)
            assert again.status==200 and await again.json()==await first.json()
            assert len(calls)==1 and calls[0][2]=='http://127.0.0.1:18800'
            # A fresh client knowing the same password deliberately shares this worker.
            response=await client.post('/v1/tools/call',json=body,headers={**headers,'Idempotency-Key':'second-request-key'})
            assert response.status==200 and calls[1][2]==calls[0][2]
            response=await client.post('/v1/tools/call',json={'name':'cognesia_models','arguments':{},'session_id':'obsolete'},headers=headers)
            assert response.status==400
            for path in ('/v1/accounts','/v1/sessions','/v1/redeem','/v1/billing/checkout','/v1/billing/webhook'):
                response=await client.post(path,json={},headers=headers);assert response.status==404
            assert response.headers['Cache-Control']=='no-store'
            with app[LEDGER_KEY].connect() as db:
                assert db.execute('SELECT COUNT(*) FROM gateway_calls').fetchone()[0]==2
            assert password.encode() not in (tmp_path/'db').read_bytes()
    asyncio.run(scenario())


def test_http_blocks_rebinding_cross_origin_bad_body_and_unbounded_work(tmp_path):
    async def scenario():
        verifier,password=credentials(tmp_path);calls=[]
        async def executor(*args,**kwargs):calls.append(args);return {}
        app=create_app(Config(tmp_path/'db',verifier),executor=executor)
        async with TestClient(TestServer(app)) as client:
            headers={'Authorization':'Bearer '+password,'Idempotency-Key':'private-request-key'}
            response=await client.get('/health',headers={'Host':'rebinding.invalid'});assert response.status==403
            response=await client.get('/v1/tools',headers={**headers,'Origin':'https://evil.test'});assert response.status==403
            for payload in ({'name':'cognesia_models','arguments':{'url':'file:///etc/passwd'}},{'name':'cognesia_start','arguments':{'options':{'duration_ms':10001}}},{'name':'cognesia_start','arguments':{'options':{'legacy_protocol':{}}}}):
                response=await client.post('/v1/tools/call',json=payload,headers=headers);assert response.status==400
            response=await client.post('/v1/tools/call',json={'name':'cognesia_models','arguments':{}},headers={'Authorization':'Bearer '+password});assert response.status==400
            response=await client.post('/v1/tools/call',data='{}',headers=headers);assert response.status==415
            assert calls==[]
    asyncio.run(scenario())


def test_http_concurrent_retries_dispatch_once_and_errors_are_replayed(tmp_path):
    async def scenario():
        verifier,password=credentials(tmp_path);entered=asyncio.Event();release=asyncio.Event();calls=[]
        async def executor(*args,**kwargs):
            calls.append(args);entered.set();await release.wait();raise ToolError('Worker timed out',504,'backend_unavailable')
        app=create_app(Config(tmp_path/'db',verifier),executor=executor)
        async with TestClient(TestServer(app)) as client:
            headers={'Authorization':'Bearer '+password,'Idempotency-Key':'concurrent-request-key'}
            body={'name':'cognesia_models','arguments':{}}
            task=asyncio.create_task(client.post('/v1/tools/call',json=body,headers=headers));await entered.wait()
            retry=await client.post('/v1/tools/call',json=body,headers=headers);assert retry.status==409
            release.set();first=await task;assert first.status==504
            retry=await client.post('/v1/tools/call',json=body,headers=headers)
            assert retry.status==504 and await retry.json()==await first.json() and len(calls)==1
    asyncio.run(scenario())


def test_start_lease_and_expired_lease_stop_share_the_configured_backend(tmp_path):
    async def scenario():
        verifier,password=credentials(tmp_path);calls=[]
        async def executor(name,args,base_url,**kwargs):calls.append((name,base_url));return {'id':'job_one'}
        app=create_app(Config(tmp_path/'db',verifier,backend_url='http://127.0.0.1:18800'),executor=executor)
        app[LEDGER_KEY].lease_job(time.time()-1)
        async with TestClient(TestServer(app)) as client:
            for _ in range(50):
                if calls:break
                await asyncio.sleep(.01)
            assert calls==[('cognesia_stop_all','http://127.0.0.1:18800')]
            assert app[LEDGER_KEY].job_deadline() is None
            response=await client.post('/v1/tools/call',json={'name':'cognesia_start','arguments':{'options':{'duration_ms':300}}},headers={'Authorization':'Bearer '+password,'Idempotency-Key':'start-experiment-key'})
            assert response.status==200 and 890<app[LEDGER_KEY].job_deadline()-time.time()<=900
    asyncio.run(scenario())


def test_real_http_tools_enforce_ranges_and_disallow_redirects():
    async def scenario():
        app=web.Application()
        async def models(request):return web.json_response({'models':['flywire-783']})
        async def asset(request):
            assert request.headers['Range']=='bytes=2-4'
            return web.Response(body=b'cde',status=206,headers={'Content-Range':'bytes 2-4/6'})
        async def redirect(request):raise web.HTTPFound('http://example.invalid/secret')
        app.router.add_get('/api/models',models);app.router.add_get('/api/runs/a/raw.bin',asset);app.router.add_get('/api/bootstrap',redirect)
        async with TestServer(app) as server:
            base=str(server.make_url('')).rstrip('/')
            assert await execute_tool('cognesia_models',{},base)=={'models':['flywire-783']}
            data=await execute_tool('cognesia_read_asset',{'kind':'run','id':'a','asset':'raw.bin','offset':2,'length':3},base)
            assert data['data']=='Y2Rl' and data['next_offset']==5 and data['eof'] is False
            with pytest.raises(ToolError) as error:await execute_tool('cognesia_bootstrap',{},base)
            assert error.value.code=='backend_redirect'
    asyncio.run(scenario())
