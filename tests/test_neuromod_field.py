"""Actual field integrator numerics; fixtures are explicitly numerical, not biology."""
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from flybrain.neuromod.compartments import CompartmentMap
from flybrain.neuromod.field import (
    FIELD_SPECIES, FieldEngine, FieldParameters, build_source_projection, validate_field,
)


def parameters(species=("DA",), tau=400., sigma=0., dt=1.):
    n = len(species)
    return FieldParameters(species, .1, dt, 5., np.full(n, tau), np.full(n, sigma),
                           np.full(n, 50.), np.ones(n))


def scalar_engine(**changes):
    return FieldEngine(parameters(**changes), ("reference",), np.zeros((1, 1)))


def test_exponential_pulse_and_decay_match_closed_form():
    engine = scalar_engine()
    engine.advance_drive(np.ones((1, 1)), 500)
    peak = 1 - np.exp(-500 / 400)
    assert engine.C.dtype == np.float32
    assert float(engine.C[0, 0]) == pytest.approx(peak, abs=1e-6)
    engine.advance_drive(np.zeros((1, 1)), 500)
    assert float(engine.C[0, 0]) == pytest.approx(peak * np.exp(-500 / 400), abs=1e-6)
    assert engine.clamp_count == 0 and engine.t_sim_ms == 1000
    assert engine.units == 'a.u.'


def test_halving_timestep_changes_pulse_peak_by_under_one_percent():
    coarse = scalar_engine(dt=1.)
    fine = scalar_engine(dt=.5)
    coarse.advance_drive(np.ones((1, 1)), 500)
    fine.advance_drive(np.ones((1, 1)), 1000)
    assert abs(float(coarse.C[0, 0] - fine.C[0, 0])) / float(coarse.C[0, 0]) < .01


def test_full_normalized_drive_approaches_one_au_without_clamping():
    engine = scalar_engine()
    engine.advance_drive(np.ones((1, 1)), 6000)
    assert engine.C[0, 0] == pytest.approx(1., abs=2e-5)
    assert engine.clamp_count == 0


def test_frozen_diffusion_conserves_mass_after_clearance_and_is_one_hop_per_step():
    adjacent = np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]], dtype=float)
    engine = FieldEngine(parameters(('NO',), tau=50, sigma=.01), ('a', 'b', 'c'), adjacent)
    engine.C[0, 0] = 1.
    engine.advance_drive(np.zeros((1, 3)))
    assert engine.C[0, 1] > 0 and engine.C[0, 2] == 0
    assert engine.C.sum() == pytest.approx(np.exp(-1 / 50), abs=1e-6)
    engine.advance_drive(np.zeros((1, 3)))
    assert engine.C[0, 2] > 0  # NO diffusion reaches a second hop honestly.
    assert engine.C.sum() == pytest.approx(np.exp(-2 / 50), abs=1e-6)
    assert engine.clamp_count == 0


def test_default_da_has_exact_zero_outside_pulsed_compartment():
    engine = FieldEngine(parameters(), ('a', 'b', 'c'), np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]]))
    engine.advance_drive(np.array([[1., 0., 0.]]), 1000)
    assert np.count_nonzero(engine.C[0, 1:]) == 0


def test_diffusion_uses_frozen_state_independent_of_compartment_order():
    adjacent = np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]], dtype=float)
    first = FieldEngine(parameters(('NO',), tau=50, sigma=.01), ('a', 'b', 'c'), adjacent)
    order = np.array([2, 0, 1])
    second = FieldEngine(parameters(('NO',), tau=50, sigma=.01), ('c', 'a', 'b'), adjacent[order][:, order])
    first.C[0] = [1., .2, .7]
    second.C[0] = first.C[0, order]
    first.advance_drive(np.zeros((1, 3)), 10)
    second.advance_drive(np.zeros((1, 3)), 10)
    np.testing.assert_array_equal(first.C[:, order], second.C)


@pytest.mark.parametrize('field,value', [
    ('dt_base_ms', 0), ('dt_base_ms', np.nan), ('dt_mod_ms', -1), ('dt_mod_ms', np.inf),
    ('dt_mod_ms', .15), ('concentration_max_au', 0), ('concentration_max_au', np.nan),
    ('tau_clear_ms', np.array([9.])), ('tau_clear_ms', np.array([np.nan])),
    ('spillover_per_ms', np.array([-.01])), ('max_source_rate_hz', np.array([0.])),
    ('source_gain', np.array([-1.])),
])
def test_invalid_parameters_fail_before_simulation(field, value):
    with pytest.raises(ValueError):
        replace(parameters(), **{field: value})


@pytest.mark.parametrize('adjacent', [
    np.array([[0., np.nan], [np.nan, 0.]]), np.array([[0., -1.], [-1., 0.]]),
    np.array([[0., 1.], [0., 0.]]), np.array([[1., 0.], [0., 1.]]),
])
def test_invalid_adjacency_fails(adjacent):
    with pytest.raises(ValueError):
        FieldEngine(parameters(), ('a', 'b'), adjacent)


def test_exponential_euler_positivity_bound_is_enforced():
    with pytest.raises(ValueError, match='positivity bound'):
        FieldEngine(parameters(sigma=2.), ('a', 'b'), np.array([[0., 1.], [1., 0.]]))


@pytest.mark.parametrize('value', [-1., np.nan, np.inf])
def test_invalid_drive_is_rejected(value):
    with pytest.raises(ValueError):
        scalar_engine().advance_drive(np.array([[value]]))


def test_each_upper_clamp_is_counted_and_state_reset_clears_counters():
    engine = scalar_engine()
    engine.advance_drive(np.array([[100000.]]), 4)
    assert engine.clamp_count == 4 and engine.C[0, 0] == 5.
    engine.reset()
    assert engine.clamp_count == 0 and engine.t_sim_ms == 0 and engine.C[0, 0] == 0


def source_fixture():
    neurons = pd.DataFrame({'root_id': np.arange(6, dtype=np.int64),
                           'cell_type': ['KCg', 'PAM06', 'PAM06', 'OA-AL2b2', 'IPC', 'unknown'],
                           'known_nt': ['acetylcholine; sNPF', 'dopamine, nitric oxide', 'dopamine', 'tyramine', 'DILP2; DILP3', None],
                           'top_nt': ['dopamine', 'gaba', 'gaba', 'octopamine', 'gaba', 'dopamine'],
                           'super_class': ['central'] * 4 + ['endocrine', 'central']})
    membership = np.array([[1, 1, 1, 1, 1, 1], [0, 0, 1, 0, 0, 0], [0, 0, 0, 0, 1, 0]], bool)
    mapping = CompartmentMap(('a', 'b', 'hemolymph'), membership, np.array([[0, 1, 0], [1, 0, 0], [0, 0, 0]], np.float32),
                             np.full(6, -1, np.int16), neurons.root_id.to_numpy(), {})
    return neurons, mapping


def test_projection_uses_per_neuron_ground_truth_and_own_source_count_normalization():
    neurons, mapping = source_fixture()
    projected = build_source_projection(neurons, mapping)
    count = lambda species: projected.source_counts[FIELD_SPECIES.index(species)]
    assert count('DA').tolist() == [2, 1, 0]
    assert count('NO').tolist() == [1, 0, 0]  # No type-wide PAM06 promotion.
    assert count('OA').sum() == 0
    assert count('TA').tolist() == [1, 0, 0]
    assert count('sNPF').tolist() == [1, 0, 0]
    assert count('ACh').tolist() == [1, 0, 0]
    assert count('peptide_pool').tolist() == [0, 0, 1]  # IPC at a cannot create a nonglobal pool.
    mean = projected.mean_rates_hz(np.full(6, 50., np.float32))
    assert np.all(mean[projected.source_counts > 0] == 50.)
    rates = np.zeros(6); rates[-1] = 1000
    assert np.count_nonzero(projected.mean_rates_hz(rates)) == 0
    neurons.top_nt = 'dopamine'
    changed = build_source_projection(neurons, mapping)
    np.testing.assert_array_equal(projected.source_counts, changed.source_counts)
    assert (projected.mean_rate_matrix != changed.mean_rate_matrix).nnz == 0


def test_engine_projects_hz_before_normalized_field_step():
    neurons, mapping = source_fixture()
    params = parameters(FIELD_SPECIES)
    projected = build_source_projection(neurons, mapping)
    engine = FieldEngine(params, mapping.names, mapping.adjacency, projected)
    engine.advance(np.full(6, 50.), 6000)
    np.testing.assert_allclose(engine.C[projected.source_counts > 0], 1., atol=2e-5)
    assert engine.clamp_count == 0


def test_hemolymph_isolated_and_peptide_pool_not_driven_elsewhere():
    with pytest.raises(ValueError, match='isolated'):
        FieldEngine(parameters(('peptide_pool',)), ('a', 'hemolymph'), np.array([[0., 1.], [1., 0.]]))
    engine = FieldEngine(parameters(('peptide_pool',)), ('a', 'hemolymph'), np.zeros((2, 2)))
    with pytest.raises(ValueError, match='only in hemolymph'):
        engine.advance_drive(np.array([[1., 0.]]))


def test_field_replay_with_same_rates_is_bit_exact():
    left = scalar_engine(); right = scalar_engine()
    rng = np.random.default_rng(7)
    for value in rng.random(100):
        left.advance_drive(np.array([[value]]))
        right.advance_drive(np.array([[value]]))
    np.testing.assert_array_equal(left.C, right.C)


def test_missing_field_config_writes_durable_failure(tmp_path):
    result = validate_field(tmp_path)
    assert result['status'] == 'FAIL'
    assert result['failed_checks'] == ['field_validation_execution']
    assert json.loads((tmp_path / 'build/validation_neuromod_field.json').read_text()) == result


@pytest.mark.integration
def test_real_field_gate_passes_after_source_and_compartment_builds(isolated_validation_root):
    root = Path(__file__).resolve().parents[1]
    if not (root / 'build/compartments.npz').exists():
        pytest.skip('Requires source and compartment builds')
    root = isolated_validation_root(root)
    result = validate_field(root)
    assert result['status'] == 'PASS', result['checks']
    assert not result['failed_checks']
    assert result['sensitivity_runs'] >= 96
    assert len(result['references']) == 8
    assert result['NO_two_step_two_hop_concentration_au'] > 0
    from flybrain.report import _current_result
    assert result['source_hashes'] and result['source_stats']
    assert _current_result(result, root, {}, {}, [], [])['status'] == 'PASS'
