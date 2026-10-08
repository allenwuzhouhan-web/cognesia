"""ParaLimbo: a conservative, reproducible BANC/FlyWire evidence compiler.

This release changes annotations, not anatomy or electrical modes. A crosswalk
is an evidence classification, never proof that neurons in two specimens are
identical. Native assertions and inferred properties remain distinguishable.
"""
from __future__ import annotations

from collections import Counter
from importlib.metadata import version
import json
import numbers
from pathlib import Path
import re
import shutil
import tempfile

import numpy as np
import pandas as pd

from .fetch import checksum
from .inspect_data import atomic_write_json
from .model_registry import (BANC_ID, PARALIMBO_ID, _folder, _freeze_model,
                             get_model_manifest, stable_hash)

BANC_BASELINE_HASH = "60d220182e6f65b98a78b008c764bb13b802d1dc5b85a798cc9028a6557665de"
FLYWIRE_NEURONS_SHA256 = "432901d18d2a5b44fd44dd558668589b81103344eeb8f44b2637cbd6b5f8889e"
FLYWIRE_SOURCE_ARTIFACTS = {
    "Completeness_783.csv": {
        "url": "https://raw.githubusercontent.com/philshiu/Drosophila_brain_model/91bdd1e7dcf193f3e7ca5a8933497fcef63b7960/Completeness_783.csv",
        "sha256": "bbb847a4cc2caaa7a16349722d220c087317b946d148d4d592d94d250617a311",
        "bytes": 3_327_347,
    },
    "Supplemental_file1_neuron_annotations.tsv": {
        "url": "https://raw.githubusercontent.com/flyconnectome/flywire_annotations/17fc57722002e1a7d38cdd0c89ac382bf92718da/supplemental_files/Supplemental_file1_neuron_annotations.tsv",
        "sha256": "9a4f8b2f843196074431ebd7cd883536afa1be86c8a4ce90970441e8be81d1be",
        "bytes": 31_718_505,
    },
}
FLYWIRE_MODE_CONFIG_SHA256 = "ea0ff19c1b632b357dad7f5c1345c0b3c700eaa279c9a44450db937a175ce2a0"
ARRAY_FILES = tuple(f"{kind}_{part}.npy" for kind in ("graded", "spiking")
                    for part in ("data", "indices", "indptr"))
FAST = frozenset({"acetylcholine", "gaba", "glutamate", "histamine", "glycine"})
MODULATORS = frozenset({"dopamine", "octopamine", "serotonin", "tyramine", "nitric oxide"})
# Only nomenclature equivalences are normalized. Unknown names remain visible;
# e.g. the donor's 'Dh331' is not silently corrected to 'Dh31'.
ALIASES = {
    "nitric_oxide": "nitric oxide", "tk": "tachykinin", "asta": "allatostatin-a",
    "astc": "allatostatin-c", "capa": "capability", "crz": "corazonin",
    "dsk": "drosulfakinin", "eh": "eclosion hormone", "hug": "hugin",
    "ilp2": "dilp2", "ilp3": "dilp3", "ilp5": "dilp5", "lk": "leucokinin",
    "ms": "myosuppressin", "myosupressin": "myosuppressin", "proc": "proctolin",
    "sifa": "sifamide", "spab": "space blanket", "amn": "amnesiac", "dnpf": "npf",
}
PEPTIDES = frozenset({"allatostatin-a", "allatostatin-c", "ccap", "ccha1", "cnma",
                     "capability", "corazonin", "dh31", "dh44", "drosulfakinin",
                     "eclosion hormone", "fmrfa", "hugin", "itp", "dilp2", "dilp3",
                     "dilp5", "leucokinin", "mip", "myosuppressin", "npf", "natalisin",
                     "nplp1", "orcokinin", "pdf", "proctolin", "sifamide", "space blanket",
                     "tachykinin", "trissin", "amnesiac", "darc1", "snpf", "ipnamide",
                     "bursicon"})
BROAD_PEPTIDE_NEGATIVES = frozenset({"neuropeptide", "neuropeptides"})
LEDGER_COLUMNS = ["entity_id", "donor_entity_id", "source", "source_field", "property",
                  "token", "polarity", "raw_token", "raw_annotation", "evidence",
                  "decision", "reason"]
ANNOTATION_COLUMNS = ("positive_fast_transmitters", "positive_neuromodulators", "positive_peptides",
                      "positive_unclassified_annotations", "negative_annotations",
                      "conflicting_annotations", "inferred_annotations", "native_positive_annotations")


def _text(value):
    return "" if value is None or pd.isna(value) else str(value).strip()


def _exact_id(value):
    """Never convert root IDs through a floating point representation."""
    if isinstance(value, numbers.Integral) and not isinstance(value, (bool, np.bool_)):
        return int(value) if value >= 0 else None
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        return int(value.strip())
    return None


def _assertions(value, peptide_field=False):
    result = []
    for raw in re.split(r"[,;]", _text(value)):
        token = raw.strip().casefold()
        if not token:
            continue
        negative = token.endswith("-negative")
        if negative:
            token = token[:-len("-negative")].strip()
        token = ALIASES.get(token, token)
        if token in FAST:
            kind = "fast_transmitter"
        elif token in MODULATORS:
            kind = "neuromodulator"
        elif peptide_field or token in PEPTIDES or token in BROAD_PEPTIDE_NEGATIVES:
            kind = "peptide"
        else:
            kind = "unclassified"
        polarity = "negative" if negative else "positive"
        if token == "negative" or not token:
            polarity = "unknown"
        result.append({"token": token, "property": kind, "polarity": polarity,
                       "raw_token": raw.strip()})
    return result


def _types(value):
    return {re.sub(r"^auto:", "", s.strip().casefold()) for s in re.split(r"[,;]", _text(value))
            if s.strip() and s.strip().casefold() not in {"unknown", "unassigned"}}


def _side(value):
    return {"l": "left", "r": "right"}.get(_text(value).casefold(), _text(value).casefold())


def _validate_ids(table, label):
    if "root_id" not in table:
        raise ValueError(f"{label} is missing root_id")
    if table.root_id.dtype.kind not in "iu":
        raise ValueError(f"{label} root IDs must have an exact integer dtype")
    if table.root_id.duplicated().any() or (table.root_id < 0).any():
        raise ValueError(f"{label} has duplicate or negative root IDs")


def build_crosswalk(banc, flywire):
    """Classify every BANC row without coercing exemplars into individual pairs."""
    _validate_ids(banc, "BANC")
    _validate_ids(flywire, "FlyWire")
    donors = {int(r["root_id"]): r for r in flywire.to_dict("records")}
    matches = [_exact_id(v) for v in banc.get("fafb_match", pd.Series("", index=banc.index))]
    multiplicity = Counter(v for v in matches if v is not None)
    output = []
    for i, row in enumerate(banc.to_dict("records")):
        donor_id = matches[i]
        donor = donors.get(donor_id)
        raw = _text(row.get("fafb_match"))
        flags = {s.strip() for s in _text(row.get("status")).split(",")}
        checked = "FAFB_MATCH_MANUALLY_CHECKED" in flags
        expected = _types(row.get("fafb_cell_type"))
        type_basis = "fafb_cell_type" if expected else "unavailable"
        if not expected:
            expected = _types(row.get("fafb_alignment_cell_type"))
            if expected:
                type_basis = "fafb_alignment_cell_type"
        # Native type naming is less directly comparable; use it only if neither
        # of the source's explicit FlyWire type annotations is available.
        if not expected:
            expected = _types(row.get("cell_type"))
            if expected:
                type_basis = "native_cell_type_name"
        observed = _types(donor.get("cell_type")) if donor else set()
        type_conflict = bool(expected and observed and not expected.intersection(observed))
        a, b = _side(row.get("side")), _side(donor.get("side")) if donor else ""
        side_conflict = a in {"left", "right"} and b in {"left", "right"} and a != b
        reasons = []
        if not raw:
            has_flywire_type = type_basis in {"fafb_cell_type", "fafb_alignment_cell_type"}
            category = "type_only" if has_flywire_type else "unresolved"
            reasons.append("flywire_type_annotation_without_individual_donor" if has_flywire_type else "no_flywire_match_or_type_annotation")
        elif donor_id is None:
            category = "ambiguous"
            reasons.append("match_is_not_one_exact_integer_id")
        elif donor is None:
            category = "missing_donor"
            reasons.append("donor_absent_from_pinned_flywire_table")
        elif type_conflict or side_conflict or {"FAFB_ALT_MATCH", "LR_TYPE_CONFLICT"}.intersection(flags):
            category = "ambiguous"
            if type_conflict:
                reasons.append("known_cell_type_conflict")
            if side_conflict:
                reasons.append("known_hemisphere_conflict")
            reasons.extend(sorted({"FAFB_ALT_MATCH", "LR_TYPE_CONFLICT"}.intersection(flags)))
        elif multiplicity[donor_id] > 1:
            category = "type_only" if expected and observed and expected.intersection(observed) else "ambiguous"
            reasons.append("shared_donor_exemplar_is_not_a_unique_individual_homolog")
        elif not checked:
            category = "type_only" if expected and observed and expected.intersection(observed) else "unresolved"
            reasons.append("individual_correspondence_not_manually_checked")
        else:
            category = "curator_supported_individual"
            reasons.append("unique_curator_checked_match_without_known_type_or_side_conflict")
        output.append({"model_index": i, "root_id": int(row["root_id"]),
                       "entity_id": f"banc:888:{int(row['root_id'])}", "raw_fafb_match": raw,
                       # Strings avoid nullable-int to float loss during serialization.
                       "donor_root_id": str(donor_id) if donor_id is not None else "",
                       "donor_entity_id": f"flywire:783:{donor_id}" if donor_id is not None else "",
                       "category": category, "eligible_for_property_transfer": category == "curator_supported_individual",
                       "decision_reasons": ";".join(reasons), "curator_checked": checked,
                       "donor_match_multiplicity": multiplicity.get(donor_id, 0),
                       "banc_side": a, "donor_side": b, "side_conflict": side_conflict,
                       "expected_flywire_types": ";".join(sorted(expected)),
                       "type_comparison_basis": type_basis,
                       "donor_types": ";".join(sorted(observed)), "type_conflict": type_conflict})
    return pd.DataFrame(output)


def merge_annotations(banc, flywire, crosswalk):
    """Resolve assertions per property while leaving all raw evidence intact."""
    neurons = banc.copy(deep=True)
    donors = {int(r["root_id"]): r for r in flywire.to_dict("records")}
    ledger = []
    values = {key: [] for key in (*ANNOTATION_COLUMNS, "known_nt", "known_nt_source")}
    for row, match in zip(banc.to_dict("records"), crosswalk.to_dict("records"), strict=True):
        native = []
        for field in ("neurotransmitter_verified", "neuropeptide_verified"):
            for assertion in _assertions(row.get(field), peptide_field=field == "neuropeptide_verified"):
                native.append({**assertion, "source_field": field, "raw_annotation": _text(row.get(field))})
        positive = {a["token"] for a in native if a["polarity"] == "positive"}
        negative = {a["token"] for a in native if a["polarity"] == "negative"}
        conflicts = positive & negative
        native_peptides = {a["token"] for a in native if a["property"] == "peptide" and a["polarity"] == "positive"}
        if negative & BROAD_PEPTIDE_NEGATIVES:
            conflicts |= native_peptides
        active = {a["token"]: a["property"] for a in native
                  if a["polarity"] == "positive" and a["token"] not in conflicts}
        inferred = set()
        for assertion in native:
            token = assertion["token"]
            conflicted = token in conflicts
            ledger.append({"entity_id": match["entity_id"], "donor_entity_id": "", "source": BANC_ID,
                           **assertion, "evidence": "native_source_annotation",
                           "decision": "conflict_preserved" if conflicted else "retained_native",
                           "reason": "native_positive_negative_conflict" if conflicted else "native_assertion_preserved"})
        donor = donors.get(_exact_id(match["donor_root_id"]))
        assertions = _assertions(donor.get("known_nt")) if donor else []
        donor_positive = {a["token"] for a in assertions if a["polarity"] == "positive"}
        donor_negative = {a["token"] for a in assertions if a["polarity"] == "negative"}
        donor_conflicts = donor_positive & donor_negative
        donor_broad_negative = bool(donor_negative & BROAD_PEPTIDE_NEGATIVES)
        native_fast = positive & FAST
        for assertion in assertions:
            token, polarity, kind = assertion["token"], assertion["polarity"], assertion["property"]
            decision = "rejected"
            if not match["eligible_for_property_transfer"]:
                reason = "ineligible_correspondence:" + match["category"]
            elif polarity == "unknown" or kind == "unclassified":
                reason = "unresolved_annotation_semantics"
            elif token in donor_conflicts or (donor_broad_negative and kind == "peptide" and polarity == "positive"):
                reason = "donor_positive_negative_conflict"
                conflicts.add(token)
            elif polarity == "positive" and (token in negative or (kind == "peptide" and negative & BROAD_PEPTIDE_NEGATIVES)):
                reason = "native_negative_veto"
                conflicts.add(token)
            elif polarity == "negative" and (token in positive or (token in BROAD_PEPTIDE_NEGATIVES and native_peptides)):
                reason = "native_positive_veto"
                conflicts.add(token)
            elif polarity == "positive" and token in positive:
                decision, reason = "corroborated", "native_positive_already_present"
            elif polarity == "negative" and token in negative:
                decision, reason = "corroborated", "native_negative_already_present"
            elif polarity == "positive" and token in FAST and native_fast:
                # An alternative transmitter across specimens is not evidence of
                # co-transmission in this BANC neuron.
                reason = "fast_transmitter_set_disagreement"
                conflicts.add(token)
            else:
                decision, reason = "transferred", "inferred_property_hole_from_curator_supported_individual"
                inferred.add((token, polarity))
                if polarity == "positive":
                    active[token] = kind
                else:
                    negative.add(token)
            ledger.append({"entity_id": match["entity_id"], "donor_entity_id": match["donor_entity_id"],
                           "source": "flywire-783", "source_field": "known_nt", **assertion,
                           "raw_annotation": _text(donor.get("known_nt")),
                           "evidence": "cross_specimen_annotation_inference",
                           "decision": decision, "reason": reason})
        for column, kind in (("positive_fast_transmitters", "fast_transmitter"),
                             ("positive_neuromodulators", "neuromodulator"),
                             ("positive_peptides", "peptide"),
                             ("positive_unclassified_annotations", "unclassified")):
            values[column].append(";".join(sorted(t for t, k in active.items() if k == kind)))
        values["native_positive_annotations"].append(";".join(sorted(positive)))
        values["negative_annotations"].append(";".join(sorted(negative)))
        values["conflicting_annotations"].append(";".join(sorted(conflicts)))
        values["inferred_annotations"].append(";".join(sorted(t + ("-negative" if p == "negative" else "") for t, p in inferred)))
        values["known_nt"].append(";".join(sorted(active) + [t + "-negative" for t in sorted(negative)]))
        values["known_nt_source"].append("ParaLimbo annotation_ledger.parquet; native BANC assertions and separately labeled cross-specimen inferences")
    for key, column in values.items():
        neurons[key] = column
    neurons["cell_class"] = neurons.cell_class.replace({"antennal_lobe_local_neuron": "ALLN"})
    records = pd.DataFrame(ledger, columns=LEDGER_COLUMNS).drop_duplicates(ignore_index=True)
    return neurons, records


def _policy():
    return {"schema_version": 1, "id": PARALIMBO_ID, "banc_model_hash": BANC_BASELINE_HASH,
            "flywire_neurons_sha256": FLYWIRE_NEURONS_SHA256, "aliases": ALIASES,
            "positive_fast_transmitters": sorted(FAST), "neuromodulators": sorted(MODULATORS),
            "recognized_donor_peptides": sorted(PEPTIDES), "unknown_native_annotations": "preserved",
            "individual_transfer": "unique manually checked exact donor with no known hemisphere/type conflict",
            "type_level_transfer": "disabled", "native_conflicts": "preserved and excluded from positive release",
            "cross_specimen_conflicts": "retain native assertion; reject conflicting donor; record disagreement",
            "fast_transmitter_holes": "only if native positive fast-transmitter set is empty",
            "peptide_holes": "per canonical token; negative evidence vetoes transfer",
            "connectivity": "six BANC CSR arrays byte-identical; zero circuit replacements",
            "electrical_modes": "BANC is_graded/mode unchanged; assumed, not measured",
            "fast_signs": "BANC signed array values unchanged under original assumed sign convention",
            "biological_gate": "PENDING; no accuracy or novelty claim"}


def _compiler_hashes():
    base = Path(__file__).parent
    return {name: checksum(base/name) for name in ("paralimbo.py", "model_registry.py", "neuromod/sources.py", "neuromod/field.py")}


def _load_base(root):
    manifest = get_model_manifest(root, BANC_ID, BANC_BASELINE_HASH)
    folder = Path(root)/"build/model-versions"/BANC_BASELINE_HASH
    for name, digest in manifest["output_hashes"].items():
        if checksum(folder/name) != digest:
            raise ValueError("Pinned BANC artifact changed: " + name)
    if set(ARRAY_FILES) - set(manifest["output_hashes"]):
        raise ValueError("Pinned BANC baseline is missing CSR arrays")
    return manifest, folder, pd.read_parquet(folder/"neurons.parquet")


def _source_counts(neurons):
    from .neuromod.sources import positive_nt_masks, source_masks
    from .neuromod.field import PEPTIDE_TOKENS
    from .neuromod.sources import parse_positive_nt
    masks = source_masks(neurons)
    masks.update(positive_nt_masks(neurons, {"ACh": "acetylcholine"}))
    masks["peptide_pool"] = (neurons.super_class.eq("endocrine").to_numpy()
                             & neurons.known_nt.map(parse_positive_nt).map(lambda t: bool(t & PEPTIDE_TOKENS)).to_numpy())
    return {key: int(mask.sum()) for key, mask in masks.items()}


def compile_paralimbo(root, progress=None):
    """Compile locally acquired pinned inputs into an immutable model version."""
    root = Path(root)
    base_manifest, base_folder, banc = _load_base(root)
    donor_path = root/"build/neurons.parquet"
    if checksum(donor_path) != FLYWIRE_NEURONS_SHA256:
        raise ValueError("FlyWire neuron table differs from pinned ParaLimbo input")
    flywire = pd.read_parquet(donor_path)
    if progress:
        progress({"phase": "compiling_paralimbo", "step": "classifying_correspondences"})
    crosswalk = build_crosswalk(banc, flywire)
    neurons, ledger = merge_annotations(banc, flywire, crosswalk)
    folder = _folder(root, PARALIMBO_ID)
    folder.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".paralimbo-", dir=folder.parent) as staging_name:
        staging = Path(staging_name)
        for name in ARRAY_FILES:
            shutil.copyfile(base_folder/name, staging/name)
        shutil.copyfile(donor_path, staging/"flywire_neurons.parquet")
        if checksum(staging/"flywire_neurons.parquet") != FLYWIRE_NEURONS_SHA256:
            raise ValueError("FlyWire input changed during compilation")
        neurons.to_parquet(staging/"neurons.parquet", index=False)
        crosswalk.to_parquet(staging/"crosswalk.parquet", index=False)
        ledger.to_parquet(staging/"annotation_ledger.parquet", index=False)
        ledger.loc[ledger.decision.isin(["rejected", "conflict_preserved"])].to_parquet(staging/"conflicts.parquet", index=False)
        atomic_write_json(staging/"policy.json", _policy())
        input_hashes = {"banc_model_hash": base_manifest["model_hash"],
                        "banc_artifacts": base_manifest["output_hashes"],
                        "banc_original_source_artifacts": base_manifest.get("source_artifacts", {}),
                        "flywire_original_source_artifacts": FLYWIRE_SOURCE_ARTIFACTS,
                        "flywire_neuron_modes_config_sha256": FLYWIRE_MODE_CONFIG_SHA256,
                        "flywire_neurons_sha256": FLYWIRE_NEURONS_SHA256}
        atomic_write_json(staging/"input_hashes.json", input_hashes)
        compiler_hashes = _compiler_hashes()
        atomic_write_json(staging/"compiler_hashes.json", compiler_hashes)
        shutil.copyfile(Path(__file__), staging/"compiler.py")
        transferred = ledger.loc[ledger.decision.eq("transferred")]
        metrics = {"crosswalk_categories": {str(k): int(v) for k, v in crosswalk.category.value_counts().sort_index().items()},
                   "native_peptide_annotated_neurons": int(banc.neuropeptide_verified.fillna("").str.strip().ne("").sum()),
                   "transferred_property_assertions": len(transferred),
                   "neurons_with_transferred_properties": int(transferred.entity_id.nunique()),
                   "transferred_positive_assertions": int(transferred.polarity.eq("positive").sum()),
                   "transferred_negative_assertions": int(transferred.polarity.eq("negative").sum()),
                   "donor_rejected_assertions": int((ledger.source.eq("flywire-783") & ledger.decision.eq("rejected")).sum()),
                   "source_masks_before": _source_counts(banc), "source_masks_after": _source_counts(neurons),
                   "native_peptide_assertions": int((ledger.source.eq(BANC_ID) & ledger.source_field.eq("neuropeptide_verified")).sum()),
                   "circuit_replacements": 0}
        manifest = {"schema_version": 1, "id": PARALIMBO_ID, "name": "ParaLimbo", "version": "0.1.0-alpha.1",
                    "identity_namespace": "banc:888", "base_model": BANC_ID,
                    "base_model_hash": base_manifest["model_hash"], "species": "Drosophila melanogaster",
                    "sex": "female", "stage": "adult", "neurons": base_manifest["neurons"],
                    "edges": base_manifest["edges"], "input_hashes": input_hashes,
                    "compiler_hashes": compiler_hashes, "policy_hash": stable_hash(_policy()),
                    "build_dependencies": {key: version(key) for key in ("numpy", "pandas", "pyarrow", "scipy")},
                    "output_hashes": {p.name: checksum(p) for p in sorted(staging.iterdir())},
                    "metrics": metrics, "optical_mapping_supported": False,
                    "status": "ASSEMBLED", "biological_gate": "PENDING",
                    "warnings": [*base_manifest.get("warnings", []),
                                 "ParaLimbo integrates cross-specimen evidence; it is not a single measured fly.",
                                 "Coverage and source fidelity are not evidence of improved biological predictions.",
                                 "Peptide annotations are retained even where the runtime has no corresponding dynamics.",
                                 "Electrical modes and signed connectivity retain BANC's existing model assumptions."]}
        manifest["model_hash"] = stable_hash(manifest)
        _freeze_model(root, staging, manifest)
        # The immutable version is authoritative. Publish the mutable convenience
        # copy's manifest last so interrupted builds cannot relabel old versions.
        folder.mkdir(parents=True, exist_ok=True)
        for path in sorted(staging.iterdir()):
            shutil.copyfile(path, folder/path.name)
        atomic_write_json(folder/"manifest.json", manifest)
    if progress:
        progress({"phase": "compiling_paralimbo", "step": "validating", "model_hash": manifest["model_hash"]})
    validate_paralimbo(root)
    return manifest


def validate_paralimbo(root):
    """Audit observed bytes, identities, assertions and actual runtime source masks.

    Failure writes an evidence record before raising ValueError. PASS covers
    structural/source fidelity invariants only; biological validation is pending.
    """
    root = Path(root)
    model_hash = None
    checks = []
    result = {"schema_version": 1, "id": PARALIMBO_ID, "status": "FAIL", "model_hash": None,
              "scope": "structural invariants and source fidelity", "biological_gate": "PENDING", "checks": checks}
    def check(name, passed, observed=None):
        checks.append({"name": name, "status": "PASS" if passed else "FAIL", "observed": observed})
    try:
        manifest = get_model_manifest(root, PARALIMBO_ID)
        model_hash = manifest["model_hash"]
        result["model_hash"] = model_hash
        folder = root/"build/model-versions"/model_hash
        for name, digest in manifest["output_hashes"].items():
            check("artifact:" + name, checksum(folder/name) == digest)
        if any(c["status"] == "FAIL" for c in checks):
            raise ValueError("ParaLimbo immutable artifact checksum mismatch")
        check("compiler_and_source_selector_hashes", manifest["compiler_hashes"] == _compiler_hashes())
        base_manifest, base_folder, banc = _load_base(root)
        check("pinned_base_identity", manifest["base_model_hash"] == BANC_BASELINE_HASH)
        check("pinned_donor_bytes", checksum(folder/"flywire_neurons.parquet") == FLYWIRE_NEURONS_SHA256)
        check("policy", json.loads((folder/"policy.json").read_text()) == _policy())
        neurons = pd.read_parquet(folder/"neurons.parquet")
        flywire = pd.read_parquet(folder/"flywire_neurons.parquet")
        crosswalk = pd.read_parquet(folder/"crosswalk.parquet")
        ledger = pd.read_parquet(folder/"annotation_ledger.parquet")
        _validate_ids(neurons, "ParaLimbo")
        changed = {"known_nt", "known_nt_source", "cell_class"}
        original_columns = [name for name in banc.columns if name not in changed]
        check("all_unchanged_native_columns_and_order", neurons[original_columns].equals(banc[original_columns]))
        check("identity_namespace", neurons.entity_id.equals(banc.entity_id))
        check("declared_model_dimensions", manifest["neurons"] == len(neurons) == base_manifest["neurons"]
              and manifest["edges"] == base_manifest["edges"])
        check("electrical_modes", neurons[["is_graded", "mode"]].equals(banc[["is_graded", "mode"]]))
        check("cell_class_alias_only", neurons.cell_class.equals(banc.cell_class.replace({"antennal_lobe_local_neuron": "ALLN"})))
        for name in ARRAY_FILES:
            check("byte_identical_topology_and_signs:" + name, checksum(folder/name) == checksum(base_folder/name))
        expected_crosswalk = build_crosswalk(banc, flywire)
        check("complete_crosswalk_and_donor_links", crosswalk.equals(expected_crosswalk))
        expected_neurons, expected_ledger = merge_annotations(banc, flywire, expected_crosswalk)
        check("complete_property_decisions", ledger.equals(expected_ledger))
        check("executable_annotation_resolution", neurons.equals(expected_neurons))
        expected_conflicts = ledger.loc[ledger.decision.isin(["rejected", "conflict_preserved"])].reset_index(drop=True)
        check("complete_rejection_and_conflict_ledger", pd.read_parquet(folder/"conflicts.parquet").equals(expected_conflicts))
        # Independent row-wise conservation check against raw fields; a correctly
        # shaped executable table alone would not reveal an omitted native field.
        from .neuromod.sources import parse_positive_nt
        native_rows = set()
        native_release_errors = 0
        for row, executable in zip(banc.to_dict("records"), neurons.known_nt, strict=True):
            entity = f"banc:888:{int(row['root_id'])}"
            native_assertions = []
            for field in ("neurotransmitter_verified", "neuropeptide_verified"):
                for assertion in _assertions(row.get(field), field == "neuropeptide_verified"):
                    native_assertions.append(assertion)
                    native_rows.add((entity, field, assertion["raw_token"], assertion["polarity"]))
            positive = {a["token"] for a in native_assertions if a["polarity"] == "positive"}
            negative = {a["token"] for a in native_assertions if a["polarity"] == "negative"}
            required = positive - negative
            if negative & BROAD_PEPTIDE_NEGATIVES:
                required -= {a["token"] for a in native_assertions if a["property"] == "peptide"}
            if not required <= parse_positive_nt(executable):
                native_release_errors += 1
        observed_rows = set(ledger.loc[ledger.source.eq(BANC_ID), ["entity_id", "source_field", "raw_token", "polarity"]].itertuples(index=False, name=None))
        check("all_native_assertions_preserved", observed_rows == native_rows, len(observed_rows))
        check("all_uncontested_native_positive_release_tokens_preserved", native_release_errors == 0, native_release_errors)
        eligible = set(crosswalk.loc[crosswalk.eligible_for_property_transfer, "entity_id"])
        transfer = ledger.loc[ledger.decision.eq("transferred")]
        check("no_type_only_or_ambiguous_transfers", set(transfer.entity_id) <= eligible)
        from .neuromod.sources import positive_nt_masks, source_masks
        names = {"DA": "dopamine", "OA": "octopamine", "5HT": "serotonin", "TA": "tyramine", "NO": "nitric oxide", "sNPF": "snpf", "ACh": "acetylcholine"}
        actual = positive_nt_masks(neurons, names)
        canonical = [set(filter(None, ";".join(row).split(";"))) for row in
                     neurons[["positive_fast_transmitters", "positive_neuromodulators", "positive_peptides", "positive_unclassified_annotations"]].itertuples(index=False, name=None)]
        for species, token in names.items():
            expected = np.array([token in tokens for tokens in canonical], dtype=bool)
            check("actual_positive_mask:" + species, np.array_equal(actual[species], expected), int(actual[species].sum()))
        masks = source_masks(neurons)
        kc = neurons.cell_type.fillna("").str.startswith("KC").to_numpy()
        for species in ("DA", "OA", "5HT", "TA"):
            check("runtime_kc_exclusion:" + species, np.array_equal(masks[species], actual[species] & ~kc))
        result["metrics"] = manifest["metrics"]
        result["observed_source_masks"] = _source_counts(neurons)
        check("reported_positive_source_counts", manifest["metrics"]["source_masks_after"] == result["observed_source_masks"])
        check("reported_baseline_source_counts", manifest["metrics"]["source_masks_before"] == _source_counts(banc))
        categories = {str(k): int(v) for k, v in crosswalk.category.value_counts().sort_index().items()}
        check("reported_correspondence_counts", manifest["metrics"]["crosswalk_categories"] == categories)
        check("reported_transfer_counts", manifest["metrics"]["transferred_property_assertions"] == len(transfer)
              and manifest["metrics"]["neurons_with_transferred_properties"] == int(transfer.entity_id.nunique())
              and manifest["metrics"]["transferred_positive_assertions"] == int(transfer.polarity.eq("positive").sum())
              and manifest["metrics"]["transferred_negative_assertions"] == int(transfer.polarity.eq("negative").sum()))
        result["status"] = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
    except (ValueError, FileNotFoundError, KeyError, OSError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["status"] = "FAIL"
    evidence = root/"build/validation_paralimbo.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(evidence, result)
    if model_hash:
        atomic_write_json(root/"build"/f"validation_paralimbo_{model_hash}.json", result)
    if result["status"] != "PASS":
        failed = [c["name"] for c in checks if c["status"] == "FAIL"]
        raise ValueError("ParaLimbo validation failed: " + result.get("error", ", ".join(failed)))
    return result
