"""Cross-check protocol tests; the expensive full V-E run is explicit."""

import json
from pathlib import Path

import numpy as np
import pytest

from flybrain.validate_engine import compare_rates, generate_input_events


def test_input_events_are_deterministic_sorted_and_unique_per_dt():
    driven, events = generate_input_events(783, 138_639, 10, 1000, 0.1)
    driven_again, events_again = generate_input_events(783, 138_639, 10, 1000, 0.1)
    np.testing.assert_array_equal(driven, driven_again)
    assert len(np.unique(driven)) == 20
    assert driven.dtype == np.int32
    for first, second in zip(events, events_again):
        np.testing.assert_array_equal(first, second)
        assert first.dtype == np.int32
        assert len(np.unique(first, axis=0)) == len(first)
        assert np.all(first[:, 0] >= 0) and np.all(first[:, 0] < 10_000)
        assert np.all(first[:, 1] >= 0) and np.all(first[:, 1] < 20)
        assert np.all(np.diff(first[:, 0]) >= 0)
    assert not np.array_equal(events[0], events[1])


def test_invalid_input_timing_rejected():
    with pytest.raises(ValueError, match="integer number"):
        generate_input_events(1, 100, 1, 0.15, 0.1)
    with pytest.raises(ValueError, match="probability"):
        generate_input_events(1, 100, 1, 1000, 10, rate_hz=150)


def test_primary_metric_uses_mean_rates_and_union_of_active_neurons():
    custom = np.array([[4, 3, 0, 0], [6, 1, 0, 0]])
    reference = np.array([[6, 1, 0, 0], [4, 3, 2, 0]])
    metrics = compare_rates(custom, reference, np.array([0]), 1000)
    assert metrics["active_union_neurons"] == 3
    assert metrics["follower_active_union_neurons"] == 2
    assert metrics["custom_active_neurons"] == 2
    assert metrics["reference_active_neurons"] == 3
    assert metrics["mean_rate_absolute_error_hz"] == pytest.approx(1 / 3)
    expected = np.corrcoef([5, 2, 0], [5, 2, 1])[0, 1]
    assert metrics["mean_rate_correlation"] == pytest.approx(expected)


def test_follower_discrepancy_is_visible_when_driven_cells_dominate():
    custom = np.array([[1000, 1, 2, 3], [1000, 1, 2, 3]])
    reference = np.array([[1000, 3, 2, 1], [1000, 3, 2, 1]])
    metrics = compare_rates(custom, reference, np.array([0]), 1000)
    assert metrics["mean_rate_correlation"] > 0.99
    assert metrics["follower_mean_rate_correlation"] == pytest.approx(-1)


def test_uncomputable_correlation_is_none_not_a_false_perfect_score():
    counts = np.zeros((10, 100), dtype=int)
    metrics = compare_rates(counts, counts, np.arange(20), 1000)
    assert metrics["mean_rate_correlation"] is None
    assert metrics["follower_mean_rate_correlation"] is None
    assert metrics["active_union_neurons"] == 0


@pytest.mark.integration
def test_full_ve_evidence_if_available():
    path = Path(__file__).resolve().parents[1] / "build/validation_engine.json"
    if not path.exists():
        pytest.skip("Run flybrain validate --gate V-E for the full real-release cross-check")
    result = json.loads(path.read_text())
    if not result.get("protocol", {}).get("full_protocol"):
        assert result["status"] != "PASS"
        pytest.skip("Only smoke/diagnostic V-E evidence exists")
    assert result["status"] == "PASS", json.dumps(result, indent=2)
    assert len(result["trial_results"]) == 10
    assert result["protocol"]["duration_ms"] == 1000
    assert result["metrics"]["mean_rate_correlation"] >= 0.95
    assert result["determinism"]["status"] == "PASS"
    assert result["source_hashes"]["model.py"]
    assert result["config_hashes"]["parameters.yaml"]
    assert result["implementation_hashes"]["src/flybrain/engine.py"]
