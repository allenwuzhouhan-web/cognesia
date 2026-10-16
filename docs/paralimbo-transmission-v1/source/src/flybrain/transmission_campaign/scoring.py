"""Prediction seals and independent, condition/animal-balanced scoring.

This module never runs a simulator or selects model parameters. Outcome reading
is owned by data.py and is allowed only after this module verifies a complete
inventory of successful predictions and explicit failures.
"""
from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path

import numpy as np

from ..paralimbo_upgrade.interfaces import canonical_json, identity
from ..validation_project.common import file_hash


def balanced_error(records, expected_case_ids=None):
    """Equal animals, then equal conditions; all samples are paired on each case.

Each row has case_id, animal_id (cell_id is accepted for the T4 fallback), and
either a finite nonnegative mse or equal-shape prediction/observation arrays.
Missing, duplicate, failed or nonfinite cases produce INCOMPLETE, never zero.
"""
    records = list(records)
    seen, groups, failures = set(), defaultdict(list), []
    for row in records:
        cid = row['case_id']
        if cid in seen:
            raise ValueError('Duplicate scored condition')
        seen.add(cid)
        if row.get('status','PASS') not in {'PASS','COMPLETE','SCORED'}:
            failures.append(cid); continue
        if 'mse' in row:
            value = row['mse']
        else:
            p,y = np.asarray(row['prediction'],dtype=float),np.asarray(row['observation'],dtype=float)
            if p.shape!=y.shape or p.ndim!=1 or not p.size:
                raise ValueError('Paired nonempty condition arrays required')
            value = float(np.mean((p-y)**2))
        if not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
            failures.append(cid); continue
        animal = str(row.get('animal_id',row.get('cell_id','single_registered_cell')))
        groups[animal].append(float(value))
    expected = set(expected_case_ids) if expected_case_ids is not None else seen
    if seen-expected:
        raise ValueError('Score includes an unregistered condition')
    missing = sorted(expected-seen)
    complete = bool(groups) and not missing and not failures
    mse = math.fsum(math.fsum(v)/len(v) for v in groups.values())/len(groups) if complete else None
    return {'status':'SCORED' if complete else 'INCOMPLETE', 'balanced_mse':mse,
            'balanced_rmse_mv':math.sqrt(mse) if mse is not None else None,
            'animal_count':len(groups),'condition_count':len(seen),
            'missing_case_ids':missing,'failed_case_ids':sorted(failures),
            'weighting':'equal animals then equal conditions, sample MSE within condition'}


def classify_difference(baseline, candidate, tolerance_mv=.001):
    if not math.isfinite(tolerance_mv) or tolerance_mv<0:
        raise ValueError('Finite nonnegative numerical tolerance required')
    if baseline is None or candidate is None:
        return {'verdict':'INCOMPLETE','baseline_minus_candidate_mv':None,'tolerance_mv':tolerance_mv}
    if not np.isfinite([baseline,candidate]).all() or min(baseline,candidate)<0:
        raise ValueError('Finite nonnegative errors required')
    delta = float(baseline-candidate)
    verdict = 'CANDIDATE_LOWER_ERROR' if delta>tolerance_mv else 'BASELINE_LOWER_ERROR' if delta < -tolerance_mv else 'NUMERICAL_TIE'
    return {'verdict':verdict,'baseline_minus_candidate_mv':delta,'tolerance_mv':tolerance_mv}


def _prediction_path(directory, relative):
    directory = Path(directory).resolve()
    p = Path(relative)
    full = directory/p
    if (p.is_absolute() or '..' in p.parts or not full.is_file() or full.is_symlink()
            or full.stat().st_nlink!=1 or not full.resolve().is_relative_to(directory)):
        raise ValueError('Unsafe or missing prediction artifact')
    return full


def _prediction_arrays(path):
    with np.load(path,allow_pickle=False) as archive:
        names = set(archive.files)
        if names=={'time_ms','values_mv'}:
            t,p = archive['time_ms'].copy(),archive['values_mv'].copy()
        elif names >= {'observation_time_ms','observation_values_mv'}:
            t,p = archive['observation_time_ms'].copy(),archive['observation_values_mv'].copy()
        else:
            raise ValueError('Prediction file lacks physical time and voltage arrays')
    if t.ndim!=1 or p.shape!=t.shape or not t.size or not np.isfinite(t).all() or not np.isfinite(p).all() or np.any(np.diff(t)<=0):
        raise ValueError('Finite ordered prediction grid required')
    return t,p


def seal_predictions(directory, protocol_sha256, expected_keys, records):
    """Write prediction-seal.json once; records contain key/arm/case_id/status.

Successful rows also need path, relative to directory. Failure rows need reason.
Both kinds occupy an expected key. This prevents disappearing failed requests.
The controller includes selected parameter/input identities in each record.
"""
    directory = Path(directory)
    expected = list(expected_keys)
    if len(expected)!=len(set(expected)) or not expected:
        raise ValueError('Unique nonempty expected prediction inventory required')
    rows = [dict(r) for r in records]
    keys = [r['key'] for r in rows]
    if len(keys)!=len(set(keys)) or set(keys)!=set(expected):
        raise ValueError('Prediction inventory incomplete or duplicated')
    for row in rows:
        if not row.get('arm') or not row.get('case_id'):
            raise ValueError('Prediction arm and condition identity required')
        if row.get('status') in {'PASS','COMPLETE','PREDICTED'}:
            path = _prediction_path(directory,row['path'])
            t,_ = _prediction_arrays(path)
            row.update(sha256=file_hash(path),samples=len(t),status='PREDICTED')
        else:
            if not row.get('reason'):
                raise ValueError('Explicit failure reason required')
            row['status']='FAILED'
    body = {'schema':'transmission-prediction-seal-v1','protocol_sha256':protocol_sha256,
            'expected_keys':expected,'records':sorted(rows,key=lambda r:r['key']),
            'status':'COMPLETE_WITH_FAILURES' if any(r['status']=='FAILED' for r in rows) else 'COMPLETE',
            'evaluation_outcomes_read':False}
    seal = body | {'prediction_seal_sha256':identity(body)}
    destination = directory/'prediction-seal.json'
    directory.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        if json.loads(destination.read_bytes())!=seal:
            raise ValueError('An immutable prediction seal already exists')
    else:
        with destination.open('x') as handle:
            handle.write(canonical_json(seal)+'\n')
    return seal


def verify_prediction_seal(seal, directory, protocol_sha256, expected_case_ids=None, allowed_case_ids=None):
    body = {k:v for k,v in seal.items() if k!='prediction_seal_sha256'}
    if (seal.get('schema')!='transmission-prediction-seal-v1' or
            seal.get('prediction_seal_sha256')!=identity(body) or
            seal.get('protocol_sha256')!=protocol_sha256 or
            seal.get('status') not in {'COMPLETE','COMPLETE_WITH_FAILURES'} or
            seal.get('evaluation_outcomes_read') is not False):
        raise ValueError('Complete unchanged prediction seal required before outcome access')
    disk = _prediction_path(directory,'prediction-seal.json')
    if json.loads(disk.read_bytes())!=seal:
        raise ValueError('Prediction seal differs from retained bytes')
    rows = seal['records']; keys = [r['key'] for r in rows]
    if len(keys)!=len(set(keys)) or set(keys)!=set(seal['expected_keys']):
        raise ValueError('Sealed prediction inventory incomplete')
    if expected_case_ids is not None:
        wanted = set(expected_case_ids)
        allowed = set(allowed_case_ids) if allowed_case_ids is not None else wanted
        if not wanted<=allowed: raise ValueError('Required cases exceed allowed inventory')
        arms = {r['arm'] for r in rows}
        if len(arms)<2:
            raise ValueError('Paired arm predictions required')
        for arm in arms:
            actual = [r['case_id'] for r in rows if r['arm']==arm]
            if len(actual)!=len(set(actual)) or not wanted<=set(actual)<=allowed:
                raise ValueError('Each arm must account for every evaluation case')
    for row in rows:
        if row['status']=='PREDICTED':
            path = _prediction_path(directory,row['path'])
            if file_hash(path)!=row['sha256']:
                raise ValueError('Sealed prediction bytes changed')
            t,_ = _prediction_arrays(path)
            if len(t)!=row['samples']:
                raise ValueError('Prediction sample inventory changed')
        elif row['status']!='FAILED' or not row.get('reason'):
            raise ValueError('Invalid sealed failure')
    return seal


def score_sealed_predictions(seal, directory, observations, case_metadata, tolerance_mv=.001):
    """Recompute physical-grid errors from retained predictions, no simulator use."""
    cases = {c['case_id']:c for c in case_metadata}
    if len(cases)!=len(case_metadata) or set(observations)!=set(cases):
        raise ValueError('Observation inventory must exactly match registered scoring cases')
    verify_prediction_seal(seal,directory,seal['protocol_sha256'],expected_case_ids=cases)
    arms = sorted({r['arm'] for r in seal['records']})
    scores = {}
    endpoint_scores = {}
    for arm in arms:
        rows = []
        statistics = {}
        for row in seal['records']:
            if row['arm']!=arm: continue
            c = cases[row['case_id']]
            item = {'case_id':row['case_id'],'animal_id':str(c.get('animal_id',c.get('cell_id','single_registered_cell'))),
                    'status':row['status']}
            if row['status']=='FAILED':
                item.update(status='FAILED',reason=row['reason']);rows.append(item);continue
            t,p = _prediction_arrays(_prediction_path(directory,row['path']))
            obs = observations[row['case_id']]
            y = np.asarray(obs['values_mv'])
            if not np.array_equal(t,np.asarray(obs['time_ms'])) or y.shape!=p.shape or not np.isfinite(y).all():
                raise ValueError('Prediction/observation grid or values mismatch')
            mask = t>=0
            if not mask.any(): raise ValueError('No post-onset scoring samples')
            item.update(status='PASS',mse=float(np.mean((p[mask]-y[mask])**2)))
            item.update(waveform_rmse_mv=math.sqrt(item['mse']),
                        predicted_peak_mv=float(np.max(p[mask])),observed_peak_mv=float(np.max(y[mask])))
            statistics[row['case_id']] = dict(item)
            rows.append(item)
        scores[arm] = balanced_error(rows,cases) | {'case_errors':rows}
        # The full nine-condition inventory permits exact use of the historical
        # five-endpoint definitions; flash metrics remain calibration only.
        if all('family' in c for c in cases.values()) and {c['family'] for c in cases.values()}=={'flash','moving'}:
            from ..paralimbo_upgrade.retrospective_scoring import endpoints
            endpoint_scores[arm] = endpoints(list(cases.values()),statistics)
            for name, metric in endpoint_scores[arm].items():
                metric['phase'] = 'CALIBRATION' if name.startswith('flash_') else 'EVALUATION'
    baseline = next((a for a in arms if a in {'banc','baseline','banc-888'}),None)
    comparisons, regressions = [],[]
    if baseline is not None:
        for arm in arms:
            if arm==baseline: continue
            for name, metric in endpoint_scores.get(arm,{}).items():
                factor = 4 if name in {'direction_contrast_rmse','speed_contrast_rmse'} else 2
                comparisons.append({'baseline_arm':baseline,'candidate_arm':arm,'metric':name,
                    'phase':metric['phase'],**classify_difference(endpoint_scores[baseline][name]['score'],
                                                                metric['score'],max(factor*.001,factor*tolerance_mv))})
            baseline_cases = {r['case_id']:r for r in scores[baseline]['case_errors']}
            for row in scores[arm]['case_errors']:
                regressions.append({'baseline_arm':baseline,'candidate_arm':arm,'case_id':row['case_id'],
                    'phase':'CALIBRATION' if cases[row['case_id']].get('family')=='flash' else 'EVALUATION',
                    **classify_difference(baseline_cases[row['case_id']].get('waveform_rmse_mv'),
                                          row.get('waveform_rmse_mv'),max(.002,2*tolerance_mv))})
    body = {'schema':'transmission-scores-v1','prediction_seal_sha256':seal['prediction_seal_sha256'],
            'protocol_sha256':seal['protocol_sha256'],'scores':scores,'numerical_tolerance_mv':tolerance_mv,
            'endpoints':endpoint_scores,'comparisons':comparisons,'condition_comparisons':regressions,
            'scope':'retrospective_native_conditional_prediction','biological_superiority':'NOT_ESTABLISHED'}
    return body | {'scores_sha256':identity(body)}


def independently_verify(output):
    """Recompute the saved evaluation score with no model execution or fitting.

    Retained observation exports are independently checked against source hashes
    frozen before calibration. Neither a simulator nor cached scores are trusted.
"""
    from .data import input_specs, load_evaluation_observations, load_development_observations
    output = Path(output)
    try:
        benchmark = json.loads((output/'benchmark.json').read_bytes())
        if benchmark['benchmark_id']!='native_t4':
            return {'pass':False,'status':'UNSUPPORTED_BENCHMARK','biological_superiority':'NOT_ESTABLISHED'}
        protocol = benchmark['t4_protocol']
        directory = output/'predictions'
        seal = json.loads((directory/'prediction-seal.json').read_bytes())
        saved = json.loads((output/'scores.json').read_bytes())
        observations = load_evaluation_observations(protocol,seal,directory,retained_root=output)
        case_metadata = list(input_specs(protocol,'evaluation'))
        recorded = {r['case_id'] for r in seal['records']}
        if recorded & set(protocol['development_case_ids']):
            observations.update(load_development_observations(protocol,retained_root=output))
            case_metadata += input_specs(protocol,'development')
        computed = score_sealed_predictions(seal,directory,observations,case_metadata,
                                           tolerance_mv=saved['numerical_tolerance_mv'])
        passed = saved==computed
        secondary = None
        if (output/'scores-t4d.json').exists():
            alternate_directory = output/'predictions-t4d'
            alternate_seal = json.loads((alternate_directory/'prediction-seal.json').read_bytes())
            alternate_saved = json.loads((output/'scores-t4d.json').read_bytes())
            # Observation retention was gated by the primary seal. The fixed
            # alternate correspondence reuses the same independently checked
            # observations, after verification of its own prediction inventory.
            alternate_computed = score_sealed_predictions(alternate_seal,alternate_directory,
                observations,case_metadata,tolerance_mv=alternate_saved['numerical_tolerance_mv'])
            alternate_passed = alternate_saved==alternate_computed
            secondary = {'pass':alternate_passed,'status':'PASS' if alternate_passed else 'SCORE_MISMATCH',
                'computed_scores_sha256':alternate_computed['scores_sha256'],
                'prediction_seal_sha256':alternate_seal['prediction_seal_sha256']}
            passed = passed and alternate_passed
        return {'pass':passed,'status':'PASS' if passed else 'SCORE_MISMATCH',
                'computed_scores_sha256':computed['scores_sha256'],
                'prediction_seal_sha256':seal['prediction_seal_sha256'],
                'secondary_verification':secondary,
                'biological_superiority':'NOT_ESTABLISHED'}
    except (ValueError,KeyError,OSError) as exc:
        return {'pass':False,'status':'INVALID_EVIDENCE','reason':str(exc),
                'biological_superiority':'NOT_ESTABLISHED'}
