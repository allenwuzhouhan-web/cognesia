"""Data-gate regression tests; tiny fixtures test rejection, never model data."""

import json
import os
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

from flybrain.validate_data import CONNECTIVITY_COLUMNS, inspect_edge_batch, validate_data


def edge_fixture(**overrides):
    """Explicitly artificial three-edge software fixture, not a connectome."""
    values = {
        "Presynaptic_ID": [720575940596125868, 720575940596125869, 720575940596125870],
        "Postsynaptic_ID": [720575940596125869, 720575940596125870, 720575940596125868],
        "Presynaptic_Index": [0, 1, 2],
        "Postsynaptic_Index": [1, 2, 0],
        "Connectivity": [1, 4, 7],
        "Excitatory": [1, -1, 1],
        "Excitatory x Connectivity": [1, -4, 7],
    }
    values.update(overrides)
    return pa.record_batch([pa.array(values[name], type=pa.int64()) for name in CONNECTIVITY_COLUMNS],
                           names=CONNECTIVITY_COLUMNS)


@pytest.fixture
def roots():
    return np.array([720575940596125868, 720575940596125869, 720575940596125870], dtype=np.int64)


def test_edge_measurements_include_exact_signed_synapse_counts(roots):
    measured = inspect_edge_batch(edge_fixture(), roots)
    assert measured["rows"] == 3
    assert measured["synapse_sum"] == 12
    assert measured["synapse_min"] == 1
    assert measured["positive_edges"] == 2
    assert measured["negative_edges"] == 1
    assert measured["signed_product_mismatches"] == 0
    assert measured["Presynaptic_root_mismatches"] == 0
    assert measured["Postsynaptic_root_mismatches"] == 0


@pytest.mark.parametrize("column", ["Presynaptic_Index", "Postsynaptic_Index"])
def test_negative_and_upper_bound_indices_are_rejected_without_indexing(roots, column):
    measured = inspect_edge_batch(edge_fixture(**{column: [-1, 3, 2]}), roots)
    prefix = column.removesuffix("_Index")
    assert measured[f"{prefix}_out_of_bounds"] == 2
    assert measured[f"{prefix}_index_min"] == -1
    assert measured[f"{prefix}_index_max"] == 3


def test_root_alignment_detects_reordered_completeness_rows(roots):
    measured = inspect_edge_batch(edge_fixture(), roots[[1, 0, 2]])
    assert measured["Presynaptic_out_of_bounds"] == 0
    assert measured["Postsynaptic_out_of_bounds"] == 0
    assert measured["Presynaptic_root_mismatches"] == 2
    assert measured["Postsynaptic_root_mismatches"] == 2


def test_root_alignment_preserves_int64_precision(roots):
    # These adjacent IDs collapse to the same float64; a float-based comparison
    # would incorrectly accept this malformed source ID.
    measured = inspect_edge_batch(edge_fixture(Presynaptic_ID=[roots[0] + 1, roots[1], roots[2]]), roots)
    assert measured["Presynaptic_root_mismatches"] == 1


def test_bad_sign_and_precomputed_product_are_independently_detected(roots):
    measured = inspect_edge_batch(edge_fixture(
        Excitatory=[0, -1, 1], **{"Excitatory x Connectivity": [0, 4, 7]}
    ), roots)
    assert measured["invalid_signs"] == 1
    assert measured["signed_product_mismatches"] == 1


def test_null_input_is_a_validation_failure(roots):
    measured = inspect_edge_batch(edge_fixture(Presynaptic_Index=[None, 1, 2]), roots)
    assert measured["null_count"] == 1
    assert measured["Presynaptic_out_of_bounds"] == 1


def test_missing_release_is_durably_reported_as_fail(tmp_path):
    result = validate_data(tmp_path)
    saved = json.loads((tmp_path / "build" / "validation_data.json").read_text())
    assert saved == result
    assert result["status"] == "FAIL"
    assert result["failed_checks"] == ["validation_execution"]
    assert result["checks"][0]["observed"]["error_type"] == "FileNotFoundError"


@pytest.mark.integration
def test_downloaded_release_passes_every_exact_data_assertion():
    root = Path(os.environ.get("FLYBRAIN_DATA_ROOT", Path(__file__).resolve().parents[1]))
    required = ["Completeness_783.csv", "Connectivity_783.parquet",
                "Supplemental_file1_neuron_annotations.tsv"]
    if not all((root / "data" / "raw" / name).exists() for name in required):
        pytest.skip("Download the real release with flybrain fetch before running the integration gate")
    result = validate_data(root)
    assert result["status"] == "PASS", json.dumps(result["checks"], indent=2)
    assert not result["failed_checks"]
    assert len(result["checks"]) >= 50
    saved = json.loads((root / "build" / "validation_data.json").read_text())
    assert saved == result
