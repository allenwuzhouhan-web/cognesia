#!/usr/bin/env python3
"""Run a bounded ParaLimbo numerical smoke and deterministic replay check.

This is an execution check, not biological validation or a stationarity test.
Outputs contain relative run identifiers and hashes, never access credentials.
"""
from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
import time

import numpy as np

from flybrain.model_registry import PARALIMBO_ID, load_model_network
from flybrain.visual_experiment import run_visual_experiment


def check_arrays(first, second):
    """Compare every saved numeric array, including spikes and chemical fields."""
    checks = {}
    with np.load(first, allow_pickle=False) as a, np.load(second, allow_pickle=False) as b:
        if set(a.files) != set(b.files):
            raise ValueError('Replay array names differ')
        for key in a.files:
            x, y = a[key], b[key]
            numeric = np.issubdtype(x.dtype, np.number)
            checks[key] = {
                'shape': list(x.shape),
                'equal': bool(np.array_equal(x, y)),
                'finite': bool(np.isfinite(x).all() and np.isfinite(y).all()) if numeric else None,
            }
    return checks


def validate(root):
    root = Path(root).resolve()
    network = load_model_network(root, PARALIMBO_ID)
    model_hash = network['manifest']['model_hash']
    neuron_count = len(network['neurons'])
    indices = np.unique(np.linspace(0, neuron_count - 1, min(32, neuron_count), dtype=int))
    roots = network['neurons'].root_id.iloc[indices].astype(str).tolist()
    del network
    gc.collect()
    options = {
        'model_id': f'{PARALIMBO_ID}@{model_hash}', 'stimulus': 'dark',
        'duration_ms': 300., 'threads': 4, 'record_dt_ms': 20.,
        'neural_overrides': {'pre_equilibration': 100.},
        'neuromod': {'enabled': True, 'plasticity_enabled': False},
        'recording_selection': {'root_ids': roots},
    }
    runs, manifests, seconds = [], [], []
    for index in range(2):
        started = time.monotonic()
        result = run_visual_experiment(root, options)
        seconds.append(time.monotonic() - started)
        manifest = json.loads((Path(result['activity_path']).parent/'run_manifest.json').read_text())
        runs.append(result)
        manifests.append(manifest)
        print(f'Completed replay arm {index + 1}: {seconds[-1]:.2f} seconds', flush=True)
    activity = check_arrays(runs[0]['activity_path'], runs[1]['activity_path'])
    chemistry = check_arrays(runs[0]['chemistry_path'], runs[1]['chemistry_path'])
    array_checks = list(activity.values()) + list(chemistry.values())
    arrays_pass = all(c['equal'] and c['finite'] is not False for c in array_checks)
    counts_match = all(m['n_neurons'] == neuron_count and m['model_hash'] == model_hash for m in manifests)
    clamp_counts = [r['stats'][key] for r in runs for key in ('clamp_count', 'baseline_clamp_count')]
    preparation_clamps = [m['preequilibration']['clamp_events'] for m in manifests]
    preparation_finite = all(m['preequilibration']['nonfinite_derivatives'] == 0 for m in manifests)
    report = {
        'schema_version': 1, 'model_id': PARALIMBO_ID, 'model_hash': model_hash,
        'status': 'PASS' if arrays_pass and counts_match and preparation_finite and not any(clamp_counts + preparation_clamps) else 'FAIL',
        'scope': '300 ms paired dark execution, after fixed 100 ms preparation, repeated twice; no biological or global stability claim',
        'acceptance': {'numeric_recordings_finite': True, 'replay_arrays_exact': True,
                       'candidate_identity_exact': True, 'stimulus_and_baseline_clamps': 0,
                       'preparation_clamps': 0, 'preparation_nonfinite_derivatives': 0},
        'simulated_neurons': neuron_count, 'recorded_neurons': len(roots), 'options': options,
        'run_ids': [Path(r['activity_path']).parent.name for r in runs], 'wall_seconds': seconds,
        'activity_arrays': activity, 'chemistry_arrays': chemistry,
        'clamp_counts': clamp_counts, 'preparation_clamp_counts': preparation_clamps,
        'preparation_diagnostics': [m['preequilibration'] for m in manifests],
        'input_hashes': manifests[0].get('input_hashes', {}),
        'source_projection': runs[0]['chemistry']['source_projection'],
        'receptor_coverage': runs[0]['chemistry'].get('receptor_coverage', {}),
        'chemical_diagnostics': runs[0]['chemistry'].get('diagnostics', {}),
        'biological_improvement': 'PENDING', 'stationarity_validation': 'NOT_ESTABLISHED',
        'timestep_convergence': 'NOT_EVALUATED',
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = validate(args.root)
    path = args.output or args.root/'build/validation_paralimbo_runtime.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k: report[k] for k in ('status', 'model_hash', 'simulated_neurons', 'recorded_neurons', 'clamp_counts', 'biological_improvement')}, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
