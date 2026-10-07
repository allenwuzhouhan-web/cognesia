from pathlib import Path
import shutil
import numpy as np
import pandas as pd
import pytest
import yaml
from scipy import sparse
from flybrain.hybrid_engine import HybridEngine
from flybrain.config import parameters
from flybrain.stimuli import STIMULI, normalize_options, luminance
from flybrain.visual_experiment import run_visual_experiment, snapshot_state, restore_state

ROOT=Path(__file__).resolve().parents[1]


def test_stimuli_bounds_reversibility_and_motion():
    az,el=np.meshgrid(np.linspace(-150,150,75),np.linspace(-70,70,31))
    for kind in STIMULI:
        options=normalize_options({'stimulus':kind})
        frames=np.stack([luminance(az,el,t,options) for t in [0,100,200,400]])
        assert np.isfinite(frames).all() and frames.min()>=0 and frames.max()<=1
        if kind!='dark':assert np.ptp(frames)>0
    options=normalize_options({'speed_deg_s':90,'grating_waveform':'sine'})
    np.testing.assert_allclose(luminance(az,el,100,options),luminance(az-9,el,0,options),atol=1e-14)
    with pytest.raises(ValueError):normalize_options({'duration_ms':123})
    with pytest.raises(ValueError):normalize_options({'contrast':1.1})
    with pytest.raises(ValueError):normalize_options({'untrusted':3})


def test_complete_state_restore_repeats_delayed_network_exactly():
    p=parameters(ROOT)
    counts=sparse.csr_matrix(([20000.],([1],[0])),shape=(2,2))
    engine=HybridEngine(counts,sparse.csr_matrix((2,2)),np.array([True,False]),p,threads=1)
    engine.run(10.)
    state=snapshot_state(engine)
    a=engine.run(25.,record_indices=np.arange(2),photoreceptor_indices=np.array([0]),photoreceptor_drive=5.)
    restore_state(engine,state)
    b=engine.run(25.,record_indices=np.arange(2),photoreceptor_indices=np.array([0]),photoreceptor_drive=5.)
    for key in ('voltages','spike_indices','spike_times','per_neuron_clamp_counts','final_v','final_g'):
        np.testing.assert_array_equal(a[key],b[key])


@pytest.mark.parametrize('stimulus',['dark','grating','apparent_motion','electrode'])
def test_paired_experiment_persists_real_signals_and_preserves_failed_gate(tmp_path,monkeypatch,stimulus):
    for name in ['config/parameters.yaml','config/visual_parameters.yaml','src/flybrain/engine.py','src/flybrain/hybrid_engine.py',
                 'src/flybrain/eye.py','src/flybrain/stimuli.py','src/flybrain/stimulation.py','src/flybrain/visual_experiment.py']:
        dest=tmp_path/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,dest)
    dest=tmp_path/'build';dest.mkdir();(dest/'validation_hybrid.json').write_text('{"stage4_status":"FAIL"}')
    neurons=pd.DataFrame({'root_id':[10,11,12,13],'cell_type':['R1-6','L1','Mi1','Mi1'],
                           'side':['right','right','right','left'],'is_graded':[True]*4,
                           'super_class':['optic']*4,'mode':['graded']*4})
    columns=pd.DataFrame({'root_id':[11,12,13],'type':['L1','Mi1','Mi1'],'hemisphere':['right','right','left'],
                          'column_id':[1,1,1],'p':[0]*3,'q':[0]*3,'x':[0]*3,'y':[0]*3})
    dest=tmp_path/'data/raw/codex';dest.mkdir(parents=True);columns.to_csv(dest/'column_assignment.csv',index=False)
    counts=sparse.csr_matrix(([-10.,20.],([1,2],[0,1])),shape=(4,4))
    monkeypatch.setattr('flybrain.visual_experiment.load_network',lambda root: {
        'neurons':neurons,'graded':counts,'spiking':sparse.csr_matrix((4,4)),'reference':counts,
        'summary':{'n_edges_released':2,'output_hashes':{}}})
    if stimulus=='apparent_motion':
        config=tmp_path/'config/visual_parameters.yaml'
        doc=yaml.safe_load(config.read_text())
        doc['parameters']['apparent_point_radius_columns']['value']=.2
        doc['parameters']['apparent_onset_ms']['value']=50.
        config.write_text(yaml.safe_dump(doc))
        config=tmp_path/'config/parameters.yaml'
        doc=yaml.safe_load(config.read_text())
        doc['parameters']['eye_spacing']['value']=8.
        config.write_text(yaml.safe_dump(doc))
    updates=[]
    request={'stimulus':'dark' if stimulus=='electrode' else stimulus,'duration_ms':300,'threads':1}
    if stimulus=='electrode':
        request.update(record_dt_ms=5,neural_overrides={'graded_tau_membrane':30},
                       visual_overrides={'maximum_drive_mv':0},
                       electrodes=[{'id':'E1','target':{'kind':'indices','indices':[1]},
                                    'voltage_mv':10,'frequency_hz':50,'duty_percent':25}])
    result=run_visual_experiment(tmp_path,request,updates.append)
    activity=np.load(result['activity_path'])
    expected_frames=60 if stimulus=='electrode' else 15
    assert activity['raw_mv'].shape==(expected_frames,4)
    np.testing.assert_array_equal(activity['delta_mv'],activity['raw_mv']-activity['baseline_mv'])
    assert result['metadata']['original_validation_status']=='FAIL'
    assert (tmp_path/'build/validation_hybrid.json').read_text()=='{"stage4_status":"FAIL"}'
    assert len(result['eye']['luminance'])==expected_frames
    assert np.load(result['stimulus_full_frames_path']).shape == (72,180,360)
    assert np.diff(result['stimulus_frame_times_ms']).mean() == pytest.approx(1000/240)
    assert updates[-1]['phase']=='complete'
    assert result['metadata']['peak_rss_bytes']>0
    assert result['metadata']['seed']==783
    assert result['metadata']['versions']['numpy']==np.__version__
    assert 'git_hash' in result['metadata']
    assert len(result['metadata']['output_sha256'])==64
    assert result['metadata']['optics']['passed']
    assert result['metadata']['optics']['sample_count']==4096
    assert result['metadata']['input_hashes_checked_unchanged']
    if stimulus=='dark':np.testing.assert_array_equal(activity['delta_mv'],0)
    elif stimulus=='electrode':
        assert result['metadata']['neural_parameters']['graded_tau_membrane']==30
        assert result['metadata']['saved_base_neural_parameters']['graded_tau_membrane']==20
        assert result['metadata']['visual_parameters']['maximum_drive_mv']==0
        assert result['metadata']['electrode_baseline']=='OFF in common pre-equilibration and paired baseline'
        targets=np.load(result['stimulation']['targets_path'])
        np.testing.assert_array_equal(targets['electrode_0'],[1])
        waveforms=np.load(result['stimulation']['waveforms_path'])
        assert waveforms['input_mv'].shape==(3000,1)
        assert np.max(activity['delta_mv'][:,1])>1
        np.testing.assert_array_equal(activity['delta_mv'][:,0],0)
    elif stimulus=='apparent_motion':
        actual=result['metadata']['options']
        assert actual['eye_spacing_deg']==8.
        assert actual['apparent_flash_radius_deg']==1.6
        assert actual['apparent_flash_onset_ms']==50.
        # Configuration changes move the first spot center to -4 degrees and its onset to 50 ms.
        az=np.array([-4.,-2.5,-2.,0.]);el=np.zeros(4)
        np.testing.assert_allclose(luminance(az,el,50.,actual),[.9,.9,.5,.5])
        np.testing.assert_allclose(luminance(az,el,100.,actual),.5)
        assert result['metadata']['stimulus_definition']['assumed_eye_spacing_deg']==8.
    else:
        assert np.max(np.abs(activity['delta_mv']))>.01
        # Input enters photoreceptor first; downstream state follows network synapses.
        assert abs(activity['delta_mv'][1,0])>abs(activity['delta_mv'][1,1])
        assert activity['delta_mv'][1,0]*activity['delta_mv'][1,1]<=0


def test_apparent_motion_zero_delay_diagonal_points_and_background():
    options=normalize_options({'stimulus':'apparent_motion','apparent_interval_ms':0,
                               'apparent_separation_columns':4,'direction_deg':45})
    shift=.5*4*5.1/np.sqrt(2)
    az=np.array([-shift,shift,0.,40.]);el=np.array([-shift,shift,0.,40.])
    np.testing.assert_allclose(luminance(az,el,99,options),.5)
    np.testing.assert_allclose(luminance(az,el,100,options),[.9,.9,.5,.5])
    np.testing.assert_allclose(luminance(az,el,104.166666667,options),.5)


def test_apparent_motion_quantization_and_separate_single_frame_flashes():
    options=normalize_options({'stimulus':'apparent_motion','apparent_interval_ms':17,
                               'apparent_separation_columns':1})
    assert options['apparent_interval_frames']==4
    assert options['apparent_effective_interval_ms']==pytest.approx(1000/240*4)
    assert options['apparent_interval_quantization_ms']==pytest.approx(-1/3)
    az=np.array([-2.55,2.55,0.]);el=np.zeros(3)
    np.testing.assert_allclose(luminance(az,el,100,options),[.9,.5,.5])
    np.testing.assert_allclose(luminance(az,el,100+1000/240*4,options),[.5,.9,.5])
    for bad in [-1,101]:
        with pytest.raises(ValueError):normalize_options({'apparent_interval_ms':bad})
    for bad in [-1,.5,5]:
        with pytest.raises(ValueError):normalize_options({'apparent_separation_columns':bad})
    square=normalize_options({'stimulus':'grating'})
    values=luminance(np.linspace(-30,30,49),0.,25.,square)
    np.testing.assert_allclose(np.unique(values),[.1,.9])


def test_source_snapshot_rejects_changes(tmp_path):
    from flybrain.fetch import checksum
    from flybrain.visual_experiment import assert_sources_unchanged
    p=tmp_path/'source';p.write_text('before')
    hashes={'source':checksum(p)}
    assert_sources_unchanged(tmp_path,hashes)
    p.write_text('after')
    with pytest.raises(ValueError,match='Source changed'):
        assert_sources_unchanged(tmp_path,hashes)
