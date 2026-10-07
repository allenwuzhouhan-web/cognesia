"""Compact receptor groups in the validated base LIF event schedule.

Every edge keeps its original signed count and identity. Only the release factor
lookup differs from receptor_engine._advance_receptors; equality is tested.
"""
import numba as nb
from numba.typed import List
import numpy as np

@nb.njit(cache=True, parallel=False, fastmath=False)
def advance_compact(v, g, last_spike, refractory_steps, active, firing,
             ring, ring_counts, csc_indptr, csc_indices, csc_counts,
             start, stop, dt, delay_steps, decay_v, decay_g, coupling,
             rest, reset, threshold, weight, input_amplitude, input_neurons,
             event_steps, event_inputs, event_position, clamp, minimum, maximum,
             record_indices, record_stride, record_start, voltages, gain, release_factor, release_group,
             voltage_diagnostics):
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
                voltage_diagnostics[0] = min(voltage_diagnostics[0], updated)
                voltage_diagnostics[1] = max(voltage_diagnostics[1], updated)
                if updated < minimum or updated > maximum:
                    voltage_diagnostics[2] += 1
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
                    g[post] += csc_counts[edge] * weight * release_factor[release_group[edge]]
        ring_counts[current] = 0

        while event_position < len(event_steps) and event_steps[event_position] == step:
            neuron = input_neurons[event_inputs[event_position]]
            if active[neuron]:
                updated = v[neuron] + input_amplitude * gain[neuron]
                voltage_diagnostics[0] = min(voltage_diagnostics[0], updated)
                voltage_diagnostics[1] = max(voltage_diagnostics[1], updated)
                if updated < minimum or updated > maximum:
                    voltage_diagnostics[2] += 1
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
