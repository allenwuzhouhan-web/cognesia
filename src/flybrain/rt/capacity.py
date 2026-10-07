"""Actual trained-memory task information, with explicit interface uncertainty."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import multiprocessing
import os
import uuid

import numpy as np
import pandas as pd

from ..fetch import checksum
from ..inspect_data import atomic_write_json
from .engine_rt import CoreRuntime
from .validation import (_provenance, _verify_provenance, array_hash, event,
                         execute_events, odor_test)


def mutual_information(intended, observed):
    """Empirical categorical MI in bits; no bias correction or fitted decoder."""
    x,y=np.asarray(intended),np.asarray(observed)
    if x.ndim!=1 or x.shape!=y.shape or not len(x):
        raise ValueError('Mutual information requires equal nonempty vectors')
    _,xi=np.unique(x,return_inverse=True);_,yi=np.unique(y,return_inverse=True)
    counts=np.zeros((xi.max()+1,yi.max()+1),float)
    np.add.at(counts,(xi,yi),1)
    p=counts/counts.sum();independent=p.sum(1)[:,None]*p.sum(0)[None,:]
    mask=p>0
    return float(np.sum(p[mask]*np.log2(p[mask]/independent[mask])))


def benjamini_hochberg(p_values):
    p=np.asarray(p_values,float)
    if p.ndim!=1 or not np.isfinite(p).all() or np.any((p<0)|(p>1)):
        raise ValueError('P values must be a finite probability vector')
    if not len(p):return p.copy()
    order=np.argsort(p,kind='stable')
    adjusted=np.minimum.accumulate((p[order]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1]
    result=np.empty_like(p);result[order]=np.minimum(adjusted,1)
    return result


def information_statistics(table, *, randomizations=1000, seed=7):
    """Bootstrap entire training protocols; shuffle intended protocol assignments.

    Held-out seeds from one trained memory are not independent training trials.
    The two-mapping pilot consequently has very low randomization resolution;
    requesting 1,000 draws does not create 1,000 independent experiments.
    """
    if isinstance(randomizations,bool) or int(randomizations)!=randomizations or randomizations<1000:
        raise ValueError('At least 1,000 bootstrap and shuffled-protocol draws required')
    required={'protocol','odor','intended','decision','baseline_decision'}
    if not required.issubset(table.columns) or table.empty:
        raise ValueError('Missing actual held-out task observations')
    protocols=list(table.protocol.unique())
    groups=[table[table.protocol.eq(name)] for name in protocols]
    if len(groups)<2:raise ValueError('At least two trained protocol assignments required')
    odours=sorted(table.odor.unique())
    targets=[]
    for group in groups:
        target=[]
        for odor in odours:
            values=group.loc[group.odor.eq(odor),'intended'].unique()
            if len(values)!=1:raise ValueError('Each protocol needs one intended action per odor')
            target.append(values[0])
        targets.append(target)
    targets=np.asarray(targets)
    observed=mutual_information(table.intended,table.decision)
    baseline=mutual_information(table.intended,table.baseline_decision)
    rng=np.random.default_rng(seed);boot=np.empty(randomizations);changes=np.empty(randomizations);null=np.empty(randomizations)
    for draw in range(randomizations):
        sample=pd.concat([groups[i] for i in rng.integers(0,len(groups),len(groups))],ignore_index=True)
        boot[draw]=mutual_information(sample.intended,sample.decision)
        changes[draw]=boot[draw]-mutual_information(sample.intended,sample.baseline_decision)
        permutation=rng.permutation(len(groups));labels=[];decisions=[]
        for index,group in enumerate(groups):
            labels.extend(targets[permutation[index],[odours.index(x) for x in group.odor]])
            decisions.extend(group.decision)
        null[draw]=mutual_information(labels,decisions)
    return {'mutual_information_bits':observed,'baseline_information_bits':baseline,
            'information_change_bits':observed-baseline,
            'bootstrap_ci95_bits':np.quantile(boot,[.025,.975]).tolist(),
            'information_change_ci95_bits':np.quantile(changes,[.025,.975]).tolist(),
            'null_mean_bits':float(null.mean()),
            'empirical_p':float((1+np.count_nonzero(null>=observed-1e-14))/(randomizations+1)),
            'randomizations':int(randomizations),'empirical_p_floor':1/(randomizations+1),
            'independent_training_protocols':len(groups),'held_out_observations':len(table),
            'resampling_unit':'Entire trained protocol, preserving all held-out seeds and odors'}


def decode_action(valence):
    if not np.isfinite(valence):raise ValueError('Nonfinite inferred valence')
    return 1 if valence>0 else 0 if valence<0 else 2


def enumerate_handles(runtime):
    rows=[]
    endocrine=runtime.neurons.super_class.eq('endocrine').to_numpy()
    masks={**{key:runtime.sources[key] for key in ('DA','OA','5HT','TA')},'endocrine':endocrine}
    selected=np.logical_or.reduce(list(masks.values()))
    named_oa=np.char.startswith(runtime.cells,'OA-')
    for cell in sorted(set(runtime.cells[selected|named_oa])):
        indices=np.flatnonzero(runtime.cells==cell)
        # A type control activates every member: mixed annotation is an explicit
        # unavailable type, never an invented selective driver for its subset.
        addressable=bool(np.all(selected[indices]))
        rows.append({'cell_type':cell,'neuron_count':len(indices),
                     'species':';'.join(key for key,mask in masks.items() if mask[indices].any()),
                     'addressable_in_runtime':addressable,
                     'availability_reason':'known-positive source type' if addressable else 'Type contains members without positive supported modulator annotation',
                     'published_driver_line':'','driver_line_status':'UNKNOWN: not verified',
                     'physical_access_claim':'none'})
    return pd.DataFrame(rows)


def _training_events(handle,odor):
    return [event(0,'odour',odor),event(1000,'odour','air'),
            event(500,'source_drive',{'cell_type':handle,'drive':1.}),
            event(1000,'source_drive',{'cell_type':handle,'drive':0.})]


def _measure_handle(runtime, handle_index, handle, baselines, seeds, randomizations):
    """The serial scientific protocol, independent of scheduling or worker identity."""
    observations=[]
    # Intended mappings are task instructions, not measured reinforcement signs.
    reinforced_action=0 if handle.startswith('PPL') else 1
    for assignment,paired_odor in enumerate(('OCT','MCH')):
        execute_events(runtime,_training_events(handle,paired_odor),3000,seed=7)
        weights=runtime.plasticity.weights.copy();trained_hash=array_hash(weights)
        training_change=float(np.abs(weights/runtime.plasticity.w0-1).sum())
        for seed in seeds:
            for odor in ('OCT','MCH'):
                measured=odor_test(runtime,odor,seed=seed,weights=weights,duration_ms=500)
                if measured['weights_sha256_before']!=trained_hash or measured['weights_sha256_after']!=trained_hash:
                    raise ValueError('Held-out capacity test changed trained weights')
                observations.append({'handle':handle,'protocol':handle+':'+str(assignment),'odor':odor,
                    'seed':seed,'paired_odor':paired_odor,
                    'intended':reinforced_action if odor==paired_odor else 1-reinforced_action,
                    'decision':decode_action(measured['valence']),'valence':measured['valence'],
                    'baseline_decision':decode_action(baselines[odor,seed]['valence']),
                    'baseline_valence':baselines[odor,seed]['valence'],
                    'spikes':measured['spikes'],'training_relative_weight_change_L1':training_change,
                    'trained_weights_sha256':trained_hash,'test_weights_unchanged':True})
    statistic={'handle':handle,**information_statistics(pd.DataFrame(observations),
        randomizations=randomizations,seed=700+handle_index)}
    return {'index':handle_index,'handle':handle,'observations':observations,'statistics':statistic}


def _capacity_worker(job):
    """One isolated process reuses one runtime; only its own progress file is written."""
    root=Path(job['root']);progress_path=Path(job['progress_path'])
    progress={'worker':job['worker'],'pid':os.getpid(),'status':'RUNNING',
              'assigned_handles':[handle for index,handle in job['assigned']],
              'completed_handles':0,'results':[]}
    atomic_write_json(progress_path,progress)
    runtime=None
    try:
        runtime=CoreRuntime(root,record=False)
        if runtime.config_hash != job['runtime_hash'] or checksum(Path(__file__)) != job['capacity_hash']:
            raise ValueError('Capacity worker implementation/configuration differs from parent')
        runtime.warmup()
        for index,handle in job['assigned']:
            measured=_measure_handle(runtime,index,handle,job['baselines'],job['seeds'],job['randomizations'])
            progress['results'].append(measured)
            progress['completed_handles']=len(progress['results'])
            progress['last_session_dir']=str(runtime.session_dir)
            atomic_write_json(progress_path,progress)
        progress['status']='PASS'
        return progress['results']
    except Exception as exc:
        progress.update(status='FAIL',error={'type':type(exc).__name__,'message':str(exc)})
        raise
    finally:
        if runtime is not None:runtime.close()
        atomic_write_json(progress_path,progress)


def _ordered_results(selected, completed):
    """Validate identities and merge out-of-order worker completions canonically."""
    by_index={}
    for row in completed:
        index=row['index']
        if (isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(selected)
                or selected[index]!=row['handle'] or row['statistics']['handle']!=row['handle']
                or any(trial['handle']!=row['handle'] for trial in row['observations'])):
            raise ValueError('Capacity worker returned an incorrect handle identity')
        if index in by_index:raise ValueError('Capacity worker returned duplicate handle results')
        by_index[index]=row
    ordered=[by_index[index] for index in sorted(by_index)]
    return ([trial for row in ordered for trial in row['observations']],
            [row['statistics'] for row in ordered])


def _worker_count(full, workers):
    workers=4 if full and workers is None else 1 if workers is None else workers
    if isinstance(workers,bool) or not isinstance(workers,int) or not 1<=workers<=4:
        raise ValueError('Capacity workers must be an integer from 1 to 4')
    return workers


def measure_capacity(root, *, full=False, runtime=None, handles=None, seeds=(101,102), randomizations=1000, workers=None):
    """Two opposite OCT/MCH mappings per handle; held-out Poisson seeds, fixed weights.

    Each handle uses 6 s training and 4 s held-out testing. This is a bounded
    experiment over the complete handle inventory when ``full=True``; it does
    not establish asymptotic Shannon capacity or physical interface bandwidth.
    Full inventory defaults to four isolated spawn workers; pilots default to
    one. Worker scheduling never enters simulation seeds or statistical draws.
    """
    root=Path(root).resolve();destination=root/'build/validation_neuromod_capacity.json'
    result={'gate':'CAPACITY','kind':'measurement','status':'FAIL','checks':[],
            'created_at':datetime.now(timezone.utc).isoformat(),'artifact_hashes':{}}
    atomic_write_json(destination,result);own=runtime is None;rt=runtime
    try:
        requested_workers=_worker_count(full,workers)
        if len(seeds)<2 or len(set(seeds))!=len(seeds) or any(int(s)!=s or s<100 for s in seeds):
            raise ValueError('Use at least two distinct held-out integer seeds >=100')
        if randomizations<1000 or int(randomizations)!=randomizations:
            raise ValueError('At least 1,000 randomizations required')
        rt=rt or CoreRuntime(root,record=False);rt.warmup();result.update(_provenance(rt,validator_path='src/flybrain/rt/capacity.py'))
        inventory=enumerate_handles(rt)
        inventory.to_csv(root/'build/neuromod_write_handles.csv',index=False)
        available=inventory.loc[inventory.addressable_in_runtime,'cell_type'].tolist()
        selected=list(handles) if handles is not None else available if full else ['PPL101','PAM01']
        if not selected or len(set(selected))!=len(selected) or any(x not in available for x in selected):
            raise ValueError('Requested handle is not an addressable known source in this core')
        worker_count=min(requested_workers,len(selected))
        result['execution']={'requested_workers':requested_workers,'workers':worker_count,
            'process_start_method':'spawn' if worker_count>1 else 'serial',
            'merge_order':'Original selected inventory order; bootstrap seed 700 + original handle index',
            'global_output_owner':'parent process only','parent_pid':os.getpid()}
        result.update(task={'N_odors':2,'M_intended_actions':2,'odors':['OCT','MCH'],
            'observed_actions':{'0':'avoid','1':'approach','2':'exactly zero inferred valence'},
            'training_ms':3000,'test_ms':500,'pulse_start_ms':500,'pulse_duration_ms':500,
            'held_out_seeds':list(seeds),'training_seed':7,'readout':'INFERRED_SIGN MBON type-normalized rates',
            'decoder_fitting':False,'body_decoder':'NOT-RUN'},
            addressable_connectome_types=len(inventory),addressable_runtime_types=len(available),
            named_MB_DAN_types=int(inventory.cell_type.str.match(r'^(PAM|PPL1|PPL2|PAL)').sum()),
            named_OA_prefix_types=int(inventory.cell_type.str.startswith('OA-').sum()),
            classification_policy='OA-prefixed TA-positive types remain TA handles; positive annotations define species, not names',
            measured_handle_count=len(selected),full_inventory_measured=set(selected)==set(available),
            verified_published_driver_line_mappings=0,published_driver_line_addressable_count=None,
            interface_bandwidth_gap_bits=None,
            interface_gap_status='NOT-QUANTIFIABLE: absence of verified driver mapping is not evidence that no drivers exist',
            read_handles={'MBON_types':len(rt.mbon_types),'signed_MBON_types':rt.valence.coverage['signed_types'],
                          'descending_decoder':'NOT-RUN'},
            limitations=['Two trained assignments per handle limit statistical power and do not establish saturation.',
                         'Three-second training and half-second tests are explicit protocol assumptions, not fitted biological durations.',
                         'Both odors and all test seeds are held out from parameter/decoder fitting; test seeds differ from training.',
                         'A nonzero innate odor MI is not written memory; baseline information is reported separately.'])
        baselines={(odor,seed):odor_test(rt,odor,seed=seed,duration_ms=500) for odor in ('OCT','MCH') for seed in seeds}
        completed=[]
        def accept(batch):
            completed.extend(batch)
            observations,statistics=_ordered_results(selected,completed)
            pd.DataFrame(observations).to_csv(root/'build/neuromod_capacity_trials.csv',index=False)
            result['completed_handles']=len(statistics)
            atomic_write_json(destination,result)
        if worker_count==1:
            for index,handle in enumerate(selected):
                accept([_measure_handle(rt,index,handle,baselines,seeds,randomizations)])
        else:
            progress_dir=root/'runs/neuromod'/('capacity-'+uuid.uuid4().hex)
            progress_dir.mkdir(parents=True,exist_ok=False)
            jobs=[{'root':str(root),'worker':i,'assigned':list(enumerate(selected))[i::worker_count],
                   'progress_path':str(progress_dir/f'worker-{i:02d}.json'),
                   'runtime_hash':rt.config_hash,'capacity_hash':result['implementation_hashes']['src/flybrain/rt/capacity.py'],
                   'baselines':baselines,'seeds':tuple(seeds),'randomizations':randomizations}
                  for i in range(worker_count)]
            result['execution']['worker_progress_files']=[job['progress_path'] for job in jobs]
            atomic_write_json(destination,result)
            if own:
                rt.close();rt=None  # Parent releases its network before four isolated copies are loaded.
            # Pool context terminates remaining workers on a failed batch; it
            # cannot leave processes running after a global failed measurement.
            with multiprocessing.get_context('spawn').Pool(processes=worker_count) as pool:
                for batch in pool.imap_unordered(_capacity_worker,jobs,chunksize=1):
                    accept(batch)
            result['execution']['worker_progress_hashes']={str(Path(job['progress_path']).relative_to(root)):checksum(job['progress_path']) for job in jobs}
        observations,statistics=_ordered_results(selected,completed)
        if len(statistics)!=len(selected):raise ValueError('Capacity measurement omitted selected handles')
        q=benjamini_hochberg([x['empirical_p'] for x in statistics])
        for row,value in zip(statistics,q,strict=True):row.update(bh_q=float(value),significant_q_lt_05=bool(value<.05))
        result['per_handle']=statistics
        curves=[]
        table=pd.DataFrame(observations)
        for count in range(1,len(selected)+1):
            part=table[table.handle.isin(selected[:count])]
            curves.append({'handles_used':count,'mutual_information_bits':mutual_information(part.intended,part.decision),
                           'baseline_information_bits':mutual_information(part.intended,part.baseline_decision),
                           'scope':'Uniform pooled handle trials; fixed lexical inventory order, not optimized combinations'})
        result['capacity_curve']=curves
        result['saturation_point']=None
        result['saturation_status']='NOT-ESTABLISHED: bounded N=2, M=2 task does not identify saturation over task complexity or handle combinations'
        result['simulation_only_curve']=curves
        result['simulation_only_definition']='All measured handles lack verified physical-driver mappings in this repository; physical availability remains unknown'
        pd.DataFrame(curves).to_csv(root/'build/neuromod_capacity_curve.csv',index=False)
        result['artifact_hashes']={name:checksum(root/'build'/name) for name in
            ('neuromod_write_handles.csv','neuromod_capacity_trials.csv','neuromod_capacity_curve.csv')}
        _verify_provenance(root,result)
        result['checks']=[{'name':'actual_held_out_trials','status':'PASS','observed':len(observations)},
                          {'name':'frozen_test_weights','status':'PASS'},
                          {'name':'bootstrap_and_null_count','status':'PASS','observed':randomizations},
                          {'name':'every_selected_handle_once_in_original_order','status':'PASS','observed':len(statistics)}]
        result['status']='PASS'
        result['interpretation']='Measurement execution passed; information estimates, null results, power and interface uncertainty are reported separately'
    except Exception as exc:
        result['checks'].append({'name':'capacity_execution','status':'FAIL','error':str(exc),'type':type(exc).__name__})
    finally:
        if own and rt is not None:rt.close()
    atomic_write_json(destination,result)
    return result
