"""Measured coupled-core protocols; biological failures remain visible results."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import psutil

from ..fetch import checksum
from ..inspect_data import atomic_write_json
from ..neuromod.state import validate_state, require_plasticity_gate
from .engine_rt import CoreRuntime


PAIRING_DELAYS_MS = (-2000, -1500, -1000, -750, -500, -250, 0, 250, 500, 1000, 1500, 2000)


def array_hash(values):
    return hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()


def execute_events(runtime, events, duration_ms, *, seed=7, reset=True, frame_timings=None):
    """Advance to each boundary; stable order retains equal-time user actions."""
    if isinstance(duration_ms, bool) or not np.isfinite(duration_ms) or duration_ms < 0 or int(duration_ms) != duration_ms:
        raise ValueError('Protocol duration must be a nonnegative integer number of ms')
    ordered = sorted(events, key=lambda e: e['t_sim_ms'])
    for item in ordered:
        when = item['t_sim_ms']
        if not np.isfinite(when) or int(when) != when or not 0 <= when <= duration_ms:
            raise ValueError('Protocol event does not lie on the integer-ms timeline')
    if reset:
        runtime.reset(seed)
    start = runtime.t_sim_ms
    previous = 0
    def advance_interval(duration):
        if frame_timings is None:
            runtime.advance(int(duration))
        else:
            for offset in range(0,int(duration),20):
                span=min(20,int(duration)-offset)
                clock=time.perf_counter()
                runtime.advance(span)
                frame_timings.append({'duration_ms':span,'wall_seconds':time.perf_counter()-clock})
    for event in ordered:
        when = event['t_sim_ms']
        if not np.isfinite(when) or int(when) != when or not previous <= when <= duration_ms:
            raise ValueError('Protocol event does not lie on the integer-ms timeline')
        advance_interval(when-previous)
        runtime.control(event['control_id'], event['value'])
        previous = when
    advance_interval(duration_ms-previous)
    if runtime.t_sim_ms != start+duration_ms:
        raise AssertionError('Scheduled duration differs from simulated duration')
    return runtime.snapshot()


def event(t, control, value):
    return {'t_sim_ms': t, 'control_id': control, 'value': value}


def pairing_events(handle='PPL101', odor='OCT', delay_ms=500):
    return [event(0, 'dan_type', handle), event(3000, 'odour', odor), event(4000, 'odour', 'air'),
            event(3000+delay_ms, 'dan_drive', 1.), event(3500+delay_ms, 'dan_drive', 0.)]


def install_weights(runtime, weights):
    weights = np.asarray(weights, np.float32)
    if weights.shape != runtime.plasticity.weights.shape or not np.isfinite(weights).all() or np.any(weights < 0):
        raise ValueError('Invalid trained weight vector')
    runtime.plasticity.weights[:] = weights
    runtime.engine.csc_counts[runtime.plastic_csc] = weights


def odor_test(runtime, odor, *, seed=7, weights=None, state_snapshot=None, duration_ms=1000):
    """Fresh fast state and adaptation, fixed memory, measured window spike rates."""
    if not np.isfinite(duration_ms) or duration_ms <= 0 or int(duration_ms) != duration_ms:
        raise ValueError('Odor test duration must be a positive integer number of ms')
    runtime.reset(seed)
    runtime.control('plasticity.enabled', False)
    if weights is not None:
        install_weights(runtime, weights)
    if state_snapshot is not None:
        runtime.state.restore(state_snapshot)
        runtime.control('state.energy', state_snapshot['state']['energy'])
    before = array_hash(runtime.plasticity.weights)
    runtime.control('odour', odor)
    runtime.advance(duration_ms)
    rates = runtime.spike_totals.astype(float)*1000/duration_ms
    result = {'valence': runtime.valence.evaluate(rates),
              'weights_sha256_before': before, 'weights_sha256_after': array_hash(runtime.plasticity.weights),
              'stimulus_sha256': hashlib.sha256(json.dumps({'odor': odor, 'duration_ms': duration_ms, 'seed': seed}, sort_keys=True).encode()).hexdigest(),
              'parameter_sha256': runtime.config_hash, 'spikes': int(runtime.spike_totals.sum()),
              'kc_active_fraction': float(np.mean(runtime.spike_totals[runtime.kc_indices]>0)),
              'voltage_out_of_bounds': runtime.voltage_out_of_bounds,
              'valence_scope': 'Window-mean inferred MBON signed rate; body readout NOT-RUN'}
    return result


def crossing_intervals(delays, values):
    """Observed zero brackets only; interpolation is labeled diagnostic, not fitting."""
    x, y = np.asarray(delays, float), np.asarray(values, float)
    if x.shape != y.shape or x.ndim != 1 or not np.isfinite(x).all() or not np.isfinite(y).all() or np.any(np.diff(x)<=0):
        raise ValueError('Curve requires ordered finite delays and matching values')
    result = []
    for i in range(len(x)-1):
        if y[i]*y[i+1] < 0:
            result.append({'bracket_ms': [float(x[i]),float(x[i+1])],
                           'linear_interpolation_ms': float(x[i]-y[i]*(x[i+1]-x[i])/(y[i+1]-y[i]))})
    return result


def _provenance(runtime, *, validator_path=None):
    from ..neuromod.sources import require_source_gate
    source = require_source_gate(runtime.root)
    result = {k: source[k] for k in ('source_hashes','source_stats','base_artifact_hashes','base_config_hashes')}
    # Match the runtime's explicit scientific dependency manifest. Cosmetic
    # console/report edits cannot invalidate otherwise identical trajectories.
    hashes=dict(runtime.manifest_hashes)
    paths=['src/flybrain/rt/validation.py','src/flybrain/engine.py']
    if validator_path is not None:paths.append(validator_path)
    for name in paths:hashes[name]=checksum(runtime.root/name)
    result['config_hashes']={name.removeprefix('config/'):digest for name,digest in hashes.items() if name.startswith('config/')}
    result['implementation_hashes']={name:digest for name,digest in hashes.items() if name.startswith('src/')}
    result['dependency_hashes']={name:digest for name,digest in hashes.items() if not name.startswith(('config/','src/'))}
    result['dependency_hashes']['build/validation_neuromod_plasticity.json']=checksum(runtime.root/'build/validation_neuromod_plasticity.json')
    return result


def _verify_provenance(root, result):
    from ..neuromod.sources import require_source_gate
    require_plasticity_gate(root)
    source = require_source_gate(root)
    for key in ('source_hashes','source_stats','base_artifact_hashes','base_config_hashes'):
        if source[key] != result[key]:
            raise ValueError('Runtime source evidence changed during validation: '+key)
    for field, prefix in (('config_hashes', root/'config'), ('implementation_hashes', root), ('dependency_hashes', root)):
        for name, digest in result[field].items():
            if checksum(prefix/name) != digest:
                raise ValueError('Runtime evidence changed during validation: '+name)


def _finish_gates(result):
    """Each report row remains independently verifiable after parent extraction."""
    if isinstance(result['gates'], dict):
        result['gates'] = list(result['gates'].values())
    for row in result['gates']:
        for name in ('source_hashes','source_stats','base_artifact_hashes','base_config_hashes',
                     'config_hashes','implementation_hashes','dependency_hashes','artifact_hashes'):
            if name in result:
                row[name] = result[name] | row.get(name,{})
    return result


def validate_biology(root, runtime=None):
    """Real F/G/H/J/K measurements with no coefficient search or compensating gain."""
    root = Path(root).resolve()
    destination = root/'build/validation_neuromod_biology.json'
    result = {'status':'FAIL','created_at':datetime.now(timezone.utc).isoformat(),'checks':[], 'gates':{},
              'fitting_performed':False,'body_readout':'NOT-RUN','artifact_hashes':{}}
    atomic_write_json(destination,result)
    own = runtime is None
    rt = runtime
    def gate(name, passed, **metrics):
        result['gates'][name] = {'gate':name,'kind':'biology','status':'PASS' if passed else 'FAIL',**metrics}
    try:
        rt = rt or CoreRuntime(root,record=False)
        rt.warmup()
        result.update(_provenance(rt))
        rows=[]
        handle='PPL101'
        source_idx=np.flatnonzero((rt.cells==handle)&rt.sources['DA'])
        assignments=rt.mapping.mb_assignment[rt.core.model_indices][source_idx]
        eligible=[int(x) for x in assignments if x>=0 and len(rt.weight_groups[int(x)])]
        if not eligible:
            raise ValueError('PPL101 has no empirically assigned plastic output compartment')
        paired=sorted(set(eligible))[0]
        group=rt.weight_groups[paired]
        for delay in PAIRING_DELAYS_MS:
            snapshot=execute_events(rt,pairing_events(handle,delay_ms=delay),7000)
            delta=rt.plasticity.weights/rt.plasticity.w0-1
            rows.append({'delay_ms':delay,'paired_mean_relative_delta':float(delta[group].mean()),
                         'total_absolute_weight_change':rt.plasticity.total_absolute_weight_change,
                         'spikes':snapshot['spikes'],'voltage_out_of_bounds':snapshot['voltage_out_of_bounds']})
        curve=pd.DataFrame(rows)
        curve.to_csv(root/'build/neuromod_network_pairing_curve.csv',index=False)
        forward=curve.loc[curve.delay_ms>0,'paired_mean_relative_delta'].sum()
        backward=curve.loc[curve.delay_ms<0,'paired_mean_relative_delta'].sum()
        crossings=crossing_intervals(curve.delay_ms,curve.paired_mean_relative_delta)
        near_zero=any(abs(x['linear_interpolation_ms'])<=500 for x in crossings)
        gate('V-NM-F',forward<0 and backward>0 and near_zero,forward_sum=float(forward),backward_sum=float(backward),
             observed_crossings=crossings,near_zero_tolerance_ms=500,
             near_zero_tolerance_source='ASSUMPTION: one reference DA pulse width; not a fitted parameter',
             source=handle,empirical_compartment=rt.mapping.names[paired],published_compartment='g1',
             mismatch_retained=True,reference='https://doi.org/10.1016/j.cell.2019.05.040',
             scope='Closed-loop network curve; distinct from the prescribed single-synapse reference')

        # Isolate the *difference* caused by a simulation-only concentration clamp.
        baseline_events=[event(3000,'odour','OCT'),event(4000,'odour','air')]
        execute_events(rt,baseline_events,7000)
        unpaired=rt.plasticity.weights.copy()
        events=baseline_events+[event(3500,'field.clamp',{'species':'DA','compartment':rt.mapping.names[paired],'value':1.}),event(4000,'field.clamp',None)]
        execute_events(rt,events,7000)
        change=np.abs((rt.plasticity.weights-unpaired)/rt.plasticity.w0)
        means=[float(change[g].mean()) if len(g) else None for g in rt.weight_groups]
        other=max([x for i,x in enumerate(means) if i!=paired and x is not None],default=0.)
        paired_change=means[paired]
        specificity=paired_change/other if other else None
        gate('V-NM-G',paired_change>0 and paired_change>10*other,paired_mean_absolute_change=paired_change,
             maximum_other_mean_absolute_change=other,ratio=specificity,
             ratio_is_infinite=bool(paired_change>0 and other==0),by_compartment=dict(zip(rt.mapping.names[:15],means)),
             scope='Treatment minus same-seed no-pulse control; direct field clamp is simulation-only',
             reference='https://doi.org/10.1016/j.neuron.2015.11.019')

        before=odor_test(rt,'OCT')
        execute_events(rt,pairing_events(handle),15000)
        trained=rt.plasticity.weights.copy()
        after=odor_test(rt,'OCT',weights=trained)
        delta=after['valence']-before['valence']
        execute_events(rt,pairing_events('PAM01'),15000)
        appetitive_weights=rt.plasticity.weights.copy()
        appetitive=odor_test(rt,'OCT',weights=appetitive_weights)
        appetitive_delta=appetitive['valence']-before['valence']
        gate('V-NM-H',delta<0 and appetitive_delta>0,baseline=before,trained=after,valence_change=float(delta),
             appetitive_trained=appetitive,appetitive_valence_change=float(appetitive_delta),
             expected_direction='PPL101 decreases approach; PAM01 increases approach',
             empirical_compartment=rt.mapping.names[paired],anatomical_mismatch=True,
             reference='https://elifesciences.org/articles/4580')

        # Re-exposure from clean fast state with the trained memory retained.
        rt.reset(7);install_weights(rt,trained)
        distance_before=float(np.abs((trained-rt.plasticity.w0)/rt.plasticity.w0).sum())
        execute_events(rt,[event(0,'odour','OCT'),event(1000,'odour','air'),event(3000,'odour','OCT'),event(4000,'odour','air')],7000,reset=False)
        distance_after=float(np.abs((rt.plasticity.weights-rt.plasticity.w0)/rt.plasticity.w0).sum())
        rt.reset(7);install_weights(rt,trained);rt.advance(7000)
        passive_distance=float(np.abs((rt.plasticity.weights-rt.plasticity.w0)/rt.plasticity.w0).sum())
        # Causal diagnostic: remove only released MBON→DAN edges and restore
        # their exact values afterward. This is not the production network.
        csc_pre=np.repeat(np.arange(len(rt.neurons)),np.diff(rt.engine.csc_indptr))
        cut=np.flatnonzero(np.char.startswith(rt.cells[csc_pre],'MBON') & rt.sources['DA'][rt.engine.csc_indices])
        released=rt.engine.csc_counts[cut].copy()
        try:
            rt.reset(7);install_weights(rt,trained);rt.engine.csc_counts[cut]=0
            execute_events(rt,[event(0,'odour','OCT'),event(1000,'odour','air'),event(3000,'odour','OCT'),event(4000,'odour','air')],7000,reset=False)
            cut_distance=float(np.abs((rt.plasticity.weights-rt.plasticity.w0)/rt.plasticity.w0).sum())
        finally:
            rt.engine.csc_counts[cut]=released
        gate('V-NM-K',distance_before>0 and distance_after<min(distance_before,passive_distance,cut_distance),
             distance_from_baseline_before=distance_before,distance_from_baseline_after=distance_after,
             passive_forgetting_control_distance=passive_distance,loop_ablation_distance=cut_distance,
             ablated_MBON_DAN_edges=len(cut),
             relative_reversal=float((distance_before-distance_after)/distance_before) if distance_before else None,
             scope='Repeated unrewarded odor, compared with passive forgetting and an explicit MBON→DAN ablation diagnostic',
             reference='https://doi.org/10.1016/j.cell.2018.08.021')
        state_result=validate_state(root,lambda snapshot,seed:odor_test(rt,'OCT',seed=seed,state_snapshot=snapshot),
                                    runtime_provenance=result)
        result['gates']['V-NM-J']=state_result
        result['checks'].append({'name':'state_software','observed':state_result['software_status'],'expected':'PASS','status':state_result['software_status']})
        result['artifact_hashes']={'neuromod_network_pairing_curve.csv':checksum(root/'build/neuromod_network_pairing_curve.csv')}
        _verify_provenance(root,result)
        result['status']='PASS' if all(c['status']=='PASS' for c in result['checks']) else 'FAIL'
        result['interpretation']='Execution/software status; inspect individual biological gate outcomes separately'
    except Exception as exc:
        result['checks'].append({'name':'biology_protocol_execution','status':'FAIL','error':str(exc),'type':type(exc).__name__})
    finally:
        if own and rt is not None:rt.close()
    _finish_gates(result)
    atomic_write_json(destination,result)
    return result


def benchmark_schedule():
    return [event(0,'odour','OCT'),event(1000,'odour','air'),event(1500,'dan_drive',1.),event(2000,'dan_drive',0.),
            event(10000,'nutritional_state','starved'),event(20000,'odour','MCH'),event(21000,'odour','air'),
            event(30000,'state.arousal',.5),event(40000,'nutritional_state','fed'),event(45000,'oa_tone',.2),event(46000,'oa_tone',0.)]


def validate_realtime(root, runtime=None, *, duration_ms=60000):
    """60 s wall-clock measurement and an identical replay. No timestep relaxation."""
    root=Path(root).resolve();destination=root/'build/validation_neuromod_runtime.json'
    result={'status':'FAIL','created_at':datetime.now(timezone.utc).isoformat(),'checks':[],'gates':{},'artifact_hashes':{}}
    atomic_write_json(destination,result)
    own=runtime is None;rt=runtime
    try:
        if duration_ms!=60000:raise ValueError('Formal B/F-prime validation requires exactly 60,000 ms')
        rt=rt or CoreRuntime(root,record=True)
        if not rt.record: raise ValueError('Formal replay validation requires recorded frames')
        rt.warmup();result.update(_provenance(rt))
        initial_rss=psutil.Process().memory_info().rss
        events=benchmark_schedule()
        frame_timings=[]
        start=time.perf_counter();first=execute_events(rt,events,duration_ms,seed=7,frame_timings=frame_timings);wall=time.perf_counter()-start
        first_digest=rt.digests();first_state={k:array_hash(v) for k,v in {'v':rt.engine.v,'g':rt.engine.g,'C':rt.field.C,'pre':rt.plasticity.e_pre,'da':rt.plasticity.e_da}.items()}
        first_endocrine=rt.state.snapshot()
        timing=np.asarray(rt.tick_wall_seconds,float)
        # Sampling frame RSS plus endpoint is measured RSS, not an OS peak-memory oracle.
        peak=max([initial_rss,psutil.Process().memory_info().rss]+[int(frame['rss_gb']*1e9) for frame in rt.frames])
        # Persist completed timing even if subsequent export/replay fails. This
        # is a measured partial result, never a fabricated completed B gate.
        pd.DataFrame({'tick_index':np.arange(len(timing)),'wall_seconds':timing}).to_csv(root/'build/neuromod_runtime_ticks.csv',index=False)
        pd.DataFrame(frame_timings).to_csv(root/'build/neuromod_runtime_frames.csv',index=False)
        result['completed_first_trajectory']={'duration_ms':duration_ms,'wall_seconds':wall,
            'real_time_factor':duration_ms/1000/wall,'rss_sampled_max_bytes':peak,
            'digests':first_digest,'replay_completed':False}
        result['artifact_hashes']={name:checksum(root/'build'/name) for name in ('neuromod_runtime_ticks.csv','neuromod_runtime_frames.csv')}
        atomic_write_json(destination,result)
        export=rt.export(root/'build/neuromod_recorded_session.zip')
        first_session=str(rt.session_dir.relative_to(root))
        recorded_events=[json.loads(line) for line in (rt.session_dir/'events.jsonl').read_text().splitlines() if line.strip()]
        replay=execute_events(rt,recorded_events,duration_ms,seed=7)
        replay_state={k:array_hash(v) for k,v in {'v':rt.engine.v,'g':rt.engine.g,'C':rt.field.C,'pre':rt.plasticity.e_pre,'da':rt.plasticity.e_da}.items()}
        exact=first_digest==rt.digests() and first_state==replay_state and first_endocrine==rt.state.snapshot()
        result['completed_first_trajectory']['replay_completed']=True
        result['gates']['V-NM-B']={'gate':'V-NM-B','kind':'software','status':'PASS' if exact else 'FAIL',
             'duration_ms':duration_ms,'event_count':len(events),'first_digests':first_digest,'replay_digests':rt.digests(),
             'exact_fast_fields_traces_and_endocrine_state':first_state==replay_state and first_endocrine==rt.state.snapshot(),
             'recorded_session':first_session,'scope':'Identical seed and full control event list; every spike and final weight hashed'}
        frame_times=np.array([x['wall_seconds'] for x in frame_timings])
        frame_budgets=np.array([x['duration_ms']/1000 for x in frame_timings])
        rtf=duration_ms/1000/wall;overruns=int(np.count_nonzero(frame_times>frame_budgets));fraction=overruns/len(frame_times)
        passing=rtf>=1.2 and fraction<=.01 and peak<=4_000_000_000
        result['gates']["V-NM-F'"]={'gate':"V-NM-F'",'kind':'software','status':'PASS' if passing else 'FAIL',
             'duration_ms':duration_ms,'wall_seconds':wall,'real_time_factor':rtf,'required_real_time_factor':1.2,'frame_budget_ms':20.,
             'measured_tick_count':len(timing),'measured_frames':len(frame_times),'over_budget_frames':overruns,'over_budget_fraction':fraction,
             'over_budget_1ms_ticks':int(np.count_nonzero(timing>.001)),
             'rss_sampled_max_bytes':peak,'rss_limit_bytes':4_000_000_000,'timing_scope':'One process, compilation excluded; reset and event dispatch included',
             'thread_count':1,'dt_base_ms':.1,'dt_mod_ms':1.,'voltage_out_of_bounds':first['voltage_out_of_bounds']}
        pd.DataFrame({'tick_index':np.arange(len(timing)),'wall_seconds':timing}).to_csv(root/'build/neuromod_runtime_ticks.csv',index=False)
        pd.DataFrame(frame_timings).to_csv(root/'build/neuromod_runtime_frames.csv',index=False)
        result['artifact_hashes']={name:checksum(root/'build'/name) for name in ('neuromod_recorded_session.zip','neuromod_runtime_ticks.csv','neuromod_runtime_frames.csv')}
        _verify_provenance(root,result)
        result['status']='PASS' if all(g['status']=='PASS' for g in result['gates'].values()) else 'FAIL'
    except Exception as exc:
        result['checks'].append({'name':'runtime_validation_execution','status':'FAIL','error':str(exc),'type':type(exc).__name__})
    finally:
        if own and rt is not None:rt.close()
    _finish_gates(result)
    atomic_write_json(destination,result)
    return result


def validate_runtime(root, gate=None):
    if gate=='neuromod-runtime':
        realtime=validate_realtime(root)
        biology=validate_biology(root)
        return {'status':'PASS' if realtime['status']==biology['status']=='PASS' else 'FAIL',
                'gates':realtime['gates']+biology['gates'],
                'interpretation':'Software execution summary; each biological outcome remains separate'}
    if gate in ('B', "F'", 'Fprime', 'V-NM-B', "V-NM-F'"):
        return validate_realtime(root)
    if gate in (None, 'F', 'G', 'H', 'J', 'K', 'V-NM-F', 'V-NM-G', 'V-NM-H', 'V-NM-J', 'V-NM-K'):
        return validate_biology(root)
    raise ValueError('Unsupported coupled runtime gate: '+str(gate))
