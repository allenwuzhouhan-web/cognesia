"""Recover committed raw samples as an explicitly incomplete viewer recording."""
import json
import re
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd

from .fetch import checksum
from .inspect_data import atomic_write_json
from .model_anatomy import write_anatomy


def export_partial(root, identifier, checkpoint_id=None):
    from .experiment_session import _unpack
    if not re.fullmatch(r'[a-f0-9]{32}', identifier or ''):
        raise ValueError('Invalid partial recording ID')
    root = Path(root)
    source = root/'sessions'/identifier
    if source.is_symlink():
        raise ValueError('Invalid partial recording path')
    manifest = json.loads((source/'manifest.json').read_text())
    model_id = manifest.get('model_id', 'flywire-783')
    model_hash = manifest.get('model_hash')
    version = root/'build/model-versions'/str(model_hash)/'neurons.parquet'
    if model_id=='flywire-783':
        from .model_registry import get_model_manifest
        model=get_model_manifest(root,model_id,model_hash)
        expected=model.get('source_hashes',{}).get('neurons.parquet')
        if expected and checksum(root/'build/neurons.parquet')!=expected:
            raise ValueError('Historical recording neuron identities changed')
    elif model_hash and not version.exists():
        raise ValueError('The exact recorded model version is unavailable')
    table = version if version.exists() else (root/'build/neurons.parquet' if model_id == 'flywire-783' else root/'build/models'/model_id/'neurons.parquet')
    neurons = pd.read_parquet(table)
    parent = (manifest.get('selection') or {}).get('parent_indices')
    if parent is not None:
        neurons = neurons.iloc[parent].reset_index(drop=True)
    indices = np.asarray(manifest['node_indices'], dtype=np.int64)
    recorded_lookup={int(value):i for i,value in enumerate(indices)}
    neurons = neurons.iloc[indices].reset_index(drop=True)
    run_id = 'partial_'+identifier
    directory = root/'runs'/run_id; directory.mkdir(parents=True, exist_ok=True)
    times = []; spikes = deque(maxlen=200000); spike_times = deque(maxlen=200000)
    clamp_count = 0; total_spikes = 0
    with (directory/'raw.bin').open('wb') as output:
        for entry in manifest['chunks']:
            if not re.fullmatch(r'chunk-[0-9]{6}\.npz', entry['file']):
                raise ValueError('Invalid partial chunk')
            path = source/entry['file']
            if path.is_symlink() or checksum(path) != entry['sha256']:
                raise ValueError('Partial chunk integrity failed')
            with np.load(path, allow_pickle=False) as arrays:
                chunk = _unpack(entry['payload'], arrays)
            values = np.asarray(chunk['voltages_mv'], dtype='<f4')
            clock = np.asarray(chunk['voltage_times_ms'], dtype=float)
            clamp_count += int(np.sum(chunk.get('clamp_counts',chunk.get('per_neuron_clamp_counts',[]))))
            for neuron,timestamp in zip(chunk['spike_indices'],chunk['spike_times_ms'],strict=True):
                if int(neuron) in recorded_lookup:
                    spikes.append(recorded_lookup[int(neuron)]);spike_times.append(float(timestamp));total_spikes+=1
            if not len(clock):
                continue
            if values.shape != (len(clock), len(neurons)) or not np.isfinite(values).all():
                raise ValueError('Partial voltage shape or values are invalid')
            values.tofile(output); times.extend(clock.tolist())
    if not times:
        return None
    duration=max(float(manifest.get('duration_ms',manifest.get('elapsed_ms',0.))),times[-1],
                 spike_times[-1] if spike_times else 0.)
    neurons.to_parquet(directory/'recorded_neurons.parquet', index=False)
    prefix = '/api/runs/'+run_id
    anatomy = write_anatomy(neurons, directory/'anatomy', prefix+'/anatomy', model_id=model_id, model_hash=model_hash)
    summary = {'id': run_id, 'label': 'Partial '+manifest['phase']+' · stopped', 'partial': True,
        'neuron_count': len(neurons), 'model_id': model_id, 'model_hash': model_hash, 'anatomy': anatomy,
        'frames': {'count': len(times), 'time_ms': times, 'dt_ms': times[1]-times[0] if len(times)>1 else 1},
        'activity': {'raw_url': prefix+'/raw.bin', 'shape': [len(times),len(neurons)], 'unit': 'mV', 'raw_unit':'mV', 'dtype':'float32', 'color_range_mv':5},
        'stats': {'spikes': total_spikes, 'clamps':clamp_count}, 'traces':[], 'region_traces':[], 'class_traces':[],
        'stimulus': {'type':'partial', 'duration_ms':duration}, 'stimulation':{}, 'eyes':{},
        'spikes': {'spike_indices':list(spikes),'spike_times_ms':list(spike_times),
                   'total_count':total_spikes,'truncated':total_spikes>len(spikes)},
        'chemistry': {'available':False}, 'metadata': {'recording_id':identifier, 'checkpoint_id':checkpoint_id, 'phase':manifest['phase']},
        'warnings': ['Stopped, incomplete recording. Only committed raw samples are shown; matched-control differences are unavailable. Chemical and organ chunks remain in the journal.'],
        'interpretation': 'Partial raw simulation output, not a completed experiment or biological validation.'}
    atomic_write_json(directory/'visual_summary.json', summary)
    return summary
