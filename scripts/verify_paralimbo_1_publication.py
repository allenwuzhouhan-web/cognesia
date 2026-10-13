#!/usr/bin/env python3
"""Independently recalculate the published single-cell benchmark (standard library).

This checks released traces, paired scores and metadata. It does not repeat the
27 native simulations or replace the separate full qualification/provenance audit.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

MODELS = ('banc-888', 'paralimbo-v0-1-0', 'paralimbo-visual-graded-v1')
METRICS = ('flash_spatial_peak_rmse', 'flash_duration_peak_rmse',
           'motion_waveform_rmse', 'direction_contrast_rmse', 'speed_contrast_rmse')
SOURCE_SCORE_ID = '37c9ac9606feed579a626c5586ca1150333d0d157d57e08f52eaaaa2b3da39d3'
PROTOCOL_ID = 'a78a968b766014514657269da41cf1402489ca7936a497b00b4ef847e437baef'
SEAL_ID = 'c429ebf38aff0d133bfad1c9c0b9c331279f7c9d819c5fd80afa8b017c6508eb'

def identity(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',', ':'),allow_nan=False).encode()).hexdigest()

def require(condition, label):
    if not condition:
        raise ValueError(label)

def close(a,b,label):
    require(math.isfinite(a) and math.isfinite(b) and abs(a-b)<=1e-11,label)

def rms(xs):
    require(bool(xs), 'Empty endpoint')
    return math.sqrt(math.fsum(x*x for x in xs)/len(xs))

def evaluate(cases, stats):
    flash=[c for c in cases if c['family']=='flash']
    moving=[c for c in cases if c['family']=='moving']
    out={
        'flash_spatial_peak_rmse':rms([stats[c['case_id']]['p']-stats[c['case_id']]['y'] for c in flash if c['duration_ms']==80]),
        'flash_duration_peak_rmse':rms([stats[c['case_id']]['p']-stats[c['case_id']]['y'] for c in flash if c['position']==0]),
        'motion_waveform_rmse':math.fsum(stats[c['case_id']]['rmse'] for c in moving)/len(moving),
    }
    for metric,group_key,values,positive in (
        ('direction_contrast_rmse','duration_ms',(20,80),lambda c:c['primary_axis_sign']==1),
        ('speed_contrast_rmse','primary_axis_sign',(-1,1),lambda c:c['duration_ms']==20)):
        errors=[]
        for value in values:
            pair=[c for c in moving if c[group_key]==value]
            require(len(pair)==2,'Contrast pair missing')
            first=[c for c in pair if positive(c)];second=[c for c in pair if not positive(c)]
            require(len(first)==len(second)==1,'Contrast orientation ambiguous')
            a,b=(stats[first[0]['case_id']],stats[second[0]['case_id']])
            errors.append((a['p']-b['p'])-(a['y']-b['y']))
        out[metric]=rms(errors)
    return out

def verify(folder):
    result=json.loads((folder/'results.json').read_text())
    protocol=json.loads((folder/'evidence/protocol.json').read_text())
    seal=json.loads((folder/'evidence/prediction-seal.json').read_text())
    for obj,key,expected in ((protocol,'protocol_sha256',PROTOCOL_ID),(seal,'prediction_seal_sha256',SEAL_ID)):
        require(obj[key]==expected==identity({k:v for k,v in obj.items() if k!=key}),key+' integrity')
    require(result['public_results_sha256']==identity({k:v for k,v in result.items() if k!='public_results_sha256'}),'Public result integrity')
    require(result['source_scores_sha256']==SOURCE_SCORE_ID,'Original score identity')
    require(result['protocol_sha256']==PROTOCOL_ID and result['prediction_seal_sha256']==SEAL_ID,'Result provenance')
    require(seal['status']=='COMPLETE' and seal['expected_requests']==27 and len(seal['predictions'])==27 and not seal['failed_requests'],'Prediction completeness')
    contract=protocol['contract'];cases=contract['cases'];case_ids={c['case_id'] for c in cases}
    require(len(cases)==9 and set(contract['models'])==set(MODELS),'Frozen workload')
    require(result['recorded_cell_count']==1 and result['dataset_count']==1 and result['scored_repeats_per_condition']==1,'Study scope')
    require(result['biological_superiority']=='NOT_ESTABLISHED' and not result['failed_requests'],'Scientific status')
    require(len(result['traces'])==27 and len(result['groups'])==3 and len(result['comparisons'])==10,'Score inventory')
    expected_keys={(m,'primary',c['case_id'],contract['trial_ids_by_case'][c['case_id']][0]) for m in MODELS for c in cases}
    require({(r['model_id'],r['sensitivity_id'],r['case_id'],r['trial_id']) for r in seal['predictions']}==expected_keys,'Sealed request identities')
    all_scores={};zero_stats={};observations={};sample_checks=0
    for model in MODELS:
        groups=[g for g in result['groups'] if g['model_id']==model and g['sensitivity_id']=='primary']
        require(len(groups)==1,'Duplicate/missing model')
        group=groups[0];require(not group['missing_case_ids'],'Missing cases')
        stats={}
        for case in cases:
            cid=case['case_id'];trace=result['traces'][model+'/primary/'+cid]
            t,p,y=(trace[k] for k in ('time_ms','prediction_mv','observation_mv'))
            require(len(t)==len(p)==len(y)>1 and all(a<b for a,b in zip(t,t[1:])),'Trace shape/time')
            require(all(math.isfinite(x) for series in (t,p,y) for x in series),'Nonfinite trace')
            selected=min(case['eligible_trial_indices'])
            require(trace['scored_repeat_count']==1 and trace['scored_trial_indices']==[selected] and trace['observation_sem_mv'] is None,'Paired single-trial target')
            if cid in observations:require(observations[cid]==(t,y),'Models have different observed target')
            else:observations[cid]=(t,y)
            post=[i for i,x in enumerate(t) if x>=0];require(bool(post),'No scoring window')
            pp=[p[i] for i in post];yy=[y[i] for i in post]
            stats[cid]={'p':max(pp),'y':max(yy),'rmse':rms([a-b for a,b in zip(pp,yy)])}
            stated=group['case_statistics'][cid]
            for short,full in [('p','predicted_peak_mv'),('y','observed_peak_mv'),('rmse','waveform_rmse_mv')]:close(stats[cid][short],stated[full],cid+' '+full)
            require(stated['post_onset_samples']==len(post),'Sample count')
            if model in MODELS[:2]:require(all(x==0 for x in p),'Silent baseline disclosure')
            zero_stats[cid]={'p':0,'y':max(yy),'rmse':rms(yy)}
            sample_checks+=len(t)
        scores=evaluate(cases,stats);all_scores[model]=scores
        require(set(group['endpoints'])==set(METRICS),'Endpoint inventory')
        for metric,value in scores.items():
            row=group['endpoints'][metric]
            require(row['status']=='SCORED' and row['unit']=='mV' and row['direction']=='lower' and not row['missing_case_ids'],'Endpoint metadata')
            close(value,row['score'],model+' '+metric)
    for metric,value in evaluate(cases,zero_stats).items():close(value,result['zero_response_baseline'][metric]['score'],'Zero '+metric)
    counts={m:0 for m in MODELS[1:]};keys=set()
    for row in result['comparisons']:
        model,metric=row['model_id'],row['metric'];require((model,metric) not in keys,'Duplicate comparison');keys.add((model,metric))
        require(model in counts and metric in METRICS,'Unknown comparison')
        b,p=all_scores[MODELS[0]][metric],all_scores[model][metric]
        delta=b-p;margin=contract['numerical_separation_mv'][metric]
        close(row['banc_score'],b,'BANC comparison');close(row['paralimbo_score'],p,'Candidate comparison')
        close(row['banc_minus_paralimbo_mv'],delta,'Paired difference');close(row['numerical_separation_mv'],margin,'Numerical separation')
        verdict='PARALIMBO_LOWER_ERROR' if delta>margin else 'BANC_LOWER_ERROR' if delta<-margin else 'WITHIN_NUMERICAL_SEPARATION'
        require(row['verdict']==verdict,'Verdict mismatch');counts[model]+=verdict=='PARALIMBO_LOWER_ERROR'
    require(counts=={MODELS[1]:0,MODELS[2]:4},'Headline verdict')
    return {'status':'PASS','native_predictions':27,'native_endpoint_scores':15,'zero_reference_scores':5,'paired_comparisons':10,'trace_samples_checked':sample_checks,'original_wins':0,'paralimbo_1_wins':4,'biological_superiority':'NOT_ESTABLISHED','scope':'Public trace arithmetic and metadata; does not rerun full native qualification.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,default=Path(__file__).resolve().parents[1]/'docs/paralimbo-1')
    args=parser.parse_args()
    print(json.dumps(verify(args.folder),indent=2))

if __name__=='__main__':main()
