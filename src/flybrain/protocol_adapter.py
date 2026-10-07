"""Import safe JSON/YAML without silently changing a protocol's dynamics.

Native timelines use membrane mV and global chemical clamps. Legacy protocols
use stateful odour transduction, Poisson source drive, and frozen learning tests;
their executable document is retained for the original CoreRuntime instead.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import yaml

from .experiment_session import compile_timeline
from .stimulation import normalize_electrodes, resolve_electrodes

MAX_BYTES = 256 * 1024
NATIVE_KINDS = {'rest', 'visual', 'electrode', 'chemical', 'enzyme', 'intervention', 'checkpoint', 'recording'}


class _ProtocolLoader(yaml.SafeLoader):
    """Reject duplicate keys and aliases instead of guessing their intention."""
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError('Protocol aliases are unsupported; write blocks explicitly')
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError('Protocol keys must be unique strings')
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def parse_protocol(document):
    """Bounded, JSON-compatible documents only; no code tags or aliases."""
    if isinstance(document, str):
        if len(document.encode('utf-8')) > MAX_BYTES:
            raise ValueError('Protocol exceeds 256 KiB')
        try:
            value = yaml.load(document, Loader=_ProtocolLoader)
        except (yaml.YAMLError, RecursionError) as error:
            raise ValueError('Invalid protocol JSON/YAML: ' + str(error)) from error
    else:
        value = document
    def visit(item, depth=0):
        if depth > 20:
            raise ValueError('Protocol nesting exceeds 20 levels')
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise ValueError('Protocol keys must be strings')
            return {key: visit(val, depth + 1) for key, val in item.items()}
        if isinstance(item, list):
            return [visit(val, depth + 1) for val in item]
        if item is None or isinstance(item, (str, bool, int)):
            return item
        if isinstance(item, float) and np.isfinite(item):
            return item
        raise ValueError('Protocol values must be finite JSON values')
    value = visit(value)
    if len(json.dumps(value).encode()) > MAX_BYTES:
        raise ValueError('Protocol exceeds 256 KiB')
    if not isinstance(value, dict) or not isinstance(value.get('blocks'), list):
        raise ValueError('Protocol requires an object with a blocks list')
    if len(value['blocks']) > 512 or not all(isinstance(b, dict) for b in value['blocks']):
        raise ValueError('Protocol requires at most 512 object blocks')
    return value


def _number(value, label, low=0, high=np.inf):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label} must be finite in [{low}, {high}]')
    return float(value)


def _target(neurons, target, audit, block_index, role):
    if neurons is None:
        raise ValueError('Neuron source annotations are required to resolve protocol targets')
    if not isinstance(target, dict):
        raise ValueError('Protocol target must be an explicit target object')
    selected = resolve_electrodes(neurons, [{'id': f'protocol-{block_index}-{role}', 'target': target}])[0]
    indices = selected.indices.tolist()
    audit.append({'block_index': block_index, 'role': role, 'indices': indices,
                  'root_ids': [str(x) for x in neurons.iloc[indices].root_id],
                  'requested_target': copy.deepcopy(target), 'assumption': selected.definition.get('assumption')})
    return {'kind': 'indices', 'indices': indices}


def import_protocol(document, *, neurons=None, duration_ms=None, dt_ms=.1,
                    model_id='flywire-783', root=None, pairing_interval_ms=None,
                    compartment_map=None, odour_library=None):
    """Return reviewable native timeline or a preserved legacy-engine document.

    ``compatible`` describes native timeline compatibility. For legacy imports,
    ``legacy_execution.source_ready`` describes annotation/DoOR resolution only;
    CoreRuntime must still perform its full integrity gates before execution.
    Injectable mapping/library arguments are for verified caller data and tests,
    never inferred conversions supplied by a protocol document.
    """
    original = parse_protocol(document)
    result = {'format': None, 'compatible': False, 'timeline': None,
              'original_document': original, 'original_text': document if isinstance(document, str) else None,
              'errors': [], 'warnings': [], 'source_audit': [], 'legacy_execution': None,
              'model_id': model_id}
    native = original.get('schema_version') is not None or any(b.get('kind') in NATIVE_KINDS - {'rest'} for b in original['blocks'])
    if not native:
        return _legacy(original, result, neurons, root, model_id, pairing_interval_ms, compartment_map, odour_library)
    result['format'] = 'timeline-v1'
    timeline = copy.deepcopy(original)
    blocks = timeline['blocks']
    dt_ms = _number(dt_ms, 'dt_ms', 1e-9)
    # Normalize aliases once so browser rows and backend use the same boundaries.
    for i, block in enumerate(blocks):
        for old, new in (('t_ms', 'start_ms'), ('dur_ms', 'duration_ms')):
            if old in block:
                if new in block and block[new] != block[old]:
                    raise ValueError('Conflicting timeline time aliases')
                block[new] = block.pop(old)
        block.setdefault('start_ms', 0)
        block.setdefault('duration_ms', 0)
        _number(block['start_ms'], 'start_ms'); _number(block['duration_ms'], 'duration_ms')
        common = {'id', 'kind', 'start_ms', 'duration_ms', 'label'}
        extra = {'visual': {'options'}, 'electrode': {'electrode'}, 'chemical': {'species', 'level'},
                 'enzyme': {'enzyme_id', 'activity'}, 'intervention': {'intervention'}}.get(block.get('kind'), set())
        if set(block) - common - extra:
            raise ValueError(f'Unsupported fields in timeline block {i + 1}')
        if block.get('kind') == 'electrode':
            electrode = block.get('electrode')
            if not isinstance(electrode, dict):
                raise ValueError('Electrode block requires an electrode object')
            electrode['target'] = _target(neurons, electrode.get('target'), result['source_audit'], i, 'electrode')
        elif block.get('kind') == 'intervention':
            effect = block.get('intervention')
            if not isinstance(effect, dict) or effect.get('kind') not in {'silence', 'edge_scale', 'receptor_block'}:
                raise ValueError('Invalid intervention block')
            kind = effect['kind']
            allowed = {'kind', 'target'} if kind == 'silence' else {'kind', 'pre', 'post', 'target', 'factor'} if kind == 'edge_scale' else {'kind', 'receptor_id', 'factor'}
            if set(effect) - allowed:
                raise ValueError('Unsupported intervention fields')
            if kind == 'silence':
                effect['target'] = _target(neurons, effect.get('target'), result['source_audit'], i, 'silence')
            elif kind == 'edge_scale':
                effect['pre'] = _target(neurons, effect.pop('target', effect.get('pre')), result['source_audit'], i, 'pre')
                if effect.get('post') is not None:
                    effect['post'] = _target(neurons, effect['post'], result['source_audit'], i, 'post')
                _number(effect.get('factor', 1), 'edge factor', 0, 10)
            else:
                if not isinstance(effect.get('receptor_id'), str) or not effect['receptor_id']:
                    raise ValueError('Receptor block requires a receptor row ID')
                _number(effect.get('factor', 0), 'receptor factor', 0, 1)
                result['warnings'].append('Receptor row identity will be checked against enabled chemistry at launch.')
        elif block.get('kind') == 'chemical':
            from .neuromod.field import FIELD_SPECIES
            if block.get('species') not in FIELD_SPECIES:
                raise ValueError('Unknown chemical species')
            _number(block.get('level'), 'chemical level', 0, 2)
            result['warnings'].append('Chemical events require enabled chemistry and clamp global model fields in a.u.')
        elif block.get('kind') == 'enzyme':
            from .enzymes import ENZYME_IDS
            if block.get('enzyme_id') not in ENZYME_IDS:
                raise ValueError('Unknown enzyme')
            _number(block.get('activity'), 'enzyme activity', 0, 10)
            result['warnings'].append('Enzyme events require the enabled enzyme system.')
    end = max((b['start_ms'] + b['duration_ms'] for b in blocks), default=dt_ms)
    repeat = timeline.get('repeat', 1)
    count = repeat.get('count', 1) if isinstance(repeat, dict) else repeat
    interval = repeat.get('interval_ms', end) if isinstance(repeat, dict) else end
    required = end + (_number(count, 'repeat count', 1, 100) - 1) * _number(interval, 'repeat interval')
    duration = _number(required if duration_ms is None else duration_ms, 'duration_ms', dt_ms)
    compiled = compile_timeline(timeline, duration, dt_ms)
    for block in compiled:
        if block['kind'] == 'electrode':
            normalize_electrodes([dict(block['electrode'], start_ms=block['start_ms'], end_ms=block['end_ms'])], duration, dt_ms)
    result.update(compatible=True, timeline=timeline, duration_ms=duration,
                  compiled_events=compiled, warnings=list(dict.fromkeys(result['warnings'])))
    return result


def _legacy(original, result, neurons, root, model_id, pairing, compartments, library):
    from .rt.protocol import compile_protocol
    from .neuromod.sources import source_masks
    result['format'] = 'neuromod-protocol'
    if set(original) - {'name', 'seed', 'notes', 'blocks', 'sweeps'}:
        raise ValueError('Unknown legacy protocol fields')
    for block in original['blocks']:
        extra = {'rest': set(), 'iti': set(), 'odour': {'id', 'intensity'},
                 'dan_pulse': {'source', 'compartment', 'drive'},
                 'test': {'odours', 'iti_ms', 'intensity', 'readout'}, 'control': {'control_id', 'value'}}.get(block.get('kind'), set())
        if set(block) - {'kind', 't_ms', 'dur_ms'} - extra:
            raise ValueError('Unknown fields in legacy protocol block')
    if original.get('sweeps'):
        result['warnings'].append('Sweep values are preserved; this import represents the nominal protocol or the explicitly selected pairing interval, not an automatic sweep.')
    compiled = compile_protocol(original, pairing_interval_ms=pairing)
    ready = model_id == 'flywire-783' and neurons is not None
    if not ready:
        result['warnings'].append('Legacy protocols require verified FlyWire neuromodulatory-core annotations.')
    needs_odor = any(b['kind'] in {'odour', 'test'} for b in original['blocks'])
    if root is not None and ready:
        if compartments is None:
            try:
                from .neuromod.compartments import load_compartments
                compartments = load_compartments(Path(root))
            except (OSError, ValueError, KeyError) as error:
                ready = False; result['warnings'].append('Compartment audit unavailable: ' + str(error))
        if needs_odor and library is None:
            try:
                from .neuromod.odour import OdourLibrary
                library = OdourLibrary.from_root(Path(root), download=False)
            except (OSError, ValueError, KeyError) as error:
                ready = False; result['warnings'].append('Pinned DoOR audit unavailable: ' + str(error))
    roots = {str(value): i for i, value in enumerate(neurons.root_id)} if neurons is not None else {}
    for i, block in enumerate(compiled['document']['blocks']):
        kind = block['kind']
        reason = {'odour': 'Stateful DoOR/ORN Poisson input cannot be represented as additive membrane mV.',
                  'dan_pulse': 'Named positive-known-DA Poisson source drive cannot be replaced by a global DA clamp.',
                  'test': 'Odour tests freeze and restore prior plasticity, including ITIs; native recording windows do not.',
                  'rest': 'Legacy rest preserves sensory and plasticity state; native rest changes visual contrast.',
                  'iti': 'Legacy ITI preserves runtime state; native rest changes visual contrast.',
                  'control': 'Legacy runtime controls retain their original engine semantics.'}[kind]
        result['errors'].append({'code': 'requires_original_engine', 'block_index': i, 'message': reason})
        if kind == 'dan_pulse':
            row = {'block_index': i, 'role': 'DAN', 'source': block['source'], 'requested_compartment': block.get('compartment')}
            try:
                if neurons is None:
                    raise ValueError('Neuron annotations unavailable')
                mask = source_masks(neurons)['DA'] & neurons.cell_type.fillna('').eq(block['source']).to_numpy()
                indices = np.flatnonzero(mask)
                if not len(indices):
                    raise ValueError('Named source has no positive-known-DA neurons; predicted transmitter labels are not substituted')
                row.update(indices=indices.tolist(), root_ids=[str(x) for x in neurons.iloc[indices].root_id])
                if compartments is None:
                    raise ValueError('Verified compartment map unavailable')
                lookup = {str(value): index for index, value in enumerate(compartments.model_root_ids)}
                assignment = [int(compartments.mb_assignment[lookup[str(value)]]) for value in neurons.iloc[indices].root_id]
                actual = sorted({compartments.names[j] for j in assignment if j >= 0})
                row['observed_compartments'] = actual
                if block.get('compartment') and actual != [block['compartment']]:
                    result['warnings'].append(f"{block['source']}: requested nominal {block['compartment']}; observed empirical {actual}. Source identities are preserved.")
            except (ValueError, KeyError, AttributeError) as error:
                ready = False; row['error'] = str(error)
            result['source_audit'].append(row)
        if kind in {'odour', 'test'}:
            for name in [block['id']] if kind == 'odour' else block['odours']:
                row = {'block_index': i, 'role': 'odour', 'odour': name}
                try:
                    if library is None or library.mode != 'door':
                        raise ValueError('Pinned DoOR library required; synthetic input is not substituted')
                    response = library.responses(name)
                    missing = [str(x) for x in library.root_ids if str(x) not in roots]
                    if missing:
                        raise ValueError('Protocol selection omits DoOR ORN source neurons')
                    row.update(indices=[roots[str(x)] for x in library.root_ids], root_ids=[str(x) for x in library.root_ids],
                               response_units='a.u. consensus; transduction computes Hz in original runtime',
                               provenance=response.metadata)
                except (ValueError, KeyError, AttributeError) as error:
                    ready = False; row['error'] = str(error)
                result['source_audit'].append(row)
    result.update(duration_ms=compiled['duration_ms'], compiled_events=compiled['events'],
                  legacy_execution={'engine': 'neuromod-core', 'document': compiled['document'],
                                    'events': compiled['events'], 'seed': compiled['seed'],
                                    'duration_ms': compiled['duration_ms'], 'source_ready': bool(ready),
                                    'requires_runtime_validation': True})
    return result
