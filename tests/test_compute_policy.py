import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
import threading

import pytest

from flybrain.compute_policy import ComputePolicy, recommend_tier
from flybrain.visual_server import make_handler, VisualState


def inventory(ram=64, cpus=16):
    return {'ram_gb': ram, 'logical_cpus': cpus, 'free_disk_gb': 100}


def test_no_hardware_scan_before_consent_and_revocation_removes_inventory(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr('flybrain.compute_policy.inspect_hardware', lambda root: calls.append(root) or inventory())
    policy = ComputePolicy(tmp_path)
    assert policy.snapshot()['consent'] is None
    assert policy.snapshot()['hardware'] is None
    policy.select({'tier': 'max'})
    assert calls == []
    scanned = policy.consent(True)
    assert scanned['recommended'] == 'max' and len(calls) == 1
    assert ComputePolicy(tmp_path).snapshot()['hardware']['ram_gb'] == 64
    assert len(calls) == 1  # reload reads saved consent without a new scan
    policy.consent(False)
    assert policy.snapshot()['hardware'] is None
    assert policy.snapshot()['tier'] == 'starter'
    assert json.loads(policy.path.read_text())['hardware'] is None


@pytest.mark.parametrize(('ram', 'cpus', 'expected'), [(4,2,'dummy'), (8,2,'starter'), (16,4,'plus'), (32,8,'pro'), (64,16,'max'), (128,32,'ultra'), (256,64,'super')])
def test_tier_recommendations(ram, cpus, expected):
    assert recommend_tier(inventory(ram, cpus)) == expected


def test_memory_reservation_and_operator_limit_are_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr('flybrain.compute_policy.inspect_hardware', lambda root: inventory())
    policy = ComputePolicy(tmp_path, operator_limit_gb=160)
    with pytest.raises(ValueError, match='hardware check'):
        policy.select({'tier':'ultra'})
    policy.consent(True)
    selected = policy.select({'tier':'max', 'agent_reserve_gb':16})
    assert selected['memory_gb'] == 35.2
    assert selected['threads'] == 16
    with pytest.raises(ValueError):
        policy.select({'tier':'max', 'memory_gb':40, 'agent_reserve_gb':16})
    with pytest.raises(ValueError):
        policy.select({'tier':'max', 'threads':17})
    assert policy.snapshot()['memory_gb'] == 35.2  # failed request is atomic
    assert ComputePolicy(tmp_path, operator_limit_gb=160).snapshot()['memory_gb'] == 35.2


@pytest.mark.parametrize('payload', [{'tier':'invented'}, {'threads':True}, {'memory_gb':float('nan')}, {'agent_reserve_gb':1}, {'command':'rm'}, [], {'threads':2.5}])
def test_invalid_compute_input_rejected(tmp_path, payload):
    with pytest.raises(ValueError):
        ComputePolicy(tmp_path).select(payload)


def test_dummy_refuses_runs_and_tier_caps_api_threads(tmp_path):
    policy = ComputePolicy(tmp_path)
    assert policy.apply({'threads':16, 'neural_overrides':{'seed':7}},16) == {'threads':2,'neural_overrides':{'seed':7}}
    assert policy.apply({'threads':16},1)['threads'] == 1
    policy.select({'tier':'dummy'})
    with pytest.raises(ValueError, match='inspection only'):
        policy.apply({},16)


def test_started_job_records_and_enforces_compute_policy(tmp_path):
    state = VisualState.__new__(VisualState)
    state.root = tmp_path; state.anatomy = {'neuron_count':10}; state.lock = threading.Lock()
    state.jobs = {}; state.futures = {}; state.compute_policy = ComputePolicy(tmp_path)
    state.options = lambda *args: {'threads': 16}
    state.executor = SimpleNamespace(submit=lambda *args: None)
    job = state.start({})
    assert job['options']['threads'] <= 2
    assert job['compute_policy']['tier'] == 'starter'


def test_http_consent_origin_busy_and_range(tmp_path, monkeypatch):
    scanned = []
    monkeypatch.setattr('flybrain.compute_policy.inspect_hardware', lambda root: scanned.append(True) or inventory())
    state = SimpleNamespace(root=tmp_path, compute_policy=ComputePolicy(tmp_path), lock=threading.Lock(),
                            _reload_busy_locked=lambda:False)
    directory = tmp_path / 'runs' / 'example'; directory.mkdir(parents=True)
    (directory / 'raw.bin').write_bytes(b'0123456789')
    server = ThreadingHTTPServer(('127.0.0.1',0), make_handler(state))
    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    client = HTTPConnection('127.0.0.1',server.server_port)
    def request(method,path,body=None,headers=None):
        client.request(method,path,body,{'X-Cognesia-Internal':state.access.capability, **(headers or {})})
        response = client.getresponse()
        return response.status,dict(response.getheaders()),response.read()
    try:
        assert request('GET','/api/compute')[0] == 200 and not scanned
        assert request('GET','/api/compute',headers={'Host':'rebinding.invalid'})[0] == 403
        assert request('GET','/api/compute',headers={'Origin':'https://bad.test'})[0] == 403
        assert request('GET','/ws/sessions/private',headers={'Host':'rebinding.invalid'})[0] == 403
        assert request('POST','/api/compute/consent','{"granted":true}',{'Origin':'https://bad.test'})[0] == 403
        assert not scanned
        status,_,body = request('POST','/api/compute/consent','{"granted":true}')
        assert status == 200 and json.loads(body)['recommended'] == 'max' and scanned
        state._reload_busy_locked = lambda:True
        assert request('POST','/api/compute/profile','{"tier":"max"}')[0] == 409
        assert state.compute_policy.snapshot()['tier'] == 'starter'
        status,headers,body = request('GET','/api/runs/example/raw.bin',headers={'Range':'bytes=2-5'})
        assert status == 206 and body == b'2345'
        assert headers['Content-Range'] == 'bytes 2-5/10'
        assert request('GET','/api/runs/example/raw.bin',headers={'Range':'bytes=-3'})[2] == b'789'
        for invalid in ['bytes=99-100','bytes=5-2','bytes=-0','bytes=1-2,3-4','garbage']:
            assert request('GET','/api/runs/example/raw.bin',headers={'Range':invalid})[0] == 416
        assert request('GET','/api/runs/example/raw.bin')[2] == b'0123456789'
    finally:
        client.close();server.shutdown();server.server_close();thread.join()


def test_large_memory_guard_requires_sufficient_physical_ram(monkeypatch):
    from flybrain.memguard import MemoryGuard
    monkeypatch.setattr('flybrain.memguard.psutil.virtual_memory',lambda:SimpleNamespace(total=64e9))
    with pytest.raises(ValueError,match='80%'):
        MemoryGuard(80)
    monkeypatch.setattr('flybrain.memguard.psutil.virtual_memory',lambda:SimpleNamespace(total=256e9))
    assert MemoryGuard(160).limit == 160_000_000_000
    for value in [True,float('nan'),float('inf'),0,1025]:
        with pytest.raises(ValueError): MemoryGuard(value)
