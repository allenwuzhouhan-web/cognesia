"""Finite Simulate sessions for the unchanged, source-gated protocol engine.

Only transport and recording are adapted. CoreRuntime remains the sole owner of
odour transduction, Poisson drive, chemical fields, plasticity and its RNG.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

import numpy as np
import yaml

from .inspect_data import atomic_write_json
from .protocol_adapter import parse_protocol
from .rt.protocol import compile_protocol, ProtocolRunner


SCOPE = 'Source-verified neuromodulatory core; no visual pathway or validated body/motor decoder'
CHECKPOINT_LIMIT = ('Core protocol snapshots are readouts, not complete restart states. '
                    'Checkpoint/branch is unavailable for this engine; export preserves the '
                    'original protocol, actual spike log and measured endpoint for inspection.')


def run_legacy_protocol(root, document, progress=None, *, frame=None, control=None):
    """Run a finite original protocol, return a browser-ready saved raw summary.

    Transport accepts pause, resume, integer-ms step (1..100), stop and explicit
    checkpoint rejection. Stop saves a partial recording and returns normally
    with ``status='stopped'``; no restart checkpoint is fabricated.
    """
    from .rt.engine_rt import CoreRuntime
    return _run(root, document, CoreRuntime, progress, frame=frame, control=control)


def _run(root, document, runtime_factory, progress=None, *, frame=None, control=None):
    root = Path(root).resolve()
    parsed = parse_protocol(document)
    compiled = compile_protocol(parsed)
    if compiled['duration_ms'] <= 0:
        raise ValueError('Protocol requires a positive finite duration')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_core_protocol_' + uuid.uuid4().hex[:8]
    directory = root / 'runs' / run_id
    directory.mkdir(parents=True)
    (directory / 'protocol.yaml').write_text(document if isinstance(document, str) else yaml.safe_dump(parsed, sort_keys=False))
    atomic_write_json(directory / 'protocol_compiled.json', compiled)
    runtime = None
    def emit(event):
        if progress:
            progress(event)
    emit({'phase': 'loading', 'message': 'Verifying the original protocol core and pinned sensory sources', 'simulation_scope': SCOPE})
    try:
        runtime = runtime_factory(root, seed=compiled['seed'])
        # Compiles the original neural kernel, then resets RNG and recordings.
        runtime.warmup()
        runner = ProtocolRunner(runtime, parsed)
        count = len(runtime.neurons)
        parent = np.asarray(runtime.core.model_indices, np.int32)
        if parent.shape != (count,) or len(np.unique(parent)) != count or np.any(parent < 0):
            raise ValueError('Invalid verified core to FlyWire index mapping')
        planned_bytes = (compiled['duration_ms'] // 20 + 2) * count * 4
        if planned_bytes > 512 * 1024 ** 2:
            raise ValueError('Core protocol raw recording exceeds 512 MiB; shorten the protocol')
        runtime.neurons.to_parquet(directory / 'recorded_neurons.parquet', index=False)
        atomic_write_json(directory / 'selection.json', {'model_id': 'flywire-783', 'parent_indices': parent.tolist(), 'boundary': 'original_verified_core'})
        times, traces, sequence = [], {}, 0
        paused, step_remaining, stopped = False, None, False
        spike_offset = 0
        started = time.perf_counter()
        metadata = runtime.metadata()
        cell_types = runtime.neurons.cell_type.fillna('').to_numpy(str)
        groups = {name: np.flatnonzero(np.char.startswith(cell_types, prefix)) for name, prefix in [('Kenyon cells', 'KC'), ('MBON', 'MBON'), ('PPL1', 'PPL1')]}
        groups = {name: members for name, members in groups.items() if len(members)}
        traces = {name: [] for name in groups}
        with (directory / 'raw.bin').open('wb') as raw_file, (directory / 'core_frames.jsonl').open('w') as chemistry_file:
            def capture():
                nonlocal sequence, spike_offset
                voltage = np.asarray(runtime.engine.v, dtype='<f4').copy()
                if voltage.shape != (count,) or not np.isfinite(voltage).all():
                    raise ValueError('Invalid actual core voltage frame')
                when = float(runtime.t_sim_ms)
                if raw_file.tell() + voltage.nbytes > 512 * 1024 ** 2:
                    raise ValueError('Core protocol raw recording reached the 512 MiB limit')
                raw_file.write(voltage.tobytes())
                times.append(when)
                for name, members in groups.items():
                    traces[name].append(float(voltage[members].mean()))
                snapshot = runtime.snapshot()
                chemistry_file.write(json.dumps(snapshot, allow_nan=False) + '\n')
                spike_indices, spike_times, spike_offset = _new_spikes(runtime, spike_offset)
                sequence += 1
                if frame:
                    frame({'schema_version': 1, 'phase': 'core_protocol', 'sequence': sequence,
                           'model_id': 'flywire-783', 'model_hash': runtime.config_hash, 'simulation_scope': SCOPE,
                           'units': {'voltage_mv': 'mV', 'time_ms': 'ms', 'concentrations_au': 'a.u.'},
                           'wall_elapsed_seconds': time.perf_counter() - started,
                           'step': int(runtime.engine.step), 'dt_ms': float(runtime.engine.dt),
                           'model_time_ms': when, 'elapsed_ms': when,
                           'indices': np.arange(count, dtype=np.int32), 'parent_indices': parent.copy(),
                           'voltage_mv': voltage, 'spike_indices': spike_indices,
                           'spike_parent_indices': parent[spike_indices], 'spike_times_ms': spike_times,
                           'signal': 'raw', 'baseline_available': False, 'clamp_count': 0, 'final': runner.done,
                           'concentrations_au': np.asarray(snapshot.get('concentrations_au', []), np.float32),
                           'chemistry_diagnostics': {'species': metadata.get('species', []), 'compartments': metadata.get('compartments', []),
                                                     'field_clamps': snapshot.get('field_clamps'), 'weight_clamps': snapshot.get('weight_clamps')},
                           'real_time_factor': when / 1000 / max(time.perf_counter() - started, 1e-12)})
                emit({'phase': 'core_protocol', 'simulated_ms': when, 'duration_ms': compiled['duration_ms'],
                      'model_time_ms': when, 'message': f'Original core protocol: {when:g}/{compiled["duration_ms"]:g} simulated ms'})
            capture()
            while not runner.done and not stopped:
                incoming = control() if control else None
                commands = [] if incoming is None else incoming if isinstance(incoming, list) else [incoming]
                for command in commands:
                    reply = {'kind': 'command_result', 'request_id': command.get('request_id'), 'action': command.get('action'),
                             'phase': 'core_protocol', 'step': int(runtime.engine.step), 'model_time_ms': float(runtime.t_sim_ms)}
                    try:
                        action = command.get('action')
                        if action == 'pause':
                            paused, step_remaining = True, None
                        elif action == 'resume':
                            paused, step_remaining = False, None
                        elif action == 'step':
                            duration = command.get('duration_ms', 1)
                            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not np.isfinite(duration) or duration != int(duration) or not 1 <= duration <= 100:
                                raise ValueError('Core step duration must be an integer from 1 to 100 ms')
                            paused, step_remaining = True, int(duration)
                        elif action == 'stop':
                            stopped = True
                        elif action == 'checkpoint':
                            raise ValueError(CHECKPOINT_LIMIT)
                        else:
                            raise ValueError('Unknown core session command')
                        emit(reply | {'status': 'stopped' if stopped else 'paused' if paused else 'running', 'checkpoint_supported': False})
                    except (ValueError, TypeError) as error:
                        emit(reply | {'status': 'rejected', 'error': str(error)})
                if stopped:
                    break
                if paused and not step_remaining:
                    time.sleep(.02)
                    continue
                amount = min(20, compiled['duration_ms'] - int(runtime.t_sim_ms), step_remaining or 20)
                runner.advance(amount)
                capture()
                if step_remaining is not None:
                    step_remaining -= amount
                    if step_remaining <= 0:
                        step_remaining = None
                        emit({'kind': 'session_status', 'phase': 'core_protocol', 'action': 'step_complete',
                              'status': 'paused', 'model_time_ms': float(runtime.t_sim_ms)})
            raw_file.flush(); chemistry_file.flush()
        # The archive is original engine output, including all spikes and weights.
        archive = runtime.export(directory / 'core_recording.zip')
        indices = runtime.all_spike_indices
        spike_times = runtime.all_spike_steps.astype(float) * runtime.engine.dt
        np.savez_compressed(directory / 'spikes.npz', spike_indices=indices, spike_times_ms=spike_times)
        from .model_anatomy import write_anatomy
        prefix = f'/api/runs/{run_id}'
        anatomy = write_anatomy(runtime.neurons, directory / 'anatomy', prefix + '/anatomy', model_id='flywire-783', model_hash=runtime.config_hash)
        final = runtime.snapshot()
        colors = ['#4dd4df', '#8e9fec', '#f0b47b']
        status = 'stopped' if stopped else 'complete'
        intervals = np.diff(times)
        sample_dt = float(intervals[0]) if len(intervals) and np.allclose(intervals, intervals[0], rtol=0, atol=1e-9) else None
        summary = {'id': run_id, 'label': f'{compiled["name"]} · core protocol · {runtime.t_sim_ms:g} ms',
                   'status': status, 'completed': not stopped, 'partial': stopped, 'baseline_available': False,
                   'preferred_mode': 'absolute', 'model_id': 'flywire-783', 'model_hash': runtime.config_hash,
                   'neuron_count': count, 'simulation_scope': SCOPE, 'anatomy': anatomy,
                   'stimulus': {'type': 'core_protocol', 'duration_ms': float(runtime.t_sim_ms)},
                   'frames': {'count': len(times), 'time_ms': times, 'dt_ms': sample_dt, 'uniform': sample_dt is not None},
                   'activity': {'raw_url': prefix + '/raw.bin', 'shape': [len(times), count], 'dtype': 'float32',
                                'unit': 'mV', 'raw_unit': 'mV', 'baseline_available': False, 'color_range_mv': 20},
                   'traces': [{'id': 'core:' + name, 'label': name, 'name': name, 'raw': values, 'raw_mv': values,
                               'values': values, 'unit': 'mV', 'color': colors[i % len(colors)], 'count': len(groups[name])}
                              for i, (name, values) in enumerate(traces.items())],
                   'region_traces': [], 'eyes': {}, 'stimulation': {},
                   'stats': {'spikes': int(len(indices)), 'clamps': 0, 'wall_seconds': time.perf_counter() - started,
                             'voltage_out_of_bounds': final.get('voltage_out_of_bounds'), 'field_clamps': final.get('field_clamps'),
                             'weight_clamps': final.get('weight_clamps')},
                   'spikes': {'spike_indices': indices[-200000:].tolist(), 'spike_times_ms': spike_times[-200000:].tolist(),
                              'total': len(indices), 'retained': min(len(indices), 200000)},
                   'chemistry': {'available': False, 'status': 'ORIGINAL-CORE-ARCHIVE',
                                 'reason': 'Actual core fields and state are retained in core_frames.jsonl and core_recording.zip; no matched baseline was run.'},
                   'interpretation': 'Actual raw core membrane voltage; original odour/Poisson/plasticity protocol. No matched baseline or body behavior is inferred.',
                   'warnings': list(metadata.get('warnings', [])) + runner.warnings + [CHECKPOINT_LIMIT],
                   'metadata': {'engine': 'neuromod-core', 'protocol': compiled, 'core': metadata,
                                'source_session': str(runtime.session_dir.relative_to(root)), 'archive': Path(archive).name,
                                'duration_ms': float(runtime.t_sim_ms), 'sample_interval_ms': 20,
                                'sampling': 'Actual voltage at transport boundaries (normally 20 ms); exact per-frame times retained',
                                'frozen_test_readouts': runner.test_readouts, 'digests': runtime.digests(),
                                'checkpoint_supported': False, 'options': {'legacy_protocol': parsed}}}
        atomic_write_json(directory / 'visual_summary.json', summary)
        emit({'phase': status, 'status': status, 'run_id': run_id, 'message': 'Saved original core protocol ' + status + ' recording'})
        return summary
    except Exception as error:
        atomic_write_json(directory / 'protocol_failure.json', {'status': 'failed', 'error': str(error), 'scope': SCOPE})
        raise
    finally:
        if runtime is not None:
            runtime.close()


def _new_spikes(runtime, offset):
    for handle in runtime._spike_files:
        handle.flush()
    with (runtime.session_dir / 'spike_indices.i32').open('rb') as source:
        source.seek(offset * 4)
        indices = np.frombuffer(source.read(), dtype=np.int32).copy()
    with (runtime.session_dir / 'spike_steps.i64').open('rb') as source:
        source.seek(offset * 8)
        steps = np.frombuffer(source.read(), dtype=np.int64).copy()
    if len(indices) != len(steps):
        raise ValueError('Original core spike logs have inconsistent lengths')
    return indices, steps.astype(float) * runtime.engine.dt, offset + len(indices)
