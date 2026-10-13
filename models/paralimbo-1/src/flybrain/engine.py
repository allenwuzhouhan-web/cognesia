"""Deterministic all-LIF dynamics with the released Brian2 scheduling rules.

Weights are signed synapse counts, W[post, pre].  State is in mV and ms.
Exponential Euler is the production integrator; exact_linear is an explicitly
separate reference diagnostic.  Float64 state avoids avoidable roundoff in the
reference comparison while the sparse wiring remains float32/int32.
"""
from __future__ import annotations

import time

import numba as nb
from numba.typed import List
import numpy as np
from scipy import sparse

from .memguard import check_memory


@nb.njit(cache=True, parallel=True, fastmath=False)
def _advance(v, g, last_spike, refractory_steps, active, firing,
             ring, ring_counts, csc_indptr, csc_indices, csc_counts,
             start, stop, dt, delay_steps, decay_v, decay_g, coupling,
             rest, reset, threshold, weight, input_amplitude, input_neurons,
             event_steps, event_inputs, event_position, clamp, minimum, maximum,
             record_indices, record_stride, record_start, voltages):
    spike_indices = List.empty_list(nb.int32)
    spike_steps = List.empty_list(nb.int64)
    clamp_count = 0
    n = len(v)
    for step in range(start, stop):
        # StateMonitor's default "start" slot: before the integration at t.
        if step % record_stride == 0:
            row = step // record_stride - record_start
            for j in range(len(record_indices)):
                voltages[row, j] = v[record_indices[j]]

        # Independent per-neuron updates. No floating point cross-thread sums.
        for neuron in nb.prange(n):
            eligible = step - last_spike[neuron] >= refractory_steps[neuron]
            active[neuron] = eligible
            firing[neuron] = False
            if eligible:
                old_g = g[neuron]
                updated = rest + (v[neuron] - rest) * decay_v + coupling * old_g
                if clamp:
                    if updated < minimum:
                        updated = minimum
                        clamp_count += 1
                    elif updated > maximum:
                        updated = maximum
                        clamp_count += 1
                v[neuron] = updated
                g[neuron] = old_g * decay_g
                if updated > threshold:
                    firing[neuron] = True
                    active[neuron] = False
                    last_spike[neuron] = step

        # Ascending neuron order gives stable spike output and summation order.
        # At most one spike per neuron per step: these ring capacities are exact
        # bounds, not heuristic event caps that could silently drop spikes.
        future = (step + delay_steps) % len(ring_counts)
        count = 0
        for neuron in range(n):
            if firing[neuron]:
                ring[future, count] = neuron
                count += 1
                spike_indices.append(np.int32(neuron))
                spike_steps.append(np.int64(step))
        ring_counts[future] = count

        # Brian2 synapses slot: deliver events only after threshold evaluation.
        # A refractory target's g is read-only, including its spike timestep.
        current = step % len(ring_counts)
        for j in range(ring_counts[current]):
            pre = ring[current, j]
            for edge in range(csc_indptr[pre], csc_indptr[pre + 1]):
                post = csc_indices[edge]
                if active[post]:
                    g[post] += csc_counts[edge] * weight
        ring_counts[current] = 0

        while event_position < len(event_steps) and event_steps[event_position] == step:
            neuron = input_neurons[event_inputs[event_position]]
            if active[neuron]:
                updated = v[neuron] + input_amplitude
                if clamp:
                    if updated < minimum:
                        updated = minimum
                        clamp_count += 1
                    elif updated > maximum:
                        updated = maximum
                        clamp_count += 1
                v[neuron] = updated
            event_position += 1

        # Brian reset comes last, after delayed and external input delivery.
        for neuron in nb.prange(n):
            if firing[neuron]:
                v[neuron] = reset
                g[neuron] = 0.0
    return np.asarray(spike_indices), np.asarray(spike_steps), event_position, clamp_count


def _integer_array(values, label, *, ndim=1):
    values = np.asarray(values)
    if values.ndim != ndim or not np.all(np.isfinite(values)):
        raise ValueError(f"{label} must be a finite {ndim}-D integer array")
    converted = values.astype(np.int64)
    if not np.array_equal(values, converted):
        raise ValueError(f"{label} must contain exact integer indices")
    return converted


class LIFEngine:
    """Persistable all-LIF state, driven only by explicitly supplied events.

    ``input_events[:, 0]`` contains timestep indices relative to the current
    ``run`` call; column 1 indexes ``input_neurons``. Events arrive in Brian's
    synapses slot and can first cause a spike on the following timestep.
    Returned times are absolute engine times in milliseconds. Requested voltage
    records have shape (samples, neurons), in the start slot, at 1 kHz by default.
    A failed run leaves ``last_result`` with all completed chunks and live state
    in ``v``, ``g``, and the delay ring for inspection or recovery.
    """

    def __init__(self, weights, parameters, dt=None, integrator="exponential_euler",
                 threads=16, clamp=True):
        if not sparse.issparse(weights) or len(weights.shape) != 2 or weights.shape[0] != weights.shape[1]:
            raise ValueError("weights must be a square scipy sparse matrix of signed synapse counts")
        if integrator not in {"exponential_euler", "exact_linear"}:
            raise ValueError("integrator must be exponential_euler or exact_linear")
        if not isinstance(threads, (int, np.integer)) or threads < 1:
            raise ValueError("threads must be a positive integer")
        self.parameters = dict(parameters)
        self.dt = float(parameters["dt"] if dt is None else dt)
        self.integrator = integrator
        self.threads = min(int(threads), nb.config.NUMBA_NUM_THREADS)
        self.clamp = bool(clamp)
        self.n_neurons = weights.shape[0]
        for name in ("v_rest", "v_reset", "v_threshold", "tau_membrane", "tau_synapse",
                     "refractory", "synaptic_delay", "spike_weight", "poisson_factor",
                     "voltage_min", "voltage_max"):
            if not np.isfinite(float(parameters[name])):
                raise ValueError(f"{name} must be finite")
        if not np.isfinite(self.dt) or self.dt <= 0:
            raise ValueError("dt must be positive and finite")
        if parameters["tau_membrane"] <= 0 or parameters["tau_synapse"] <= 0:
            raise ValueError("Time constants must be positive")
        if parameters["refractory"] < 0 or parameters["synaptic_delay"] < 0:
            raise ValueError("Refractory period and synaptic delay cannot be negative")
        if parameters["voltage_min"] >= parameters["voltage_max"]:
            raise ValueError("Voltage clamp bounds must be ordered")
        if parameters["spike_weight"] < 0 or parameters["poisson_factor"] < 0:
            raise ValueError("Input amplitudes must be nonnegative")
        self.delay_steps = self._steps(parameters["synaptic_delay"], "synaptic_delay")
        # Brian's timestep helper adds 0.001*dt before truncating to int64.
        self.default_refractory_steps = int((float(parameters["refractory"]) + .001 * self.dt) / self.dt)
        self.record_stride = self._steps(parameters.get("record_dt_ms", 1.0), "record_dt_ms")
        if self.record_stride < 1:
            raise ValueError("record_dt_ms must be at least dt")
        self.decay_v = np.exp(-self.dt / parameters["tau_membrane"])
        self.decay_g = np.exp(-self.dt / parameters["tau_synapse"])
        if integrator == "exponential_euler":
            self.coupling = 1.0 - self.decay_v
        else:
            tm, ts = parameters["tau_membrane"], parameters["tau_synapse"]
            self.coupling = ((self.dt / tm) * self.decay_v if tm == ts else
                             ts / (ts - tm) * (self.decay_g - self.decay_v))
        check_memory()
        csc = sparse.csc_matrix(weights, dtype=np.float32, copy=True)
        csc.sum_duplicates()
        csc.eliminate_zeros()
        csc.sort_indices()
        if not np.all(np.isfinite(csc.data)):
            raise ValueError("weights contain non-finite signed counts")
        if csc.nnz >= np.iinfo(np.int32).max or self.n_neurons >= np.iinfo(np.int32).max:
            raise ValueError("Connectome exceeds int32 sparse-index capacity")
        self.csc_indptr = csc.indptr.astype(np.int32, copy=False)
        self.csc_indices = csc.indices.astype(np.int32, copy=False)
        self.csc_counts = csc.data
        self.reset()
        check_memory()

    def _steps(self, duration, label):
        duration = float(duration)
        if not np.isfinite(duration) or duration < 0:
            raise ValueError(f"{label} must be nonnegative and finite")
        steps = int(round(duration / self.dt))
        if not np.isclose(steps * self.dt, duration, rtol=0, atol=1e-9):
            raise ValueError(f"{label} must be an exact multiple of dt")
        return steps

    def reset(self):
        self.v = np.full(self.n_neurons, self.parameters["v_rest"], dtype=np.float64)
        self.g = np.zeros(self.n_neurons, dtype=np.float64)
        self.last_spike = np.full(self.n_neurons, -10**12, dtype=np.int64)
        self.refractory_steps = np.full(self.n_neurons, self.default_refractory_steps, dtype=np.int64)
        self.active = np.ones(self.n_neurons, dtype=np.bool_)
        self.firing = np.zeros(self.n_neurons, dtype=np.bool_)
        self.ring = np.empty((self.delay_steps + 1, self.n_neurons), dtype=np.int32)
        self.ring_counts = np.zeros(self.delay_steps + 1, dtype=np.int32)
        self.step = 0
        self.clamp_count = 0
        self.last_result = None
        self.partial_result = None

    def run(self, duration_ms, input_neurons, input_events, record_indices=None, chunk_ms=100):
        n_steps = self._steps(duration_ms, "duration_ms")
        chunk_steps = self._steps(chunk_ms, "chunk_ms")
        if chunk_steps < 1:
            raise ValueError("chunk_ms must be at least dt")
        inputs = _integer_array(input_neurons, "input_neurons")
        if np.any(inputs < 0) or np.any(inputs >= self.n_neurons) or len(np.unique(inputs)) != len(inputs):
            raise ValueError("input_neurons must be unique valid neuron indices")
        inputs = inputs.astype(np.int32)
        events = _integer_array(input_events, "input_events", ndim=2)
        if events.shape[1] != 2:
            raise ValueError("input_events must have columns [step, input index]")
        if len(events) and (np.any(events[:, 0] < 0) or np.any(events[:, 0] >= n_steps)
                            or np.any(events[:, 1] < 0) or np.any(events[:, 1] >= len(inputs))):
            raise ValueError("Input event step or input index is out of bounds")
        if len(events):
            events = events[np.lexsort((events[:, 1], events[:, 0]))]
        records = _integer_array([] if record_indices is None else record_indices, "record_indices")
        if np.any(records < 0) or np.any(records >= self.n_neurons):
            raise ValueError("record_indices contains an invalid neuron")
        records = records.astype(np.int32)
        self.refractory_steps.fill(self.default_refractory_steps)
        self.refractory_steps[inputs] = 0
        start, end = self.step, self.step + n_steps
        event_steps = events[:, 0] + start
        event_inputs = events[:, 1].astype(np.int32)
        record_steps = np.arange(((start + self.record_stride - 1) // self.record_stride) * self.record_stride,
                                 end, self.record_stride, dtype=np.int64)
        voltages = np.empty((len(record_steps), len(records)), dtype=np.float32)
        spike_arrays, time_arrays = [], []
        event_position = 0
        clamp_start = self.clamp_count
        wall_start = time.perf_counter()
        self.partial_result = None
        old_threads = nb.get_num_threads()
        nb.set_num_threads(self.threads)

        def snapshot(complete):
            captured = int(np.searchsorted(record_steps, self.step, side="left"))
            return {
                "spike_indices": np.concatenate(spike_arrays) if spike_arrays else np.empty(0, np.int32),
                "spike_times": np.concatenate(time_arrays) if time_arrays else np.empty(0, np.float32),
                "voltages": voltages[:captured],
                "voltage_times": (record_steps[:captured] * self.dt).astype(np.float32),
                "record_indices": records,
                "clamp_count": self.clamp_count - clamp_start,
                "wall_seconds": time.perf_counter() - wall_start,
                "completed": complete,
                "simulated_ms": (self.step - start) * self.dt,
                "integrator": self.integrator,
                "dt_ms": self.dt,
                "threads": self.threads,
            }

        try:
            check_memory()
            for chunk_start in range(start, end, chunk_steps):
                chunk_end = min(chunk_start + chunk_steps, end)
                indices, steps, event_position, clamps = _advance(
                    self.v, self.g, self.last_spike, self.refractory_steps, self.active, self.firing,
                    self.ring, self.ring_counts, self.csc_indptr, self.csc_indices, self.csc_counts,
                    chunk_start, chunk_end, self.dt, self.delay_steps, self.decay_v, self.decay_g,
                    self.coupling, self.parameters["v_rest"], self.parameters["v_reset"],
                    self.parameters["v_threshold"], self.parameters["spike_weight"],
                    self.parameters["spike_weight"] * self.parameters["poisson_factor"], inputs,
                    event_steps, event_inputs, event_position, self.clamp,
                    self.parameters["voltage_min"], self.parameters["voltage_max"], records,
                    self.record_stride, (start + self.record_stride - 1) // self.record_stride, voltages)
                self.step = chunk_end
                self.clamp_count += clamps
                spike_arrays.append(indices)
                time_arrays.append((steps * self.dt).astype(np.float32))
                check_memory()
            self.last_result = snapshot(True)
            return self.last_result
        except BaseException:
            self.last_result = snapshot(False)
            self.partial_result = self.last_result | {
                "checkpoint_v": self.v,
                "checkpoint_g": self.g,
                "checkpoint_last_spike": self.last_spike,
                "checkpoint_ring": self.ring,
                "checkpoint_ring_counts": self.ring_counts,
                "checkpoint_step": self.step,
            }
            raise
        finally:
            nb.set_num_threads(old_threads)
