import numpy as np
import pandas as pd
import pytest

from flybrain.visual_assets import prepare_anatomy, export_visual_run,export_chemistry


def test_anatomy_corrects_anisotropic_voxels_and_omits_missing_points(tmp_path):
    (tmp_path / 'build').mkdir()
    pd.DataFrame({'root_id': [1, 2, 3], 'super_class': ['optic', 'central', None],
                  'pos_x': [0, 100, np.nan], 'pos_y': [0, 0, np.nan],
                  'pos_z': [0, 100, np.nan]}).to_parquet(tmp_path / 'build/neurons.parquet')
    meta = prepare_anatomy(tmp_path)
    assert meta['visible_neuron_count'] == 2 and meta['missing_positions'] == 1
    out = tmp_path / 'build/visual/anatomy'
    points = np.fromfile(out / 'positions.bin', dtype='<f4').reshape(3, 3)
    assert (points[1, 2] - points[0, 2]) / (points[1, 0] - points[0, 0]) == pytest.approx(10)
    np.testing.assert_array_equal(np.fromfile(out / 'visible_indices.bin', dtype='<u4'), [0, 1])


def test_playback_export_preserves_recorded_values_and_rejects_reordered_neurons(tmp_path, monkeypatch):
    (tmp_path / 'build').mkdir()
    pd.DataFrame({'root_id': [1, 2], 'super_class': ['optic', 'central']}).to_parquet(tmp_path / 'build/neurons.parquet')
    run = tmp_path / 'runs/demo'
    run.mkdir(parents=True)
    raw = np.array([[-52, -53], [-50, -55]], dtype=np.float32)
    baseline = np.full_like(raw, -52)
    def save(indices):
        np.savez(run / 'activity.npz', node_indices=indices, time_ms=[0, 20], raw_mv=raw,
                 baseline_mv=baseline, delta_mv=raw-baseline)
    save([0, 1])
    eye = np.array([[.1, .3], [.2, .5], [.4, .8]], dtype=np.float32)
    np.savez(run / 'eye_input.npz', luminance=eye, frame_times_ms=[0, 1000/240, 2000/240])
    monkeypatch.setattr('flybrain.visual_assets.neuropil_traces', lambda *args: [])
    result = {'run_dir': str(run), 'activity_path': str(run / 'activity.npz'),
              'metadata': {'options': {'stimulus': 'flash', 'duration_ms': 300}}}
    summary = export_visual_run(tmp_path, result)
    assert summary['neuron_count']==2
    assert summary['chemistry']['available'] is False
    for name, expected in [('raw', raw), ('baseline', baseline), ('delta', raw-baseline)]:
        np.testing.assert_array_equal(np.fromfile(run / (name+'.bin'), dtype='<f4').reshape(2, 2), expected)
    np.testing.assert_array_equal(np.fromfile(run / 'eye_luminance.bin', dtype='<f4').reshape(3, 2), eye)
    assert summary['eyes']['dt_ms'] == pytest.approx(1000/240)
    save([1, 0])
    with pytest.raises(ValueError, match='released order'):
        export_visual_run(tmp_path, result)


def chemistry_fixture(tmp_path):
    path=tmp_path/'runs/chemical';path.mkdir(parents=True)
    roots=np.array([720575940000000001,720575940000000002,720575940000000003],np.int64)
    arrays={'time_ms':np.array([0.,20.]),'node_root_ids':roots,
        'concentrations_au':np.array([[[0.,1.]],[[2.,3.]]],np.float32),
        'baseline_concentrations_au':np.zeros((2,1,2),np.float32),
        'state_values':np.array([[1.],[.8]],np.float32),'hormones_au':np.array([[.2],[.3]],np.float32),
        'membership_indptr':np.array([0,1,3,3]),'membership_indices':np.array([0,0,1]),
        'membership_weights':np.array([1.,.25,.75],np.float32)}
    result={'chemistry_path':str(path/'chemistry.npz'),'chemistry':{'enabled':True,'species':['DA'],
        'compartments':['a','b'],'state_names':['energy'],'hormone_names':['insulin'],'scenario':'fed'}}
    return path,roots,arrays,result


def test_chemistry_export_preserves_actual_fields_and_exact_global_membership(tmp_path):
    directory,roots,arrays,result=chemistry_fixture(tmp_path)
    np.savez(directory/'chemistry.npz',**arrays)
    metadata=export_chemistry(directory,result,roots,[0.,20.])
    np.testing.assert_array_equal(np.fromfile(directory/'chemistry.bin','<f4').reshape(2,1,2),arrays['concentrations_au'])
    np.testing.assert_array_equal(np.fromfile(directory/'chemistry_membership_indptr.bin','<u4'),[0,1,3,3])
    assert metadata['neuron_count']==3
    assert metadata['membership']['assigned_neuron_count']==2
    assert metadata['membership']['unassigned_neuron_count']==1
    assert metadata['recording_sha256'] and metadata['asset_sha256']


def test_enzyme_export_keeps_intracellular_axes_and_flux_separate(tmp_path):
    directory,roots,arrays,result=chemistry_fixture(tmp_path)
    result['chemistry']['enzymes']={'enabled':True,'pool_names':['choline','tyramine'],'compartments':['a','b']}
    for prefix in ('','baseline_'):
        arrays[prefix+'enzyme_pools_au']=np.arange(8,dtype=float).reshape(2,2,2)/10
        arrays[prefix+'enzyme_flux_au_per_ms']=np.arange(20,dtype=float).reshape(2,5,2)/100
    np.savez(directory/'chemistry.npz',**arrays)
    metadata=export_chemistry(directory,result,roots,[0.,20.])
    assert metadata['enzymes']['pool_names']==['choline','tyramine']
    assert metadata['enzymes']['flux_names']==['ChAT','AChE','Tbh','ACh release','OA release']
    np.testing.assert_array_equal(np.fromfile(directory/'enzyme_pools.bin','<f4').reshape(2,2,2),arrays['enzyme_pools_au'].astype('f4'))
    assert metadata['baseline_enzyme_flux_au_per_ms_url'].endswith('/enzyme_baseline_flux.bin')
    arrays['enzyme_pools_au'][0,0,0]=-1
    np.savez(directory/'chemistry.npz',**arrays)
    with pytest.raises(ValueError,match='Negative'):export_chemistry(directory,result,roots,[0.,20.])


def test_recording_subset_exports_spikes_in_recorded_column_order(tmp_path,monkeypatch):
    (tmp_path/'build').mkdir();directory=tmp_path/'runs/selected';directory.mkdir(parents=True)
    table=pd.DataFrame({'root_id':[1,2,3],'super_class':['optic']*3,'pos_x':[0.,1.,2.],'pos_y':[0.]*3,'pos_z':[0.]*3})
    table.to_parquet(tmp_path/'build/neurons.parquet');table.to_parquet(directory/'neurons.parquet')
    np.savez(directory/'activity.npz',node_indices=[2,0],time_ms=[0.,20.],raw_mv=np.ones((2,2)),baseline_mv=np.ones((2,2)),delta_mv=np.zeros((2,2)),spike_indices=[0,2,1,2],spike_times_ms=[1.,2.,3.,4.])
    summary=export_visual_run(tmp_path,{'run_dir':str(directory),'activity_path':str(directory/'activity.npz'),'metadata':{}})
    assert summary['spikes']['spike_indices']==[1,0,0]
    assert summary['spikes']['spike_times_ms']==[1.,2.,4.]
    assert pd.read_parquet(directory/'recorded_neurons.parquet').root_id.tolist()==[3,1]


@pytest.mark.parametrize('fault',['root_order','time','nonfinite','shape','membership_sum','membership_negative','membership_range'])
def test_bad_chemical_recording_is_rejected_before_binary_export(tmp_path,fault):
    directory,roots,arrays,result=chemistry_fixture(tmp_path)
    if fault=='root_order':arrays['node_root_ids']=roots[::-1]
    if fault=='time':arrays['time_ms']=np.array([0.,21.])
    if fault=='nonfinite':arrays['concentrations_au'][0,0,0]=np.nan
    if fault=='shape':arrays['state_values']=np.ones((1,1))
    if fault=='membership_sum':arrays['membership_weights'][0]=.5
    if fault=='membership_negative':arrays['membership_weights'][0]=-1
    if fault=='membership_range':arrays['membership_indices'][0]=2
    np.savez(directory/'chemistry.npz',**arrays)
    with pytest.raises(ValueError):export_chemistry(directory,result,roots,[0.,20.])
    assert not (directory/'chemistry.bin').exists()
