"""All-LIF receptor adapter; the disabled path delegates unchanged base execution.

The active deterministic kernel retains the base scheduling but reads named
per-neuron gain/threshold/tau and per-CSC-edge release factors. Concentrations
never become an additive current. Call set_effects between dt_mod intervals to
couple evolving fields; effects are immutable during one run.
"""
from __future__ import annotations
import time

import numba as nb
from numba.typed import List
import numpy as np

from ..engine import LIFEngine, _integer_array
from ..memguard import check_memory

@nb.njit(cache=True, parallel=True, fastmath=False)
def _advance_receptors(v, g, last_spike, refractory_steps, active, firing,
             ring, ring_counts, csc_indptr, csc_indices, csc_counts,
             start, stop, dt, delay_steps, decay_v, decay_g, coupling,
             rest, reset, threshold, weight, input_amplitude, input_neurons,
             event_steps, event_inputs, event_position, clamp, minimum, maximum,
             record_indices, record_stride, record_start, voltages, gain, release_factor):
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
                updated = rest + (v[neuron] - rest) * decay_v[neuron] + coupling[neuron] * old_g * gain[neuron]
                if clamp:
                    if updated < minimum:
                        updated = minimum
                        clamp_count += 1
                    elif updated > maximum:
                        updated = maximum
                        clamp_count += 1
                v[neuron] = updated
                g[neuron] = old_g * decay_g
                if updated > threshold[neuron]:
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
                    g[post] += csc_counts[edge] * weight * release_factor[edge]
        ring_counts[current] = 0

        while event_position < len(event_steps) and event_steps[event_position] == step:
            neuron = input_neurons[event_inputs[event_position]]
            if active[neuron]:
                updated = v[neuron] + input_amplitude * gain[neuron]
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


class ReceptorLIFEngine(LIFEngine):
    def __init__(self, *args, enabled=False, model_root_ids=None, **kwargs):
        self.enabled = bool(enabled)
        self.effects = None
        self.nonfinite_state_events = 0
        self.model_root_ids = None if model_root_ids is None else np.asarray(model_root_ids).copy()
        if self.enabled and self.model_root_ids is None:
            raise ValueError("Active receptor engine requires explicit model_root_ids")
        if self.model_root_ids is not None and self.model_root_ids.dtype != np.int64:
            raise ValueError("Engine model root IDs must be exact int64 identities")
        super().__init__(*args, **kwargs)
        if self.model_root_ids is not None and self.model_root_ids.shape != (self.n_neurons,):
            raise ValueError("Engine model root IDs must match neuron count")

    def reset(self):
        super().reset()
        self.nonfinite_state_events = 0

    def set_effects(self, effects):
        n = self.n_neurons
        if self.model_root_ids is None:
            raise ValueError("Binding active effects requires explicit model_root_ids")
        for key in ("gain", "threshold_factor", "tau_factor"):
            array = np.asarray(getattr(effects, key))
            if array.shape != (n,) or not np.isfinite(array).all() or np.any(array < 0):
                raise ValueError(f"Invalid receptor parameter: {key}")
        if np.any(effects.tau_factor <= 0) or np.any(effects.threshold_factor <= 0):
            raise ValueError("Tau and threshold-distance factors must be positive")
        if (effects.release_factor.shape != self.csc_counts.shape
                or not np.isfinite(effects.release_factor).all() or np.any(effects.release_factor < 0)):
            raise ValueError("Invalid per-edge release factors")
        pres = np.repeat(np.arange(n, dtype=np.int32), np.diff(self.csc_indptr))
        if not np.array_equal(effects.edge_pre, pres) or not np.array_equal(effects.edge_post, self.csc_indices):
            raise ValueError("Receptor edge ordering differs from the engine CSC order")
        if self.model_root_ids is not None and not np.array_equal(effects.model_root_ids, self.model_root_ids):
            raise ValueError("Receptor model row ordering differs from the engine")
        self.effects = effects
        tau = self.parameters["tau_membrane"] * effects.tau_factor
        self.receptor_decay_v = np.exp(-self.dt / tau)
        if self.integrator == "exponential_euler":
            self.receptor_coupling = 1.0 - self.receptor_decay_v
        else:
            ts = self.parameters["tau_synapse"]
            # expm1(x)/x has a continuous limit of 1 at equal time constants.
            # Form x from the tau difference, avoiding cancellation of decays.
            x = (ts - tau) * self.dt / (tau * ts)
            ratio = np.ones(n, np.float64)
            unequal = x != 0
            ratio[unequal] = np.expm1(x[unequal]) / x[unequal]
            self.receptor_coupling = (self.dt / tau) * self.receptor_decay_v * ratio
        self.receptor_threshold = (self.parameters["v_rest"]
                                  + (self.parameters["v_threshold"] - self.parameters["v_rest"]) * effects.threshold_factor)
        if not all(np.isfinite(x).all() for x in (self.receptor_decay_v, self.receptor_coupling, self.receptor_threshold)):
            raise ValueError("Receptor transformation produced nonfinite parameters")

    def run(self, duration_ms, input_neurons, input_events, record_indices=None, chunk_ms=100):
        if not self.enabled:
            # Deliberately call the original implementation, including its validation,
            # scheduling, recording and continuation semantics.
            return super().run(duration_ms, input_neurons, input_events, record_indices, chunk_ms)
        if self.effects is None:
            raise ValueError("Active receptor engine requires explicit effect arrays")
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
                "receptor_guard_events": dict(self.effects.guard_events),
                "nonfinite_state_events": self.nonfinite_state_events,
                "receptor_effects": "frozen over this run; no additive current",
            }

        try:
            check_memory()
            for chunk_start in range(start, end, chunk_steps):
                chunk_end = min(chunk_start + chunk_steps, end)
                indices, steps, event_position, clamps = _advance_receptors(
                    self.v, self.g, self.last_spike, self.refractory_steps, self.active, self.firing,
                    self.ring, self.ring_counts, self.csc_indptr, self.csc_indices, self.csc_counts,
                    chunk_start, chunk_end, self.dt, self.delay_steps, self.receptor_decay_v, self.decay_g,
                    self.receptor_coupling, self.parameters["v_rest"], self.parameters["v_reset"],
                    self.receptor_threshold, self.parameters["spike_weight"],
                    self.parameters["spike_weight"] * self.parameters["poisson_factor"], inputs,
                    event_steps, event_inputs, event_position, self.clamp,
                    self.parameters["voltage_min"], self.parameters["voltage_max"], records,
                    self.record_stride, (start + self.record_stride - 1) // self.record_stride, voltages,
                    self.effects.gain, self.effects.release_factor)
                self.step = chunk_end
                self.clamp_count += clamps
                spike_arrays.append(indices)
                time_arrays.append((steps * self.dt).astype(np.float32))
                invalid = int((~np.isfinite(self.v)).sum() + (~np.isfinite(self.g)).sum())
                self.nonfinite_state_events += invalid
                if invalid:
                    raise FloatingPointError("Active receptor engine produced nonfinite state")
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
