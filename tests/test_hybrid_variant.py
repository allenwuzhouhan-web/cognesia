from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from flybrain.hybrid_variant import (VariantNetwork, HybridVariantEngine, normalize_graded,
                                     spectral_stats, fixed_point, variant_parameters,
                                     validate_variant_parameters)

ROOT = Path(__file__).resolve().parents[1]
BASE = {"dt": .1, "v_rest": -52., "v_reset": -52., "v_threshold": -45.,
        "tau_membrane": 20., "tau_synapse": 5., "refractory": 2.2, "synaptic_delay": 1.8,
        "spike_weight": .275, "poisson_factor": 250., "voltage_min": -90., "voltage_max": 20.,
        "graded_rest": -52., "graded_release": -54., "graded_tau_membrane": 20.,
        "graded_tau_synapse": 5., "dt_graded": .5}


def fixture(matrix=None, graded=None):
    matrix = sparse.csr_matrix([[1.]]) if matrix is None else sparse.csr_matrix(matrix)
    n = matrix.shape[0]
    mask = np.ones(n, bool) if graded is None else np.asarray(graded, bool)
    neurons = pd.DataFrame({"root_id": np.arange(n, dtype=np.int64), "cell_type": ["test"]*n, "is_graded": mask})
    spec = spectral_stats(matrix[mask][:, mask])
    return VariantNetwork(neurons, matrix, sparse.csr_matrix((n, n)), mask, np.zeros(n, bool), np.ones(n), spec, {})


@pytest.mark.parametrize("mode,expected", [
    ("none", [[2., -2.], [0, 9.]]),
    ("in_weight", [[.5, -.5], [0, 1.]]),
    ("in_degree_alpha", [[2/np.sqrt(2), -2/np.sqrt(2)], [0, 9.]]),
])
def test_normalization_is_postsynaptic_absolute_row_weight(mode, expected):
    matrix = sparse.csr_matrix([[2., -2.], [0, 9.]])
    original = matrix.toarray().copy()
    normalized, _ = normalize_graded(matrix, mode, .5)
    np.testing.assert_allclose(normalized.toarray(), expected)
    np.testing.assert_array_equal(matrix.toarray(), original)


def test_zero_rows_do_not_divide_by_zero():
    matrix, denominator = normalize_graded(sparse.csr_matrix((3, 3)), "in_weight")
    assert matrix.nnz == 0
    np.testing.assert_array_equal(denominator, 1)


def test_spectrum_distinguishes_largest_real_part_from_largest_magnitude():
    matrix = sparse.diags([-8., -4., 3., 2., 1., .5, .2, .1, 0.], format="csr")
    result = spectral_stats(matrix, modes=2)
    assert result["converged"]
    assert result["max_Re_lambda"] == pytest.approx(3.)
    assert result["max_abs_lambda"] == pytest.approx(8.)
    assert result["ritz_relative_residual_max"] < 1e-6


@pytest.mark.parametrize("kappa", [-1, 0, 1, 1.2, np.nan])
def test_out_of_bound_kappa_is_refused(kappa):
    with pytest.raises(ValueError, match="kappa"):
        validate_variant_parameters(variant_parameters(ROOT) | {"kappa": kappa})


def test_current_fixed_point_has_unit_gain_synaptic_forcing_not_extra_tau():
    network = fixture()
    p = variant_parameters(ROOT)
    point = fixed_point(network, BASE, p)
    assert point["quiescent_fixed_point"]
    # v = -52 + .8*(v+54), so v=-44 and g=8.
    assert point["voltage"][0] == pytest.approx(-44., abs=.001)
    assert point["g_exc"][0] == pytest.approx(8., abs=.001)
    engine = HybridVariantEngine(network, BASE, p, threads=1)
    engine.initialize_fixed_point(point)
    result = engine.run(10.)
    assert abs(result["final_v"][0] - point["voltage"][0]) < .001
    assert result["clamp_count"] == 0


def test_nonconvergence_is_not_fabricated_and_refuses_integration():
    network = fixture()
    network.spectrum["max_Re_lambda"] = .01  # Deliberately inconsistent numerical fixture.
    p = variant_parameters(ROOT) | {"fixed_point_max_iterations": 20}
    point = fixed_point(network, BASE, p)
    assert not point["converged"]
    assert point["iterations"] == 20
    with pytest.raises(ValueError, match="unestablished"):
        HybridVariantEngine(network, BASE, p).initialize_fixed_point(point)


def test_suprathreshold_spiking_solution_is_not_a_hybrid_rest_state():
    network = fixture([[1., 0.], [2., 0.]], graded=[True, False])
    point = fixed_point(network, BASE, variant_parameters(ROOT))
    assert point["converged"]
    assert point["suprathreshold_spiking_neurons"].tolist() == [1]
    assert not point["quiescent_fixed_point"]


@pytest.mark.parametrize("syn_model", ["current", "conductance"])
def test_deterministic_perturbation_continuation_and_half_dt(syn_model):
    network = fixture([[.8, -.1], [.2, .7]])
    p = variant_parameters(ROOT) | {"syn_model": syn_model}
    point = fixed_point(network, BASE, p)
    full = HybridVariantEngine(network, BASE, p, threads=1)
    split = HybridVariantEngine(network, BASE, p, threads=1)
    fine = HybridVariantEngine(network, BASE, p, dt=.05, threads=1)
    for engine in (full, split, fine):
        engine.initialize_fixed_point(point, perturbation=1., seed=5)
    a = full.run(10.)
    split.run(4.); b = split.run(6.)
    c = fine.run(10.)
    np.testing.assert_array_equal(a["final_v"], b["final_v"])
    assert np.max(abs(a["final_v"]-c["final_v"])) < .01
    assert a["clamp_count"] == b["clamp_count"] == c["clamp_count"] == 0


def test_conductance_update_stays_between_reversals_without_clamping():
    network = fixture([[1., -.5], [.1, .5]])
    p = variant_parameters(ROOT) | {"syn_model": "conductance"}
    point = fixed_point(network, BASE, p)
    engine = HybridVariantEngine(network, BASE, p, threads=1)
    engine.initialize_fixed_point(point)
    engine.v[:] = [-79., -1.]
    engine.ge[:] = [100., 0.]
    engine.gi[:] = [0., 100.]
    result = engine.run(10.)
    assert result["voltage_min"].min() >= p["E_inh"]
    assert result["voltage_max"].max() <= p["E_exc"]
    assert result["clamp_count"] == 0


def test_current_rail_events_are_counted_per_neuron():
    network = fixture()
    p = variant_parameters(ROOT)
    point = fixed_point(network, BASE, p)
    engine = HybridVariantEngine(network, BASE, p, threads=1)
    engine.initialize_fixed_point(point)
    engine.ge[0] = 1e6
    result = engine.run(1.)
    assert result["clamp_count"] > 0
    assert result["clamp_count"] == int(result["per_neuron_clamps"].sum())


def test_excluded_cell_is_not_perturbed_or_released():
    network = fixture([[1., 0.], [0., 0.]])
    network.excluded[1] = True
    p = variant_parameters(ROOT)
    point = fixed_point(network, BASE, p)
    engine = HybridVariantEngine(network, BASE, p, threads=1)
    engine.initialize_fixed_point(point, perturbation=1.)
    assert engine.v[1] == BASE["graded_rest"]
    assert not engine.history[:, 1].any()
