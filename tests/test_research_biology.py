from pathlib import Path
import copy

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from flybrain.enzymes import EnzymeSystem, normalize_enzyme_options, POOL_NAMES
from flybrain.neuromod.field import FieldEngine, FieldParameters, FIELD_SPECIES, SourceProjection
from flybrain.model_registry import choose_sector_provider, normalize_banc_neurons
from flybrain.selection import (compile_selection, slice_source_projection, BoundaryRecording,
                               BoundaryRecorder, normalize_selection)
from flybrain.peripheral import catalog, PeripheralRuntime
from flybrain.model_eye import build_model_eye_mapping
from flybrain.hybrid_engine import HybridEngine

P={'dt':.1,'dt_graded':.5,'v_rest':-52.,'v_reset':-52.,'v_threshold':-45.,
   'tau_membrane':20.,'tau_synapse':5.,'refractory':2.2,'synaptic_delay':1.8,
   'spike_weight':.275,'poisson_factor':250.,'voltage_min':-90.,'voltage_max':20.,
   'graded_tau_membrane':20.,'graded_tau_synapse':5.,'graded_rest':-52.,
   'graded_release':-54.,'graded_gain':.0001,'record_dt_ms':.1}


def field():
    p=FieldParameters(FIELD_SPECIES,.1,1.,5.,np.full(8,100.),np.zeros(8),np.full(8,50.),np.ones(8))
    return FieldEngine(p,('left','right'),np.zeros((2,2)))


def network():
    neurons=pd.DataFrame({'root_id':[11,22,33], 'entity_id':['banc:888:11','banc:888:22','banc:888:33'],
        'cell_type':['R7','target','source'],'cell_class':['photoreceptor_neuron','central','motor'],
        'native_cell_class':['photoreceptor_neuron','central','motor'],'super_class':['sensory','central','motor'],
        'side':['left','left','right'],'region':['eye','brain','cord'],'root_region':['eye_L','brain','cord'],
        'is_graded':[True,False,False], 'known_nt':['histamine','acetylcholine','acetylcholine'],
        'pos_x':[1.,2.,3.],'pos_y':[1.,2.,3.],'pos_z':[1.,2.,3.],
        'body_part_sensory':['front_leg','',''],'body_part_effector':['','','front_leg'],
        'peripheral_target_type':['chordotonal_organ','','tibia_flexor_muscle'],'nerve':['left_leg_nerve','','right_leg_nerve']})
    g=sparse.csr_matrix(([4.],([1],[0])),shape=(3,3),dtype=np.float32)
    s=sparse.csr_matrix(([2.],([1],[2])),shape=(3,3),dtype=np.float32)
    return {'neurons':neurons,'graded':g,'spiking':s,'reference':g+s,'manifest':{'model_hash':'test-model'},'model_id':'test'}


def test_fusion_recency_only_breaks_comparable_quality_tie():
    older={'provider':'old','publication_date':'2024-01-01','comparison_basis':'audited-A','quality':[1,.9]}
    newer={'provider':'new','publication_date':'2026-01-01','comparison_basis':'audited-A','quality':[1,.9]}
    assert choose_sector_provider([older,newer],'old')['provider']=='new'
    assert choose_sector_provider([older,dict(newer,quality=[1,.8])],'old')['provider']=='old'
    unresolved=choose_sector_provider([older,dict(newer,comparison_basis='incomparable')],'old')
    assert unresolved['provider']=='old' and unresolved['unresolved']


def test_banc_uses_materialization_identity_and_excludes_nonneurons():
    raw=pd.DataFrame({'banc_888_id':['10','20'],'root_id':['999','888'], 'super_class':['sensory','glia'],
        'cell_class':['photoreceptor_neuron','astrocyte'],'cell_type':['R7','glia'], 'neurotransmitter_verified':['histamine',None],
        'neurotransmitter_predicted':['histamine',None],'neurotransmitter_score':[.9,0.],
        'root_position_nm':['4000, 8000, 12000','0, 0, 0']})
    result=normalize_banc_neurons(raw)
    assert result.root_id.tolist()==[10] and result.native_latest_root_id.tolist()==['999']
    assert result.entity_id.tolist()==['banc:888:10']
    np.testing.assert_allclose(result[['pos_x','pos_y','pos_z']].to_numpy()*[.004,.004,.04],[[4,8,12]])


def test_selection_extracts_actual_graph_and_default_recorded_boundary():
    n=network(); selected=compile_selection(n,{'root_ids':['22']})
    assert selected['neurons'].root_id.tolist()==[22]
    assert selected['spiking'].shape==(1,1) and selected['spiking'].nnz==0
    assert selected['selection']['incoming_cut_edges']==2
    assert selected['selection']['reference_required'] is True
    whole=compile_selection(n,{'root_ids':['22'],'boundary':'full_context'})
    assert len(whole['neurons'])==3 and whole['selection']['research_neurons']==1
    with pytest.raises(ValueError):compile_selection(n,{'entity_ids':['flywire:783:22']})
    with pytest.raises(ValueError):normalize_selection({'mode':'selected'})


def test_subset_source_projection_preserves_full_population_denominator():
    p=SourceProjection(('ACh',),('left',),sparse.csr_matrix([[.25,.25,.25,.25]]),np.array([[4]]),{})
    s=slice_source_projection(p,[1,3])
    assert s.source_counts[0,0]==4
    np.testing.assert_allclose(s.mean_rates_hz(np.array([10.,10.])),[[5.]])


def test_enzymes_off_exact_field_equivalence():
    a,b=field(),field(); enzymes=EnzymeSystem({'enabled':False},a.compartment_names)
    for _ in range(10):
        drive=np.ones(a.C.shape)*.5; drive[a.species.index("peptide_pool")]=0
        enzymes.step(a,drive); b.advance_drive(drive)
        np.testing.assert_array_equal(a.C,b.C)


def test_ache_replaces_selected_clearance_and_activity_changes_decay():
    a=field(); enzyme=EnzymeSystem({'enabled':True,'activities':{'ChAT':0,'Tbh':0,'AChE':0},'compartments':['left']},a.compartment_names)
    enzyme.configure_field(a); ach=a.species.index('ACh'); a.C[ach,:]=1.
    enzyme.step(a,np.zeros_like(a.C))
    assert a.C[ach,0]==1. and a.C[ach,1]<1.
    enzyme.set_activity('AChE',2.)
    before=float(a.C[ach,0]); enzyme.step(a,np.zeros_like(a.C))
    assert a.C[ach,0]<before
    assert enzyme.pools[POOL_NAMES.index('choline_product'),0]>0
    assert enzyme.pools[POOL_NAMES.index('choline_product'),1]==0


def test_synthesis_uses_intracellular_pools_and_tbh_does_not_consume_external_ta():
    a=field(); enzyme=EnzymeSystem({'enabled':True,'activities':{'AChE':0}},a.compartment_names)
    enzyme.configure_field(a); a.C[a.species.index('TA')]=1.
    before=enzyme.pools.copy(); enzyme.step(a,np.zeros_like(a.C))
    assert np.all(enzyme.pools[0]<before[0]) and np.all(enzyme.pools[2]>before[2])
    assert np.all(enzyme.pools[3]<before[3]) and np.all(enzyme.pools[4]>before[4])
    np.testing.assert_allclose(a.C[a.species.index('TA')],np.exp(-.01),rtol=1e-6)
    assert a.C[a.species.index('OA')].max()==0 # synthesis alone does not fabricate secretion


def test_enzyme_checkpoint_replays_precursors_and_fluxes():
    a=field(); enzyme=EnzymeSystem({'enabled':True},a.compartment_names);enzyme.configure_field(a)
    drive=np.ones_like(a.C); drive[a.species.index('peptide_pool')]=0
    for _ in range(3):enzyme.step(a,drive)
    saved=enzyme.snapshot();saved_c=a.C.copy()
    enzyme.step(a,drive);expected=enzyme.snapshot();expected_c=a.C.copy()
    enzyme.restore(saved);a.C[:]=saved_c;enzyme.step(a,drive)
    np.testing.assert_array_equal(enzyme.pools,expected['pools']);np.testing.assert_array_equal(enzyme.total_flux,expected['total_flux'])
    np.testing.assert_array_equal(a.C,expected_c)
    with pytest.raises(ValueError):enzyme.set_activity('AChE',float('nan'))
    with pytest.raises(ValueError):normalize_enzyme_options({'activities':{'invented':1}})


def test_peripheral_anatomical_modules_and_causal_state_feedback():
    table=network()['neurons']; modules=catalog(table)
    muscle=next(x for x in modules if x['kind']=='muscle')
    sense=next(x for x in modules if x.get('subdivision')=='chordotonal_organ')
    assert muscle['output_indices']==[2] and sense['input_indices']==[0]
    runtime=PeripheralRuntime(neurons=table,options={'enabled':True,'modules':[muscle['id'],sense['id']], 'external_inputs':{sense['id']:1.}})
    runtime.advance([0,0,50],100.)
    indices,drive=runtime.membrane_drive();assert indices.tolist()==[0] and drive[0]>0
    saved=runtime.snapshot();runtime.advance([0,0,0],100.);expected=runtime.state.copy()
    runtime.restore(saved);runtime.advance([0,0,0],100.);np.testing.assert_array_equal(runtime.state,expected)


def test_peripheral_signal_changes_actual_neural_voltage():
    n=network(); module=next(x for x in catalog(n['neurons']) if x.get('subdivision')=='chordotonal_organ')
    organ=PeripheralRuntime(neurons=n['neurons'],options={'enabled':True,'modules':[module['id']],'external_inputs':{module['id']:1.}})
    organ.advance([0,0,0],100.)
    stimulated=HybridEngine(n['graded'],n['spiking'],n['neurons'].is_graded.to_numpy(),P,threads=1)
    control=HybridEngine(n['graded'],n['spiking'],n['neurons'].is_graded.to_numpy(),P,threads=1)
    indices,drive=organ.membrane_drive()
    stimulated.run(10.,membrane_input_indices=indices,membrane_input_drive=np.tile(drive,(100,1)))
    control.run(10.)
    assert stimulated.v[0]>control.v[0]
    assert stimulated.v[1]>control.v[1]


def test_provider_optics_labels_modeled_columns_and_keeps_unknown_side_unassigned(tmp_path):
    n=network(); n['neurons'].loc[2,['native_cell_class','is_graded','side']]=['photoreceptor_neuron',True,'']
    mapping=build_model_eye_mapping(tmp_path,n)
    assert mapping.photoreceptor_indices.tolist()==[0]
    assert mapping.audit['modeled_photoreceptors']==1
    assert mapping.audit['photoreceptors_unassigned']==1
    assert 'ASSUMPTION' in mapping.assignments.assignment_source.iloc[0]


def test_fine_recorded_boundary_restores_delay_state_and_matches_reference(tmp_path):
    n=network(); full=HybridEngine(n['graded'],n['spiking'],n['neurons'].is_graded.to_numpy(),P,threads=1)
    full.v[0]=-45.;full.v[2]=-44.
    full.run(1.,record_indices=[0])
    selected=compile_selection(n,{'root_ids':['22']})
    recorder=BoundaryRecorder(full,n,selected['selection'],'same-protocol',3.)
    full.record_stride=1
    expected=[]
    for _ in range(30):
        expected.append(full.v[1]);recorder.add_chunk(full.run(.1,record_indices=recorder.record_indices))
    boundary=recorder.finish();boundary.save(tmp_path/'reference')
    boundary=BoundaryRecording.load(tmp_path/'reference')
    local=HybridEngine(selected['graded'],selected['spiking'],np.array([False]),P,threads=1)
    boundary.apply_initial_state(local)
    start=local.step;result=local.run(3.,record_indices=[0],**boundary.slice(start,30))
    np.testing.assert_allclose(result['voltages'][:,0],expected,rtol=0,atol=1e-5)
    with pytest.raises(ValueError):boundary.validate_reference(model_hash='wrong',selection_hash=selected['selection']['selection_hash'],dt_ms=.1)
    with pytest.raises(ValueError):boundary.slice(start-1,1)


def test_provider_chemistry_runs_enzyme_state_without_legacy_counts():
    from flybrain.provider_chemistry import build_model_chemistry
    from flybrain.wholebrain_neuromod import WholeBrainNeuromodEngine
    root=Path(__file__).resolve().parents[1];n=network()
    options={'enabled':True,'plasticity_enabled':False,'enzymes':{'enabled':True}}
    engine=WholeBrainNeuromodEngine(n['graded'],n['spiking'],n['neurons'].is_graded.to_numpy(),P,threads=1,
        neuromod=options,chemistry_factory=lambda e:build_model_chemistry(root,e,n,options))
    result=engine.run(2.,record_indices=[0,1,2])
    assert result['chemistry']['enzyme_pools_au'].shape[0]==20
    assert engine.chemistry.enzymes.time_ms==2.
    assert engine.chemistry.mapping.names==('brain','cord','eye_L','hemolymph')


def test_reduced_chemical_enzyme_and_organ_boundaries_preserve_full_denominators(tmp_path):
    from flybrain.provider_chemistry import build_model_chemistry
    from flybrain.peripheral import build_model_peripheral
    from flybrain.wholebrain_neuromod import WholeBrainNeuromodEngine
    root=Path(__file__).resolve().parents[1];n=network()
    n['neurons']['root_region']='shared'
    selected=compile_selection(n,{'root_ids':['11','22']})
    sensory=next(x for x in catalog(n['neurons']) if x.get('subdivision')=='chordotonal_organ')
    organs={'enabled':True,'modules':[sensory['id']], 'external_inputs':{sensory['id']:.8},
            'modeled_links':[{'module_id':sensory['id'],'direction':'efferent','entity_ids':['banc:888:33']}]}
    chemical={'enabled':True,'plasticity_enabled':False,'enzymes':{'enabled':True}}
    def make(net):
        e=WholeBrainNeuromodEngine(net['graded'],net['spiking'],net['neurons'].is_graded.to_numpy(),P,threads=1,
            neuromod=chemical,chemistry_factory=lambda e:build_model_chemistry(root,e,net,chemical))
        e.organs=build_model_peripheral(net,organs)
        return e
    def tick(e,record,arrival=None):
        indices,drive=e.organs.membrane_drive()
        result=e.run(1.,record_indices=record,record_dtype=np.float64,
            membrane_input_indices=indices,membrane_input_drive=np.tile(drive,(10,1)),**(arrival or {}))
        targets=np.bincount(result['spike_indices'],minlength=e.n_neurons)*1000.
        targets[e.graded_mask]=np.maximum(0.,e.v[e.graded_mask]-e.parameters['graded_release'])*5.
        targets*=e.output_enabled
        rates=e.organs.rates_hz+-np.expm1(-1/20.)*(targets-e.organs.rates_hz)
        e.organs.advance(rates,1.)
        return result
    full=make(n);full.chemistry.rates_hz[:]=[20.,10.,45.];full.organs.rates_hz[:]=[10.,10.,50.]
    full.v[2]=-44.;tick(full,[0,1])
    recorder=BoundaryRecorder(full,n,selected['selection'],'coupled',4.)
    expected=[]
    for _ in range(4):
        recorder.prepare_chunk();part=tick(full,recorder.record_indices);recorder.add_chunk(part)
        expected.append((full.v[:2].copy(),full.g[:2].copy(),full.chemistry.field.C.copy(),full.chemistry.enzymes.pools.copy(),full.organs.state.copy()))
    boundary=recorder.finish();boundary.save(tmp_path/'coupled');boundary=BoundaryRecording.load(tmp_path/'coupled')
    assert boundary.chemical_sources.shape==(4,8,2)
    assert boundary.component_data['organ_motor_sum_hz'].shape==(4,1)
    local=make(selected);boundary.apply_initial_state(local)
    for voltage,g,fields,pools,organ_state in expected:
        tick(local,[0,1],boundary.slice(local.step,10))
        np.testing.assert_allclose(local.v,voltage,rtol=0,atol=2e-9)
        np.testing.assert_allclose(local.g,g,rtol=0,atol=2e-9)
        np.testing.assert_array_equal(local.chemistry.field.C,fields)
        np.testing.assert_allclose(local.chemistry.enzymes.pools,pools,rtol=0,atol=1e-12)
        np.testing.assert_allclose(local.organs.state,organ_state,rtol=0,atol=1e-14)
    assert local.chemistry.field.projection.source_counts.tolist()==full.chemistry.field.projection.source_counts.tolist()
    assert local.organs.modules[0]['source_output_count']==1 and local.organs.modules[0]['output_indices']==[]


def test_model_versions_keep_original_executable_artifacts(tmp_path):
    from flybrain.model_registry import _freeze_model, get_model_manifest, stable_hash
    from flybrain.fetch import checksum
    from flybrain.inspect_data import atomic_write_json
    folder=tmp_path/'build/models/example';folder.mkdir(parents=True)
    def freeze(content):
        (folder/'values.npy').write_bytes(content)
        manifest={'id':'example','output_hashes':{'values.npy':checksum(folder/'values.npy')}}
        manifest['model_hash']=stable_hash(manifest)
        _freeze_model(tmp_path,folder,manifest);atomic_write_json(folder/'manifest.json',manifest)
        return manifest
    first=freeze(b'original');second=freeze(b'new version')
    assert first['model_hash']!=second['model_hash']
    assert get_model_manifest(tmp_path,'example@'+first['model_hash'])==first
    assert (tmp_path/'build/model-versions'/first['model_hash']/'values.npy').read_bytes()==b'original'
    assert get_model_manifest(tmp_path,'example')==second
    with pytest.raises(ValueError):get_model_manifest(tmp_path,'other@'+first['model_hash'])


@pytest.mark.parametrize('include_kc',[False,True])
def test_recorded_legacy_chemistry_preserves_endocrine_clock_and_plastic_state(include_kc):
    from flybrain.wholebrain_neuromod import WholeBrainChemistry,WholeBrainNeuromodEngine
    from flybrain.neuromod.compartments import CompartmentMap,MB_NAMES
    from flybrain.neuromod.state import EndocrineState,StateParameters,read_endocrine_sources
    from flybrain.neuromod.plasticity import PlasticityParameters
    from flybrain.neuromod.receptors import read_receptors
    root=Path(__file__).resolve().parents[1]
    endocrine_table=read_endocrine_sources(root/'config/endocrine_sources.csv');entry=next(r for r in endocrine_table if r['hormone']=='insulin')
    neurons=pd.DataFrame({'root_id':[1,2,3,4], 'cell_type':[entry['cell_type'],'KCg','MBON01','PAM01'],
        'cell_class':['endocrine','Kenyon_Cell','MBON','DAN'], 'super_class':['endocrine','central','central','central'],
        'known_nt':[entry['positive_nt'],'acetylcholine; sNPF','gaba','dopamine; nitric oxide'], 'is_graded':[False]*4})
    membership=np.zeros((16,4),bool);membership[0,1:]=True;membership[-1,0]=True
    mapping=CompartmentMap(MB_NAMES+('hemolymph',),membership,np.zeros((16,16)),np.array([-1,-1,0,0]),neurons.root_id.to_numpy(),{})
    g=sparse.csr_matrix((4,4));s=sparse.csr_matrix(([100.,20.],([2,1],[1,3])),shape=(4,4))
    n={'neurons':neurons,'graded':g,'spiking':s,'reference':g+s,'model_id':'flywire-783','manifest':{'model_hash':'legacy-fixture'}}
    selected=compile_selection(n,{'root_ids':['2','3'] if include_kc else ['3','4']})
    options={'enabled':True,'plasticity_enabled':True,'enzymes':{'enabled':True}}
    fp=FieldParameters(FIELD_SPECIES,.1,1.,5.,np.full(8,100.),np.zeros(8),np.full(8,50.),np.ones(8))
    nm={'dt_plast_ms':1.,'state_source_max_rate_hz':50.,'runtime_rate_tau_ms':20.,'state_dt_ms':2.,'max_kc_rate_hz':100.}
    def make(net):
        def chemistry(engine):
            return WholeBrainChemistry(engine,net['neurons'],mapping,options,fp,read_receptors(root/'config/receptors.csv'),
                EndocrineState(neurons,StateParameters(dt_ms=2.),endocrine_table,require_complete=False),nm,
                PlasticityParameters(),np.ones(15),np.ones(15),source_neurons=neurons,model_indices=net.get('parent_neuron_indices'))
        return WholeBrainNeuromodEngine(net['graded'],net['spiking'],net['neurons'].is_graded.to_numpy(),P,threads=1,neuromod=options,chemistry_factory=chemistry)
    full=make(n);full.v[:]=-44.;full.chemistry.rates_hz[:]=[40.,60.,10.,45.];full.run(1.)
    recorder=BoundaryRecorder(full,n,selected['selection'],'legacy',4.);expected=[]
    for _ in range(4):
        recorder.prepare_chunk();recorder.add_chunk(full.run(1.,record_indices=recorder.record_indices,record_dtype=np.float64))
        expected.append((full.v[selected['parent_neuron_indices']].copy(),full.chemistry.field.C.copy(),dict(full.chemistry.state.hormones)))
    boundary=recorder.finish();local=make(selected);boundary.apply_initial_state(local)
    for voltage,fields,hormones in expected:
        local.run(1.,**boundary.slice(local.step,10))
        np.testing.assert_allclose(local.v,voltage,atol=1e-10,rtol=0)
        np.testing.assert_allclose(local.chemistry.field.C,fields,atol=1e-8,rtol=0)
        assert local.chemistry.state.hormones==hormones


def test_recorded_silencing_preserves_pending_arrivals_and_delivery_time_weights():
    n=network();full=HybridEngine(n['graded'],n['spiking'],n['neurons'].is_graded.to_numpy(),P,threads=1)
    full.v[2]=-44.;full.run(1.)
    selected=compile_selection(n,{'root_ids':['22']})
    recorder=BoundaryRecorder(full,n,selected['selection'],'silence',3.)
    expected=[]
    for tick in range(3):
        full.output_enabled[[0,2]]=False
        full.csc_counts[:]=.5 if tick==0 else 3.
        recorder.prepare_chunk();recorder.add_chunk(full.run(1.,record_indices=recorder.record_indices,record_dtype=np.float64))
        expected.append((full.v[1],full.g[1]))
    boundary=recorder.finish();local=HybridEngine(selected['graded'],selected['spiking'],np.array([False]),P,threads=1)
    boundary.apply_initial_state(local)
    assert np.any(boundary.spike_delta>0) # spike enqueued before silencing survives
    assert np.count_nonzero(boundary.spike_delta)==1
    for voltage,g in expected:
        local.run(1.,**boundary.slice(local.step,10))
        np.testing.assert_allclose([local.v[0],local.g[0]],[voltage,g],atol=1e-12,rtol=0)


def test_provider_retains_all_out_release_receptors_without_fabricating_mb_compartments():
    from flybrain.provider_chemistry import build_model_chemistry
    from flybrain.wholebrain_neuromod import WholeBrainNeuromodEngine
    root=Path(__file__).resolve().parents[1];n=network()
    n['neurons'].loc[2,['cell_type','known_nt']]=['PAM01','dopamine']
    opts={'enabled':True,'plasticity_enabled':False,'chemical_levels':{'DA':1.},'chemical_control_mode':'clamped'}
    def make():
        return WholeBrainNeuromodEngine(n['graded'],n['spiking'],n['neurons'].is_graded.to_numpy(),P,threads=1,
            neuromod=opts,chemistry_factory=lambda e:build_model_chemistry(root,e,n,opts))
    active=make();control=make()
    row=next(i for i,(r,_) in enumerate(control.chemistry.effects.rows) if r['id']=='DA_Dop2R_release_prob')
    control.chemistry.effects.row_magnitude[row]=0.;control.chemistry.update_effects()
    assert np.all(active.chemistry.mapping.mb_assignment==-1)
    assert np.min(active.chemistry.effects.release)<1
    for e in (active,control):e.v[2]=-44.;e.run(2.)
    assert active.g[1]<control.g[1]
