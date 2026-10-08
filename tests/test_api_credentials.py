"""Customer credential lifecycle, tenant routing, scoped replay and worker identity."""
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from flybrain.api_credentials import CredentialError, CredentialRegistry, scope_for_tool, workspace_fingerprint
from flybrain.public_api import (APIError,Config,Ledger,LEDGER_KEY,create_app,initialize_password,main,
                                verify_workspace_backend)


def customer(tmp_path,registry,name='a',scopes=('read',),port=18800):
    root=tmp_path/('workspace-'+name);root.mkdir(exist_ok=True)
    output=tmp_path/('key-'+name+'.json')
    metadata=registry.issue(customer_id='customer-'+name,name='Lab '+name,workspace_id='workspace-'+name,
        backend_url=f'http://127.0.0.1:{port}',workspace_root=root,output_file=output,scopes=scopes)
    return json.loads(output.read_text())['api_key'],metadata,root


def make_registry(tmp_path):return CredentialRegistry(tmp_path/'registry.sqlite3',create=True)


async def permit_workspace(*args):pass


def test_keys_have_256_secret_bits_and_only_verifiers_are_stored(tmp_path):
    registry=make_registry(tmp_path);key,metadata,root=customer(tmp_path,registry)
    prefix,secret=key.split('.')
    assert prefix=='cgnk_'+metadata['key_id'] and len(secret)==43
    import base64
    assert len(base64.urlsafe_b64decode(secret+'='))==32
    principal=registry.authenticate(key)
    assert principal.customer_id=='customer-a' and principal.scopes==('read',)
    assert principal.workspace_fingerprint==workspace_fingerprint(root)
    assert principal.public_access()['workspace']=={'id':'workspace-a'}
    assert 'backend' not in json.dumps(principal.public_access()) and str(root) not in json.dumps(principal.public_access())
    with registry.connect() as db:
        assert db.execute('SELECT verifier FROM customer_keys').fetchone()[0]==hashlib.sha256(key.encode()).hexdigest()
    assert key.encode() not in registry.path.read_bytes()
    assert registry.path.stat().st_mode&0o777==0o600
    assert (tmp_path/'key-a.json').stat().st_mode&0o777==0o600
    listed=json.dumps(registry.list_keys())
    assert key not in listed and 'verifier' not in listed and 'backend' not in listed and str(root) not in listed


def test_immutable_binding_rejects_duplicate_worker_alias_root_and_nested_roots(tmp_path):
    registry=make_registry(tmp_path);key,metadata,root=customer(tmp_path,registry)
    other=tmp_path/'other';other.mkdir()
    nested=root/'nested';nested.mkdir()
    for binding in ({'backend_url':'http://127.0.0.1:18800','workspace_root':other},
                    {'backend_url':'http://127.0.0.2:18800','workspace_root':other},
                    {'backend_url':'http://127.0.0.1:18801','workspace_root':root},
                    {'backend_url':'http://127.0.0.1:18801','workspace_root':nested}):
        with pytest.raises(CredentialError,match='share'):
            registry.issue(customer_id='customer-b',name='Lab b',workspace_id='workspace-b',output_file=tmp_path/'b.json',**binding)
    registry.revoke(metadata['key_id'])
    with pytest.raises(CredentialError,match='share'):
        registry.issue(customer_id='customer-b',name='Lab b',workspace_id='workspace-b',backend_url='http://127.0.0.1:18800',workspace_root=other,output_file=tmp_path/'b.json')
    (other/'runs').symlink_to(root,target_is_directory=True)
    with pytest.raises(CredentialError,match='outside'):
        registry.issue(customer_id='customer-b',name='Lab b',workspace_id='workspace-b',backend_url='http://127.0.0.1:18801',workspace_root=other,output_file=tmp_path/'b.json')
    with pytest.raises(CredentialError,match='immutable'):
        registry.issue(customer_id='customer-a',name='Lab a',workspace_id='changed',backend_url='http://127.0.0.1:18800',workspace_root=root,output_file=tmp_path/'b.json')


def test_rotation_and_revocation_are_atomic_and_output_is_never_overwritten(tmp_path):
    registry=make_registry(tmp_path);key,metadata,root=customer(tmp_path,registry,scopes=('read','run'))
    blocked=tmp_path/'exists.json';blocked.write_text('keep')
    with pytest.raises(FileExistsError):registry.rotate(metadata['key_id'],output_file=blocked)
    assert registry.authenticate(key) and blocked.read_text()=='keep'
    output=tmp_path/'rotated.json';new_metadata=registry.rotate(metadata['key_id'],output_file=output)
    new_key=json.loads(output.read_text())['api_key']
    assert registry.authenticate(new_key).scopes==('read','run')
    with pytest.raises(CredentialError) as error:registry.authenticate(key)
    assert error.value.status==401
    registry.revoke(new_metadata['key_id']);registry.revoke(new_metadata['key_id'])
    with pytest.raises(CredentialError):registry.authenticate(new_key)
    assert {row['status'] for row in registry.list_keys()}=={'revoked'}
    assert registry.list_keys('customer-missing')==[]


def test_invalid_expired_and_revoked_keys_fail_closed_without_revealing_status(tmp_path):
    registry=make_registry(tmp_path);key,metadata,_=customer(tmp_path,registry)
    errors=[]
    for bad in ('',key+'.',key[:-1],key+'x','Bearer '+key,'x'*500,None,'cgnk_'+'0'*32+'.'+'A'*43):
        with pytest.raises(CredentialError) as error:registry.authenticate(bad)
        errors.append((error.value.status,str(error.value)))
    with registry.connect(write=True) as db:db.execute('UPDATE customer_keys SET expires=?',(time.time()-1,))
    with pytest.raises(CredentialError) as error:registry.authenticate(key)
    errors.append((error.value.status,str(error.value)))
    assert len(set(errors))==1
    assert registry.list_keys()[0]['status']=='expired'


def test_scope_validation_defaults_read_and_cli_never_prints_key(tmp_path,capsys):
    root=tmp_path/'workspace';root.mkdir();output=tmp_path/'key.json';registry=tmp_path/'registry'
    command=['--registry',str(registry),'key-issue','--customer','lab','--name','Example Lab','--workspace','lab-main','--backend','http://127.0.0.1:18800','--workspace-root',str(root),'--output',str(output)]
    main(command)
    secret=json.loads(output.read_text())['api_key'];printed=capsys.readouterr().out
    assert secret not in printed and 'verifier' not in printed
    metadata=json.loads(printed);assert metadata['scopes']==['read']
    main(['--registry',str(registry),'key-list']);assert secret not in capsys.readouterr().out
    main(['--registry',str(registry),'key-revoke',metadata['key_id']]);assert secret not in capsys.readouterr().out
    for scopes in (('admin',),('run',),('read','admin')):
        with pytest.raises(CredentialError):
            CredentialRegistry(registry).issue(customer_id='lab',name='Example Lab',workspace_id='lab-main',backend_url='http://127.0.0.1:18800',workspace_root=root,output_file=tmp_path/'new.json',scopes=scopes)
    assert scope_for_tool('cognesia_models')=='read' and scope_for_tool('cognesia_start')=='run'
    assert scope_for_tool('cognesia_prepare_model') is None


def test_customer_config_never_accepts_owner_password_or_maintenance(tmp_path):
    registry=make_registry(tmp_path)
    config=Config(tmp_path/'state',auth_mode='customer',credential_registry=registry.path,production=True,public_origin='https://api.example.test')
    config.validate()  # No owner password file is needed or read.
    with pytest.raises(ValueError,match='registry'):Config(tmp_path/'state',auth_mode='customer').validate()
    with pytest.raises(ValueError,match='maintenance'):Config(tmp_path/'state',auth_mode='customer',credential_registry=registry.path,allow_operator_tools=True).validate()


def test_namespaced_replays_and_stop_leases_never_cross_customers(tmp_path):
    registry=make_registry(tmp_path)
    first=customer(tmp_path,registry,'a',port=18800);second=customer(tmp_path,registry,'b',port=18801)
    principals=[registry.authenticate(item[0]) for item in (first,second)]
    ledger=Ledger(tmp_path/'state');payload={'name':'cognesia_models','arguments':{}}
    for principal in principals:
        ledger.bind(principal.namespace,principal.backend_url,principal.workspace_fingerprint)
        assert ledger.reserve('same-idempotency-key',payload,principal.namespace) is None
        ledger.finish('same-idempotency-key',200,{'result':principal.customer_id},principal.namespace)
        ledger.lease_job(time.time()-1,namespace=principal.namespace)
    for principal in principals:
        assert ledger.replay('same-idempotency-key',payload,principal.namespace)[1]['result']==principal.customer_id
    assert ledger.replay('same-idempotency-key',payload) is None
    jobs=ledger.expired_jobs();assert {job['backend_url'] for job in jobs}=={'http://127.0.0.1:18800','http://127.0.0.1:18801'}
    ledger.clear_lease(namespace=principals[0].namespace)
    assert ledger.job_deadline(principals[1].namespace) is not None
    with pytest.raises(APIError,match='binding'):
        ledger.bind(principals[0].namespace,principals[1].backend_url,principals[1].workspace_fingerprint)


def test_customer_http_identity_scope_and_cross_tenant_replays(tmp_path):
    async def scenario():
        registry=make_registry(tmp_path);key_a,meta_a,_=customer(tmp_path,registry,'a',port=18800)
        key_b,meta_b,_=customer(tmp_path,registry,'b',scopes=('read','run'),port=18801)
        calls=[]
        async def execute(name,args,backend,**kwargs):
            calls.append((name,args,backend))
            if args.get('experiment_id')=='job-from-b' and backend.endswith('18800'):
                from flybrain.api_tools import ToolError
                raise ToolError('Unknown experiment',404,'backend_error')
            return {'workspace_marker':backend.rsplit(':',1)[-1]}
        app=create_app(Config(tmp_path/'state',auth_mode='customer',credential_registry=registry.path),executor=execute,workspace_checker=permit_workspace)
        async with TestClient(TestServer(app)) as client:
            headers_a={'Authorization':'Bearer '+key_a,'Idempotency-Key':'same-idempotency-key'}
            headers_b={'Authorization':'Bearer '+key_b,'Idempotency-Key':'same-idempotency-key'}
            response=await client.get('/v1/access',headers=headers_a);access=await response.json()
            assert access['customer']=={'id':'customer-a','name':'Lab a'} and access['workspace']=={'id':'workspace-a'}
            assert access['scopes']==['read'] and '18800' not in json.dumps(access)
            a_tools=await (await client.get('/v1/tools',headers=headers_a)).json()
            b_tools=await (await client.get('/v1/tools',headers=headers_b)).json()
            assert a_tools['tool_scopes']['cognesia_models']=='read' and 'cognesia_start' not in a_tools['tool_scopes']
            assert b_tools['tool_scopes']['cognesia_start']=='run' and 'cognesia_clear_cache' not in b_tools['tool_scopes']
            body={'name':'cognesia_models','arguments':{}}
            first=await client.post('/v1/tools/call',json=body,headers=headers_a)
            second=await client.post('/v1/tools/call',json=body,headers=headers_b)
            assert (await first.json())['result']['workspace_marker']=='18800'
            assert (await second.json())['result']['workspace_marker']=='18801'
            await client.post('/v1/tools/call',json=body,headers=headers_a);assert len(calls)==2
            for name,args in (('cognesia_start',{'options':{'duration_ms':300}}),('cognesia_stop_all',{}),('cognesia_command',{'experiment_id':'job-from-b','command':{'action':'stop'}})):
                response=await client.post('/v1/tools/call',json={'name':name,'arguments':args},headers={**headers_a,'Idempotency-Key':'blocked-run-request'});assert response.status==403
            response=await client.post('/v1/tools/call',json={'name':'cognesia_clear_cache','arguments':{}},headers=headers_b);assert response.status==403
            response=await client.post('/v1/tools/call',json={'name':'cognesia_session','arguments':{'experiment_id':'job-from-b'}},headers={**headers_a,'Idempotency-Key':'unknown-experiment-id'});assert response.status==404
            assert calls[-1][2].endswith('18800')
            registry.revoke(meta_a['key_id'])
            response=await client.post('/v1/tools/call',json=body,headers=headers_a);assert response.status==401
            with registry.connect(write=True) as db:db.execute('UPDATE customer_keys SET expires=0 WHERE id=?',(meta_b['key_id'],))
            response=await client.post('/v1/tools/call',json=body,headers=headers_b);assert response.status==401
    asyncio.run(scenario())


def test_fresh_scope_changes_block_cached_mutation_and_owner_password_is_rejected(tmp_path):
    async def scenario():
        registry=make_registry(tmp_path);key,metadata,_=customer(tmp_path,registry,scopes=('read','run'))
        output=tmp_path/'owner.json';verifier=tmp_path/'owner-hash.json';initialize_password(verifier,output)
        owner_password=json.loads(output.read_text())['password']
        calls=[]
        async def execute(*args,**kwargs):calls.append(args);return {'id':'run-one'}
        app=create_app(Config(tmp_path/'state',password_file=verifier,auth_mode='customer',credential_registry=registry.path),executor=execute,workspace_checker=permit_workspace)
        async with TestClient(TestServer(app)) as client:
            response=await client.get('/v1/access',headers={'Authorization':'Bearer '+owner_password});assert response.status==401
            headers={'Authorization':'Bearer '+key,'Idempotency-Key':'shared-run-request'}
            body={'name':'cognesia_start','arguments':{'options':{'duration_ms':300}}}
            response=await client.post('/v1/tools/call',json=body,headers=headers);assert response.status==200
            with registry.connect(write=True) as db:db.execute('UPDATE customer_keys SET scopes=? WHERE id=?',(json.dumps(['read']),metadata['key_id']))
            response=await client.post('/v1/tools/call',json=body,headers=headers);assert response.status==403 and len(calls)==1
    asyncio.run(scenario())


def test_worker_health_fingerprint_is_checked_before_dispatch_and_watchdog(tmp_path):
    async def scenario():
        actual_root=tmp_path/'actual';actual_root.mkdir()
        worker=web.Application()
        async def health(request):return web.json_response({'workspace_fingerprint':workspace_fingerprint(actual_root)})
        worker.router.add_get('/api/health',health)
        async with TestServer(worker) as backend:
            registry=make_registry(tmp_path);expected=tmp_path/'expected';expected.mkdir()
            output=tmp_path/'key.json'
            registry.issue(customer_id='a',name='Lab A',workspace_id='a-main',backend_url=str(backend.make_url('')).rstrip('/'),workspace_root=expected,output_file=output,scopes=('read','run'))
            key=json.loads(output.read_text())['api_key'];principal=registry.authenticate(key);calls=[]
            async def execute(*args,**kwargs):calls.append(args);return {}
            app=create_app(Config(tmp_path/'state',auth_mode='customer',credential_registry=registry.path),executor=execute)
            ledger=app[LEDGER_KEY];ledger.bind(principal.namespace,principal.backend_url,principal.workspace_fingerprint)
            ledger.lease_job(time.time()-1,namespace=principal.namespace)
            async with TestClient(TestServer(app)) as client:
                response=await client.post('/v1/tools/call',json={'name':'cognesia_models','arguments':{}},headers={'Authorization':'Bearer '+key,'Idempotency-Key':'mismatch-request-key'})
                assert response.status==503 and calls==[]
                assert ledger.job_deadline(principal.namespace) is not None
                with ledger.connect() as db:assert db.execute('SELECT COUNT(*) FROM gateway_calls').fetchone()[0]==0
    asyncio.run(scenario())


def test_customer_rates_are_isolated_from_anonymous_and_other_customer_requests(tmp_path):
    async def scenario():
        registry=make_registry(tmp_path);key_a,_,_=customer(tmp_path,registry,'a',port=18800);key_b,_,_=customer(tmp_path,registry,'b',port=18801)
        app=create_app(Config(tmp_path/'state',auth_mode='customer',credential_registry=registry.path),workspace_checker=permit_workspace)
        async with TestClient(TestServer(app)) as client:
            for _ in range(31):response=await client.get('/v1/access',headers={'Authorization':'Bearer invalid'})
            assert response.status==429
            for _ in range(121):response=await client.get('/v1/access',headers={'Authorization':'Bearer '+key_a})
            assert response.status==429
            response=await client.get('/v1/access',headers={'Authorization':'Bearer '+key_b})
            assert response.status==200
    asyncio.run(scenario())


def test_watchdog_serializes_expired_stop_before_a_new_start(tmp_path):
    async def scenario():
        registry=make_registry(tmp_path);key,_,_=customer(tmp_path,registry,scopes=('read','run'))
        principal=registry.authenticate(key);checking=asyncio.Event();release=asyncio.Event();events=[]
        async def checker(*args):
            if not checking.is_set():
                checking.set();await release.wait()
        async def execute(name,args,backend,**kwargs):
            events.append(name)
            return {'id':'fresh-experiment'} if name=='cognesia_start' else {'status':'stopping'}
        app=create_app(Config(tmp_path/'state',auth_mode='customer',credential_registry=registry.path),executor=execute,workspace_checker=checker)
        ledger=app[LEDGER_KEY];ledger.bind(principal.namespace,principal.backend_url,principal.workspace_fingerprint)
        ledger.lease_job(time.time()-1,namespace=principal.namespace)
        async with TestClient(TestServer(app)) as client:
            await checking.wait()
            request=asyncio.create_task(client.post('/v1/tools/call',json={'name':'cognesia_start','arguments':{'options':{'duration_ms':300}}},headers={'Authorization':'Bearer '+key,'Idempotency-Key':'fresh-start-request'}))
            await asyncio.sleep(.03)
            assert not request.done() and events==[]
            release.set();response=await request
            assert response.status==200 and events==['cognesia_stop_all','cognesia_start']
            assert ledger.job_deadline(principal.namespace)>time.time()+890
    asyncio.run(scenario())


def test_durable_ledger_refuses_worker_reassignment_even_with_new_registry_identity(tmp_path):
    ledger=Ledger(tmp_path/'state')
    ledger.bind('customer_first','http://127.0.0.1:18800','a'*64)
    with pytest.raises(APIError,match='already owns'):ledger.bind('customer_second','http://127.0.0.2:18800','b'*64)
    with pytest.raises(APIError,match='already owns'):ledger.bind('customer_second','http://127.0.0.1:18801','a'*64)


def test_legacy_owner_cache_and_deadline_migrate_without_replay(tmp_path):
    path=tmp_path/'legacy-state';payload={'name':'cognesia_models','arguments':{}}
    fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    body=json.dumps({'result':{'owner':True}})
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE gateway_calls(key TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,state TEXT NOT NULL,status INTEGER,response TEXT,created REAL NOT NULL,cache_bytes INTEGER NOT NULL DEFAULT 0)')
        db.execute('CREATE TABLE gateway_state(id INTEGER PRIMARY KEY,cache_bytes INTEGER NOT NULL DEFAULT 0,job_deadline REAL)')
        db.execute('INSERT INTO gateway_state VALUES(1,?,1234)',(len(body),))
        db.execute('INSERT INTO gateway_calls VALUES(?,?,?,?,?,?,?)',('existing-owner-key',fingerprint,'complete',200,body,time.time(),len(body)))
    ledger=Ledger(path);assert ledger.replay('existing-owner-key',payload)==(200,{'result':{'owner':True}})
    assert ledger.job_deadline()==1234
    ledger.bind('owner','http://127.0.0.1:8794')
    ledger.bind('customer_new','http://127.0.0.1:18800','a'*64)
    assert ledger.replay('existing-owner-key',payload,'customer_new') is None
