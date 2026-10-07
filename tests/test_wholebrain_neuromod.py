from pathlib import Path
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from flybrain.hybrid_engine import HybridEngine
from flybrain.wholebrain_neuromod import (WholeBrainNeuromodEngine, WholeBrainChemistry,
    normalize_neuromod_options, FIELD_SPECIES, STATE_NAMES)
from flybrain.neuromod.compartments import CompartmentMap, MB_NAMES
from flybrain.neuromod.field import FieldParameters
from flybrain.neuromod.receptors import read_receptors
from flybrain.neuromod.plasticity import PlasticityParameters
from flybrain.neuromod.state import EndocrineState, StateParameters, read_endocrine_sources
from flybrain.visual_experiment import snapshot_state, restore_state

ROOT=Path(__file__).resolve().parents[1]
P={'dt':.1,'dt_graded':.5,'v_rest':-52.,'v_reset':-52.,'v_threshold':-45.,
   'tau_membrane':20.,'tau_synapse':5.,'refractory':2.2,'synaptic_delay':1.8,
   'spike_weight':.275,'poisson_factor':250.,'voltage_min':-90.,'voltage_max':20.,
   'graded_tau_membrane':20.,'graded_tau_synapse':5.,'graded_rest':-52.,
   'graded_release':-54.,'graded_gain':.0001,'record_dt_ms':2.}


def fixture(*, rows=None, enabled=True, scenario='fed', neutral_state=False, plasticity=False,
            chemical_levels=None, chemical_control_mode='initial'):
    table=read_endocrine_sources(ROOT/'config/endocrine_sources.csv')
    cells=[{'cell_type':r['cell_type'],'known_nt':r['positive_nt'],'super_class':'endocrine','cell_class':'endocrine'} for r in table]
    cells += [dict(cell_type=t,known_nt=nt,super_class='central',cell_class=cl) for t,nt,cl in (
        ('KCg','acetylcholine; sNPF','Kenyon_Cell'),('MBON01','gaba','MBON'),
        ('PAM01','dopamine; nitric oxide','DAN'),('VS1','acetylcholine','optic'),
        ('L1','acetylcholine','optic'),('MBON02','glutamate','MBON'))]
    neurons=pd.DataFrame(cells);neurons['root_id']=np.arange(len(cells),dtype=np.int64)+100
    n=len(neurons);kc,mbon,pam,vs,photo,mbon2=np.arange(n-6,n)
    graded=np.zeros(n,bool);graded[[vs,photo]]=True
    neurons['is_graded']=graded
    membership=np.zeros((17,n),bool)
    membership[0,[kc,mbon,pam]]=True;membership[1,[kc,mbon2]]=True
    membership[15,[vs,photo]]=True;membership[16,:n-6]=True
    names=MB_NAMES+('optic','hemolymph')
    adjacency=np.zeros((17,17));adjacency[0,1]=adjacency[1,0]=1
    assignment=np.full(n,-1,np.int16);assignment[[mbon,pam]]=0;assignment[mbon2]=1
    mapping=CompartmentMap(names,membership,adjacency,assignment,neurons.root_id.to_numpy(),{})
    g=sparse.csr_matrix(([20000.,10.],([pam,vs],[photo,photo])),shape=(n,n))
    s=sparse.csr_matrix(([100.,100.,3.,-2.],([mbon,mbon2,kc,pam],[kc,kc,pam,mbon])),shape=(n,n))
    parameters=StateParameters(dt_ms=10.)
    if neutral_state:parameters=replace(parameters,pam_hunger_gain=0.,pam_insulin_suppression=0.)
    state=EndocrineState(neurons,parameters,table,require_complete=False)
    fp=FieldParameters(FIELD_SPECIES,.1,1.,5.,np.full(8,400.),np.array([0.,0.,0.,.001,0.,0.,0.,0.]),np.full(8,50.),np.ones(8))
    nm={'dt_plast_ms':1.,'state_source_max_rate_hz':50.,'runtime_rate_tau_ms':20.,'state_dt_ms':10.,'max_kc_rate_hz':100.}
    options={'enabled':enabled,'scenario':scenario,'plasticity_enabled':plasticity,
             'chemical_levels':{} if chemical_levels is None else chemical_levels,
             'chemical_control_mode':chemical_control_mode}
    def factory(engine):
        return WholeBrainChemistry(engine,neurons,mapping,options,fp,
            read_receptors(ROOT/'config/receptors.csv') if rows is None else rows,state,nm,
            PlasticityParameters(),np.ones(15),np.ones(15))
    engine=WholeBrainNeuromodEngine(g,s,graded,P,threads=1,neuromod=options,chemistry_factory=factory)
    return engine,neurons,mapping,g,s,(kc,mbon,pam,vs,photo,mbon2)


def compare(a,b,ra,rb):
    for k in ('spike_indices','spike_times','voltages','voltage_times','final_v','final_g','per_neuron_clamp_counts'):
        np.testing.assert_array_equal(ra[k],rb[k],err_msg=k)
    for k in ('v','g','last_spike','ring_counts','release_history'):
        np.testing.assert_array_equal(getattr(a,k),getattr(b,k))


@pytest.mark.parametrize('payload',[
    {'enabled':1},{'plasticity_enabled':1},{'scenario':'fake'}, {'initial_state':{'energy':float('nan')}},
    {'initial_state':{'energy':True}}, {'initial_state':{'circadian_phase':1}},
    {'feeding':-1},{'aversive':True},{'fake':0},
])
def test_options_reject_ambiguous_controls(payload):
    with pytest.raises(ValueError):normalize_neuromod_options(payload)


def test_scenario_presets_and_explicit_override():
    assert normalize_neuromod_options()['enabled'] is False
    assert normalize_neuromod_options({'scenario':'starved'})['initial_state']['energy']==0
    assert normalize_neuromod_options({'scenario':'dehydrated'})['initial_state']['hydration']==0
    assert normalize_neuromod_options({'scenario':'stressed'})['initial_state']['stress']==1
    assert normalize_neuromod_options({'scenario':'starved','initial_state':{'energy':.4}})['initial_state']['energy']==.4


def test_disabled_delegates_original_hybrid_bit_exact_with_continuation():
    e,neurons,_,g,s,ids=fixture(enabled=False)
    b=HybridEngine(g,s,neurons.is_graded.to_numpy(),P,threads=1)
    for duration,drive in ((4.,10.),(8.,0.),(2.,3.)):
        args=dict(record_indices=np.arange(len(neurons)),photoreceptor_indices=[ids[4]],photoreceptor_drive=drive)
        compare(e,b,e.run(duration,**args),b.run(duration,**args))
    assert e.chemistry is None


def test_neutral_active_kernel_preserves_original_hybrid_spikes_and_delays():
    e,neurons,_,g,s,ids=fixture(rows=[],neutral_state=True)
    b=HybridEngine(g,s,neurons.is_graded.to_numpy(),P,threads=1)
    e.v[[ids[0],ids[2]]]=-44.;b.v[[ids[0],ids[2]]]=-44.
    for duration,drive in ((10.,20.),(6.,0.)):
        args=dict(record_indices=np.arange(len(neurons)),photoreceptor_indices=[ids[4]],photoreceptor_drive=drive)
        compare(e,b,e.run(duration,**args),b.run(duration,**args))


def test_graded_receptor_gain_and_tau_change_actual_voltage_response():
    changed,_,_,_,_,ids=fixture()
    unchanged,*_=fixture()
    vs=ids[3]
    changed.chemistry.field.C[FIELD_SPECIES.index('OA'),15]=1.
    changed.chemistry.update_effects()
    assert changed.chemistry.effects.gain[vs]>1
    assert changed.chemistry.effects.tau_factor[vs]<1
    for engine in (changed,unchanged):
        engine.g[vs]=2.;engine.graded_counts.fill(0)
        engine.run(1.)
    assert changed.v[vs]>unchanged.v[vs]


def test_graded_source_contributes_field_without_fabricated_spikes():
    e,_,_,_,_,ids=fixture(rows=[])
    out=e.run(10.,record_indices=np.arange(e.n_neurons))
    si=FIELD_SPECIES.index('ACh')
    assert e.chemistry.field.C[si,15]>0
    assert not np.isin(out['spike_indices'],ids[3:5]).any()
    assert e.chemistry.rates_hz[ids[4]]>0
    assert out['chemistry']['concentrations_au'].shape==(5,8,17)
    assert out['chemistry']['concentrations_au'][0].max()==0
    assert out['chemistry']['concentrations_au'][-1,si,15]>0


def test_source_spiking_drives_da_and_saved_no_adjacency_spreads():
    e,_,_,_,_,ids=fixture(rows=[])
    pam=ids[2];e.v[pam]=-44
    e.run(12.)
    assert e.chemistry.field.C[FIELD_SPECIES.index('DA'),0]>0
    assert e.chemistry.field.C[FIELD_SPECIES.index('DA'),1]==0
    assert e.chemistry.field.C[FIELD_SPECIES.index('NO'),1]>0


def test_starvation_applies_immediately_and_changes_driven_pam_response():
    fed,_,_,_,_,ids=fixture(rows=[],scenario='fed')
    hungry,_,_,_,_,_=fixture(rows=[],scenario='starved')
    pam=ids[2]
    assert hungry.chemistry.effects.gain[pam]>fed.chemistry.effects.gain[pam]
    assert hungry.chemistry.state.state['energy']==0
    for e in (fed,hungry):e.g[pam]=2
    a=fed.run(1.,record_indices=[pam]);b=hungry.run(1.,record_indices=[pam])
    assert b['chemistry']['state_values'][0,STATE_NAMES.index('energy')]==0
    assert hungry.v[pam]>fed.v[pam]
    # Gain has no effect with no incoming current.
    hungry.reset();hungry.g.fill(0)
    hungry.graded_counts.fill(0)
    hungry.run(1.)
    assert hungry.v[pam]==P['v_rest']


def test_restore_repeats_complete_neural_field_state_and_plasticity():
    e,_,_,_,_,ids=fixture(plasticity=True)
    kc,_,pam,_,photo,_=ids
    # An existing eligibility trace and DA pulse make edge changes resolvable
    # at float32 weight precision during this short continuation fixture.
    e.chemistry.plasticity.e_pre.fill(.2)
    e.chemistry.field.C[FIELD_SPECIES.index('DA'),0]=1.
    e.chemistry.update_effects()
    e.v[[kc,pam]]=-44.;e.run(4.)
    checkpoint=snapshot_state(e)
    args=dict(record_indices=np.arange(e.n_neurons),photoreceptor_indices=[photo],photoreceptor_drive=20.)
    a=e.run(8.,**args);final=e.chemistry.snapshot()
    restore_state(e,checkpoint);b=e.run(8.,**args)
    for key in ('voltages','spike_indices','spike_times','final_v','final_g'):
        np.testing.assert_array_equal(a[key],b[key])
    for key in a['chemistry']:
        np.testing.assert_array_equal(a['chemistry'][key],b['chemistry'][key])
    for key in ('field_C','rates_hz','weights','e_pre','e_da'):
        np.testing.assert_array_equal(final[key],e.chemistry.snapshot()[key])
    assert e.chemistry.plasticity.total_absolute_weight_change>0
    np.testing.assert_array_equal(e.csc_counts[e.chemistry.plastic_csc],e.chemistry.plasticity.weights)


def test_release_scope_is_actual_postsynaptic_compartment_not_all_kc_outputs():
    rows=[r for r in read_receptors(ROOT/'config/receptors.csv') if r['id']=='sNPF_sNPFR_KC_release']
    e,_,_,_,_,ids=fixture(rows=rows)
    e.chemistry.field.C[FIELD_SPECIES.index('sNPF'),0]=1.
    e.chemistry.update_effects()
    effects=e.chemistry.effects;model=e.chemistry.receptors
    release=effects.release[effects.release_group]
    kc,mbon,_,_,_,mbon2=ids
    assert release[(model.edge_pre==kc)&(model.edge_post==mbon)][0]>1
    assert release[(model.edge_pre==kc)&(model.edge_post==mbon2)][0]==1


def test_identity_and_tick_contract_fail_closed_before_advancement():
    e,*_=fixture()
    before=e.v.copy()
    with pytest.raises(ValueError,match='whole 1-ms'):e.run(1.5)
    np.testing.assert_array_equal(e.v,before)
    assert e.step==0


def test_sparse_exposure_matches_multi_membership_mean_and_unassigned_is_explicit():
    e,_,mapping,_,_,ids=fixture()
    c=e.chemistry;values=np.arange(len(mapping.names),dtype=float)
    exposure=c.membership@values
    assert exposure[ids[0]]==.5
    np.testing.assert_allclose(np.asarray(c.membership.sum(axis=1)).ravel(),1)


@pytest.mark.parametrize('payload',[
    {'chemical_levels':[]}, {'chemical_levels':None}, {'chemical_levels':{'dopamine':1}},
    {'chemical_levels':{'DA':True}}, {'chemical_levels':{'DA':'1'}},
    {'chemical_levels':{'DA':None}}, {'chemical_levels':{'DA':[1]}},
    {'chemical_levels':{'DA':-0.001}}, {'chemical_levels':{'DA':2.001}},
    {'chemical_levels':{'DA':float('nan')}}, {'chemical_levels':{'DA':float('inf')}},
    {'chemical_levels':{'DA':10**1000}}, {'chemical_control_mode':True},
    {'chemical_control_mode':None}, {'chemical_control_mode':[]}, {'chemical_control_mode':'continuous'},
])
def test_chemical_control_validation_rejects_invalid_requests(payload):
    with pytest.raises(ValueError):normalize_neuromod_options(payload)


def test_chemical_control_normalization_preserves_missing_species_and_old_requests():
    old=normalize_neuromod_options({'enabled':True,'scenario':'starved'})
    assert old['chemical_levels']=={}
    assert old['chemical_control_mode']=='initial'
    normalized=normalize_neuromod_options({'chemical_levels':{'DA':0,'OA':2}})
    assert normalized['chemical_levels']=={'DA':0.,'OA':2.}
    assert 'NO' not in normalized['chemical_levels']


def test_all_eight_initial_levels_apply_before_first_receptor_evaluation_and_reset():
    levels={name:0.25*(i+1) for i,name in enumerate(FIELD_SPECIES)}
    e,_,_,_,_,ids=fixture(chemical_levels=levels)
    c=e.chemistry
    for name,value in levels.items():
        np.testing.assert_array_equal(c.field.C[FIELD_SPECIES.index(name)],value)
    assert c.effects.tau_factor[ids[3]]<1 # OA reaches the actual graded VS tau.
    assert c.effects.release[c.effects.release_group].max()>1 # sNPF KC->MBON.
    e.run(2.);e.reset()
    for name,value in levels.items():
        np.testing.assert_array_equal(c.field.C[FIELD_SPECIES.index(name)],value)


def test_initial_mode_evolves_selected_species_without_resetting_unspecified_sources():
    e,_,_,_,_,ids=fixture(chemical_levels={'DA':1.25})
    e.graded_counts.fill(0) # No DAN stimulation; other graded sources still release.
    out=e.run(4.,record_indices=[ids[2]])
    da=FIELD_SPECIES.index('DA');ach=FIELD_SPECIES.index('ACh')
    np.testing.assert_array_equal(out['chemistry']['concentrations_au'][0,da],1.25)
    np.testing.assert_allclose(e.chemistry.field.C[da],1.25*np.exp(-4/400),rtol=2e-7)
    assert e.chemistry.field.C[ach,15]>0
    assert out['chemistry']['concentrations_au'][-1,da,0]<1.25


def test_clamped_mode_is_applied_before_plasticity_and_next_receptor_effects(monkeypatch):
    e,_,_,_,_,ids=fixture(chemical_levels={'DA':1.,'OA':.5},chemical_control_mode='clamped',plasticity=True)
    c=e.chemistry;seen=[];original=c.plasticity.step
    def observe(drive,dopamine,dt):
        seen.append(dopamine.copy())
        return original(drive,dopamine,dt)
    monkeypatch.setattr(c.plasticity,'step',observe)
    e.run(4.,record_indices=[ids[2]])
    assert len(seen)==4
    for dopamine in seen:np.testing.assert_array_equal(dopamine,1.)
    np.testing.assert_array_equal(c.field.C[FIELD_SPECIES.index('DA')],1.)
    np.testing.assert_array_equal(c.field.C[FIELD_SPECIES.index('OA')],.5)
    assert c.field.C[FIELD_SPECIES.index('ACh'),15]>0
    assert c.effects.tau_factor[ids[3]]==pytest.approx(1-.25*.5)


def test_clamped_zero_suppresses_only_requested_species():
    e,_,_,_,_,ids=fixture(chemical_levels={'DA':0},chemical_control_mode='clamped')
    e.v[ids[2]]=-44.
    e.run(4.)
    np.testing.assert_array_equal(e.chemistry.field.C[FIELD_SPECIES.index('DA')],0)
    assert e.chemistry.field.C[FIELD_SPECIES.index('NO'),0]>0


@pytest.mark.parametrize('mode',['initial','clamped'])
def test_chemical_intervention_restores_paired_state_and_exports_provenance(tmp_path,mode):
    from flybrain.visual_assets import export_chemistry
    e,neurons,_,_,_,_=fixture(chemical_levels={'DA':.75},chemical_control_mode=mode)
    e.run(4.) # Common preequilibration must not be replaced by a fresh initial level.
    checkpoint=snapshot_state(e)
    a=e.run(4.,record_indices=[0]);restore_state(e,checkpoint);b=e.run(4.,record_indices=[0])
    for key in a['chemistry']:np.testing.assert_array_equal(a['chemistry'][key],b['chemistry'][key])
    if mode=='initial':assert a['chemistry']['concentrations_au'][0,0,0]<.75
    else:np.testing.assert_array_equal(a['chemistry']['concentrations_au'][:,0],.75)
    c=e.chemistry;m=c.membership;path=tmp_path/'chemistry.npz'
    np.savez(path,time_ms=a['voltage_times'],node_root_ids=neurons.root_id.to_numpy(),
        membership_indptr=m.indptr,membership_indices=m.indices,membership_weights=m.data,
        **a['chemistry'],**{'baseline_'+k:v for k,v in b['chemistry'].items()})
    summary=export_chemistry(tmp_path,{'chemistry_path':str(path),'chemistry':c.metadata()},
        neurons.root_id.to_numpy(),a['voltage_times'])
    assert summary['chemical_intervention']['mode']==mode
    assert summary['chemical_intervention']['levels_au']=={'DA':.75}
    assert summary['options']['chemical_control_mode']==mode
    assert summary['options']['chemical_levels']=={'DA':.75}


def test_disabled_chemical_intervention_keeps_original_path_bit_exact():
    e,neurons,_,g,s,ids=fixture(enabled=False,chemical_levels={name:2 for name in FIELD_SPECIES},chemical_control_mode='clamped')
    original=HybridEngine(g,s,neurons.is_graded.to_numpy(),P,threads=1)
    args=dict(record_indices=np.arange(len(neurons)),photoreceptor_indices=[ids[4]],photoreceptor_drive=20.)
    compare(e,original,e.run(4.,**args),original.run(4.,**args))
    assert e.chemistry is None
