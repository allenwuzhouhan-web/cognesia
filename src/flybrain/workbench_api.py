"""Local workbench analysis and source-backed inspection services.

These helpers never advance simulation time. Execution belongs to VisualState's
single supervised session queue.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np
from scipy.fft import rfft, irfft


def json_safe(value):
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def interval_analysis(payload):
    """FFT of exactly the selected original samples, with a relative time origin."""
    if not isinstance(payload, dict):
        raise ValueError('Expected an interval analysis object')
    times = np.asarray(payload.get('time_ms', []), dtype=np.float64)
    values = np.asarray(payload.get('values', []), dtype=np.float64)
    if times.ndim != 1 or values.shape != times.shape or not 2 <= len(times) <= 1_000_000:
        raise ValueError('Provide 2 to 1,000,000 matching time/value samples')
    if not np.isfinite(times).all() or not np.isfinite(values).all() or np.any(np.diff(times) <= 0):
        raise ValueError('Samples must be finite and times strictly increasing')
    start = float(payload.get('start_ms', times[0]))
    end = float(payload.get('end_ms', times[-1]))
    if not math.isfinite(start) or not math.isfinite(end):
        raise ValueError('Interval endpoints must be finite')
    start, end = sorted((start, end))
    first = int(np.searchsorted(times, start, side='left'))
    last = int(np.searchsorted(times, end, side='right'))
    times, values = times[first:last], values[first:last]
    n = len(times)
    if n < 2:
        raise ValueError('The selected interval needs at least two recorded samples')
    dt = (times[-1] - times[0]) / (n - 1)
    tolerance = max(dt * 1e-6, 8 * np.finfo(float).eps * max(1, abs(times[0]), abs(times[-1])))
    if np.any(np.abs(np.diff(times) - dt) > tolerance):
        raise ValueError('Fourier fitting requires uniform recorded sampling; no resampling is performed')
    count = payload.get('harmonics', 8)
    if isinstance(count, bool) or not isinstance(count, (int, float)) or not math.isfinite(count) or int(count) != count or count < 0:
        raise ValueError('Harmonics must be a nonnegative integer')
    count = min(int(count), n // 2)
    original = rfft(values) / n
    kept = original.copy()
    kept[count + 1:] = 0
    reconstruction = irfft(kept * n, n=n)
    residual = values - reconstruction
    error = float(residual @ residual)
    total = float(np.sum((values - values.mean()) ** 2))
    frequencies = np.arange(len(original)) * 1000 / (n * dt)
    coefficients = []
    for k in range(1, count + 1):
        factor = 1 if n % 2 == 0 and k == n // 2 else 2
        coefficients.append({'k': k, 'frequency_hz': float(frequencies[k]),
                             'cos': float(factor * original[k].real),
                             'sin': float(-factor * original[k].imag)})
    window = payload.get('window', 'none')
    demean = payload.get('demean', False)
    if window not in ('none', 'hann') or not isinstance(demean, bool):
        raise ValueError('Spectrum window must be none or hann; demean must be boolean')
    spectrum_values = values - values.mean() if demean else values.copy()
    gain = 1.
    if window == 'hann':
        spectrum_values *= .5 - .5 * np.cos(2 * np.pi * np.arange(n) / n)
        gain = .5
    spectrum = rfft(spectrum_values) / (n * gain)
    spectrum[0] = spectrum[0].real
    if n % 2 == 0:
        spectrum[-1] = spectrum[-1].real
    factors = np.full(len(spectrum), 2.)
    factors[0] = 1
    if n % 2 == 0:
        factors[-1] = 1
    dc = float(original[0].real)
    equation = (f'y(t) ≈ {dc:.10g} + Σ[k=1..{count}] '
                f'[aₖ cos(2π fₖ (t − {times[0]:.10g})/1000) + '
                f'bₖ sin(2π fₖ (t − {times[0]:.10g})/1000)]')
    return json_safe({'schema_version': 1, 'time_ms': times, 'values': values,
                     'reconstruction': reconstruction, 'residuals': residual,
                     'coefficients': coefficients, 'dc': dc,
                     'time_origin_ms': times[0], 'period_ms': n * dt,
                     'sample_interval_ms': dt, 'sample_count': n,
                     'sample_rate_hz': 1000 / dt, 'nyquist_hz': 500 / dt,
                     'resolution_hz': 1000 / (n * dt), 'harmonics': count,
                     'frequencies_hz': frequencies, 'amplitudes': factors * np.abs(spectrum),
                     'phases': np.angle(spectrum), 'window': window, 'demean': demean,
                     'rmse': math.sqrt(error / n), 'r_squared': 1 - error / total if total > 0 else None,
                     'equation': equation, 'units': str(payload.get('unit', '')),
                     'range': {'start_ms': times[0], 'end_ms': times[-1],
                               'first_sample': first, 'last_sample': last - 1},
                     'source': payload.get('source', {}),
                     'interpretation': 'Approximation of recorded samples, not an inferred governing biological equation.'})


def checkpoint_catalog(root):
    result = []
    for path in sorted((Path(root) / 'checkpoints').glob('*/manifest.json'), reverse=True):
        try:
            item = json.loads(path.read_text())
            result.append({k: item.get(k) for k in ('id', 'created_at', 'label', 'model_fingerprint',
                                                  'step', 'dt_ms', 'phase', 'model_time_ms', 'parent_checkpoint_id')})
        except (OSError, ValueError):
            continue
    return result


def inspection_neurons(state, model_id='flywire-783', run_id=None):
    """Resolve the displayed row order before interpreting a picked index."""
    import pandas as pd
    if run_id:
        if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
            raise ValueError('Invalid recording identity')
        directory = Path(state.root) / 'runs' / run_id
        summary = json.loads((directory / 'visual_summary.json').read_text())
        if summary.get('model_id', 'flywire-783') != model_id:
            raise ValueError('Recording belongs to a different model')
        table = directory / 'recorded_neurons.parquet'
        if table.exists():
            return pd.read_parquet(table)
    if model_id == 'flywire-783':
        return state.neuron_table()
    from .model_registry import get_model_manifest
    get_model_manifest(state.root, model_id)
    return pd.read_parquet(Path(state.root) / 'build/models' / model_id / 'neurons.parquet')


def model_eye_map(state, model_id='flywire-783'):
    """Inspect the selected model's default optics without starting or saving a run."""
    import pandas as pd
    from .config import parameters
    from .eye import EyeMapping, build_eye_mapping, column_directions
    from .model_eye import build_model_eye_mapping
    from .model_registry import get_model_manifest
    from .visual_experiment import read_visual_parameters

    root = Path(state.root)
    manifest = get_model_manifest(root, model_id)
    neurons = inspection_neurons(state, model_id).reset_index(drop=True)
    spacing = parameters(root)['eye_spacing']
    center = read_visual_parameters(root)['eye_center_azimuth_deg']
    if manifest.get('optical_mapping_supported', True):
        directory = root / 'build/visual'
        paths = [directory / name for name in ('eye_columns.csv', 'eye_assignments.parquet', 'eye_audit.json')]
        mapping = None
        if all(path.exists() for path in paths):
            columns = pd.read_csv(paths[0], dtype={'anchor_root_id': str})
            assignments = pd.read_parquet(paths[1])
            # Cached assignment indices are meaningful only in this exact source row order.
            required = {'root_id', 'cell_type', 'side', 'neuron_index', 'column_index'}
            compatible = required <= set(assignments) and len(assignments) == len(neurons)
            if compatible:
                compatible = (np.array_equal(assignments.neuron_index.to_numpy(), np.arange(len(neurons)))
                    and np.array_equal(assignments.root_id.astype(str).to_numpy(), neurons.root_id.astype(str).to_numpy())
                    and np.array_equal(assignments.cell_type.fillna('').to_numpy(), neurons.cell_type.fillna('').to_numpy())
                    and np.array_equal(assignments.side.fillna('').to_numpy(), neurons.side.fillna('').to_numpy()))
            if compatible:
                columns = column_directions(columns, spacing, center)
                known = assignments.column_index.to_numpy(dtype=np.int32)
                mapped = np.flatnonzero(assignments.cell_type.isin(['R1-6', 'R7', 'R8']).to_numpy() & (known >= 0))
                if not np.isin(known[mapped], columns.column_index).all():
                    raise ValueError('Cached photoreceptor assignment refers to an absent column')
                audit = json.loads(paths[2].read_text())
                audit['retinotopy_assumptions'] = [f'{spacing:g} degree center spacing mapped to a sphere via a tangent exponential map',
                    'each eye centered on its mean axial coordinate', 'left eye horizontal reflection',
                    f'eye centers at +/-{center:g} degrees azimuth; center elevation zero']
                mapping = EyeMapping(columns, assignments, mapped, known[mapped], audit)
        if mapping is None:
            mapping = build_eye_mapping(root, neurons=neurons, spacing_deg=spacing, eye_center_deg=center, persist=False)
    else:
        mapping = build_model_eye_mapping(root, {'neurons': neurons, 'manifest': manifest},
            spacing_deg=spacing, eye_center_deg=center)

    columns = mapping.columns.copy()
    if 'anchor_root_id' in columns:
        columns['anchor_root_id'] = columns.anchor_root_id.map(lambda value: None if pd.isna(value) else str(value))
    assigned = mapping.assignments.iloc[np.asarray(mapping.photoreceptor_indices, dtype=int)].copy()
    assigned['index'] = assigned.neuron_index.astype(int)
    assigned['root_id'] = assigned.root_id.astype(str)
    if 'entity_id' in neurons:
        assigned['entity_id'] = neurons.iloc[assigned['index'].to_numpy()].entity_id.astype(str).to_numpy()
    return json_safe({'model_id': model_id, 'model_hash': manifest['model_hash'],
        'columns': columns.to_dict('records'), 'receptors': assigned.to_dict('records'), 'audit': mapping.audit})


def inspect_neuron(state, index, model_id='flywire-783', run_id=None):
    import pandas as pd
    neurons = inspection_neurons(state, model_id, run_id)
    if not 0 <= index < len(neurons):
        raise ValueError('Neuron index is outside the displayed recording or model')
    row = neurons.iloc[index]
    result = {'index': index, 'model_id': model_id, 'root_id': str(int(row.root_id))}
    for name in ('entity_id', 'cell_type', 'super_class', 'side', 'top_nt', 'mode', 'root_region', 'neuromere'):
        value = row.get(name)
        result[name] = None if value is None or pd.isna(value) else str(value)
    p = row[['pos_x', 'pos_y', 'pos_z']].to_numpy(float)
    result['position_um'] = (p * [.004, .004, .04]).tolist() if np.isfinite(p).all() else None
    return result


def preview_experiment(state, payload):
    """Resolve targets and budget supporting state without constructing an engine."""
    from .config import parameters
    from .model_registry import load_model_network
    from .selection import compile_selection
    from .stimulation import resolve_electrodes
    model_id = payload.get('model_id', 'flywire-783')
    network = load_model_network(state.root, model_id)
    compiled = compile_selection(network, payload.get('selection', {'mode': 'full'}))
    selection = compiled['selection']
    p = parameters(state.root) | payload.get('options', {}).get('neural_overrides', {})
    options = payload.get('options', {})
    duration = float(options.get('duration_ms', 300))
    record_dt = float(options.get('record_dt_ms', 20))
    dt = float(p['dt'])
    if not np.isfinite([duration, record_dt, dt]).all() or min(duration, record_dt, dt) <= 0:
        raise ValueError('Duration and clocks must be positive finite numbers')
    n = selection['simulated_neurons']; parent_n = selection['parent_neurons']
    edges = sum(compiled[k].nnz for k in ('graded', 'spiking'))
    delay = int(round(p['synaptic_delay']/dt))+1
    neural_state = n * (128 + delay*12)
    network_bytes = edges*24 + (n+1)*16
    checkpoint = neural_state + network_bytes
    recording = int(np.ceil(duration/record_dt))*n*12
    boundary = int(np.ceil(duration/dt))*n*16*2 if selection['reference_required'] else 0
    # Chemistry keeps the full compartment graph and source denominators.
    compartments = max(1, len(network['neurons'].get('root_region', np.zeros(96)).unique())) if 'root_region' in network['neurons'] else 96
    chemical_bytes = compartments*8*8*32 if options.get('neuromod', {}).get('enabled') else 0
    entries = []
    for ordinal, entry in enumerate(payload.get('targets', [])):
        resolved = resolve_electrodes(compiled['neurons'], [{'id': str(ordinal), 'target': entry}])[0]
        rows = compiled['neurons'].iloc[resolved.indices]
        identities = rows['entity_id'].astype(str).tolist() if 'entity_id' in rows else [f'flywire:783:{value}' for value in rows.root_id]
        entries.append({'target': entry, 'count': len(rows), 'entity_ids': identities,
                        'assumption': resolved.definition.get('assumption')})
    return {'selection': selection, 'simulated_connections': edges, 'targets': entries,
            'sequence': ['Prepare compatible full reference', 'Run selected circuit'] if selection['reference_required'] and not selection.get('reference_id') else ['Run simulation'],
            'memory_estimate': {'network_bytes': network_bytes, 'neural_state_bytes': neural_state,
                'checkpoint_copy_bytes': checkpoint, 'boundary_recording_bytes': boundary,
                'voltage_recording_bytes': recording, 'chemical_state_bytes': chemical_bytes,
                'total_working_bytes': network_bytes+neural_state+checkpoint+boundary+recording+chemical_bytes,
                'reference_neurons': parent_n if selection['reference_required'] else 0,
                'note': 'Conservative arrays estimate including a checkpoint copy and paired boundary buffers; source preparation, optical inputs, Python objects and compression require additional space. Boundary data and voltage journals are disk-backed.'}}


def connectivity(state, payload):
    """Directed edges from the selected source graph, never visual proximity."""
    if not isinstance(payload, dict):
        raise ValueError('Expected connectivity selections')
    model_id = payload.get('model_id', 'flywire-783')
    recorded_table=inspection_neurons(state,model_id,payload['run_id']) if payload.get('run_id') else None
    recorded_hash=payload.get('model_hash')
    if recorded_table is not None:
        saved_hash=json.loads((Path(state.root)/'runs'/payload['run_id']/'visual_summary.json').read_text()).get('model_hash')
        if recorded_hash is not None and saved_hash is not None and recorded_hash != saved_hash:
            raise ValueError('Requested model version differs from the recording')
        recorded_hash=saved_hash or recorded_hash
    if model_id == 'flywire-783':
        if recorded_hash is not None:
            from .model_registry import get_model_manifest
            # Historical graph aliases must not reinterpret a saved recording
            # after the released source artifacts have changed.
            get_model_manifest(state.root,model_id,model_hash=recorded_hash)
        from .build import load_network
        if state.wiring is None:
            state.wiring = load_network(state.root)
        network = state.wiring
        neurons = state.neuron_table()
    else:
        from .model_registry import load_model_network
        network = load_model_network(state.root, model_id, model_hash=recorded_hash)
        neurons = network['neurons']
    # Matrix naming follows the existing engine's target-row/source-column CSR.
    matrices = [(key, value) for key, value in network.items()
                if key in ('graded', 'spiking')
                and hasattr(value, 'tocsr')]
    if not matrices:
        matrices = [(key, value) for key, value in network.items() if hasattr(value, 'tocsr')]
    if not matrices:
        raise ValueError('The selected model has no loaded connectivity matrices')
    displayed = recorded_table if recorded_table is not None else neurons
    n = len(displayed)
    # Recordings may contain a subset in a different row order. Never interpret
    # those local indices as indices in the complete source graph.
    parent_lookup = {str(value): i for i, value in enumerate(neurons.root_id)}
    parent_rows = np.array([parent_lookup.get(str(value), -1) for value in displayed.root_id], dtype=np.int64)
    if np.any(parent_rows < 0):
        raise ValueError('Recorded neurons are incompatible with the active source graph')
    def indices(which):
        selected = payload.get(f'{which}_indices', [])
        if not isinstance(selected, list) or any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < n for i in selected):
            raise ValueError('Neuron selections must contain valid integer indices')
        result = set(parent_rows[np.asarray(selected,dtype=np.int64)].tolist())
        displayed_parents = set(parent_rows.tolist())
        for key in payload.get(f'{which}_regions', []):
            if model_id != 'flywire-783':
                raise ValueError('Use model-qualified neuron selections for combined-model connectivity')
            result.update(displayed_parents.intersection(state.region_neurons(key)['indices']))
        if not result:
            raise ValueError('Choose at least one source and target neuron or region')
        return np.array(sorted(result), dtype=np.int64)
    source, target = indices('source'), indices('target')
    limit = payload.get('limit', 100)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError('Edge display limit must be between 1 and 1000')
    def directed(src, dst):
        edges = []; total = 0; count = 0
        for kind, matrix in matrices:
            subset = matrix.tocsr()[dst][:, src].tocoo()
            subset.eliminate_zeros()
            count += subset.nnz
            total += float(np.sum(np.abs(subset.data)))
            for j in np.argsort(-np.abs(subset.data))[:limit]:
                a, b = int(src[subset.col[j]]), int(dst[subset.row[j]])
                edges.append({'source_index': a, 'target_index': b,
                              'source_id': str(neurons.iloc[a].get('entity_id', neurons.iloc[a].root_id)),
                              'target_id': str(neurons.iloc[b].get('entity_id', neurons.iloc[b].root_id)),
                              'weight': float(subset.data[j]), 'kind': kind})
        return {'edge_count': count, 'synapse_count': total,
                'edges': sorted(edges, key=lambda edge: -abs(edge['weight']))[:limit]}
    return {'model_id': model_id, 'source_count': len(source), 'target_count': len(target),
            'forward': directed(source, target), 'reverse': directed(target, source)}
