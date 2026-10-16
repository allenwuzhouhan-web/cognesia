"""Full-graph direct perturbations with independent campaign admission.

This factory is a new engineering contract, not a bypass of the retrospective
T4 factory. The caller owns live locks, MemoryGuard, deadline and CampaignBudget;
its admission callback is checked before load, construction and every block.
"""
from __future__ import annotations
import copy
import hashlib
import math
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, asdict
from pathlib import Path
import numpy as np
import numba as nb
from scipy import sparse

from flybrain.config import parameters as source_parameters
from flybrain.hybrid_engine import HybridEngine
from flybrain.model_registry import load_model_network
from flybrain.memguard import check_memory
from flybrain.paralimbo_upgrade.interfaces import identity
from flybrain.paralimbo_upgrade.numerics import integer_steps
from flybrain.paralimbo_upgrade.runtime import CheckedRunner, _state_digest
from flybrain.experiment_session import _validate_tree
from .dynamics import NATIVE_POPULATION, configured_parameters, parameter_manifest
from .instrumentation import advance_instrumented, STAT_NAMES, COUNT_NAMES

_SCHEMA = 'transmission-direct-native-v1'
_ACTIVE_ADMISSION = ContextVar('transmission_campaign_admission', default=None)


@contextmanager
def campaign_admission(check):
    """Bind the caller's REAL lock/budget/deadline checker, never legacy admission."""
    if not callable(check):
        raise TypeError('Campaign admission must be a live callable')
    if check() is False:
        raise RuntimeError('Campaign admission refused')
    token = _ACTIVE_ADMISSION.set(check)
    try:
        yield check
    finally:
        _ACTIVE_ADMISSION.reset(token)


def _admit(check):
    if not callable(check):
        raise RuntimeError('Live campaign admission required')
    result = check()
    if result is False:
        raise RuntimeError('Live campaign admission required')
    return result


@dataclass(frozen=True)
class DirectPulse:
    target_root_ids: tuple[str, ...]
    onset_ms: float
    offset_ms: float
    amplitude_mv: float

    def __post_init__(self):
        object.__setattr__(self, 'target_root_ids', tuple(str(r) for r in self.target_root_ids))
        if not self.target_root_ids or len(set(self.target_root_ids)) != len(self.target_root_ids):
            raise ValueError('Pulse targets must be nonempty and unique')
        if not all(math.isfinite(x) and not isinstance(x, bool) for x in (self.onset_ms, self.offset_ms, self.amplitude_mv)) or not 0 <= self.onset_ms < self.offset_ms:
            raise ValueError('Pulse requires finite amplitude and ordered nonnegative times')


@dataclass(frozen=True)
class DirectProtocol:
    duration_ms: float
    pulses: tuple[DirectPulse, ...] = ()
    dt_ms: float = .1
    record_dt_ms: float = 1.
    background_mv: float = 0.
    silenced_roots: tuple[str, ...] = ()
    recording_roots: tuple[str, ...] = ()
    response_threshold_mv: float = .001
    label: str = 'direct-normalized-membrane-input'

    def __post_init__(self):
        object.__setattr__(self, 'pulses', tuple(self.pulses))
        for key in ('silenced_roots', 'recording_roots'):
            object.__setattr__(self, key, tuple(str(x) for x in getattr(self, key)))
            if len(set(getattr(self, key))) != len(getattr(self, key)):
                raise ValueError('Protocol root lists must be unique')
        integer_steps(self.duration_ms, self.dt_ms)
        integer_steps(self.record_dt_ms, self.dt_ms)
        if not math.isfinite(self.background_mv) or not math.isfinite(self.response_threshold_mv) or self.response_threshold_mv <= 0:
            raise ValueError('Finite background and positive response threshold required')
        if any(not isinstance(p, DirectPulse) or p.offset_ms > self.duration_ms for p in self.pulses):
            raise ValueError('Every pulse must lie within declared duration')
        if len(self.recording_roots) > 256:
            raise ValueError('At most 256 selected traces; full-population summaries remain active')

    @property
    def digest(self):
        return identity({'schema': _SCHEMA, 'protocol': asdict(self),
                         'units': 'normalized additive membrane input mV; not pA or voltage clamp'})


class PulseInput:
    """Analytic interval-mean rectangular pulses; only bounded blocks allocated."""
    def __init__(self, protocol, root_ids):
        self.protocol = protocol
        self.root_ids = tuple(str(r) for r in root_ids)
        lookup = {r: i for i, r in enumerate(self.root_ids)}
        targets = set(r for p in protocol.pulses for r in p.target_root_ids)
        if not targets <= set(lookup):
            raise ValueError('Direct target absent from frozen graph')
        ordered = tuple(r for r in self.root_ids if r in targets)
        self.indices = np.array([lookup[r] for r in ordered], np.int32)
        local = {r: i for i, r in enumerate(ordered)}
        self.pulse_columns = [np.array([local[r] for r in p.target_root_ids], np.int32) for p in protocol.pulses]
        self.cursor = 0
        self.identity = identity({'protocol': protocol.digest, 'root_order': identity(self.root_ids)})
        self.total_steps = integer_steps(protocol.duration_ms, protocol.dt_ms)

    def block(self, start_step, stop_step):
        if start_step != self.cursor or not start_step <= stop_step <= self.total_steps:
            raise ValueError('Direct input cursor/duration mismatch')
        starts = np.arange(start_step, stop_step) * self.protocol.dt_ms
        ends = starts + self.protocol.dt_ms
        drive = np.full((len(starts), len(self.indices)), self.protocol.background_mv, np.float64)
        for pulse, columns in zip(self.protocol.pulses, self.pulse_columns, strict=True):
            overlap = np.maximum(0., np.minimum(ends, pulse.offset_ms) - np.maximum(starts, pulse.onset_ms)) / self.protocol.dt_ms
            drive[:, columns] += overlap[:, None] * pulse.amplitude_mv
        self.cursor = stop_step
        return self.indices, drive

    def snapshot(self):
        return {'identity': self.identity, 'cursor': self.cursor}

    def restore(self, state):
        if set(state) != {'identity', 'cursor'} or state['identity'] != self.identity or type(state['cursor']) is not int or not 0 <= state['cursor'] <= self.total_steps:
            raise ValueError('Direct input checkpoint identity/cursor mismatch')
        self.cursor = state['cursor']

    def registered_background_input(self):
        return self.indices.copy(), np.full(len(self.indices), self.protocol.background_mv)


class FrozenModelCache:
    """Read-only verified full topology cache, scoped to one worker process."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self._models = {}
        self._preparations = {}
        self.last_preparation_cache_hit = False

    def prepare(self, engine, indices, drive, *, model_id, model_hash, source_hash, admission):
        """Reuse only an exact equilibrium; two model entries maximum, no adapters."""
        from flybrain import neural_baseline
        _admit(admission)
        if engine.step != 0 or any(getattr(engine, name, None) is not None for name in ('chemistry', 'organs', 'enzymes')):
            raise ValueError('Equilibrium caching requires a fresh neural-only engine')
        indices = np.asarray(indices, dtype=np.int64)
        if indices.ndim != 1 or len(np.unique(indices)) != len(indices) or np.any(indices < 0) or np.any(indices >= engine.n_neurons):
            raise ValueError('Unique valid preparation targets required')
        external = np.zeros(engine.n_neurons)
        external[indices] = np.broadcast_to(np.asarray(drive, float), (len(indices),))
        if not np.isfinite(external).all():
            raise ValueError('Finite preparation background required')
        key = identity({'model': [model_id, model_hash], 'source_config': source_hash,
            'solver_source': hashlib.sha256(Path(neural_baseline.__file__).read_bytes()).hexdigest(),
            'hybrid_source': hashlib.sha256(Path(__file__).parent.parent.joinpath('hybrid_engine.py').read_bytes()).hexdigest(),
            'parameters': engine.parameters, 'dt': engine.dt,
            'background': _state_digest({'external': external})})
        previous = self._preparations.get(model_id)
        self.last_preparation_cache_hit = previous is not None and previous['key'] == key
        if self.last_preparation_cache_hit:
            engine.reset()
            engine.v[:] = previous['v']; engine.g[:] = previous['g']
            engine.release_history[:] = np.maximum(0., engine.v-engine.parameters['graded_release'])*engine.graded_mask
            engine.ring.fill(0); engine.ring_counts.fill(0); engine.output_enabled[:] = True
            solver = copy.deepcopy(previous['solver'])
        else:
            solver = neural_baseline.initialize_equilibrium(engine, indices, drive)
            v, g = engine.v.copy(), engine.g.copy()
            v.flags.writeable = False; g.flags.writeable = False
            self._preparations[model_id] = {'key': key, 'v': v, 'g': g, 'solver': copy.deepcopy(solver)}
            if len(self._preparations) > 2:
                del self._preparations[next(iter(self._preparations))]
        _admit(admission)
        return solver

    def get(self, model_id, model_hash, *, admission):
        _admit(admission)
        key = (model_id, model_hash)
        if key not in self._models:
            if not isinstance(model_hash, str) or len(model_hash) != 64:
                raise ValueError('Explicit pinned model SHA-256 required')
            network = load_model_network(self.root, model_id, model_hash)
            m, neurons = network['manifest'], network['neurons']
            if m['id'] != model_id or m['model_hash'] != model_hash or identity({k:v for k,v in m.items() if k != 'model_hash'}) != model_hash:
                raise ValueError('Frozen model identity mismatch')
            if len(neurons) != NATIVE_POPULATION or m['neurons'] != NATIVE_POPULATION or neurons.root_id.duplicated().any():
                raise ValueError('Full 175401-neuron native graph required')
            if neurons.is_graded.to_numpy().dtype != np.bool_:
                raise ValueError('Frozen electrical mask must be boolean')
            for kind in ('graded', 'spiking'):
                matrix = network[kind]
                if not sparse.issparse(matrix) or matrix.shape != (NATIVE_POPULATION, NATIVE_POPULATION) or not np.isfinite(matrix.data).all():
                    raise ValueError('Both complete finite native partitions required')
                for array in (matrix.data, matrix.indices, matrix.indptr):
                    array.flags.writeable = False
            self._models[key] = network
        _admit(admission)
        return self._models[key]


class InstrumentedRunner(CheckedRunner):
    """Checked physical state plus O(N) summaries; counters are checkpoint state."""
    def __init__(self, engine, adapter, root_ids, *, expected_population, scope='fixture',
                 admission=None, total_steps=None, record_indices=(), response_threshold_mv=.001,
                 source_types=None, pool_target_indices=(), block_callback=None):
        super().__init__(engine, adapter, root_ids, expected_population=expected_population, scope=scope)
        if scope == 'fixture' and engine.n_neurons > 256:
            raise ValueError('Fixture population cannot exceed 256')
        self._admission = admission or _ACTIVE_ADMISSION.get()
        if scope == 'full_graph':
            _admit(self._admission)
            if engine.n_neurons != NATIVE_POPULATION:
                raise ValueError('Full 175401-neuron population required')
        self.total_steps = total_steps
        self.record_indices = np.array(record_indices, np.int32)
        self.response_threshold_mv = float(response_threshold_mv)
        if not np.isfinite(self.response_threshold_mv) or self.response_threshold_mv <= 0:
            raise ValueError('Positive diagnostic response threshold required')
        self.block_callback = block_callback
        labels = tuple(str(x) for x in (source_types if source_types is not None else ['<untyped>'] * engine.n_neurons))
        if len(labels) != engine.n_neurons:
            raise ValueError('Source types must preserve complete root order')
        self.group_names, ids = np.unique(labels, return_inverse=True)
        self.source_groups = ids.astype(np.int32)
        target_indices = tuple(int(x) for x in pool_target_indices)
        if len(target_indices) > 32 or len(set(target_indices)) != len(target_indices) or any(i < 0 or i >= engine.n_neurons for i in target_indices):
            raise ValueError('At most 32 unique valid target roots for compact source-type forcing')
        self.pool_targets = np.array(target_indices, np.int32)
        self.target_slots = np.full(engine.n_neurons, -1, np.int32)
        self.target_slots[self.pool_targets] = np.arange(len(self.pool_targets))
        self.stats = np.zeros((engine.n_neurons, len(STAT_NAMES)), np.float64)
        self.counts = np.zeros((engine.n_neurons, len(COUNT_NAMES)), np.int64)
        self.first = np.full((engine.n_neurons, 2), -1, np.int64)
        self.pool_forcing = np.zeros((len(target_indices), len(self.group_names), 2), np.float64)
        # Encode only anatomically present type pairs. Edge ids are immutable;
        # diagnostic storage scales with N, edges and thread x existing pairs,
        # never time x edges. Row ownership + private thread slots avoid races.
        check_memory()
        groups = len(self.group_names)
        graded_codes = (np.repeat(self.source_groups.astype(np.int64), np.diff(engine.graded_indptr)) * groups
                        + self.source_groups[engine.graded_indices])
        spike_codes = (self.source_groups[engine.csc_indices].astype(np.int64) * groups
                       + np.repeat(self.source_groups, np.diff(engine.csc_indptr)))
        self.pair_codes = np.union1d(graded_codes, spike_codes)
        self.graded_pair_ids = np.searchsorted(self.pair_codes, graded_codes).astype(np.int32)
        self.spike_pair_ids = np.searchsorted(self.pair_codes, spike_codes).astype(np.int32)
        del graded_codes, spike_codes
        # Keep slots stable across campaign policy reductions and restarts.
        # Current campaign admits at most 16 threads; larger explicit fixtures
        # remain possible without out-of-bounds private accumulators.
        self.pair_forcing = np.zeros((max(16, engine.threads), len(self.pair_codes), 2), np.float64)
        self.pair_diagnostic_bytes = sum(a.nbytes for a in (self.pair_codes, self.graded_pair_ids, self.spike_pair_ids, self.pair_forcing))
        check_memory()
        self.baseline_v = engine.v.copy()
        self.baseline_g = engine.g.copy()
        self.reset_instrumentation()
        self.runtime_identity = identity({'inherited': self.runtime_identity, 'schema': _SCHEMA,
            'instrumentation_source': hashlib.sha256(Path(__file__).with_name('instrumentation.py').read_bytes()).hexdigest(),
            'runtime_source': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'threshold_mv': self.response_threshold_mv, 'types': identity(labels), 'pool_targets': target_indices})
        self.receipt = {}

    def reset_instrumentation(self):
        if self.engine.step != 0:
            raise ValueError('Cannot erase running diagnostic history')
        self.baseline_v[:] = self.engine.v
        self.baseline_g[:] = self.engine.g
        self.stats.fill(0.); self.counts.fill(0); self.first.fill(-1); self.pool_forcing.fill(0.); self.pair_forcing.fill(0.)
        self.stats[:, 11] = np.where(self.engine.graded_mask, 0., self.engine.parameters['v_threshold'] - self.engine.v)

    def _check_admission(self):
        if self.scope == 'full_graph':
            policy = _admit(self._admission)
            if isinstance(policy, dict) and 'threads' in policy:
                threads = policy['threads']
                if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
                    raise ValueError('Invalid admitted thread limit')
                self.engine.threads = min(self.engine.threads, threads)
        if self.block_callback is not None:
            self.block_callback()

    def snapshot(self):
        result = super().snapshot()
        result['instrumentation'] = {name: getattr(self, name).copy() for name in ('baseline_v', 'baseline_g', 'stats', 'counts', 'first', 'pool_forcing', 'pair_forcing')}
        return result

    def restore(self, saved):
        if 'instrumentation' not in saved:
            raise ValueError('Checkpoint lacks diagnostic accumulators')
        _validate_tree(self.snapshot()['instrumentation'], saved['instrumentation'])
        if np.any(saved['instrumentation']['counts'] < 0) or np.any(saved['instrumentation']['first'] < -1):
            raise ValueError('Invalid diagnostic counters')
        super().restore(saved)
        for name, value in saved['instrumentation'].items():
            getattr(self, name)[:] = value

    def summary(self, *, include_arrays=True):
        e = self.engine
        totals = {name: int(self.counts[:, i].sum()) for i, name in enumerate(COUNT_NAMES)}
        ntypes = len(self.group_names)
        grouped = lambda values: np.bincount(self.source_groups, weights=values, minlength=ntypes)
        sizes = np.bincount(self.source_groups, minlength=ntypes)
        responding = grouped(self.first[:, 0] >= 0)
        peak = np.zeros(ntypes)
        np.maximum.at(peak, self.source_groups, self.stats[:, 0])
        spikes = grouped(self.counts[:, 3])
        saturated = grouped(e.graded_row_scale < 1.)
        positive = grouped(self.stats[:, 3] + self.stats[:, 5])
        negative = grouped(self.stats[:, 4] + self.stats[:, 6])
        by_type = []
        for i, name in enumerate(self.group_names):
            by_type.append({'type': str(name), 'neurons': int(sizes[i]),
                'responding_neurons': int(responding[i]), 'peak_abs_delta_v_mv': float(peak[i]),
                'spikes': int(spikes[i]), 'cap_saturated_neurons': int(saturated[i]),
                'positive_synaptic_forcing_mv': float(positive[i]), 'negative_synaptic_forcing_mv': float(negative[i])})
        report = {'schema': _SCHEMA, 'population': e.n_neurons, 'step': e.step, 'dt_ms': e.dt,
            'response_threshold_mv': self.response_threshold_mv, 'reference': 'registered prepared state; not population mean',
            'causal_limit': 'Prepared-state deviations include background drift; use matched quiet traces, never subtract absolute maxima.',
            'first_response_clock': 'integration boundary step; spikes use inherited emission-step convention',
            'pool_coverage': 'all anatomical source-type to target-type pairs; selected-root detail separately retained',
            'type_pair_diagnostic_bytes': self.pair_diagnostic_bytes,
            'type_pair_types': self.group_names.tolist(),
            'type_pair_count': len(self.pair_codes),
            'type_pair_positive_forcing_mv': float(self.pair_forcing[:, :, 0].sum()),
            'type_pair_negative_forcing_mv': float(self.pair_forcing[:, :, 1].sum()),
            'type_pair_precision': 'float64 private-thread sums; physical state remains independent of thread summation',
            'forcing_units': 'summed synaptic-state update mV, not physical charge',
            'totals': totals, 'by_type': by_type, 'pool_target_roots': [self.root_ids[i] for i in self.pool_targets],
            'pool_source_types': self.group_names.tolist(),
            'stats_columns': list(STAT_NAMES), 'counter_columns': list(COUNT_NAMES),
            'diagnostics': self.diagnostics()}
        if include_arrays:
            report.update(stats=self.stats.copy(), counts=self.counts.copy(), first_steps=self.first.copy(),
                rms_delta_v_mv=np.sqrt(self.stats[:, 1] / np.maximum(self.counts[:, 0], 1)),
                cap_scale=e.graded_row_scale.copy(), output_enabled=e.output_enabled.copy(), root_ids=np.array(self.root_ids),
                type_pair_source_indices=(self.pair_codes % ntypes).astype(np.int32),
                type_pair_target_indices=(self.pair_codes // ntypes).astype(np.int32),
                signed_type_pair_forcing_mv=self.pair_forcing.sum(axis=0), signed_pool_forcing_mv=self.pool_forcing.copy())
        return report

    def run(self, duration_ms=None, *, record_indices=None, block_ms=10.):
        e = self.engine
        self._check_admission()
        if duration_ms is None:
            if self.total_steps is None:
                raise ValueError('Explicit duration required')
            duration_ms = (self.total_steps - e.step) * e.dt
        if record_indices is None:
            record_indices = self.record_indices
        if self.total_steps is not None and e.step + integer_steps(duration_ms, e.dt) > self.total_steps:
            raise ValueError('Run exceeds registered duration')
        steps, block_steps = integer_steps(duration_ms, e.dt), integer_steps(block_ms, e.dt, 'block_ms')
        records = np.asarray(record_indices)
        if records.ndim != 1 or records.dtype.kind not in 'iu' or np.any(records < 0) or np.any(records >= e.n_neurons) or len(np.unique(records)) != len(records):
            raise ValueError('Unique valid recording indices required')
        records = records.astype(np.int32)
        start, end = e.step, e.step + steps
        chunks, spikes, spike_times, times, voltages = [], [], [], [], []
        old_threads = nb.get_num_threads()
        error = None
        control_error = None
        try:
            self._check_admission()
            nb.set_num_threads(e.threads)
            if not self.preparation['pass']:
                raise ValueError('PREPARATION_NOT_QUALIFIED: ' + str(self.preparation.get('reason')))
            if self.adapter.snapshot().get('cursor') != e.step:
                raise ValueError('Adapter cursor/timing does not match engine step')
            while e.step < end and self.diagnostics()['pass']:
                self._check_admission()
                nb.set_num_threads(e.threads)
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
                ix, ts = advance_instrumented(e.v, e.g, e.graded_mask, e.last_spike, e.refractory_steps,
                    e.active, e.firing, e.ring, e.ring_counts, e.release_history,
                    e.per_neuron_clamp_counts, e.graded_indptr, e.graded_indices, e.graded_counts,
                    e.csc_indptr, e.csc_indices, e.csc_counts, lo, hi, lo, e.delay_steps,
                    e.decay_v_each, e.decay_g_each, e.forcing_scale, e.rest,
                    e.parameters['graded_release'], e.parameters['graded_gain'], e.parameters['v_reset'],
                    e.parameters['v_threshold'], e.parameters['spike_weight'], e.parameters['voltage_min'],
                    e.parameters['voltage_max'], photo_map, drive, 2, records, e.record_stride,
                    record_start, recorded, np.empty((0, 0)), np.empty((0, 0)), e.output_enabled, self.faults,
                    self.baseline_v, self.baseline_g, self.stats, self.counts, self.first,
                    self.response_threshold_mv, e.dt, self.source_groups, self.target_slots, self.pool_forcing,
                    self.graded_pair_ids, self.spike_pair_ids, self.pair_forcing)
                e.step = hi; e.clamp_count = int(e.per_neuron_clamp_counts.sum())
                chunks.append({'start_step': lo, 'stop_step': hi, 'wall_seconds': time.perf_counter() - began})
                times.append(record_steps * e.dt); voltages.append(recorded)
                selected_events = np.isin(ix, records)
                spikes.append(ix[selected_events]); spike_times.append(ts[selected_events] * e.dt)
                check_memory()
        except Exception as exc:
            error = type(exc).__name__ + ': ' + str(exc)
            from flybrain.memguard import MemoryLimitExceeded
            from .budget import CampaignStorageExhausted
            from .controller import CampaignHalt
            if isinstance(exc, (CampaignHalt, MemoryLimitExceeded, CampaignStorageExhausted)):
                control_error = exc
        finally:
            nb.set_num_threads(old_threads)
        diagnostics = self.diagnostics()
        self.last_result = {'time_ms': np.concatenate(times) if times else np.empty(0),
                           'voltage_mv': np.concatenate(voltages) if voltages else np.empty((0, len(records))),
                           'root_ids': np.array(self.root_ids)[records], 'units': 'mV',
                           'spike_indices': np.concatenate(spikes) if spikes else np.empty(0, np.int32),
                           'spike_times_ms': np.concatenate(spike_times) if spike_times else np.empty(0),
                           'spike_event_scope': 'recorded_roots_only; full-population counts in summary',
                           'diagnostics': diagnostics, 'blocks': chunks, 'runtime_identity': self.runtime_identity,
                           'completed': e.step == end and diagnostics['pass'] and error is None,
                           'failure_reason': error or (None if diagnostics['pass'] else 'COMPILED_STATE_CHECK_FAILED'),
                           'scope': self.scope, 'preparation': copy.deepcopy(self.preparation), 'simulated_ms': (e.step - start) * e.dt}
        if control_error is not None:
            raise control_error
        return self.last_result

class NativePreparationError(ValueError):
    """Preparation is a retained refusal, never a request to invent a baseline."""
    def __init__(self, receipt):
        self.receipt = receipt
        super().__init__('PREPARATION_FAILED: ' + str(receipt.get('reason', 'residual failed')))


def _native_inputs(root, model_id, model_hash, values, dt, record_dt, threads, admission, model_cache):
    parameter_manifest(values)  # Reject out-of-bounds proposals before native load.
    policy = _admit(admission)
    if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
        raise ValueError('Positive integer thread count required')
    if isinstance(policy, dict) and 'threads' in policy:
        threads = min(threads, policy['threads'])
    cache = model_cache or FrozenModelCache(root)
    if cache.root != Path(root).resolve():
        raise ValueError('Model cache belongs to another frozen workspace')
    network = cache.get(model_id, model_hash, admission=admission)
    neurons = network['neurons']
    roots = tuple(neurons.root_id.astype('int64').astype(str))
    types = tuple(neurons.cell_type.fillna('').astype(str).replace('', '<untyped>'))
    params = configured_parameters(source_parameters(root), network['manifest'], values,
                                   dt_ms=dt, record_dt_ms=record_dt)
    _admit(admission)
    engine = HybridEngine(network['graded'], network['spiking'], neurons.is_graded.to_numpy(),
                          params, dt=dt, threads=threads)
    return network, engine, roots, types


def build_direct_runner(root, model_id, model_hash, protocol, *, parameters=None, threads=16,
                        admission=None, model_cache=None, block_callback=None):
    """Prepare the entire frozen graph for explicit normalized-input perturbations.

    Silence is an output intervention beginning at t=0 after the shared equilibrium;
    already prepared delayed release is retained, so its effect respects the delay.
    The background is applied to the union of declared pulse targets only.
    """
    if not isinstance(protocol, DirectProtocol):
        raise TypeError('Explicit DirectProtocol required')
    admission = admission or _ACTIVE_ADMISSION.get()
    _admit(admission)
    cache = model_cache or FrozenModelCache(root)
    network, engine, roots, types = _native_inputs(root, model_id, model_hash, parameters,
        protocol.dt_ms, protocol.record_dt_ms, threads, admission, cache)
    lookup = {r: i for i, r in enumerate(roots)}
    declared = set(protocol.recording_roots) | set(protocol.silenced_roots)
    if not declared <= set(lookup):
        raise ValueError('Recording/silencing target absent from frozen graph')
    adapter = PulseInput(protocol, roots)
    records = protocol.recording_roots or tuple(roots[i] for i in adapter.indices)
    if len(records) > 256:
        raise ValueError('At most 256 selected traces')
    record_indices = np.array([lookup[r] for r in records], np.int32)
    runner = InstrumentedRunner(engine, adapter, roots, expected_population=NATIVE_POPULATION,
        scope='full_graph', admission=admission, total_steps=adapter.total_steps,
        record_indices=record_indices, response_threshold_mv=protocol.response_threshold_mv,
        source_types=types, pool_target_indices=record_indices[:32], block_callback=block_callback)
    indices, drive = adapter.registered_background_input()
    try:
        solver = cache.prepare(engine, indices, drive, model_id=model_id, model_hash=model_hash,
            source_hash=hashlib.sha256((Path(root)/'config/parameters.yaml').read_bytes()).hexdigest(), admission=admission)
    except (ValueError, FloatingPointError) as exc:
        raise NativePreparationError({'pass': False, 'reason': str(exc)}) from exc
    prepared = runner.register_preparation('constant_background_equilibrium_v1', initialize=False,
        indices=indices, drive=drive, assumptions=[
            'Engineering diagnostic: constant declared normalized membrane input equilibrium.',
            'Undriven roots retain endogenous release with zero external drive.',
            'Direct amplitude is an assumed normalized mV input, not a measured optogenetic pA current.'])
    if not prepared['pass']:
        raise NativePreparationError(prepared)
    prepared['solver'] = solver
    runner.reset_instrumentation()
    engine.output_enabled[[lookup[r] for r in protocol.silenced_roots]] = False
    runner.runtime_identity = identity({'runner': runner.runtime_identity, 'protocol': protocol.digest,
        'parameter_contract': parameter_manifest(parameters)['identity'], 'silence_onset_ms': 0.})
    runner.receipt = {'schema': _SCHEMA, 'model_id': model_id, 'model_sha256': model_hash,
        'population': len(roots), 'graph_edges': network['manifest']['edges'],
        'protocol': asdict(protocol), 'protocol_identity': protocol.digest,
        'parameter_contract': parameter_manifest(parameters), 'preparation': prepared,
        'preparation_cache_hit': cache.last_preparation_cache_hit,
        'runtime_identity': runner.runtime_identity, 'scope': 'full_graph_engineering_diagnostic',
        'units': 'normalized additive membrane input mV; not measured pA',
        'silence': {'roots': list(protocol.silenced_roots), 'onset_ms': 0., 'retains_pre_intervention_delay_history': True},
        'background_target_roots': [roots[i] for i in adapter.indices],
        'resource_contract': 'live transmission-campaign admission; independent of legacy session exports',
        'biological_accuracy': 'NOT_EVALUATED'}
    _admit(admission)
    return runner


class T4InstrumentedRunner(InstrumentedRunner):
    def observe(self, trace):
        """Apply the unchanged registered acquisition/voltage observation operator."""
        from flybrain.paralimbo_upgrade.observation import observe_trace
        request = self.request
        if request.digest != self.receipt['source_request_sha256']:
            raise ValueError('Source observation contract changed')
        if (trace.get('scope') != 'full_graph' or trace.get('completed') is not True
                or trace.get('runtime_identity') != self.runtime_identity):
            raise ValueError('Observation requires a completed, identity-bound full-graph trace')
        return observe_trace(np.asarray(trace['time_ms']) + request.physical_origin_ms,
            {'voltage_mv': trace['voltage_mv']}, trace['root_ids'], request.observation,
            request.sample_time_ms, source_units='mV', event_onset_ms=request.event_onset_ms)


def build_t4_runner(root, request, parameters=None, *, admission=None, model_cache=None, block_callback=None):
    """Retain native T4 science validators and adapter under a new campaign contract.

    The old request binds source inputs, observation and preparation. Six-parameter
    dynamics and resource admission receive NEW identities; no legacy factory
    review or legacy group admission is fabricated or claimed.
    """
    from flybrain.paralimbo_upgrade.native_factory import _validate_science, _input_preflight, _holding_preflight
    from flybrain.paralimbo_upgrade import dynamics as native_dynamics, inputs
    from flybrain.paralimbo_upgrade.registrations.factories import graph_identity
    from flybrain.neural_baseline import complete_residual
    from flybrain.experiment_session import snapshot_state
    admission = admission or _ACTIVE_ADMISSION.get()
    _admit(admission)
    _validate_science(request)
    binding = request.digest
    preflight = _input_preflight(request)
    holding = _holding_preflight(request)
    indices, drive = np.asarray(holding['indices']), np.asarray(holding['drive_mv'], np.float64)
    expected = {'registration_digest': request.sensory_registration.digest,
        'context_digest': request.context.digest, 'movie_digest': request.movie.digest,
        'dt_ms': request.dt_ms, 'physical_origin_ms': request.physical_origin_ms}
    receipt = holding['receipt']
    if holding.get('digest') != identity(receipt) or any(receipt.get(k) != v for k, v in expected.items()):
        raise ValueError('Holding derivation identity mismatch')
    targets = set(request.sensory_registration.root_ids)
    expected_indices = np.array([i for i, r in enumerate(request.context.root_ids) if r in targets], np.int32)
    if (indices.ndim != 1 or indices.dtype.kind not in 'iu' or not np.array_equal(indices, expected_indices)
            or drive.shape != indices.shape or not np.isfinite(drive).all()
            or receipt.get('indices') != indices.tolist() or receipt.get('drive_mv') != drive.tolist()
            or preflight.get('indices') != indices.tolist()):
        raise ValueError('Holding and stimulus must cover all registered targets exactly once')
    if hashlib.sha256((Path(root) / 'config/parameters.yaml').read_bytes()).hexdigest() != request.source_parameters_sha256:
        raise ValueError('Frozen source parameters differ from source request')
    cache = model_cache or FrozenModelCache(root)
    network, engine, roots, types = _native_inputs(root, request.context.model_id, request.context.model_sha256,
        parameters, request.dt_ms, request.record_dt_ms, request.threads, admission, cache)
    manifest = network['manifest']
    if roots != request.context.root_ids or types != request.context.cell_types:
        raise ValueError('Frozen graph root order/types differ from T4 contract')
    graph_digest = graph_identity(manifest, manifest['output_hashes']['neurons.parquet'])
    if graph_digest != request.context.graph_sha256 or manifest['output_hashes']['neurons.parquet'] != request.context.source_sha256:
        raise ValueError('Frozen graph/source identity differs from T4 contract')
    source_science = native_dynamics.native_contract(request.variant, request.physiology_registration,
        request.observation, roots, engine.graded_mask)
    preparation = {'protocol': request.preparation_plan['protocol'], 'pass': False,
        'holding_digest': holding['digest'], 'source_request_sha256': binding,
        'parameter_contract': parameter_manifest(parameters)['identity']}
    try:
        preparation['solver'] = cache.prepare(engine, indices, drive, model_id=request.context.model_id,
            model_hash=request.context.model_sha256, source_hash=request.source_parameters_sha256, admission=admission)
        residual = preparation['residual'] = complete_residual(engine, indices, drive)
        diagnostics = preparation['diagnostics'] = native_dynamics.full_state_diagnostics(engine)
        tolerance = request.preparation_plan['residual_tolerance']
        if (not diagnostics['numerically_clean'] or not residual['finite'] or residual['queued_spikes']
                or any(not np.isfinite(residual[k]) or not 0 <= residual[k] <= tolerance for k in
                       ('max_abs_dvdt_mv_per_ms', 'max_abs_dgdt_mv_per_ms', 'max_delay_history_residual_mv'))):
            raise ValueError('Complete quiescent preparation residual failed')
        preparation['initial_state_digest'] = _state_digest(snapshot_state(engine))
    except (ValueError, FloatingPointError) as exc:
        preparation['reason'] = str(exc)
        raise NativePreparationError(preparation) from exc
    preparation['pass'] = True
    _admit(admission)
    resource_identity = identity({'schema': 'transmission-campaign-live-admission-v1',
        'source_request': binding, 'parameter_contract': parameter_manifest(parameters)['identity'],
        'campaign_workspace': str(Path(root).resolve()),
        'enforcement': 'caller locks, MemoryGuard, CampaignBudget and live deadline each block'})
    adapter_admission = {'registration_digest': request.sensory_registration.digest,
        'observation_digest': request.observation.digest, 'resource_admission_digest': resource_identity,
        'preparation_digest': identity(preparation), 'allowed_stimulus_ids': [request.movie.stimulus_id],
        'hypothesis_digest': identity(request.sensory_registration.spatial_correspondence['sensory_adapter']['hypothesis'])}
    adapter = inputs.DeterministicInputAdapter(request.sensory_registration, request.movie, request.context,
        dt_ms=request.dt_ms, physical_origin_ms=request.physical_origin_ms, admission=adapter_admission)
    actual_indices, actual_drive = adapter.registered_background_input()
    if adapter.input_preflight_receipt != preflight or not np.array_equal(actual_indices, indices) or not np.array_equal(actual_drive, drive):
        raise ValueError('Final sensory adapter differs from validated stimulus/holding contract')
    lookup = {r: i for i, r in enumerate(roots)}
    records = np.array([lookup[r] for r in request.observation.root_ids], np.int32)
    runner = T4InstrumentedRunner(engine, adapter, roots, expected_population=NATIVE_POPULATION,
        scope='full_graph', admission=admission, total_steps=integer_steps(request.duration_ms, request.dt_ms),
        record_indices=records, source_types=types, pool_target_indices=records[:32], block_callback=block_callback)
    checked = runner.register_preparation(request.preparation_plan['protocol'], indices=indices, drive=drive,
        initialize=False, residual_tolerance=tolerance, assumptions=request.preparation_plan['assumptions'])
    if not checked['pass'] or checked['initial_state_digest'] != preparation['initial_state_digest']:
        raise NativePreparationError(checked)
    runner.reset_instrumentation()
    runner.runtime_identity = identity({'runner': runner.runtime_identity, 'source_request': binding,
        'parameter_contract': parameter_manifest(parameters)['identity'], 'new_resource_contract': resource_identity})
    runner.request = request
    runner.receipt = {'schema': 'transmission-t4-native-v1', 'source_request_sha256': binding,
        'source_science_contract': source_science, 'parameter_contract': parameter_manifest(parameters),
        'source_request_scope': 'source sensory, anatomy, observation and preparation contract only',
        'legacy_evaluation_and_schedule_reused': False,
        'calibration_authority': 'separately frozen transmission campaign configuration, schedule and job ledger',
        'preparation_cache_hit': cache.last_preparation_cache_hit,
        'input_preflight': preflight, 'holding_receipt': receipt, 'preparation': preparation,
        'checked_preparation': checked, 'resource_admission_digest': resource_identity,
        'runtime_identity': runner.runtime_identity, 'population': len(roots), 'graph_sha256': graph_digest,
        'scope': 'restricted_hypothesis', 'evidence_class': 'single_cell_retrospective',
        'biological_accuracy': 'NOT_EVALUATED', 'numerical_qualification': 'PENDING_CAMPAIGN_PILOT'}
    _admit(admission)
    if request.digest != binding:
        raise ValueError('Source request changed during construction')
    return runner
