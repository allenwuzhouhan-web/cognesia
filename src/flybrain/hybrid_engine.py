"""Uniform graded/spiking dynamics with a shared exact-delay timestep.

Implements the explicit normalized equations in DESIGN_NOTES.md.  Graded
release is tonic below rest and is never subtracted or silenced for stability.
The requested dt_graded is an upper bound; all states use the finer dt so the
1.8-ms delay requires neither interpolation nor rounded arrival times.
"""
from __future__ import annotations

import time

import numba as nb
from numba.typed import List
import numpy as np
from scipy import sparse

from .engine import LIFEngine, _integer_array
from .memguard import check_memory


@nb.njit(cache=True, parallel=True, fastmath=False)
def _advance_hybrid(v, g, graded, last_spike, refractory_steps, active, firing,
                    spike_ring, spike_ring_counts, release_history, clamp_counts,
                    graded_indptr, graded_indices, graded_counts,
                    spike_indptr, spike_indices, spike_counts,
                    start, stop, run_start, delay_steps, decay_v, decay_g,
                    synaptic_forcing_scale, rest, release_threshold, gain,
                    reset, threshold, spike_weight, minimum, maximum,
                    photo_map, photo_drive, drive_mode, records, record_stride,
                    record_start, voltages, boundary_graded, boundary_spikes, output_enabled):
    output_indices = List.empty_list(nb.int32)
    output_steps = List.empty_list(nb.int64)
    n = len(v)
    for step in range(start, stop):
        if step % record_stride == 0:
            row = step // record_stride - record_start
            for j in range(len(records)):
                voltages[row, j] = v[records[j]]

        # Snapshot release before ANY neuron is advanced, including delay=0.
        history_now = step % len(release_history)
        for neuron in nb.prange(n):
            release_history[history_now, neuron] = max(0.0, v[neuron] - release_threshold) if graded[neuron] and output_enabled[neuron] else 0.0
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
        for neuron in nb.prange(n):
            if firing[neuron]:
                v[neuron] = reset
                g[neuron] = 0.0
    return np.asarray(output_indices), np.asarray(output_steps)


class HybridEngine(LIFEngine):
    """Passive graded neurons plus source-compatible LIF neurons.

    ``photoreceptor_drive`` is an additive normalized membrane input, in mV,
    NOT an imposed voltage. It can be a scalar constant, a full-field series
    ``[n_steps]``, or individual drive ``[n_steps, n_photoreceptors]``. Only the
    provided graded photoreceptor indices receive it. No provided drive means
    zero external input everywhere, while tonic synaptic release remains active.

    The explicit ``membrane_input_indices/drive`` path permits virtual electrodes
    on graded or spiking neurons. It is mutually exclusive with the optical-only
    API; callers must sum any overlapping optical/electrode input. Refractory
    eligibility and all intrinsic dynamics remain unchanged.

    Requested voltage recordings follow the same start-slot, 1-kHz convention
    as LIFEngine. Live state supports continuation; reset restarts history at the
    initial resting voltages, including their tonic transmitter release.
    """

    def __init__(self, graded_counts, spiking_counts, graded_mask, parameters,
                 dt=None, threads=16):
        self.graded_mask = np.asarray(graded_mask)
        if self.graded_mask.ndim != 1 or self.graded_mask.dtype != np.bool_:
            raise ValueError("graded_mask must be a one-dimensional boolean array")
        self.graded_mask = self.graded_mask.copy()
        self.output_enabled = np.ones(len(self.graded_mask), dtype=np.bool_)
        if (not sparse.issparse(graded_counts) or not sparse.issparse(spiking_counts)
                or graded_counts.shape != spiking_counts.shape
                or graded_counts.shape != (len(self.graded_mask), len(self.graded_mask))):
            raise ValueError("Mode matrices must be square and match graded_mask")
        for key in ("graded_tau_membrane", "graded_tau_synapse", "graded_rest", "graded_release", "graded_gain", "dt_graded"):
            if not np.isfinite(float(parameters[key])):
                raise ValueError(f"{key} must be finite")
        if parameters["graded_tau_membrane"] <= 0 or parameters["graded_tau_synapse"] <= 0:
            raise ValueError("Graded time constants must be positive")
        if parameters["graded_gain"] < 0:
            raise ValueError("graded_gain must be nonnegative")
        actual_dt = float(parameters["dt"] if dt is None else dt)
        if actual_dt > parameters["dt_graded"]:
            raise ValueError("Common integration dt exceeds requested dt_graded upper bound")
        if actual_dt > min(parameters["graded_tau_membrane"], parameters["graded_tau_synapse"]):
            raise ValueError("Integration dt exceeds the minimum graded time constant")
        graded_csr = sparse.csr_matrix(graded_counts, dtype=np.float32, copy=True)
        graded_csr.sum_duplicates()
        graded_csr.eliminate_zeros()
        graded_csr.sort_indices()
        if not np.all(np.isfinite(graded_csr.data)):
            raise ValueError("Graded counts contain non-finite values")
        if np.any(~self.graded_mask[graded_csr.indices]):
            raise ValueError("graded_counts has a spiking presynaptic column")
        spike_coo = spiking_counts.tocoo(copy=False)
        if np.any(self.graded_mask[spike_coo.col]):
            raise ValueError("spiking_counts has a graded presynaptic column")
        del spike_coo
        self.graded_indptr = graded_csr.indptr.astype(np.int32, copy=False)
        self.graded_indices = graded_csr.indices.astype(np.int32, copy=False)
        self.graded_counts = graded_csr.data
        super().__init__(spiking_counts, parameters, dt=dt, threads=threads, clamp=True)
        self.rest = np.where(self.graded_mask, parameters["graded_rest"], parameters["v_rest"])
        self.tau_membrane = np.where(self.graded_mask, parameters["graded_tau_membrane"], parameters["tau_membrane"])
        self.tau_synapse = np.where(self.graded_mask, parameters["graded_tau_synapse"], parameters["tau_synapse"])
        self.decay_v_each = np.exp(-self.dt / self.tau_membrane)
        self.decay_g_each = np.exp(-self.dt / self.tau_synapse)
        self.forcing_scale = self.tau_synapse * (1.0 - self.decay_g_each)

    def reset(self):
        super().reset()
        self.v[self.graded_mask] = self.parameters["graded_rest"]
        initial_release = np.where(self.graded_mask, np.maximum(0., self.v - self.parameters["graded_release"]), 0.)
        self.release_history = np.tile(initial_release, (self.delay_steps + 1, 1))
        self.per_neuron_clamp_counts = np.zeros(self.n_neurons, dtype=np.int64)

    def run(self, duration_ms, record_indices=None, photoreceptor_indices=None,
            photoreceptor_drive=None, chunk_ms=100, *, membrane_input_indices=None,
            membrane_input_drive=None, boundary_graded_release=None,
            boundary_spike_delta=None, record_dtype=np.float32):
        n_steps = self._steps(duration_ms, "duration_ms")
        boundary_arrays = []
        for name, value in (("boundary_graded_release", boundary_graded_release),
                            ("boundary_spike_delta", boundary_spike_delta)):
            array = np.empty((0, 0), dtype=np.float64) if value is None else np.asarray(value, dtype=np.float64)
            if value is not None and (array.shape != (n_steps, self.n_neurons) or not np.isfinite(array).all()):
                raise ValueError(name + " must contain finite [integration steps, selected neurons] samples")
            boundary_arrays.append(array)
        chunk_steps = self._steps(chunk_ms, "chunk_ms")
        if chunk_steps < 1:
            raise ValueError("chunk_ms must be at least dt")
        general_input = membrane_input_indices is not None or membrane_input_drive is not None
        if general_input:
            if photoreceptor_indices is not None or photoreceptor_drive is not None:
                raise ValueError('Use either photoreceptor input or combined membrane input, not both')
            photoreceptor_indices, photoreceptor_drive = membrane_input_indices, membrane_input_drive
        photos = _integer_array([] if photoreceptor_indices is None else photoreceptor_indices, "photoreceptor_indices")
        if (np.any(photos < 0) or np.any(photos >= self.n_neurons)
                or len(np.unique(photos)) != len(photos)):
            raise ValueError("photoreceptor_indices must be unique valid indices")
        if not general_input and np.any(~self.graded_mask[photos]):
            raise ValueError("Photoreceptor input must target graded neurons")
        photo_map = np.full(self.n_neurons, -1, dtype=np.int32)
        photo_map[photos] = np.arange(len(photos), dtype=np.int32)
        drive = np.asarray(0. if photoreceptor_drive is None else photoreceptor_drive, dtype=np.float64)
        if not np.all(np.isfinite(drive)):
            raise ValueError("photoreceptor_drive contains non-finite input")
        if not len(photos) and np.any(drive):
            raise ValueError("Nonzero photoreceptor_drive requires photoreceptor_indices")
        if drive.ndim == 0:
            drive_mode, drive = 0, drive.reshape(1, 1)
        elif drive.shape == (n_steps,):
            drive_mode, drive = 1, drive.reshape(n_steps, 1)
        elif drive.shape == (n_steps, len(photos)):
            drive_mode = 2
        else:
            raise ValueError("photoreceptor_drive must be scalar, [n_steps], or [n_steps,n_photoreceptors]")
        records = _integer_array([] if record_indices is None else record_indices, "record_indices")
        if np.any(records < 0) or np.any(records >= self.n_neurons):
            raise ValueError("record_indices contains an invalid neuron")
        records = records.astype(np.int32)
        start, end = self.step, self.step + n_steps
        record_start = (start + self.record_stride - 1) // self.record_stride
        record_steps = np.arange(record_start * self.record_stride, end, self.record_stride, dtype=np.int64)
        if np.dtype(record_dtype) not in (np.dtype('float32'), np.dtype('float64')):
            raise ValueError('Voltage recording dtype must be float32 or float64')
        voltages = np.empty((len(record_steps), len(records)), dtype=record_dtype)
        spike_arrays, time_arrays, chunk_timings = [], [], []
        initial_clamps = self.per_neuron_clamp_counts.copy()
        wall_start = time.perf_counter()
        old_threads = nb.get_num_threads()
        nb.set_num_threads(self.threads)
        self.partial_result = None

        def snapshot(complete):
            captured = np.searchsorted(record_steps, self.step, side="left")
            per_neuron_clamps = self.per_neuron_clamp_counts - initial_clamps
            external = np.zeros(self.n_neurons, dtype=np.float64)
            if len(photos) and self.step > start:
                row = 0 if drive_mode == 0 else self.step - start - 1
                external[photos] = drive[row, 0] if drive_mode < 2 else drive[row]
            derivative = (self.rest - self.v + self.g + external) / self.tau_membrane
            eligible = self.graded_mask | (self.step - self.last_spike >= self.refractory_steps)
            derivative[~eligible] = 0.
            return {"spike_indices": np.concatenate(spike_arrays) if spike_arrays else np.empty(0, np.int32),
                    "spike_times": np.concatenate(time_arrays) if time_arrays else np.empty(0, np.float32),
                    "voltages": voltages[:captured], "voltage_times": (record_steps[:captured] * self.dt).astype(np.float32),
                    "record_indices": records, "per_neuron_clamp_counts": per_neuron_clamps,
                    "clamp_count": int(per_neuron_clamps.sum()), "final_dvdt": derivative,
                    "max_abs_dvdt": float(np.max(np.abs(derivative))) if len(derivative) else 0.,
                    "final_v": self.v.copy(), "final_g": self.g.copy(),
                    "wall_seconds": time.perf_counter() - wall_start, "completed": complete,
                    "simulated_ms": (self.step - start) * self.dt, "integrator": "exponential_euler",
                    "dt_ms": self.dt, "actual_dt_graded_ms": self.dt,
                    "requested_dt_graded_ms": self.parameters["dt_graded"],
                    "graded_timestep_note": "Shared fine timestep exactly represents the configured synaptic delay; dt_graded is an upper bound.",
                    "threads": self.threads, "chunk_timings": chunk_timings,
                    "input_units": "mV additive normalized membrane current; never voltage clamping",
                    "input_kind": "combined optical/electrode input" if general_input else "graded photoreceptor input"}

        try:
            check_memory()
            for chunk_start in range(start, end, chunk_steps):
                chunk_end = min(chunk_start + chunk_steps, end)
                chunk_wall = time.perf_counter()
                indices, steps = _advance_hybrid(
                    self.v, self.g, self.graded_mask, self.last_spike, self.refractory_steps,
                    self.active, self.firing, self.ring, self.ring_counts, self.release_history,
                    self.per_neuron_clamp_counts, self.graded_indptr, self.graded_indices,
                    self.graded_counts, self.csc_indptr, self.csc_indices, self.csc_counts,
                    chunk_start, chunk_end, start, self.delay_steps, self.decay_v_each,
                    self.decay_g_each, self.forcing_scale, self.rest, self.parameters["graded_release"],
                    self.parameters["graded_gain"], self.parameters["v_reset"], self.parameters["v_threshold"],
                    self.parameters["spike_weight"], self.parameters["voltage_min"], self.parameters["voltage_max"],
                    photo_map, drive, drive_mode, records, self.record_stride, record_start, voltages,
                    boundary_arrays[0], boundary_arrays[1], self.output_enabled)
                self.step = chunk_end
                self.clamp_count = int(self.per_neuron_clamp_counts.sum())
                spike_arrays.append(indices)
                time_arrays.append((steps * self.dt).astype(np.float32))
                elapsed = time.perf_counter() - chunk_wall
                chunk_timings.append({"simulated_ms": (chunk_end - chunk_start) * self.dt,
                                      "wall_seconds": elapsed, "first_chunk_may_include_compilation": chunk_start == start})
                check_memory()
            self.last_result = snapshot(True)
            return self.last_result
        except BaseException:
            self.last_result = snapshot(False)
            self.partial_result = self.last_result | {
                "checkpoint_v": self.v, "checkpoint_g": self.g,
                "checkpoint_last_spike": self.last_spike,
                "checkpoint_ring": self.ring, "checkpoint_ring_counts": self.ring_counts,
                "checkpoint_release_history": self.release_history,
                "checkpoint_per_neuron_clamp_counts": self.per_neuron_clamp_counts,
                "checkpoint_step": self.step}
            raise
        finally:
            nb.set_num_threads(old_threads)
