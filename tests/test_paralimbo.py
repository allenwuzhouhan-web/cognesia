"""Independent fixtures for evidence transfer, exact IDs and frozen artifacts."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from flybrain import paralimbo as p
from flybrain.fetch import checksum
from flybrain.inspect_data import atomic_write_json
from flybrain.model_registry import (BANC_ID, PARALIMBO_ID, _folder, _freeze_model,
                                     _save_csr, get_model_manifest, stable_hash)
from flybrain.neuromod.sources import parse_positive_nt, positive_nt_masks

BIG = 720575940632081439


def banc_row(root_id, match="", **changes):
    row = {"root_id": root_id, "index": 0, "entity_id": f"banc:888:{root_id}",
           "fafb_match": match, "status": "FAFB_MATCH_MANUALLY_CHECKED", "side": "left",
           "cell_type": "X", "fafb_cell_type": "X", "fafb_alignment_cell_type": "",
           "cell_class": "antennal_lobe_local_neuron", "super_class": "central",
           "neurotransmitter_verified": "acetylcholine", "neuropeptide_verified": "",
           "known_nt": "acetylcholine", "known_nt_source": "native", "is_graded": False,
           "mode": "spiking", "raw_extra": "untouched"}
    row.update(changes)
    return row


def donor_row(root_id=BIG, known_nt="acetylcholine; sNPF", **changes):
    row = {"root_id": root_id, "side": "left", "cell_type": "X", "known_nt": known_nt,
           "known_nt_source": "donor evidence"}
    row.update(changes)
    return row


def merge(banc, donors):
    b = pd.DataFrame(banc)
    f = pd.DataFrame(donors)
    c = p.build_crosswalk(b, f)
    n, ledger = p.merge_annotations(b, f, c)
    return n, c, ledger


def test_exact_ids_unique_transfer_into_nonempty_native_field():
    n, c, ledger = merge([banc_row(1, str(BIG))], [donor_row()])
    assert c.iloc[0].donor_root_id == str(BIG)
    assert c.iloc[0].category == "curator_supported_individual"
    assert parse_positive_nt(n.iloc[0].known_nt) == {"acetylcholine", "snpf"}
    assert n.iloc[0].positive_peptides == "snpf"
    assert n.iloc[0].inferred_annotations == "snpf"
    assert n.iloc[0].neurotransmitter_verified == "acetylcholine"
    assert n.iloc[0].cell_class == "ALLN"
    assert ledger.loc[ledger.decision.eq("transferred"), "token"].tolist() == ["snpf"]


def test_shared_exemplar_is_type_only_and_never_transfers():
    n, c, ledger = merge([banc_row(1, str(BIG)), banc_row(2, str(BIG))], [donor_row()])
    assert c.category.tolist() == ["type_only", "type_only"]
    assert not c.eligible_for_property_transfer.any()
    assert n.positive_peptides.tolist() == ["", ""]
    assert set(ledger.loc[ledger.source.eq("flywire-783"), "decision"]) == {"rejected"}


def test_donor_missing_ambiguous_and_unchecked():
    _, c, _ = merge([banc_row(1, str(BIG + 1)), banc_row(2, f"{BIG},{BIG + 1}"),
                     banc_row(3, str(BIG), status=""), banc_row(4, "", cell_type="", fafb_cell_type=""),
                     banc_row(5, "")], [donor_row()])
    assert c.category.tolist() == ["missing_donor", "ambiguous", "type_only", "unresolved", "type_only"]


def test_native_type_alone_does_not_assert_flywire_type_correspondence():
    _, c, _ = merge([banc_row(1, "", fafb_cell_type="", cell_type="NativeVNCType")], [donor_row()])
    assert c.iloc[0].category == "unresolved"
    assert c.iloc[0].type_comparison_basis == "native_cell_type_name"


@pytest.mark.parametrize("change, reason", [({"side": "right"}, "known_hemisphere_conflict"),
                                             ({"cell_type": "Y"}, "known_cell_type_conflict")])
def test_known_side_or_type_conflicts_veto_individual_transfer(change, reason):
    n, c, _ = merge([banc_row(1, str(BIG))], [donor_row(**change)])
    assert c.iloc[0].category == "ambiguous"
    assert reason in c.iloc[0].decision_reasons
    assert n.iloc[0].positive_peptides == ""


def test_float_ids_never_silently_round_into_correspondences():
    _, c, _ = merge([banc_row(1, float(BIG))], [donor_row()])
    assert c.iloc[0].category == "ambiguous"
    with pytest.raises(ValueError, match="integer dtype"):
        p.build_crosswalk(pd.DataFrame([banc_row(1, str(BIG))]), pd.DataFrame([donor_row(float(BIG))]))


def test_duplicate_root_ids_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        p.build_crosswalk(pd.DataFrame([banc_row(1)]), pd.DataFrame([donor_row(), donor_row()]))


def test_negative_evidence_and_donor_self_conflict_preserved_without_false_sources():
    native = banc_row(1, str(BIG), neurotransmitter_verified="acetylcholine; dopamine-negative")
    donor = donor_row(known_nt="dopamine; octopamine; octopamine-negative; acetylcholine-negative; sNPF-negative")
    n, _, ledger = merge([native], [donor])
    assert parse_positive_nt(n.iloc[0].known_nt) == {"acetylcholine"}
    assert "snpf-negative" in n.iloc[0].known_nt
    assert "dopamine" in n.iloc[0].conflicting_annotations
    reasons = set(ledger.loc[ledger.decision.eq("rejected"), "reason"])
    assert {"native_negative_veto", "native_positive_veto", "donor_positive_negative_conflict"} <= reasons
    assert not positive_nt_masks(n)["DA"].any()
    assert not positive_nt_masks(n)["OA"].any()


def test_native_positive_negative_conflict_is_not_an_executable_positive():
    n, _, ledger = merge([banc_row(1, "", neurotransmitter_verified="gaba,gaba-negative")], [donor_row()])
    assert parse_positive_nt(n.iloc[0].known_nt) == set()
    assert n.iloc[0].native_positive_annotations == "gaba"
    assert n.iloc[0].conflicting_annotations == "gaba"
    assert ledger.decision.tolist() == ["conflict_preserved", "conflict_preserved"]


def test_native_fast_transmitter_not_union_with_incompatible_donor():
    n, _, ledger = merge([banc_row(1, str(BIG))], [donor_row(known_nt="gaba; sNPF")])
    assert parse_positive_nt(n.iloc[0].known_nt) == {"acetylcholine", "snpf"}
    assert n.iloc[0].positive_fast_transmitters == "acetylcholine"
    assert ledger.loc[ledger.token.eq("gaba"), "reason"].tolist() == ["fast_transmitter_set_disagreement"]


def test_native_peptides_no_alias_and_alln_recovered_without_global_mutation():
    b = pd.DataFrame([banc_row(1, "", neurotransmitter_verified="gaba,nitric_oxide",
                               neuropeptide_verified="sNPF,Tk,UnrecognizedPeptide")])
    original = b.copy(deep=True)
    f = pd.DataFrame([donor_row()])
    n, ledger = p.merge_annotations(b, f, p.build_crosswalk(b, f))
    assert b.equals(original)
    assert n.iloc[0].neuropeptide_verified == "sNPF,Tk,UnrecognizedPeptide"
    assert parse_positive_nt(n.iloc[0].known_nt) == {"gaba", "nitric oxide", "snpf", "tachykinin", "unrecognizedpeptide"}
    assert positive_nt_masks(n)["NO"].tolist() == [True]
    assert positive_nt_masks(n)["sNPF"].tolist() == [True]
    assert len(ledger.loc[ledger.source_field.eq("neuropeptide_verified")]) == 3


def test_broad_peptide_negative_veto_and_unknown_donor_not_guessed():
    n, _, ledger = merge([banc_row(1, str(BIG), neuropeptide_verified="neuropeptide-negative")],
                         [donor_row(known_nt="sNPF; Dh331; negative")])
    assert not n.iloc[0].positive_peptides
    assert not ledger.decision.eq("transferred").any()
    assert "native_negative_veto" in ledger.reason.to_list()
    assert "unresolved_annotation_semantics" in ledger.reason.to_list()


@pytest.fixture
def frozen_inputs(tmp_path, monkeypatch):
    b = pd.DataFrame([banc_row(1, str(BIG), neuropeptide_verified="sNPF", neurotransmitter_verified="gaba,nitric_oxide"),
                      banc_row(2, str(BIG + 1), index=1)])
    f = pd.DataFrame([donor_row(known_nt="gaba; sNPF"), donor_row(BIG + 1, known_nt="acetylcholine; Dh44")])
    folder = _folder(tmp_path, BANC_ID)
    folder.mkdir(parents=True)
    b.to_parquet(folder/"neurons.parquet", index=False)
    _save_csr(folder, "spiking", sparse.csr_matrix(np.array([[0., -2.], [3., 0.]], dtype=np.float32)))
    _save_csr(folder, "graded", sparse.csr_matrix((2, 2), dtype=np.float32))
    m = {"id": BANC_ID, "neurons": 2, "edges": 2, "output_hashes": {p.name: checksum(p) for p in sorted(folder.iterdir())}, "warnings": []}
    m["model_hash"] = stable_hash(m)
    _freeze_model(tmp_path, folder, m)
    atomic_write_json(folder/"manifest.json", m)
    f.to_parquet(tmp_path/"build/neurons.parquet", index=False)
    monkeypatch.setattr(p, "BANC_BASELINE_HASH", m["model_hash"])
    monkeypatch.setattr(p, "FLYWIRE_NEURONS_SHA256", checksum(tmp_path/"build/neurons.parquet"))
    return tmp_path, m


def test_compile_is_deterministic_frozen_and_topologically_identical(frozen_inputs):
    root, base = frozen_inputs
    first = p.compile_paralimbo(root)
    second = p.compile_paralimbo(root)
    assert first == second
    assert first["biological_gate"] == "PENDING"
    assert first["metrics"]["source_masks_after"]["NO"] == 1
    frozen = root/"build/model-versions"/first["model_hash"]
    for name in p.ARRAY_FILES:
        assert checksum(frozen/name) == base["output_hashes"][name]
    assert p.validate_paralimbo(root)["status"] == "PASS"
    assert checksum(root/"build/model-versions"/base["model_hash"]/"neurons.parquet") == base["output_hashes"]["neurons.parquet"]
    # Validation uses captured donor bytes, so later local donor changes do not
    # reinterpret this historical model. A fresh compile refuses those changes.
    (root/"build/neurons.parquet").write_bytes(b"changed")
    assert p.validate_paralimbo(root)["status"] == "PASS"
    with pytest.raises(ValueError, match="differs from pinned"):
        p.compile_paralimbo(root)


def test_corruption_fails_and_saves_hash_bound_evidence(frozen_inputs):
    root, _ = frozen_inputs
    m = p.compile_paralimbo(root)
    path = root/"build/model-versions"/m["model_hash"]/"spiking_data.npy"
    path.write_bytes(path.read_bytes() + b"corruption")
    with pytest.raises(ValueError, match="validation failed"):
        p.validate_paralimbo(root)
    audit = json.loads((root/"build/validation_paralimbo.json").read_text())
    assert audit["status"] == "FAIL"
    assert audit["model_hash"] == m["model_hash"]
    assert audit["biological_gate"] == "PENDING"
    assert any(c["status"] == "FAIL" for c in audit["checks"])


def test_corrupt_baseline_is_rejected_before_new_model(frozen_inputs):
    root, m = frozen_inputs
    path = root/"build/model-versions"/m["model_hash"]/"spiking_data.npy"
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="Pinned BANC artifact changed"):
        p.compile_paralimbo(root)
    assert not (_folder(root, PARALIMBO_ID)/"manifest.json").exists()


def test_compiler_code_drift_fails_audit(frozen_inputs, monkeypatch):
    root, _ = frozen_inputs
    p.compile_paralimbo(root)
    monkeypatch.setattr(p, "_compiler_hashes", lambda: {"paralimbo.py": "changed"})
    with pytest.raises(ValueError, match="compiler_and_source_selector_hashes"):
        p.validate_paralimbo(root)
