from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scipy import sparse
from flybrain.config import parameters
from flybrain.hybrid_engine import HybridEngine
from flybrain.stimulation import (normalize_lab_options,normalize_electrodes,resolve_electrodes,
    electrode_waveform,input_layout,combined_drive,available_threads,MAX_RECORDING_BYTES)
from flybrain.visual_experiment import read_visual_parameters,_run_branch,snapshot_state,restore_state,eye_movie

ROOT=Path(__file__).resolve().parents[1]


def test_runtime_overrides_are_validated_and_do_not_mutate_saved_values():
    p=parameters(ROOT);v=read_visual_parameters(ROOT);p0=p.copy();v0=v.copy()
    options,effective,eye,resources=normalize_lab_options({
        'duration_ms':10000,'record_dt_ms':10,'threads':available_threads(),
        'neural_overrides':{'dt':.025,'graded_gain':.0003,'v_threshold':-40},
        'visual_overrides':{'frame_rate':120,'eye_fwhm':7.,'maximum_drive_mv':30,'optics_samples':16384}},p,v)
    assert effective['dt']==.025 and effective['graded_gain']==.0003
    assert effective['frame_rate']==120 and effective['eye_fwhm']==7.
    assert eye['maximum_drive_mv']==30 and eye['display_sample_ms']==10
    assert p==p0 and v==v0
    assert options['neural_overrides']=={'dt':.025,'graded_gain':.0003,'v_threshold':-40.}
    assert resources['total_neural_steps']==840000
    assert resources['recording_float32_bytes']==1_663_668_000<MAX_RECORDING_BYTES
    bad=[{'neural_overrides':{'does_not_exist':1}}, {'neural_overrides':{'poisson_rate':12}},
         {'neural_overrides':{'dt':.03}}, {'neural_overrides':{'dt':.2,'synaptic_delay':1.7}},
         {'neural_overrides':{'v_reset':-40}}, {'visual_overrides':{'optics_samples':5}},
         {'record_dt_ms':1}, {'duration_ms':10000,'record_dt_ms':2},
         {'threads':available_threads()+1}, {'neural_overrides':{'graded_gain':float('nan')}}]
    for request in bad:
        with pytest.raises(ValueError):normalize_lab_options(request,p,v)


def sample_neurons():
    return pd.DataFrame({'root_id':[10,11,12,13,14,15],'cell_type':['R1-6','R7','L1','AN1','AN2','OR1'],
                         'side':['left','right','left','left','right','left'],
                         'super_class':['sensory','sensory','optic','ascending','sensory_ascending','sensory'],
                         'cell_class':['visual','visual','LA','AN','AN','olfactory'],
                         'nerve':['','','','CV','CV','AN'],'mode':['graded']*3+['spiking']*3,
                         'pos_x':[0,1000,2000,3000,4000,5000], 'pos_y':[0]*6,'pos_z':[0]*6})


def electrode(target,**kwargs):
    return normalize_electrodes([{'target':target,'voltage_mv':10,'frequency_hz':100,
                                 'duty_percent':25,'start_ms':10,'end_ms':40,**kwargs}],100,.1)[0]


def test_electrode_targets_resolve_real_annotations_and_explicit_body_proxy():
    n=sample_neurons()
    targets=[{'kind':'indices','indices':[3,3,0]},
             {'kind':'group','field':'cell_type','values':['R1-6','R7'],'side':'left'},
             {'kind':'region','name':'left_optic'},
             {'kind':'body_zone','name':'left_eye'},
             {'kind':'body_zone','name':'antennae'},
             {'kind':'body_zone','name':'legs'},
             {'kind':'body_zone','name':'wings'},
             {'kind':'sphere','center_um':[12,0,0],'radius_um':1}]
    found=[resolve_electrodes(n,[electrode(t)])[0] for t in targets]
    assert [r.indices.tolist() for r in found]==[[0,3],[0],[2],[0],[5],[3,4],[3,4],[3]]
    assert 'ASSUMPTION' in found[5].definition['assumption']
    for target in [{'kind':'indices','indices':[.2]},{'kind':'indices','indices':[9]},
                   {'kind':'body_zone','name':'invented'},{'kind':'group','field':'cell_type','values':['none']}]:
        with pytest.raises(ValueError):resolve_electrodes(n,[electrode(target)])


def test_electrode_pulse_frequency_duty_window_and_signed_dc():
    e=electrode({'kind':'indices','indices':[0]})
    times=np.array([9.9,10,12.4,12.5,19.9,20,22.5,30,39.9,40])
    np.testing.assert_array_equal(electrode_waveform(e,times),[0,10,10,0,0,10,0,10,0,0])
    dc=electrode({'kind':'indices','indices':[0]},voltage_mv=-8,frequency_hz=0)
    np.testing.assert_array_equal(electrode_waveform(dc,[0,10,29,40]),[0,-8,-8,0])
    with pytest.raises(ValueError):electrode({'kind':'indices','indices':[0]},frequency_hz=500,duty_percent=1)
    with pytest.raises(ValueError):electrode({'kind':'indices','indices':[0]},voltage_mv=101)


def test_overlapping_optical_and_electrode_inputs_sum_once():
    neurons=sample_neurons()
    raw=[{'id':'a','target':{'kind':'indices','indices':[0,3]},'voltage_mv':10,'frequency_hz':0},
         {'id':'b','target':{'kind':'indices','indices':[0]},'voltage_mv':-3,'frequency_hz':0}]
    es=resolve_electrodes(neurons,normalize_electrodes(raw,100,.1))
    layout=input_layout(np.array([0,1]),es)
    assert layout[0].tolist()==[0,1,3]
    drive=combined_drive(np.array([0.,1.]),np.array([[2.,4.],[3.,5.]]),layout,es)
    np.testing.assert_array_equal(drive,[[9,4,10],[10,5,10]])


def test_general_input_can_drive_spiking_neuron_and_preserves_refractory_rules():
    p=parameters(ROOT);zero=sparse.csr_matrix((2,2))
    e=HybridEngine(zero,zero,np.array([True,False]),p,threads=1)
    result=e.run(.1,record_indices=np.arange(2),membrane_input_indices=np.array([1]),membrane_input_drive=20.)
    assert e.v[0]==p['graded_rest']
    assert e.v[1]==pytest.approx(p['v_rest']+20*(1-np.exp(-.1/p['tau_membrane'])))
    e.last_spike[1]=e.step;e.v[1]=p['v_reset']
    e.run(1.,membrane_input_indices=np.array([1]),membrane_input_drive=100.)
    assert e.v[1]==p['v_reset']
    with pytest.raises(ValueError,match='either'):
        e.run(.1,photoreceptor_indices=np.array([0]),photoreceptor_drive=1.,
              membrane_input_indices=np.array([1]),membrane_input_drive=1.)


def test_paired_branch_electrode_control_is_off_and_record_timing_is_exact():
    p=parameters(ROOT)|{'record_dt_ms':5.};zero=sparse.csr_matrix((2,2))
    e=HybridEngine(zero,zero,np.array([True,False]),p,threads=1)
    mapping=SimpleNamespace(photoreceptor_indices=np.array([0],dtype=np.int32),photoreceptor_columns=np.array([0]))
    n=sample_neurons().iloc[:2]
    stimulation=resolve_electrodes(n,normalize_electrodes([
        {'target':{'kind':'indices','indices':[1]},'voltage_mv':20,'frequency_hz':50,'duty_percent':50}],300,.1))
    e.run(100.)
    state=snapshot_state(e);movie=np.zeros((72,1));options={'duration_ms':300.}
    actual=_run_branch(e,options,mapping,movie,240.,np.arange(2),None,'stimulus',electrodes=stimulation)
    restore_state(e,state)
    baseline=_run_branch(e,options,mapping,movie,240.,np.arange(2),None,'paired_baseline')
    np.testing.assert_array_equal(actual['voltage_times'],np.arange(0,300,5))
    np.testing.assert_array_equal(baseline['voltages'],-52.)
    assert np.max(actual['voltages'][:,1]-baseline['voltages'][:,1])>1.
    np.testing.assert_array_equal(actual['voltages'][:,0],baseline['voltages'][:,0])


def test_progress_callback_can_cancel_neural_and_optical_work():
    class Cancelled(RuntimeError):pass
    def cancel(_):raise Cancelled()
    p=parameters(ROOT);zero=sparse.csr_matrix((1,1))
    e=HybridEngine(zero,zero,np.array([True]),p,threads=1)
    mapping=SimpleNamespace(photoreceptor_indices=np.array([0]),photoreceptor_columns=np.array([0]),
        columns=pd.DataFrame({'azimuth_deg':[0.],'elevation_deg':[0.]}))
    with pytest.raises(Cancelled):_run_branch(e,{'duration_ms':300},mapping,np.zeros((72,1)),240,np.array([0]),cancel,'stimulus')
    assert e.step==0
    options,_,v,_=normalize_lab_options({'duration_ms':300,'threads':1},p,read_visual_parameters(ROOT),n_neurons=1)
    with pytest.raises(Cancelled):eye_movie(mapping,options,v,progress=cancel)
