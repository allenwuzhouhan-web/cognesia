"""Final brief Part III correction: reference and production must both pass."""
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pytest

from flybrain.neuromod.plasticity import (
    NormalizedPlasticity, PlasticityParameters, reference_parameters, reference_curve,
    production_reference_curve, assert_reference_curve, REFERENCE_DELTA_W,
    REFERENCE_FIXTURE, REFERENCE_DELAYS_MS, INDEPENDENT_FLOAT32_TOLERANCE,
    normalize_kc_rates, pairing_summary, software_checks, require_receptor_gate,
    load_compartment_rules,
)


def single(**changes):
    return NormalizedPlasticity(1, 1, np.array([0]), np.array([0]), [1.], replace(reference_parameters(), **changes))


def test_pinned_float64_reference_reproduces_all_twelve_new_values():
    curve = reference_curve()
    assert_reference_curve(curve)
    assert curve['max_absolute_reference_error'] < 5e-7
    assert curve['state_dtype'] == 'float64'
    assert curve['weight_clamp_events'] == curve['concentration_clamp_events'] == 0
    summary = pairing_summary(curve)
    assert summary['crossover_ms'] == pytest.approx(-510.07858446, abs=1e-6)
    assert summary['peak_depression_delay_ms'] == 500
    assert summary['forward_sum'] < 0 < summary['backward_sum']


def test_production_float32_matches_independent_pinned_float64():
    exact, production = reference_curve(), production_reference_curve()
    assert_reference_curve(production)
    assert production['state_dtype'] == 'float32'
    assert max(abs(np.asarray(exact['delta_w'])-production['delta_w'])) < INDEPENDENT_FLOAT32_TOLERANCE


def test_reference_refinement_and_pinned_assumptions():
    coarse, fine = reference_curve(), reference_curve(.5)
    assert max(abs(np.asarray(coarse['delta_w'])-fine['delta_w'])) < .000031
    assert_reference_curve(fine)
    serialized = json.dumps(REFERENCE_FIXTURE, allow_nan=False)
    assert 'Infinity' not in serialized
    assert REFERENCE_FIXTURE['given']['tau_forget_ms'] is None
    assert REFERENCE_FIXTURE['given']['horizon_ms'] == 7000
    assert not REFERENCE_FIXTURE['unprovided_assumptions']


def test_unit_gain_traces_converge_to_input_without_tau_multiplier():
    kernel = single(eta_per_ms=0.)
    for _ in range(1000):
        kernel.step([1], [1], 1)
    assert kernel.e_pre[0] == pytest.approx(-np.expm1(-1000/600), rel=2e-5)
    assert kernel.e_da[0] == pytest.approx(-np.expm1(-1000/1500), rel=2e-5)
    assert kernel.e_pre.dtype == kernel.e_da.dtype == kernel.weights.dtype == np.float32


def test_first_weight_update_uses_new_traces_and_supplied_new_concentration():
    kernel = single()
    kernel.step([1], [.5], 10)
    ep = -np.expm1(-10/600)
    ed = .5 * -np.expm1(-10/1500)
    expected = 1 - .00055*(.5*ep - .55*ed)*10
    assert kernel.weights[0] == pytest.approx(expected, abs=3e-8)
    assert kernel.weights[0] < 1


def test_forward_backward_and_current_zero_history_are_distinct():
    forward, backward = single(), single()
    forward.step([1], [0], 100)
    forward.step([0], [1], 100)
    backward.step([0], [1], 100)
    backward.step([1], [0], 100)
    assert forward.weights[0] < 1 < backward.weights[0]


def test_no_signal_throughout_relevant_history_at_baseline_is_invariant():
    no_da, no_kc = single(), single()
    for _ in range(500):
        no_da.step([1], [0], 1)
        no_kc.step([0], [1], 1)
    np.testing.assert_array_equal(no_da.weights, [1])
    np.testing.assert_array_equal(no_kc.weights, [1])


def test_forgetting_nonbaseline_no_input_matches_exact_exponential():
    kernel = single(tau_forget_ms=600000.)
    kernel.weights[:] = .5
    kernel.step([0], [0], 1000)
    assert kernel.weights[0] == pytest.approx(1 - .5*np.exp(-1000/600000), abs=3e-8)
    assert kernel.e_pre[0] == kernel.e_da[0] == 0


def test_dopamine_accelerates_forgetting_and_disabling_is_exact():
    a,b = single(tau_forget_ms=1000, beta=2), single(tau_forget_ms=1000, beta=2)
    a.weights[:] = b.weights[:] = .5
    a.step([0], [0], 100)
    b.step([0], [1], 100)
    assert a.weights[0] == pytest.approx(1-.5*np.exp(-.1), abs=3e-8)
    assert b.weights[0] == pytest.approx(1-.5*np.exp(-.3), abs=3e-8)
    off = single()
    off.weights[:] = .5
    off.step([0], [0], 1000)
    assert off.weights[0] == .5


def test_bounds_logging_and_decade_eta_checks_are_executed():
    checks, metrics = software_checks()
    assert all(c['status'] == 'PASS' for c in checks), checks
    json.dumps(checks, allow_nan=False)
    assert metrics['eta_decade_ratio'] == pytest.approx(10., abs=.001)


def test_compartment_and_presynaptic_indexing_do_not_leak():
    kernel = NormalizedPlasticity(2, 2, np.array([0,0,1]), np.array([0,1,0]),
                                  [1.,2.,3.], reference_parameters())
    kernel.step([1,0], [1,0], 100)
    assert kernel.weights[0] < 1
    assert kernel.weights[1] == 2 and kernel.weights[2] == 3


def test_per_compartment_signed_rules_reverse_only_selected_edges():
    kernel = NormalizedPlasticity(1,2,np.array([0,0]),np.array([0,1]),[1.,1.],
                                  reference_parameters(),compartment_sign=[1,-1],compartment_scale=[1,2])
    kernel.step([1], [1,1], 100)
    assert kernel.weights[0] < 1 < kernel.weights[1]
    assert kernel.weights[1]-1 == pytest.approx(2*(1-kernel.weights[0]), abs=2e-7)


def test_hz_normalization_records_saturation_without_wrapping():
    drive, count = normalize_kc_rates([0,25,50,100,3e38],50)
    np.testing.assert_array_equal(drive,[0,.5,1,1,1])
    assert drive.dtype == np.float32 and count == 2
    with pytest.raises(ValueError): normalize_kc_rates([-1],50)
    with pytest.raises(ValueError): normalize_kc_rates([1],0)


@pytest.mark.parametrize('kind',['shape','negative','nan','above_unit_drive','above_field_guard','dt'])
def test_bad_inputs_rejected(kind):
    rate,c,dt=[1],[1],1
    if kind == 'shape': rate=[1,2]
    if kind == 'negative': c=[-1]
    if kind == 'nan': rate=[np.nan]
    if kind == 'above_unit_drive': rate=[1.1]
    if kind == 'above_field_guard': c=[5.1]
    if kind == 'dt': dt=0
    with pytest.raises(ValueError): single().step(rate,c,dt)


@pytest.mark.parametrize('changes',[
    {'eta_per_ms':1e40},{'A1':1e40},{'A2':1e-50},
    {'tau_forget_ms':1e-300},{'tau_pre_ms':0},
])
def test_parameters_must_survive_float32_conversion(changes):
    with pytest.raises(ValueError): single(**changes)


@pytest.mark.parametrize('kind',['forcing','candidate','time','tiny_time','input','upper','nonfinite_state'])
def test_rejected_proposals_do_not_clip_or_mutate_state(kind):
    changes = {'A1':3e38} if kind == 'forcing' else {'eta_per_ms':3e38} if kind == 'candidate' else {}
    kernel=single(**changes)
    rate,c,dt=[1.],[1.],1.
    if kind == 'forcing': kernel.e_pre[:]=1.;c=[5.]
    if kind == 'candidate': kernel.e_pre[:]=1.;dt=1000.
    if kind == 'time': dt=1e-50
    if kind == 'tiny_time': dt=np.nextafter(0.,1.)
    if kind == 'input': rate=[1e40]
    if kind == 'upper': kernel.w0[:]=3e38
    if kind == 'nonfinite_state': kernel.e_da[:]=np.nan
    before=[v.copy() for v in (kernel.weights,kernel.e_pre,kernel.e_da)]
    with pytest.raises((ValueError,FloatingPointError)): kernel.step(rate,c,dt)
    for a,b in zip((kernel.weights,kernel.e_pre,kernel.e_da),before): np.testing.assert_array_equal(a,b)
    assert kernel.weight_clamp_events == kernel.total_absolute_weight_change == 0


@pytest.mark.parametrize('delays',[None,list(reversed(REFERENCE_DELAYS_MS)),[0]*12])
def test_missing_or_wrong_delay_axis_rejected(delays):
    curve={'delta_w':list(REFERENCE_DELTA_W)}
    if delays is not None: curve['delays_ms']=delays
    with pytest.raises(AssertionError,match='ordered reference delays'): assert_reference_curve(curve)


@pytest.mark.parametrize('values',[[0.]*11,[[0.]*12],[np.nan]*12])
def test_wrong_reference_shape_or_nonfinite_rejected(values):
    with pytest.raises(AssertionError,match='twelve finite'):
        assert_reference_curve({'delays_ms':REFERENCE_DELAYS_MS,'delta_w':values})


def test_compartment_rule_table_declares_every_default_as_assumption():
    root=Path(__file__).parents[1]
    names=('g1','g2','g3','g4','g5','bp1','bp2','b1','b2','a1','a2','a3','ap1','ap2','ap3')
    signs,scales,rows=load_compartment_rules(root,names)
    assert len(rows)==15 and all(r['provenance']=='ASSUMPTION' and r['citation'] for r in rows)
    np.testing.assert_array_equal(signs,1)
    np.testing.assert_array_equal(scales,1)
def test_receptor_prerequisite_recursively_rejects_changed_compartment_reference(tmp_path, monkeypatch):
    from flybrain.fetch import checksum
    from flybrain.neuromod import plasticity, compartments

    # The saved field/receptor files stay unchanged while an upstream CSV is
    # edited. This exercises the actual recursive loaders on a tiny map.
    monkeypatch.setattr(plasticity, "require_source_gate", lambda root: {})
    monkeypatch.setattr(compartments, "require_source_gate", lambda root: {})
    build, config = tmp_path / "build", tmp_path / "config"
    build.mkdir()
    config.mkdir()
    (tmp_path / "implementation.py").write_text("version one")
    reference = config / "mb_compartment_reference.csv"
    reference.write_text("original reference")
    (build / "compartments_metadata.json").write_text("{}")
    np.savez(build / "compartments.npz", names=["g1"], membership=np.ones((1, 1), bool),
             adjacency=np.zeros((1, 1)), mb_assignment=np.array([0]), model_root_ids=np.array([1], np.int64))
    common = {"status": "PASS", "checks": [{"status": "PASS"}],
              "implementation_hashes": {"implementation.py": checksum(tmp_path / "implementation.py")},
              "config_hashes": {reference.name: checksum(reference)},
              "artifact_hashes": {"compartments.npz": checksum(build / "compartments.npz")}}
    compartment_record = common | {
        "dependency_hashes": {"implementation.py": checksum(tmp_path / "implementation.py")},
        "neuropil_source_hashes": {"implementation.py": checksum(tmp_path / "implementation.py")}}
    cp = build / "validation_neuromod_compartments.json"
    cp.write_text(json.dumps(compartment_record))
    field_record = common | {"dependency_hashes": {"build/validation_neuromod_compartments.json": checksum(cp)}}
    fp = build / "validation_neuromod_field.json"
    fp.write_text(json.dumps(field_record))
    # Receptor-level configs need not contain the upstream CSV.
    (config / "receptors.csv").write_text("receptor config")
    receptor_record = common | {"gate": "V-NM-A",
        "config_hashes": {"receptors.csv": checksum(config / "receptors.csv")},
        "dependency_hashes": {"build/validation_neuromod_field.json": checksum(fp)},
        "base_artifact_hashes": common["artifact_hashes"],
        "base_config_hashes": {"receptors.csv": checksum(config / "receptors.csv")}}
    (build / "validation_neuromod_receptors.json").write_text(json.dumps(receptor_record))
    assert require_receptor_gate(tmp_path)["status"] == "PASS"
    reference.write_text("changed reference")
    with pytest.raises(ValueError, match="Compartment input/artifact changed: mb_compartment_reference.csv"):
        require_receptor_gate(tmp_path)


def test_decayed_rates_round_to_zero_without_relaxing_parameter_guards():
    drive,count=normalize_kc_rates([1e-50,1e-300,0.,50.,1e300],50.)
    np.testing.assert_array_equal(drive,np.array([0,0,0,1,1],np.float32))
    assert count==1
    with pytest.raises(ValueError,match='underflows'):
        normalize_kc_rates([1.],1e-50)
