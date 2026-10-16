"""Read-only streaming instrumentation around the inherited checked equations.

The physical arithmetic and scheduling order match paralimbo_upgrade.runtime.
Accumulator updates cannot affect neuron state. Signed forcing sums are actual
model synaptic-state increments in mV, NOT charge or physical conductance.
No time-by-edge or time-by-population matrix is allocated.
"""
from __future__ import annotations
import numpy as np
import numba as nb
from numba.typed import List

STAT_NAMES = ("peak_abs_delta_v_mv", "sum_square_delta_v_mv2", "sum_delta_v_mv",
    "graded_positive_forcing_mv", "graded_negative_forcing_mv",
    "spike_positive_forcing_mv", "spike_negative_forcing_mv", "reserved",
    "applied_external_input_mv_ms", "requested_external_input_mv_ms",
    "release_mv_ms", "minimum_spike_threshold_margin_mv", "peak_abs_delta_g_mv",
    "sum_abs_delta_g_mv", "pre_reset_peak_abs_delta_v_mv")
COUNT_NAMES = ("sampled_steps", "refractory_steps", "release_active_steps", "spikes",
    "delivered_spike_edges", "rejected_refractory_spike_edges", "queued_spikes", "arrived_spikes")

@nb.njit(cache=True, parallel=True, fastmath=False)
def advance_instrumented(v, g, graded, last_spike, refractory_steps, active, firing,
                    spike_ring, spike_ring_counts, release_history, clamp_counts,
                    graded_indptr, graded_indices, graded_counts,
                    spike_indptr, spike_indices, spike_counts,
                    start, stop, run_start, delay_steps, decay_v, decay_g,
                    synaptic_forcing_scale, rest, release_threshold, gain,
                    reset, threshold, spike_weight, minimum, maximum,
                    photo_map, photo_drive, drive_mode, records, record_stride,
                    record_start, voltages, boundary_graded, boundary_spikes, output_enabled, faults, baseline_v, baseline_g, stats, counts, first, response_threshold, dt_ms, source_groups, target_slots, pool_forcing,
                    graded_pair_ids, spike_pair_ids, pair_forcing):
    output_indices = List.empty_list(nb.int32)
    output_steps = List.empty_list(nb.int64)
    n = len(v)
    for step in range(start, stop):
        for neuron in nb.prange(n):
            if not np.isfinite(v[neuron]):
                faults[neuron, 0] += 1
            if not np.isfinite(g[neuron]):
                faults[neuron, 1] += 1
        for neuron in nb.prange(n):
            delta = v[neuron] - baseline_v[neuron]
            dg = g[neuron] - baseline_g[neuron]
            stats[neuron, 0] = max(stats[neuron, 0], abs(delta))
            stats[neuron, 1] += delta * delta
            stats[neuron, 2] += delta
            stats[neuron, 12] = max(stats[neuron, 12], abs(dg))
            stats[neuron, 13] += abs(dg)
            counts[neuron, 0] += 1
            if abs(delta) >= response_threshold and first[neuron, 0] < 0:
                first[neuron, 0] = step
            if not graded[neuron]:
                stats[neuron, 11] = min(stats[neuron, 11], threshold - v[neuron])
            photo = photo_map[neuron]
            if photo >= 0:
                requested = photo_drive[0, 0] if drive_mode == 0 else photo_drive[step-run_start, 0] if drive_mode == 1 else photo_drive[step-run_start, photo]
                stats[neuron, 9] += requested * dt_ms
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
            release = release_history[history_now, neuron]
            stats[neuron, 10] += release * dt_ms
            if release > 0.0:
                counts[neuron, 2] += 1
        history_delayed = (step - delay_steps) % len(release_history)

        for neuron in nb.prange(n):
            thread = nb.get_thread_id()
            eligible = graded[neuron] or step - last_spike[neuron] >= refractory_steps[neuron]
            active[neuron] = eligible
            firing[neuron] = False
            if not eligible:
                counts[neuron, 1] += 1
            if eligible:
                # Row ownership and fixed edge order keep sums deterministic.
                release_sum = 0.0
                for edge in range(graded_indptr[neuron], graded_indptr[neuron + 1]):
                    pre = graded_indices[edge]
                    release_sum += graded_counts[edge] * release_history[history_delayed, pre]
                    contribution = synaptic_forcing_scale[neuron] * gain * (graded_counts[edge] * release_history[history_delayed, pre])
                    if contribution >= 0.0:
                        stats[neuron, 3] += contribution
                    else:
                        stats[neuron, 4] += contribution
                    pair_forcing[thread, graded_pair_ids[edge], 0 if contribution >= 0.0 else 1] += contribution
                    slot = target_slots[neuron]
                    if slot >= 0:
                        pool_forcing[slot, source_groups[pre], 0 if contribution >= 0.0 else 1] += contribution
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
                stats[neuron, 8] += current * dt_ms
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
                stats[neuron, 14] = max(stats[neuron, 14], abs(updated - baseline_v[neuron]))
                stats[neuron, 0] = max(stats[neuron, 0], abs(updated - baseline_v[neuron]))
                if abs(updated - baseline_v[neuron]) >= response_threshold and first[neuron, 0] < 0:
                    first[neuron, 0] = step + 1
                if not graded[neuron]:
                    stats[neuron, 11] = min(stats[neuron, 11], threshold - updated)
                if not graded[neuron] and updated > threshold:
                    firing[neuron] = True
                    active[neuron] = False
                    last_spike[neuron] = step

        future = (step + delay_steps) % len(spike_ring_counts)
        count = 0
        emitted_start = len(output_indices)
        for neuron in range(n):
            if firing[neuron]:
                counts[neuron, 3] += 1
                if first[neuron, 1] < 0:
                    first[neuron, 1] = step
                if output_enabled[neuron]:
                    counts[neuron, 6] += 1
                    spike_ring[future, count] = neuron
                    count += 1
                output_indices.append(np.int32(neuron))
                output_steps.append(np.int64(step))
        spike_ring_counts[future] = count
        current = step % len(spike_ring_counts)
        for j in range(spike_ring_counts[current]):
            pre = spike_ring[current, j]
            counts[pre, 7] += 1
            for edge in range(spike_indptr[pre], spike_indptr[pre + 1]):
                post = spike_indices[edge]
                if active[post]:
                    g[post] += spike_counts[edge] * spike_weight
                    counts[post, 4] += 1
                    contribution = spike_counts[edge] * spike_weight
                    stats[post, 5 if contribution >= 0.0 else 6] += contribution
                    pair_forcing[0, spike_pair_ids[edge], 0 if contribution >= 0.0 else 1] += contribution
                    slot = target_slots[post]
                    if slot >= 0:
                        pool_forcing[slot, source_groups[pre], 0 if contribution >= 0.0 else 1] += contribution
                else:
                    counts[post, 5] += 1
        spike_ring_counts[current] = 0
        if boundary_spikes.shape[0]:
            for neuron in nb.prange(n):
                if active[neuron]:
                    g[neuron] += boundary_spikes[step - run_start, neuron]
        # Inspect before spike reset can erase an overflowing synaptic update.
        for neuron in nb.prange(n):
            stats[neuron, 12] = max(stats[neuron, 12], abs(g[neuron] - baseline_g[neuron]))
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
