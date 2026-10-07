"""Discoverable runtime controls for the local experimental workbench."""
from pathlib import Path
import yaml

from .stimulation import NEURAL_OVERRIDE_LIMITS, VISUAL_OVERRIDE_LIMITS, available_threads, resolve_electrodes

BODY_LABELS = {'left_eye': 'Left eye', 'right_eye': 'Right eye', 'antennae': 'Antennae',
               'legs': 'Legs', 'wings': 'Wings'}


def lab_configuration(root, neurons):
    root = Path(root)
    neural = yaml.safe_load((root / 'config/parameters.yaml').read_text())['parameters']
    optical = yaml.safe_load((root / 'config/visual_parameters.yaml').read_text())['parameters']
    schema = []
    for group, limits in [('neural', NEURAL_OVERRIDE_LIMITS), ('optical', VISUAL_OVERRIDE_LIMITS)]:
        for key, bounds in limits.items():
            entry = (optical if key in optical else neural)[key]
            item = {'key': key, 'label': key.replace('_', ' ').capitalize(), 'group': group,
                    'unit': entry['unit'], 'default': entry['value'], 'source': entry['source'],
                    'step': 1 if bounds.get('integer') else 'any',
                    'help': entry.get('note', 'Runtime override; the saved model configuration stays unchanged.')}
            if 'choices' in bounds:
                item.update(type='select', options=bounds['choices'])
            else:
                item.update(type='number', min=bounds['min'], max=bounds['max'])
            schema.append(item)
    targets = []
    for key, label in BODY_LABELS.items():
        resolved = resolve_electrodes(neurons, [{'id': key, 'target': {'kind': 'body_zone', 'name': key}}])[0]
        targets.append({'id': key, 'label': label, 'neuron_count': len(resolved.indices),
                        'mapping_note': resolved.definition['assumption'],
                        'target': {'kind': 'body_zone', 'name': key}})
    cores = available_threads()
    presets = [
        {'id': 'interactive', 'label': 'Interactive', 'threads': cores, 'duration_ms': 600,
         'record_dt_ms': 20, 'dt_ms': .1, 'neural_overrides': {'dt': .1}, 'visual_overrides': {'optics_samples': 4096},
         'description': 'Full connectome · short experiments · 20 ms recordings'},
        {'id': 'beast', 'label': 'BEAST', 'threads': cores, 'duration_ms': 3000,
         'record_dt_ms': 10, 'dt_ms': .05, 'neural_overrides': {'dt': .05}, 'visual_overrides': {'optics_samples': 8192},
         'description': 'Twice the neural time resolution · 8,192 optical rays · 3 s paired runs'},
        {'id': 'maximum', 'label': 'Maximum detail', 'threads': cores, 'duration_ms': 10000,
         'record_dt_ms': 10, 'dt_ms': .025, 'neural_overrides': {'dt': .025}, 'visual_overrides': {'optics_samples': 16384},
         'description': '25 μs integration · 16,384 optical rays · 10 s paired runs · sustained compute'},
    ]
    return {'parameter_schema': schema, 'electrical_targets': targets, 'performance_presets': presets,
            'electrode_model': 'Virtual additive membrane input in model mV, not a physical tissue electric-field simulation.',
            'simulation_limits': {'duration_ms': [300, 10000], 'duration_step_ms': 20, 'threads': cores,
                'max_threads': cores, 'snapshot_ms_options': [2, 5, 10, 20, 50],
                'dt_ms_options': [.025, .05, .1, .2], 'default_snapshot_ms': 20, 'default_dt_ms': .1,
                'concurrent_runs': 1, 'max_electrodes': 16, 'recording_budget_bytes': 3_000_000_000}}
