from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from flybrain.engine import LIFEngine
from flybrain.neuromod.compartments import CompartmentMap
from flybrain.neuromod.field import FIELD_SPECIES
from flybrain.neuromod.receptor_engine import ReceptorLIFEngine
from flybrain.neuromod.receptors import (ReceptorModel, read_receptors, kernel_response,
                                         parse_kernel, receptor_bounds)

ROOT = Path(__file__).resolve().parents[1]
P = {"dt": .1, "v_rest": -52., "v_reset": -52., "v_threshold": -45.,
     "tau_membrane": 20., "tau_synapse": 5., "refractory": 2.2,
     "synaptic_delay": 1.8, "spike_weight": .275, "poisson_factor": 20.,
     "voltage_min": -90., "voltage_max": 20.}
EMPTY = np.empty((0, 2), np.int64)


def fixture(rows=None):
    neurons = pd.DataFrame({"root_id": np.arange(6, dtype=np.int64),
                            "cell_type": ["KCg", "KCab", "MBON01", "MBON02", "PAM01", "LN"],
                            "cell_class": ["Kenyon_Cell", "Kenyon_Cell", "MBON", "MBON", "DAN", "ALLN"],
                            "known_nt": ["acetylcholine; sNPF", "acetylcholine", "gaba", "glutamate", "dopamine", "gaba"]})
    membership = np.array([[1, 1, 1, 0, 1, 1], [1, 0, 0, 1, 0, 0]], bool)
    mapping = CompartmentMap(("g1", "g2"), membership, np.zeros((2, 2), np.float32),
                             np.array([-1, -1, 0, 1, 0, -1], np.int16), neurons.root_id.to_numpy(), {})
    weights = sparse.csr_matrix(([1000., 1000., 1000., 1000., -100.],
                                ([2, 3, 4, 2, 2], [0, 0, 0, 1, 5])), shape=(6, 6))
    model = ReceptorModel(read_receptors(ROOT / "config/receptors.csv") if rows is None else rows,
                          neurons, mapping, weights)
    return model, neurons, mapping, weights


def row(**changes):
    reference = read_receptors(ROOT / "config/receptors.csv")[0]
    return reference | {"id": "test", "history": "instant", "effect": "gain", "edge_scope": "none",
                        "target": "^KCg$", "magnitude": .5, "kernel": "linear"} | changes


def effects_for(model, species="DA", values=(1., 0.)):
    c = np.zeros((len(FIELD_SPECIES), 2))
    c[FIELD_SPECIES.index(species)] = values
    return model.evaluate(c)


def compare(a, b, left, right):
    for key in ("spike_indices", "spike_times", "voltages", "voltage_times", "record_indices"):
        np.testing.assert_array_equal(left[key], right[key])
    for key in ("v", "g", "last_spike", "ring_counts", "refractory_steps"):
        np.testing.assert_array_equal(getattr(a, key), getattr(b, key))
    for slot, count in enumerate(a.ring_counts):
        np.testing.assert_array_equal(a.ring[slot, :count], b.ring[slot, :count])
    assert left["clamp_count"] == right["clamp_count"]


def test_seed_evidence_corrects_receptor_identity_without_erasing_requested_rows():
    rows = {r["id"]: r for r in read_receptors(ROOT / "config/receptors.csv")}
    assert rows["OA_OAMB_PAM"]["enabled"]
    assert not rows["OA_Octbeta2R_PAM_requested"]["enabled"]
    assert rows["ACh_mAChRA_KC"]["enabled"]
    assert not rows["ACh_mAChRB_KC_requested"]["enabled"]
    assert {r["expression_provenance"] for r in rows.values()} == {"ASSUMPTION"}
    assert {r["magnitude_provenance"] for r in rows.values()} == {"ASSUMPTION"}
    assert rows["DA_Dop1R1_forward"]["history"] != rows["DA_Dop1R2_backward"]["history"]


@pytest.mark.parametrize("kernel", ["linear", "hill(1,1)", "hill(2,0.5)", "biphasic"])
def test_kernel_normalization_is_explicit(kernel):
    value = kernel_response([0, 1], kernel)
    np.testing.assert_allclose(value, [0, 1], rtol=0, atol=1e-15)


def test_biphasic_is_concentration_shape_not_a_dopamine_history_rule():
    np.testing.assert_array_equal(kernel_response([0, 1, 2, 3], "biphasic"), [0, 1, 0, -3])
    with pytest.raises(ValueError, match="nonnegative"):
        kernel_response([-1], "linear")


@pytest.mark.parametrize("kernel", ["unknown", "hill(0,1)", "hill(1,-1)", "hill(nan,1)", "hill(1)"])
def test_bad_kernels_rejected(kernel):
    with pytest.raises(ValueError):
        parse_kernel(kernel)


@pytest.mark.parametrize("change", [
    {"target": "["}, {"modulator": "made-up"}, {"effect": "current"},
    {"edge_scope": "row"}, {"history": "instant"}, {"magnitude": "nan"},
    {"magnitude_provenance": "PMID:123"}, {"expression_provenance": "SCRNA"},
    {"magnitude_sweep": "1;2"}, {"enabled": "yes"},
])
def test_invalid_schema_is_rejected(tmp_path, change):
    table = pd.read_csv(ROOT / "config/receptors.csv", keep_default_na=False, dtype=str)
    for name, value in change.items():
        table.loc[0, name] = value
    path = tmp_path / "bad.csv"
    table.to_csv(path, index=False)
    with pytest.raises(ValueError):
        read_receptors(path)


def test_zero_concentration_is_identity_and_no_current_output_exists():
    model, *_ = fixture()
    effect = model.evaluate(np.zeros((len(FIELD_SPECIES), 2)))
    for values in (effect.gain, effect.threshold_factor, effect.tau_factor, effect.release_factor):
        np.testing.assert_array_equal(values, 1)
    assert all(not channel.signal.any() for channel in effect.plasticity_channels.values())
    assert not hasattr(effect, "current")
    assert not any(effect.guard_events.values())


def test_release_scope_uses_matching_presynaptic_kc_and_target_mbon_compartment():
    model, *_ = fixture([row(effect="release_prob", edge_scope="KC->MBON")])
    effect = effects_for(model)
    by_edge = {(int(pre), int(post)): factor for pre, post, factor in zip(effect.edge_pre, effect.edge_post, effect.release_factor)}
    assert by_edge[0, 2] == 1.5
    assert by_edge[0, 3] == 1  # Same KC; different postsynaptic compartment.
    assert by_edge[0, 4] == 1  # Same KC; not a KC->MBON edge.
    assert by_edge[1, 2] == 1  # Same MBON; KC does not match target regex.
    np.testing.assert_array_equal(effect.gain, 1)


def test_all_out_release_scales_only_selected_presynaptic_columns():
    model, *_ = fixture([row(effect="release_prob", edge_scope="all_out")])
    effect = effects_for(model)
    # KC0 has equal membership in both volumes, so concentration exposure is .5.
    np.testing.assert_array_equal(effect.release_factor[effect.edge_pre == 0], 1.25)
    np.testing.assert_array_equal(effect.release_factor[effect.edge_pre != 0], 1.)


def test_dopamine_branches_are_separate_and_do_not_change_instantaneous_release():
    rows = read_receptors(ROOT / "config/receptors.csv")[:2]
    model, *_ = fixture(rows)
    effect = effects_for(model)
    np.testing.assert_array_equal(effect.release_factor, 1)
    np.testing.assert_array_equal(effect.gain, 1)
    channels = effect.plasticity_channels
    assert len(channels) == 2
    assert channels[rows[0]["id"]].history == "kc_before_da"
    assert channels[rows[1]["id"]].history == "da_before_kc"
    assert channels[rows[0]["id"]].signal.min() < 0
    assert channels[rows[1]["id"]].signal.max() > 0


def test_guards_are_bounded_and_counted_and_nonfinite_c_is_rejected():
    model, *_ = fixture([row(magnitude=-100.)])
    effect = effects_for(model)
    assert effect.gain[0] == 0
    assert effect.guard_events["signal"] == 1
    assert effect.guard_events["gain"] == 1
    with pytest.raises(ValueError, match="finite"):
        model.evaluate(np.full((len(FIELD_SPECIES), 2), np.nan))
    assert not effect.gain.flags.writeable


def test_row_order_and_edge_order_mismatches_fail():
    model, neurons, mapping, weights = fixture([])
    with pytest.raises(ValueError, match="row order"):
        ReceptorModel([], neurons.iloc[::-1], mapping, weights)
    effect = effects_for(model)
    engine = ReceptorLIFEngine(weights, P, enabled=True, model_root_ids=np.arange(6, dtype=np.int64), threads=1)
    with pytest.raises(ValueError, match="CSC order"):
        engine.set_effects(replace(effect, edge_pre=effect.edge_pre[::-1]))


def test_disabled_path_delegates_directly(monkeypatch):
    engine = ReceptorLIFEngine(sparse.csr_matrix((1, 1)), P, enabled=False, threads=1)
    marker = object()
    monkeypatch.setattr(LIFEngine, "run", lambda *args, **kwargs: marker)
    assert engine.run(1, [], EMPTY) is marker


@pytest.mark.parametrize("enabled", [False, True])
def test_identity_adapter_matches_recurrent_base_and_continuation(enabled):
    model, _, _, weights = fixture([])
    weights = weights + weights.T
    model, neurons, mapping, _ = fixture([])
    model = ReceptorModel([], neurons, mapping, weights)
    a = LIFEngine(weights, P | {"poisson_factor": 250}, clamp=False, threads=1)
    b = ReceptorLIFEngine(weights, P | {"poisson_factor": 250}, enabled=enabled, model_root_ids=np.arange(6, dtype=np.int64), clamp=False, threads=1)
    if enabled:
        b.set_effects(effects_for(model))
    for duration, events in [(4.3, np.array([[0, 0], [15, 1]])), (5.7, np.array([[12, 0], [40, 1]]))]:
        left = a.run(duration, [0, 1], events, record_indices=np.arange(6), chunk_ms=1.)
        right = b.run(duration, [0, 1], events, record_indices=np.arange(6), chunk_ms=2.)
        compare(a, b, left, right)


def test_active_gain_changes_response_without_current_at_rest():
    model, _, _, weights = fixture([row(magnitude=2.)])
    effect = effects_for(model)
    a = ReceptorLIFEngine(weights, P, enabled=True, model_root_ids=np.arange(6, dtype=np.int64), clamp=False, threads=1)
    b = LIFEngine(weights, P, clamp=False, threads=1)
    a.set_effects(effect)
    rest = a.run(.5, [], EMPTY)
    assert not len(rest["spike_indices"])
    np.testing.assert_array_equal(a.v, P["v_rest"])
    a.reset()
    actual = a.run(1., [0], [[0, 0]])
    baseline = b.run(1., [0], [[0, 0]])
    assert len(actual["spike_indices"]) > len(baseline["spike_indices"])


def test_active_tau_and_threshold_are_consumed_as_named_parameters():
    model, _, _, weights = fixture([row(effect="tau_m", magnitude=-.5), row(id="th", effect="v_th", magnitude=-.5)])
    engine = ReceptorLIFEngine(weights, P, enabled=True, model_root_ids=np.arange(6, dtype=np.int64), clamp=False, threads=1)
    effect = effects_for(model)
    engine.set_effects(effect)
    assert engine.receptor_decay_v[0] == pytest.approx(np.exp(-.1 / 15.))
    assert engine.receptor_threshold[0] == pytest.approx(-52 + 7 * .75)
    engine.v[0] = -46.
    result = engine.run(.1, [], EMPTY)
    assert result["spike_indices"].tolist() == [0]


def test_active_release_changes_delivered_g_only_for_scoped_edges():
    model, _, _, weights = fixture([row(effect="release_prob", edge_scope="KC->MBON", magnitude=-1.)])
    engine = ReceptorLIFEngine(weights, P, enabled=True, model_root_ids=np.arange(6, dtype=np.int64), clamp=False, threads=1)
    engine.set_effects(effects_for(model))
    engine.v[0] = -44.
    engine.run(1.9, [], EMPTY)
    assert engine.g[2] == 0
    assert engine.g[3] == engine.g[4] == 275


def test_nonidentity_active_effects_preserve_split_run_state_and_delayed_events():
    model, _, _, weights = fixture([row(magnitude=.3), row(id="release", effect="release_prob", edge_scope="KC->MBON", magnitude=-.4)])
    effect = effects_for(model)
    full = ReceptorLIFEngine(weights, P | {"poisson_factor": 250.}, enabled=True, model_root_ids=np.arange(6, dtype=np.int64), clamp=False, threads=1)
    split = ReceptorLIFEngine(weights, P | {"poisson_factor": 250.}, enabled=True, model_root_ids=np.arange(6, dtype=np.int64), clamp=False, threads=1)
    full.set_effects(effect); split.set_effects(effect)
    one = full.run(10., [0, 1], [[0, 0], [55, 1]], record_indices=np.arange(6))
    first = split.run(4.3, [0, 1], [[0, 0]], record_indices=np.arange(6))
    second = split.run(5.7, [0, 1], [[12, 1]], record_indices=np.arange(6))
    joined = {key: np.concatenate([first[key], second[key]]) for key in
              ("spike_indices", "spike_times", "voltages", "voltage_times")}
    joined.update(record_indices=one["record_indices"], clamp_count=first["clamp_count"] + second["clamp_count"])
    compare(full, split, one, joined)


def test_nonfinite_active_state_fails_and_preserves_partial_evidence():
    model, _, _, weights = fixture([])
    engine = ReceptorLIFEngine(weights, P, enabled=True, model_root_ids=np.arange(6, dtype=np.int64), clamp=False, threads=1)
    engine.set_effects(effects_for(model))
    engine.g[0] = np.nan
    with pytest.raises(FloatingPointError, match="nonfinite"):
        engine.run(.1, [], EMPTY)
    assert engine.nonfinite_state_events > 0
    assert engine.partial_result["completed"] is False
    engine.reset()
    recovered = engine.run(.1, [], EMPTY)
    assert recovered["completed"]
    assert recovered["nonfinite_state_events"] == 0


@pytest.mark.parametrize("factor", [np.nextafter(.25, 0.), .25, np.nextafter(.25, np.inf)])
def test_exact_linear_is_stable_on_both_sides_of_equal_time_constants(factor):
    model, _, _, weights = fixture([])
    effects = replace(effects_for(model), tau_factor=np.full(6, factor))
    engine = ReceptorLIFEngine(weights, P, enabled=True, model_root_ids=np.arange(6, dtype=np.int64),
                              integrator="exact_linear", threads=1, clamp=False)
    engine.set_effects(effects)
    assert engine.receptor_coupling[0] == pytest.approx(.1 / 5 * np.exp(-.1 / 5), abs=1e-16)
    engine.g[0] = 1.
    engine.run(.1, [], EMPTY)
    assert engine.v[0] > P["v_rest"]


def test_active_model_identity_is_required_and_reversed_ids_are_rejected():
    model, _, _, weights = fixture([])
    with pytest.raises(ValueError, match="explicit model_root_ids"):
        ReceptorLIFEngine(weights, P, enabled=True, threads=1)
    engine = ReceptorLIFEngine(weights, P, enabled=True, model_root_ids=np.arange(6, dtype=np.int64), threads=1)
    with pytest.raises(ValueError, match="row ordering"):
        engine.set_effects(replace(effects_for(model), model_root_ids=np.arange(5, -1, -1, dtype=np.int64)))


def test_active_requires_effects_and_invalid_transforms_fail():
    model, _, _, weights = fixture([])
    engine = ReceptorLIFEngine(weights, P, enabled=True, model_root_ids=np.arange(6, dtype=np.int64), threads=1)
    with pytest.raises(ValueError, match="requires explicit"):
        engine.run(1, [], EMPTY)
    with pytest.raises(ValueError, match="positive"):
        engine.set_effects(replace(effects_for(model), tau_factor=np.zeros(6)))


@pytest.mark.integration
def test_real_receptor_validator(isolated_validation_root):
    from flybrain.neuromod.receptors import validate_receptors
    if not (ROOT / "build/validation_neuromod_field.json").exists():
        pytest.skip("Requires real source, compartment and field artifacts")
    result = validate_receptors(isolated_validation_root(ROOT))
    assert result["status"] == "PASS", result["failed_checks"]
    assert result["visual_gate"]["status"] == "NOT-RUN"
    assert result["disabled_equivalence"]["core_neurons"] == 13300
