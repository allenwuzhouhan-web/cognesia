"""HTTP acceptance tests for personal-key gating; no live credentials or gateway."""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from flybrain.app_access import AppAccess, AccessError, access_url, verify_personal_key, internal_capability, normalize_access
from flybrain.visual_server import make_handler

KEY = 'test_personal_access_key_never_shipped'


def approval(customer='alice', scopes=None):
    return {'authenticated':True, 'authentication':'customer_key', 'customer':{'id':customer},
        'workspace':{'id':customer + '-workspace'}, 'scopes':scopes or ['read','run'],
        'expires_at':datetime.fromtimestamp(time.time()+3600, timezone.utc).isoformat()}


@contextmanager
def gateway():
    settings = {'approval':approval(), 'status':200, 'seen':[]}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            settings['seen'].append((self.path, self.headers.get('Authorization')))
            status = settings['status'] if self.headers.get('Authorization') == 'Bearer ' + KEY else 401
            self.send_response(status)
            if status == 302: self.send_header('Location', '/stolen')
            body = settings.get('raw', json.dumps(settings['approval']).encode())
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1/access', settings
    finally:
        server.shutdown(); server.server_close(); thread.join()


@contextmanager
def viewer(tmp_path, endpoint=''):
    access = AppAccess(tmp_path, endpoint=endpoint)
    stops = []
    def stop_all():
        stops.append(1); return {'status':'stopped'}
    state = SimpleNamespace(root=tmp_path, stop_all=stop_all,
        compute_policy=SimpleNamespace(snapshot=lambda:{'ok':True}),
        jobs={'one':{'id':'one','status':'complete'}}, lock=threading.Lock(), frames={})
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(state, access=access))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    def request(method, path, body=None, headers=None):
        client = HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        try:
            client.request(method, path, body=body, headers=headers or {})
            response = client.getresponse()
            data = response.read() if response.status != 101 else b''
            return response.status, dict(response.getheaders()), data
        finally: client.close()
    try: yield SimpleNamespace(access=access, state=state, url=base, request=request, stops=stops)
    finally:
        server.shutdown(); server.server_close(); thread.join()


def signin(v):
    status, headers, body = v.request('POST','/auth/login',json.dumps({'key':KEY}),
        {'Origin':v.url,'Content-Type':'application/json','X-Cognesia-Login':'1'})
    assert status == 200, body
    data = json.loads(body)
    return {'Cookie':headers['Set-Cookie'].split(';')[0], 'Origin':v.url,
            'Content-Type':'application/json','X-Cognesia-CSRF':data['csrf']}, data, headers


@pytest.mark.parametrize('value', ['http://public.example/v1/access','https://example.com/redirect',
    'https://user:secret@example.com/v1/access','https://example.com/v1/access?x=1',
    'https://192.168.1.2/v1/access','https://169.254.169.254/v1/access',
    'https://224.0.0.1/v1/access','https://[fc00::1]/v1/access'])
def test_endpoint_rejects_unsafe_operator_configuration(value):
    with pytest.raises(ValueError): access_url(value)


def test_http_loopback_is_explicit_and_remote_https_is_exact():
    with pytest.raises(ValueError): access_url('http://127.0.0.1:8796/v1/access')
    assert access_url('http://127.0.0.1:8796/v1/access',allow_loopback_http=True)
    assert access_url('https://access.example/v1/access')


def test_gateway_no_redirect_no_proxy_bounded_response(monkeypatch):
    monkeypatch.setenv('http_proxy','http://127.0.0.1:1')
    with gateway() as (url, settings):
        assert verify_personal_key(url, KEY)['customer_id'] == 'alice'
        settings['status']=302
        with pytest.raises(AccessError): verify_personal_key(url, KEY)
        assert all(path == '/v1/access' for path, _ in settings['seen'])
        settings['status']=200; settings['raw']=b'x'*16385
        with pytest.raises(AccessError, match='too large'): verify_personal_key(url, KEY)
        settings['raw']=b'not-json'
        with pytest.raises(AccessError): verify_personal_key(url, KEY)
        settings.pop('raw'); settings['approval']={'authenticated':True,'workspace':'shared_private'}
        with pytest.raises(AccessError): verify_personal_key(url, KEY)


def test_every_data_route_requires_access_even_without_service_configuration(tmp_path):
    with viewer(tmp_path) as v:
        assert v.request('GET','/api/health')[0] == 200
        assert v.request('GET','/auth/login')[0] == 200
        assert v.request('GET','/')[0] == 302
        for method,path in [('GET','/api/bootstrap'),('GET','/app.js'),('HEAD','/app.js'),
            ('GET','/api/runs/a/raw.bin'),('GET','/api/workspace-sessions/a/download'),
            ('GET','/ws/sessions/one'),('GET','/api/live-reload')]:
            assert v.request(method,path)[0] == 401, (method,path)
        assert v.request('POST','/api/stop-all','{}',{'Origin':v.url,'Content-Type':'application/json'})[0] == 401
        assert not v.stops
        assert v.request('POST','/auth/login',json.dumps({'key':KEY}),
            {'Origin':v.url,'Content-Type':'application/json','X-Cognesia-Login':'1'})[0] == 503


def test_real_key_login_protects_mutations_streams_assets_and_native_fetch(tmp_path, monkeypatch):
    monkeypatch.setenv('COGNESIA_ACCESS_ALLOW_LOOPBACK_HTTP','1')
    with gateway() as (url, settings), viewer(tmp_path, url) as v:
        headers, session, response = signin(v)
        assert 'HttpOnly' in response['Set-Cookie'] and 'SameSite=Strict' in response['Set-Cookie']
        assert KEY not in json.dumps(session) and KEY not in response['Set-Cookie']
        assert v.request('GET','/api/compute',headers=headers)[0] == 200
        assert v.request('HEAD','/app.js',headers=headers)[0] == 200
        status, _, body = v.request('GET','/',headers=headers)
        assert status == 200 and b'/auth/client.js' in body
        assert v.request('POST','/api/stop-all','{}',headers)[0] == 200
        assert len(v.stops) == 1
        bad = dict(headers); bad.pop('X-Cognesia-CSRF')
        assert v.request('POST','/api/stop-all','{}',bad)[0] == 403
        bad = {**headers,'Origin':'http://127.0.0.1:6666'}
        assert v.request('POST','/api/stop-all','{}',bad)[0] == 403
        assert v.request('GET','/api/compute',headers={**headers,'Host':'evil.example'})[0] == 403
        ws = {**headers,'Upgrade':'websocket','Connection':'Upgrade','Sec-WebSocket-Version':'13',
              'Sec-WebSocket-Key':'dGhlIHNhbXBsZSBub25jZQ=='}
        assert v.request('GET','/ws/sessions/one',headers=ws)[0] == 101
        # A denied revalidation removes the entire session, including streams and binaries.
        settings['status']=401
        next(iter(v.access.sessions.values()))['checked_at']=0
        assert v.request('GET','/api/compute',headers=headers)[0] == 401
        assert v.request('GET','/ws/sessions/one',headers=ws)[0] == 401
        assert not v.access.sessions
        assert v.access.revalidate_all() is True
        assert v.access.revalidate_all() is False


def test_read_only_scope_gateway_failure_and_persistent_account_binding(tmp_path, monkeypatch):
    monkeypatch.setenv('COGNESIA_ACCESS_ALLOW_LOOPBACK_HTTP','1')
    with gateway() as (url, settings), viewer(tmp_path, url) as v:
        settings['approval']=approval(scopes=['read'])
        headers, _, _ = signin(v)
        assert v.request('GET','/api/compute',headers=headers)[0] == 200
        assert v.request('POST','/api/stop-all','{}',headers)[0] == 403
        settings['status']=503
        next(iter(v.access.sessions.values()))['checked_at']=0
        assert v.request('GET','/api/compute',headers=headers)[0] == 503
        assert not v.access.sessions
        settings['status']=200; settings['approval']=approval('bob')
        with pytest.raises(AccessError, match='different account'):
            AppAccess(tmp_path, endpoint=url).login(KEY)
        assert KEY not in v.access.binding_path.read_text()


def test_expiry_rate_limits_logout_and_private_capability(tmp_path):
    verifier=lambda url,key: normalize_access(approval())
    access=AppAccess(tmp_path, endpoint='https://access.example/v1/access',verifier=verifier)
    token,_=access.login(KEY)
    access.sessions[token]['expires_at']=0
    with pytest.raises(AccessError): access.session(token)
    assert token not in access.sessions
    for _ in range(5): access.login(KEY)
    with pytest.raises(AccessError) as caught: access.login(KEY)
    assert caught.value.status==429
    assert internal_capability(tmp_path)==access.capability
    assert (tmp_path/'build/private/app-access/internal-capability').stat().st_mode & 0o077 == 0
    with viewer(tmp_path) as v:
        assert v.request('GET','/api/compute',headers={'X-Cognesia-Internal':'wrong'})[0] == 403
        cap={'X-Cognesia-Internal':v.access.capability}
        assert v.request('GET','/api/compute',headers=cap)[0] == 200
        assert v.request('GET','/api/compute',headers={**cap,'Origin':v.url})[0] == 403
        assert v.request('POST','/api/stop-all','{}',{**cap,'X-Cognesia-Scopes':'read'})[0] == 403


def test_research_console_uses_same_viewer_session_and_scope(tmp_path,monkeypatch):
    from flybrain.local_agent import ResearchAgent, create_app
    monkeypatch.setenv('COGNESIA_ACCESS_ALLOW_LOOPBACK_HTTP','1')
    with gateway() as (url, settings), viewer(tmp_path,url) as v:
        headers,_,_=signin(v)
        async def scenario():
            agent=ResearchAgent(viewer_url=v.url,history_dir=tmp_path/'research')
            client=TestClient(TestServer(create_app(agent))); await client.start_server()
            try:
                for path in ('/api/state','/api/history/a','/agent.js','/api/report/a.pdf','/api/figures/a.png'):
                    assert (await client.get(path)).status==401
                assert (await client.get('/api/health')).status==200
                authorized={'Cookie':headers['Cookie']}
                response=await client.get('/api/state',headers=authorized)
                assert response.status==200
                state=await response.json()
                agent_origin=str(client.make_url('')).rstrip('/')
                mutation={**authorized,'Origin':agent_origin,'X-Cognesia-Token':state['csrf']}
                assert (await client.post('/api/configure',json={},headers=mutation)).status==200
                assert agent.viewer_headers['Cookie']==headers['Cookie']
                assert (await client.post('/api/configure',json={},headers={**mutation,'Origin':v.url})).status==403
                settings['approval']=approval(scopes=['read'])
                next(iter(v.access.sessions.values()))['checked_at']=0
                assert (await client.post('/api/configure',json={},headers=mutation)).status==401
                refreshed,_,_=await asyncio.to_thread(signin,v)
                authorized={'Cookie':refreshed['Cookie']}
                assert (await client.post('/api/configure',json={},headers={**mutation,**authorized})).status==403
                settings['status']=401
                next(iter(v.access.sessions.values()))['checked_at']=0
                assert (await client.get('/api/state',headers=authorized)).status==401
            finally: await client.close()
        asyncio.run(scenario())


def test_native_stop_bridge_uses_authenticated_webview():
    source=(Path(__file__).parents[1]/'macos/Sources/Cognesia.swift').read_text()
    stop=source.split('private func emergencyStopAll()',1)[1].split('@objc private func retryConnection()',1)[0]
    assert "fetch('/auth/session')" in stop and 'X-Cognesia-CSRF' in stop
    assert 'callAsyncJavaScript' in stop and 'URLSession' not in stop


def test_logout_invalidates_cookie_without_requiring_run_scope(tmp_path,monkeypatch):
    monkeypatch.setenv('COGNESIA_ACCESS_ALLOW_LOOPBACK_HTTP','1')
    with gateway() as (url, settings), viewer(tmp_path,url) as v:
        settings['approval']=approval(scopes=['read'])
        headers,_,_=signin(v)
        status,response,_=v.request('POST','/auth/logout','{}',headers)
        assert status==200 and 'Max-Age=0' in response['Set-Cookie']
        assert not v.stops and not v.access.sessions
        assert v.request('GET','/api/compute',headers=headers)[0]==401


def test_protected_public_gateway_uses_explicit_private_worker_capability(tmp_path):
    from flybrain.api_credentials import CredentialRegistry
    from flybrain.public_api import Config,create_app
    async def scenario():
        root=tmp_path/'workspace';root.mkdir()
        with viewer(root) as v:
            registry=CredentialRegistry(tmp_path/'registry.sqlite3',create=True)
            output=tmp_path/'key.json'
            registry.issue(customer_id='alice',name='Alice',workspace_id='alice-workspace',backend_url=v.url,
                workspace_root=root,output_file=output,scopes=('read','run'))
            key=json.loads(output.read_text())['api_key']
            client=TestClient(TestServer(create_app(Config(tmp_path/'ledger',auth_mode='customer',credential_registry=registry.path))))
            await client.start_server()
            try:
                headers={'Authorization':'Bearer '+key,'Idempotency-Key':'real-worker-stop-00001'}
                result=await client.post('/v1/tools/call',json={'name':'cognesia_stop_all','arguments':{}},headers=headers)
                assert result.status==200,await result.text()
                assert (await result.json())['result']['status']=='stopped' and len(v.stops)==1
                assert json.loads(v.access.binding_path.read_text())=={'customer_id':'alice','workspace_id':'alice-workspace'}
                assert v.request('POST','/api/stop-all','{}',{'Origin':v.url,'Content-Type':'application/json'})[0]==401
            finally:await client.close()
    asyncio.run(scenario())


def test_private_operator_config_supports_native_launch_without_env(tmp_path,monkeypatch):
    monkeypatch.delenv('COGNESIA_ACCESS_URL',raising=False)
    monkeypatch.delenv('COGNESIA_ACCESS_ALLOW_LOOPBACK_HTTP',raising=False)
    internal_capability(tmp_path,create=True)
    config=tmp_path/'build/private/app-access/config.json'
    config.write_text(json.dumps({'access_url':'http://127.0.0.1:8796/v1/access','allow_loopback_http':True}))
    config.chmod(0o600)
    assert AppAccess(tmp_path).endpoint=='http://127.0.0.1:8796/v1/access'
    config.chmod(0o644)
    with pytest.raises(ValueError,match='private permissions'):AppAccess(tmp_path)
