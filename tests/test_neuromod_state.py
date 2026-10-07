from dataclasses import replace
import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from flybrain.neuromod.state import (EndocrineState, StateParameters, MBONValence,
    read_endocrine_sources, valence_from_rates)

ROOT = Path(__file__).resolve().parents[1]


def fixture(parameters=None):
    table = read_endocrine_sources(ROOT / 'config/endocrine_sources.csv')
    rows=[]
    for row in table:
        for _ in range(row['expected_model_count']):
            rows.append(dict(cell_type=row['cell_type'], super_class='endocrine',
                             known_nt=row['positive_nt']))
    rows += [dict(cell_type='PAM01',super_class='central',known_nt='dopamine'),
             dict(cell_type='OA-AL2b2',super_class='central',known_nt='tyramine'),
             dict(cell_type='OA-VPM3',super_class='central',known_nt='octopamine'),
             dict(cell_type='KCg',super_class='central',known_nt='acetylcholine; sNPF'),
             dict(cell_type='CSD',super_class='central',known_nt='serotonin')]
    neurons=pd.DataFrame(rows)
    neurons['root_id']=np.arange(len(neurons),dtype=np.int64)+1000
    return EndocrineState(neurons,parameters or StateParameters(),table),neurons


def test_exact_inventory_no_invented_hormones_or_currents():
    state,_=fixture()
    assert state.endocrine_mask.sum()==76
    assert state.identified_mask.sum()==52
    assert 'akh' not in state.family_masks
    out=state.outputs()
    assert not out['endocrine_drive'][~state.identified_mask].any()
    assert 'current' not in out and 'membrane_current' not in out
    assert state.rows[-1]['driver_line']==''


def test_source_annotations_not_top_nt_or_names_control_release():
    state,neurons=fixture()
    neurons['top_nt']='dopamine'
    other=EndocrineState(neurons,state.parameters,state.rows)
    np.testing.assert_array_equal(other.oa_mask,state.oa_mask)
    neurons.loc[neurons.cell_type.eq('IPC'),'known_nt']='DILP2-negative; DILP3; DILP5'
    with pytest.raises(ValueError,match='positive peptide'):
        EndocrineState(neurons,state.parameters,state.rows)


def test_exact_relaxation_energy_hydration_arousal_and_circadian():
    state,_=fixture()
    p=state.parameters
    state.step(p.dt_ms,locomotion=1,aversive=1)
    assert state.state['energy']==pytest.approx(np.exp(-p.dt_ms/p.energy_depletion_tau_ms))
    assert state.state['hydration']==pytest.approx(np.exp(-p.dt_ms/p.hydration_loss_tau_ms))
    assert state.state['arousal']==pytest.approx(-np.expm1(-p.dt_ms/p.arousal_tau_ms))
    assert state.state['stress']==pytest.approx(-np.expm1(-p.dt_ms/p.stress_tau_ms))
    assert state.state['circadian_phase']==pytest.approx(p.dt_ms/p.circadian_period_ms)


def test_hormone_response_uses_actual_identified_source_activity():
    state,_=fixture()
    rate=np.zeros(state.n)
    rate[state.family_masks['insulin']]=10
    before=state.hormones['insulin']
    state.step(state.parameters.dt_ms,rate)
    assert state.hormones['insulin']>before
    assert state.clamp_events==0


def test_release_clamps_are_counted_without_assigning_unknowns():
    state,_=fixture()
    state.step(state.parameters.dt_ms,np.full(state.n,1000.))
    assert state.clamp_events==52
    assert np.all(state.endocrine_drive[state.identified_mask]==1)
    assert not state.endocrine_drive[~state.identified_mask].any()


def test_fed_starved_changes_pam_gain_without_parameters_or_weights():
    fed,_=fixture()
    starved=fed.clone()
    starved.reset({'energy':0})
    assert fed.parameter_hash==starved.parameter_hash
    a,b=fed.outputs(),starved.outputs()
    assert b['gain_factor'][fed.pam_mask].min()>a['gain_factor'][fed.pam_mask].max()
    np.testing.assert_array_equal(a['gain_factor'][~fed.pam_mask],1)
    np.testing.assert_array_equal(b['gain_factor'][~fed.pam_mask],1)
    assert not hasattr(fed,'weights')


def test_arousal_changes_only_annotated_oa_and_circadian_aminergic_scaling():
    state,neurons=fixture()
    state.apply_control('arousal',1.)
    scale=state.outputs()['source_rate_scale']
    assert scale[neurons.cell_type.eq('OA-VPM3')][0]>1
    assert scale[neurons.cell_type.eq('OA-AL2b2')][0]==1
    state.apply_control('circadian_phase',.25)
    scale=state.outputs()['source_rate_scale']
    assert np.all(scale[state.da_mask|state.ht_mask]>1)
    assert scale[neurons.cell_type.eq('KCg')][0]==1


def test_controls_clone_restore_replay_and_json_save(tmp_path):
    a,_=fixture(); b=a.clone()
    for state in (a,b):
        state.apply_control('nutritional_state','starved')
        state.step(1000,feeding=.2)
        state.apply_control('hydration',.3)
        state.step(1000,locomotion=.7)
    assert a.snapshot()==b.snapshot()
    b.reset();b.restore(a.snapshot());assert b.snapshot()==a.snapshot()
    a.save(tmp_path/'state.json')
    import json
    assert json.loads((tmp_path/'state.json').read_text())==a.snapshot()
    a.step(1000)
    assert a.snapshot()!=b.snapshot()


@pytest.mark.parametrize('field,value',[('parameter_hash','bad'),('model_identity_hash','bad'),('source_table_hash','bad'),('t_sim_ms',.3),('clamp_events',-1)])
def test_bad_snapshot_is_rejected_without_mutation(field,value):
    state,_=fixture();before=state.snapshot();bad=copy.deepcopy(before);bad[field]=value
    with pytest.raises(ValueError):state.restore(bad)
    assert state.snapshot()==before


@pytest.mark.parametrize('kind',['negative_rate','nan_rate','wrong_dt','bad_drive','bad_control'])
def test_bad_steps_and_controls_preserve_state(kind):
    state,_=fixture();before=state.snapshot()
    with pytest.raises(ValueError):
        if kind=='negative_rate':state.step(1000,np.full(state.n,-1))
        if kind=='nan_rate':state.step(1000,np.full(state.n,np.nan))
        if kind=='wrong_dt':state.step(500)
        if kind=='bad_drive':state.step(1000,feeding=2)
        if kind=='bad_control':state.apply_control('energy',2)
    assert state.snapshot()==before


def test_valence_signed_types_unknowns_and_type_normalization():
    neurons=pd.DataFrame({'cell_type':['MBON01','MBON01','MBON11','MBON35','KCg']})
    reader=MBONValence(neurons,ROOT/'config/mbon_valence.csv')
    assert reader.coverage['signed_types']==2
    assert reader.evaluate([10,10,0,100,100])==-5
    assert reader.evaluate([0,0,10,100,100])==5
    assert valence_from_rates(neurons,[0,0,10,100,100],ROOT)==5
    with pytest.raises(ValueError):reader.evaluate([np.nan]*5)


def test_callback_state_evidence_binds_full_runtime_and_rejects_stale_input(tmp_path,monkeypatch):
    from flybrain.neuromod.state import _bind_trial_provenance
    from flybrain.rt import engine_rt
    from flybrain.fetch import checksum
    files={'config/parameters.yaml':'tau: 20','src/flybrain/rt/kernel.py':'actual kernel',
           'src/flybrain/rt/validation.py':'actual callback runner','build/compartments.npz':'actual mapping'}
    for name,value in files.items():
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value)
    hashes={name:checksum(tmp_path/name) for name in files}
    monkeypatch.setattr(engine_rt,'runtime_fingerprint',lambda root:('identity',hashes))
    proof={'config_hashes':{'parameters.yaml':hashes['config/parameters.yaml']},
           'implementation_hashes':{name:digest for name,digest in hashes.items() if name.startswith('src/')},
           'dependency_hashes':{'build/compartments.npz':hashes['build/compartments.npz']}}
    result={key:{} for key in proof}
    _bind_trial_provenance(tmp_path,result,proof)
    assert result==proof
    bad=copy.deepcopy(proof);bad['implementation_hashes'].pop('src/flybrain/rt/kernel.py')
    with pytest.raises(ValueError,match='missing or changed'):_bind_trial_provenance(tmp_path,result,bad)
    (tmp_path/'src/flybrain/rt/kernel.py').write_text('different kernel')
    with pytest.raises(ValueError,match='provenance changed'):_bind_trial_provenance(tmp_path,result,proof)
    with pytest.raises(ValueError,match='explicit runtime provenance'):_bind_trial_provenance(tmp_path,result,None)
