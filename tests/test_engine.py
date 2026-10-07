import numpy as np
import pytest
from scipy import sparse

from flybrain.engine import LIFEngine
from flybrain.memguard import MemoryLimitExceeded


PARAMETERS = {
    "dt": .1, "v_rest": -52., "v_reset": -52., "v_threshold": -45.,
    "tau_membrane": 20., "tau_synapse": 5., "refractory": 2.2,
    "synaptic_delay": 1.8, "spike_weight": .275, "poisson_factor": 250.,
    "voltage_min": -90., "voltage_max": 20.,
}
EMPTY_INPUTS = np.empty(0, dtype=np.int32)
EMPTY_EVENTS = np.empty((0, 2), dtype=np.int64)


def make_engine(n=3, weights=None, **kwargs):
    p = PARAMETERS | kwargs.pop("parameters", {})
    return LIFEngine(sparse.csr_matrix((n, n)) if weights is None else weights,
                     p, threads=kwargs.pop("threads", 1), **kwargs)


def test_external_input_arrives_after_threshold_and_resets_g():
    engine = make_engine()
    result = engine.run(1., np.array([1], np.int32), np.array([[0, 0]]), record_indices=np.arange(3))
    assert result["spike_indices"].tolist() == [1]
    assert result["spike_times"].tolist() == [np.float32(.1)]
    assert engine.v[1] == -52.
    assert engine.g[1] == 0.
    assert result["clamp_count"] == 0
    assert result["voltages"].shape == (1, 3)
    assert result["voltage_times"].tolist() == [0.]


def test_synaptic_delay_and_continuation_are_exact():
    weights = sparse.csr_matrix(([1000.], ([1], [0])), shape=(2, 2))
    engine = make_engine(n=2, weights=weights, clamp=False)
    engine.v[0] = -44.
    first = engine.run(1.8, EMPTY_INPUTS, EMPTY_EVENTS)
    assert first["spike_times"].tolist() == [0.]
    assert engine.g[1] == 0.
    engine.run(.1, EMPTY_INPUTS, EMPTY_EVENTS)
    assert engine.g[1] == 275.
    assert engine.v[1] == -52.
    engine.run(.1, EMPTY_INPUTS, EMPTY_EVENTS)
    assert engine.g[1] == pytest.approx(275. * np.exp(-.1 / 5.))
    assert engine.v[1] > -52.


def test_refractory_g_is_frozen_and_incoming_synapses_are_ignored():
    weights = sparse.csr_matrix(([1000.], ([1], [0])), shape=(2, 2))
    engine = make_engine(n=2, weights=weights, clamp=False)
    engine.step = 1
    engine.last_spike[1] = 0
    engine.g[1] = 2.
    engine.v[0] = -44.
    engine.run(2., EMPTY_INPUTS, EMPTY_EVENTS)
    assert engine.g[1] == 2.
    assert engine.v[1] == -52.
    engine.run(.1, EMPTY_INPUTS, EMPTY_EVENTS)  # timestep 21, still refractory
    assert engine.g[1] == 2.
    engine.run(.1, EMPTY_INPUTS, EMPTY_EVENTS)  # timestep 22, eligible
    assert engine.g[1] < 2.
    assert engine.v[1] > -52.


@pytest.mark.parametrize("tau_synapse", [5., 20.])
def test_exact_integrator_matches_analytic_linear_solution(tau_synapse):
    engine = make_engine(n=1, integrator="exact_linear", clamp=False,
                         parameters={"tau_synapse": tau_synapse, "v_threshold": 100.})
    engine.v[0] = -50.
    engine.g[0] = 3.
    engine.run(10., EMPTY_INPUTS, EMPTY_EVENTS)
    a, b = np.exp(-10. / 20.), np.exp(-10. / tau_synapse)
    coupling = (10. / 20.) * a if tau_synapse == 20. else tau_synapse / (tau_synapse - 20.) * (b - a)
    assert engine.v[0] == pytest.approx(-52. + 2 * a + 3 * coupling, abs=1e-11)
    assert engine.g[0] == pytest.approx(3 * b, abs=1e-12)


def test_no_spikes_or_drift_without_any_input():
    engine = make_engine(n=4)
    result = engine.run(3., EMPTY_INPUTS, EMPTY_EVENTS, record_indices=np.arange(4))
    assert len(result["spike_indices"]) == 0
    np.testing.assert_array_equal(result["voltages"], -52 * np.ones((3, 4)))
    assert result["completed"]
    assert result["simulated_ms"] == 3.


def test_thread_count_does_not_change_spikes_or_state():
    rng = np.random.default_rng(3)
    weights = sparse.csr_matrix(rng.integers(-100, 250, (30, 30)).astype(np.float32))
    events = np.array([[0, 0], [13, 1], [25, 0], [38, 1], [70, 0]])
    a = make_engine(weights=weights, threads=1)
    b = make_engine(weights=weights, threads=2)
    results = [e.run(15., np.array([2, 8]), events, record_indices=np.arange(30)) for e in [a, b]]
    for key in ["spike_indices", "spike_times", "voltages"]:
        np.testing.assert_array_equal(results[0][key], results[1][key])
    np.testing.assert_array_equal(a.v, b.v)
    np.testing.assert_array_equal(a.g, b.g)


def test_split_run_preserves_pending_delays_and_record_phase():
    weights = sparse.csr_matrix(([1000.], ([1], [0])), shape=(2, 2))
    full = make_engine(weights=weights)
    split = make_engine(weights=weights)
    one = full.run(10., np.array([0]), np.array([[0, 0], [55, 0]]), record_indices=np.array([1]))
    two_a = split.run(4.3, np.array([0]), np.array([[0, 0]]), record_indices=np.array([1]))
    two_b = split.run(5.7, np.array([0]), np.array([[12, 0]]), record_indices=np.array([1]))
    for key in ["spike_indices", "spike_times", "voltages", "voltage_times"]:
        np.testing.assert_array_equal(one[key], np.concatenate([two_a[key], two_b[key]]))
    np.testing.assert_array_equal(full.v, split.v)
    np.testing.assert_array_equal(full.g, split.g)


def test_clamps_are_counted_and_invalid_events_fail_loudly():
    engine = make_engine(parameters={"poisson_factor": 500.})
    result = engine.run(.2, np.array([0]), np.array([[0, 0]]))
    assert result["clamp_count"] == 1
    with pytest.raises(ValueError, match="out of bounds"):
        engine.run(.2, np.array([0]), np.array([[2, 0]]))
    with pytest.raises(ValueError, match="exact integer"):
        engine.run(.2, np.array([0]), np.array([[.5, 0]]))


def test_more_than_one_step_of_spikes_has_no_fixed_event_cap():
    engine = make_engine(n=2)
    events = np.array([[step, input_id] for step in range(0, 100, 2) for input_id in range(2)])
    result = engine.run(10., np.array([0, 1]), events, chunk_ms=1.)
    assert len(result["spike_indices"]) == 100
    assert result["spike_indices"].dtype == np.int32
    assert result["spike_times"].dtype == np.float32


def test_cooperative_abort_preserves_completed_chunk_activity_and_state(monkeypatch):
    engine = make_engine(n=1)
    checks = 0

    def limit_after_first_chunk():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise MemoryLimitExceeded("test limit after completed chunk")

    monkeypatch.setattr("flybrain.engine.check_memory", limit_after_first_chunk)
    with pytest.raises(MemoryLimitExceeded):
        engine.run(10., np.array([0]), np.array([[0, 0]]), record_indices=np.array([0]), chunk_ms=1.)
    partial = engine.partial_result
    assert partial["completed"] is False
    assert partial["simulated_ms"] == 1.
    assert partial["spike_indices"].tolist() == [0]
    assert partial["voltages"].shape == (1, 1)
    assert partial["checkpoint_step"] == 10
    assert partial["checkpoint_v"] is engine.v
    assert partial["checkpoint_g"] is engine.g


def test_threshold_is_strict_and_zero_delay_still_requires_next_integration():
    engine = make_engine(n=1, parameters={"v_threshold": -52.})
    assert len(engine.run(.1, EMPTY_INPUTS, EMPTY_EVENTS)["spike_indices"]) == 0
    weights = sparse.csr_matrix(([1000.], ([1], [0])), shape=(2, 2))
    engine = make_engine(weights=weights, parameters={"synaptic_delay": 0.})
    engine.v[0] = -44.
    engine.run(.1, EMPTY_INPUTS, EMPTY_EVENTS)
    assert engine.v[1] == -52.
    assert engine.g[1] == 275.
    engine.run(.1, EMPTY_INPUTS, EMPTY_EVENTS)
    assert engine.v[1] > -52.
