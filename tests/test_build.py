"""Graph assembly correctness and real-release build integration."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from flybrain.build import (
    MISSING_TYPE, _prepare_modes, corrected_signs, default_graded, load_network, make_csr,
)


@pytest.mark.parametrize("cell_type,super_class,expected", [
    ("R1-6", "sensory", True), ("R7", "sensory", True),
    ("L1", "optic", True), ("L1-3", "optic", True), ("Lawf2", "optic", True),
    ("Mi1", "optic", True), ("Mi1", "central", False),
    ("TmY14", "optic", True), ("T2a", "optic", True),
    ("T4a", "optic", True), ("T5d", "optic", True),
    ("CT1", "optic", True), ("HSE", "visual_projection", True),
    ("VS1", "visual_projection", True), ("LPLC2", "visual_projection", False),
    ("LC10a", "visual_projection", False), ("LT34", "visual_centrifugal", False),
    ("DNa02", "descending", False), (MISSING_TYPE, "optic", False),
    ("Mi1", "sensory", False),
])
def test_refined_neuron_modes_are_visual_family_gated(cell_type, super_class, expected):
    assert default_graded(cell_type, super_class) is expected


def test_csr_posts_are_rows_and_repeated_edges_add_exactly():
    matrix = make_csr(np.array([0, 0, 2]), np.array([1, 1, 0]), np.array([2, -5, 7]), 3)
    np.testing.assert_array_equal(matrix.toarray(), [[0, 0, 7], [-3, 0, 0], [0, 0, 0]])
    np.testing.assert_array_equal(matrix @ np.array([1, 0, 0]), [0, -3, 0])
    assert matrix.data.dtype == np.float32
    assert matrix.indices.dtype == np.int32
    assert matrix.indptr.dtype == np.int32


def test_photoreceptor_sign_baseline_and_explicit_post_override():
    names = ["R1-6", "L1", "L2", "Mi1"]
    pre, post = np.array([0, 0, 1]), np.array([1, 2, 3])
    original = np.array([1, 1, -1], dtype=np.int8)
    fixed = corrected_signs(pre, post, original, names, [])
    np.testing.assert_array_equal(fixed, [-1, -1, -1])
    rules = [
        {"pre_type": "R1-6", "post_type": "L2", "sign": 1},
        {"pre_type": "R1-6", "post_type": "*", "sign": -1},
    ]
    fixed = corrected_signs(pre, post, original, names, rules)
    np.testing.assert_array_equal(fixed, [-1, 1, -1])
    np.testing.assert_array_equal(original, [1, 1, -1])  # raw reference untouched


def test_per_type_config_edit_and_all_lif_override(tmp_path):
    neurons = pd.DataFrame({"cell_type": ["Mi1", "LC4", None],
                            "super_class": ["optic", "visual_projection", "central"]})
    path = tmp_path / "neuron_modes.csv"
    np.testing.assert_array_equal(_prepare_modes(neurons, path, "hybrid"), [True, False, False])
    config = pd.read_csv(path)
    config.loc[config.cell_type.eq("LC4"), "mode"] = "graded"
    config.to_csv(path, index=False)
    np.testing.assert_array_equal(_prepare_modes(neurons, path, "hybrid"), [True, True, False])
    np.testing.assert_array_equal(_prepare_modes(neurons, path, "all_lif"), [False, False, False])


def test_default_type_config_does_not_remove_class_gate(tmp_path):
    neurons = pd.DataFrame({"cell_type": ["Mi1", "Mi1"], "super_class": ["optic", "central"]})
    path = tmp_path / "neuron_modes.csv"
    for _ in range(2):
        np.testing.assert_array_equal(_prepare_modes(neurons, path, "hybrid"), [True, False])


@pytest.mark.integration
def test_actual_released_build_partition_and_photoreceptor_signs():
    root = Path(__file__).resolve().parents[1]
    if not (root / "build" / "build_summary.json").exists():
        pytest.skip("Run flybrain build to create the real-release network")
    loaded = load_network(root)
    summary = loaded["summary"]
    neurons = loaded["neurons"]
    assert len(neurons) == 138_639
    np.testing.assert_array_equal(neurons["index"], np.arange(len(neurons)))
    assert sum(summary["edge_partition"].values()) == 15_091_983
    assert summary["first_pass_n_graded"] == 96_674
    assert summary["first_pass_n_spiking"] == 41_965
    assert summary["first_pass_edge_partition"] == {
        "graded_to_graded": 8_903_991, "graded_to_spiking": 464_989,
        "spiking_to_graded": 185_308, "spiking_to_spiking": 5_537_695,
    }
    assert summary["synthetic_edges"] == 0
    for name in ("graded", "spiking", "reference"):
        matrix = loaded[name]
        assert matrix.shape == (138_639, 138_639)
        assert matrix.data.dtype == np.float32
        assert matrix.indices.dtype == np.int32
        assert matrix.indptr.dtype == np.int32
    graded = neurons.is_graded.to_numpy()
    assert np.all(graded[loaded["graded"].indices])
    assert not np.any(graded[loaded["spiking"].indices])
    assert int(np.abs(loaded["reference"].data).sum(dtype=np.float64)) == 54_492_922
    rules = pd.read_csv(root / "config" / "sign_overrides.csv")
    if len(rules) == 3 and rules.sign.eq(-1).all() and rules.post_type.eq("*").all():
        pr_indices = np.flatnonzero(neurons.cell_type.isin(["R1-6", "R7", "R8"]))
        for key in ("graded", "spiking"):
            assert np.all(loaded[key][:, pr_indices].data < 0)
    override_log = pd.read_csv(root / "build" / "sign_overrides.csv")
    assert int(override_log.n_edges.sum()) == summary["sign_overridden_edges"]
    assert int(override_log.n_synapses.sum()) == summary["sign_overridden_synapses"]
