"""Outcome access only after the native prediction inventory is fully sealed."""
from __future__ import annotations

import json
import math
from pathlib import Path
import numpy as np

from .interfaces import identity
from . import retrospective_comparison as driver
from .retrospective_contract import INPUT_ROOT, InputStore
from ..t4_fit_project import data
from ..validation_project.common import file_hash, identity as legacy_identity


def rmse(values):
    a=np.asarray(values,dtype=float)
    if not a.size or not np.isfinite(a).all(): raise ValueError('Finite nonempty errors required')
    return float(np.sqrt(np.mean(a*a)))


def case_statistics(time_ms, predicted, observed):
    t=np.asarray(time_ms); p=np.asarray(predicted); y=np.asarray(observed)
    if t.ndim!=1 or p.shape!=t.shape or y.shape!=t.shape or not np.isfinite([p,y]).all():
        raise ValueError('Paired finite physical-grid traces required')
    window=t>=0
    if not window.any(): raise ValueError('No post-onset observation samples')
    return {'waveform_rmse_mv':rmse(p[window]-y[window]),'predicted_peak_mv':float(np.max(p[window])),
            'observed_peak_mv':float(np.max(y[window])),'post_onset_samples':int(window.sum())}


def endpoints(cases, statistics):
    """Five dependent endpoints; an incomplete endpoint never gets a zero."""
    flash=[c for c in cases if c['family']=='flash']; motion=[c for c in cases if c['family']=='moving']
    groups={'flash_spatial_peak_rmse':[c for c in flash if c['duration_ms']==80.],
            'flash_duration_peak_rmse':[c for c in flash if c['position']==0.],
            'motion_waveform_rmse':motion,'direction_contrast_rmse':motion,'speed_contrast_rmse':motion}
    output={}
    for name,required in groups.items():
        missing=[c['case_id'] for c in required if c['case_id'] not in statistics]
        item={'metric':name,'unit':'mV','direction':'lower','case_ids':[c['case_id'] for c in required],
              'missing_case_ids':missing,'score':None,'status':'INCOMPLETE' if missing else 'SCORED'}
        if missing: output[name]=item; continue
        if name=='motion_waveform_rmse':
            item['score']=float(np.mean([statistics[c['case_id']]['waveform_rmse_mv'] for c in required]))
        elif name.startswith('flash_'):
            item['score']=rmse([statistics[c['case_id']]['predicted_peak_mv']-statistics[c['case_id']]['observed_peak_mv'] for c in required])
        else:
            contrasts=[]
            def peak(c,k): return statistics[c['case_id']][k+'_peak_mv']
            def pair(key,value,positive):
                selected=[c for c in required if c[key]==value]
                if len(selected)!=2: raise ValueError('Incomplete registered contrast pair')
                first=next(c for c in selected if positive(c)); second=next(c for c in selected if not positive(c))
                pred=peak(first,'predicted')-peak(second,'predicted')
                obs=peak(first,'observed')-peak(second,'observed')
                contrasts.append({'first_case':first['case_id'],'second_case':second['case_id'],
                                  'predicted_contrast_mv':pred,'observed_contrast_mv':obs,'error_mv':pred-obs})
            if name=='direction_contrast_rmse':
                for dwell in (20.,80.): pair('duration_ms',dwell,lambda c:c['primary_axis_sign']==1)
            else:
                for sign in (-1,1): pair('primary_axis_sign',sign,lambda c:c['duration_ms']==20.)
            item['score']=rmse([c['error_mv'] for c in contrasts]);item['contrasts']=contrasts
        output[name]=item
    return output


def observation_target(contract, case, arrays):
    """Match the frozen trial policy; never mix a single prediction with a mean."""
    policy = contract.get('scoring_observation', {}).get('trial_policy', 'all_eligible_repeat_mean')
    if policy == 'all_eligible_repeat_mean':
        return (arrays['observed_mv'], arrays['repeat_sd_mv'] / math.sqrt(case['eligible_repeats']),
                list(case['eligible_trial_indices']))
    if policy != 'first_eligible_single_trial':
        raise ValueError('Unregistered observation trial policy')
    selected = contract['scoring_observation']['selected_trial_ids_by_case'][case['case_id']]
    expected = ['trial_' + str(min(case['eligible_trial_indices']))]
    if selected != expected or selected != contract['trial_ids_by_case'][case['case_id']]:
        raise ValueError('Selected observation trial differs from frozen input trial')
    number = min(case['eligible_trial_indices'])
    indices = np.asarray(arrays['eligible_trial_indices'])
    matches = np.flatnonzero(indices == number)
    if len(matches) != 1:
        raise ValueError('Selected recording trial is missing or duplicated')
    return np.asarray(arrays['eligible_trials_mv'][int(matches[0])]), None, [number]


def _observed_after_seal(store,protocol,seal,case):
    if seal.get('protocol_sha256')!=protocol['protocol_sha256'] or seal.get('status') not in {'COMPLETE','COMPLETE_WITH_FAILURES'}:
        raise ValueError('Complete native inventory must be sealed before outcome access')
    folder='flash' if case['family']=='flash' else 'motion'
    relative=f"observations/{folder}/{case['case_id']}.npz"
    metadata_path=INPUT_ROOT/relative.replace('.npz','.json')
    metadata=json.loads(metadata_path.read_bytes())
    if metadata.get('observation_identity')!=legacy_identity({k:v for k,v in metadata.items() if k!='observation_identity'}):
        raise ValueError('Historical outcome identity mismatch')
    source=INPUT_ROOT/relative
    if (metadata['case_id']!=case['case_id'] or metadata['source_trace_sha256']!=case['source_trace_sha256']
            or metadata['eligible_trial_indices']!=case['eligible_trial_indices']
            or metadata['input_identity']!=data.manifest(InputStore())['input_identity']
            or metadata['path']!=relative or file_hash(source)!=metadata['sha256']):
        raise ValueError('Recorded outcome provenance mismatch')
    with np.load(source,allow_pickle=False) as z: arrays={k:z[k] for k in z.files}
    input_arrays=data.input_case(InputStore(),case)
    data._validate_outcomes(arrays,case,input_arrays['time_ms'])
    retained=driver.retain_arrays(store,'observations/'+case['case_id']+'.npz',arrays,protocol['contract'])
    return arrays,{'source_path':str(source),'source_sha256':metadata['sha256'],
                   'historical_observation_identity':metadata['observation_identity'],'retained':retained,
                   'processing':'Previously exported acquisition-filtered, baseline-subtracted eligible trial voltages; mean and sampleSD rechecked. No second filter.'}


def score(store):
    driver.verify(store)
    protocol=store.read_json('protocol.json'); contract=protocol['contract']; seal=store.read_json('prediction-seal.json')
    if identity({k:v for k,v in seal.items() if k!='prediction_seal_sha256'})!=seal['prediction_seal_sha256']:
        raise ValueError('Prediction seal corrupted')
    observed={}; observation_sources={}
    for case in contract['cases']:
        observed[case['case_id']],observation_sources[case['case_id']]=_observed_after_seal(store,protocol,seal,case)
    targets = {c['case_id']: observation_target(contract, c, observed[c['case_id']]) for c in contract['cases']}
    for cid, (_, _, trial_indices) in targets.items():
        observation_sources[cid]['scored_trial_indices'] = trial_indices
        observation_sources[cid]['scored_repeat_count'] = len(trial_indices)
    by_key={(r['model_id'],r['sensitivity_id'],r['case_id'],r['trial_id']):r for r in seal['predictions']}
    groups=[]; traces={}
    for model in contract['models']:
        for sensitivity in contract['sensitivity_ids']:
            stats={}; missing=[]
            for case in contract['cases']:
                cid=case['case_id']; required=contract['trial_ids_by_case'][cid]
                rows=[by_key.get((model,sensitivity,cid,t)) for t in required]
                if any(r is None for r in rows): missing.append(cid);continue
                arrays=[driver.read_arrays(store,r['prediction']) for r in rows]
                grid=observed[cid]['time_ms']
                if any(not np.array_equal(a['observation_time_ms'],grid) for a in arrays): raise ValueError('Prediction grid mismatch')
                mean=np.mean([a['observation_values_mv'] for a in arrays],axis=0)
                target, sem, trial_indices = targets[cid]
                stats[cid]=case_statistics(grid,mean,target)
                traces[f'{model}/{sensitivity}/{cid}']={'time_ms':grid.tolist(),'prediction_mv':mean.tolist(),
                    'observation_mv':target.tolist(), 'observation_sem_mv':None if sem is None else sem.tolist(),
                    'scored_trial_indices':trial_indices, 'scored_repeat_count':len(trial_indices)}
            groups.append({'model_id':model,'sensitivity_id':sensitivity,'case_statistics':stats,
                           'missing_case_ids':missing,'endpoints':endpoints(contract['cases'],stats)})
    zero={c['case_id']:case_statistics(observed[c['case_id']]['time_ms'],np.zeros_like(targets[c['case_id']][0]),targets[c['case_id']][0]) for c in contract['cases']}
    comparisons=[]
    for sensitivity in contract['sensitivity_ids']:
        baseline=next(g for g in groups if g['model_id']=='banc-888' and g['sensitivity_id']==sensitivity)
        for candidate in [g for g in groups if g['model_id']!='banc-888' and g['sensitivity_id']==sensitivity]:
            for metric,endpoint in candidate['endpoints'].items():
                b=baseline['endpoints'][metric]['score']; p=endpoint['score']; margin=contract['numerical_separation_mv'][metric]
                delta=None if b is None or p is None else b-p
                verdict='UNSCORED' if delta is None else 'PARALIMBO_LOWER_ERROR' if delta>margin else 'BANC_LOWER_ERROR' if delta<-margin else 'WITHIN_NUMERICAL_SEPARATION'
                comparisons.append({'model_id':candidate['model_id'],'sensitivity_id':sensitivity,'metric':metric,
                    'banc_score':b,'paralimbo_score':p,'banc_minus_paralimbo_mv':delta,'numerical_separation_mv':margin,'verdict':verdict})
    result={'schema':'native-retrospective-scores-v1','protocol_sha256':protocol['protocol_sha256'],
            'prediction_seal_sha256':seal['prediction_seal_sha256'],'scope':contract['scope'],
            'dataset_count':1,'recorded_cell_count':1,'date_group_count':1,'condition_count':9,'eligible_repeats_per_condition':3,
            'scored_repeats_per_condition':len(next(iter(targets.values()))[2]),
            'observation_trial_policy':contract.get('scoring_observation',{}).get('trial_policy','all_eligible_repeat_mean'),
            'selected_trial_ids_by_case':contract['trial_ids_by_case'],
            'groups':groups,'comparisons':comparisons,'zero_response_baseline':endpoints(contract['cases'],zero),
            'observation_sources':observation_sources,'traces':traces,'failed_requests':seal['failed_requests'],
            'limits':contract['limits'],'absolute_rmse_reporting_threshold_mv':.05,
            'all_native_endpoints_scored':all(e['score'] is not None for g in groups for e in g['endpoints'].values()),
            'biological_superiority':'NOT_ESTABLISHED','inference':'Descriptive single-cell conditional comparison; no confidence interval or independent replication claimed.'}
    result['scores_sha256']=identity(result)
    driver._write_json(store,'scores.json',result,contract)
    return {k:v for k,v in result.items() if k not in {'traces','observation_sources','groups'}}
