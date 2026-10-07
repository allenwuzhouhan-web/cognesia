"""Exact source parsing, order preservation and fail-closed stage 1 evidence.

Synthetic fixtures test software, not biology. The integration test uses Patch 1
references and normative selectors; primary release differences still fail.
"""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from flybrain.fetch import checksum
from flybrain.neuromod.sources import (
    AMINERGIC, EXPECTED_AUDIT, EXPECTED_MOTIFS, RAW_FILES, block_masks,
    build_sources, model_subset, parse_positive_nt, require_source_gate,
    source_masks, transmitter_audit, gate_status, reference_check, population_inventory,
)


@pytest.mark.parametrize("value,expected", [
    (None, set()), (np.nan, set()), (pd.NA, set()), ("", set()),
    (" dopamine ; nitric oxide, sNPF ", {"dopamine", "nitric oxide", "snpf"}),
    ("dopamine-negative; tyramine, OCTOPAMINE-negative", {"tyramine"}),
    ("dopamine-negative; dopamine; dopamine", {"dopamine"}),
    ("dopamine-like; predopamine; not dopamine", {"dopamine-like", "predopamine", "not dopamine"}),
])
def test_positive_known_nt_exact_token_rule(value, expected):
    assert parse_positive_nt(value) == expected


def source_fixture():
    return pd.DataFrame({
        "cell_type": ["KCg", "OA-AL2b2", "CSD", "PAM01", "unknown", "KC_test"],
        "known_nt": ["acetylcholine; sNPF", "tyramine", "serotonin; dopamine-negative",
                     "dopamine; nitric oxide", None, "dopamine; acetylcholine"],
        "top_nt": ["dopamine", "octopamine", "dopamine", "acetylcholine", "dopamine", "dopamine"],
    })


def test_sources_never_use_predictor_and_oa_named_tyramine_is_not_oa():
    table = source_fixture()
    first = source_masks(table)
    table.top_nt = ["serotonin", "gaba", "octopamine", "tyramine", "nitric oxide", "gaba"]
    second = source_masks(table)
    for species in first:
        np.testing.assert_array_equal(first[species], second[species])
    assert not first["OA"][1]
    assert first["TA"][1]
    assert not first["DA"][2]  # dopamine-negative is not a positive source.
    assert not any(first[key][4] for key in first)  # Unannotated prediction only.
    assert first["DA"][3] and first["NO"][3]


def test_defect_d_excludes_kc_aminergic_but_preserves_annotated_snpf():
    masks = source_masks(source_fixture())
    assert all(not masks[species][0] and not masks[species][5] for species in AMINERGIC)
    assert masks["sNPF"][0]


def test_predictor_audit_changes_without_changing_ground_truth_sources():
    table = source_fixture()
    before = transmitter_audit(table)
    table.top_nt = "gaba"
    after = transmitter_audit(table)
    assert [x["positive_known_nt"] for x in before] == [x["positive_known_nt"] for x in after]
    assert [x["predicted_top_nt"] for x in before] != [x["predicted_top_nt"] for x in after]


def test_model_subset_preserves_int64_root_order_and_missing_annotation():
    roots = np.array([720575940596125870, 720575940596125868, 720575940596125869], dtype=np.int64)
    ann = pd.DataFrame({"root_id": roots[[1, 0]], "known_nt": ["dopamine", "serotonin"]})
    result = model_subset(pd.DataFrame({"Unnamed: 0": roots, "Completed": True}), ann)
    np.testing.assert_array_equal(result.root_id, roots)
    np.testing.assert_array_equal(result.model_index, [0, 1, 2])
    assert result.root_id.dtype == np.dtype("int64")
    assert result.known_nt.iloc[0] == "serotonin"
    assert pd.isna(result.known_nt.iloc[2])


@pytest.mark.parametrize("invalid", ["duplicate", "float"])
def test_model_subset_rejects_ambiguous_roots(invalid):
    roots = pd.DataFrame({"root_id": [1, 2]})
    ann = pd.DataFrame({"root_id": [1, 1] if invalid == "duplicate" else [1., 2.]})
    with pytest.raises(ValueError):
        model_subset(roots, ann)


def test_block_selectors_do_not_inflate_projection_neurons_with_orns():
    table = pd.DataFrame({"cell_type": ["ORN_DA1", "DA1_lPN", "CX_test", "CSD"],
                          "cell_class": ["olfactory", "ALPN", "CX", None],
                          "super_class": ["sensory", "central", "central", "central"]})
    blocks = block_masks(table)
    np.testing.assert_array_equal(blocks["PN"], [False, True, False, False])
    np.testing.assert_array_equal(blocks["ORN"], [True, False, False, False])
    np.testing.assert_array_equal(blocks["CX"], [False, False, True, False])


def test_missing_release_is_saved_as_failure(tmp_path):
    result = build_sources(tmp_path)
    assert result["status"] == "FAIL"
    assert result["failed_checks"] == ["source_stage_execution"]
    saved = json.loads((tmp_path / "build/validation_neuromod_sources.json").read_text())
    assert saved == result
    with pytest.raises(ValueError, match="not PASS"):
        require_source_gate(tmp_path)


def gate_fixture(tmp_path):
    """A tiny artificial integrity-manifest fixture, never model evidence."""
    build = tmp_path / "build"
    raw = tmp_path / "data/raw"
    build.mkdir()
    raw.mkdir(parents=True)
    for name in RAW_FILES:
        (raw / name).write_text("software test fixture")
    artifact = build / "fixture.csv"
    artifact.write_text("synthetic,artifact\n1,2\n")
    result = {"status": "PASS", "failed_checks": [],
              "checks": [{"status": "PASS"}],
              "source_hashes": {name: checksum(raw / name) for name in RAW_FILES},
              "artifact_hashes": {artifact.name: checksum(artifact)}}
    path = build / "validation_neuromod_sources.json"
    path.write_text(json.dumps(result))
    (build / "neuromod_sources_manifest.json").write_text(json.dumps({
        "status": "PASS", "validation_sha256": checksum(path)}))
    return path, artifact, raw / RAW_FILES[0]


@pytest.mark.parametrize("tamper,match", [(0, "record was modified"), (1, "artifact changed"), (2, "source changed")])
def test_integrity_gate_rejects_modified_evidence(tmp_path, tamper, match):
    targets = gate_fixture(tmp_path)
    assert require_source_gate(tmp_path)["status"] == "PASS"
    with targets[tamper].open("a") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match=match):
        require_source_gate(tmp_path)


def test_integrity_gate_rejects_red_check_under_pass_label(tmp_path):
    path, _, _ = gate_fixture(tmp_path)
    result = json.loads(path.read_text())
    result["checks"][0]["status"] = "FAIL"
    path.write_text(json.dumps(result))
    manifest = path.with_name("neuromod_sources_manifest.json")
    manifest.write_text(json.dumps({"status": "PASS", "validation_sha256": checksum(path)}))
    with pytest.raises(ValueError, match="evidence is incomplete"):
        require_source_gate(tmp_path)


@pytest.mark.integration
def test_release_audit_passes_patch1_with_exact_primary_measurements(isolated_validation_root):
    root = Path(os.environ.get("FLYBRAIN_DATA_ROOT", Path(__file__).resolve().parents[1]))
    if not (root / "build/build_summary.json").exists() or not all((root / "data/raw" / f).exists() for f in RAW_FILES):
        pytest.skip("Requires the downloaded and assembled real base release")
    root = isolated_validation_root(root)
    result = build_sources(root)
    assert "source_stage_execution" not in result["failed_checks"]
    for row in result["audit"]:
        assert tuple(row[k] for k in ("positive_known_nt", "predicted_top_nt", "agree")) == EXPECTED_AUDIT[row["transmitter"]]
    for name, expected in EXPECTED_MOTIFS.items():
        row = result["motifs"][name]
        assert tuple(row[k] for k in ("edges", "synapses", "median_synapses_per_edge")) == expected
    assert result["status"] == "PASS"
    assert result["failed_checks"] == []
    assert result["warning_checks"] == []
    assert not result["artifacts_usable_for_simulation"]
    assert result["artifacts_usable_for_source_layer"]
    assert result["core"]["neurons"] == 13300
    assert result["core"]["block_sum"] == 13302
    assert result["core"]["edges"] == 1161917
    assert result["core"]["synapses"] == 4581576
    assert result["core"]["overlaps"][0]["cell_types"] == {"OA-VUMa5": 2}
    assert result["core"]["overlaps"][0]["blocks"] == ["ALLN", "OA_named"]
    assert len(result["core"]["overlaps"]) == 1
    assert result["KC_sNPF_sources"] == 4133
    assert result["source_counts"]["sNPF"]["model"] == 5034
    assert result["MB_DAN_nitric_oxide_counts"] == {"PAM01": 40, "PAM05": 20, "PAM06": 2, "PPL101": 2, "PPL103": 2}
    assert result["inventory"]["CX"]["named_types"] == 229
    assert result["inventory"]["CX"]["type_categories"] == 230
    assert result["inventory"]["CX"]["untyped"] == 9
    assert require_source_gate(root)["status"] == "PASS"
    overrides = pd.read_csv(root / "build/neuromod_overrides.csv")
    assert len(overrides) == 5177
    assert overrides.effective_fast_nt.eq("acetylcholine").all()
    assert overrides.effective_fast_sign.eq(1).all()
    assert overrides.exclude_aminergic_source.all()
    sources = pd.read_parquet(root / "build/neuromod_sources.parquet")
    assert not sources.cell_type.fillna("").str.startswith("KC").any()
    peptides = pd.read_parquet(root / "build/neuromod_peptide_sources.parquet")
    assert peptides.cell_type.fillna("").str.startswith("KC").sum() == 4133
    assert sources.root_id.dtype == np.dtype("int64")
    assert peptides.model_index.lt(0).sum() > 0  # Outside-model rows were retained.
    core = pd.read_parquet(root / "build/neuromod_core_diagnostic.parquet")
    assert core.model_index.is_monotonic_increasing
    assert len(core) == 13300
    for name, digest in result["base_artifact_hashes"].items():
        assert checksum(root / "build" / name) == digest


@pytest.mark.parametrize("key,relative", [
    ("base_artifact_hashes", "build/base_csr.npz"),
    ("base_config_hashes", "config/base.yaml"),
    ("config_hashes", "config/neuromod.yaml"),
    ("implementation_hashes", "src/flybrain/neuromod/sources.py"),
])
def test_integrity_gate_covers_base_configuration_and_implementation(tmp_path, key, relative):
    path, _, _ = gate_fixture(tmp_path)
    covered = tmp_path / relative
    covered.parent.mkdir(parents=True, exist_ok=True)
    covered.write_text("artificial hash fixture")
    result = json.loads(path.read_text())
    name = relative if key == "implementation_hashes" else covered.name
    result[key] = {name: checksum(covered)}
    path.write_text(json.dumps(result))
    path.with_name("neuromod_sources_manifest.json").write_text(json.dumps({
        "status": "PASS", "validation_sha256": checksum(path)}))
    assert require_source_gate(tmp_path)["status"] == "PASS"
    covered.write_text("changed")
    with pytest.raises(ValueError, match=key):
        require_source_gate(tmp_path)


def test_patch1_normative_selectors_preserve_prefixes_and_require_sensory_orns():
    table = pd.DataFrame({
        'cell_type': ['KC-new', 'MBON-new', 'PAM-new', 'PPL1-new', 'PPL2-new', 'PAL-new',
                      'APL-new', 'DPM-new', 'OA-new', 'VPM-new', 'VUM-new', 'CSD-new',
                      'ORN_fake', None, 'unrelated'],
        'cell_class': [None] * 12 + ['olfactory', 'olfactory', 'Kenyon_Cell'],
        'super_class': ['central'] * 13 + ['sensory', 'central'],
    })
    masks = block_masks(table)
    expected = {'KC': [0], 'MBON': [1], 'DAN': [2, 3, 4, 5], 'APL_DPM': [6, 7],
                'OA_named': [8, 9, 10], 'CSD': [11], 'ORN': [13],
                'PN': [], 'ALLN': [], 'CX': [], 'DN': [], 'endocrine': []}
    for name, indices in expected.items():
        assert np.flatnonzero(masks[name]).tolist() == indices


def test_population_inventory_keeps_untyped_cells_and_reports_both_type_counts():
    table = pd.DataFrame({'cell_type': ['FB1', None, '', 'FB1'],
                          'side': ['left', 'right', None, 'center']})
    row = population_inventory(table, {'CX': np.ones(4, dtype=bool)})['CX']
    assert (row['neurons'], row['named_types'], row['type_categories'], row['untyped']) == (4, 1, 2, 2)
    assert row['side_counts'] == {'left': 1, 'right': 1, '__UNKNOWN__': 1, 'center': 1}


def test_no_cotransmission_is_per_neuron_not_per_type():
    table = pd.DataFrame({'cell_type': ['PAM06'] * 3,
                          'known_nt': ['dopamine, nitric oxide', 'dopamine; nitric oxide', 'dopamine']})
    masks = source_masks(table)
    assert masks['DA'].tolist() == [True, True, True]
    assert masks['NO'].tolist() == [True, True, False]


def test_population_definition_drift_warns_but_primary_data_mismatch_fails():
    population = reference_check('core_neurons', 13301, 13300, kind='population_definition')
    assert population['status'] == 'WARNING'
    assert gate_status([population]) == 'PASS'
    primary = reference_check('motif_KC->MBON', 62260, 62261)
    assert primary['status'] == 'FAIL'
    assert gate_status([population, primary]) == 'FAIL'
    assert gate_status([{'status': 'WARNING', 'kind': 'primary_data'}]) == 'FAIL'


def test_integrity_gate_allows_population_warning_with_pass_label(tmp_path):
    path, _, _ = gate_fixture(tmp_path)
    result = json.loads(path.read_text())
    result['checks'] = [reference_check('core_neurons', 13301, 13300, kind='population_definition')]
    path.write_text(json.dumps(result))
    path.with_name('neuromod_sources_manifest.json').write_text(json.dumps({
        'status': 'PASS', 'validation_sha256': checksum(path)}))
    assert require_source_gate(tmp_path)['status'] == 'PASS'
