"""Experimental eye-driven whole-brain playback, retaining all failed gates.

This deliberately separate experiment is permitted to continue through an unstable
pre-equilibration. It neither changes the audited dynamics nor certifies biology.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
import importlib.metadata
from pathlib import Path
import platform
import resource
import subprocess
import time
import uuid
import numpy as np
import yaml

from .build import load_network
from .config import parameters
from .eye import build_eye_mapping, gaussian_ray_samples, Phototransduction
from .fetch import checksum
from .hybrid_engine import HybridEngine
from .record import run_directory
from .stimuli import normalize_options, luminance, preview_frames
from .validate_hybrid import summarize_endpoint
from .memguard import check_memory
from .stimulation import (normalize_lab_options, resolve_electrodes, input_layout,
                          combined_drive, electrode_waveform)

INPUT_FILES = ('config/parameters.yaml','config/visual_parameters.yaml',
               'data/raw/codex/column_assignment.csv','src/flybrain/engine.py',
               'src/flybrain/hybrid_engine.py','src/flybrain/eye.py',
               'src/flybrain/stimuli.py','src/flybrain/stimulation.py','src/flybrain/visual_experiment.py')


from .experiment_session import (STATE_ARRAYS, SESSION_KEYS, snapshot_state, restore_state,
    normalize_session_options, compile_timeline, InterventionSet, SessionControl, BranchSession,
    model_fingerprint, read_checkpoint, remaining_intervals, estimate_session_memory, validate_timeline_targets)


def read_visual_parameters(root):
    doc = yaml.safe_load((Path(root)/'config/visual_parameters.yaml').read_text())
    for key, entry in doc['parameters'].items():
        if not {'value','unit','source'} <= set(entry) or entry['source'] == 'ASSUMPTION' and not entry.get('sweep'):
            raise ValueError('Missing visual parameter provenance: '+key)
        if not np.isfinite(entry['value']) or entry['value'] <= 0:
            raise ValueError('Visual parameter must be finite and positive: '+key)
    return {key: entry['value'] for key,entry in doc['parameters'].items()}


def scene_at(options, timeline, time_ms, frame_rate=240.):
    for block in timeline or []:
        if block['kind'] == 'rest' and block['start_ms'] <= time_ms < block['end_ms']:
            return options | {'contrast':0.}, time_ms-block['start_ms']
        if block['kind'] == 'visual' and block['start_ms'] <= time_ms < block['end_ms']:
            keys = {'stimulus','duration_ms','speed_deg_s','direction_deg','contrast','mean_luminance',
                    'spatial_period_deg','grating_waveform','apparent_interval_ms','apparent_separation_columns','threads'}
            overrides = block.get('options', {})
            if not isinstance(overrides,dict) or set(overrides)-keys:
                raise ValueError('Unknown visual timeline option')
            scene = normalize_options({k:v for k,v in options.items() if k in keys} | overrides,
                frame_rate, eye_spacing_deg=options['eye_spacing_deg'],
                point_radius_columns=options['apparent_flash_radius_deg']/options['eye_spacing_deg'],
                flash_onset_ms=options['apparent_flash_onset_ms'])
            return scene, time_ms-block['start_ms']
    return options, time_ms


def layered_scene(layers,time_ms,frame_rate):
    frame=int(np.floor(time_ms*frame_rate/1000.+1e-10))
    for layer in reversed(layers):
        local=time_ms-layer['input_origin_ms']
        if frame>=layer['first_frame'] and (layer is layers[0] or any(b['kind'] in {'visual','rest'} and b['start_ms']<=local<b['end_ms'] for b in layer['timeline'])):
            return scene_at(layer['options'],layer['timeline'],local,frame_rate)
    return scene_at(layers[0]['options'],layers[0]['timeline'],time_ms,frame_rate)


def timeline_preview_frames(times_ms, options, timeline=None, width=96, height=48, *, layers=None,frame_rate=240.):
    if not timeline and not layers:
        return preview_frames(times_ms,options,width=width,height=height)
    az, el = np.meshgrid(np.linspace(-180,180,width,endpoint=False),np.linspace(90,-90,height))
    frames=[]
    for t in times_ms:
        scene,local=layered_scene(layers,t,frame_rate) if layers else scene_at(options,timeline,t,frame_rate)
        frames.append(np.rint(255*luminance(az,el,local,scene)).astype(np.uint8))
    return np.stack(frames)


def eye_movie(mapping, options, visual_params, frame_rate=240., fwhm_deg=5.7, *, baseline=False, initial_state=None, optics_seed=783, progress=None, timeline=None):
    times = np.arange(int(np.ceil(options['duration_ms']*frame_rate/1000.)))*1000./frame_rate
    if not len(mapping.columns):
        empty=np.empty((len(times),0),np.float64)
        return times,empty,empty.copy(),{'adaptation':np.empty(0),'drive':np.empty(0)}
    if baseline or (not timeline and options['stimulus'] in ('dark','flash')):
        coordinates = np.zeros(len(mapping.columns))
        light = np.stack([luminance(coordinates,coordinates,t,options,baseline=baseline) for t in times])
    else:
        az,el = gaussian_ray_samples(mapping.columns,fwhm_deg,visual_params['optics_samples'],optics_seed)
        light = np.empty((len(times),len(mapping.columns)))
        for i,t in enumerate(times):
            if i%8==0:
                check_memory()
                if progress:
                    progress({'phase':'optics','message':f'Rendering Gaussian eye input: {i}/{len(times)} frames',
                              'simulated_ms':float(t),'duration_ms':options['duration_ms']})
            scene, local = scene_at(options,timeline,t,frame_rate)
            light[i]=luminance(az,el,local,scene).mean(axis=1)
    transduction = Phototransduction(len(mapping.columns), visual_params, initial_luminance=0.)
    if initial_state is not None:
        transduction.adaptation[:] = initial_state['adaptation']
        transduction.drive[:] = initial_state['drive']
    drive = np.empty_like(light)
    for i, values in enumerate(light):
        # Start-slot convention matches engine voltage sampling: no future filter state.
        drive[i] = transduction.drive
        transduction.step(np.clip(values,0,1), 1000./frame_rate)
    return times, np.clip(light,0,1), drive, {'adaptation':transduction.adaptation.copy(), 'drive':transduction.drive.copy()}


def check_optics_convergence(mapping, options, frame_times, light, visual_params, fwhm_deg, seed, timeline=None, layers=None):
    """Bound a representative numerical comparison without claiming global proof."""
    count = int(visual_params['optics_samples'])
    if not len(mapping.columns):
        return {'passed':True,'status':'NOT_APPLICABLE','scope':'No mapped optical input in this model; no optical convergence claim.',
                'max_abs_luminance_error':0.,'tolerance':float(visual_params['optics_convergence_tolerance']),
                'sample_count':0,'columns_compared':0}
    reference_count = min(count*4,65536)
    if reference_count <= count:
        raise ValueError('optics_samples must leave room for a denser reference (maximum 16384)')
    columns = np.unique(np.linspace(0,len(mapping.columns)-1,min(128,len(mapping.columns)),dtype=int))
    flashes = [options['apparent_onset_frame'],options['apparent_onset_frame']+options['apparent_interval_frames']]
    frames = np.unique(np.concatenate((np.linspace(0,len(frame_times)-1,min(6,len(frame_times)),dtype=int),flashes)))
    frames = frames[(frames>=0)&(frames<len(frame_times))]
    if not timeline and not layers and options['stimulus'] in ('dark','flash'):
        errors = np.zeros((len(frames),len(columns)))
    else:
        az,el = gaussian_ray_samples(mapping.columns.iloc[columns],fwhm_deg,reference_count,seed)
        reference = []
        for i in frames:
            frame_rate=1000./(frame_times[1]-frame_times[0])
            scene,local=layered_scene(layers,frame_times[i],frame_rate) if layers else scene_at(options,timeline,frame_times[i],frame_rate)
            reference.append(luminance(az,el,local,scene).mean(axis=1))
        reference=np.stack(reference)
        errors = np.abs(light[np.ix_(frames,columns)]-reference)
    maximum = float(errors.max())
    return {'method':'spherical tangent Gaussian; deterministic scrambled Sobol rays',
            'sample_count':count,'seed':int(seed),'fwhm_deg':float(fwhm_deg),
            'reference_sample_count':reference_count,'columns_compared':len(columns),
            'frame_times_compared_ms':frame_times[frames].tolist(),
            'max_abs_luminance_error':maximum,'mean_abs_luminance_error':float(errors.mean()),
            'tolerance':float(visual_params['optics_convergence_tolerance']),
            'passed':bool(maximum <= visual_params['optics_convergence_tolerance']),
            'scope':'Representative numerical sampling comparison; not a proof of global convergence or biological validity.'}


def assert_sources_unchanged(root, hashes):
    for name, expected in hashes.items():
        if checksum(Path(root)/name) != expected:
            raise ValueError('Source changed during visual simulation; result not finalized: '+name)


def _run_branch(engine, options, mapping, drive_frames, frame_rate, records, progress, phase,
                electrodes=None, **session_kwargs):
    return BranchSession(engine, options, mapping, drive_frames, frame_rate, records,
                         progress=progress, phase=phase, electrodes=electrodes, **session_kwargs).run()


def _traces(neurons, records, raw, baseline):
    types = neurons.cell_type.fillna('')
    groups = [('R1-6', types.eq('R1-6')), ('R7/R8', types.isin(['R7','R8'])),
              ('L1', types.eq('L1')), ('L2',types.eq('L2')), ('Mi1',types.eq('Mi1'))]
    groups += [(kind,types.eq(kind)) for kind in ['T4a','T4b','T4c','T4d','T5a','T5b','T5c','T5d','LPLC2']]
    groups += [('HS/VS',types.str.startswith(('HS','VS'))),('Descending',neurons.super_class.eq('descending'))]
    traces = []
    for name,mask in groups:
        take = mask.to_numpy()[records]
        if take.any():
            actual, control = raw[:,take].mean(axis=1), baseline[:,take].mean(axis=1)
            traces.append({'name':name, 'n_recorded':int(take.sum()), 'n_total':int(mask.sum()),
                           'raw_mv':actual.tolist(),'baseline_mv':control.tolist(),
                           'delta_mv':(actual-control).tolist()})
    return traces


def runtime_metadata(root, seed):
    """Process evidence captured while the completed run arrays remain resident."""
    try:
        git_hash = subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True,
                                           stderr=subprocess.DEVNULL).strip()
        git_dirty = bool(subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True,
                                                stderr=subprocess.DEVNULL).strip())
    except (subprocess.CalledProcessError,FileNotFoundError):
        git_hash,git_dirty = None,None
    versions = {}
    for name in ('flybrain','numpy','scipy','numba','pandas','pyarrow','brian2','PyYAML'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {'git_hash':git_hash,'git_dirty':git_dirty,'versions':versions,
            'seed':int(seed),'random_input':'none; deterministic scene and neural dynamics',
            'platform':platform.platform(),'python_version':platform.python_version(),
            'peak_rss_bytes':int(peak if platform.system() == 'Darwin' else peak*1024),
            'peak_rss_scope':'Process lifetime high-water resident memory; a persistent server process may include earlier runs.'}


def run_visual_experiment(root, options=None, progress=None, *, frame=None, control=None, _reference_recovery=None):
    """Run/persist full-brain paired experiment; return compact JSON-ready playback.

    progress receives a dictionary {phase,message,simulated_ms?,duration_ms?}.
    activity_path points to NPZ with node_indices, time_ms, raw_mv, baseline_mv,
    delta_mv, and full spike trains. All displayed activity comes from these runs.
    """
    root = Path(root).resolve()
    input_hashes = {name:checksum(root/name) for name in INPUT_FILES}
    # These adapters participate even when chemistry is disabled. Fixture roots
    # may use the installed package; record the actual imported source then.
    for name in ('experiment_session.py','model_registry.py','selection.py','provider_chemistry.py','peripheral.py','model_eye.py','enzymes.py'):
        path=root/'src/flybrain'/name
        key='src/flybrain/'+name if path.exists() else str(Path(__file__).parent/name)
        input_hashes[key]=checksum(root/key)
    from .wholebrain_neuromod import (normalize_neuromod_options, WholeBrainNeuromodEngine,
                                      CHEMICAL_INPUT_FILES)
    supplied_options=dict(options or {})
    session_options=normalize_session_options({key:supplied_options.pop(key) for key in list(supplied_options) if key in SESSION_KEYS})
    fork = None
    preparation_fork=False
    if session_options.get('from_checkpoint'):
        fork_manifest, fork = read_checkpoint(root,session_options['from_checkpoint'])
        if fork['context']['phase'].startswith('reference_'):
            request=fork['context'].get('reference_request_options')
            if request is None: raise ValueError('This historical reference checkpoint lacks its reconstruction request')
            allowed_overrides={'from_checkpoint','live_chunk_ms'}
            for key,value in dict(options or {}).items():
                if key not in allowed_overrides and value!=request.get(key):
                    raise ValueError('Finish reference checkpoint recovery before changing '+key)
            recovered={'manifest':fork_manifest,'engine':fork['engine'],'model_hash':fork['context'].get('model_hash')}
            if progress: progress({'phase':'reconstructing_reference','message':'Rebuilding the recorded reference prefix deterministically before restoring its saved state'})
            return run_visual_experiment(root,request,progress,frame=frame,control=control,_reference_recovery=recovered)
        preparation_fork=fork['context']['phase']=='preequilibration'
        if preparation_fork and session_options.get('branch_time_ms') is not None:
            raise ValueError('Resume preparation first; branch_time_ms addresses a stimulus trajectory')
        target=session_options.get('branch_time_ms')
        visited=set()
        while target is not None and target < fork['context']['input_origin_ms']:
            visited.add(fork_manifest['id'])
            initial=fork['context'].get('initial_checkpoint_id')
            if not initial or initial in visited: initial=fork['context'].get('parent_checkpoint_id')
            if not initial or initial in visited:
                raise ValueError('Earlier branch time requires a preceding or initial checkpoint')
            fork_manifest,fork=read_checkpoint(root,initial)
        if target is not None and not fork['context']['input_origin_ms'] <= target < fork['context']['input_origin_ms']+fork['context']['remaining_ms']:
            raise ValueError('branch_time_ms must lie within the checkpoint optical trajectory')
        canonical = {'stimulus','duration_ms','speed_deg_s','direction_deg','contrast','mean_luminance',
            'spatial_period_deg','grating_waveform','apparent_interval_ms','apparent_separation_columns',
            'threads','neural_overrides','visual_overrides','record_dt_ms','electrodes','neuromod'}
        inherited = {k:v for k,v in fork['context'].get('experiment_options',fork['context']['options']).items() if k in canonical}
        electrode_keys={'id','label','target','voltage_mv','frequency_hz','duty_percent','start_ms','end_ms','phase_deg'}
        inherited['electrodes']=[{k:v for k,v in e.items() if k in electrode_keys} for e in inherited.get('electrodes',[])]
        inherited.update(supplied_options)
        supplied_options = inherited
        for key in ('model_id','research_selection','modules','recording_selection'):
            if key not in session_options and key in fork['context'].get('session_options',{}):
                session_options[key]=fork['context']['session_options'][key]
        if preparation_fork:
            for key in ('timeline','interventions'):
                if key not in session_options and key in fork['context'].get('session_options',{}):
                    session_options[key]=fork['context']['session_options'][key]
    chemical_options=normalize_neuromod_options(supplied_options.pop('neuromod',None))
    if chemical_options['enabled']:
        input_hashes.update({name:checksum(root/name) for name in CHEMICAL_INPUT_FILES})
    base_params,base_visual = parameters(root),read_visual_parameters(root)
    requested_duration=supplied_options.get('duration_ms')
    if fork is not None and requested_duration is not None and requested_duration<300:
        supplied_options['duration_ms']=300
    options,params,visual,resource_estimate = normalize_lab_options(supplied_options,base_params,base_visual)
    options['neuromod']=chemical_options
    if fork is not None and not preparation_fork:
        offset=session_options.get('branch_time_ms',fork['context']['input_origin_ms'])-fork['context']['input_origin_ms']
        options['duration_ms']=min(requested_duration if requested_duration is not None else options['duration_ms'],fork['context']['remaining_ms']-offset)
    has_organs=bool(session_options.get('modules')) and (not isinstance(session_options['modules'],dict) or session_options['modules'].get('enabled',False))
    timeline = compile_timeline(session_options.get('timeline'), options['duration_ms'], params['dt'],
        state_tick_ms=1. if chemical_options['enabled'] or has_organs else params['dt'])
    interventions = list(session_options.get('interventions', []))
    interventions += [dict(b.get('intervention', {}), start_ms=b['start_ms'], end_ms=b['end_ms'])
                      for b in timeline if b['kind'] == 'intervention']
    controller = SessionControl(control, progress, recovery=_reference_recovery)
    began = time.perf_counter()
    if progress:
        progress({'phase':'loading','message':'Verifying and loading the released whole-brain network'})
    if session_options.get('model_id') or (root/'build/neurons.parquet').exists():
        from .model_registry import load_model_network
        built=load_model_network(root,session_options.get('model_id','flywire-783'),
            model_hash=fork['context'].get('model_hash') if fork else _reference_recovery.get('model_hash') if _reference_recovery else None)
        session_options['model_id']=built['model_id']
    else:
        built = load_network(root)
    model_id=built.get('model_id','flywire-783')
    if 'manifest' not in built:
        from .model_registry import stable_hash
        built['manifest']={'id':model_id,'model_hash':stable_hash({'id':model_id,
            'output_hashes':built['summary'].get('output_hashes',{}),
            'root_ids':built['neurons'].root_id.astype(str).tolist()})}
    built['summary']=dict(built['summary'])
    built['summary'].setdefault('n_edges_released',built['graded'].nnz+built['spiking'].nnz)
    built['summary'].setdefault('output_hashes',{})
    if built.get('manifest',{}).get('optical_mapping_supported',True):
        mapping = build_eye_mapping(root, built['neurons'], built['reference'], spacing_deg=params['eye_spacing'],
                                    eye_center_deg=visual['eye_center_azimuth_deg'])
    else:
        from .model_eye import build_model_eye_mapping
        mapping=build_model_eye_mapping(root,built,spacing_deg=params['eye_spacing'],eye_center_deg=visual['eye_center_azimuth_deg'])
    full_network=built
    full_mapping=mapping
    boundary=None;baseline_boundary=None;automatic_reference=False
    if session_options.get('research_selection'):
        from .selection import compile_selection, remap_eye_mapping, BoundaryRecording
        built=compile_selection(built,session_options['research_selection'])
        mapping=remap_eye_mapping(mapping,built['parent_neuron_indices'])
        if built['selection']['reference_required']:
            reference=built['selection'].get('reference_id')
            if not reference:
                automatic_reference=True
            else:
                boundary=BoundaryRecording.load(root/'boundaries'/reference)
                baseline_boundary=BoundaryRecording.load(root/'boundaries'/(reference+'-baseline'))
    neurons = built['neurons']
    validate_timeline_targets(neurons,timeline,electrodes=options['electrodes'],interventions=session_options.get('interventions',[]))
    from .stimulation import normalize_electrodes
    preparation_options=dict(options,electrodes=list(options['electrodes']))
    electrode_origin=session_options.get('branch_time_ms',fork['context']['input_origin_ms']) if fork and not preparation_fork else 0.
    for block in timeline:
        if block['kind'] == 'electrode':
            options['electrodes'].extend(normalize_electrodes([dict(block.get('electrode', {}),
                start_ms=block['start_ms']+electrode_origin, end_ms=block['end_ms']+electrode_origin)], options['duration_ms']+electrode_origin, params['dt']))
    electrodes = resolve_electrodes(neurons,options['electrodes'])
    del built['reference']
    if np.any(~neurons.is_graded.to_numpy()[mapping.photoreceptor_indices]):
        raise ValueError('Mapped photoreceptor is not graded')
    records = np.asarray(options.pop('node_indices',np.arange(len(neurons))))
    if session_options.get('recording_selection'):
        from .selection import resolve_selection_indices
        records=resolve_selection_indices(neurons,session_options['recording_selection'])
    if records.ndim != 1 or not len(records) or records.dtype.kind not in 'iu' or len(np.unique(records)) != len(records) or np.any(records<0) or np.any(records>=len(neurons)):
        raise ValueError('node_indices must be unique valid neuron indices')
    records = records.astype(np.int32)
    resource_estimate['recorded_neurons']=len(records)
    resource_estimate['recording_float32_bytes']=resource_estimate['voltage_samples_per_neuron']*len(records)*4*3
    from .stimulation import MAX_RECORDING_BYTES
    if resource_estimate['recording_float32_bytes']>MAX_RECORDING_BYTES:
        raise ValueError('Selected model exceeds the full raw/baseline/delta recording allocation limit')
    resource_estimate['estimated_synaptic_edge_visits']=built['summary']['n_edges_released']*resource_estimate['total_neural_steps']
    engine_params = params | {'record_dt_ms':visual['display_sample_ms']}
    def make_engine(network):
        if chemical_options['enabled']:
            from .provider_chemistry import build_model_chemistry
            result=WholeBrainNeuromodEngine(network['graded'],network['spiking'],network['neurons'].is_graded.to_numpy(),engine_params,
                threads=options['threads'],root=root,neurons=network['neurons'],neuromod=chemical_options,
                chemistry_factory=lambda instance:build_model_chemistry(root,instance,network,chemical_options))
        else:
            result=HybridEngine(network['graded'],network['spiking'],network['neurons'].is_graded.to_numpy(),engine_params,threads=options['threads'])
        if session_options.get('modules') and (not isinstance(session_options['modules'],dict) or session_options['modules'].get('enabled',False)):
            from .peripheral import build_model_peripheral
            peripheral=session_options['modules']
            if isinstance(peripheral,list):peripheral={'enabled':True,'modules':peripheral}
            result.organs=build_model_peripheral(network,peripheral)
        return result
    engine=make_engine(built)
    resource_estimate.update(estimate_session_memory(engine,duration_ms=options['duration_ms'],recorded_neurons=len(records),
        boundary=boundary,paired_boundary=baseline_boundary,
        reference_steps=engine._steps(options['duration_ms'],'duration_ms') if automatic_reference else 0,
        selected_neurons=len(neurons)))
    if resource_estimate['estimated_additional_peak_bytes']>30_000_000_000:
        raise ValueError('Recordings, checkpoints and paired boundary buffers exceed the 30 GB additional allocation limit; shorten duration or select fewer neurons')
    from .model_registry import stable_hash
    reference_protocol_hash=(fork['context'].get('reference_protocol_hash') if fork else None) or stable_hash({'options':options,'timeline':timeline,'interventions':interventions,
        'modules':session_options.get('modules'),'params':params,'visual':visual,'input_hashes':input_hashes,
        'model_hash':built.get('manifest',{}).get('model_hash')})
    if automatic_reference or boundary is not None:
        if automatic_reference:
            from .selection import BoundaryRecorder
            reference_engine=make_engine(full_network)
            eq_options=options|{'duration_ms':params['pre_equilibration']}
            eq_times,eq_light,eq_drive,reference_transduction=eye_movie(full_mapping,eq_options,visual,params['frame_rate'],params['eye_fwhm'],baseline=True,optics_seed=params['seed'])
            request_keys={'stimulus','duration_ms','speed_deg_s','direction_deg','contrast','mean_luminance',
                'spatial_period_deg','grating_waveform','apparent_interval_ms','apparent_separation_columns',
                'threads','neural_overrides','visual_overrides','record_dt_ms','electrodes','neuromod'}
            request={key:value for key,value in preparation_options.items() if key in request_keys}|session_options
            electrode_keys={'id','label','target','voltage_mv','frequency_hz','duty_percent','start_ms','end_ms','phase_deg'}
            request['electrodes']=[{key:value for key,value in row.items() if key in electrode_keys} for row in request['electrodes']]
            request.pop('from_checkpoint',None);request.pop('branch_time_ms',None)
            reference_context={'session_options':session_options|{'live_chunk_ms':1.},'experiment_options':preparation_options,
                'reference_request_options':request,'model_id':model_id,'model_hash':full_network.get('manifest',{}).get('model_hash')}
            reference_live={'root':root,'control':controller,'context':reference_context,
                'fingerprint':model_fingerprint(reference_engine,full_network['neurons'].root_id,input_hashes|{
                    'model_hash':full_network.get('manifest',{}).get('model_hash'),'modules':session_options.get('modules'),
                    'neuromod':chemical_options,'selection_hash':built['selection']['selection_hash']})}
            _run_branch(reference_engine,eq_options,full_mapping,eq_drive,params['frame_rate'],np.empty(0,np.int32),progress,
                        'reference_preequilibration',**reference_live)
            reference_start=snapshot_state(reference_engine)
            ref_times,ref_light,ref_drive,_=eye_movie(full_mapping,options,visual,params['frame_rate'],params['eye_fwhm'],initial_state=reference_transduction,optics_seed=params['seed'],progress=progress,timeline=timeline)
            _,_,ref_control,_=eye_movie(full_mapping,options,visual,params['frame_rate'],params['eye_fwhm'],initial_state=reference_transduction,optics_seed=params['seed'],baseline=True)
            from .stimulation import ResolvedElectrode
            parent=np.asarray(built['parent_neuron_indices'])
            reference_electrodes=[ResolvedElectrode(e.definition,parent[e.indices].astype(np.int32)) for e in electrodes]
            reference_interventions=[]
            for definition in interventions:
                projected=dict(definition)
                for key in ('target','pre','post'):
                    if key in projected:
                        local=resolve_electrodes(neurons,[{'id':'reference-target','target':projected[key]}])[0].indices
                        projected[key]={'kind':'indices','indices':parent[local].tolist()}
                reference_interventions.append(projected)
            reference_live['context']['compiled_timeline']=[b for b in timeline if b['kind'] in {'chemical','enzyme'}]
            reference_engine.record_stride=1
            recorder=BoundaryRecorder(reference_engine,full_network,built['selection'],reference_protocol_hash,options['duration_ms'])
            _run_branch(reference_engine,options,full_mapping,ref_drive,params['frame_rate'],recorder.record_indices,progress,
                'reference_stimulus',electrodes=reference_electrodes,observer=recorder.add_chunk,retain_recording=False,record_dtype=np.float64,
                interventions=InterventionSet(reference_engine,full_network['neurons'],reference_interventions,options['duration_ms']),**reference_live)
            boundary=recorder.finish()
            restore_state(reference_engine,reference_start)
            reference_live['context']['compiled_timeline']=[]
            recorder=BoundaryRecorder(reference_engine,full_network,built['selection'],reference_protocol_hash,options['duration_ms'])
            _run_branch(reference_engine,options,full_mapping,ref_control,params['frame_rate'],recorder.record_indices,progress,
                'reference_baseline',observer=recorder.add_chunk,retain_recording=False,record_dtype=np.float64,**reference_live)
            baseline_boundary=recorder.finish()
            reference=uuid.uuid4().hex
            for recording,suffix in ((boundary,''),(baseline_boundary,'-baseline')):
                recording.metadata.update(graded_voltage_precision='float64 fine-step source records; native integration timestep',
                    optical_initial_state={k:v.tolist() for k,v in reference_transduction.items()})
                recording.save(root/'boundaries'/(reference+suffix))
            built['selection']['reference_id']=reference
            session_options['research_selection']=dict(session_options['research_selection'],reference_id=reference)
            del reference_engine,reference_start,recorder
            if controller.recovery is not None: raise ValueError('Saved reference phase/step was not reached during reconstruction')
        for recording in (boundary,baseline_boundary):
            recording.validate_reference(model_hash=built['selection']['model_hash'],selection_hash=built['selection']['selection_hash'],dt_ms=params['dt'],protocol_hash=reference_protocol_hash,
                parameter_hash=stable_hash(engine.parameters))
    del full_network,full_mapping
    built.pop('parent_source_neurons',None)
    del built['graded'],built['spiking']
    model_hash=built.get('manifest',{}).get('model_hash')
    selection=built.get('selection')
    fingerprint = model_fingerprint(engine, neurons.get('entity_id',neurons.root_id),
        input_hashes | {'model_hash':model_hash,'selection_hash':selection.get('selection_hash') if selection else None,
                        'modules':session_options.get('modules'),'neuromod':chemical_options})
    runtime_context = {'session_options':session_options, 'source_hashes':input_hashes,
                       'experiment_options':preparation_options,
                       'compiled_timeline':timeline, 'parent_checkpoint_id':session_options.get('from_checkpoint'),
                       'model_id':model_id,'model_hash':model_hash,'selection':selection,
                       'recording_selection':session_options.get('recording_selection'),
                       'reference_protocol_hash':reference_protocol_hash}
    if controller.recovered_from: runtime_context['recovered_reference_checkpoint_id']=controller.recovered_from
    live = {'root':root, 'frame':frame, 'control':controller, 'fingerprint':fingerprint,'boundary':boundary}
    if fork is None or preparation_fork:
        if progress:
            progress({'phase':'preequilibration','message':f"Running fixed {params['pre_equilibration']:g} ms mean-luminance pre-equilibration; instability is recorded"})
        if boundary is None:
            eq_options = options | {'duration_ms':params['pre_equilibration']}
            eq_times, eq_light, eq_drive, transduction_state = eye_movie(mapping,eq_options,visual,params['frame_rate'],params['eye_fwhm'],baseline=True,optics_seed=params['seed'])
            eq_origin=0.
            if preparation_fork:
                if fork_manifest['model_fingerprint']!=fingerprint: raise ValueError('Checkpoint model/configuration identity differs')
                restore_state(engine,fork['engine']);eq_origin=fork['context']['input_origin_ms']
                eq_options=eq_options|{'duration_ms':fork['context']['remaining_ms']}
            if eq_options['duration_ms']>0:
                eq = _run_branch(engine,eq_options,mapping,eq_drive,params['frame_rate'],np.empty(0,dtype=np.int32),progress,'preequilibration',
                                 context=runtime_context | {'options':options,'compiled_timeline':[],'recording_selection':None},input_origin_ms=eq_origin, **live)
                eq_summary = summarize_endpoint(neurons,eq['final_dvdt'],engine.per_neuron_clamp_counts,params['stationary_tolerance'])
            else:
                eq_summary={'status':'RESTORED_COMPLETE','source_checkpoint':fork_manifest['id']}
            if preparation_fork: eq_summary['resumed_from_checkpoint']=fork_manifest['id']
        else:
            boundary.apply_initial_state(engine)
            transduction_state={k:np.asarray(v,np.float64) for k,v in boundary.metadata['optical_initial_state'].items()}
            eq_times=np.empty(0);eq_light=np.empty((0,len(mapping.columns)));eq_drive=eq_light.copy()
            eq_summary={'status':'REFERENCE_STATE','reference_id':built['selection']['reference_id']}
        state = snapshot_state(engine)
        frame_times, eye_light, eye_drive, _ = eye_movie(mapping,options,visual,params['frame_rate'],params['eye_fwhm'],initial_state=transduction_state,optics_seed=params['seed'],progress=progress,timeline=timeline)
        _, control_light, control_drive, _ = eye_movie(mapping,options,visual,params['frame_rate'],params['eye_fwhm'],baseline=True,initial_state=transduction_state,optics_seed=params['seed'],progress=progress)
        optics = check_optics_convergence(mapping,options,frame_times,eye_light,visual,params['eye_fwhm'],params['seed'],timeline=timeline)
        input_origin_ms=0.
        baseline_electrodes=[]
        baseline_interventions=[]
        baseline_timeline=[b for b in timeline if b['kind']=='recording']
        scene_layers=[{'options':options.copy(),'timeline':timeline,'input_origin_ms':0.,'first_frame':0}]
        control_scene_layers=[{'options':options|{'stimulus':'grating','contrast':0.},'timeline':[],'input_origin_ms':0.,'first_frame':0}]
    else:
        if fork_manifest['model_fingerprint'] != fingerprint:
            raise ValueError('Checkpoint model/configuration identity differs')
        if fork['context']['phase'] not in ('stimulus','paired_baseline'):
            raise ValueError('Branch a stimulus or baseline checkpoint; preparation checkpoints are recovery evidence only')
        remaining = fork['context']['remaining_ms']
        if remaining <= 0:
            raise ValueError('Checkpoint has no remaining optical trajectory')
        options['duration_ms'] = min(options['duration_ms'],remaining)
        restore_state(engine,fork['engine'])
        saved=fork['context']
        target=session_options.get('branch_time_ms',saved['input_origin_ms'])
        advance=target-saved['input_origin_ms']
        if advance:
            engine._steps(advance,'branch_time_ms')
            reconstruction_timeline=remaining_intervals(saved.get('compiled_timeline',[]),saved['elapsed_ms'],advance)
            reconstruction_timeline=[b for b in reconstruction_timeline if b['kind'] in {'chemical','enzyme'}]
            reconstruction_interventions=remaining_intervals(saved.get('resolved_interventions',[]),saved['elapsed_ms'],advance)
            reconstruction_boundary=baseline_boundary if saved['phase']=='paired_baseline' else boundary
            _run_branch(engine,options|{'duration_ms':advance},mapping,np.asarray(saved['drive_frames']),saved['frame_rate'],
                np.empty(0,np.int32),progress,'reconstructing',root=root,control=controller,frame=frame,
                context=saved|{'compiled_timeline':reconstruction_timeline},fingerprint=fingerprint,
                input_origin_ms=saved['input_origin_ms'],electrodes=resolve_electrodes(neurons,saved.get('electrodes',[])),
                interventions=InterventionSet(engine,neurons,reconstruction_interventions,advance),
                boundary=reconstruction_boundary,retain_recording=False)
            saved=dict(saved,input_origin_ms=target,elapsed_ms=saved['elapsed_ms']+advance,
                       remaining_ms=saved['remaining_ms']-advance)
        state=snapshot_state(engine)
        runtime_context.update(chemical_original=saved.get('chemical_original'),enzyme_original=saved.get('enzyme_original',{}))
        eye_drive=np.asarray(saved['drive_frames'])
        control_drive=eye_drive.copy()
        eye_light=np.asarray(saved['eye_light'])
        control_light=eye_light.copy()
        frame_times=np.asarray(saved['frame_times'])
        transduction_state=saved['transduction_state']
        eq_times=np.empty(0);eq_light=np.empty((0,len(mapping.columns)));eq_drive=eq_light.copy()
        eq_summary={'status':'RESTORED','source_checkpoint':fork_manifest['id']}
        optics=saved['optics']
        input_origin_ms=saved['input_origin_ms']
        scene_layers=list(saved.get('scene_layers',[{'options':saved['options'],'timeline':saved.get('compiled_timeline',[]),
            'input_origin_ms':saved['input_origin_ms']-saved['elapsed_ms'],'first_frame':0}]))
        control_scene_layers=list(scene_layers)
        if boundary is not None:
            if saved['phase']=='paired_baseline':boundary=baseline_boundary
            baseline_boundary=boundary
            live['boundary']=boundary
        baseline_electrodes=resolve_electrodes(neurons,saved.get('electrodes',[]))
        baseline_interventions=remaining_intervals(saved.get('resolved_interventions',[]),saved['elapsed_ms'],options['duration_ms'])
        inherited_timeline=remaining_intervals(saved.get('compiled_timeline',[]),saved['elapsed_ms'],options['duration_ms'])
        inherited_timeline=[b for b in inherited_timeline if b['kind'] not in {'visual','rest','electrode','intervention'}
            and (b['kind']!='recording' or not any(row['kind']=='recording' for row in timeline))]
        baseline_timeline=inherited_timeline+[b for b in timeline if b['kind']=='recording']
        child_control_blocks=timeline+[{'kind':'intervention','start_ms':row.get('start_ms',0.),
            'end_ms':row.get('end_ms',options['duration_ms']),'intervention':row} for row in session_options.get('interventions',[])]
        validate_timeline_targets(neurons,child_control_blocks,
            electrodes=remaining_intervals([e.definition for e in baseline_electrodes],input_origin_ms,options['duration_ms']),
            interventions=baseline_interventions)
        # Parent interventions continue in both arms. New child changes only
        # affect the experimental arm and never mutate the checkpoint.
        interventions=baseline_interventions+interventions
        timeline=compile_timeline({'blocks':[dict(row,duration_ms=row['end_ms']-row['start_ms']) for row in inherited_timeline+timeline]},
            options['duration_ms'],params['dt'],state_tick_ms=1. if chemical_options['enabled'] or has_organs else params['dt'])
        if any(b['kind'] in {'visual','rest'} for b in timeline):
            # Recompute only future optical slots, carrying adaptation through
            # the preserved prefix. The active slot at the fork stays intact.
            first=int(np.floor(input_origin_ms*params['frame_rate']/1000.+1e-10))+1
            scene_layers.append({'options':options.copy(),'timeline':timeline,'input_origin_ms':input_origin_ms,'first_frame':first})
            eye_light=eye_light.copy();eye_drive=eye_drive.copy()
            az,el=gaussian_ray_samples(mapping.columns,params['eye_fwhm'],visual['optics_samples'],params['seed'])
            for i in range(first,len(frame_times)):
                scene,local=scene_at(options,timeline,frame_times[i]-input_origin_ms,params['frame_rate'])
                if any(b['kind'] in {'visual','rest'} and b['start_ms']<=frame_times[i]-input_origin_ms<b['end_ms'] for b in timeline):
                    eye_light[i]=luminance(az,el,local,scene).mean(axis=1)
            transduction=Phototransduction(len(mapping.columns),visual)
            transduction.adaptation[:]=transduction_state['adaptation'];transduction.drive[:]=transduction_state['drive']
            for i,values in enumerate(eye_light):
                if i>=first:eye_drive[i]=transduction.drive
                transduction.step(values,1000./params['frame_rate'])
            optics=check_optics_convergence(mapping,options,frame_times,eye_light,visual,params['eye_fwhm'],params['seed'],layers=scene_layers)
        # Both arms start at this checkpoint. The reference continues precisely
        # the recorded external optical trajectory, not a fresh dark baseline.
    if not optics['passed']:
        raise ValueError(f"Optics convergence check failed: {optics['max_abs_luminance_error']:.6g} exceeds {optics['tolerance']:g} normalized luminance")
    intervention_set = InterventionSet(engine,neurons,interventions,options['duration_ms'])
    runtime_context.update(eye_light=eye_light,frame_times=frame_times,transduction_state=transduction_state,optics=optics,
                           compiled_timeline=timeline,resolved_interventions=interventions,scene_layers=scene_layers,experiment_options=options)
    raw_session=BranchSession(engine,options,mapping,eye_drive,params['frame_rate'],records,progress=progress,phase='stimulus',
        electrodes=electrodes,context=runtime_context,interventions=intervention_set,input_origin_ms=input_origin_ms,**live)
    initial_checkpoint=raw_session.checkpoint('Initial experiment state')
    runtime_context['initial_checkpoint_id']=initial_checkpoint['id']
    raw_session.context['initial_checkpoint_id']=initial_checkpoint['id']
    controller.emit({'kind':'checkpoint','phase':'stimulus','checkpoint_id':initial_checkpoint['id'],'initial':True})
    raw=raw_session.run()
    restore_state(engine,state)
    del state
    baseline_context = runtime_context | {'compiled_timeline':baseline_timeline,'resolved_interventions':baseline_interventions,
        'eye_light':control_light,'scene_layers':control_scene_layers}
    control = _run_branch(engine,options,mapping,control_drive,params['frame_rate'],records,progress,'paired_baseline',
                          context=baseline_context,input_origin_ms=input_origin_ms,electrodes=baseline_electrodes,
                          interventions=InterventionSet(engine,neurons,baseline_interventions,options['duration_ms']),**(live|{'boundary':baseline_boundary or boundary}))
    if not np.array_equal(raw['voltage_times'],control['voltage_times']):
        raise RuntimeError('Paired sample times disagree')
    times = raw['voltage_times']
    delta = raw['voltages']-control['voltages']
    if progress:
        progress({'phase':'saving','message':'Saving neural recordings, electrode waveforms and run provenance'})
    directory = run_directory(root,'visual_'+options['stimulus'])
    neuron_path=directory/'neurons.parquet'
    neurons.to_parquet(neuron_path,index=False)
    electrode_definitions=[]
    waveform_times=np.arange(int(round(options['duration_ms']/engine.dt)))*engine.dt
    waveform_matrix=np.column_stack([electrode_waveform(e.definition,waveform_times+input_origin_ms) for e in electrodes]) if electrodes else np.empty((len(waveform_times),0))
    target_arrays={}
    for i,e in enumerate(electrodes):
        key=f'electrode_{i}'
        target_arrays[key]=e.indices
        electrode_definitions.append({k:v for k,v in e.definition.items() if k!='target_indices'} | {'target_array':key})
    np.savez_compressed(directory/'electrode_targets.npz',**target_arrays)
    np.savez_compressed(directory/'electrode_waveforms.npz',time_ms=waveform_times.astype(np.float32),input_mv=waveform_matrix.astype(np.float32))
    activity_path = directory/'activity.npz'
    np.savez_compressed(activity_path,node_indices=records,time_ms=times,raw_mv=raw['voltages'],
                        baseline_mv=control['voltages'],delta_mv=delta,
                        spike_indices=raw['spike_indices'],spike_times_ms=raw['spike_times'],
                        baseline_spike_indices=control['spike_indices'],baseline_spike_times_ms=control['spike_times'],
                        raw_clamps=raw['per_neuron_clamp_counts'],baseline_clamps=control['per_neuron_clamp_counts'])
    chemistry = {'schema_version':1,'enabled':False}
    peripheral={'schema_version':1,'enabled':False}
    if getattr(engine,'organs',None) is not None:
        organ_path=directory/'organs.npz'
        np.savez_compressed(organ_path,time_ms=times,state_values=raw['organs']['state_values'],
            baseline_state_values=control['organs']['state_values'])
        peripheral={'schema_version':1,'enabled':True,'time_ms':times.tolist(),
            'state_names':['activation','output','cumulative_effort_au_s'],
            'state_values':raw['organs']['state_values'].tolist(),
            'baseline_state_values':control['organs']['state_values'].tolist(),
            'modules':[{key:m.get(key) for key in ('id','label','status','modeled_links','source_output_count')} for m in engine.organs.modules],
            'recording_path':str(organ_path),'units':'Normalized modeled activation/output; accumulated effort in a.u. seconds',
            'sampling':'Organ state held during the neural sample integration tick; same time_ms as activity recording',
            'feedback':'Explicit modeled peripheral transfer dynamics driven by native neural outputs and saved external inputs',
            'options':engine.organs.options}
    if getattr(engine,'chemistry',None) is not None:
        coupling=engine.chemistry
        membership=coupling.membership[records].tocsr()
        chemical_arrays={'time_ms':times,'node_root_ids':neurons.root_id.to_numpy(np.int64)[records],
            'membership_indptr':membership.indptr,'membership_indices':membership.indices,
            'membership_weights':membership.data,
            **raw['chemistry'],**{'baseline_'+k:v for k,v in control['chemistry'].items()}}
        chemical_path=directory/'chemistry.npz'
        np.savez_compressed(chemical_path,**chemical_arrays)
        chemistry=coupling.metadata() | {'time_ms':times.tolist(),
            'neurons':len(records),'simulated_neurons':len(neurons),'node_indices':records.tolist(),
            'neuron_order':'Recording selection in activity.node_indices order',
            **{k:v.tolist() for k,v in raw['chemistry'].items()},
            **{'baseline_'+k:v.tolist() for k,v in control['chemistry'].items()},
            'neuron_membership':{'indptr':membership.indptr.tolist(),'indices':membership.indices.tolist(),
                                  'weights':membership.data.tolist()},
            'recording_path':str(chemical_path),'diagnostics':raw['chemistry_diagnostics'],
            'baseline_diagnostics':control['chemistry_diagnostics'],
            'paired_initialization':'Both branches restore the same preequilibrated voltages, delays, concentrations, rates, endocrine state, traces and synaptic weights.'}
        (directory/'chemistry.json').write_text(json.dumps(chemistry,separators=(',',':'),allow_nan=False)+'\n')
    np.savez_compressed(directory/'eye_input.npz',frame_times_ms=frame_times,luminance=eye_light,
                        drive_mv=eye_drive,baseline_drive_mv=control_drive,
                        photoreceptor_indices=mapping.photoreceptor_indices,
                        photoreceptor_columns=mapping.photoreceptor_columns,
                        preequilibration_times_ms=eq_times,preequilibration_luminance=eq_light,
                        preequilibration_drive_mv=eq_drive,
                        initial_adaptation=transduction_state['adaptation'],initial_drive_mv=transduction_state['drive'])
    preview = timeline_preview_frames(times + input_origin_ms,options,timeline,layers=scene_layers,frame_rate=params['frame_rate'])
    np.save(directory/'stimulus_frames.npy',preview)
    full_preview = timeline_preview_frames(frame_times,options,timeline,width=360,height=180,layers=scene_layers,frame_rate=params['frame_rate'])
    np.save(directory/'stimulus_full_frames.npy',full_preview)
    sample_frames = np.minimum(np.floor((times + input_origin_ms)*params['frame_rate']/1000.+1e-10).astype(int),len(eye_light)-1)
    old_gate_path = root/'build/validation_hybrid.json'
    old_gate = json.loads(old_gate_path.read_text()) if old_gate_path.exists() else {}
    assert_sources_unchanged(root,input_hashes)
    metadata = {
        **runtime_metadata(root,params['seed']),
        'created_at':datetime.now(timezone.utc).isoformat(),'status':'EXPERIMENTAL_UNVALIDATED',
        'completed':True,'session':session_options,'session_events':controller.events,'parent_checkpoint_id':session_options.get('from_checkpoint'),
        'initial_checkpoint_id':initial_checkpoint['id'],'recording_ids':{'raw':raw.get('recording_id'),'baseline':control.get('recording_id')},
        'options':options,'n_neurons':len(neurons),'n_recorded':len(records),
        'model_id':model_id,'model_hash':model_hash,'selection':selection,'model_fingerprint':fingerprint,
        'recording_selection':session_options.get('recording_selection'),'recorded_indices':records.tolist(),
        'recovered_reference_checkpoint_id':controller.recovered_from,
        'input_origin_ms':input_origin_ms,
        'neuron_table_path':str(neuron_path),'neuron_table_sha256':checksum(neuron_path),
        'n_edges_released':built['summary']['n_edges_released'],'synthetic_edges':0,'lamina_mode':'connectome',
        'engine':('WholeBrainNeuromodEngine; original graded/spiking network with compartment fields, receptor parameters, KC-to-MBON plasticity and endocrine state' if chemical_options['enabled'] else 'HybridEngine; graded/spiking equations with explicit additive virtual-electrode input'), 'integration_dt_ms':engine.dt,
        'sample_interval_ms':visual['display_sample_ms'],'render_frame_rate_hz':params['frame_rate'],
        'stimulus_definition':{'grating_waveform':options['grating_waveform'],
            'apparent_motion':'Two bright circular point flashes, each one stimulus frame, on mean-luminance background; simultaneous spots use logical OR.',
            'apparent_interval_requested_ms':options['apparent_interval_ms'],
            'apparent_interval_effective_ms':options['apparent_effective_interval_ms'],
            'apparent_interval_frames':options['apparent_interval_frames'],
            'apparent_point_radius_deg':options['apparent_flash_radius_deg'],
            'apparent_flash_onset_requested_ms':options['apparent_flash_onset_ms'],
            'apparent_flash_onset_effective_ms':options['apparent_effective_onset_ms'],
            'assumed_eye_spacing_deg':options['eye_spacing_deg']},
        'pre_equilibration_ms':params['pre_equilibration'],'preequilibration':eq_summary,
        'original_validation_status':old_gate.get('stage4_status','NOT-RUN'),
        'experimental_continuation':True,
        'baseline':('Both arms restore the same checkpoint, advanced deterministically to the chosen branch time when requested. Control continues inherited optical, electrode, chemical, enzyme and intervention inputs; new child changes affect only the experimental arm. Delta is the experimental arm minus this matched continuation. It is not a validated biological response.' if fork is not None and not preparation_fork else f"Same complete neural and phototransduction states after fixed {params['pre_equilibration']:g} ms mean-luminance pre-equilibration. "
            'Control continues stationary mean luminance with electrodes OFF at t=0. Both branches use the same effective neural parameters. Delta is stimulus plus electrode input minus that paired control at the same time; '
            'it is not a stability correction or a validated biological response.'),
        'external_input':('Both arms continue the saved optical and electrode inputs; only the experimental arm receives new child controls.' if fork and not preparation_fork else
            'Light drives mapped graded photoreceptors. Explicit virtual electrodes add membrane input only at the saved target indices; compatible inputs sum. The paired control has electrodes OFF.' if electrodes else 'Additive normalized membrane input to mapped graded photoreceptors; loaded organs contribute their documented modeled feedback.'),
        'neural_parameters':params,'visual_parameters':visual,'eye_audit':mapping.audit,
        'saved_base_neural_parameters':base_params,'saved_base_visual_parameters':base_visual,
        'runtime_overrides':{'neural':options['neural_overrides'],'visual':options['visual_overrides'],'record_dt_ms':options['record_dt_ms']},
        'resource_estimate':resource_estimate,'electrodes':electrode_definitions,
        'electrode_baseline':'Inherited parent inputs continue in the matched baseline' if fork and not preparation_fork else 'OFF in common pre-equilibration and paired baseline',
        'historical_validation_applicability':'Historical validation does not certify runtime parameter overrides or electrode experiments.',
        'neuromod':{k:v for k,v in chemistry.items() if k not in {'neuron_membership','time_ms','concentrations_au','baseline_concentrations_au','state_values','baseline_state_values','hormones_au','baseline_hormones_au','plasticity_change_l1','baseline_plasticity_change_l1'}},
        'peripheral':{k:v for k,v in peripheral.items() if k not in {'time_ms','state_values','baseline_state_values'}},
        'stimulus_clamp_count':raw['clamp_count'],'baseline_clamp_count':control['clamp_count'],
        'stimulus_spike_count':len(raw['spike_indices']),'baseline_spike_count':len(control['spike_indices']),
        'wall_seconds':time.perf_counter()-began,
        'input_hashes':input_hashes,'input_hashes_checked_unchanged':True,
        'optics':optics,
        'network_hashes':built['summary']['output_hashes'],
        'output_sha256':checksum(activity_path),
        'output_hashes':{name:checksum(directory/name) for name in ('activity.npz','eye_input.npz','stimulus_frames.npy','stimulus_full_frames.npy','electrode_targets.npz','electrode_waveforms.npz')},
    }
    warnings = ['V-C stability gate remains '+metadata['original_validation_status']+'. This is an experimental visualization.',
                'Raw activity includes autonomous unstable dynamics; paired deltas do not establish biological validity.',
                'Retinotopy orientation, transduction amplitude and kinetics are explicit assumptions.',
                f"{mapping.audit['photoreceptors_unassigned']} photoreceptors have no unambiguous optical assignment and receive no light input."]
    if electrodes:
        warnings.append('Electrodes are virtual mV-equivalent membrane inputs, not physical device voltages or a tissue electric-field model.')
    if chemical_options['enabled']:
        metadata['output_hashes'].update({name:checksum(directory/name) for name in ('chemistry.npz','chemistry.json')})
        metadata['historical_validation_applicability']='Historical base/core validation is preserved; it does not certify this new full-brain chemical coupling. This run remains experimental.'
        warnings.extend(chemistry['assumptions'])
    if peripheral['enabled']:
        metadata['output_hashes']['organs.npz']=checksum(directory/'organs.npz')
    if options['neural_overrides'] or options['visual_overrides']:
        warnings.append('Runtime parameter overrides are experimental; historical validation was performed with the original saved parameters.')
    for e in electrode_definitions:
        if e.get('assumption'): warnings.append(e['label']+': '+e['assumption'])
    waveform_preview_stride=max(1,int(np.ceil(len(waveform_times)/10000)))
    result = {
        'run_id':directory.name,'run_dir':str(directory),'metadata':metadata,
        'initial_checkpoint_id':initial_checkpoint['id'],'reference_id':selection.get('reference_id') if selection else None,
        'recording_ids':metadata['recording_ids'],
        'model_id':model_id,'model_hash':model_hash,'selection':selection,
        'neuron_table_path':str(neuron_path),
        'activity_path':str(activity_path),'stimulus_frames_path':str(directory/'stimulus_frames.npy'),
        'chemistry':chemistry,'chemistry_path':chemistry.get('recording_path'),
        'peripheral':peripheral,'peripheral_path':peripheral.get('recording_path'),
        'stimulus_full_frames_path':str(directory/'stimulus_full_frames.npy'),
        'stimulus_frame_times_ms':frame_times.tolist(),
        'time_ms':times.tolist(),
        'stimulation':{'definitions':electrode_definitions,'time_ms':waveform_times[::waveform_preview_stride].tolist(),
                       'input_mv':waveform_matrix[::waveform_preview_stride].tolist(),
                       'preview_stride_steps':waveform_preview_stride,'full_resolution_ms':engine.dt,
                       'waveforms_path':str(directory/'electrode_waveforms.npz'),'targets_path':str(directory/'electrode_targets.npz'),
                       'note':'Preview waveforms may be downsampled. Exact integration-step inputs and target indices are saved in NPZ files.'},
        'eye':{'columns':mapping.columns.assign(anchor_root_id=mapping.columns.anchor_root_id.astype(str)).to_dict('records'),
               'luminance':eye_light[sample_frames].astype(np.float32).tolist(),
               'drive_mv':eye_drive[sample_frames].astype(np.float32).tolist()},
        'traces':_traces(neurons,records,raw['voltages'],control['voltages']),
        'stats':{'max_abs_delta_mv':float(np.abs(delta).max()),
                 'mean_abs_delta_mv':float(np.abs(delta).mean()),
                 'responsive_neurons_above_0_001_mv':int(np.count_nonzero(np.max(np.abs(delta),axis=0)>.001)),
                 'spike_count':len(raw['spike_indices']),'baseline_spike_count':len(control['spike_indices']),
                 'clamp_count':raw['clamp_count'],'baseline_clamp_count':control['clamp_count']},
        'warnings':warnings}
    (directory/'run_manifest.json').write_text(json.dumps(metadata,indent=2,allow_nan=False)+'\n')
    (directory/'playback.json').write_text(json.dumps(result,separators=(',',':'),allow_nan=False)+'\n')
    (directory/'visual_result.json').write_text(json.dumps(result,separators=(',',':'),allow_nan=False)+'\n')
    if progress:
        progress({'phase':'complete','message':'Saved paired whole-brain simulation and eye input','run_id':directory.name})
    return result
