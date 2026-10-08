"""Actual HTTP loop tests with deterministic stand-in model and gateway servers."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from flybrain.local_agent import AgentError, ResearchAgent, create_app, endpoint_url, tool_budget, compact_context

TOOLS = [{'type':'function','function':{'name':'cognesia_models','description':'Read model evidence',
    'parameters':{'type':'object','properties':{},'additionalProperties':False}}}]


def completion(content=None, calls=None, finish='stop'):
    return {'choices':[{'finish_reason':finish,'message':{'role':'assistant','content':content,
                                                        'tool_calls':calls or []}}]}


def call(identity='call-one', name='cognesia_models', arguments=None):
    return {'id':identity,'type':'function','function':{'name':name,'arguments':json.dumps(arguments or {})}}


async def authorized_console(agent=None):
    viewer = web.Application()
    async def session(request):
        if request.headers.get('Cookie') != 'test_session=authorized':
            return web.json_response({'error':'unauthorized'}, status=401)
        return web.json_response({'authenticated':True, 'csrf':'viewer-csrf', 'scopes':['read','run'],
            'customer':{'id':'test'}, 'workspace':{'id':'test'}})
    viewer.router.add_get('/auth/session', session)
    server = TestServer(viewer); await server.start_server()
    agent = agent or ResearchAgent()
    agent.viewer_url = str(server.make_url('')).rstrip('/')
    client = TestClient(TestServer(create_app(agent)), headers={'Cookie':'test_session=authorized'})
    await client.start_server()
    return client, server


async def fixtures(*, replies=None, report_replies=None, rate_limited=False, echo_password=False, unsupported=False, model_id='gpt-oss-20b', slow=False):
    history, sent, endpoints = [], [], []
    report_history = []
    waiting = asyncio.Event()
    model = web.Application()
    async def models(_):
        return web.json_response({'data':[{'id':model_id}]})
    async def chat(request):
        payload = await request.json()
        if payload['tools'][0]['function']['name'] == 'cognesia_connection_probe':
            result = completion('Tools disabled') if unsupported else completion(calls=[call('probe','cognesia_connection_probe',{'ok':True})])
            return web.json_response(result)
        if payload['tools'][0]['function']['name'] == 'cognesia_write_report':
            report_history.append(payload)
            context = next(m['content'].split('Report context: ', 1)[1] for m in payload['messages'] if 'Report context: ' in (m.get('content') or ''))
            evidence_ids = json.loads(context)['evidence_ids']
            paper = {'title': 'Readiness inspection', 'abstract': 'The model was inspected.',
                'methodology': {'experimental_design':'No simulations were started.', 'experimental_units':'No live organisms.', 'control':'No intervention was tested.'},
                'data': 'Tool observations were returned.',
                'analysis': {'interpretation':'Readiness was inspected.','limitations':'Biological validation remains unestablished.'},
                'futures': {'next_experiments':'Inspect stability.','generalization':'Validate biology before generalizing.'}, 'evidence_ids': evidence_ids}
            reply = report_replies[len(report_history)-1] if report_replies and len(report_history) <= len(report_replies) else completion(calls=[call('paper','cognesia_write_report',paper)])
            return web.json_response(reply)
        history.append(payload)
        waiting.set()
        if slow:
            await asyncio.sleep(0.4)
        reply = replies[len(history)-1] if replies and len(history) <= len(replies) else completion('Observed evidence; biological validation is not established.')
        return web.json_response(reply)
    model.router.add_get('/v1/models',models)
    model.router.add_post('/v1/chat/completions',chat)
    @web.middleware
    async def authentication(request, handler):
        endpoints.append(request.path)
        if request.headers.get('Authorization') != 'Bearer cg_test_password':
            return web.json_response({'error':'Wrong workspace password'}, status=401)
        return await handler(request)
    gateway = web.Application(middlewares=[authentication])
    async def catalog(_):return web.json_response({'tools':TOOLS})
    async def access(_):return web.json_response({'authenticated':True,'workspace':'shared_private','billing':False})
    async def invoke(request):
        payload = await request.json()
        assert set(payload) == {'name','arguments'}
        sent.append((payload,request.headers['Idempotency-Key']))
        if rate_limited:return web.json_response({'error':'Request rate limit reached'},status=429)
        return web.json_response({'result':{'model':'flywire-783','valid':False,'seed':17,
                                           'note':'cg_test_password' if echo_password else 'recorded evidence'}})
    gateway.router.add_get('/v1/tools',catalog)
    gateway.router.add_get('/v1/access',access)
    gateway.router.add_post('/v1/tools/call',invoke)
    ms, gs = TestServer(model), TestServer(gateway)
    await ms.start_server(); await gs.start_server()
    agent = ResearchAgent(model_url=str(ms.make_url('/v1')),gateway_url=str(gs.make_url('')))
    agent.configure({'mode':'gateway','api_password':'cg_test_password'})
    await agent.open()
    return SimpleNamespace(agent=agent,ms=ms,gs=gs,history=history,sent=sent,endpoints=endpoints,waiting=waiting,report_history=report_history)


async def close(f):
    await f.agent.close(); await f.ms.close(); await f.gs.close()


def test_http_multi_round_password_tool_loop_uses_only_workspace_endpoints():
    async def scenario():
        f=await fixtures(replies=[completion(calls=[call('one')]),completion(calls=[call('two')]),
                                 completion('Two returned observations; validation remains failed.')])
        try:
            await f.agent.connect()
            f.agent.start({'prompt':'Inspect models twice and report limitations','max_calls':4})
            await f.agent.task
            run=f.agent.run
            assert run['status']=='completed' and run['calls_used']==2
            assert len(f.sent)==2
            assert f.endpoints==['/v1/tools','/v1/access','/v1/tools/call','/v1/tools/call']
            assert len({item[1] for item in f.sent})==2
            assert f.history[1]['messages'][-1]['role']=='tool'
            assert json.loads(f.history[1]['messages'][-1]['content'])['valid'] is False
            assert f.history[1]['messages'][-2]['tool_calls'][0]['id']=='one'
            assert all(request['parallel_tool_calls'] is False for request in f.history)
            assert f.agent.state()['password_present']
            assert not {'account','calls_remaining','session_id','key_present'}.intersection(f.agent.state())
            assert 'cg_test_password' not in json.dumps(f.agent.state())
            assert 'cg_test_password' not in json.dumps(f.history)
            f.agent.start({'prompt':'Summarize the validation boundary','max_calls':1})
            await f.agent.task
            assert len(f.endpoints)==4
        finally:await close(f)
    asyncio.run(scenario())


def test_hard_budget_stops_a_model_batch_at_one_call():
    async def scenario():
        f=await fixtures(replies=[completion(calls=[call('one'),call('two')]),completion('One call completed.')])
        try:
            await f.agent.connect();f.agent.start({'prompt':'Inspect','max_calls':1});await f.agent.task
            assert len(f.sent)==1
            assert f.agent.run['calls_used']==1 and f.agent.run['status']=='budget_reached'
            assert f.history[1]['tool_choice']=='none'
            assert len([m for m in f.history[1]['messages'] if m['role']=='tool'])==2
        finally:await close(f)
    asyncio.run(scenario())


@pytest.mark.parametrize('value', [0, -1, True, False, 1.5, 'unlimited', float('inf')])
def test_tool_budget_rejects_ambiguous_or_invalid_limits(value):
    with pytest.raises(AgentError, match='positive integer'):
        tool_budget(value)


def test_unlimited_and_large_explicit_tool_budgets():
    assert tool_budget(None) is None
    assert tool_budget(250) == 250


def test_unlimited_runs_past_old_call_and_context_limits_then_writes_a_report(tmp_path):
    from flybrain.research_history import ResearchHistory
    async def scenario():
        # Enough actual mock-HTTP rounds to cross the old 50-call cap and the
        # context ceiling. Every full response must remain in the saved trace.
        count = 220
        f = await fixtures(replies=[completion(calls=[call(f'call-{i:03}')]) for i in range(count)]
                           + [completion('All requested observations are complete.')])
        f.agent.history = ResearchHistory(tmp_path)
        try:
            await f.agent.connect()
            f.agent.start({'prompt':'Inspect the requested evidence until finished.', 'max_calls':None})
            await f.agent.task
            run = f.agent.run
            assert run['status'] == 'completed' and run['calls_used'] == count
            assert len(f.sent) == count and run['max_calls'] is None
            assert all(request['tool_choice'] == 'auto' for request in f.history)
            assert 'unlimited' in f.history[0]['messages'][0]['content']
            assert run['context_exchanges_archived'] > 0
            for request in f.history:
                pending = set()
                for message in request['messages']:
                    if message['role'] == 'assistant':
                        assert not pending
                        pending.update(c['id'] for c in message.get('tool_calls', []))
                    if message['role'] == 'tool':
                        assert message['tool_call_id'] in pending
                        pending.remove(message['tool_call_id'])
                assert not pending
                assert len(json.dumps(request['messages'])) <= 52000 - len(json.dumps(f.agent.tools))
            assert run['report'] and len(run['report']['evidence_ids']) == 50
            restored = ResearchHistory(tmp_path).get(run['id'])
            results = [e for e in restored['events'] if e['kind'] == 'tool_result' and e.get('name') != 'cognesia_write_report']
            assert len(results) == count
            assert all(e['result']['model'] == 'flywire-783' for e in results)
            assert restored['max_calls'] is None
        finally: await close(f)
    asyncio.run(scenario())


def test_context_compaction_keeps_batched_calls_and_results_together():
    messages = [{'role':'system','content':'System instructions'}, {'role':'user','content':'Study question'}]
    for i in range(12):
        messages.append({'role':'assistant','content':None,'tool_calls':[call(f'{i}-a'),call(f'{i}-b')]})
        messages.extend({'role':'tool','tool_call_id':f'{i}-{suffix}','content':json.dumps({'data':'x'*500})}
                        for suffix in ('a','b'))
    assert compact_context(messages, 5000) > 0
    assert messages[0]['content'] == 'System instructions' and messages[1]['content'] == 'Study question'
    assert messages[-2]['tool_call_id'] == '11-a' and messages[-1]['tool_call_id'] == '11-b'
    for i, message in enumerate(messages):
        if message['role'] == 'assistant':
            assert {c['id'] for c in message['tool_calls']} == {m['tool_call_id'] for m in messages[i+1:i+3]}


def test_stop_cancels_pending_inference_and_prevents_tool_execution():
    async def scenario():
        f=await fixtures(replies=[completion(calls=[call()])],slow=True)
        try:
            await f.agent.connect();f.agent.start({'prompt':'Inspect'})
            await asyncio.wait_for(f.waiting.wait(),2)
            assert f.agent.run['max_calls'] is None
            await f.agent.stop()
            assert f.agent.run['status']=='cancelled' and not f.sent
            assert 'may continue' in f.agent.run['events'][-1]['message']
        finally:await close(f)
    asyncio.run(scenario())


def test_gateway_rate_limit_stops_without_retry():
    async def scenario():
        f=await fixtures(replies=[completion(calls=[call()])],rate_limited=True)
        try:
            await f.agent.connect();f.agent.start({'prompt':'Inspect'});await f.agent.task
            assert f.agent.run['status']=='rate_limited'
            assert len(f.sent)==1 and len(f.endpoints)==3 and len(f.history)==1
        finally:await close(f)
    asyncio.run(scenario())


@pytest.mark.parametrize('kwargs,message',[({'unsupported':True},'structured tool call'),({'model_id':'another-model'},'not loaded')])
def test_unsupported_models_and_templates_fail_before_gateway_access(kwargs,message):
    async def scenario():
        f=await fixtures(**kwargs)
        try:
            with pytest.raises(AgentError,match=message):await f.agent.connect()
            assert not f.agent.connected and not f.endpoints
            with pytest.raises(AgentError,match='Connect'):f.agent.start({'prompt':'Inspect'})
        finally:await close(f)
    asyncio.run(scenario())


def test_invented_shell_tool_is_never_forwarded():
    async def scenario():
        f=await fixtures(replies=[completion(calls=[call('one','exec_shell',{'command':'echo unsafe'})]),completion('Tool unavailable.')])
        try:
            await f.agent.connect();f.agent.start({'prompt':'Inspect'});await f.agent.task
            assert not f.sent and f.agent.run['calls_used']==0
            assert any(event['kind']=='rejected' for event in f.agent.run['events'])
        finally:await close(f)
    asyncio.run(scenario())


def test_owner_mode_executes_shared_catalog_against_real_mock_viewer():
    async def scenario():
        f=await fixtures(replies=[completion(calls=[call('one')]),completion('Model source recorded.')])
        viewer=web.Application()
        async def health(_):return web.json_response({'service':'flybrain-visual'})
        async def models(_):return web.json_response({'models':[{'id':'flywire-783'}]})
        viewer.router.add_get('/api/health',health);viewer.router.add_get('/api/models',models)
        vs=TestServer(viewer);await vs.start_server()
        try:
            f.agent.viewer_url=str(vs.make_url('')).rstrip('/')
            f.agent.configure({'mode':'owner','api_password':''})
            await f.agent.connect();f.agent.start({'prompt':'Inspect'});await f.agent.task
            assert f.agent.run['status']=='completed' and f.agent.run['calls_used']==1
            assert not f.sent and not f.endpoints
            returned=next(e['result'] for e in f.agent.run['events'] if e['kind']=='tool_result')
            assert returned['models'][0]['id']=='flywire-783'
        finally:await close(f);await vs.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('url',[ 'file:///tmp/model','http://192.168.1.2:8080','http://0.0.0.0:8080',
    'http://example.com:8080','https://example.com','http://user:secret@127.0.0.1:8080',
    'http://127.0.0.1:8080/v1/chat/completions','http://127.0.0.1:8080/?key=secret'])
def test_model_endpoint_cannot_reach_non_loopback_or_arbitrary_paths(url):
    with pytest.raises(AgentError):endpoint_url(url,loopback=True,model=True)


def test_canonical_endpoints_and_private_gateway_rejection():
    assert endpoint_url('http://localhost:8080/',loopback=True,model=True)=='http://127.0.0.1:8080/v1'
    assert endpoint_url('https://api.example.com/')=='https://api.example.com'
    with pytest.raises(AgentError):endpoint_url('https://169.254.169.254')
    with pytest.raises(AgentError):endpoint_url('http://api.example.com')


def test_console_csrf_origin_host_and_uninstalled_state():
    async def scenario():
        client, viewer = await authorized_console()
        try:
            response=await client.get('/api/state');state=await response.json()
            assert not state['connected'] and 'Not connected' in state['connection_message']
            assert response.headers['Cache-Control']=='no-store'
            assert (await client.post('/api/run',json={'prompt':'test'})).status==403
            headers={'X-Cognesia-Token':state['csrf'],'Origin':'https://evil.example'}
            assert (await client.post('/api/configure',json={},headers=headers)).status==403
            assert (await client.get('/api/state',headers={'Host':'evil.example'})).status==403
            assert (await client.post('/api/configure',json={},headers={'X-Cognesia-Token':state['csrf'],'Origin':str(client.make_url('')).rstrip('/')})).status==200
            assert (await client.get('/')).status==200
            assert (await client.get('/agent.js')).status==200
            assert (await client.get('/agent.css')).status==200
        finally:
            await client.close()
            await viewer.close()
    asyncio.run(scenario())


def test_managed_launcher_uses_fixed_argv_and_clears_llama_env(tmp_path,monkeypatch):
    executable=tmp_path/'llama-server';executable.write_text('binary');executable.chmod(0o700)
    model=tmp_path/'gpt-oss-20b.gguf';model.write_bytes(b'GGUFmock')
    captured={}
    def popen(argv,**kwargs):
        captured.update(argv=argv,**kwargs);return SimpleNamespace(poll=lambda:None)
    monkeypatch.setattr('flybrain.local_agent.subprocess.Popen',popen)
    monkeypatch.setenv('LLAMA_ARG_TOOLS','exec_shell_command')
    agent=ResearchAgent();agent.launch_model({'executable':str(executable),'model_file':str(model)})
    assert captured['argv'][0]==str(executable) and '--jinja' in captured['argv']
    assert captured['argv'][captured['argv'].index('--host')+1]=='127.0.0.1'
    assert 'shell' not in captured and 'LLAMA_ARG_TOOLS' not in captured['env']
    assert captured['env']['LLAMA_API_KEY'] == agent.model_api_key
    assert len(agent.model_api_key) >= 43 and agent.model_api_key not in json.dumps(agent.state())
    assert '--cors-origins' in captured['argv'] and '--no-cors-credentials' in captured['argv']
    assert agent.state()['managed_model_running'] and not agent.connected


def test_recoverable_tool_error_is_returned_to_model_with_budget_enforced():
    async def scenario():
        f=await fixtures(replies=[completion(calls=[call('one')]),completion(calls=[call('two')]),completion('The first call failed; the second returned evidence.')])
        try:
            await f.agent.connect()
            original=f.agent.request
            failed=False
            async def request(method,url,**kwargs):
                nonlocal failed
                if url.endswith('/tools/call') and not failed:
                    failed=True
                    raise AgentError('Invalid selection',400)
                return await original(method,url,**kwargs)
            f.agent.request=request
            f.agent.start({'prompt':'Inspect and retain failed calls','max_calls':2})
            await f.agent.task
            assert f.agent.run['status']=='budget_reached' and f.agent.run['calls_used']==2
            assert json.loads(f.history[1]['messages'][-1]['content'])['call_failed']
            assert len(f.sent)==1
        finally:await close(f)
    asyncio.run(scenario())


def test_launcher_paths_are_prefilled_without_running_or_reading_weights(tmp_path,monkeypatch):
    executable=tmp_path/'llama-server';executable.write_text('binary');executable.chmod(0o700)
    model=tmp_path/'gpt-oss-20b-MXFP4.gguf';model.write_bytes(b'GGUFfixture')
    def unexpected(*args,**kwargs):pytest.fail('Providing paths must never launch a process')
    monkeypatch.setattr('flybrain.local_agent.subprocess.Popen',unexpected)
    agent=ResearchAgent(llama_server=executable,model_file=model)
    state=agent.state()
    assert state['launcher_defaults']=={'executable':str(executable),'model_file':str(model)}
    assert state['launcher_readiness']['executable_present']
    assert state['launcher_readiness']['model_file_present']
    assert state['launcher_readiness']['model_file_bytes']==11
    assert state['launcher_readiness']['weights_verified'] is False
    assert not state['connected'] and not state['managed_model_running']
    model.unlink()
    assert agent.state()['launcher_readiness']['model_file_present'] is False


def test_cli_path_defaults_and_explicit_start_are_distinct(monkeypatch,tmp_path):
    from flybrain.local_agent import main
    launched=[];states=[]
    monkeypatch.setattr(ResearchAgent,'launch_model',lambda self,payload:launched.append(dict(payload)))
    def run(app,**kwargs):
        async def start_and_close():
            app.on_startup.freeze()
            await app.startup()
            states.append(next(value for value in app.values() if isinstance(value,ResearchAgent)).state())
            await app.cleanup()
        asyncio.run(start_and_close())
    monkeypatch.setattr('flybrain.local_agent.web.run_app',run)
    executable=str(tmp_path/'llama-server');model=str(tmp_path/'gpt-oss-20b-MXFP4.gguf')
    arguments=['--llama-server',executable,'--model-file',model]
    main(arguments)
    assert not launched
    assert states[-1]['launcher_defaults']['model_file']==model
    main([*arguments,'--start-model'])
    assert launched==[{'executable':executable,'model_file':model}]
    with pytest.raises(SystemExit):main(['--start-model','--model-file',model])


def test_unload_only_stops_owned_model_and_clears_connection():
    async def scenario():
        agent = ResearchAgent()
        calls = []
        agent.process = SimpleNamespace(poll=lambda:None,
            terminate=lambda:calls.append('terminate'), wait=lambda:calls.append('wait'))
        agent.connected = True
        agent.model_api_key = 'private-runtime-key'
        state = await agent.unload_model()
        assert calls == ['terminate','wait']
        assert not state['managed_model_running'] and not state['connected']
        assert agent.model_api_key == '' and agent.managed_model_url is None
        assert 'unloaded' in state['connection_message']
        await agent.unload_model()
        assert calls == ['terminate','wait']
    asyncio.run(scenario())


def test_managed_model_auth_stays_on_exact_owned_routes():
    async def scenario():
        received = []
        app = web.Application()
        async def handle(request):
            received.append((request.path, request.headers.get('Authorization')))
            return web.json_response({'ok': True})
        app.router.add_get('/{tail:.*}', handle)
        server = TestServer(app)
        await server.start_server()
        other_app = web.Application()
        other_app.router.add_get('/{tail:.*}', handle)
        other_server = TestServer(other_app)
        await other_server.start_server()
        agent = ResearchAgent(model_url=str(server.make_url('/v1')))
        await agent.open()
        agent.managed_model_url = agent.model_url
        agent.model_api_key = 'private-runtime-key'
        agent.process = SimpleNamespace(poll=lambda: None, terminate=lambda: None, wait=lambda: None)
        try:
            await agent.request('GET', agent.model_url + '/models')
            await agent.request('GET', agent.model_url + '/models-other')
            agent.configure({'model_url': str(other_server.make_url('/v1'))})
            await agent.request('GET', agent.model_url + '/models')
            assert received == [('/v1/models', 'Bearer private-runtime-key'),
                                ('/v1/models-other', None), ('/v1/models', None)]
            assert 'private-runtime-key' not in json.dumps(agent.state())
        finally:
            await agent.close()
            await server.close()
            await other_server.close()
    asyncio.run(scenario())


def test_native_health_identifies_service_and_viewer_without_credentials():
    async def scenario():
        agent = ResearchAgent(viewer_url='http://127.0.0.1:9024')
        agent.api_password = 'private-workspace-password'
        agent.model_api_key = 'private-model-key'
        client = TestClient(TestServer(create_app(agent)))
        await client.start_server()
        try:
            response = await client.get('/api/health')
            health = await response.json()
            assert response.status == 200
            assert health == {'service':'cognesia-research-agent','status':'ready',
                              'viewer_url':'http://127.0.0.1:9024','access_required':True}
            assert 'csrf' not in health and 'private' not in json.dumps(health)
            assert (await client.get('/api/state')).status == 503
        finally:
            await client.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('password',['','incorrect-workspace-password'])
def test_gateway_requires_password_before_tools_are_available(password):
    async def scenario():
        f = await fixtures()
        try:
            f.agent.configure({'api_password':password})
            with pytest.raises(AgentError) as rejected:
                await f.agent.connect()
            assert rejected.value.status == 401
            assert not f.agent.connected and not f.sent
            assert set(f.endpoints) <= {'/v1/tools'}
        finally:
            await close(f)
    asyncio.run(scenario())


def test_reflected_credentials_never_enter_trace_or_model_context():
    async def scenario():
        f = await fixtures(echo_password=True, replies=[completion(calls=[call('one')]),
                           completion('Reflected cg_test_password and private-model-test-key')])
        f.agent.model_api_key = 'private-model-test-key'
        try:
            await f.agent.connect()
            f.agent.start({'prompt':'Inspect. Accidental pasted credential: cg_test_password', 'max_calls':2})
            await f.agent.task
            for secret in ('cg_test_password','private-model-test-key'):
                assert secret not in json.dumps(f.agent.state())
                assert secret not in json.dumps(f.history)
            result = next(event['result'] for event in f.agent.run['events'] if event['kind']=='tool_result')
            assert result['note']=='[credential redacted]'
            assert f.agent.run['answer']=='Reflected [credential redacted] and [credential redacted]'
            assert f.sent[0][0]=={'name':'cognesia_models','arguments':{}}
        finally:
            await close(f)
    asyncio.run(scenario())


def test_workspace_password_is_bound_to_configured_gateway_and_old_key_field_is_rejected():
    agent = ResearchAgent()
    agent.configure({'mode':'gateway','api_password':'private-workspace-password'})
    assert agent.state()['password_present']
    agent.configure({'gateway_url':'https://new-gateway.example'})
    assert not agent.state()['password_present']
    assert agent.api_password==''
    with pytest.raises(AgentError, match='api_password'):
        agent.configure({'api_key':'legacy-key'})
    agent.configure({'gateway_url':'https://another-gateway.example','api_password':'replacement-password'})
    assert agent.api_password=='replacement-password' and agent.model_api_key==''
