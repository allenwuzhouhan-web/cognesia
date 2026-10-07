import numpy as np
import pytest
from scipy import sparse

from flybrain.engine import LIFEngine
from flybrain.hybrid_engine import HybridEngine
from flybrain.memguard import MemoryLimitExceeded


PARAMETERS = {
    "dt": .1, "dt_graded": .5, "v_rest": -52., "v_reset": -52., "v_threshold": -45.,
    "tau_membrane": 20., "tau_synapse": 5., "refractory": 2.2,
    "synaptic_delay": 1.8, "spike_weight": .275, "poisson_factor": 250.,
    "voltage_min": -90., "voltage_max": 20., "graded_tau_membrane": 20.,
    "graded_tau_synapse": 5., "graded_rest": -52., "graded_release": -54.,
    "graded_gain": .0001,
}


def engine(mask=(True, True), graded_edges=(), spiking_edges=(), threads=1, **overrides):
    def matrix(edges):
        rows, cols, values = zip(*edges) if edges else ([], [], [])
        return sparse.csr_matrix((values, (rows, cols)), shape=(len(mask), len(mask)))
    return HybridEngine(matrix(graded_edges), matrix(spiking_edges), np.array(mask, dtype=bool),
                        PARAMETERS | overrides, threads=threads)


def test_tonic_release_is_active_in_dark_and_has_consistent_units():
    e = engine(graded_edges=[(1, 0, 10.)])
    result = e.run(10., record_indices=np.array([0, 1]))
    expected = .0001 * 10 * 2 * 5 * (1 - np.exp(-10. / 5.))
    assert e.g[1] == pytest.approx(expected, abs=1e-12)
    assert e.v[0] == -52.
    assert e.v[1] > -52.
    assert len(result["spike_indices"]) == 0
    np.testing.assert_allclose(result["final_dvdt"], (-52 - e.v + e.g) / 20.)
    assert result["actual_dt_graded_ms"] == .1
    assert result["requested_dt_graded_ms"] == .5


def test_changed_graded_voltage_propagates_only_after_exact_delay():
    baseline = engine(graded_edges=[(1, 0, 10.)])
    changed = engine(graded_edges=[(1, 0, 10.)])
    changed.v[0] = -50.
    baseline.run(1.8)
    changed.run(1.8)
    assert baseline.g[1] == changed.g[1]
    baseline.run(.1)
    changed.run(.1)
    assert changed.g[1] - baseline.g[1] == pytest.approx(5 * (1 - np.exp(-.1 / 5)) * .0001 * 10 * 2)
    assert changed.v[1] == baseline.v[1]
    changed.run(.1)
    baseline.run(.1)
    assert changed.v[1] > baseline.v[1]


def test_graded_neurons_never_threshold_or_reset():
    e = engine(mask=(True,))
    e.v[0] = 10.
    r = e.run(1.)
    assert not len(r["spike_indices"])
    assert e.v[0] > 0.
    assert e.last_spike[0] == -10**12


def test_spikes_drive_graded_targets_after_delay():
    e = engine(mask=(False, True), spiking_edges=[(1, 0, 1000.)])
    e.v[0] = -44.
    r = e.run(1.8)
    assert r["spike_indices"].tolist() == [0]
    assert e.g[1] == 0.
    e.run(.1)
    assert e.g[1] == 275.
    assert e.v[1] == -52.
    e.run(1.)
    assert e.v[1] > -45.
    assert e.last_spike[1] == -10**12


def test_tonic_graded_input_can_drive_spiking_neurons_without_external_input():
    e = engine(mask=(True, False), graded_edges=[(1, 0, 20000.)])
    r = e.run(100.)
    assert len(r["spike_indices"]) > 0
    assert set(r["spike_indices"]) == {1}
    assert e.v[0] == -52.


def test_spiking_refractory_blocks_continuous_and_discrete_input():
    e = engine(mask=(True, False, False), graded_edges=[(1, 0, 1000.)],
               spiking_edges=[(1, 2, 1000.)])
    e.step = 1
    e.last_spike[1] = 0
    e.g[1] = 2.
    e.v[2] = -44.
    e.run(2.1)
    assert e.g[1] == 2.
    assert e.v[1] == -52.
    e.run(.1)
    assert e.g[1] != 2.


def test_all_spiking_limit_matches_validated_production_engine():
    e = engine(mask=(False, False), spiking_edges=[(1, 0, 1000.), (0, 1, 40.)])
    weights = sparse.csr_matrix(([1000., 40.], ([1, 0], [0, 1])), shape=(2, 2))
    reference = LIFEngine(weights, PARAMETERS, threads=1)
    e.v[0] = reference.v[0] = -44.
    a = e.run(30., record_indices=np.arange(2))
    b = reference.run(30., np.empty(0, np.int32), np.empty((0, 2), np.int64), record_indices=np.arange(2))
    for key in ("spike_indices", "spike_times", "voltages"):
        np.testing.assert_array_equal(a[key], b[key])
    np.testing.assert_array_equal(e.v, reference.v)
    np.testing.assert_array_equal(e.g, reference.g)


def test_photoreceptor_drive_is_passive_input_not_voltage_clamping():
    e = engine(mask=(True, False))
    e.run(.1, photoreceptor_indices=np.array([0]), photoreceptor_drive=20.)
    assert e.v[0] == pytest.approx(-52. + 20 * (1 - np.exp(-.1 / 20)))
    assert e.v[1] == -52.
    with pytest.raises(ValueError, match="graded"):
        e.run(.1, photoreceptor_indices=np.array([1]), photoreceptor_drive=20.)


def test_threads_and_split_runs_preserve_exact_spikes_and_voltages():
    a = engine(mask=(True, True, False), graded_edges=[(1, 0, -100.), (2, 1, 30000.)], threads=1)
    b = engine(mask=(True, True, False), graded_edges=[(1, 0, -100.), (2, 1, 30000.)], threads=2)
    full = a.run(20., record_indices=np.arange(3))
    parts = [b.run(4.3, record_indices=np.arange(3)), b.run(15.7, record_indices=np.arange(3))]
    for key in ("spike_indices", "spike_times", "voltages", "voltage_times"):
        np.testing.assert_array_equal(full[key], np.concatenate([p[key] for p in parts]))
    np.testing.assert_array_equal(a.v, b.v)
    np.testing.assert_array_equal(a.g, b.g)


def test_clamps_are_counted_per_neuron_and_do_not_mask_outward_derivatives():
    e = engine(mask=(True, True))
    r = e.run(100., photoreceptor_indices=np.array([0]), photoreceptor_drive=1000.)
    assert r["clamp_count"] > 0
    assert r["per_neuron_clamp_counts"][0] == r["clamp_count"]
    assert r["per_neuron_clamp_counts"][1] == 0
    assert r["final_dvdt"][0] > 1.


def test_abort_preserves_release_history_and_completed_chunk(monkeypatch):
    e = engine()
    checks = 0

    def check():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise MemoryLimitExceeded("test abort")

    monkeypatch.setattr("flybrain.hybrid_engine.check_memory", check)
    with pytest.raises(MemoryLimitExceeded):
        e.run(10., record_indices=np.arange(2), chunk_ms=1.)
    assert e.partial_result["simulated_ms"] == 1.
    assert e.partial_result["checkpoint_release_history"] is e.release_history
    assert e.partial_result["voltages"].shape == (1, 2)


def test_wrong_presynaptic_partition_is_rejected():
    with pytest.raises(ValueError, match="spiking presynaptic"):
        engine(mask=(False, True), graded_edges=[(1, 0, 10.)])
    with pytest.raises(ValueError, match="graded presynaptic"):
        engine(mask=(False, True), spiking_edges=[(0, 1, 10.)])
