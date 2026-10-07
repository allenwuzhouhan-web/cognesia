"""DoOR provenance, missingness and assumed afferent dynamics; no biology gate."""
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import pytest

from flybrain.eye import Phototransduction
from flybrain.neuromod.odour import (
    ALIASES, SOURCE_FILES, BASELINE_NOTE, OdourLibrary, OdourTransduction,
    OdourEventSampler, SourceUnavailable, fetch_door, validate_tables,
)

ROOT = Path(__file__).parents[1]
PARAMETERS = {"odour_max_rate_hz": 150., "odour_adaptation_tau_ms": 200.,
              "odour_transduction_tau_ms": 12., "odour_half_saturation": .2,
              "odour_adaptation_strength": .5, "odour_baseline_mode": "source_sfr"}


def neuron_fixture():
    return pd.DataFrame({"root_id": [9, 8, 7, 6, 5, 4, 3],
                         "cell_type": ["ORN_DM1", "ORN_DM1", "ORN_VM6m", None,
                                       "ORN_DM2", "ORN_DL2d", "KCg"],
                         "cell_class": ["olfactory"] * 6 + ["KC"],
                         "super_class": ["sensory"] * 6 + ["central"]})


def tables_fixture():
    keys = ["SFR", ALIASES["OCT"], ALIASES["MCH"]]
    response = pd.DataFrame({"Or42b": [.2, .5, .1], "Or22a": [.3, np.nan, .3],
                             "ac3A": [.1, .5, .4]}, index=keys)
    mapping = pd.DataFrame({"receptor": ["Or42b", "Or22a", "ac3A"],
                            "code": ["DM1", "DM2", "DL2d"],
                            "glomerulus": ["DM1", "DM2", "DL2d/v"],
                            "comment": [None, None, "separation unclear"]})
    odors = pd.DataFrame({"Name": ["sfr", "3-octanol", "4-methylcyclohexanol"],
                          "InChIKey": keys, "CAS": ["SFR", "589-98-0", "589-91-3"]})
    return response, mapping, odors


def library_fixture():
    return OdourLibrary(neuron_fixture(), *tables_fixture())


def test_signed_evoked_delta_and_zero_missing_are_separate():
    library = library_fixture()
    oct_response = library.responses("OCT")
    mch_response = library.responses("MCH")
    dm1, dm2, vm6 = [library.types.index(x) for x in ["ORN_DM1", "ORN_DM2", "ORN_VM6m"]]
    assert oct_response.values[dm1] == pytest.approx(.3)
    assert mch_response.values[dm1] == pytest.approx(-.1)
    assert oct_response.values[dm2] == 0
    assert oct_response.metadata["status"][dm2] == "missing_odor_measurement"
    assert mch_response.metadata["status"][dm2] == "measured_zero_evoked_response"
    assert oct_response.metadata["status"][vm6] == "unmapped_glomerulus"
    assert oct_response.metadata["spontaneous_au"][vm6] is None
    assert oct_response.metadata["baseline_input_au"][vm6] == 0
    assert library.baseline[dm2] == .3  # independent SFR remains available
    assert oct_response.metadata["baseline_note"] == BASELINE_NOTE
    assert oct_response.metadata["measured_named_types"] == 1
    assert oct_response.metadata["measured_neurons"] == 2
    assert oct_response.metadata["total_orn_neurons"] == 6
    assert oct_response.metadata["untyped_neurons"] == 1
    np.testing.assert_array_equal(library.responses("589-98-0").values, oct_response.values)
    np.testing.assert_array_equal(library.responses("3-OCTANOL").values, oct_response.values)


def test_mapping_does_not_invent_vm6_split_or_duplicate_ac3a():
    library = library_fixture()
    for name in ["ORN_VM6m", "ORN_DL2d"]:
        i = library.types.index(name)
        assert library.baseline[i] == 0
        assert library.responses("OCT").values[i] == 0
    with pytest.raises(ValueError, match="Unknown or ambiguous"):
        library.responses("imaginary odor")
    rows = library.map_rows()
    assert len(rows) == 2 * len(library.types)
    assert not rows.duplicated(["odor", "orn_type"]).any()
    assert rows.baseline_note.eq(BASELINE_NOTE).all()


def test_per_neuron_order_and_untyped_zero():
    library = library_fixture()
    values = np.arange(len(library.types), dtype=float) + 1
    mapped = library.per_neuron(values)
    np.testing.assert_array_equal(library.root_ids, [9, 8, 7, 6, 5, 4])
    assert mapped[0] == mapped[1] == values[library.types.index("ORN_DM1")]
    assert mapped[3] == 0
    with pytest.raises(ValueError):
        library.per_neuron([np.nan] * len(library.types))
    with pytest.raises(ValueError):
        library.per_neuron(np.zeros(1))


def test_inhibitory_odor_reduces_firing_relative_to_same_baseline():
    library = library_fixture()
    rest, inhibited = [OdourTransduction(library, PARAMETERS) for _ in range(2)]
    baseline = rest.step(None, 0, 1)
    response = inhibited.step("MCH", 1, 1)
    assert 0 < response[0] < baseline[0]
    assert response[3] == response[2] == response[5] == 0  # unknown/unmapped/ambiguous
    assert response[4] == baseline[4]  # measured zero evoked delta retains tonic SFR
    missing = OdourTransduction(library, PARAMETERS).step("OCT", 1, 1)
    assert missing[4] == baseline[4]  # missing measurement is zero EVOKED only


def test_zero_baseline_mode_records_lost_inhibition():
    transduction = OdourTransduction(library_fixture(), PARAMETERS | {"odour_baseline_mode": "zero"})
    assert transduction.metadata["zero_baseline_discards_inhibition"] is True
    assert transduction.step("MCH", 1, 1)[0] == 0


def test_eye_form_and_analytic_adaptation():
    library = library_fixture()
    p = PARAMETERS | {"odour_baseline_mode": "zero"}
    odor = OdourTransduction(library, p)
    eye = Phototransduction(len(library.types), {
        "adaptation_tau_ms": 200., "phototransduction_tau_ms": 12.,
        "half_saturation": .2, "adaptation_strength": .5, "maximum_drive_mv": 1.,
    })
    activation = np.maximum(library.responses("OCT").values, 0)
    for _ in range(100):
        odor.step("OCT", 1, 1)
        expected = eye.step(activation, 1) * 150
        np.testing.assert_allclose(odor.rates_hz, expected, rtol=2e-14, atol=2e-14)
    np.testing.assert_allclose(odor.adaptation, activation * -np.expm1(-100 / 200), rtol=1e-14)
    odor.step(None, 0, 100)
    np.testing.assert_allclose(odor.adaptation, activation * -np.expm1(-.5) * np.exp(-.5), rtol=1e-14)


@pytest.mark.parametrize("dt,intensity", [(0, 1), (-1, 1), (np.nan, 1), (1, 2), (1, -.1), (1, np.nan)])
def test_invalid_step_inputs(dt, intensity):
    with pytest.raises(ValueError):
        OdourTransduction(library_fixture(), PARAMETERS).step("OCT", intensity, dt)


def test_poisson_source_events_seed_and_units():
    first, second = OdourEventSampler(91), OdourEventSampler(91)
    for _ in range(5):
        np.testing.assert_array_equal(first.sample(np.array([0, 100, 250]), 2),
                                      second.sample(np.array([0, 100, 250]), 2))
    # 1000 Hz over 1000 ms: expected count is 1000, not one clipped event.
    counts = first.sample(np.full(10000, 1000.), 1000)
    assert counts.mean() == pytest.approx(1000, abs=2)
    assert np.all(counts > 1)
    with pytest.raises(ValueError):
        first.sample(np.array([-1]), 1)


def test_source_fetch_failure_and_corruption_are_distinct(tmp_path, monkeypatch):
    def offline(*args, **kwargs):
        raise OSError("offline fixture")
    monkeypatch.setattr("flybrain.neuromod.odour.urlopen", offline)
    with pytest.raises(SourceUnavailable, match="download failed"):
        fetch_door(tmp_path)
    folder = tmp_path / "data/raw/neuromod/door"
    # Verify all existing files before a missing earlier source can trigger fallback.
    (folder / "odor.csv").write_text("corrupt")
    with pytest.raises(ValueError, match="checksum mismatch"):
        fetch_door(tmp_path)


def test_no_synthetic_fallback_on_corruption(tmp_path, monkeypatch):
    monkeypatch.setattr("flybrain.neuromod.odour.require_source_gate", lambda root: {})
    monkeypatch.setattr(pd, "read_parquet", lambda path: neuron_fixture())
    folder = tmp_path / "data/raw/neuromod/door"
    folder.mkdir(parents=True)
    (folder / "odor.csv").write_text("modified")
    with pytest.raises(ValueError, match="checksum mismatch"):
        OdourLibrary.from_root(tmp_path, download=False, allow_synthetic=True)


def test_synthetic_fallback_requires_explicit_option_and_records_reason(tmp_path, monkeypatch):
    monkeypatch.setattr("flybrain.neuromod.odour.require_source_gate", lambda root: {})
    monkeypatch.setattr(pd, "read_parquet", lambda path: neuron_fixture())
    with pytest.raises(SourceUnavailable):
        OdourLibrary.from_root(tmp_path, download=False)
    with pytest.raises(SourceUnavailable):
        OdourLibrary.from_root(tmp_path, download=False, allow_synthetic=True)
    def offline(*args, **kwargs):
        raise OSError("actual download attempt failed in fixture")
    monkeypatch.setattr("flybrain.neuromod.odour.urlopen", offline)
    one = OdourLibrary.from_root(tmp_path, download=True, allow_synthetic=True, seed=21)
    two = OdourLibrary.from_root(tmp_path, download=True, allow_synthetic=True, seed=21)
    before = one.responses("OCT")
    one.responses("MCH")
    np.testing.assert_array_equal(before.values, two.responses("OCT").values)
    np.testing.assert_array_equal(before.values, one.responses("OCT").values)
    assert before.metadata["label"] == "SYNTHETIC ODOUR"
    assert "discrimination" in before.metadata["limitation"]
    assert before.metadata["source_failure"]
    assert before.metadata["measured_named_types"] == 0


@pytest.mark.parametrize("invalid", ["duplicate", "infinite", "negative", "missing_sfr", "ambiguous_code"])
def test_bad_tables_cannot_be_used(invalid):
    response, mapping, odors = tables_fixture()
    if invalid == "duplicate":
        response = pd.concat([response, response.iloc[:1]])
    elif invalid == "infinite":
        response.iloc[0, 0] = np.inf
    elif invalid == "negative":
        response.iloc[0, 0] = -.01
    elif invalid == "missing_sfr":
        response = response.drop(index="SFR")
    elif invalid == "ambiguous_code":
        mapping = pd.concat([mapping, mapping.iloc[:1]])
    with pytest.raises(ValueError):
        validate_tables(response, mapping, odors)


@pytest.mark.integration
def test_pinned_door_shapes_hashes_identity_and_actual_coverage(tmp_path):
    folder = ROOT / "data/raw/neuromod/door"
    if not all((folder / name).exists() for name in SOURCE_FILES):
        pytest.skip("Pinned DoOR files not cached")
    target = tmp_path / "data/raw/neuromod/door"
    target.mkdir(parents=True)
    for name in SOURCE_FILES:
        shutil.copyfile(folder / name, target / name)
    tables, audit = fetch_door(tmp_path, download=False)
    assert all(len(v["first_three_rows"]) == 3 for v in audit.values())
    neurons_path = ROOT / "build/neurons.parquet"
    if not neurons_path.exists():
        pytest.skip("FlyWire neuron build unavailable")
    library = OdourLibrary(pd.read_parquet(neurons_path), tables["door_response_matrix.csv"],
                          tables["door_mappings.csv"], tables["odor.csv"], source_audit=audit)
    assert len(library.types) == 53
    for name, count, cells, cas in [("OCT", 28, 1207, "589-98-0"), ("MCH", 22, 975, "589-91-3")]:
        response = library.responses(name)
        assert response.values.shape == (53,)
        assert response.metadata["CAS"] == cas
        assert response.metadata["measured_named_types"] == count
        assert response.metadata["measured_neurons"] == cells
        assert np.count_nonzero(response.values < 0) == 4
    assert len(library.map_rows()) == 106


def build_provenance_fixture(tmp_path, monkeypatch):
    """Artificial complete-size ORN population for validator/provenance software tests."""
    from flybrain.fetch import checksum, stat_signature
    import flybrain.neuromod.odour as module
    types = ['ORN_DM1', 'ORN_DM2'] + [f'ORN_X{i:02}' for i in range(51)]
    cells = [types[i % 53] for i in range(2275)] + [None] * 4
    neurons = pd.DataFrame({'root_id': np.arange(2279, dtype=np.int64), 'cell_type': cells,
                           'cell_class': 'olfactory', 'super_class': 'sensory'})
    library = OdourLibrary(neurons, *tables_fixture())
    build, config, raw = [tmp_path / path for path in ('build', 'config', 'data/raw')]
    for path in (build, config, raw):
        path.mkdir(parents=True)
    config_path = config / 'neuromod.yaml'
    entries = {key: {'value': value, 'unit': 'fixture', 'source': 'ASSUMPTION'} for key, value in PARAMETERS.items()}
    config_path.write_text(json.dumps({'parameters': entries}))
    source_file = raw / 'fixture.csv'
    source_file.write_text('artificial source\n')
    gate = {'status': 'PASS', 'source_hashes': {'fixture.csv': checksum(source_file)},
            'source_stats': {'fixture.csv': stat_signature(source_file)},
            'base_artifact_hashes': {}, 'base_config_hashes': {}}
    (build / 'validation_neuromod_sources.json').write_text(json.dumps(gate))
    code = tmp_path / 'src/flybrain/neuromod/odour.py'
    code.parent.mkdir(parents=True)
    shutil.copyfile(Path(module.__file__), code)
    door = raw / 'neuromod/door/fixture.csv'
    door.parent.mkdir(parents=True)
    door.write_text('artificial DoOR source\n')
    library.source_audit = {'fixture.csv': {'sha256': checksum(door), 'source_stats': stat_signature(door)}}
    monkeypatch.setattr(module, 'require_source_gate', lambda root: gate)
    monkeypatch.setattr(OdourLibrary, 'from_root', classmethod(lambda cls, *args, **kwargs: library))
    return config_path, source_file, door


def test_odour_validator_standard_provenance_remains_current_in_report(tmp_path, monkeypatch):
    from flybrain.neuromod.odour import build_odours
    from flybrain.report import _current_result
    build_provenance_fixture(tmp_path, monkeypatch)
    result = build_odours(tmp_path, download=False)
    assert result['status'] == 'PASS', result['checks']
    assert 'neuromod/door/fixture.csv' in result['source_hashes']
    assert result['source_stats']['neuromod/door/fixture.csv']
    assert result['config_hashes']['neuromod.yaml']
    assert result['implementation_hashes']['src/flybrain/neuromod/odour.py']
    assert result['dependency_hashes']['build/validation_neuromod_sources.json']
    assert _current_result(result, tmp_path, {}, {}, [], [])['status'] == 'PASS'


@pytest.mark.parametrize('change', ['configuration', 'door_source'])
def test_odour_validator_rejects_changes_during_transduction(tmp_path, monkeypatch, change):
    from flybrain.neuromod.odour import build_odours
    config_path, _, door = build_provenance_fixture(tmp_path, monkeypatch)
    original = OdourTransduction.step
    def mutate_after_loading(self, *args, **kwargs):
        value = original(self, *args, **kwargs)
        path = config_path if change == 'configuration' else door
        with path.open('a') as stream:
            stream.write(' ')
        return value
    monkeypatch.setattr(OdourTransduction, 'step', mutate_after_loading)
    result = build_odours(tmp_path, download=False)
    assert result['status'] == 'FAIL'
    expected = ('unchanged_config_hashes_neuromod.yaml' if change == 'configuration'
                else 'unchanged_source_hashes_neuromod/door/fixture.csv')
    assert expected in result['failed_checks']
