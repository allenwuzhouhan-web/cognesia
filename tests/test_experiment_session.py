from pathlib import Path
from types import SimpleNamespace
import json

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from flybrain.config import parameters
from flybrain.hybrid_engine import HybridEngine
from flybrain.experiment_session import (
    BranchSession, SessionControl, InterventionSet, ExperimentStopped,
    snapshot_state, restore_state, model_fingerprint, save_checkpoint, read_checkpoint,
    compile_timeline,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('advanced',[
    {'peripheral':{'enabled':False,'modules':[]}},
    {'prepare_reference':True,'reference_selection':{'root_ids':['101']}},
    {'research_selection':{'root_ids':['101'],'boundary':'recorded'}},
    {'timeline':{'schema_version':1,'repeat':2,'blocks':[{'kind':'rest','start_ms':0,'duration_ms':100}]}},
    {'interventions':[{'kind':'silence','target':{'kind':'root_ids','root_ids':['101']},'start_ms':0,'end_ms':10}]},
    {'model_id':'flywire-783','live_chunk_ms':5},
    {'recording_selection':{'root_ids':['101']}},
])
def test_http_options_accept_advanced_runtime_contract(advanced):
    from flybrain.visual_server import VisualState
    normalized=VisualState.options({'stimulus':'grating','duration_ms':300,**advanced},ROOT,3)
    for key in advanced: assert key in normalized


def test_pause_acknowledges_durable_state(tmp_path):
    engine,mapping,_=fixture();updates=[];counter=0
    def poll():
        nonlocal counter
        counter+=1
        return {'action':'pause'} if counter==1 else {'action':'resume'} if counter==2 else None
    branch(engine,mapping,root=tmp_path,control=SessionControl(poll,updates.append),fingerprint=model_fingerprint(engine)).run()
    paused=next(row for row in updates if row.get('action')=='pause')
    manifest,payload=read_checkpoint(tmp_path,paused['checkpoint_id'])
    assert manifest['step']==payload['engine']['step']==0


def fixture():
    p = parameters(ROOT) | {'record_dt_ms': 1.}
    graded = sparse.csr_matrix(([20000.], ([1], [0])), shape=(3, 3))
    spiking = sparse.csr_matrix(([10.], ([2], [1])), shape=(3, 3))
    engine = HybridEngine(graded, spiking, np.array([True, False, False]), p, threads=1)
    mapping = SimpleNamespace(photoreceptor_indices=np.array([0], np.int32),
                              photoreceptor_columns=np.array([0], np.int32))
    neurons = pd.DataFrame({'root_id': [101, 102, 103], 'cell_type': ['R1-6', 'A', 'B']})
    return engine, mapping, neurons


def branch(engine, mapping, *, duration=30., chunk=7., **kwargs):
    context = kwargs.pop('context', {}) | {'session_options': {'live_chunk_ms': chunk}}
    return BranchSession(engine, {'duration_ms': duration}, mapping,
        np.full((100, 1), 12.), 1000., np.arange(3), context=context, **kwargs)


def test_incremental_frames_do_not_change_trajectory_and_are_owned():
    a, mapping, _ = fixture(); b, _, _ = fixture()
    direct = a.run(30., record_indices=np.arange(3), photoreceptor_indices=[0], photoreceptor_drive=12.)
    frames = []
    result = branch(b, mapping, frame=frames.append).run()
    for key in ('voltages', 'spike_indices', 'spike_times', 'final_v', 'final_g'):
        np.testing.assert_array_equal(result[key], direct[key])
    assert frames and frames[-1]['step'] == b.step
    assert all(x['signal'] == 'raw' and x['baseline_available'] is False for x in frames)
    first = frames[0]['voltage_mv'].copy()
    b.v[:] = 42
    np.testing.assert_array_equal(frames[0]['voltage_mv'], first)


def test_pause_step_checkpoint_resume_uses_model_time(tmp_path):
    engine, mapping, _ = fixture()
    updates = []
    polls = 0
    def poll():
        nonlocal polls
        polls += 1
        if polls == 1:
            return [{'action': 'pause'}, {'action': 'step', 'duration_ms': 1.}]
        if polls == 2:
            assert engine.step * engine.dt == 1.
            return {'action': 'checkpoint', 'request_id': 'save'}
        if polls == 3:
            assert engine.step * engine.dt == 1.
            return {'action': 'resume'}
    session = branch(engine, mapping, root=tmp_path,
        control=SessionControl(poll, updates.append), fingerprint=model_fingerprint(engine))
    session.run()
    identifier = next(u['checkpoint_id'] for u in updates if u.get('request_id') == 'save')
    manifest, payload = read_checkpoint(tmp_path, identifier)
    assert manifest['model_time_ms'] == 1.
    assert payload['context']['elapsed_ms'] == 1.
    assert any(u['status'] == 'paused' for u in updates)


def test_checkpoint_restores_delayed_state_and_rejects_corruption(tmp_path):
    engine, _, _ = fixture()
    engine.run(7., photoreceptor_indices=[0], photoreceptor_drive=12.)
    fingerprint = model_fingerprint(engine)
    manifest = save_checkpoint(tmp_path, engine, {'phase': 'stimulus'}, fingerprint)
    expected = engine.run(14., record_indices=np.arange(3), photoreceptor_indices=[0], photoreceptor_drive=9.)
    _, payload = read_checkpoint(tmp_path, manifest['id'], fingerprint=fingerprint)
    restore_state(engine, payload['engine'])
    actual = engine.run(14., record_indices=np.arange(3), photoreceptor_indices=[0], photoreceptor_drive=9.)
    for key in ('voltages', 'spike_indices', 'spike_times', 'final_v', 'final_g'):
        np.testing.assert_array_equal(actual[key], expected[key])
    with pytest.raises(ValueError, match='identity'):
        read_checkpoint(tmp_path, manifest['id'], fingerprint='changed')
    arrays = tmp_path / 'checkpoints' / manifest['id'] / 'state.npz'
    with arrays.open('ab') as handle:
        handle.write(b'corruption')
    with pytest.raises(ValueError, match='integrity'):
        read_checkpoint(tmp_path, manifest['id'])


def test_stop_saves_incomplete_recoverable_checkpoint(tmp_path):
    engine, mapping, _ = fixture()
    session = branch(engine, mapping, root=tmp_path,
        control=SessionControl(lambda: {'action': 'stop'}), fingerprint=model_fingerprint(engine))
    with pytest.raises(ExperimentStopped) as error:
        session.run()
    manifest, _ = read_checkpoint(tmp_path, error.value.checkpoint_id)
    assert not manifest['completed']
    assert engine.step == 0


def test_partial_journal_retains_actual_samples_after_stop(tmp_path):
    from flybrain.experiment_session import read_partial_recording
    engine,mapping,_=fixture()
    expected,_,_=fixture()
    observed=expected.run(7.,record_indices=np.arange(3),photoreceptor_indices=[0],photoreceptor_drive=12.)
    def poll():
        if engine.step: return {'action':'stop'}
    session=branch(engine,mapping,root=tmp_path,control=SessionControl(poll),fingerprint=model_fingerprint(engine))
    with pytest.raises(ExperimentStopped) as error: session.run()
    manifest,chunks=read_partial_recording(tmp_path,error.value.recording_id)
    assert manifest['status']=='stopped' and not manifest['completed']
    assert manifest['written_samples']==7 and manifest['voltage_shape']==[30,3]
    assert (tmp_path/'sessions'/error.value.recording_id/'voltages.npy').exists()
    np.testing.assert_array_equal(chunks[0]['voltages_mv'],observed['voltages'])
    np.testing.assert_array_equal(chunks[0]['spike_times_ms'],observed['spike_times'])
    checkpoint,_=read_checkpoint(tmp_path,error.value.checkpoint_id)
    assert checkpoint['recording_id']==error.value.recording_id


def test_timeline_rejects_alias_target_conflicts_but_preserves_legacy_sums():
    from flybrain.experiment_session import validate_timeline_targets
    _,_,neurons=fixture()
    one={'id':'a','target':{'kind':'indices','indices':[1]},'start_ms':0,'end_ms':10}
    alias={'id':'b','target':{'kind':'root_ids','root_ids':['102']},'start_ms':5,'end_ms':15}
    validate_timeline_targets(neurons,[],electrodes=[one,alias])
    timeline=compile_timeline({'blocks':[{'kind':'electrode','start_ms':5,'duration_ms':10,'electrode':alias}]},30.,.1)
    with pytest.raises(ValueError,match='same resolved target'):
        validate_timeline_targets(neurons,timeline,electrodes=[one])
    timeline=compile_timeline({'blocks':[
        {'kind':'intervention','start_ms':0,'duration_ms':10,'intervention':{'kind':'edge_scale','pre':one['target'],'post':{'kind':'indices','indices':[2]},'factor':.5}},
        {'kind':'intervention','start_ms':5,'duration_ms':10,'intervention':{'kind':'edge_scale','pre':alias['target'],'post':{'kind':'root_ids','root_ids':['103']},'factor':2.}},
    ]},30.,.1)
    with pytest.raises(ValueError,match='edge_scale'):
        validate_timeline_targets(neurons,timeline)


def test_edge_intervention_is_temporary_and_changes_real_voltage():
    baseline, mapping, neurons = fixture(); changed, _, _ = fixture()
    reference = branch(baseline, mapping).run()
    before = changed.graded_counts.copy()
    intervention = InterventionSet(changed, neurons,
        [{'kind': 'edge_scale', 'pre': {'kind': 'indices', 'indices': [0]},
          'post': {'kind': 'indices', 'indices': [1]}, 'factor': 0., 'start_ms': 5., 'end_ms': 20.}], 30.)
    result = branch(changed, mapping, interventions=intervention).run()
    np.testing.assert_array_equal(changed.graded_counts, before)
    np.testing.assert_array_equal(reference['voltages'][:5], result['voltages'][:5])
    assert np.max(np.abs(reference['voltages'][7:] - result['voltages'][7:])) > .001


def test_recording_window_does_not_change_dynamics():
    a, mapping, _ = fixture(); b, _, _ = fixture()
    full = branch(a, mapping).run()
    timeline = compile_timeline({'blocks': [{'kind': 'recording', 't_ms': 5., 'dur_ms': 8.}]}, 30., .1)
    result = branch(b, mapping, context={'compiled_timeline': timeline}).run()
    np.testing.assert_array_equal(a.v, b.v)
    np.testing.assert_array_equal(result['voltage_times'], np.arange(5., 13.))
    np.testing.assert_array_equal(result['voltages'], full['voltages'][5:13])


def test_timeline_repeat_and_conflict_validation():
    events = compile_timeline({'repeat': {'count': 2, 'interval_ms': 10.},
        'blocks': [{'kind': 'chemical', 'species': 'DA', 'level': .4, 't_ms': 1., 'dur_ms': 2.}]}, 30., .1)
    assert [b['start_ms'] for b in events] == [1., 11.]
    with pytest.raises(ValueError, match='Overlapping'):
        compile_timeline({'blocks': [
            {'kind': 'visual', 't_ms': 1, 'dur_ms': 10},
            {'kind': 'rest', 't_ms': 5, 'dur_ms': 10}]}, 30, .1)
    with pytest.raises(ValueError, match='clock'):
        compile_timeline({'blocks': [{'kind': 'chemical', 'species': 'DA', 't_ms': .1, 'dur_ms': 2.}]}, 30, .1)


def test_boundary_spikes_obey_refractory_and_graded_drive_is_not_current():
    a, _, _ = fixture(); b, _, _ = fixture()
    # Recipient 1 is refractory at step zero, so a replayed spike is discarded.
    a.last_spike[1] = b.last_spike[1] = 0
    external = np.zeros((10, 3)); external[0, 1] = 999.
    original = a.run(1.)
    replayed = b.run(1., boundary_spike_delta=external)
    np.testing.assert_array_equal(original['final_v'], replayed['final_v'])
    np.testing.assert_array_equal(original['final_g'], replayed['final_g'])
    c, _, _ = fixture(); d, _, _ = fixture()
    d.run(1., boundary_graded_release=np.full((10, 3), 100.))
    c.run(1.)
    assert np.max(np.abs(d.g - c.g)) > 0
    with pytest.raises(ValueError, match='samples'):
        d.run(1., boundary_spike_delta=np.zeros((1, 3)))


def test_saved_visual_fork_inherits_optics_electrodes_and_paired_state(tmp_path, monkeypatch):
    import shutil
    from flybrain.visual_experiment import run_visual_experiment
    from flybrain.visual_server import VisualState
    for name in ['config/parameters.yaml','config/visual_parameters.yaml','src/flybrain/engine.py',
                 'src/flybrain/hybrid_engine.py','src/flybrain/eye.py','src/flybrain/stimuli.py',
                 'src/flybrain/stimulation.py','src/flybrain/visual_experiment.py']:
        dest=tmp_path/name; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(ROOT/name,dest)
    (tmp_path/'build').mkdir()
    neurons=pd.DataFrame({'root_id':[10,11,12,13],'cell_type':['R1-6','L1','Mi1','Mi1'],
        'side':['right','right','right','left'],'is_graded':[True]*4,'super_class':['optic']*4,'mode':['graded']*4})
    columns=pd.DataFrame({'root_id':[11,12,13],'type':['L1','Mi1','Mi1'],'hemisphere':['right','right','left'],
        'column_id':[1,1,1],'p':[0]*3,'q':[0]*3,'x':[0]*3,'y':[0]*3})
    dest=tmp_path/'data/raw/codex'; dest.mkdir(parents=True); columns.to_csv(dest/'column_assignment.csv',index=False)
    counts=sparse.csr_matrix(([-10.,20.],([1,2],[0,1])),shape=(4,4))
    monkeypatch.setattr('flybrain.visual_experiment.load_network',lambda root: {
        'neurons':neurons,'graded':counts,'spiking':sparse.csr_matrix((4,4)),'reference':counts,
        'summary':{'n_edges_released':2,'output_hashes':{}}})
    last={}; requested=False; events=[]
    def poll():
        nonlocal requested
        if last.get('phase')=='stimulus' and last.get('elapsed_ms')==100 and not requested:
            requested=True
            return {'action':'checkpoint','request_id':'fork-me'}
    def frame(event):
        last.clear(); last.update(event)
    parent=run_visual_experiment(tmp_path,{'stimulus':'grating','duration_ms':300,'threads':1,
        'electrodes':[{'id':'pulse','target':{'kind':'indices','indices':[1]},'voltage_mv':10,
                       'start_ms':50,'end_ms':250}],
        'interventions':[{'kind':'silence','target':{'kind':'indices','indices':[3]},'start_ms':50,'end_ms':250}]},events.append,frame=frame,control=poll)
    identifier=next(e['checkpoint_id'] for e in events if e.get('request_id')=='fork-me')
    child=run_visual_experiment(tmp_path,{'from_checkpoint':identifier})
    with np.load(parent['activity_path']) as data, np.load(child['activity_path']) as fork:
        np.testing.assert_array_equal(fork['raw_mv'], data['raw_mv'][5:])
        np.testing.assert_array_equal(fork['delta_mv'],0.)
    assert child['metadata']['parent_checkpoint_id']==identifier
    assert child['metadata']['input_origin_ms']==100.
    with pytest.raises(ValueError,match='Conflicting timeline silence'):
        run_visual_experiment(tmp_path,{'from_checkpoint':identifier,'interventions':[{'kind':'silence',
            'target':{'kind':'root_ids','root_ids':['13']},'start_ms':0,'end_ms':50}]})
    changed=run_visual_experiment(tmp_path,{'from_checkpoint':identifier,
        'timeline':{'blocks':[{'kind':'rest','start_ms':0,'duration_ms':100}]}})
    with np.load(parent['activity_path']) as data,np.load(changed['activity_path']) as experiment:
        np.testing.assert_array_equal(experiment['baseline_mv'],data['raw_mv'][5:])
        assert np.max(np.abs(experiment['delta_mv']))>1e-5
    assert changed['metadata']['optics']['passed']
    reconstructed=run_visual_experiment(tmp_path,{'from_checkpoint':parent['initial_checkpoint_id'],'branch_time_ms':160.})
    earlier=run_visual_experiment(tmp_path,{'from_checkpoint':identifier,'branch_time_ms':60.})
    with np.load(parent['activity_path']) as data,np.load(reconstructed['activity_path']) as later,np.load(earlier['activity_path']) as before:
        np.testing.assert_array_equal(later['raw_mv'],data['raw_mv'][8:])
        np.testing.assert_array_equal(later['delta_mv'],0.)
        np.testing.assert_array_equal(before['raw_mv'],data['raw_mv'][3:])
        np.testing.assert_array_equal(before['delta_mv'],0.)
    full=run_visual_experiment(tmp_path,{'stimulus':'grating','duration_ms':300,'threads':1})
    preparation_progress={}
    def preparation_update(event): preparation_progress.update(event)
    def preparation_stop():
        if preparation_progress.get('phase')=='preequilibration' and preparation_progress.get('simulated_ms',0)>=40:
            return {'action':'stop'}
    with pytest.raises(ExperimentStopped) as stopped:
        run_visual_experiment(tmp_path,{'stimulus':'grating','duration_ms':300,'threads':1},preparation_update,control=preparation_stop)
    resumed=run_visual_experiment(tmp_path,VisualState.options({'from_checkpoint':stopped.value.checkpoint_id},tmp_path,4))
    with np.load(full['activity_path']) as data,np.load(resumed['activity_path']) as resumed_data:
        np.testing.assert_array_equal(resumed_data['raw_mv'],data['raw_mv'])
        np.testing.assert_array_equal(resumed_data['baseline_mv'],data['baseline_mv'])
    assert resumed['metadata']['preequilibration']['resumed_from_checkpoint']==stopped.value.checkpoint_id
    recorded=run_visual_experiment(tmp_path,{'stimulus':'grating','duration_ms':300,'threads':1,
        'recording_selection':{'root_ids':['12']}})
    assert recorded['metadata']['n_neurons']==4 and recorded['metadata']['n_recorded']==1
    with np.load(full['activity_path']) as data,np.load(recorded['activity_path']) as recording:
        np.testing.assert_array_equal(recording['raw_mv'],data['raw_mv'][:,[2]])
        np.testing.assert_array_equal(recording['node_indices'],[2])
    reduced=run_visual_experiment(tmp_path,{'stimulus':'grating','duration_ms':300,'threads':1,
        'research_selection':{'root_ids':['11','12']}})
    assert reduced['selection']['reference_id']
    assert reduced['selection']['one_way_surroundings']
    with np.load(full['activity_path']) as data,np.load(reduced['activity_path']) as subset:
        np.testing.assert_allclose(subset['raw_mv'],data['raw_mv'][:,[1,2]],rtol=0,atol=1e-5)
        np.testing.assert_allclose(subset['baseline_mv'],data['baseline_mv'][:,[1,2]],rtol=0,atol=1e-5)
    for recovery_phase in ('reference_preequilibration','reference_stimulus','reference_baseline'):
        reference_progress={}
        def reference_update(event): reference_progress.update(event)
        def reference_stop():
            if reference_progress.get('phase')==recovery_phase and reference_progress.get('simulated_ms',0)>=10:
                return {'action':'stop'}
        with pytest.raises(ExperimentStopped) as stopped:
            run_visual_experiment(tmp_path,{'stimulus':'grating','duration_ms':300,'threads':1,
                'research_selection':{'root_ids':['11','12']}},reference_update,control=reference_stop)
        recovered=run_visual_experiment(tmp_path,VisualState.options({'from_checkpoint':stopped.value.checkpoint_id},tmp_path,4))
        assert recovered['metadata']['recovered_reference_checkpoint_id']==stopped.value.checkpoint_id
        assert any(e['kind']=='checkpoint_restored' for e in recovered['metadata']['session_events'])
        with np.load(reduced['activity_path']) as data,np.load(recovered['activity_path']) as recovered_data:
            np.testing.assert_array_equal(recovered_data['raw_mv'],data['raw_mv'])
            np.testing.assert_array_equal(recovered_data['baseline_mv'],data['baseline_mv'])


def test_organ_feedback_and_hidden_state_survive_disk_checkpoint(tmp_path):
    from flybrain.peripheral import PeripheralRuntime
    engine,mapping,neurons=fixture()
    module={'id':'fixture-organ','label':'Fixture organ','input_indices':[0],'output_indices':[1],
            'neuron_indices':[0,1],'status':'explicit_test_model'}
    engine.organs=PeripheralRuntime([module],neurons=neurons,
        options={'enabled':True,'modules':['fixture-organ'],'external_inputs':{'fixture-organ':1.}})
    branch(engine,mapping,duration=10.).run()
    saved=save_checkpoint(tmp_path,engine,{},model_fingerprint(engine))
    result=branch(engine,mapping,duration=10.).run()
    expected=engine.organs.snapshot()
    _,payload=read_checkpoint(tmp_path,saved['id'])
    restore_state(engine,payload['engine'])
    repeated=branch(engine,mapping,duration=10.).run()
    np.testing.assert_array_equal(result['voltages'],repeated['voltages'])
    np.testing.assert_array_equal(result['organs']['state_values'],repeated['organs']['state_values'])
    np.testing.assert_array_equal(result['organs']['time_ms'],result['voltage_times'])
    np.testing.assert_array_equal(engine.organs.state,expected['state'])
    assert engine.organs.t_ms==20.
    assert engine.organs.state[0,0]>0


def test_provider_enzyme_timeline_changes_chemistry_and_preserves_resume(tmp_path):
    from flybrain.wholebrain_neuromod import WholeBrainNeuromodEngine
    from flybrain.provider_chemistry import build_model_chemistry
    def make():
        base,mapping,neurons=fixture()
        neurons['super_class']=['sensory','central','central']
        neurons['cell_class']=['visual','DAN','other']
        neurons['known_nt']=['acetylcholine','dopamine','gaba']
        neurons['cell_type']=['R1-6','PAM01','B']
        neurons['root_region']='brain'
        neurons['is_graded']=[True,False,False]
        options={'enabled':True,'plasticity_enabled':False,'enzymes':{'enabled':True},
                 'chemical_levels':{'ACh':1.}}
        g=sparse.csr_matrix((base.graded_counts,base.graded_indices,base.graded_indptr),shape=(3,3))
        s=sparse.csc_matrix((base.csc_counts,base.csc_indices,base.csc_indptr),shape=(3,3))
        network={'neurons':neurons,'model_id':'fixture-provider'}
        engine=WholeBrainNeuromodEngine(g,s,base.graded_mask,base.parameters,threads=1,
            neuromod=options,chemistry_factory=lambda e:build_model_chemistry(ROOT,e,network,options))
        return engine,mapping,neurons
    a,mapping,_=make();b,_,neurons=make()
    branch(a,mapping,duration=10.).run()
    timeline=compile_timeline({'blocks':[{'kind':'enzyme','enzyme_id':'AChE','activity':0.,'start_ms':0.,'duration_ms':10.}]},10.,.1)
    result=branch(b,mapping,duration=10.,context={'compiled_timeline':timeline}).run()
    assert b.chemistry.enzymes.get_activity('AChE')==1.
    ach=b.chemistry.field.species.index('ACh')
    assert np.any(b.chemistry.field.C[ach]>a.chemistry.field.C[ach])
    saved=save_checkpoint(tmp_path,b,{},model_fingerprint(b))
    expected=branch(b,mapping,duration=5.).run()
    _,payload=read_checkpoint(tmp_path,saved['id'])
    restore_state(b,payload['engine'])
    repeated=branch(b,mapping,duration=5.).run()
    for name in expected['chemistry']:
        np.testing.assert_array_equal(expected['chemistry'][name],repeated['chemistry'][name])
    # Receptor rows are resolved by identity and operate in this provider too.
    intervention=InterventionSet(b,neurons,[{'kind':'receptor_block','receptor_id':'DA_Dop2R_gain','start_ms':0,'end_ms':2}],2)
    branch(b,mapping,duration=2.,interventions=intervention).run()


def test_output_silencing_preserves_previously_emitted_delayed_spikes():
    a,_,neurons=fixture();b,_,_=fixture()
    # Emit the first spike before the output is disabled. Both receive it at
    # exactly the native delayed arrival, despite the later source intervention.
    a.v[1]=b.v[1]=0.
    a.run(.1);b.run(.1)
    silence=InterventionSet(b,neurons,[{'kind':'silence','target':{'kind':'indices','indices':[1]},'start_ms':0,'end_ms':4}],4)
    with silence.applied(0):
        actual=b.run(2.)
    expected=a.run(2.)
    np.testing.assert_array_equal(actual['final_v'],expected['final_v'])
    np.testing.assert_array_equal(actual['final_g'],expected['final_g'])
    assert np.all(b.output_enabled)
    # A spike generated while silenced is recorded locally but is not queued.
    b.last_spike[1]=-10000;b.v[1]=0.
    with silence.applied(0):
        result=b.run(.1)
    assert 1 in result['spike_indices']
    assert all(1 not in b.ring[i,:n] for i,n in enumerate(b.ring_counts))


def test_output_silencing_preserves_graded_release_already_in_delay_buffer():
    a,_,neurons=fixture();b,_,_=fixture()
    a.v[0]=b.v[0]=-40.
    a.run(a.dt);b.run(b.dt)
    silence=InterventionSet(b,neurons,[{'kind':'silence','target':{'kind':'indices','indices':[0]},
        'start_ms':0,'end_ms':5}],5)
    duration=a.delay_steps*a.dt
    with silence.applied(0): actual=b.run(duration)
    expected=a.run(duration)
    np.testing.assert_array_equal(actual['final_g'],expected['final_g'])
    assert actual['final_g'][1]>0
    with silence.applied(duration): b.run(a.dt)
    a.run(a.dt)
    assert a.g[1]!=b.g[1]
