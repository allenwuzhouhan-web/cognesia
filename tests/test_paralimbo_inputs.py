"""Bootstrap publication is atomic and pinned files are never replaced."""
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from flybrain.fetch import checksum
from flybrain.inspect_data import atomic_write_json
from flybrain.model_registry import BANC_ID, _freeze_model, stable_hash

SCRIPT = Path(__file__).resolve().parents[1]/"scripts/prepare_paralimbo_inputs.py"
spec = importlib.util.spec_from_file_location("prepare_paralimbo_inputs", SCRIPT)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def source_spec(content):
    return {"url": "https://example.invalid/pinned/source", "bytes": len(content), "sha256": sha256(content).hexdigest()}


def test_download_verified_and_published_without_temporary_debris(tmp_path, monkeypatch):
    content = b"verified source"
    monkeypatch.setattr(bootstrap, "urlopen", lambda *args, **kwargs: io.BytesIO(content))
    result = bootstrap.acquire_source(tmp_path, Path("data/raw/source"), source_spec(content))
    target = tmp_path/"data/raw/source"
    assert target.read_bytes() == content
    assert result["downloaded"] is True
    assert result["path"] == "data/raw/source"
    assert list(target.parent.iterdir()) == [target]
    monkeypatch.setattr(bootstrap, "urlopen", lambda *a, **kw: pytest.fail("cached file should not download"))
    assert bootstrap.acquire_source(tmp_path, Path("data/raw/source"), source_spec(content))["downloaded"] is False


def test_existing_mismatch_refused_before_network_and_preserved(tmp_path, monkeypatch):
    target = tmp_path/"source"
    target.write_bytes(b"old content")
    monkeypatch.setattr(bootstrap, "urlopen", lambda *a, **kw: pytest.fail("mismatch must not download"))
    with pytest.raises(ValueError, match="mismatched SHA256"):
        bootstrap.acquire_source(tmp_path, Path("source"), source_spec(b"new content"))
    assert target.read_bytes() == b"old content"


@pytest.mark.parametrize("received", [b"bad", b"123456", b"too long to be valid"])
def test_download_mismatch_never_publishes_partial_file(tmp_path, monkeypatch, received):
    monkeypatch.setattr(bootstrap, "urlopen", lambda *args, **kwargs: io.BytesIO(received))
    with pytest.raises(ValueError):
        bootstrap.acquire_source(tmp_path, Path("source"), source_spec(b"abcdef"))
    assert not (tmp_path/"source").exists()
    assert list(tmp_path.iterdir()) == []


def test_interrupted_download_never_publishes_partial_file(tmp_path, monkeypatch):
    class Interrupted(io.BytesIO):
        def read(self, *args):
            raise OSError("interrupted transfer")
    monkeypatch.setattr(bootstrap, "urlopen", lambda *args, **kwargs: Interrupted(b"abc"))
    with pytest.raises(OSError, match="interrupted"):
        bootstrap.acquire_source(tmp_path, Path("source"), source_spec(b"abcdef"))
    assert list(tmp_path.iterdir()) == []


def test_concurrent_target_is_not_overwritten(tmp_path):
    staged, target = tmp_path/"staged", tmp_path/"target"
    staged.write_bytes(b"new")
    target.write_bytes(b"old")
    with pytest.raises(ValueError, match="mismatched SHA256"):
        bootstrap._publish_file(staged, target, checksum(staged))
    assert target.read_bytes() == b"old"
    target.write_bytes(b"new")
    assert bootstrap._publish_file(staged, target, checksum(staged)) is False


@pytest.fixture
def donor_inputs(tmp_path, monkeypatch):
    raw, config = tmp_path/"data/raw", tmp_path/"config"
    raw.mkdir(parents=True)
    config.mkdir()
    completeness = pd.DataFrame({"Unnamed: 0": [720575940632081439], "Completed": [True]})
    annotations = pd.DataFrame({"root_id": [720575940632081439], "cell_type": ["X"], "super_class": ["central"], "known_nt": ["gaba"]})
    completeness.to_csv(raw/"Completeness_783.csv", index=False)
    annotations.to_csv(raw/"Supplemental_file1_neuron_annotations.tsv", sep="\t", index=False)
    modes = config/"neuron_modes.csv"
    modes.write_text("cell_type,mode,source\nX,spiking,ASSUMPTION\n")
    monkeypatch.setattr(bootstrap, "FLYWIRE_MODE_CONFIG_SHA256", checksum(modes))
    expected = completeness.rename(columns={"Unnamed: 0": "root_id"}).merge(annotations, on="root_id", how="left", sort=False, validate="one_to_one")
    expected.insert(0, "index", np.arange(len(expected), dtype=np.int32))
    expected["is_graded"] = False
    expected["mode"] = "spiking"
    expected_path = tmp_path/"expected.parquet"
    expected.to_parquet(expected_path, index=False)
    monkeypatch.setattr(bootstrap, "FLYWIRE_NEURONS_SHA256", checksum(expected_path))
    return tmp_path, modes


def test_donor_reconstruction_uses_only_annotation_sources_and_preserves_config(donor_inputs):
    root, modes = donor_inputs
    original = modes.read_bytes()
    result = bootstrap.prepare_donor(root)
    assert result["reused"] is False
    assert checksum(root/"build/neurons.parquet") == bootstrap.FLYWIRE_NEURONS_SHA256
    assert modes.read_bytes() == original
    assert not (root/"data/raw/Connectivity_783.parquet").exists()
    assert [p.name for p in (root/"build").iterdir()] == ["neurons.parquet"]
    assert bootstrap.prepare_donor(root)["reused"] is True


def test_donor_mismatch_leaves_no_output_and_config_unchanged(donor_inputs, monkeypatch):
    root, modes = donor_inputs
    original = modes.read_bytes()
    monkeypatch.setattr(bootstrap, "FLYWIRE_NEURONS_SHA256", "0"*64)
    with pytest.raises(ValueError, match="mismatched SHA256"):
        bootstrap.prepare_donor(root)
    assert modes.read_bytes() == original
    assert list((root/"build").iterdir()) == []


def test_existing_donor_mismatch_is_not_overwritten(donor_inputs):
    root, _ = donor_inputs
    (root/"build").mkdir()
    path = root/"build/neurons.parquet"
    path.write_bytes(b"existing")
    with pytest.raises(ValueError, match="mismatched SHA256"):
        bootstrap.prepare_donor(root)
    assert path.read_bytes() == b"existing"


def test_dependency_lock_enforced(tmp_path, monkeypatch):
    (tmp_path/"requirements.lock").write_text("pandas==1.0\n-e .\n")
    monkeypatch.setattr(bootstrap, "version", lambda name: "2.0")
    with pytest.raises(ValueError, match="Install requirements.lock"):
        bootstrap.verify_dependencies(tmp_path)
    monkeypatch.setattr(bootstrap, "version", lambda name: "1.0")
    assert bootstrap.verify_dependencies(tmp_path)["checked_packages"] == 1


def test_verified_existing_frozen_baseline_reused_without_touching_alias(tmp_path, monkeypatch):
    source = tmp_path/"fixture"
    source.mkdir()
    (source/"artifact.bin").write_bytes(b"baseline")
    manifest = {"id": BANC_ID, "output_hashes": {"artifact.bin": checksum(source/"artifact.bin")}}
    manifest["model_hash"] = stable_hash(manifest)
    _freeze_model(tmp_path, source, manifest)
    monkeypatch.setattr(bootstrap, "BANC_BASELINE_HASH", manifest["model_hash"])
    monkeypatch.setattr(bootstrap, "assemble_banc", lambda *a, **kw: pytest.fail("existing baseline must not rebuild"))
    alias = tmp_path/"build/models"/BANC_ID
    alias.mkdir(parents=True)
    (alias/"old.txt").write_text("preserved")
    result = bootstrap.prepare_banc(tmp_path)
    assert result["reused"] is True
    assert (alias/"old.txt").read_text() == "preserved"
    frozen = tmp_path/result["path"]/"artifact.bin"
    frozen.write_bytes(b"changed!")
    with pytest.raises(ValueError, match="mismatched SHA256"):
        bootstrap.prepare_banc(tmp_path)
