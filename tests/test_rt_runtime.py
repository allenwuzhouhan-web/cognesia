import json
import hashlib
import io
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from flybrain.engine import LIFEngine
from flybrain.neuromod.compartments import CompartmentMap
from flybrain.neuromod.field import FIELD_SPECIES
from flybrain.neuromod.receptors import ReceptorModel,read_receptors
from flybrain.rt.engine_rt import CoreRuntime, FastReceptors, require_plasticity_gate
from flybrain.rt.kernel import advance_compact
from flybrain.rt.protocol import compile_protocol
from flybrain.rt.replay import replay_session

ROOT=Path(__file__).resolve().parents[1]
P={'dt':.1,'v_rest':-52.,'v_reset':-52.,'v_threshold':-45.,'tau_membrane':20.,'tau_synapse':5.,
   'refractory':2.2,'synaptic_delay':1.8,'spike_weight':.275,'poisson_factor':20.,'voltage_min':-90.,'voltage_max':20.}


def receptor_fixture():
    neurons=pd.DataFrame({'root_id':np.arange(5,dtype=np.int64),'cell_type':['KCg','KCab','MBON01','MBON02','PAM01'],
        'cell_class':['KC','KC','MBON','MBON','DAN'],'known_nt':['acetylcholine;sNPF','acetylcholine','gaba','glutamate','dopamine']})
    mapping=CompartmentMap(('g1','g2'),np.array([[1,1,1,0,1],[1,0,0,1,0]],bool),np.zeros((2,2)),
        np.array([-1,-1,0,1,0]),neurons.root_id.to_numpy(),{})
    weights=sparse.csr_matrix(([50.,60.,70.,80.,100.],([2,3,2,4,0],[0,0,1,0,4])),shape=(5,5))
    return ReceptorModel(read_receptors(ROOT/'config/receptors.csv'),neurons,mapping,weights)


def test_compact_receptor_groups_match_independent_full_edge_evaluation():
    model=receptor_fixture(); fast=FastReceptors(model)
    rng=np.random.default_rng(713)
    for c in [np.zeros((8,2)),np.ones((8,2)),rng.uniform(0,5,(8,2)),rng.uniform(0,5,(8,2))]:
        expected=model.evaluate(c); got=fast.evaluate(c)
        for key in ('gain','threshold_factor','tau_factor'):
            np.testing.assert_allclose(getattr(got,key),getattr(expected,key),rtol=0,atol=2e-15)
        np.testing.assert_allclose(got.release[got.release_group],expected.release_factor,rtol=0,atol=2e-15)
    fast.evaluate(c,enabled=False)
    np.testing.assert_array_equal(fast.gain,1)
    np.testing.assert_array_equal(fast.release,1)


def test_compact_disabled_kernel_is_bit_identical_to_base_with_delays_and_duplicate_events():
    weights=sparse.csr_matrix(([700.,-110.,80.],([1,2,0],[0,1,2])),shape=(3,3))
    a=LIFEngine(weights,P,threads=1,clamp=False); b=LIFEngine(weights,P,threads=1,clamp=False)
    inputs=np.array([0],np.int32)
    events=np.array([[0,0],[1,0],[1,0],[25,0],[26,0],[60,0],[61,0]],np.int64)
    expected=a.run(10,inputs,events,record_indices=[0,1,2])
    b.refractory_steps[inputs]=0
    voltage=np.empty((10,3),np.float32)
    indices,steps,position,clamps=advance_compact(b.v,b.g,b.last_spike,b.refractory_steps,b.active,b.firing,
        b.ring,b.ring_counts,b.csc_indptr,b.csc_indices,b.csc_counts,0,100,.1,b.delay_steps,
        np.full(3,b.decay_v),b.decay_g,np.full(3,b.coupling),P['v_rest'],P['v_reset'],np.full(3,P['v_threshold']),
        P['spike_weight'],P['spike_weight']*P['poisson_factor'],inputs,events[:,0],events[:,1].astype(np.int32),0,
        False,-90.,20.,np.arange(3,dtype=np.int32),10,0,voltage,np.ones(3),np.ones(1),np.zeros(3,np.int32),
        np.array([-52.,-52.,0.]))
    np.testing.assert_array_equal(indices,expected['spike_indices'])
    np.testing.assert_array_equal((steps*.1).astype(np.float32),expected['spike_times'])
    np.testing.assert_array_equal(voltage,expected['voltages'])
    for key in ('v','g','last_spike','ring_counts'):
        np.testing.assert_array_equal(getattr(a,key),getattr(b,key))
    assert position==len(events) and clamps==0


@pytest.mark.parametrize('trigger', ['external_input', 'integration'])
def test_voltage_diagnostics_retain_transient_violation_before_spike_reset(trigger):
    b=LIFEngine(sparse.csr_matrix((1,1)),P,threads=1,clamp=False)
    if trigger == 'integration': b.g[:] = 30000.
    events=np.array([0],np.int64) if trigger == 'external_input' else np.empty(0,np.int64)
    diagnostic=np.array([-52.,-52.,0.])
    indices,steps,_,clamps=advance_compact(b.v,b.g,b.last_spike,b.refractory_steps,b.active,b.firing,
        b.ring,b.ring_counts,b.csc_indptr,b.csc_indices,b.csc_counts,0,10,.1,b.delay_steps,
        np.full(1,b.decay_v),b.decay_g,np.full(1,b.coupling),P['v_rest'],P['v_reset'],np.full(1,P['v_threshold']),
        P['spike_weight'],100.,np.array([0],np.int32),events,np.zeros(len(events),np.int32),0,
        False,-90.,20.,np.empty(0,np.int32),10,0,np.empty((1,0),np.float32),np.ones(1),np.ones(1),np.empty(0,np.int32),diagnostic)
    assert len(indices)==1 and clamps==0
    assert b.v[0] == P['v_reset']  # A 1-ms endpoint-only check would miss the violation.
    assert diagnostic[1] > P['voltage_max'] and diagnostic[2] >= 1


def test_saved_frame_elapsed_time_includes_current_advance(monkeypatch):
    runtime=object.__new__(CoreRuntime)
    runtime.engine=SimpleNamespace(step=0,dt=.1,v=np.array([-52.]),g=np.array([0.]))
    runtime.neurons=[0]; runtime.orn_indices=np.array([0]); runtime.cells=np.array(['ORN'])
    runtime.sources={name:np.array([False]) for name in ('DA','OA','5HT')}
    runtime.nm={'max_source_rate_hz_DA':1.,'max_source_rate_hz_OA':1.,'max_source_rate_hz_5HT':1.,'runtime_rate_tau_ms':10.}
    runtime.controls={'odour':'air','intensity':1.,'dan_type':'PAM','dan_drive':0.,'oa_tone':0.,'serotonin_tone':0.,
        'state.enabled':False,'fields.enabled':False,'plasticity.enabled':False}
    runtime.odour=SimpleNamespace(step=lambda *args:np.array([0.]))
    runtime.field=SimpleNamespace(C=np.zeros((1,1)))
    runtime.rates_hz=np.zeros(1); runtime.spike_totals=np.zeros(1,dtype=np.int64)
    runtime._voltage_diagnostics=np.array([-52.,-52.,0.]); runtime.tick_wall_seconds=[]
    runtime.frames=deque(); runtime.frame_counter=0; runtime.record=True; runtime.wall_seconds=0.; runtime.spike_count=0
    runtime._frame_file=io.StringIO(); runtime._spike_files=[io.BytesIO(),io.BytesIO()]
    runtime._spike_hashes=[hashlib.sha256(),hashlib.sha256()]
    runtime._update_effects=lambda:None
    def neural_tick(rates):
        runtime.engine.step+=10
        return np.empty(0,np.int32),np.empty(0,np.int64)
    runtime._neural_tick=neural_tick
    runtime.snapshot=lambda **kwargs:{'elapsed':kwargs.get('wall_seconds',runtime.wall_seconds)}
    clock=iter(np.arange(1000)*.001)
    monkeypatch.setattr('flybrain.rt.engine_rt.time.perf_counter',lambda:next(clock))
    runtime.advance(40)
    frames=[json.loads(line) for line in runtime._frame_file.getvalue().splitlines()]
    assert 0 < frames[0]['elapsed'] < frames[1]['elapsed'] < runtime.wall_seconds


@pytest.fixture
def plasticity_gate_fixture(tmp_path):
    (tmp_path/'config').mkdir(); (tmp_path/'build').mkdir()
    paths={'config_hashes':('config','settings.yaml'),'implementation_hashes':('','implementation.py'),
        'dependency_hashes':('','dependency.json'),'artifact_hashes':('build','curve.csv')}
    gate={'gate':'V-NM-E','status':'PASS','checks':[{'name':'fixture','status':'PASS'}]}
    for field,(folder,name) in paths.items():
        path=tmp_path/folder/name; path.write_text('fixture')
        gate[field]={name:hashlib.sha256(path.read_bytes()).hexdigest()}
    path=tmp_path/'build/validation_neuromod_plasticity.json'
    path.write_text(json.dumps(gate))
    return tmp_path,path,gate


@pytest.mark.parametrize('missing',['gate','checks','config_hashes','implementation_hashes','dependency_hashes','artifact_hashes'])
def test_runtime_rejects_incomplete_plasticity_pass(plasticity_gate_fixture,missing):
    root,path,gate=plasticity_gate_fixture
    require_plasticity_gate(root)
    del gate[missing]; path.write_text(json.dumps(gate))
    with pytest.raises(ValueError): require_plasticity_gate(root)


def test_runtime_rejects_failed_or_stale_plasticity_evidence(plasticity_gate_fixture):
    root,path,gate=plasticity_gate_fixture
    gate['checks'][0]['status']='FAIL'; path.write_text(json.dumps(gate))
    with pytest.raises(ValueError): require_plasticity_gate(root)
    gate['checks'][0]['status']='PASS'; path.write_text(json.dumps(gate))
    (root/'build/curve.csv').write_text('changed')
    with pytest.raises(ValueError,match='Stale'): require_plasticity_gate(root)


def test_positive_tyramine_source_handle_preserves_ta_identity(tmp_path):
    runtime=object.__new__(CoreRuntime)
    runtime.engine=SimpleNamespace(step=0,dt=.1)
    runtime.neurons=pd.DataFrame({'super_class':['central']})
    runtime.cells=np.array(['TA_only'])
    runtime.sources={name:np.array([name=='TA']) for name in ('DA','OA','TA','5HT')}
    runtime.controls={}; runtime.events=[]; runtime.session_dir=tmp_path
    runtime._update_effects=lambda:None
    event=runtime.control('source_drive',{'cell_type':'TA_only','drive':.5})
    assert event['value']=={'cell_type':'TA_only','drive':.5}
    assert runtime.sources['TA'][0] and not runtime.sources['OA'][0]


def test_protocol_equal_time_turnoff_precedes_new_stimulus_and_test_is_sequential():
    p=compile_protocol({'blocks':[{'t_ms':0,'kind':'odour','id':'OCT','dur_ms':10},
        {'t_ms':10,'kind':'odour','id':'MCH','dur_ms':10},
        {'t_ms':30,'kind':'test','odours':['OCT','MCH'],'dur_ms':10,'iti_ms':5}]})
    assert p['duration_ms']==55
    assert [e['value'] for e in p['events'] if e['t_sim_ms']==10 and e['control_id']=='odour']==['air','MCH']


@pytest.mark.parametrize('blocks',[
    [{'t_ms':.1,'kind':'rest','dur_ms':100}],
    [{'t_ms':0,'kind':'rest','dur_ms':float('nan')}],
    [{'t_ms':0,'kind':'shell','dur_ms':100}],
    [{'t_ms':0,'kind':'odour','dur_ms':10,'id':'OCT'}, {'t_ms':5,'kind':'odour','dur_ms':10,'id':'MCH'}],
])
def test_ambiguous_or_invalid_protocol_rejected(blocks):
    with pytest.raises(ValueError): compile_protocol({'blocks':blocks})


def test_negative_pairing_moves_source_before_odour_without_relabeling():
    p=compile_protocol({'blocks':[{'t_ms':3000,'kind':'odour','id':'OCT','dur_ms':1000},
        {'t_ms':3500,'kind':'dan_pulse','source':'PPL101','compartment':'g1','dur_ms':500}]},pairing_interval_ms=-2000)
    assert next(e for e in p['events'] if e['control_id']=='dan_type')['t_sim_ms']==1000
    assert next(e for e in p['events'] if e['control_id']=='dan_type')['value']=='PPL101'
