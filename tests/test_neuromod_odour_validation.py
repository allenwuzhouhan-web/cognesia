"""Window semantics and unchanged-engine delivery for the biology experiment."""
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from flybrain.engine import LIFEngine
from flybrain.neuromod.odour import OdourLibrary, ALIASES
from flybrain.neuromod.odour_validation import (
    PROTOCOL, core_orn_indices, integer_steps, protocol_hash, run_core_protocol,
    source_event_log, voltage_metrics, window_counts,
)


def fixture_inputs():
    neurons = pd.DataFrame({"root_id": [100, 200, 300],
                            "cell_type": ["ORN_DM1", "KCg", "MBON01"],
                            "cell_class": ["olfactory", "KC", "MBON"],
                            "super_class": ["sensory", "central", "central"]})
    response = pd.DataFrame({"Or42b": [.1, .8]}, index=["SFR", ALIASES["OCT"]])
    mapping = pd.DataFrame({"code": ["DM1"], "receptor": ["Or42b"], "glomerulus": ["DM1"], "comment": [None]})
    odors = pd.DataFrame({"InChIKey": ["SFR", ALIASES["OCT"]], "Name": ["sfr", "3-octanol"], "CAS": ["SFR", "589-98-0"]})
    library = OdourLibrary(neurons, response, mapping, odors)
    core = SimpleNamespace(neurons=neurons, model_indices=np.arange(3, dtype=np.int32),
                           counts=sparse.csr_matrix(np.array([[0, 0, 0], [20, 0, 0], [0, 10, 0]], dtype=np.float32)),
                           metadata={"kc_kc_mode": "thresholded", "fixture": True})
    # Numerical fixture values only, not production physiology or biological tuning.
    p = {"dt": 1., "v_rest": -60., "v_reset": -60., "v_threshold": -50.,
         "tau_membrane": 10., "tau_synapse": 5., "refractory": 2., "synaptic_delay": 1.,
         "spike_weight": 1., "poisson_factor": 30., "voltage_min": -100., "voltage_max": 0.}
    op = {"odour_max_rate_hz": 1000., "odour_adaptation_tau_ms": 200.,
          "odour_transduction_tau_ms": 12., "odour_half_saturation": .2,
          "odour_adaptation_strength": .5, "odour_baseline_mode": "source_sfr"}
    protocol = PROTOCOL | {"baseline_ms": 20., "baseline_measurement_ms": 10., "stimulus_ms": 40.,
                           "recovery_ms": 20., "chunk_ms": 10.}
    return core, library, p, op, protocol


def test_window_half_open_and_fraction_is_observed_spikes():
    counts, rates = window_counts(np.array([0, 1, 2, 0]), np.array([9., 10., 19., 20.]), 3, 10, 20)
    np.testing.assert_array_equal(counts, [0, 1, 1])
    np.testing.assert_array_equal(rates, [0, 100, 100])
    with pytest.raises(ValueError):
        window_counts(np.array([3]), np.array([1.]), 3, 0, 10)


def test_core_orn_mapping_is_by_actual_model_order():
    np.testing.assert_array_equal(core_orn_indices([8, 2, 5], [5, 8]), [2, 0])
    with pytest.raises(ValueError):
        core_orn_indices([8, 2, 5], [1])
    with pytest.raises(ValueError):
        core_orn_indices([8, 8], [8])


def test_voltage_violations_are_not_clamp_counts():
    result = voltage_metrics(np.array([[-101., -60.], [0., np.nan], [np.inf, -50.]]), -100, -40)
    assert result["out_of_bound_samples"] == 2
    assert result["nonfinite_samples"] == 2
    np.testing.assert_array_equal(result["out_of_bound_counts"], [2, 0])
    assert result["minimum_sample_mV"] == -101
    assert result["maximum_sample_mV"] == 0
    assert "clamp_events" not in result


def test_protocol_hash_and_integer_grid():
    assert protocol_hash(PROTOCOL) == protocol_hash(dict(reversed(list(PROTOCOL.items()))))
    assert protocol_hash(PROTOCOL) != protocol_hash(PROTOCOL | {"seed": 784})
    assert integer_steps(1000, .1) == 10000
    with pytest.raises(ValueError):
        integer_steps(1.5, 1)


def test_event_log_determinism_and_baseline_mode():
    _, library, p, op, protocol = fixture_inputs()
    first = source_event_log(library, "OCT", op, p["dt"], protocol)
    second = source_event_log(library, "OCT", op, p["dt"], protocol)
    for a, b in zip(first, second):
        np.testing.assert_array_equal(a, b)
    assert len(first[0]) > 0
    assert first[0][:, 0].min() >= 0 and first[0][:, 0].max() < 80
    with pytest.raises(ValueError, match="source_sfr"):
        source_event_log(library, "OCT", op | {"odour_baseline_mode": "zero"}, p["dt"], protocol)


def test_chunked_experiment_matches_single_unchanged_lif_run(tmp_path):
    core, library, p, op, protocol = fixture_inputs()
    result = run_core_protocol(core, library, "OCT", p, op, tmp_path, protocol)
    with np.load(tmp_path / "odour_sparseness_OCT_activity.npz", allow_pickle=False) as saved:
        direct = LIFEngine(core.counts, p | {"record_dt_ms": p["dt"]}, threads=1, clamp=False)
        direct_result = direct.run(80, saved["input_core_indices"], saved["source_events"], record_indices=[0, 1, 2], chunk_ms=80)
        np.testing.assert_array_equal(saved["spike_indices"], direct_result["spike_indices"])
        np.testing.assert_array_equal(saved["spike_times_ms"], direct_result["spike_times"])
        np.testing.assert_array_equal(saved["final_v"], direct.v)
        np.testing.assert_array_equal(saved["final_g"], direct.g)
        assert saved["source_rates_hz"].shape == (8, 1)
        assert len(saved["spike_indices"]) > 0
    assert result["completed"]
    assert result["numerics"]["clamp_enabled"] is False
    assert result["numerics"]["clamp_events"] == 0
    table = pd.read_csv(tmp_path / "odour_sparseness_OCT_neurons.csv")
    assert result["kc_active_fraction"] == float((table.loc[table.cell_type=='KCg', 'stimulus_spikes'] > 0).mean())
    assert result["kc_active_fraction"] in {0, 1}  # one-KC fixture cannot satisfy 2–12% gate
    assert result["status"] == "FAIL"
