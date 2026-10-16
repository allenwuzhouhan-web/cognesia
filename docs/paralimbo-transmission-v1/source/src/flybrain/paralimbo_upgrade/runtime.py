"""Batched checked HybridEngine equations and complete deterministic replay.

This explicit kernel mirrors the inherited HybridEngine scheduler; it adds
persistent checks before clamps/resets. It does not change or prepare providers,
trim the graph, or claim native registrations. Unsupported chemistry/organ
components fail closed. All Python callbacks occur between compiled blocks.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import uuid
from pathlib import Path
import time

import numba as nb
from numba.typed import List
import numpy as np

from flybrain.experiment_session import (snapshot_state, restore_state, model_fingerprint,
                                        _pack, _unpack, _validate_tree, COMPONENTS)
from flybrain.hybrid_engine import HybridEngine
from flybrain.memguard import check_memory, MemoryGuard
from .interfaces import INTERFACE_VERSION, StimulusInput, identity, canonical_json
from .numerics import integer_steps

FAULT_FIELDS = ('nonfinite_voltage_updates', 'nonfinite_synaptic_updates',
                'nonfinite_release_updates', 'invalid_delayed_spikes')

@nb.njit(cache=True, parallel=True, fastmath=False)
def _advance_checked(v, g, graded, last_spike, refractory_steps, active, firing,
                    spike_ring, spike_ring_counts, release_history, clamp_counts,
                    graded_indptr, graded_indices, graded_counts,
                    spike_indptr, spike_indices, spike_counts,
                    start, stop, run_start, delay_steps, decay_v, decay_g,
                    synaptic_forcing_scale, rest, release_threshold, gain,
                    reset, threshold, spike_weight, minimum, maximum,
                    photo_map, photo_drive, drive_mode, records, record_stride,
                    record_start, voltages, boundary_graded, boundary_spikes, output_enabled, faults):
    output_indices = List.empty_list(nb.int32)
    output_steps = List.empty_list(nb.int64)
    n = len(v)
    for step in range(start, stop):
        for neuron in nb.prange(n):
            if not np.isfinite(v[neuron]):
                faults[neuron, 0] += 1
            if not np.isfinite(g[neuron]):
                faults[neuron, 1] += 1
        # Validate queued events before a future slot can overwrite evidence.
        for slot in range(len(spike_ring_counts)):
            count_live = spike_ring_counts[slot]
            if count_live < 0 or count_live > spike_ring.shape[1]:
                faults[0, 3] += 1
                spike_ring_counts[slot] = 0  # unsafe indices never reach delivery
            else:
                for event in range(count_live):
                    if spike_ring[slot, event] < 0 or spike_ring[slot, event] >= n:
                        faults[0, 3] += 1
                        spike_ring_counts[slot] = 0
                        break
        if step % record_stride == 0:
            row = step // record_stride - record_start
            for j in range(len(records)):
                voltages[row, j] = v[records[j]]

        # Snapshot release before ANY neuron is advanced, including delay=0.
        history_now = step % len(release_history)
        for neuron in nb.prange(n):
            release_history[history_now, neuron] = max(0.0, v[neuron] - release_threshold) if graded[neuron] and output_enabled[neuron] else 0.0
            if not np.isfinite(release_history[history_now, neuron]):
                faults[neuron, 2] += 1
        history_delayed = (step - delay_steps) % len(release_history)

        for neuron in nb.prange(n):
            eligible = graded[neuron] or step - last_spike[neuron] >= refractory_steps[neuron]
            active[neuron] = eligible
            firing[neuron] = False
            if eligible:
                # Row ownership and fixed edge order keep sums deterministic.
                release_sum = 0.0
                for edge in range(graded_indptr[neuron], graded_indptr[neuron + 1]):
                    pre = graded_indices[edge]
                    release_sum += graded_counts[edge] * release_history[history_delayed, pre]
                if boundary_graded.shape[0]:
                    release_sum += boundary_graded[step - run_start, neuron]
                current = 0.0
                photo = photo_map[neuron]
                if photo >= 0:
                    if drive_mode == 0:
                        current = photo_drive[0, 0]
                    elif drive_mode == 1:
                        current = photo_drive[step - run_start, 0]
                    else:
                        current = photo_drive[step - run_start, photo]
                old_g = g[neuron]
                updated = (rest[neuron] + (v[neuron] - rest[neuron]) * decay_v[neuron]
                           + (old_g + current) * (1.0 - decay_v[neuron]))
                g[neuron] = old_g * decay_g[neuron] + synaptic_forcing_scale[neuron] * gain * release_sum
                if not np.isfinite(updated):
                    faults[neuron, 0] += 1
                if not np.isfinite(g[neuron]):
                    faults[neuron, 1] += 1
                if not np.isfinite(release_sum):
                    faults[neuron, 2] += 1
                if updated < minimum:
                    updated = minimum
                    clamp_counts[neuron] += 1
                elif updated > maximum:
                    updated = maximum
                    clamp_counts[neuron] += 1
                v[neuron] = updated
                if not graded[neuron] and updated > threshold:
                    firing[neuron] = True
                    active[neuron] = False
                    last_spike[neuron] = step

        future = (step + delay_steps) % len(spike_ring_counts)
        count = 0
        emitted_start = len(output_indices)
        for neuron in range(n):
            if firing[neuron]:
                if output_enabled[neuron]:
                    spike_ring[future, count] = neuron
                    count += 1
                output_indices.append(np.int32(neuron))
                output_steps.append(np.int64(step))
        spike_ring_counts[future] = count
        current = step % len(spike_ring_counts)
        for j in range(spike_ring_counts[current]):
            pre = spike_ring[current, j]
            for edge in range(spike_indptr[pre], spike_indptr[pre + 1]):
                post = spike_indices[edge]
                if active[post]:
                    g[post] += spike_counts[edge] * spike_weight
        spike_ring_counts[current] = 0
        if boundary_spikes.shape[0]:
            for neuron in nb.prange(n):
                if active[neuron]:
                    g[neuron] += boundary_spikes[step - run_start, neuron]
        # Inspect before spike reset can erase an overflowing synaptic update.
        for neuron in nb.prange(n):
            if not np.isfinite(g[neuron]):
                faults[neuron, 1] += 1
            if faults[neuron, 4] < 0 and (faults[neuron, 0] or faults[neuron, 1] or faults[neuron, 2] or faults[neuron, 3] or clamp_counts[neuron]):
                faults[neuron, 4] = step
        # Reset after delivery, preserving the original scheduler. Walking only
        # this step's emitted events avoids a full-memory pass and a parallel
        # barrier on every step of a sparse/graded Apple Silicon workload.
        # Recorded events include output-silenced spikes, which still reset.
        for j in range(emitted_start, len(output_indices)):
            neuron = output_indices[j]
            v[neuron] = reset
            g[neuron] = 0.0
    return np.asarray(output_indices), np.asarray(output_steps)



class ScheduledInput:
    """Input-only contract cursor; samples denote exact integration start times."""
    def __init__(self, stimulus: StimulusInput, root_ids, dt_ms):
        self.stimulus = stimulus
        self.root_ids = tuple(str(r) for r in root_ids)
        if len(set(self.root_ids)) != len(self.root_ids):
            raise ValueError('Complete graph roots must be unique')
        lookup = {root: i for i, root in enumerate(self.root_ids)}
        if any(root not in lookup for root in stimulus.target_root_ids):
            raise ValueError('Input target is absent from the retained graph')
        self.indices = np.array([lookup[r] for r in stimulus.target_root_ids], np.int32)
        self.dt_ms = float(dt_ms)
        self.times = np.asarray(stimulus.time_ms, np.float64)
        self.drive = np.asarray(stimulus.drive_mv, np.float64)
        if len(self.times) > 1 and not np.allclose(np.diff(self.times), self.dt_ms, rtol=0, atol=1e-10):
            raise ValueError('Input samples must match the physical integration clock')
        if not np.isfinite(self.dt_ms) or self.dt_ms <= 0 or self.times[0] != 0:
            raise ValueError('Input clock must start at zero with positive dt_ms')
        self.cursor = stimulus.cursor
        self.identity = stimulus.digest

    def block(self, start_step, stop_step):
        end = self.cursor + stop_step - start_step
        expected = np.arange(start_step, stop_step, dtype=np.float64) * self.dt_ms
        if end > len(self.times) or not np.allclose(self.times[self.cursor:end], expected, rtol=0, atol=1e-10):
            raise ValueError('Input cursor/timing does not match the engine clock')
        result = self.drive[self.cursor:end].copy()
        self.cursor = end
        return self.indices, result

    def snapshot(self):
        return {'identity': self.identity, 'cursor': self.cursor, 'dt_ms': self.dt_ms,
                'root_ids': list(self.root_ids)}

    def restore(self, state):
        if set(state) != {'identity', 'cursor', 'dt_ms', 'root_ids'} or state['identity'] != self.identity or state['dt_ms'] != self.dt_ms or tuple(state['root_ids']) != self.root_ids:
            raise ValueError('Adapter identity mismatch')
        if type(state['cursor']) is not int or not 0 <= state['cursor'] <= len(self.times):
            raise ValueError('Invalid input cursor')
        self.cursor = state['cursor']


def _state_digest(state):
    def describe(value):
        if isinstance(value, np.ndarray):
            return {'dtype': str(value.dtype), 'shape': value.shape,
                    'sha256': hashlib.sha256(value.tobytes(order='C')).hexdigest()}
        if isinstance(value, dict):
            return {key: describe(v) for key, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [describe(v) for v in value]
        if isinstance(value, np.generic):
            return value.item()
        return value
    return identity(describe(state))


class CheckedRunner:
    """Full population checked execution; selected recording stays float64.

    Adapters implement block(start_step, stop_step) -> (indices, mV samples),
    snapshot(), restore(state), and immutable identity. Area 03 can wrap its
    deterministic interval-mean input in this bounded block interface.
    """
    def __init__(self, engine, adapter, root_ids, *, expected_population, scope='fixture'):
        if not isinstance(engine, HybridEngine):
            raise ValueError('Checked HybridEngine required')
        if any(getattr(engine, name, None) is not None for name in COMPONENTS):
            raise ValueError('Chemistry/organ components need a separately registered checked kernel')
        self.root_ids = tuple(str(r) for r in root_ids)
        if len(self.root_ids) != engine.n_neurons or len(set(self.root_ids)) != len(self.root_ids) or expected_population != engine.n_neurons:
            raise ValueError('Full retained graph population/identity mismatch')
        if scope not in {'fixture', 'full_graph'}:
            raise ValueError('Explicit runtime scope required')
        self.engine, self.adapter, self.scope = engine, adapter, scope
        self.faults = np.zeros((engine.n_neurons, 5), np.int64)
        self.faults[:, 4] = -1
        coefficient_names = ('rest', 'tau_membrane', 'tau_synapse', 'decay_v_each', 'decay_g_each', 'forcing_scale', 'graded_row_scale')
        self.runtime_identity = identity({'coefficients': _state_digest({k: getattr(engine, k) for k in coefficient_names}), 'interface': INTERFACE_VERSION, 'model': model_fingerprint(engine, self.root_ids),
                                          'source': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                          'input': adapter.identity, 'scope': scope})
        self.last_result = None
        self.preparation = {'protocol': None, 'pass': False, 'reason': 'PREPARATION_NOT_REGISTERED'}

    def register_preparation(self, protocol, *, indices=(), drive=0., initialize=False,
                             residual_tolerance=1e-8, assumptions=()):
        """Explicit preparation; never silently impose quiescence on a provider.

        Use constant_background_equilibrium_v1 only when that protocol is
        registered. Existing prepared states can be checked with initialize=False.
        Any failed provider remains failed; a different preparation needs a new
        registration and runner. Fixture initial states require an explicit label.
        """
        if self.engine.step != 0 or self.preparation['protocol'] is not None:
            raise ValueError('Preparation is declared once before execution')
        if not np.isfinite(residual_tolerance) or not 0 < residual_tolerance <= 1e-8:
            raise ValueError('Preparation residual tolerance cannot be loosened')
        row = {'protocol': protocol, 'assumptions': list(assumptions), 'pass': False,
               'residual_tolerance': residual_tolerance, 'residual_units': 'mV/ms for derivatives; mV for delay history'}
        try:
            if protocol == 'synthetic_declared_initial_state_v1':
                if self.scope != 'fixture' or not assumptions or initialize:
                    raise ValueError('Declared initial state is fixture-only and requires assumptions')
                row['pass'] = self.diagnostics()['pass']
            elif protocol == 'constant_background_equilibrium_v1':
                from flybrain.neural_baseline import initialize_equilibrium, complete_residual
                if initialize:
                    row['solver'] = initialize_equilibrium(self.engine, indices, drive)
                residual = complete_residual(self.engine, indices, drive)
                row['residual'] = residual
                row['pass'] = self.diagnostics()['pass'] and residual['finite'] and residual['queued_spikes'] == 0 and all(
                    residual[k] <= residual_tolerance for k in ('max_abs_dvdt_mv_per_ms', 'max_abs_dgdt_mv_per_ms', 'max_delay_history_residual_mv'))
                row['background_indices'] = [int(i) for i in indices]
                row['background_drive_mv'] = np.asarray(drive).tolist()
            else:
                raise ValueError('Preparation alternative requires a separately implemented registration')
        except (ValueError, FloatingPointError) as error:
            row['reason'] = type(error).__name__ + ': ' + str(error)
        if not row['pass']:
            row.setdefault('reason', 'PREPARATION_RESIDUAL_FAILED')
        row['initial_state_digest'] = _state_digest(snapshot_state(self.engine))
        self.preparation = row
        return copy.deepcopy(row)

    def _scan(self):
        e = self.engine
        for j, name in enumerate(('v', 'g')):
            bad = ~np.isfinite(getattr(e, name))
            self.faults[bad, j] = np.maximum(self.faults[bad, j], 1)
        bad_release = np.any(~np.isfinite(e.release_history), axis=0)
        self.faults[bad_release, 2] = np.maximum(self.faults[bad_release, 2], 1)
        for slot, count in enumerate(e.ring_counts):
            if count < 0 or count > e.ring.shape[1] or np.any((e.ring[slot, :max(0, count)] < 0) | (e.ring[slot, :max(0, count)] >= e.n_neurons)):
                self.faults[0, 3] = max(self.faults[0, 3], 1)
        bad = (np.any(self.faults[:, :4] > 0, axis=1) | (e.per_neuron_clamp_counts != 0)) & (self.faults[:, 4] < 0)
        self.faults[bad, 4] = e.step

    def diagnostics(self):
        self._scan()
        e = self.engine
        totals = dict(zip(FAULT_FIELDS, map(int, self.faults[:, :4].sum(axis=0))))
        first = self.faults[:, 4][self.faults[:, 4] >= 0]
        return totals | {'clamps': int(e.per_neuron_clamp_counts.sum()),
                         'first_failure_step': int(first.min()) if first.size else None,
                         'endpoint_finite': bool(np.isfinite(e.v).all() and np.isfinite(e.g).all() and np.isfinite(e.release_history).all()),
                         'simulated_population': e.n_neurons,
                         'pass': not any(totals.values()) and not np.any(e.per_neuron_clamp_counts)}

    def snapshot(self):
        return {'runtime_identity': self.runtime_identity, 'interface_version': INTERFACE_VERSION,
                'engine': snapshot_state(self.engine), 'adapter': copy.deepcopy(self.adapter.snapshot()),
                'faults': self.faults.copy(), 'preparation': copy.deepcopy(self.preparation)}

    def restore(self, saved):
        previous = self.snapshot()
        if saved.get('runtime_identity') != self.runtime_identity or saved.get('interface_version') != INTERFACE_VERSION:
            raise ValueError('Runtime checkpoint identity mismatch')
        _validate_tree(previous, saved)
        if saved['adapter'].get('cursor') != saved['engine']['step']:
            raise ValueError('Adapter cursor and engine step mismatch')
        if saved['preparation'] != self.preparation:
            raise ValueError('Checkpoint preparation registration mismatch')
        if np.any(saved['faults'][:, :4] < 0) or np.any(saved['faults'][:, 4] < -1):
            raise ValueError('Invalid persistent diagnostics')
        counts = saved['engine']['ring_counts']; ring = saved['engine']['ring']
        for slot, count in enumerate(counts):
            if not 0 <= count <= ring.shape[1] or np.any((ring[slot, :count] < 0) | (ring[slot, :count] >= self.engine.n_neurons)):
                raise ValueError('Invalid checkpoint delayed buffer')
        try:
            restore_state(self.engine, saved['engine'])
            self.adapter.restore(copy.deepcopy(saved['adapter']))
            self.faults[:] = saved['faults']
        except Exception:
            restore_state(self.engine, previous['engine'])
            self.adapter.restore(previous['adapter'])
            self.faults[:] = previous['faults']
            raise

    def run(self, duration_ms, *, record_indices, block_ms=5.):
        e = self.engine
        steps, block_steps = integer_steps(duration_ms, e.dt), integer_steps(block_ms, e.dt, 'block_ms')
        records = np.asarray(record_indices)
        if records.ndim != 1 or records.dtype.kind not in 'iu' or np.any(records < 0) or np.any(records >= e.n_neurons) or len(np.unique(records)) != len(records):
            raise ValueError('Unique valid recording indices required')
        records = records.astype(np.int32)
        start, end = e.step, e.step + steps
        chunks, spikes, spike_times, times, voltages = [], [], [], [], []
        old_threads = nb.get_num_threads()
        error = None
        try:
            from .resources import current_admission
            admission = current_admission()
            if self.scope == 'full_graph' and (admission is None or admission['scope'] != 'full_graph'):
                raise RuntimeError('Full graph execution requires primary-root admission')
            if self.scope == 'fixture' and e.n_neurons > 256:
                raise ValueError('Fixture population cannot exceed 256')
            if admission is not None and e.threads > admission['policy']['threads']:
                raise ValueError('Engine exceeds admitted thread policy')
            nb.set_num_threads(e.threads)
            if not self.preparation['pass']:
                raise ValueError('PREPARATION_NOT_QUALIFIED: ' + str(self.preparation.get('reason')))
            if self.adapter.snapshot().get('cursor') != e.step:
                raise ValueError('Adapter cursor/timing does not match engine step')
            while e.step < end and self.diagnostics()['pass']:
                check_memory()
                lo, hi = e.step, min(end, e.step + block_steps)
                before_adapter = copy.deepcopy(self.adapter.snapshot())
                try:
                    indices, drive = self.adapter.block(lo, hi)
                    indices, drive = np.asarray(indices), np.asarray(drive, np.float64)
                    if indices.ndim != 1 or indices.dtype.kind not in 'iu' or len(np.unique(indices)) != len(indices) or np.any(indices < 0) or np.any(indices >= e.n_neurons):
                        raise ValueError('Invalid adapter target indices')
                    if drive.shape != (hi - lo, len(indices)) or not np.isfinite(drive).all():
                        raise ValueError('Adapter block must contain finite normalized mV samples')
                except Exception:
                    self.adapter.restore(before_adapter)
                    raise
                photo_map = np.full(e.n_neurons, -1, np.int32)
                photo_map[indices] = np.arange(len(indices), dtype=np.int32)
                record_start = (lo + e.record_stride - 1) // e.record_stride
                record_steps = np.arange(record_start * e.record_stride, hi, e.record_stride, dtype=np.int64)
                recorded = np.empty((len(record_steps), len(records)), np.float64)
                began = time.perf_counter()
                ix, ts = _advance_checked(e.v, e.g, e.graded_mask, e.last_spike, e.refractory_steps,
                    e.active, e.firing, e.ring, e.ring_counts, e.release_history,
                    e.per_neuron_clamp_counts, e.graded_indptr, e.graded_indices, e.graded_counts,
                    e.csc_indptr, e.csc_indices, e.csc_counts, lo, hi, lo, e.delay_steps,
                    e.decay_v_each, e.decay_g_each, e.forcing_scale, e.rest,
                    e.parameters['graded_release'], e.parameters['graded_gain'], e.parameters['v_reset'],
                    e.parameters['v_threshold'], e.parameters['spike_weight'], e.parameters['voltage_min'],
                    e.parameters['voltage_max'], photo_map, drive, 2, records, e.record_stride,
                    record_start, recorded, np.empty((0, 0)), np.empty((0, 0)), e.output_enabled, self.faults)
                e.step = hi; e.clamp_count = int(e.per_neuron_clamp_counts.sum())
                chunks.append({'start_step': lo, 'stop_step': hi, 'wall_seconds': time.perf_counter() - began})
                times.append(record_steps * e.dt); voltages.append(recorded)
                spikes.append(ix); spike_times.append(ts * e.dt)
                check_memory()
        except Exception as exc:
            error = type(exc).__name__ + ': ' + str(exc)
        finally:
            nb.set_num_threads(old_threads)
        diagnostics = self.diagnostics()
        self.last_result = {'time_ms': np.concatenate(times) if times else np.empty(0),
                           'voltage_mv': np.concatenate(voltages) if voltages else np.empty((0, len(records))),
                           'root_ids': np.array(self.root_ids)[records], 'units': 'mV',
                           'spike_indices': np.concatenate(spikes) if spikes else np.empty(0, np.int32),
                           'spike_times_ms': np.concatenate(spike_times) if spike_times else np.empty(0),
                           'diagnostics': diagnostics, 'blocks': chunks, 'runtime_identity': self.runtime_identity,
                           'completed': e.step == end and diagnostics['pass'] and error is None,
                           'failure_reason': error or (None if diagnostics['pass'] else 'COMPILED_STATE_CHECK_FAILED'),
                           'scope': self.scope, 'preparation': copy.deepcopy(self.preparation), 'simulated_ms': (e.step - start) * e.dt}
        return self.last_result

    def checkpoint_bytes(self):
        arrays = {}; saved = self.snapshot(); tree = _pack(saved, arrays)
        metadata = {'tree': tree, 'state_digest': _state_digest(saved)}
        buffer = io.BytesIO()
        np.savez_compressed(buffer, metadata=np.frombuffer(canonical_json(metadata).encode(), dtype=np.uint8), **arrays)
        return buffer.getvalue()

    def restore_bytes(self, payload):
        with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
            metadata = json.loads(archive['metadata'].tobytes())
            arrays = {k: archive[k] for k in archive.files if k != 'metadata'}
        saved = _unpack(metadata['tree'], arrays)
        if _state_digest(saved) != metadata['state_digest']:
            raise ValueError('Checkpoint content digest mismatch')
        self.restore(saved)

    def seal_checkpoint(self, store, prefix):
        payload = self.checkpoint_bytes()
        path = store.bytes(prefix + '.npz', payload)
        store.json(prefix + '.json', {'sha256': hashlib.sha256(payload).hexdigest(),
                                    'runtime_identity': self.runtime_identity, 'step': self.engine.step,
                                    'scope': self.scope})
        return path

    def save_recovery(self, store):
        """One rotating recovery file; atomic budget charges old plus new copies."""
        payload = self.checkpoint_bytes()
        path = store.path('active-recovery.npz')
        # Write a fresh immutable first copy using the workload reservation.
        # The registered parent charges both old recovery and new temporary.
        temporary = store.bytes('.active-recovery-' + uuid.uuid4().hex + '.next', payload)
        with store.budget._locked() as state:
            os.replace(temporary, path)
            store.budget._save(state)
        return path

    def retain_result(self, store, prefix):
        if self.last_result is None:
            raise ValueError('No execution to retain')
        result = self.last_result
        store.npz(prefix + '.npz', **{k: result[k] for k in ('time_ms', 'voltage_mv', 'root_ids', 'spike_indices', 'spike_times_ms')})
        store.json(prefix + '.json', {k: v for k, v in result.items() if not isinstance(v, np.ndarray)})
        # Failed nonfinite state is inspectable evidence, never admitted recovery.
        store.bytes(prefix + '-state.npz', self.checkpoint_bytes())


def measured_pilot(factory, *, duration_ms, record_indices, block_ms=5., store=None, prefix='pilot', memory_limit_gb=1.):
    """Measure exactly the supplied factory, including full checkpoint replay.

    Use resources.admitted_pilot around this call for retained or full-graph
    execution. Unretained fixtures of <=256 neurons may run in module tests.
    A factory returns a fresh, explicitly prepared CheckedRunner. Two measured
    runs follow a separate warm-up, each restored from serialized initial state.
    """
    from .resources import current_admission
    if store is not None and current_admission() is None:
        raise RuntimeError('Retained pilot requires admission-controlled context')
    with MemoryGuard(memory_limit_gb) as guard:
        started = time.perf_counter()
        runner = factory()
        startup = time.perf_counter() - started
        if runner.scope == 'full_graph' and current_admission() is None:
            raise RuntimeError('Full graph pilot requires admission')
        if runner.scope == 'fixture' and runner.engine.n_neurons > 256:
            raise ValueError('Fixture pilot cannot relabel a full graph')
        checkpoint_start = time.perf_counter()
        initial = runner.checkpoint_bytes()
        checkpoint_seconds = time.perf_counter() - checkpoint_start
        warmup = runner.run(duration_ms, record_indices=record_indices, block_ms=block_ms)
        warmup_seconds = sum(b['wall_seconds'] for b in warmup['blocks'])
        if not warmup['completed']:
            if store is not None:
                runner.retain_result(store, prefix + '-failed')
            return {'status': 'FAILED', 'scope': runner.scope, 'runtime_identity': runner.runtime_identity,
                    'preparation': runner.preparation, 'failure_reason': warmup['failure_reason']}
        restore_start = time.perf_counter(); runner.restore_bytes(initial)
        restore_seconds = time.perf_counter() - restore_start
        wall = time.perf_counter()
        first = runner.run(duration_ms, record_indices=record_indices, block_ms=block_ms)
        first_seconds = time.perf_counter() - wall
        ending = _state_digest(runner.snapshot())
        runner.restore_bytes(initial)
        wall = time.perf_counter()
        replay = runner.run(duration_ms, record_indices=record_indices, block_ms=block_ms)
        replay_seconds = time.perf_counter() - wall
        replay_exact = first['completed'] and replay['completed'] and ending == _state_digest(runner.snapshot()) and np.array_equal(first['voltage_mv'], replay['voltage_mv'])
        guard.check()
        report = {'interface_version': INTERFACE_VERSION, 'status': 'PASS' if replay_exact else 'FAILED',
                  'scope': runner.scope, 'runtime_identity': runner.runtime_identity,
                  'population': runner.engine.n_neurons, 'recorded_population': len(record_indices),
                  'duration_ms': duration_ms, 'dt_ms': runner.engine.dt, 'threads': runner.engine.threads,
                  'startup_seconds': startup, 'warmup_including_compile_seconds': warmup_seconds,
                  'warm_runtime_seconds': [first_seconds, replay_seconds],
                  'warm_seconds_per_step': max(first_seconds, replay_seconds) / integer_steps(duration_ms, runner.engine.dt),
                  'peak_rss_bytes': guard.peak_rss, 'checkpoint_seconds': checkpoint_seconds,
                  'checkpoint_restore_seconds': restore_seconds, 'checkpoint_bytes': len(initial),
                  'atomic_temporary_bytes': len(initial), 'serialized_full_state_replay_exact': bool(replay_exact),
                  'preparation': runner.preparation, 'diagnostics': replay['diagnostics'],
                  'experimental_response_rmse': None, 'biological_accuracy': 'NOT_EVALUATED',
                  'limitation': 'Rate applies only to this exact graph, input, kernel and threads.'}
        if store is not None:
            wall = time.perf_counter()
            store.bytes(prefix + '-initial.npz', initial)
            report['checkpoint_write_seconds'] = time.perf_counter() - wall
            report['checkpoint_seconds'] += report['checkpoint_write_seconds']
            runner.retain_result(store, prefix + '-trace')
            runner.save_recovery(store)
            report['retained_bytes_before_report'] = sum(p.stat().st_size for p in store.output.rglob('*') if p.is_file())
            store.json(prefix + '.json', report)
        return report


def synthetic_runner(*, dt_ms=.1, duration_ms=20., fixture_path=None):
    """Three-root inherited-HybridEngine fixture, using area-00 root contract.

    This is a separate signed-graph runtime diagnostic, not the analytic passive
    equation in integration-v1.json. Stimulus event values are sampled with exact
    zero-order holding at the registered 1, 2 and 3 ms event boundaries.
    """
    from scipy import sparse
    from flybrain.config import parameters
    from .resources import PRIMARY_ROOT
    path = Path(fixture_path or PRIMARY_ROOT / 'tests/fixtures/paralimbo_upgrade/integration-v1.json')
    document = json.loads(path.read_bytes())
    if document['interface_version'] != INTERFACE_VERSION:
        raise ValueError('Synthetic fixture interface mismatch')
    roots = tuple(document['registration']['root_ids'])
    if len(roots) != 3:
        raise ValueError('Expected registered three-root synthetic fixture')
    p = parameters(PRIMARY_ROOT) | {'record_dt_ms': 1., 'graded_input_cap': .8}
    engine = HybridEngine(sparse.csr_matrix(([100., -20.], ([1, 2], [0, 1])), shape=(3, 3)),
                          sparse.csr_matrix((3, 3)), np.array([True, True, False]), p, dt=dt_ms, threads=1)
    times = np.arange(integer_steps(duration_ms, dt_ms)) * dt_ms
    original = document['stimulus']
    indices = np.searchsorted(original['time_ms'], times, side='right') - 1
    drive = np.asarray(original['drive_mv'])[indices]
    stimulus = StimulusInput('runtime-three-root-pulse-v1', identity(original), original['registration_id'],
                             tuple(times), tuple(original['target_root_ids']), tuple(map(tuple, drive)),
                             input_provenance={'source_fixture': str(path), 'resampling': 'registered exact event hold'})
    runner = CheckedRunner(engine, ScheduledInput(stimulus, roots, dt_ms), roots, expected_population=3)
    runner.register_preparation('constant_background_equilibrium_v1', initialize=True, indices=[0], drive=0.,
                                assumptions=['Synthetic graph and inherited electrical equations.'])
    return runner
