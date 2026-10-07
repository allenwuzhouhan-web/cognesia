"""Incremental, single-owner experiments and portable, identity-bound checkpoints.

Display callbacks observe completed integration blocks. They never supply model
clock time. Checkpoints use JSON + numeric NPZ arrays, never executable pickle.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid

import numpy as np

from .fetch import checksum
from .memguard import check_memory
from .stimulation import input_layout, combined_drive, resolve_electrodes

STATE_ARRAYS = ('v', 'g', 'last_spike', 'refractory_steps', 'active', 'firing',
                'ring', 'ring_counts', 'release_history', 'per_neuron_clamp_counts','output_enabled')
SESSION_KEYS = frozenset({'timeline', 'interventions', 'from_checkpoint', 'live_chunk_ms',
                          'model_id', 'research_selection', 'modules','peripheral',
                          'prepare_reference','reference_selection','branch_time_ms','recording_selection'})
COMPONENTS = ('chemistry', 'organs', 'enzymes')


class ExperimentStopped(RuntimeError):
    def __init__(self, checkpoint_id, recording_id=None):
        self.checkpoint_id = checkpoint_id
        self.recording_id = recording_id
        super().__init__('Experiment stopped; recoverable checkpoint ' + str(checkpoint_id))


def _number(value, name, minimum=0., maximum=np.inf):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be a finite number in [{minimum}, {maximum}]')
    return float(value)


def normalize_session_options(value=None):
    value = dict(value or {})
    if set(value) - SESSION_KEYS:
        raise ValueError('Unknown session options: ' + ', '.join(sorted(set(value) - SESSION_KEYS)))
    out = copy.deepcopy(value)
    if 'peripheral' in value:
        if 'modules' in value and value['modules'] != value['peripheral']:
            raise ValueError('modules and peripheral specify conflicting controls')
        out['modules']=copy.deepcopy(value['peripheral'])
    if 'reference_selection' in value and 'research_selection' not in value:
        out['research_selection']=copy.deepcopy(value['reference_selection'])
    if 'prepare_reference' in value and not isinstance(value['prepare_reference'],bool):
        raise ValueError('prepare_reference must be boolean')
    if 'branch_time_ms' in value:
        out['branch_time_ms']=_number(value['branch_time_ms'],'branch_time_ms')
        if not value.get('from_checkpoint'):
            raise ValueError('branch_time_ms requires from_checkpoint')
    out['live_chunk_ms'] = _number(value.get('live_chunk_ms', 10.), 'live_chunk_ms', 1., 100.)
    if value.get('from_checkpoint') is not None and not re.fullmatch(r'[a-f0-9]{32}', str(value['from_checkpoint'])):
        raise ValueError('from_checkpoint must be a checkpoint ID')
    if not isinstance(value.get('interventions', []), list):
        raise ValueError('interventions must be a list')
    if len(value.get('interventions', [])) > 256:
        raise ValueError('At most 256 interventions are supported')
    timeline = value.get('timeline')
    if timeline is not None:
        if not isinstance(timeline, dict) or set(timeline) - {'schema_version', 'name', 'blocks', 'repeat'} or timeline.get('schema_version', 1) != 1 or not isinstance(timeline.get('blocks'), list):
            raise ValueError('timeline must be a version-1 document with a blocks list')
        if len(timeline['blocks']) > 512:
            raise ValueError('At most 512 timeline blocks are supported')
    return out


def snapshot_state(engine):
    result = {'step': int(engine.step), 'clamp_count': int(engine.clamp_count),
              **{name: getattr(engine, name).copy() for name in STATE_ARRAYS}}
    # The native ring reserves np.empty capacity beyond each live count. Those
    # bytes are not queued signals and must not become checkpoint identity.
    for index,count in enumerate(result['ring_counts']): result['ring'][index,int(count):]=0
    # Preserve nonplastic experimental changes as well as learned weights.
    for name in ('csc_counts', 'graded_counts'):
        if hasattr(engine, name):
            result[name] = getattr(engine, name).copy()
    for name in COMPONENTS:
        component = getattr(engine, name, None)
        if component is not None:
            if not callable(getattr(component, 'snapshot', None)):
                raise ValueError(f'{name} does not support complete checkpoints')
            result[name] = copy.deepcopy(component.snapshot())
    if getattr(engine, 'rng', None) is not None:
        result['rng_state'] = copy.deepcopy(engine.rng.bit_generator.state)
    return result


def _validate_tree(expected, actual, path='state'):
    if isinstance(expected, np.ndarray):
        if not isinstance(actual, np.ndarray) or expected.shape != actual.shape or expected.dtype != actual.dtype:
            raise ValueError(f'Checkpoint array identity mismatch: {path}')
        if actual.dtype.kind in 'fc' and not np.isfinite(actual).all():
            raise ValueError(f'Nonfinite checkpoint array: {path}')
    elif isinstance(expected, dict):
        if not isinstance(actual, dict) or set(expected) != set(actual):
            raise ValueError(f'Checkpoint fields mismatch: {path}')
        for key in expected:
            _validate_tree(expected[key], actual[key], path + '.' + str(key))
    elif isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)) or len(expected) != len(actual):
            raise ValueError(f'Checkpoint sequence mismatch: {path}')
        for i, (a, b) in enumerate(zip(expected, actual, strict=True)):
            _validate_tree(a, b, path + '.' + str(i))


def restore_state(engine, state):
    previous = snapshot_state(engine)
    _validate_tree(previous, state)
    if isinstance(state['step'], bool) or int(state['step']) != state['step'] or state['step'] < 0:
        raise ValueError('Checkpoint step must be a nonnegative integer')

    def apply(saved):
        for name in STATE_ARRAYS + ('csc_counts', 'graded_counts'):
            if name in saved:
                getattr(engine, name)[:] = saved[name]
        engine.step, engine.clamp_count = int(saved['step']), int(saved['clamp_count'])
        for name in COMPONENTS:
            if name in saved:
                getattr(engine, name).restore(copy.deepcopy(saved[name]))
        if 'rng_state' in saved:
            engine.rng.bit_generator.state = copy.deepcopy(saved['rng_state'])
        engine.last_result = engine.partial_result = None
    try:
        apply(state)
    except Exception:
        apply(previous)
        raise


def model_fingerprint(engine, identities=None, sources=None):
    digest = hashlib.sha256()
    digest.update(Path(__file__).read_bytes())
    digest.update(json.dumps({'parameters': engine.parameters, 'dt': engine.dt,
                              'sources': sources or {}}, sort_keys=True).encode())
    for name in ('graded_mask', 'csc_indptr', 'csc_indices', 'csc_counts',
                 'graded_indptr', 'graded_indices', 'graded_counts'):
        array = np.ascontiguousarray(getattr(engine, name))
        digest.update(name.encode()); digest.update(str(array.dtype).encode()); digest.update(array.tobytes())
    if identities is not None:
        digest.update(json.dumps([str(x) for x in identities], separators=(',', ':')).encode())
    return digest.hexdigest()


def _pack(value, arrays):
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            raise ValueError('Object arrays cannot be checkpointed')
        key = 'array_' + str(len(arrays))
        arrays[key] = value
        return {'__array__': key}
    if isinstance(value, dict):
        return {str(k): _pack(v, arrays) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_pack(v, arrays) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _unpack(value, arrays):
    if isinstance(value, dict):
        if set(value) == {'__array__'}:
            return arrays[value['__array__']].copy()
        return {k: _unpack(v, arrays) for k, v in value.items()}
    if isinstance(value, list):
        return [_unpack(v, arrays) for v in value]
    return value


def save_checkpoint(root, engine, context, fingerprint, *, label='', parent_checkpoint_id=None):
    identifier = uuid.uuid4().hex
    folder = Path(root) / 'checkpoints'
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / ('.' + identifier)
    temporary.mkdir()
    arrays = {}
    payload = _pack({'engine': snapshot_state(engine), 'context': context}, arrays)
    if shutil.disk_usage(folder).free < sum(a.nbytes for a in arrays.values())+16*1024**2:
        raise ValueError('Insufficient free disk for a complete checkpoint')
    np.savez(temporary / 'state.npz', **arrays)
    manifest = {'schema_version': 1, 'id': identifier, 'created_at': datetime.now(timezone.utc).isoformat(),
                'label': str(label)[:200], 'model_fingerprint': fingerprint,
                'step': int(engine.step), 'dt_ms': float(engine.dt),
                'model_time_ms': float(engine.step * engine.dt),
                'phase': context.get('phase'), 'parent_checkpoint_id': parent_checkpoint_id,
                'recording_id': context.get('recording_id'),
                'options': context.get('experiment_options',context.get('options', {})), 'data_sha256': checksum(temporary / 'state.npz'),
                'payload': payload, 'completed': False}
    # The manifest is the commit record; incomplete temporary directories are ignored.
    (temporary / 'manifest.json').write_text(json.dumps(manifest, allow_nan=False, separators=(',', ':')) + '\n')
    os.replace(temporary, folder / identifier)
    return {k: v for k, v in manifest.items() if k != 'payload'}


def read_checkpoint(root, identifier, *, fingerprint=None):
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier):
        raise ValueError('Invalid checkpoint ID')
    base = (Path(root) / 'checkpoints').resolve()
    folder = base / identifier
    if folder.is_symlink() or folder.resolve().parent != base:
        raise ValueError('Checkpoint path must remain within its store')
    manifest = json.loads((folder / 'manifest.json').read_text())
    if manifest.get('schema_version') != 1 or manifest.get('id') != identifier:
        raise ValueError('Unsupported checkpoint manifest')
    if fingerprint is not None and manifest.get('model_fingerprint') != fingerprint:
        raise ValueError('Checkpoint model/configuration identity differs')
    if (folder / 'state.npz').is_symlink() or checksum(folder / 'state.npz') != manifest['data_sha256']:
        raise ValueError('Checkpoint array integrity failed')
    with np.load(folder / 'state.npz', allow_pickle=False) as arrays:
        payload = _unpack(manifest['payload'], arrays)
    return manifest, payload


def estimate_session_memory(engine, *, duration_ms, recorded_neurons, boundary=None,
                            paired_boundary=None, reference_steps=0, selected_neurons=0):
    """Conservative dense allocations in addition to the already loaded graph."""
    def size(value):
        if isinstance(value, np.ndarray): return int(value.nbytes)
        if isinstance(value, dict): return sum(size(v) for v in value.values())
        if isinstance(value, (tuple, list)): return sum(size(v) for v in value)
        return 0
    neural=sum(getattr(engine,name).nbytes for name in STATE_ARRAYS)
    neural+=sum(getattr(engine,name).nbytes for name in ('csc_counts','graded_counts') if hasattr(engine,name))
    component=sum(size(getattr(engine,name).snapshot()) for name in COMPONENTS if getattr(engine,name,None) is not None)
    checkpoint=neural+component
    boundary_bytes=sum(size(vars(b)) for b in (boundary,paired_boundary) if b is not None)
    if reference_steps:
        boundary_bytes=max(boundary_bytes,int(reference_steps)*int(selected_neurons)*8*4)
        chemistry=getattr(engine,'chemistry',None); organs=getattr(engine,'organs',None)
        ticks=int(np.ceil(duration_ms))
        if chemistry is not None:
            boundary_bytes+=2*ticks*(2*chemistry.field.C.size+76)*8
        if organs is not None: boundary_bytes+=2*ticks*len(organs.modules)*8
    samples=int(np.ceil(duration_ms/(engine.dt*engine.record_stride)))
    recordings=samples*int(recorded_neurons)*4*3
    return {'recording_float32_bytes':recordings,'complete_checkpoint_array_bytes':checkpoint,
            'checkpoint_temporary_copy_bytes':checkpoint*2,'boundary_buffer_bytes':boundary_bytes,
            'estimated_additional_peak_bytes':recordings+checkpoint*3+boundary_bytes,
            'estimate_scope':'Dense recordings, branch state, checkpoint copies and paired boundary channels; excludes loaded graph, Python overhead and compression buffers.'}


class RecordingJournal:
    """Atomically committed chunks remain readable after stop or process failure."""
    def __init__(self, root, phase, indices, context):
        self.id=uuid.uuid4().hex
        self.path=Path(root)/'sessions'/self.id
        self.path.mkdir(parents=True)
        self.manifest={'schema_version':1,'id':self.id,'phase':phase,'status':'running','completed':False,
            'elapsed_ms':0.,'duration_ms':0.,
            'model_id':context.get('model_id','flywire-783'),'model_hash':context.get('model_hash'),
            'selection':context.get('selection'),'node_indices':np.asarray(indices).tolist(),'chunks':[],
            'signal':'baseline' if phase=='paired_baseline' else 'raw','baseline_available':phase=='paired_baseline'}
        self.commit()

    def commit(self):
        temporary=self.path/'manifest.tmp'
        temporary.write_text(json.dumps(self.manifest,allow_nan=False,separators=(',',':'))+'\n')
        os.replace(temporary,self.path/'manifest.json')

    def append(self, part, start, dt, record_now, organs=None):
        arrays={}
        payload={'voltage_times_ms':part['voltage_times']-start*dt,
                 'voltages_mv':part['voltages'],'spike_indices':part['spike_indices'],
                 'spike_times_ms':part['spike_times']-start*dt,
                 'clamp_indices':np.flatnonzero(part['per_neuron_clamp_counts']).astype(np.int32),
                 'clamp_counts':part['per_neuron_clamp_counts'][part['per_neuron_clamp_counts']!=0]}
        if not record_now:
            payload.update(voltage_times_ms=np.empty(0,np.float32),voltages_mv=np.empty((0,0),np.float32),
                           spike_indices=np.empty(0,np.int32),spike_times_ms=np.empty(0,np.float32))
        if 'chemistry' in part and record_now: payload['chemistry']=part['chemistry']
        if organs is not None and record_now: payload['organs']=organs
        packed=_pack(payload,arrays)
        name=f'chunk-{len(self.manifest["chunks"]):06d}.npz'
        temporary=self.path/(name+'.tmp')
        with temporary.open('wb') as handle: np.savez(handle,**arrays)
        os.replace(temporary,self.path/name)
        self.manifest['chunks'].append({'file':name,'sha256':checksum(self.path/name),'payload':packed})
        self.manifest['elapsed_ms']+=float(part['simulated_ms'])
        self.manifest['duration_ms']=self.manifest['elapsed_ms']
        self.commit()

    def finish(self,status):
        self.manifest.update(status=status,completed=status=='complete')
        self.commit()


def read_partial_recording(root, identifier):
    if not isinstance(identifier,str) or not re.fullmatch(r'[a-f0-9]{32}',identifier):
        raise ValueError('Invalid partial recording ID')
    base=(Path(root)/'sessions').resolve(); folder=base/identifier
    if folder.is_symlink() or folder.resolve().parent!=base: raise ValueError('Invalid recording path')
    manifest=json.loads((folder/'manifest.json').read_text())
    chunks=[]
    for entry in manifest['chunks']:
        if not re.fullmatch(r'chunk-[0-9]{6}\.npz',entry['file']): raise ValueError('Invalid recording chunk')
        path=folder/entry['file']
        if path.is_symlink() or checksum(path)!=entry['sha256']: raise ValueError('Recording chunk integrity failed')
        with np.load(path,allow_pickle=False) as arrays: chunks.append(_unpack(entry['payload'],arrays))
    return manifest,chunks


def remaining_intervals(rows, elapsed, duration):
    """Shift absolute interval definitions onto a fork's local clock."""
    result = []
    for source in rows:
        row = copy.deepcopy(source)
        start = float(row.get('start_ms', 0)) - elapsed
        end = float(row.get('end_ms', elapsed + duration)) - elapsed
        if row.get('kind') == 'checkpoint':
            if start <= 0 or start > duration:
                continue
        elif end <= 0 or start >= duration:
            continue
        row['start_ms'], row['end_ms'] = max(0., start), min(duration, end)
        result.append(row)
    return result


def compile_timeline(document, duration_ms, dt_ms, *, chemical_tick_ms=1.,state_tick_ms=None):
    """Validate deterministic graphical/API blocks; return chronological events."""
    if not document:
        return []
    normalize_session_options({'timeline': document})
    for block in document['blocks']:
        if not isinstance(block,dict): raise ValueError('Timeline blocks must be objects')
        _number(block.get('start_ms',block.get('t_ms',0)),'timeline.start_ms',0,duration_ms)
        _number(block.get('duration_ms',block.get('dur_ms',0)),'timeline.duration_ms',0,duration_ms)
    repeat = document.get('repeat', 1)
    if isinstance(repeat, dict):
        if set(repeat) - {'count', 'interval_ms'}:
            raise ValueError('Unknown repeat option')
        count = repeat.get('count', 1)
        interval = _number(repeat.get('interval_ms'), 'repeat.interval_ms', dt_ms, duration_ms)
    else:
        count = repeat
        interval = max((float(b.get('start_ms', b.get('t_ms', 0))) + float(b.get('duration_ms', b.get('dur_ms', 0))) for b in document['blocks']), default=0.)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100:
        raise ValueError('repeat count must be an integer in [1,100]')
    blocks = []
    for repetition in range(count):
        for block in document['blocks']:
            blocks.append(dict(block, start_ms=float(block.get('start_ms', block.get('t_ms', 0))) + repetition * interval,
                               repetition=repetition))
    if len(blocks) > 4096:
        raise ValueError('Expanded timeline exceeds 4096 blocks')
    events, intervals = [], {}
    for ordinal, block in enumerate(blocks):
        if not isinstance(block, dict):
            raise ValueError('Timeline blocks must be objects')
        kind = block.get('kind')
        if kind not in {'rest', 'visual', 'electrode', 'chemical', 'enzyme', 'intervention', 'checkpoint', 'recording'}:
            raise ValueError('Unsupported timeline kind: ' + str(kind))
        start = _number(block.get('start_ms', block.get('t_ms', 0)), 'timeline.start_ms', 0, duration_ms)
        duration = _number(block.get('duration_ms', block.get('dur_ms', 0)), 'timeline.duration_ms', 0, duration_ms)
        end = start + duration
        if end > duration_ms + 1e-9 or (kind != 'checkpoint' and duration <= 0):
            raise ValueError('Timeline block falls outside experiment or has no duration')
        quantum = chemical_tick_ms if kind in {'chemical', 'enzyme'} else state_tick_ms if state_tick_ms and kind in {'recording','checkpoint'} else dt_ms
        if not np.isclose(start / quantum, round(start / quantum), atol=1e-8) or not np.isclose(end / quantum, round(end / quantum), atol=1e-8):
            raise ValueError('Timeline boundaries must align with their integration clock')
        if kind in {'visual', 'rest'}:
            key = 'visual'
        elif kind == 'chemical':
            from .neuromod.field import FIELD_SPECIES
            if block.get('species') not in FIELD_SPECIES: raise ValueError('Unknown chemical timeline species')
            _number(block.get('level'),'chemical.level',0,2)
            key = 'chemical:' + str(block.get('species'))
        elif kind == 'enzyme':
            from .enzymes import ENZYME_IDS
            if block.get('enzyme_id') not in ENZYME_IDS: raise ValueError('Unknown enzyme timeline identity')
            _number(block.get('activity'),'enzyme.activity',0,10)
            key = 'enzyme:' + str(block.get('enzyme_id'))
        elif kind == 'recording':
            key = 'recording'
        else:
            key = None
        if key:
            for a, b in intervals.setdefault(key, []):
                if start < b and a < end:
                    raise ValueError('Overlapping timeline writes to ' + key)
            intervals[key].append((start, end))
        event = copy.deepcopy(block) | {'start_ms': start, 'end_ms': end, 'ordinal': ordinal}
        events.append(event)
    return sorted(events, key=lambda b: (b['start_ms'], b['ordinal']))


def validate_timeline_targets(neurons, timeline, *, electrodes=(), interventions=()):
    """Reject overlapping writes by resolved identity, preserving legacy sums."""
    rows=[]
    def targets(selector):
        return set(resolve_electrodes(neurons,[{'id':'timeline-target','target':selector}])[0].indices.tolist())
    def append(kind,body,start,end,timed):
        if kind=='electrode': identity=(targets(body.get('target')),)
        elif kind=='silence': identity=(targets(body.get('target')),)
        elif kind=='edge_scale':
            identity=(targets(body.get('pre',body.get('target'))),targets(body['post']) if body.get('post') is not None else set(range(len(neurons))))
        elif kind=='receptor_block': identity=({body.get('receptor_id')},)
        else: return
        for previous in rows:
            if (timed or previous['timed']) and kind==previous['kind'] and start<previous['end'] and previous['start']<end and all(a&b for a,b in zip(identity,previous['identity'])):
                raise ValueError('Conflicting timeline '+kind+' controls overlap on the same resolved target')
        rows.append({'kind':kind,'identity':identity,'start':start,'end':end,'timed':timed})
    for body in electrodes: append('electrode',body,body.get('start_ms',0.),body.get('end_ms',np.inf),False)
    for body in interventions: append(body.get('kind'),body,body.get('start_ms',0.),body.get('end_ms',np.inf),False)
    for block in timeline:
        if block['kind']=='electrode': append('electrode',block.get('electrode',{}),block['start_ms'],block['end_ms'],True)
        elif block['kind']=='intervention':
            body=block.get('intervention',{})
            append(body.get('kind'),body,block['start_ms'],block['end_ms'],True)


class InterventionSet:
    """Temporary effective-edge and documented receptor-row changes.

    Learned plastic weights remain separate from transmission multipliers.
    Receptor rows are blocked by their declared identity, not invented targets.
    """
    def __init__(self, engine, neurons, definitions, duration_ms):
        self.engine, self.rows = engine, []
        for i, definition in enumerate(definitions):
            d = copy.deepcopy(definition)
            kind = d.get('kind')
            if kind not in {'silence', 'edge_scale', 'receptor_block'}:
                raise ValueError('Intervention kind must be silence, edge_scale or receptor_block')
            start = _number(d.get('start_ms', 0), 'intervention.start_ms', 0, duration_ms)
            end = _number(d.get('end_ms', duration_ms), 'intervention.end_ms', start, duration_ms)
            if end <= start:
                raise ValueError('Intervention needs a nonempty interval')
            quantum = 1. if getattr(engine, 'chemistry', None) is not None else engine.dt
            if any(not np.isclose(t / quantum, round(t / quantum), atol=1e-8) for t in (start, end)):
                raise ValueError('Intervention boundaries must align with the model clock')
            row = {'definition': d, 'start': start, 'end': end, 'kind': kind}
            if kind == 'receptor_block':
                chemistry = getattr(engine, 'chemistry', None)
                if chemistry is None:
                    raise ValueError('Receptor blockade requires enabled chemical dynamics')
                indices = [j for j, (r, _) in enumerate(chemistry.effects.rows)
                           if r['id'] == d.get('receptor_id')]
                if not indices:
                    raise ValueError('No supported enabled receptor row matches receptor_id')
                row['receptors'] = np.asarray(indices, np.int32)
                row['factor'] = _number(d.get('factor', 0), 'receptor factor', 0, 1)
            else:
                target = d.get('target') if kind == 'silence' else d.get('pre', d.get('target'))
                pre = resolve_electrodes(neurons, [{'id': 'intervention-' + str(i), 'target': target}])[0].indices
                pre_mask = np.zeros(engine.n_neurons, bool); pre_mask[pre] = True
                if kind == 'silence':
                    row['sources']=pre
                    self.rows.append(row)
                    continue
                if kind == 'edge_scale' and d.get('post') is not None:
                    post = resolve_electrodes(neurons, [{'id': 'post-' + str(i), 'target': d['post']}])[0].indices
                    post_mask = np.zeros(engine.n_neurons, bool); post_mask[post] = True
                else:
                    post_mask = np.ones(engine.n_neurons, bool)
                spike_pre = np.repeat(np.arange(engine.n_neurons), np.diff(engine.csc_indptr))
                graded_post = np.repeat(np.arange(engine.n_neurons), np.diff(engine.graded_indptr))
                row['spikes'] = np.flatnonzero(pre_mask[spike_pre] & post_mask[engine.csc_indices])
                row['graded'] = np.flatnonzero(pre_mask[engine.graded_indices] & post_mask[graded_post])
                row['factor'] = 0. if kind == 'silence' else _number(d.get('factor', 1), 'edge factor', 0, 10)
            self.rows.append(row)

    def next_boundary(self, elapsed_ms, default_ms):
        future = [t for row in self.rows for t in (row['start'], row['end']) if t > elapsed_ms + 1e-8]
        active = any(row['start'] <= elapsed_ms < row['end'] for row in self.rows)
        limit = min(default_ms, min(future) - elapsed_ms) if future else default_ms
        return min(limit, 1.) if active and getattr(self.engine, 'chemistry', None) is not None else limit

    @contextmanager
    def applied(self, elapsed_ms):
        active = [row for row in self.rows if row['start'] <= elapsed_ms < row['end']]
        engine, chemistry = self.engine, getattr(self.engine, 'chemistry', None)
        saved = []
        receptor_original = None
        try:
            for row in active:
                if row['kind']=='silence':
                    indices=row['sources']
                    saved.append(('output_enabled',indices,engine.output_enabled[indices].copy()))
                    engine.output_enabled[indices]=False
                    continue
                if row['kind'] == 'receptor_block':
                    if receptor_original is None:
                        receptor_original = chemistry.effects.row_magnitude.copy()
                    chemistry.effects.row_magnitude[row['receptors']] *= row['factor']
                    continue
                for key, name in (('spikes', 'csc_counts'), ('graded', 'graded_counts')):
                    indices = row[key]
                    values = getattr(engine, name)
                    saved.append((name, indices, values[indices].copy()))
                    values[indices] *= row['factor']
            if receptor_original is not None:
                chemistry.update_effects()
            yield
        finally:
            for name, indices, values in reversed(saved):
                getattr(engine, name)[indices] = values
            if chemistry is not None:
                # A chemical tick may have learned while effective transmission
                # was masked. Retain its new weights when removing the mask.
                if hasattr(chemistry, 'plastic_csc'):
                    engine.csc_counts[chemistry.plastic_csc] = chemistry.plasticity.weights
                if receptor_original is not None:
                    chemistry.effects.row_magnitude[:] = receptor_original
                    chemistry.update_effects()


class SessionControl:
    def __init__(self, poll=None, progress=None, recovery=None):
        self.poll, self.progress = poll, progress
        self.paused = False
        self.steps_remaining = None
        self.events = []
        self.recovery=recovery
        self.recovered_from=recovery['manifest']['id'] if recovery else None

    def emit(self, event):
        self.events.append(copy.deepcopy(event))
        if self.progress:
            self.progress(event)

    def boundary(self, session):
        if self.recovery is not None:
            saved=self.recovery;manifest=saved['manifest']
            if session.phase!=manifest['phase'] or session.engine.step<manifest['step']:
                # Commands still work while rebuilding the prefix; they do not
                # mutate dynamics, and each new stop has its own exact state.
                self.recovery=None
                try: self.boundary(session)
                finally: self.recovery=saved
                return
            if session.engine.step!=manifest['step'] or session.fingerprint!=manifest['model_fingerprint']:
                raise ValueError('Reference checkpoint reconstruction differs in time or model identity')
            current=snapshot_state(session.engine)
            def equal(a,b):
                if isinstance(a,np.ndarray): return isinstance(b,np.ndarray) and a.dtype==b.dtype and np.array_equal(a,b)
                if isinstance(a,dict): return isinstance(b,dict) and a.keys()==b.keys() and all(equal(a[k],b[k]) for k in a)
                if isinstance(a,(list,tuple)): return isinstance(b,(list,tuple)) and len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
                return a==b
            if not equal(current,saved['engine']):
                raise ValueError('Reference checkpoint prefix did not reproduce its complete saved state')
            self.recovery=None
            self.emit({'kind':'checkpoint_restored','phase':session.phase,'checkpoint_id':manifest['id'],
                'step':int(session.engine.step),'model_time_ms':session.engine.step*session.engine.dt,
                'method':'Deterministic prefix reconstruction; complete state verified before continuation'})
        while True:
            incoming = self.poll() if self.poll else None
            commands = [] if incoming is None else incoming if isinstance(incoming, list) else [incoming]
            for command in commands:
                request = {'kind': 'command_result', 'request_id': command.get('request_id'),
                           'action': command.get('action'), 'phase': session.phase,
                           'step': int(session.engine.step), 'model_time_ms': session.engine.step * session.engine.dt}
                try:
                    action = command.get('action')
                    if action == 'pause':
                        self.paused, self.steps_remaining = True, None
                        if session.root is not None:
                            request['checkpoint_id']=session.checkpoint('Paused session')['id']
                    elif action == 'resume':
                        self.paused, self.steps_remaining = False, None
                    elif action == 'step':
                        duration = _number(command.get('duration_ms', 1.), 'step.duration_ms', session.quantum_ms, 100.)
                        if not np.isclose(duration / session.quantum_ms, round(duration / session.quantum_ms)):
                            raise ValueError('Step must align with the integration clock')
                        self.paused = True
                        self.steps_remaining = session.engine._steps(duration, 'duration_ms')
                    elif action in {'checkpoint', 'stop'}:
                        result = session.checkpoint(command.get('label', 'Stopped session' if action == 'stop' else ''))
                        request['checkpoint_id'] = result['id']
                        if action == 'stop':
                            if session.journal: session.journal.finish('stopped')
                            request['recording_id']=session.journal.id if session.journal else None
                            self.emit(request | {'status': 'stopped'})
                            raise ExperimentStopped(result['id'],request['recording_id'])
                    else:
                        raise ValueError('Unknown session command')
                    self.emit(request | {'status': 'paused' if self.paused else 'running'})
                except ExperimentStopped:
                    raise
                except Exception as error:
                    if command.get('action') == 'stop':
                        self.emit(request | {'status':'stopped','checkpoint_error':str(error)})
                        raise ExperimentStopped(None) from error
                    self.emit(request | {'status': 'rejected', 'error': str(error)})
            if not self.paused or self.steps_remaining:
                return
            time.sleep(.02)

    def advanced(self, amount, session=None):
        if self.steps_remaining is not None:
            self.steps_remaining -= amount
            if self.steps_remaining <= 0:
                self.steps_remaining = None
                event={'kind':'session_status','status':'paused','action':'step_complete'}
                if session is not None:
                    event.update(phase=session.phase,step=int(session.engine.step),model_time_ms=session.engine.step*session.engine.dt)
                    if session.root is not None: event['checkpoint_id']=session.checkpoint('Paused after step')['id']
                self.emit(event)


class BranchSession:
    def __init__(self, engine, options, mapping, drive_frames, frame_rate, records,
                 *, root=None, progress=None, frame=None, control=None, phase='stimulus',
                 electrodes=None, context=None, fingerprint='', interventions=None,
                 input_origin_ms=0., boundary=None, observer=None, retain_recording=True,
                 record_dtype=np.float32):
        self.engine, self.options, self.mapping = engine, options, mapping
        self.drive_frames, self.frame_rate = drive_frames, frame_rate
        self.records = np.asarray(records, np.int32)
        self.record_mask=np.zeros(engine.n_neurons,bool);self.record_mask[self.records]=True
        self.root, self.progress, self.frame, self.phase = root, progress, frame, phase
        self.control = control or SessionControl(progress=progress)
        self.electrodes = list(electrodes or [])
        self.context = copy.deepcopy(context or {})
        self.fingerprint, self.input_origin_ms = fingerprint, float(input_origin_ms)
        self.interventions, self.boundary_input = interventions, boundary
        self.observer,self.retain_recording,self.record_dtype=observer,retain_recording,np.dtype(record_dtype)
        self.start = engine.step
        self.quantum_ms = 1. if getattr(engine, 'chemistry', None) is not None or getattr(engine,'organs',None) is not None else engine.dt
        self.layout = input_layout(mapping.photoreceptor_indices, self.electrodes)
        self.total_steps = engine._steps(options['duration_ms'], 'duration_ms')
        requested = float(self.context.get('session_options', {}).get('live_chunk_ms', 10.))
        limit = min(engine._steps(requested, 'live_chunk_ms'), (128 * 1024**2) // max(8, 8 * len(self.layout[0]),self.record_dtype.itemsize*len(self.records)))
        quantum = engine._steps(self.quantum_ms, 'quantum_ms')
        self.chunk_steps = max(quantum, limit // quantum * quantum)
        self.sequence = 0
        self.timeline = self.context.get('compiled_timeline', [])
        self.executed_checkpoints = set()
        self.chemical_original = copy.deepcopy(self.context.get('chemical_original'))
        self.enzyme_original = copy.deepcopy(self.context.get('enzyme_original',{}))
        self.journal = RecordingJournal(root,phase,self.records,self.context) if root is not None and phase in {'stimulus','paired_baseline'} else None

    def checkpoint(self, label=''):
        if self.root is None:
            raise ValueError('This session has no checkpoint store')
        elapsed = (self.engine.step - self.start) * self.engine.dt
        context = self.context | {'phase': self.phase, 'options': self.options,
            'elapsed_ms': elapsed, 'remaining_ms': self.options['duration_ms'] - elapsed,
            'input_origin_ms': self.input_origin_ms + elapsed,
            'drive_frames': self.drive_frames, 'frame_rate': self.frame_rate,
            'record_indices': self.records, 'events': self.control.events,
            'chemical_original':self.chemical_original,'enzyme_original':self.enzyme_original,
            'recording_id':self.journal.id if self.journal else None,
            'electrodes': [e.definition for e in self.electrodes]}
        return save_checkpoint(self.root, self.engine, context, self.fingerprint,
                               label=label, parent_checkpoint_id=self.context.get('parent_checkpoint_id'))

    def _timeline_boundary(self, elapsed, amount_ms):
        chemistry = getattr(self.engine, 'chemistry', None)
        chemical = [b for b in self.timeline if b['kind'] == 'chemical']
        if chemical:
            if chemistry is None:
                raise ValueError('Chemical timeline requires enabled chemistry')
            if self.chemical_original is None:
                self.chemical_original = copy.deepcopy(chemistry.options)
            levels = dict(self.chemical_original.get('chemical_levels', {}))
            for block in chemical:
                if block['start_ms'] <= elapsed < block['end_ms']:
                    from .neuromod.field import FIELD_SPECIES
                    if block.get('species') not in FIELD_SPECIES:
                        raise ValueError('Unknown chemical timeline species')
                    levels[block['species']] = _number(block.get('level'), 'chemical.level', 0, 2)
            chemistry.options['chemical_levels'] = levels
            chemistry.options['chemical_control_mode'] = 'clamped' if any(b['start_ms'] <= elapsed < b['end_ms'] for b in chemical) else self.chemical_original['chemical_control_mode']
        enzyme_blocks = [b for b in self.timeline if b['kind'] == 'enzyme']
        if enzyme_blocks:
            enzymes = getattr(chemistry, 'enzymes', None)
            if enzymes is None or not callable(getattr(enzymes, 'set_activity', None)):
                raise ValueError('Enzyme timeline requires an enabled enzyme system')
            for block in enzyme_blocks:
                identifier = block.get('enzyme_id')
                if identifier not in self.enzyme_original:
                    self.enzyme_original[identifier] = enzymes.get_activity(identifier)
                value = block.get('activity') if block['start_ms'] <= elapsed < block['end_ms'] else self.enzyme_original[identifier]
                # Sequential nonoverlapping blocks on one enzyme share a single
                # original setting; only the active block controls its value.
                active = next((b for b in enzyme_blocks if b.get('enzyme_id') == identifier and b['start_ms'] <= elapsed < b['end_ms']), None)
                enzymes.set_activity(identifier, active['activity'] if active else self.enzyme_original[identifier])
        for block in self.timeline:
            checkpoint_key=(block['ordinal'],block['start_ms'],block.get('id'),block.get('label'))
            if block['kind'] == 'checkpoint' and block['start_ms'] <= elapsed + 1e-8 and checkpoint_key not in self.executed_checkpoints:
                result = self.checkpoint(block.get('label', 'Timeline checkpoint'))
                self.executed_checkpoints.add(checkpoint_key)
                self.control.emit({'kind': 'checkpoint', 'phase': self.phase, 'checkpoint_id': result['id']})
        future = [t for b in self.timeline if b['kind'] in {'chemical','enzyme','checkpoint','recording'}
                  for t in (b['start_ms'], b['end_ms']) if t > elapsed + 1e-8]
        return min(amount_ms, min(future) - elapsed) if future else amount_ms

    def run(self):
        engine = self.engine
        if self.boundary_input is not None and hasattr(self.boundary_input,'bind_components'):
            self.boundary_input.bind_components(engine)
        if self.progress:
            self.progress({'phase':self.phase,'simulated_ms':0.,'duration_ms':self.options['duration_ms'],
                           'message':f'{self.phase}: 0/{self.options["duration_ms"]:g} simulated ms',
                           'step':int(engine.step),'model_time_ms':engine.step*engine.dt})
        if self.root is not None and engine.step==0 and self.phase in {'preequilibration','reference_preequilibration'}:
            initial=self.checkpoint('Initial model state')
            self.control.emit({'kind':'checkpoint','phase':self.phase,'checkpoint_id':initial['id'],'initial':True,
                'step':0,'model_time_ms':0.})
        stride = engine.record_stride
        steps = np.arange(((self.start + stride - 1) // stride) * stride,
                          self.start + self.total_steps, stride, dtype=np.int64)
        recording = [b for b in self.timeline if b['kind'] == 'recording']
        if recording:
            local = (steps - self.start) * engine.dt
            wanted = np.zeros(len(steps), bool)
            for window in recording:
                wanted |= (local >= window['start_ms']) & (local < window['end_ms'])
            steps = steps[wanted]
            if not len(steps):
                raise ValueError('Recording windows contain no samples on the recording clock')
        shape=(len(steps),len(self.records)) if self.retain_recording else (0,len(self.records))
        if self.journal is not None and np.prod(shape)>0:
            needed=int(np.prod(shape))*self.record_dtype.itemsize
            if shutil.disk_usage(self.journal.path).free < needed*2+256*1024**2:
                raise ValueError('Insufficient free disk for recording array and recoverable chunks')
            buffer=np.lib.format.open_memmap(self.journal.path/'voltages.npy',mode='w+',dtype=self.record_dtype,shape=shape)
            self.journal.manifest.update(voltage_array='voltages.npy',voltage_shape=list(shape),written_samples=0)
            self.journal.commit()
        else:
            buffer=np.empty(shape,self.record_dtype)
        clamps = np.zeros(engine.n_neurons, np.int64)
        spikes, timings, chemical_parts, organ_parts = [], [], [], []
        cursor, elapsed_wall, final = 0, 0., None
        wall_started=time.perf_counter()
        while engine.step < self.start + self.total_steps:
            self.control.boundary(self)
            offset = engine.step - self.start
            amount = min(self.chunk_steps, self.total_steps - offset)
            if getattr(engine, 'organs', None) is not None:
                amount = min(amount, engine._steps(1., 'organ tick'))
            if self.control.steps_remaining is not None:
                amount = min(amount, self.control.steps_remaining)
            elapsed = offset * engine.dt
            amount_ms = self._timeline_boundary(elapsed, amount * engine.dt)
            if self.interventions:
                amount_ms = self.interventions.next_boundary(elapsed, amount_ms)
            amount = engine._steps(amount_ms, 'advance duration')
            local_ms = self.input_origin_ms + (offset + np.arange(amount)) * engine.dt
            frames = np.floor(local_ms * self.frame_rate / 1000. + 1e-10).astype(int)
            if len(frames) and frames[-1] >= len(self.drive_frames):
                raise ValueError('Optical input recording does not cover the requested continuation')
            photo = self.drive_frames[frames[:, None], self.mapping.photoreceptor_columns[None, :]]
            record_now = not recording or any(b['start_ms'] <= elapsed < b['end_ms'] for b in recording)
            kwargs = {'record_indices': self.records if record_now else np.empty(0, np.int32), 'chunk_ms': amount_ms}
            if self.record_dtype==np.dtype('float64'):
                kwargs['record_dtype']=np.float64
            if self.electrodes:
                kwargs.update(membrane_input_indices=self.layout[0],
                              membrane_input_drive=combined_drive(local_ms, photo, self.layout, self.electrodes))
            else:
                kwargs.update(photoreceptor_indices=self.mapping.photoreceptor_indices, photoreceptor_drive=photo)
            if getattr(engine, 'organs', None) is not None:
                indices, values = engine.organs.membrane_drive()
                if len(indices):
                    original_indices = kwargs.pop('membrane_input_indices', kwargs.pop('photoreceptor_indices', None))
                    original_drive = kwargs.pop('membrane_input_drive', kwargs.pop('photoreceptor_drive', None))
                    combined_indices = np.union1d(original_indices, indices).astype(np.int32)
                    drive = np.zeros((amount, len(combined_indices)), np.float64)
                    drive[:, np.searchsorted(combined_indices, original_indices)] += original_drive
                    drive[:, np.searchsorted(combined_indices, indices)] += values
                    kwargs.update(membrane_input_indices=combined_indices, membrane_input_drive=drive)
            if self.boundary_input is not None:
                kwargs.update(self.boundary_input.slice(engine.step, amount))
            organ_sample=engine.organs.state.copy() if getattr(engine,'organs',None) is not None else None
            with self.interventions.applied(elapsed) if self.interventions else _no_interventions():
                owner=getattr(self.observer,'__self__',None)
                if callable(getattr(owner,'prepare_chunk',None)): owner.prepare_chunk()
                part = engine.run(amount_ms, **kwargs)
                if self.observer:
                    if getattr(engine,'organs',None) is None: self.observer(part)
                source_enabled=engine.output_enabled.copy() if getattr(engine,'organs',None) is not None else None
                if getattr(engine, 'organs', None) is not None:
                    target = np.bincount(part['spike_indices'], minlength=engine.n_neurons) * 1000. / amount_ms
                    graded = engine.graded_mask
                    target[graded] = np.maximum(0., engine.v[graded] - engine.parameters['graded_release']) * 5.
                    target *= source_enabled
                    rates = engine.organs.rates_hz + -np.expm1(-amount_ms / 20.) * (target - engine.organs.rates_hz)
                    engine.organs.advance(rates, amount_ms)
                    if self.observer: self.observer(part)
            if self.context.get('recording_selection'):
                keep=self.record_mask[part['spike_indices']]
                part=dict(part,spike_indices=part['spike_indices'][keep],spike_times=part['spike_times'][keep])
            count = len(part['voltage_times']) if record_now else 0
            if record_now:
                if self.retain_recording:buffer[cursor:cursor + count] = part['voltages']
                cursor += count
                if count and organ_sample is not None and self.retain_recording:
                    organ_parts.append(np.repeat(organ_sample[None,:,:],count,axis=0))
            if record_now:
                spikes.append(part['spike_indices']); timings.append(part['spike_times'])
            if 'chemistry' in part and record_now and self.retain_recording:
                chemical_parts.append(part['chemistry'])
            clamps += part['per_neuron_clamp_counts']; elapsed_wall += part['wall_seconds']
            final = part
            if self.journal:
                if isinstance(buffer,np.memmap) and count: buffer.flush()
                self.journal.manifest['written_samples']=cursor
                self.journal.append(part,self.start,engine.dt,record_now,
                    engine.organs.readout() if getattr(engine,'organs',None) is not None else None)
            self.control.advanced(amount,self)
            self.sequence += 1
            if self.frame:
                indices = self.records if len(self.records) else np.arange(engine.n_neurons, dtype=np.int32)
                event = {'schema_version': 1, 'phase': self.phase, 'sequence': self.sequence,
                         'step': int(engine.step), 'dt_ms': float(engine.dt),
                         'model_time_ms': float(engine.step * engine.dt), 'elapsed_ms': float((engine.step - self.start) * engine.dt),
                         'indices': indices.copy(), 'voltage_mv': engine.v[indices].astype(np.float32, copy=True),
                         'spike_indices': part['spike_indices'].copy(), 'spike_times_ms': part['spike_times'].copy(),
                         'baseline_available': self.phase == 'paired_baseline', 'signal': 'baseline' if self.phase == 'paired_baseline' else 'raw',
                         'clamp_count': int(clamps.sum()), 'real_time_factor': amount_ms / 1000. / max(part['wall_seconds'], 1e-12)}
                event.update(model_hash=self.context.get('model_hash'),elapsed_wall_seconds=time.perf_counter()-wall_started,
                    units={'voltage_mv':'mV','model_time_ms':'ms','spike_times_ms':'ms','concentrations_au':'a.u.'})
                selection=self.context.get('selection')
                event['model_id']=self.context.get('model_id','flywire-783')
                if selection is not None:
                    event['parent_indices']=np.asarray(selection['parent_indices'],np.int32)[indices]
                    event['boundary_policy']=selection['boundary']
                if getattr(engine, 'chemistry', None) is not None:
                    event['concentrations_au'] = engine.chemistry.field.C.copy()
                    event['chemistry_diagnostics'] = engine.chemistry.diagnostics()
                if getattr(engine, 'organs', None) is not None:
                    event['organs'] = engine.organs.readout()
                self.frame(event)
            if self.progress:
                self.progress({'phase': self.phase, 'simulated_ms': float((engine.step - self.start) * engine.dt),
                    'duration_ms': self.options['duration_ms'], 'message': f'{self.phase}: {(engine.step-self.start)*engine.dt:g}/{self.options["duration_ms"]:g} simulated ms',
                    'step': int(engine.step), 'model_time_ms': engine.step * engine.dt})
            check_memory()
        if final is None or cursor != len(steps):
            raise RuntimeError('Branch recording did not complete')
        if self.control.recovery and self.control.recovery['manifest']['phase']==self.phase:
            self.control.boundary(self)
        self._timeline_boundary(self.options['duration_ms'], 0.)
        if self.chemical_original is not None:
            engine.chemistry.options.clear(); engine.chemistry.options.update(self.chemical_original)
        for identifier, original in self.enzyme_original.items():
            engine.chemistry.enzymes.set_activity(identifier, original)
        result = dict(final, voltages=buffer, voltage_times=(steps * engine.dt - self.start * engine.dt).astype(np.float32) if self.retain_recording else np.empty(0,np.float32),
                      spike_indices=np.concatenate(spikes), spike_times=np.concatenate(timings) - self.start * engine.dt,
                      per_neuron_clamp_counts=clamps, clamp_count=int(clamps.sum()), wall_seconds=elapsed_wall,
                      simulated_ms=self.options['duration_ms'])
        if chemical_parts:
            result['chemistry'] = {key: np.concatenate([part[key] for part in chemical_parts]) for key in chemical_parts[0]}
        if organ_parts:
            result['organs']={'time_ms':result['voltage_times'].copy(),'state_values':np.concatenate(organ_parts)}
        if self.journal:
            self.journal.finish('complete')
            result['recording_id']=self.journal.id
        return result


@contextmanager
def _no_interventions():
    yield
