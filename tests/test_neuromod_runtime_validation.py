from types import SimpleNamespace
import numpy as np
import pytest

from flybrain.rt.validation import execute_events,event,crossing_intervals,install_weights,_finish_gates


class Timeline:
    def __init__(self):self.t_sim_ms=0;self.actions=[]
    def reset(self,seed):self.t_sim_ms=0;self.actions=[]
    def advance(self,duration):self.t_sim_ms+=duration
    def control(self,key,value):self.actions.append((self.t_sim_ms,key,value))
    def snapshot(self):return {'time':self.t_sim_ms}


def test_event_boundaries_order_and_continuation_are_exact():
    runtime=Timeline()
    execute_events(runtime,[event(10,'off',False),event(0,'on',True),event(10,'other',1)],20)
    assert runtime.actions==[(0,'on',True),(10,'off',False),(10,'other',1)]
    execute_events(runtime,[event(2,'next',3)],5,reset=False)
    assert runtime.t_sim_ms==25 and runtime.actions[-1]==(22,'next',3)


@pytest.mark.parametrize('duration,events',[(.5,[]),(-1,[]),(np.nan,[]),(10,[event(11,'a',1)]),(10,[event(.5,'a',1)]),(10,[event(-1,'a',1)])])
def test_bad_timeline_rejected_before_reset(duration,events):
    runtime=Timeline();runtime.t_sim_ms=42
    with pytest.raises(ValueError):execute_events(runtime,events,duration)
    assert runtime.t_sim_ms==42


def test_frame_measurement_includes_each_advance_and_preserves_events():
    runtime=Timeline();timings=[]
    execute_events(runtime,[event(30,'a',1)],55,frame_timings=timings)
    assert [x['duration_ms'] for x in timings]==[20,10,20,5]
    assert runtime.actions==[(30,'a',1)] and runtime.t_sim_ms==55


def test_crossing_only_reports_observed_brackets_and_no_extrapolation():
    assert crossing_intervals([-2,-1,1],[2,1,-1])==[{'bracket_ms':[-1.,1.],'linear_interpolation_ms':0.}]
    assert crossing_intervals([-2,-1,1],[2,1,.2])==[]
    with pytest.raises(ValueError):crossing_intervals([1,0],[1,-1])


def test_weight_restore_updates_the_exact_runtime_csc_identity():
    rt=SimpleNamespace(plasticity=SimpleNamespace(weights=np.ones(2,np.float32)),
                       engine=SimpleNamespace(csc_counts=np.array([4,5,6,7],np.float32)),plastic_csc=np.array([1,3]))
    install_weights(rt,[.5,1.5])
    np.testing.assert_array_equal(rt.engine.csc_counts,[4,.5,6,1.5])
    before=rt.engine.csc_counts.copy()
    with pytest.raises(ValueError):install_weights(rt,[np.inf,1])
    np.testing.assert_array_equal(rt.engine.csc_counts,before)


def test_extracted_gate_rows_keep_both_parent_and_specific_provenance():
    result={'gates':{'J':{'gate':'J','config_hashes':{'j':'specific'}}},'config_hashes':{'runtime':'parent'},'artifact_hashes':{'curve':'hash'}}
    _finish_gates(result)
    assert isinstance(result['gates'],list)
    assert result['gates'][0]['config_hashes']=={'runtime':'parent','j':'specific'}
    assert result['gates'][0]['artifact_hashes']=={'curve':'hash'}


def test_runtime_completion_rechecks_transitive_prerequisites(monkeypatch,tmp_path):
    from flybrain.rt import validation
    def reject(root):raise ValueError('upstream compartment matrix changed')
    monkeypatch.setattr(validation,'require_plasticity_gate',reject)
    with pytest.raises(ValueError,match='upstream compartment'):
        validation._verify_provenance(tmp_path,{})
