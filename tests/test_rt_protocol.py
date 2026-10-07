from pathlib import Path

import numpy as np
import pytest

from flybrain.neuromod.plasticity import NormalizedPlasticity, reference_parameters
from flybrain.rt.protocol import ProtocolRunner, compile_protocol


class PlasticityRuntime:
    """Real plasticity kernel with controlled nonzero KC/DA drive, no network load."""
    def __init__(self, path, enabled=True):
        self.session_dir=Path(path)
        self.controls={'plasticity.enabled':enabled}
        self.plasticity=NormalizedPlasticity(1,1,np.array([0]),np.array([0]),[1.],reference_parameters())
        self.t_sim_ms=0
        self.events=[]
    def control(self,key,value):
        self.controls[key]=value
        self.events.append({'t_sim_ms':self.t_sim_ms,'control_id':key,'value':value})
    def advance(self,duration_ms):
        for _ in range(duration_ms):
            if self.controls['plasticity.enabled']:
                self.plasticity.step([1.],[1.],1.)
            self.t_sim_ms+=1
    def snapshot(self):return {'t_sim_ms':self.t_sim_ms}


@pytest.mark.parametrize('prior_enabled',[True,False])
def test_test_block_freezes_real_plasticity_through_itis_and_restores_prior_state(tmp_path,prior_enabled):
    runtime=PlasticityRuntime(tmp_path,prior_enabled)
    document={'blocks':[{'kind':'odour','t_ms':0,'id':'OCT','dur_ms':10},
        {'kind':'test','t_ms':10,'odours':['OCT','MCH'],'dur_ms':10,'iti_ms':5},
        {'kind':'rest','t_ms':35,'dur_ms':10}]}
    runner=ProtocolRunner(runtime,document,reset=False)
    runner.advance(10)
    trained=runtime.plasticity.weights.copy()
    assert runtime.controls['plasticity.enabled'] is False
    runner.advance(13)  # Includes the first odor and part of its ITI.
    np.testing.assert_array_equal(runtime.plasticity.weights,trained)
    runner.advance(12)  # Includes the second odor and end boundary.
    np.testing.assert_array_equal(runtime.plasticity.weights,trained)
    assert runtime.controls['plasticity.enabled'] is prior_enabled
    assert runner.test_readouts[0]['weights_unchanged']
    toggles=[event for event in runtime.events if event['control_id']=='plasticity.enabled']
    assert toggles==[{'t_sim_ms':10,'control_id':'plasticity.enabled','value':False},
                     {'t_sim_ms':35,'control_id':'plasticity.enabled','value':prior_enabled}]
    runner.advance(10)
    assert runner.done
    assert np.any(runtime.plasticity.weights!=trained)==prior_enabled


def test_manual_enable_during_test_fails_before_advancing(tmp_path):
    runtime=PlasticityRuntime(tmp_path)
    runner=ProtocolRunner(runtime,{'blocks':[{'kind':'test','t_ms':0,'odours':['OCT'],'dur_ms':10}]},reset=False)
    runner.advance(1)
    before=runtime.plasticity.weights.copy()
    runtime.control('plasticity.enabled',True)
    with pytest.raises(RuntimeError,match='enabled during'):runner.advance(1)
    assert runtime.t_sim_ms==1
    np.testing.assert_array_equal(runtime.plasticity.weights,before)


def test_changed_test_weights_are_rejected_before_restoring(tmp_path):
    runtime=PlasticityRuntime(tmp_path)
    runner=ProtocolRunner(runtime,{'blocks':[{'kind':'test','t_ms':0,'odours':['OCT'],'dur_ms':10}]},reset=False)
    runner.advance(1)
    runtime.plasticity.weights[0]+=.1
    with pytest.raises(RuntimeError,match='changed trained weights'):runner.advance(9)


@pytest.mark.parametrize('conflict',[
    {'kind':'odour','t_ms':12,'id':'MCH','dur_ms':2},
    {'kind':'dan_pulse','t_ms':12,'source':'PPL101','dur_ms':2},
    {'kind':'control','t_ms':12,'control_id':'plasticity.enabled','value':True,'dur_ms':1},
    {'kind':'test','t_ms':12,'odours':['OCT'],'dur_ms':2},
])
def test_test_iti_cannot_hide_training_or_plasticity_override(conflict):
    with pytest.raises(ValueError):
        compile_protocol({'blocks':[{'kind':'test','t_ms':0,'odours':['OCT','MCH'],'dur_ms':10,'iti_ms':10},conflict]})


@pytest.mark.parametrize('interval',[.5,-.5,True,float('nan'),float('inf'),'500'])
def test_pairing_interval_is_not_silently_rounded(interval):
    with pytest.raises(ValueError):
        compile_protocol({'blocks':[{'kind':'odour','t_ms':3000,'id':'OCT','dur_ms':1000},
            {'kind':'dan_pulse','t_ms':3500,'source':'PPL101','dur_ms':500}]},pairing_interval_ms=interval)


@pytest.mark.parametrize('intensity',[float('nan'),float('inf'),-.1,1.1])
def test_test_intensity_is_validated_before_run(intensity):
    with pytest.raises(ValueError):
        compile_protocol({'blocks':[{'kind':'test','t_ms':0,'odours':['OCT'],'dur_ms':10,'intensity':intensity}]})


def test_instantaneous_final_control_preserves_exact_recorded_duration(tmp_path):
    runtime=PlasticityRuntime(tmp_path)
    document={'blocks':[{'kind':'rest','t_ms':0,'dur_ms':10},
        {'kind':'control','t_ms':10,'dur_ms':0,'control_id':'intensity','value':.25}]}
    runner=ProtocolRunner(runtime,document,reset=False)
    runner.advance(100)
    assert runner.done and runtime.t_sim_ms==runner.protocol['duration_ms']==10
    assert runtime.events[-1]=={'t_sim_ms':10,'control_id':'intensity','value':.25}


@pytest.mark.parametrize('kind',['rest','iti','odour','dan_pulse','test'])
def test_zero_duration_remains_invalid_for_noncontrol_blocks(kind):
    with pytest.raises(ValueError,match='duration must be positive'):
        compile_protocol({'blocks':[{'kind':kind,'t_ms':0,'dur_ms':0}]})
