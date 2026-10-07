"""Compartment software checks do not require published-label agreement."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from flybrain.fetch import checksum
from flybrain.neuromod import compartments as c


def test_primary_reference_keeps_multi_territories_and_unknowns_explicit():
    root = Path(__file__).resolve().parents[1]
    reference = c.read_reference(root / "config/mb_compartment_reference.csv")
    assert len(reference) == 65
    assert reference["PPL101"]["labels"] == ("g1",)
    assert set(reference["PPL103"]["labels"]) == {"g2", "ap1"}
    assert reference["PAM07"]["labels"] == ("g4",)  # Other territories are dendrites.
    assert set(reference["PAM15"]["labels"]) == {"g5", "bp2"}
    assert reference["MBON22"]["status"] == "outside_15"
    assert reference["MBON25,MBON34"]["status"] == "ambiguous_label"
    assert set(reference["MBON15-like"]["labels"]) == {"ap1", "ap2"}
    for name in ("PAL01", "PPL107", "PPL108", "PPL201"):
        assert reference[name]["status"] == "unmapped"
        assert not reference[name]["labels"]


def test_partner_vectors_use_correct_directions_and_preserve_edge_identity(tmp_path):
    neurons = pd.DataFrame({"root_id": np.arange(5, dtype=np.int64),
                            "cell_type": ["KCg-m", "KCg-m", "PAM01", "MBON01", "PAL01"],
                            "cell_class": ["Kenyon_Cell", "Kenyon_Cell", "DAN", "MBON", "DAN"],
                            "super_class": ["central"] * 5})
    edges = pd.DataFrame({"Presynaptic_Index": [2, 0, 0, 3, 4],
                          "Postsynaptic_Index": [0, 3, 2, 1, 1],
                          "Connectivity": [2, 7, 9, 9, 0]})
    path = tmp_path / "edges.parquet"
    edges.to_parquet(path)
    result = c.kc_partner_vectors(neurons, path)
    by_type = dict(zip(result["types"], result["vectors"]))
    np.testing.assert_array_equal(by_type["PAM01"], [True, False])
    np.testing.assert_array_equal(by_type["MBON01"], [True, False])
    assert not by_type["PAL01"].any()
    np.testing.assert_array_equal(result["plastic_edges"], [[0, 3, 7]])


def clustering_fixture():
    # Fifteen disjoint partner populations, each shared by one DAN and MBON.
    types = tuple(f"type{i:02d}" for i in range(31))
    vectors = np.zeros((31, 15), bool)
    for i in range(30):
        vectors[i, i // 2] = True
    reference = {name: {"labels": (c.MB_NAMES[i // 2],), "status": "published"}
                 for i, name in enumerate(types[:-1])}
    return types, vectors, reference


def test_jaccard_clustering_is_exact_deterministic_and_excludes_empty_vectors():
    types, vectors, reference = clustering_fixture()
    first = c.cluster_partners(types, vectors, reference)
    second = c.cluster_partners(types, vectors, reference)
    np.testing.assert_array_equal(first["assignment"], second["assignment"])
    assert len(set(first["raw_cluster"]) - {-1}) == 15
    assert first["assignment"][-1] == -1
    assert first["rows"][-1]["comparison"] == "empty_partner_vector"
    for i in range(0, 30, 2):
        assert first["assignment"][i] == first["assignment"][i + 1] == i // 2
    assert all(row["comparison"] == "match" for row in first["rows"][:-1])


def test_published_labels_never_change_empirical_clusters():
    types, vectors, reference = clustering_fixture()
    first = c.cluster_partners(types, vectors, reference)
    rotated = {name: info | {"labels": (c.MB_NAMES[(i // 2 + 1) % 15],)}
               for i, (name, info) in enumerate(reference.items())}
    second = c.cluster_partners(types, vectors, rotated)
    np.testing.assert_array_equal(first["raw_cluster"], second["raw_cluster"])
    np.testing.assert_array_equal(first["linkage"], second["linkage"])
    assert not np.array_equal(first["assignment"], second["assignment"])


def test_unknown_and_ambiguous_references_are_not_counted_as_matches():
    types, vectors, reference = clustering_fixture()
    reference[types[0]] = {"labels": ("g1", "g2"), "status": "ambiguous_label"}
    reference[types[1]] = {"labels": (), "status": "unmapped"}
    result = c.cluster_partners(types, vectors, reference)
    assert result["rows"][0]["comparison"] == "ambiguous_reference_label"
    assert result["rows"][1]["comparison"] == "unmapped_reference"
    assert not result["rows"][0]["canonical_identity_supported"]
    with pytest.raises(ValueError, match="Fewer nonempty"):
        c.cluster_partners(types[:14], vectors[:14], reference)


@pytest.mark.parametrize("name,cell_class,expected", [
    ("ORN_VM6l", "olfactory", ("VM6",)),
    ("ORN_VM6m", "olfactory", ("VM6",)),
    ("ORN_VM6v", "olfactory", ("VM6",)),
    ("DA1_lPN", "ALPN", ("DA1",)),
    ("VP1m+VP2_lvPN1", "ALPN", ("VP1m", "VP2")),
    ("VP5+_l2PN,VP5+VP2_l2PN", "ALPN", ("VP2", "VP5")),
    ("VP3+_vPN", "ALPN", ("VP3",)),
    ("VP5+Z_adPN", "ALPN", ("VP5",)),
    ("M_vPNml53", "ALPN", ()), ("MZ_lv2PN", "ALPN", ()),
    ("Z_vPNml1", "ALPN", ()), ("CB4219", "ALPN", ()),
    ("DA1_lPN", "CX", ()), ("", "olfactory", ()),
])
def test_glomerular_name_parser_has_no_invented_multiglomerular_assignments(name, cell_class, expected):
    assert c.glomeruli_from_type(name, cell_class) == expected


def test_adjacency_is_spatial_assumption_not_connectome_propagation():
    names = c.MB_NAMES + ("AL_DA1", "AL_DA2", "LA_L", "ME_L", "LO_L", "LOP_L", "hemolymph")
    a = c.compartment_adjacency(names)
    assert a.dtype == np.float32
    np.testing.assert_array_equal(a, a.T)
    assert not np.diag(a).any()
    assert a[names.index("g1"), names.index("g2")] == 1
    assert a[names.index("g1"), names.index("g3")] == 0
    assert not a[names.index("AL_DA1")].any()
    assert not a[names.index("hemolymph")].any()


def test_actual_endpoint_membership_overrides_side_and_type_guessing():
    neurons = pd.DataFrame({"root_id": np.array([11, 12, 13, 14], np.int64),
                            "cell_type": ["KCg-m", "MBON01", "FB1A", "IPC"],
                            "cell_class": ["Kenyon_Cell", "MBON", "CX", "pars_intercerebralis"],
                            "super_class": ["central", "central", "central", "endocrine"],
                            "side": ["left"] * 4})
    vectors = {"types": ("MBON01",), "type_codes": np.array([-1, 0, -1, -1]),
               "kc_indices": np.array([0]), "vectors": np.array([[True]])}
    clusters = {"assignment": np.array([4], np.int16)}
    rois = {"names": ["ME_R", "FB", "EB"],
            "weights": sparse.csr_matrix([[0.1, 0, 0, 0], [0, 0, 1, 0], [0, 0.5, 0, 0]])}
    mapping, _ = c.anatomical_membership(neurons, vectors, clusters, rois)
    assert mapping.membership[mapping.names.index("ME_R"), 0]
    assert not mapping.membership[mapping.names.index("ME_L"), 0]
    assert mapping.membership[mapping.names.index("CX_FB1"), 2]
    assert mapping.membership[mapping.names.index("CX_EB"), 1]
    assert mapping.membership[mapping.names.index("hemolymph"), 3]
    assert mapping.mb_assignment[0] == -1  # KCs may belong to multiple compartments.
    assert mapping.membership[4, 0] and mapping.membership[4, 1]


def test_loader_rejects_stale_artifact_even_when_gate_says_pass(tmp_path, monkeypatch):
    build = tmp_path / "build"
    build.mkdir()
    (tmp_path / "config").mkdir()
    artifact = build / "compartments.npz"
    np.savez_compressed(artifact, names=np.array(["g1"]), membership=np.array([[True]]),
                        adjacency=np.zeros((1, 1), np.float32), mb_assignment=np.array([0], np.int16),
                        model_root_ids=np.array([123], np.int64))
    (build / "compartments_metadata.json").write_text("{}")
    other = tmp_path / "input.txt"
    other.write_text("fixture")
    config = tmp_path / "config/input.txt"
    config.write_text("fixture")
    result = {"status": "PASS", "checks": [{"status": "PASS"}],
              "artifact_hashes": {"compartments.npz": checksum(artifact)},
              "config_hashes": {"input.txt": checksum(config)},
              "implementation_hashes": {"input.txt": checksum(other)},
              "dependency_hashes": {"input.txt": checksum(other)},
              "neuropil_source_hashes": {"input.txt": checksum(other)}}
    (build / "validation_neuromod_compartments.json").write_text(json.dumps(result))
    monkeypatch.setattr(c, "require_source_gate", lambda root: {"status": "PASS"})
    assert c.load_compartments(tmp_path).names == ("g1",)
    with artifact.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="changed: compartments.npz"):
        c.load_compartments(tmp_path)


@pytest.mark.integration
def test_real_compartment_build_keeps_disagreement_as_a_result(isolated_validation_root):
    root = Path(__file__).resolve().parents[1]
    if not (root / "build/neuromod_sources_manifest.json").exists():
        pytest.skip("Requires a completed real source audit")
    root = isolated_validation_root(root)
    result = c.build_compartments(root)
    assert result["status"] == "PASS", result["failed_checks"]
    mapping = c.load_compartments(root)
    assert mapping.membership.shape[1] == 138639
    assert mapping.names[:15] == c.MB_NAMES
    assert result["coverage"]["AL_glomeruli"] == 58
    assert result["clustering"]["comparison_counts"]["disagreement"] > 0
    for cell_type in result["clustering"]["empty_types"]:
        row = next(r for r in result["clustering"]["types"] if r["cell_type"] == cell_type)
        assert row["aligned_compartment"] is None
    with np.load(root / "build/compartments.npz", allow_pickle=False) as archive:
        assert len(archive["plastic_pre"]) == 62261
        assert archive["plastic_synapses"].sum() == 256719
        assert archive["kc_partner_vectors"].shape == (65, 5177)
