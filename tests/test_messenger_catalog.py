"""Catalogue must not turn literature or guessed names into simulated sources."""
import json

import pytest

from flybrain.messenger_catalog import catalog_payload, messenger_details, source_annotation_tags


def test_runtime_inventory_matches_actual_species_and_hormones():
    from flybrain.neuromod.field import FIELD_SPECIES
    from flybrain.neuromod.state import HORMONES
    payload = catalog_payload()
    assert tuple(payload["field_control_ids"]) == FIELD_SPECIES
    assert tuple(payload["endocrine_proxy_ids"]) == HORMONES
    assert payload["validation"]["biologically_validated"] is False
    assert payload["curated_annotation_resource"]["imported"] is False
    json.dumps(payload, allow_nan=False)


def test_candidates_are_referenced_without_kinetics_or_runtime_enablement():
    candidates = [r for r in catalog_payload()["messengers"] if r["implementation_status"] == "candidate_tag_only"]
    assert len(candidates) == 10
    for row in candidates:
        assert row["evidence"]
        assert all(e["evidence_kind"] == "primary_research" for e in row["evidence"])
        assert all(e["url"].startswith("https://") and e["stage"] and e["tissue_or_circuit"] for e in row["evidence"])
        assert row["field_control_id"] is None and row["endocrine_proxy_id"] is None
        assert row["kinetic_parameters"] is None
        assert row["automatic_neuron_assignment"] is False
        assert row["biologically_validated"] is False


def test_catalog_does_not_hide_stage_and_sex_constraints():
    assert messenger_details("CCHa2")["evidence"][0]["stage"] == "larval"
    assert "female" in messenger_details("TK")["limitations"]
    assert messenger_details("itp")["receptors_reported_in_literature"] == ["Gyc76C"]
    assert "amidated" in messenger_details("itp")["limitations"]


def test_returned_data_is_detached():
    payload = catalog_payload()
    payload["messengers"][0]["id"] = "invented"
    row = messenger_details("NPF")
    row["evidence"][0]["finding"] = "invented"
    assert catalog_payload()["messengers"][0]["id"] == "DA"
    assert messenger_details("NPF")["evidence"][0]["finding"] != "invented"


@pytest.mark.parametrize("identity", ["NPF?", "probably dopamine", "NPF-negative", "NPFR", None, 5])
def test_no_fuzzy_ligand_or_receptor_matching(identity):
    with pytest.raises(ValueError):
        messenger_details(identity)


def test_exact_tags_distinguish_npf_snpf_and_preserve_conflicting_evidence():
    result = source_annotation_tags(" sNPF ; NPF, snpf-negative, NPF?;dopamine-negative; unknown ; peptide_pool",
                                    dataset="flywire-783", neuron_id="720575940600000001",
                                    evidence_url="https://example.org/study")
    rows = {r["messenger_id"]: r for r in result["tags"]}
    assert set(rows) == {"sNPF", "NPF"}
    assert rows["sNPF"]["has_negative_report"] is True
    assert rows["NPF"]["has_negative_report"] is False
    assert result["negative_tokens"] == ["snpf-negative", "dopamine-negative"]
    assert result["unrecognized_tokens"] == ["NPF?", "unknown", "peptide_pool"]
    assert result["neuron_id"] == "720575940600000001"
    assert result["mutates_model"] is False
    assert all(not r["source_evidence_verified"] and not r["enables_simulation"] for r in rows.values())


def test_alias_does_not_claim_other_members_of_lumped_hormone():
    result = source_annotation_tags("DILP2; dILP2; AstB")
    rows = {r["messenger_id"]: r for r in result["tags"]}
    assert rows["insulin"]["matched_tokens"] == ["DILP2", "dILP2"]
    assert "dilp3" not in str(result)
    assert "MIP" in rows


@pytest.mark.parametrize("options", [
    {"known_nt": []}, {"known_nt": float("nan")}, {"known_nt": "a" * 16385},
    {"known_nt": "NPF", "evidence_url": "javascript:alert(1)"},
    {"known_nt": "NPF", "evidence_url": "https://user:password@example.org"},
    {"known_nt": "NPF", "evidence_url": "https://"},
    {"known_nt": "NPF", "dataset": ""}, {"known_nt": "NPF", "neuron_id": 720575940600000001},
])
def test_invalid_annotation_metadata_is_rejected(options):
    with pytest.raises(ValueError):
        source_annotation_tags(**options)


def test_missing_annotation_has_no_invented_sources():
    result = source_annotation_tags(None)
    assert result["tags"] == [] and result["negative_tokens"] == []
