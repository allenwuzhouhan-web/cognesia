import json
import threading
from pathlib import Path
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from flybrain.stimulation import normalize_lab_options, available_threads
from flybrain.config import parameters
from flybrain.visual_experiment import read_visual_parameters
from flybrain.visual_server import VisualState, make_handler

ROOT = Path(__file__).resolve().parents[1]


def test_request_normalization_can_cross_experiment_boundary():
    canonical = VisualState.options({'stimulus': 'apparent_motion', 'duration_ms': 300,
                                     'apparent_interval_ms': 17, 'direction_deg': -90,
                                     'visual_overrides': {'eye_spacing': 8}})
    actual, _, _, _ = normalize_lab_options(canonical, parameters(ROOT), read_visual_parameters(ROOT))
    assert actual['direction_deg'] == 270
    assert actual['eye_spacing_deg'] == 8
    assert actual['apparent_interval_frames'] == 4
    assert actual['threads'] == available_threads()


@pytest.mark.parametrize('payload', [[], {'threads': 64}, {'duration_ms': 50000},
                                    {'contrast': float('nan')}, {'node_indices': [0]},
                                    {'duration_ms': 310}, {'grating_waveform': 'unknown'}])
def test_requests_cannot_bypass_recording_or_resource_limits(payload):
    with pytest.raises(ValueError):
        VisualState.options(payload)


def test_concurrent_simulation_is_rejected_before_submission():
    state = VisualState.__new__(VisualState)
    state.root = ROOT
    state.anatomy = {'neuron_count':138639}
    state.lock = threading.Lock()
    state.jobs = {'first': {'status': 'running'}}
    with pytest.raises(RuntimeError, match='already running'):
        state.start({})


def test_cancelled_job_does_not_run_simulation(monkeypatch):
    state = VisualState.__new__(VisualState)
    state.lock = threading.Lock()
    state.jobs = {'one': {'status':'queued', 'progress':0, 'cancel_requested':True}}
    def unexpected(*args, **kwargs):
        pytest.fail('Cancelled work must stop before expensive computation')
    monkeypatch.setattr('flybrain.visual_experiment.run_visual_experiment', unexpected)
    state._run('one', {})
    assert state.jobs['one']['status'] == 'cancelled'


def test_lab_request_preserves_electrode_for_second_normalization():
    electrode = {'target': {'kind':'indices', 'indices':[4]}, 'voltage_mv':25,
                 'frequency_hz':50, 'duty_percent':25}
    canonical = VisualState.options({'duration_ms':1200, 'record_dt_ms':10,
                                     'neural_overrides':{'dt':.05}, 'electrodes':[electrode]})
    normalized, p, _, estimate = normalize_lab_options(canonical,parameters(ROOT),read_visual_parameters(ROOT))
    assert p['dt'] == .05 and estimate['neural_steps_per_branch'] == 24000
    assert normalized['electrodes'][0]['voltage_mv'] == 25
    assert normalized['electrodes'][0]['end_ms'] == 1200
    assert canonical['electrodes'] == [electrode]


def test_machine_cpu_measurement_uses_shared_deltas_across_http_threads(monkeypatch):
    from collections import namedtuple
    Times = namedtuple('Times', 'user system idle')
    state = VisualState.__new__(VisualState)
    state.lock = threading.Lock()
    state.previous_cpu_times = Times(1, 1, 8)
    state.resource_sample = None
    state.resource_time = 0
    state.memory_limit_gb = 40
    state.jobs = {}
    state.process = SimpleNamespace(cpu_percent=lambda:600, memory_info=lambda:SimpleNamespace(rss=10**9),children=lambda recursive:[])
    monkeypatch.setattr('flybrain.visual_server.psutil.cpu_times', lambda:Times(5, 2, 13))
    reading = state.resources()
    assert reading['cpu_percent'] == 50
    assert reading['process_cpu_percent'] == 600
    assert reading['rss_gb'] == 1


def test_resource_readings_include_and_reuse_simulation_children(monkeypatch):
    from collections import namedtuple
    Times=namedtuple('Times','user system idle')
    state=VisualState.__new__(VisualState)
    state.lock=threading.Lock();state.previous_cpu_times=Times(1,1,8)
    state.resource_sample=None;state.resource_time=0;state.memory_limit_gb=40;state.jobs={}
    original=SimpleNamespace(pid=123,cpu_percent=lambda:300,memory_info=lambda:SimpleNamespace(rss=15*10**8),is_running=lambda:True)
    recreated=SimpleNamespace(pid=123,cpu_percent=lambda:0,memory_info=lambda:SimpleNamespace(rss=15*10**8))
    state.resource_children={123:original}
    state.process=SimpleNamespace(cpu_percent=lambda:600,memory_info=lambda:SimpleNamespace(rss=10**9),children=lambda recursive:[recreated])
    monkeypatch.setattr('flybrain.visual_server.psutil.cpu_times',lambda:Times(5,2,13))
    reading=state.resources()
    assert reading['rss_gb']==2.5 and reading['process_cpu_percent']==900
    assert reading['worker_process_count']==1
    assert state.resource_children[123] is original


def test_http_restricts_mutation_origin_and_file_routes(tmp_path):
    state = SimpleNamespace(root=tmp_path)
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HTTPConnection('127.0.0.1', server.server_port)
    try:
        client.request('GET', '/api/health')
        response = client.getresponse()
        assert response.status == 200
        assert json.load(response)['service'] == 'flybrain-visual'
        client.request('POST', '/api/simulate', '{}', {'Origin': 'https://example.com'})
        response = client.getresponse()
        assert response.status == 403
        response.read()
        for path in ['/api/runs/%2E%2E/summary.json', '/%2E%2E/config/parameters.yaml',
                     '/api/runs/a/activity.npz', '/api/anatomy/neurons.parquet']:
            client.request('GET', path)
            response = client.getresponse()
            assert response.status in (400, 404)
            response.read()
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join()


def test_eye_source_is_recovered_from_cached_archive_and_hash_bound(tmp_path):
    import gzip
    from flybrain.visual_setup import ensure_column_data
    directory = tmp_path / 'data/raw/codex'
    directory.mkdir(parents=True)
    source = b'root_id,hemisphere,type,column_id,p,q,x,y\n720575940000000001,left,Mi1,1,0,0,0,0\n'
    with gzip.open(directory / 'column_assignment.csv.gz', 'wb') as file:
        file.write(source)
    target = ensure_column_data(tmp_path)
    assert target.read_bytes() == source
    assert ensure_column_data(tmp_path) == target
    target.write_bytes(source.replace(b'left', b'right'))
    with pytest.raises(ValueError, match='changed'):
        ensure_column_data(tmp_path)


def test_neuromod_scenario_preserves_the_original_stimulus_contract():
    canonical=VisualState.options({'stimulus':'flash','duration_ms':300,
        'neuromod':{'enabled':True,'scenario':'starved','plasticity_enabled':False}})
    assert canonical['stimulus']=='flash'
    assert canonical['neuromod']['enabled'] is True
    assert canonical['neuromod']['initial_state']['energy']==0
    assert canonical['neuromod']['plasticity_enabled'] is False
    original={key:value for key,value in canonical.items() if key!='neuromod'}
    actual,*_=normalize_lab_options(original,parameters(ROOT),read_visual_parameters(ROOT))
    assert actual['duration_ms']==300


@pytest.mark.parametrize('options',[{'enabled':'yes'},{'scenario':'invented'},
    {'initial_state':{'hydration':float('nan')}},{'feeding':2},{'chemical_overrides':{}}])
def test_chemical_request_uses_the_scientific_normalizer(options):
    with pytest.raises(ValueError):VisualState.options({'neuromod':options})


def test_cache_clear_is_strictly_limited_to_regenerable_displays(tmp_path):
    from flybrain.visual_server import clear_viewer_cache,CACHE_DIRECTORIES
    protected=['data/raw/source.csv','config/parameters.yaml','build/validation_neuromod_state.json',
               'build/visual/eye_assignments.parquet','build/visual/morphology/vertices.bin',
               'build/visual/morphology/manifest.json','runs/recorded/activity.npz']
    for name in protected+[name+'/display.bin' for name in CACHE_DIRECTORIES]:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'keep or regenerate')
    result=clear_viewer_cache(tmp_path)
    assert result['deleted']==list(CACHE_DIRECTORIES) and result['bytes_removed']>0
    assert all((tmp_path/name).read_bytes()==b'keep or regenerate' for name in protected)
    assert all(not (tmp_path/name).exists() for name in CACHE_DIRECTORIES)


def test_cache_clear_rejects_symlink_to_recordings_before_removing_anything(tmp_path):
    from flybrain.visual_server import clear_viewer_cache
    (tmp_path/'runs/precious').mkdir(parents=True)
    (tmp_path/'runs/precious/recording').write_text('recorded')
    (tmp_path/'build/visual').mkdir(parents=True)
    (tmp_path/'build/visual/anatomy').symlink_to(tmp_path/'runs/precious',target_is_directory=True)
    with pytest.raises(ValueError,match='Unsafe'):clear_viewer_cache(tmp_path)
    assert (tmp_path/'runs/precious/recording').read_text()=='recorded'


@pytest.mark.parametrize('simulation,morphology',[(True,False),(False,True)])
def test_cache_clear_refuses_active_writers(tmp_path,simulation,morphology):
    state=VisualState.__new__(VisualState);state.root=tmp_path
    state.lock=threading.Lock();state.cache_lock=threading.RLock()
    state.jobs={'a':{'status':'running'}} if simulation else {}
    state.morphology_job={'status':'running'} if morphology else None
    with pytest.raises(RuntimeError,match='Stop simulations'):state.clear_cache()


def test_cache_clear_waits_for_terminal_job_process_to_actually_exit(tmp_path):
    state=VisualState.__new__(VisualState);state.root=tmp_path
    state.lock=threading.Lock();state.cache_lock=threading.RLock();state.morphology_job=None
    state.jobs={'a':{'status':'failed'}}
    state.processes={'a':SimpleNamespace(is_alive=lambda:True)}
    with pytest.raises(RuntimeError,match='Stop simulations'):state.clear_cache()


@pytest.mark.parametrize('status',['running','failed'])
def test_stop_all_terminates_an_uncooperative_worker_within_bounded_time(status):
    import multiprocessing,time
    worker=multiprocessing.get_context('spawn').Process(target=time.sleep,args=(60,))
    worker.start()
    state=VisualState.__new__(VisualState);state.lock=threading.Lock()
    state.asset_cancel=threading.Event();state.morphology_cancel=threading.Event();state.morphology_job=None
    state.jobs={'sleeping':{'status':status,'cancel_requested':False}}
    state.processes={'sleeping':worker}
    try:
        before=time.monotonic();result=state.stop_all()
        assert time.monotonic()-before<3
        assert not worker.is_alive()
        assert result['status']=='stopped' and result['active_jobs']==0
        assert state.jobs['sleeping']['status']=='cancelled'
        assert result['recordings_preserved'] is True
    finally:
        if worker.is_alive():worker.kill()
        worker.join(timeout=1)


def test_static_assets_ignore_stale_conditional_cache_headers():
    state=SimpleNamespace()
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(state))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    client=HTTPConnection('127.0.0.1',server.server_port)
    try:
        client.request('GET','/app.js',headers={'If-Modified-Since':'Wed, 01 Jan 2099 00:00:00 GMT'})
        response=client.getresponse()
        assert response.status==200
        assert 'no-store' in response.getheader('Cache-Control')
        assert response.read()
    finally:
        client.close();server.shutdown();server.server_close();thread.join()
