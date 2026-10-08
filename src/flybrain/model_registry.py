"""Versioned connectome providers and an auditable, single fused model.

Native source identifiers are always qualified by dataset and materialization.
The legacy provider remains byte-for-byte separate from newly assembled models.
"""
from __future__ import annotations

from datetime import datetime, timezone
import copy
import hashlib
import json
from pathlib import Path
import re
import os
import shutil
import uuid
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from scipy import sparse

from .fetch import checksum
from .inspect_data import atomic_write_json

BANC_ID = "banc-888"
FUSED_ID = "cognesia-fused-v1"
PARALIMBO_ID = "paralimbo-v0-1-0"
BANC_SOURCE = "https://www.nature.com/articles/s41586-026-10735-w"
BANC_BUCKET = "https://storage.googleapis.com/lee-lab_brain-and-nerve-cord-fly-connectome/compiled_data/banc_888/"
# Immutable GCS object generations inspected in the authors' public mirror.
BANC_FILES = {
    "metadata.feather": ("banc_888_meta.feather", "1787336614757441", 57_503_026),
    "edgelist.feather": ("banc_888_edgelist_simple_v3.feather", "1786578377086929", 359_161_658),
}
SCHEMA_VERSION = 1


def stable_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _folder(root, model_id):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", model_id):
        raise ValueError("Invalid model ID")
    return Path(root) / "build/models" / model_id


def catalog(root):
    result = []
    for model_id, label in (("flywire-783", "FlyWire 783 · historical brain"),
                            (BANC_ID, "BANC 888 · brain and nerve cord"),
                            (FUSED_ID, "Cognesia · fused adult female model"),
                            (PARALIMBO_ID, "ParaLimbo 0.1 · BANC × FlyWire")):
        path = _folder(root, model_id) / "manifest.json"
        available = path.exists() if model_id != "flywire-783" else (Path(root)/"build/build_summary.json").exists()
        entry = {"id": model_id, "label": label, "available": available,
                 "species": "Drosophila melanogaster", "sex": "female", "stage": "adult"}
        if available:
            manifest = get_model_manifest(root, model_id)
            entry.update({k: manifest.get(k) for k in ("model_hash", "neurons", "edges", "warnings")})
        result.append(entry)
    return result


def _model_request(model_id,model_hash=None):
    if "@" in model_id:
        model_id, embedded = model_id.split("@",1)
        if model_hash is not None and model_hash != embedded: raise ValueError("Conflicting model hashes")
        model_hash = embedded
    if model_hash is not None and not re.fullmatch(r"[a-f0-9]{64}",model_hash): raise ValueError("Invalid model hash")
    return model_id,model_hash


def _freeze_model(root,folder,manifest):
    """Copy (never hardlink) every executable artifact into its content version."""
    versions = Path(root)/"build/model-versions"; versions.mkdir(parents=True,exist_ok=True)
    destination = versions/manifest["model_hash"]
    if destination.exists():
        saved = json.loads((destination/"manifest.json").read_text())
        if saved != manifest: raise ValueError("Immutable model version collision")
        for name,digest in manifest["output_hashes"].items():
            if checksum(destination/name) != digest: raise ValueError("Immutable model artifact changed: "+name)
        return
    temporary = versions/("."+manifest["model_hash"]+"."+uuid.uuid4().hex)
    temporary.mkdir()
    try:
        for name,digest in manifest["output_hashes"].items():
            if Path(name).name != name: raise ValueError("Model artifact must be a direct file")
            if checksum(Path(folder)/name) != digest: raise ValueError("Artifact changed during freezing: "+name)
            shutil.copy2(Path(folder)/name,temporary/name)
        atomic_write_json(temporary/"manifest.json",manifest)
        os.replace(temporary,destination)
    except BaseException:
        shutil.rmtree(temporary,ignore_errors=True)
        raise


def get_model_manifest(root, model_id="flywire-783",model_hash=None):
    model_id,model_hash = _model_request(model_id,model_hash)
    if model_id == "flywire-783":
        summary = json.loads((Path(root)/"build/build_summary.json").read_text())
        payload = {"schema_version": 1, "id": model_id, "source": "FlyWire", "materialization": 783,
                   "identity_namespace": "flywire:783", "species": "Drosophila melanogaster",
                   "sex": "female", "stage": "adult", "source_hashes": summary.get("output_hashes", {}),
                   "neurons": len(pd.read_parquet(Path(root)/"build/neurons.parquet", columns=["root_id"])),
                   "historical": True, "optical_mapping_supported": True,
                   "warnings": ["Historical numerical and biological validation limitations remain in REPORT.md."]}
        payload["model_hash"] = stable_hash(payload)
        if model_hash is not None and model_hash != payload["model_hash"]:
            raise ValueError("Historical FlyWire source identity differs; cannot reinterpret that model version")
        return payload
    path = (Path(root)/"build/model-versions"/model_hash/"manifest.json") if model_hash else _folder(root, model_id)/"manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Model {model_id} is not assembled; acquire and compile it first")
    manifest = json.loads(path.read_text())
    if manifest["id"] != model_id: raise ValueError("Model hash belongs to another provider")
    if stable_hash({k: v for k, v in manifest.items() if k != "model_hash"}) != manifest["model_hash"]:
        raise ValueError("Model manifest checksum differs from its identity")
    return manifest


def acquire_banc(root, progress=None):
    """Download pinned, public author artifacts; fail on partial or changed bytes."""
    folder = Path(root)/"data/raw/models"/BANC_ID
    folder.mkdir(parents=True, exist_ok=True)
    old_path = folder/"sources.json"
    old = json.loads(old_path.read_text()) if old_path.exists() else {}
    records = {}
    for name, (remote, generation, size) in BANC_FILES.items():
        path = folder/name
        url = BANC_BUCKET + remote + "?generation=" + generation
        if path.exists() and path.stat().st_size != size:
            raise ValueError(f"BANC cached source has wrong length: {name}")
        if not path.exists():
            temporary = folder/(name+".partial")
            with urlopen(Request(url, headers={"User-Agent": "Cognesia/1.0 scientific model acquisition"}), timeout=60) as response, temporary.open("wb") as handle:
                seen = 0
                while chunk := response.read(4*1024*1024):
                    handle.write(chunk); seen += len(chunk)
                    if seen > size:
                        raise ValueError("BANC source exceeds pinned size")
                    if progress:
                        progress({"phase": "acquiring_model", "file": name, "bytes": seen, "total_bytes": size})
            if temporary.stat().st_size != size:
                raise ValueError("Incomplete BANC download")
            temporary.replace(path)
        digest = checksum(path)
        if name in old.get("files", {}) and digest != old["files"][name]["sha256"]:
            raise ValueError(f"BANC source changed after acquisition: {name}")
        records[name] = {"url": url, "generation": generation, "bytes": size, "sha256": digest}
    record = {"source": BANC_SOURCE, "materialization": 888, "files": records,
              "synapse_detection": "v3; authors' simple edgelist, synapse-size threshold >=10",
              "acquired_at": datetime.now(timezone.utc).isoformat()}
    atomic_write_json(old_path, record)
    return record


def _list(value):
    return [] if pd.isna(value) else [x.strip() for x in str(value).split(",") if x.strip()]


def normalize_banc_neurons(raw):
    if "banc_888_id" not in raw:
        raise ValueError("BANC materialization-qualified identity column is absent")
    table = raw.copy()
    table["native_latest_root_id"] = table.get("root_id", "")
    table["root_id"] = pd.to_numeric(table["banc_888_id"], errors="raise").astype(np.int64)
    if table.root_id.duplicated().any():
        raise ValueError("Duplicate BANC 888 root identity")
    nonneuronal = table.super_class.fillna("").isin(["glia", "not_a_neuron", "trachea"])
    # Retain unresolved neural classes rather than deciding missing means non-neural.
    table = table.loc[~nonneuronal].reset_index(drop=True)
    table["entity_id"] = "banc:888:" + table.root_id.astype(str)
    table["source_dataset"] = "banc"; table["source_version"] = "888"
    table["native_super_class"] = table.super_class
    table["native_cell_class"] = table.cell_class
    table["super_class"] = table.super_class.replace({"central_brain_intrinsic": "central", "optic_lobe_intrinsic": "optic", "ventral_nerve_cord_intrinsic": "vnc", "visceral_circulatory": "endocrine", "ascending_visceral_circulatory": "endocrine"})
    table["cell_class"] = table.cell_class.replace({"kenyon_cell": "Kenyon_Cell", "mushroom_body_output_neuron": "MBON", "olfactory_receptor_neuron": "olfactory", "antennal_lobe_projection_neuron": "ALPN"})
    table["known_nt"] = table.neurotransmitter_verified.fillna("")
    table["known_nt_source"] = np.where(table.known_nt.ne(""), BANC_SOURCE, "")
    table["top_nt"] = table.neurotransmitter_predicted.fillna("unknown")
    table["top_nt_conf"] = table.neurotransmitter_score.fillna(0.)
    table["is_graded"] = table.native_cell_class.eq("photoreceptor_neuron")
    table["mode"] = np.where(table.is_graded, "graded", "spiking")
    xyz = np.full((len(table), 3), np.nan)
    for i, value in enumerate(table.root_position_nm):
        try:
            values = [float(x) for x in str(value).split(",")]
            if len(values) == 3: xyz[i] = np.asarray(values)/1000.
        except (ValueError, TypeError):
            pass
    # Compatibility positions preserve physical micrometres in legacy render paths.
    for j, axis in enumerate("xyz"):
        table["pos_"+axis] = xyz[:, j]/(.04 if axis == "z" else .004)
    table["index"] = np.arange(len(table), dtype=np.int32)
    return table


def choose_sector_provider(candidates, incumbent):
    """Compare audited evidence vectors; recency breaks genuinely comparable ties.

    Vectors must share `comparison_basis`; unknown or incomparable evidence does
    not acquire a fabricated numeric score. The caller supplies source findings.
    """
    if not candidates or not any(x["provider"] == incumbent for x in candidates):
        raise ValueError("Sector comparison requires its incumbent candidate")
    chosen = copy.deepcopy(next(x for x in candidates if x["provider"] == incumbent))
    reasons = []
    for candidate in sorted(candidates, key=lambda x: x["provider"]):
        if candidate["provider"] == chosen["provider"]: continue
        a, b = candidate.get("quality"), chosen.get("quality")
        comparable = (a is not None and b is not None and candidate.get("comparison_basis")
                      and candidate.get("comparison_basis") == chosen.get("comparison_basis")
                      and len(a) == len(b) and all(isinstance(v, (int, float)) and np.isfinite(v) for v in [*a, *b]))
        if not comparable:
            reasons.append({"candidate": candidate["provider"], "decision": "accuracy_unresolved; retained incumbent"})
            continue
        if tuple(a) > tuple(b) or (tuple(a) == tuple(b) and (candidate.get("publication_date", ""), candidate.get("release_date", ""), candidate["provider"]) > (chosen.get("publication_date", ""), chosen.get("release_date", ""), chosen["provider"])):
            chosen = copy.deepcopy(candidate)
    return {"provider": chosen["provider"], "selected_evidence": chosen, "unresolved": reasons,
            "tie_rule": "later publication, then data release; only comparable evidence"}


def _save_csr(folder, name, matrix):
    matrix = sparse.csr_matrix(matrix, dtype=np.float32)
    matrix.sum_duplicates(); matrix.sort_indices()
    for suffix, value in (("data", matrix.data), ("indices", matrix.indices.astype(np.int32)), ("indptr", matrix.indptr.astype(np.int64))):
        np.save(folder/f"{name}_{suffix}.npy", value, allow_pickle=False)


def assemble_banc(root, progress=None):
    sources = acquire_banc(root, progress)
    folder = _folder(root, BANC_ID); folder.mkdir(parents=True, exist_ok=True)
    raw = Path(root)/"data/raw/models"/BANC_ID
    neurons = normalize_banc_neurons(pd.read_feather(raw/"metadata.feather"))
    edges = pd.read_feather(raw/"edgelist.feather")
    alternatives = (("pre_pt_root_id", "post_pt_root_id", "syn_count"), ("pre", "post", "weight"), ("pre_id", "post_id", "weight"), ("pre", "post", "count"))
    fields = next((x for x in alternatives if set(x).issubset(edges)), None)
    if fields is None:
        # Authors currently use pre_id/post_id/syn_count; retain strict names.
        fields = next((x for x in (("pre_id", "post_id", "syn_count"), ("pre", "post", "syn_count"), ("pre_root_id", "post_root_id", "syn_count"), ("pre", "post", "n_synapses")) if set(x).issubset(edges)), None)
    if fields is None:
        raise ValueError("Unsupported BANC edgelist schema: " + ", ".join(edges.columns))
    pre_key, post_key, weight_key = fields
    ids = pd.Index(neurons.root_id)
    pre = ids.get_indexer(pd.to_numeric(edges[pre_key], errors="raise").astype(np.int64))
    post = ids.get_indexer(pd.to_numeric(edges[post_key], errors="raise").astype(np.int64))
    counts = pd.to_numeric(edges[weight_key], errors="raise").to_numpy(np.float64)
    if not np.isfinite(counts).all() or np.any(counts < 0):
        raise ValueError("BANC synapse counts must be finite and nonnegative")
    keep = (pre >= 0)&(post >= 0)&(counts > 0)
    omitted = int((~keep).sum()); pre, post, counts = pre[keep], post[keep], counts[keep]
    nt = neurons.known_nt.where(neurons.known_nt.ne(""), neurons.top_nt).str.lower()
    sign = np.where(nt.str.contains("gaba|glutamate|histamine", regex=True), -1., 1.)
    # Same explicit point-neuron sign convention as historical Cognesia; not receptor-specific truth.
    signed = counts*sign[pre]
    graded = neurons.is_graded.to_numpy()[pre]
    n = len(neurons)
    _save_csr(folder, "graded", sparse.csr_matrix((signed[graded], (post[graded], pre[graded])), shape=(n, n)))
    _save_csr(folder, "spiking", sparse.csr_matrix((signed[~graded], (post[~graded], pre[~graded])), shape=(n, n)))
    neurons.to_parquet(folder/"neurons.parquet", index=False)
    files = sorted(["neurons.parquet", *[p.name for p in folder.glob("*.npy")]])
    manifest = {"schema_version": 1, "id": BANC_ID, "identity_namespace": "banc:888", "source": BANC_SOURCE,
                "materialization": 888, "species": "Drosophila melanogaster", "sex": "female", "stage": "adult",
                "source_artifacts": sources["files"], "neurons": n, "edges": len(signed), "excluded_non_neural_or_unmapped_edges": omitted,
                "output_hashes": {name: checksum(folder/name) for name in files}, "optical_mapping_supported": False,
                "warnings": ["BANC native synapses with Cognesia point-neuron dynamics: not a validated whole-animal simulation.",
                             "Glutamate/GABA/histamine inhibitory and other/unknown fast signs excitatory are explicit model assumptions.",
                             "Native latest root_id was not used: all graph identities use banc_888_id.",
                             "Source proofreading/problem flags retained; morphology and optical registration require source-specific assets."],
                "assembly": "postsynaptic rows, presynaptic columns; source-qualified exact IDs", "status": "ASSEMBLED"}
    manifest["model_hash"] = stable_hash(manifest); _freeze_model(root,folder,manifest); atomic_write_json(folder/"manifest.json", manifest)
    return manifest


def compile_fused_model(root, sector_candidates=None, progress=None):
    """Freeze one model from native wiring and explicit physiology providers.

    Incomparable donor anatomy is retained as evidence rather than forced into a
    false identity match. Checked homologies provide chemical/mode annotation
    overlays; native BANC edges maintain measured brain/cord continuity.
    """
    source = get_model_manifest(root, BANC_ID) if (_folder(root, BANC_ID)/"manifest.json").exists() else assemble_banc(root, progress)
    network = load_model_network(root, BANC_ID)
    neurons = network["neurons"].copy()
    decisions = {}
    property_evidence = {}
    for sector in sorted(neurons.region.fillna("unassigned").unique()):
        rows = neurons.loc[neurons.region.fillna("unassigned").eq(sector)]
        flags = rows.status.fillna("").str.split(",").explode(); flags = flags[flags.ne("")].value_counts()
        property_evidence[sector] = {
            "specimen_compatibility":{"species":"Drosophila melanogaster","sex":"female","stage":"adult","same_specimen_continuity":True},
            "connectivity":{"provider":BANC_ID,"native_neurons":len(rows),"source_proofread":int(rows.proofread.eq("TRUE").sum()),
                            "source_roughly_proofread":int(rows.roughly_proofread.eq("TRUE").sum()),"source_status_flags":flags.to_dict(),
                            "matched_sector_precision_recall":None,"comparative_accuracy":"unresolved"},
            "morphology":{"provider":BANC_ID,"representation":"source root anchors; source skeletons not imported by this assembly",
                          "finite_anchors":int(np.isfinite(rows[['pos_x','pos_y','pos_z']].to_numpy()).all(axis=1).sum()),"registration_error_um":None},
            "transmitter_identity":{"provider":BANC_ID,"verified_labels":int(rows.known_nt.fillna("").ne("").sum()),
                                    "predicted_labels":int(rows.top_nt.fillna("unknown").ne("unknown").sum()),
                                    "policy":"native verified labels first; holes may receive unique curator-checked donor annotation"},
            "peripheral_interfaces":{"provider":BANC_ID,"sensory_target_annotations":int(rows.body_part_sensory.fillna("").ne("").sum()),
                                     "effector_target_annotations":int(rows.body_part_effector.fillna("").ne("").sum())},
            "physiology":{"provider":"Cognesia model assumptions","matched_held_out_error":None,"biological_validation":"not established"}}
        defaults = [{"provider": BANC_ID, "publication_date": "2026-06-08", "comparison_basis": "native_continuous_specimen", "quality": None,
                     "evidence":property_evidence[sector]}]
        if sector in {"central_brain", "optic_lobe"}:
            defaults.append({"provider":"flywire-783","publication_date":"2024-10-02","comparison_basis":"regional_quality_not_yet_harmonized","quality":None,
                             "note":"Native neuron counts are not a comparable accuracy score. No automatic identity/circuit replacement without mapped evidence."})
        candidates = (sector_candidates or {}).get(sector, defaults)
        decisions[sector] = choose_sector_provider(candidates, BANC_ID)
        if decisions[sector]["provider"] != BANC_ID:
            # A source-quality claim does not itself define an executable mapping.
            raise ValueError(f"Sector {sector} chooses a donor without an imported checked circuit patch; import mapping and connectivity before compiling")
    ledger = []
    legacy_path = Path(root)/"build/neurons.parquet"
    if legacy_path.exists():
        legacy = pd.read_parquet(legacy_path).set_index("root_id")
        matches = neurons.get("fafb_match", pd.Series("", index=neurons.index)).fillna("")
        checked = neurons.status.fillna("").str.contains(r"(?:^|,)FAFB_MATCH_MANUALLY_CHECKED(?:,|$)", regex=True) & matches.str.fullmatch(r"\d+")
        checked &= ~matches.duplicated(keep=False)
        for i in np.flatnonzero(checked):
            root_id = int(matches.iloc[i])
            if root_id not in legacy.index: continue
            donor = legacy.loc[root_id]
            # Preserve experimental positive AND negative reports verbatim;
            # downstream source selectors parse only explicit positive tokens.
            for field in ("known_nt",):
                value = donor.get(field)
                if not neurons.at[i, field] and pd.notna(value) and str(value):
                    neurons.at[i, field] = str(value)
                    neurons.at[i, "known_nt_source"] = "Cross-specimen curated FAFB homology; " + str(donor.get("known_nt_source", "FlyWire annotation"))
                    from .neuromod.sources import parse_positive_nt
                    ledger.append({"entity_id": neurons.at[i, "entity_id"], "donor": f"flywire:783:{root_id}", "property": field, "value": str(value),
                                   "positive_tokens":sorted(parse_positive_nt(value)),"status": "inferred_from_curated_homology"})
    folder = _folder(root, FUSED_ID); folder.mkdir(parents=True, exist_ok=True)
    neurons.to_parquet(folder/"neurons.parquet", index=False)
    atomic_write_json(folder/"fusion_ledger.json", ledger)
    base_version = Path(root)/"build/model-versions"/source["model_hash"]
    if not base_version.exists():
        _freeze_model(root,_folder(root,BANC_ID),source)
    for name in source["output_hashes"]:
        if name.endswith(".npy"): shutil.copy2(base_version/name,folder/name)
    files = ["neurons.parquet","fusion_ledger.json",*[name for name in source["output_hashes"] if name.endswith(".npy")]]
    manifest = {"schema_version": 1, "id": FUSED_ID, "identity_namespace": "banc:888", "base_model": BANC_ID,
                "base_model_hash": source["model_hash"], "species": "Drosophila melanogaster", "sex": "female", "stage": "adult",
                "neurons": source["neurons"], "edges": source["edges"], "sector_decisions": decisions,"sector_property_evidence":property_evidence,
                "property_overlays": len(ledger),"positive_annotation_overlays":sum(bool(row["positive_tokens"]) for row in ledger),
                "negative_only_annotation_overlays":sum(not row["positive_tokens"] for row in ledger),
                "providers": {"connectivity": BANC_ID, "fast_synapse_signs":"BANC native verified/predicted labels under explicit sign convention",
                              "inferred_transmitter_annotations": "flywire-783 checked matches; negative reports retained without assigning positive release", "dynamics": "Cognesia hybrid point neuron", "body_physiology": "explicit modeled organ ports"},
                "output_hashes": {name: checksum(folder/name) for name in files},
                "optical_mapping_supported": False, "warnings": source["warnings"] + ["Fusion is a composite model, not a single measured fly. Unresolved homology retains BANC identity and wiring."], "status": "ASSEMBLED"}
    manifest["model_hash"] = stable_hash(manifest); _freeze_model(root,folder,manifest); atomic_write_json(folder/"manifest.json", manifest)
    return manifest


def load_model_network(root, model_id="flywire-783",model_hash=None):
    model_id,model_hash = _model_request(model_id or "flywire-783",model_hash)
    if model_id in (None, "flywire-783"):
        from .build import load_network
        result = load_network(root)
        result["neurons"] = result["neurons"].copy()
        result["neurons"]["entity_id"] = "flywire:783:"+result["neurons"].root_id.astype(str)
        result["manifest"] = get_model_manifest(root, "flywire-783",model_hash)
    else:
        manifest = get_model_manifest(root, model_id,model_hash)
        folder = Path(root)/"build/model-versions"/manifest["model_hash"]
        if not folder.exists():
            # Migrate an existing local assembly into the immutable store before
            # exposing it to an experiment; old source files are left untouched.
            _freeze_model(root,_folder(root,model_id),manifest)
        for name, digest in manifest["output_hashes"].items():
            if checksum(folder/name) != digest: raise ValueError("Compiled model changed: "+name)
        n = manifest["neurons"]
        base = folder
        if manifest.get("base_model") and not (folder/"graded_data.npy").exists():
            base_manifest = get_model_manifest(root, manifest["base_model"],manifest["base_model_hash"])
            base = Path(root)/"build/model-versions"/base_manifest["model_hash"]
            for name,digest in base_manifest["output_hashes"].items():
                if checksum(base/name)!=digest: raise ValueError("Frozen fused dependency changed: "+name)
        def matrix(name):
            return sparse.csr_matrix(tuple(np.load(base/f"{name}_{s}.npy", mmap_mode="r") for s in ("data", "indices", "indptr")), shape=(n,n), copy=False)
        result = {"neurons": pd.read_parquet(folder/"neurons.parquet"), "graded": matrix("graded"), "spiking": matrix("spiking"), "manifest": manifest, "summary": manifest}
        result["reference"] = result["graded"] + result["spiking"]
    result["model_id"] = result["manifest"]["id"]
    return result
