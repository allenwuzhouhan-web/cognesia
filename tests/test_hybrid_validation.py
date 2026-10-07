"""Stage-4 gate analysis tests; no artificial fixture is used as model data."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from flybrain.validate_hybrid import class_spike_counts, summarize_endpoint


@pytest.fixture
def neurons():
    return pd.DataFrame({"root_id": [1, 2, 3, 4], "cell_type": ["Mi1", "Mi1", "DNa02", None],
                         "super_class": ["optic", "optic", "descending", "central"],
                         "mode": ["graded", "graded", "spiking", "spiking"]})


def test_stationarity_checks_both_modes_without_ignoring_spiking_cells(neurons):
    measured = summarize_endpoint(neurons, np.array([0.001, 0, -0.002, 0]), np.zeros(4), 0.001)
    assert not measured["stationary"]
    assert measured["unstable_neurons"] == 1
    assert measured["unstable_by_mode"] == {"graded": 0, "spiking": 1}
    assert measured["max_abs_dvdt_mV_per_ms"] == 0.002
    assert measured["affected_cell_types"][0]["cell_type"] == "DNa02"


def test_clamps_are_reported_even_if_endpoint_is_stationary(neurons):
    measured = summarize_endpoint(neurons, np.zeros(4), np.array([2, 7, 0, 3]), 0.001)
    assert measured["stationary"]
    assert measured["clamp_events"] == 12
    assert measured["clamped_neurons"] == 3
    mi1 = next(row for row in measured["affected_cell_types"] if row["cell_type"] == "Mi1")
    assert mi1["clamp_events"] == 9
    assert mi1["n_neurons"] == 2


def test_nan_derivative_cannot_pass_or_serialize_as_a_number(neurons):
    measured = summarize_endpoint(neurons, np.array([0, np.nan, 0, np.inf]), np.zeros(4), 0.001)
    assert not measured["stationary"]
    assert measured["nonfinite_derivatives"] == 2
    assert measured["max_abs_dvdt_mV_per_ms"] is None
    json.dumps(measured, allow_nan=False)


def test_derivative_vector_must_cover_all_neurons(neurons):
    with pytest.raises(ValueError, match="every neuron"):
        summarize_endpoint(neurons, np.zeros(3), np.zeros(4), 0.001)


def test_negative_clamp_counts_are_rejected(neurons):
    with pytest.raises(ValueError, match="negative"):
        summarize_endpoint(neurons, np.zeros(4), np.array([0, -1, 0, 0]), 0.001)


def test_class_counts_include_central_and_zero_spike_classes(neurons):
    assert class_spike_counts(neurons, np.array([0, 3, 3])) == {"central": 2, "descending": 0, "optic": 1}


@pytest.mark.integration
def test_hybrid_gate_evidence_never_claims_missing_dt_convergence():
    path = Path(__file__).resolve().parents[1] / "build/validation_hybrid.json"
    if not path.exists():
        pytest.skip("Run the whole-brain hybrid gate after V-E passes")
    evidence = json.loads(path.read_text())
    c, d = evidence["gates"]
    assert c["gate"] == "V-C" and d["gate"] == "V-D"
    assert c["status"] in {"FAIL", "NOT-RUN"}
    if "equilibration" not in c:
        pytest.skip("Hybrid gate has not completed a valid pre-equilibration run")
    by_name = {row["name"]: row for row in c["checks"]}
    assert by_name["T4_T5_peak_response_dt_convergence"]["status"] == "NOT-RUN"
    if c["stage4_subgate_status"] == "FAIL" and not d.get("evidence"):
        assert d["status"] == "NOT-RUN"
    if evidence["stage4_status"] == "PASS":
        assert c["stage4_subgate_status"] == "PASS"
        assert d["status"] == "PASS"
        assert d["spikes_by_super_class"]["central"] == 0
