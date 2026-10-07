"""Regression cases found in the independent server/recording integration review."""
import json
from pathlib import Path
from types import SimpleNamespace
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import threading

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from flybrain.experiment_session import RecordingJournal
from flybrain.fetch import checksum
from flybrain.model_registry import get_model_manifest
from flybrain.partial_export import export_partial
from flybrain.workbench_api import connectivity

ROOT=Path(__file__).resolve().parents[1]


def neurons():
    return pd.DataFrame({'root_id':[11,22,33],'entity_id':['flywire:783:11','flywire:783:22','flywire:783:33'],
        'cell_type':['a','b','c'],'super_class':['optic','central','central'], 'side':['left']*3,
        'pos_x':[0.,1.,2.],'pos_y':[0.,1.,2.],'pos_z':[0.,1.,2.]})


def legacy_model(root):
    (root/'build').mkdir();neurons().to_parquet(root/'build/neurons.parquet',index=False)
    (root/'build/build_summary.json').write_text(json.dumps({'output_hashes':{'neurons.parquet':checksum(root/'build/neurons.parquet')}}))
    return get_model_manifest(root,'flywire-783')['model_hash']


def part(clock,values,spikes,times,clamps,duration_ms=1.):
    return {'voltage_times':np.asarray(clock,float),'voltages':np.asarray(values,np.float32),
        'spike_indices':np.asarray(spikes,np.int32),'spike_times':np.asarray(times,float),
        'per_neuron_clamp_counts':np.asarray(clamps,np.int64),'simulated_ms':duration_ms}


def test_flywire_partial_retains_events_between_voltage_samples(tmp_path):
    model_hash=legacy_model(tmp_path)
    journal=RecordingJournal(tmp_path,'stimulus',[1,0],{'model_id':'flywire-783','model_hash':model_hash})
    journal.append(part([0.],[[-51.,-52.]],[1],[.3],[1,2,3]),0,.1,True)
    journal.append(part([],np.empty((0,2)),[0,2],[1.1,1.2],[4,0,0]),0,.1,True)
    journal.finish('stopped')
    result=export_partial(tmp_path,journal.id,'checkpoint')
    assert result['model_hash']==model_hash
    assert result['stats']=={'spikes':2,'clamps':10}
    assert result['spikes']['spike_indices']==[0,1]
    assert result['spikes']['spike_times_ms']==[.3,1.1]
    assert result['spikes']['total_count']==2 and not result['spikes']['truncated']
    assert result['stimulus']['duration_ms']==2.
    assert pd.read_parquet(tmp_path/'runs'/result['id']/'recorded_neurons.parquet').root_id.tolist()==[22,11]
    np.testing.assert_array_equal(np.fromfile(tmp_path/'runs'/result['id']/'raw.bin',dtype='<f4'),[-51.,-52.])
    # A changed identity table cannot silently inherit the old model hash.
    changed=neurons();changed.loc[0,'root_id']=99;changed.to_parquet(tmp_path/'build/neurons.parquet',index=False)
    with pytest.raises(ValueError,match='identities changed'):export_partial(tmp_path,journal.id)


def test_partial_raster_cap_preserves_total_count_and_marks_truncation(tmp_path):
    model_hash=legacy_model(tmp_path)
    journal=RecordingJournal(tmp_path,'stimulus',[0],{'model_id':'flywire-783','model_hash':model_hash})
    journal.append(part([0.],[[-52.]],[0],[0.],[0,0,0]),0,.1,True)
    times=np.arange(200005,dtype=float)/10.+.1
    journal.append(part([],np.empty((0,1)),np.zeros(len(times),int),times,[0,0,0]),0,.1,True)
    result=export_partial(tmp_path,journal.id)
    assert result['stats']['spikes']==200006
    assert result['spikes']['total_count']==200006 and result['spikes']['truncated']
    assert len(result['spikes']['spike_indices'])==200000
    assert result['spikes']['spike_times_ms'][-1]==times[-1]


def test_recording_region_connectivity_maps_global_membership_once(tmp_path):
    table=neurons();matrix=sparse.csr_matrix(([3.,-2.],([1,0],[0,1])),shape=(3,3))
    state=SimpleNamespace(root=tmp_path,wiring={'graded':matrix,'spiking':matrix*0},neuron_table=lambda:table,
                          region_neurons=lambda key:{'indices':{'source':[0,2],'target':[1]}[key]})
    run=tmp_path/'runs/example';run.mkdir(parents=True)
    (run/'visual_summary.json').write_text(json.dumps({'model_id':'flywire-783'}))
    table.iloc[[1,0]].to_parquet(run/'recorded_neurons.parquet',index=False)
    result=connectivity(state,{'run_id':'example','source_regions':['source'],'target_regions':['target']})
    assert result['source_count']==1 # source member2 was not recorded
    assert result['forward']['edges'][0]['source_id']=='flywire:783:11'
    assert result['forward']['edges'][0]['target_id']=='flywire:783:22'
    assert result['forward']['edges'][0]['weight']==3.


def test_checkpoint_branch_draft_is_a_valid_session_request(monkeypatch):
    from flybrain.visual_server import make_handler,VisualState,REQUEST_OPTION_KEYS
    from flybrain.config import parameters
    from flybrain.visual_experiment import read_visual_parameters
    from flybrain.stimulation import normalize_lab_options
    options,*_=normalize_lab_options({'stimulus':'apparent_motion','duration_ms':300,
        'electrodes':[{'target':{'kind':'indices','indices':[0]},'voltage_mv':1.}]},parameters(ROOT),read_visual_parameters(ROOT))
    assert 'apparent_interval_frames' in options
    assert 'effective_start_ms' in options['electrodes'][0]
    checkpoint={'id':'a'*32,'options':options}
    protocol={'schema_version':1,'blocks':[{'kind':'rest','start_ms':0.,'duration_ms':300.}]}
    context={'session_options':{'model_id':'cognesia-fused-v1','recording_selection':{'root_ids':['11']},
        'timeline':protocol},'resolved_interventions':[{'kind':'silence','indices':[0]}],'input_origin_ms':100.}
    monkeypatch.setattr('flybrain.experiment_session.read_checkpoint',lambda root,identifier:(checkpoint,{'context':context}))
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(SimpleNamespace(root=ROOT)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    client=HTTPConnection('127.0.0.1',server.server_port)
    try:
        client.request('POST','/api/checkpoints/'+checkpoint['id']+'/branches',body='{}',headers={'Content-Type':'application/json'})
        response=client.getresponse();draft=json.loads(response.read())
        assert response.status==200 and draft['status']=='draft'
        assert set(draft['options'])<=REQUEST_OPTION_KEYS
        canonical=VisualState.options(draft['options'],ROOT)
        assert canonical['from_checkpoint']==checkpoint['id']
        assert canonical['model_id']=='cognesia-fused-v1'
        assert canonical['recording_selection']=={'root_ids':['11']}
        assert draft['parent_protocol']==protocol
        assert draft['parent_interventions']==context['resolved_interventions']
        assert draft['parent_input_origin_ms']==100.
        assert 'parent_protocol' not in draft['options'] and 'parent_interventions' not in draft['options']
        assert canonical['electrodes'][0]['voltage_mv']==1.
        assert 'effective_start_ms' not in canonical['electrodes'][0]
        direct=VisualState.options({'from_checkpoint':checkpoint['id']},ROOT)
        assert direct['electrodes'][0]['voltage_mv']==1.
        with pytest.raises(ValueError,match='Electrode contains unsupported fields'):
            VisualState.options({'from_checkpoint':checkpoint['id'],'electrodes':options['electrodes']},ROOT)
    finally:
        client.close();server.shutdown();server.server_close();thread.join()


def test_historical_connectivity_rejects_a_different_recorded_model_hash(tmp_path,monkeypatch):
    table=neurons();matrix=sparse.csr_matrix(([3.],([1],[0])),shape=(3,3))
    state=SimpleNamespace(root=tmp_path,wiring={'graded':matrix,'spiking':matrix*0},neuron_table=lambda:table)
    run=tmp_path/'runs/example';run.mkdir(parents=True)
    (run/'visual_summary.json').write_text(json.dumps({'model_id':'flywire-783','model_hash':'old-version'}))
    table.to_parquet(run/'recorded_neurons.parquet',index=False)
    def require_version(root,model_id,model_hash=None):
        assert model_id=='flywire-783' and model_hash=='old-version'
        raise ValueError('Historical FlyWire source identity differs')
    monkeypatch.setattr('flybrain.model_registry.get_model_manifest',require_version)
    with pytest.raises(ValueError,match='source identity differs'):
        connectivity(state,{'run_id':'example','source_indices':[0],'target_indices':[1]})
