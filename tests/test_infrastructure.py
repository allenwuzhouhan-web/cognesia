from pathlib import Path
import importlib
import json
import os
import pytest

from flybrain.fetch import checksum, download
from flybrain.memguard import MemoryGuard, MemoryLimitExceeded
from flybrain.report import record_error, write_report
from flybrain.inspect_data import atomic_write_json, stat_signature


def test_checksum_and_atomic_download(tmp_path):
    source = tmp_path / "source.txt"
    source.write_bytes(b"real bytes")
    dest = tmp_path / "output.txt"
    download(source.as_uri(), dest)
    assert checksum(source) == checksum(dest)
    assert not dest.with_suffix(".txt.part").exists()


def test_failed_download_preserves_previous_file(tmp_path):
    dest = tmp_path / "output.txt"
    dest.write_text("keep")
    with pytest.raises(Exception):
        download((tmp_path / "missing").as_uri(), dest)
    assert dest.read_text() == "keep"
    assert not dest.with_suffix(".txt.part").exists()


def test_memory_guard_rejects_over_limit_process():
    with pytest.raises(MemoryLimitExceeded):
        with MemoryGuard(limit_gb=1e-9):
            pass


def test_missing_evidence_is_not_a_pass(tmp_path):
    report = write_report(tmp_path).read_text()
    assert report.count("| NOT-RUN |") == 9
    record_error(tmp_path, "fetch", ValueError("schema mismatch"))
    assert "schema mismatch" in (tmp_path / "REPORT.md").read_text()
    assert json.loads((tmp_path / "build/stage_errors.json").read_text())[0]["stage"] == "fetch"


def test_atomic_evidence_replace_failure_preserves_previous_json(tmp_path, monkeypatch):
    target = tmp_path / "downloads.json"
    atomic_write_json(target, {"files": {"old": "verified"}})

    def interrupted_replace(*args):
        raise OSError("simulated interruption before replacement")

    monkeypatch.setattr("flybrain.inspect_data.os.replace", interrupted_replace)
    with pytest.raises(OSError, match="interruption"):
        atomic_write_json(target, {"files": {"new": "uncommitted"}})
    assert json.loads(target.read_text()) == {"files": {"old": "verified"}}
    assert list(tmp_path.glob("*.tmp")) == []


def test_fetch_retains_completed_inspections_when_next_download_fails(tmp_path, monkeypatch):
    fetch_module = importlib.import_module("flybrain.fetch")
    source = tmp_path / "source.csv"
    source.write_text("root_id,Completed\n123,True\n")
    monkeypatch.setattr(fetch_module, "SOURCES", {
        "first.csv": source.as_uri(),
        "missing.csv": (tmp_path / "missing.csv").as_uri(),
    })
    root = tmp_path / "run"
    with pytest.raises(Exception):
        fetch_module.fetch(root, neuropils=False)
    manifest = json.loads((root / "build/downloads.json").read_text())
    inspections = json.loads((root / "build/schema_inspection.json").read_text())
    assert manifest["files"]["first.csv"]["sha256"] == checksum(source)
    assert manifest["files"]["first.csv"]["stat"] == stat_signature(root / "data/raw/first.csv")
    assert inspections["first.csv"]["rows"] == 1
    assert inspections["first.csv"]["first_three_rows"] == [{"root_id": 123, "Completed": True}]
    failures = json.loads((root / "build/integrity_failures.json").read_text())
    assert "missing.csv" in failures


def test_fetch_checksum_mismatch_preserves_manifest_and_clears_only_after_repair(tmp_path, monkeypatch):
    fetch_module = importlib.import_module("flybrain.fetch")
    source = tmp_path / "source.csv"
    source.write_text("id\n1\n")
    metadata = tmp_path / "record.json"
    metadata.write_text('{"files": []}')
    monkeypatch.setattr(fetch_module, "SOURCES", {
        "input.csv": source.as_uri(), "zenodo_record_10676866.json": metadata.as_uri()})
    root = tmp_path / "run"
    fetch_module.fetch(root, neuropils=False)
    manifest_path = root / "build/downloads.json"
    original_manifest = manifest_path.read_text()
    cached = root / "data/raw/input.csv"
    cached.write_text("id\n2\n")
    with pytest.raises(ValueError, match="Cached release changed"):
        fetch_module.fetch(root, neuropils=False)
    assert manifest_path.read_text() == original_manifest
    failures_path = root / "build/integrity_failures.json"
    failure = json.loads(failures_path.read_text())["input.csv"]
    assert failure["observed_sha256"] != failure["expected_sha256"]
    cached.write_bytes(source.read_bytes())
    fetch_module.fetch(root, neuropils=False)
    assert json.loads(failures_path.read_text()) == {}
    assert json.loads(manifest_path.read_text())["files"]["input.csv"]["stat"] == stat_signature(cached)


def _bound_passing_gate(root):
    source = root / "data/raw/input.csv"
    source.parent.mkdir(parents=True)
    source.write_text("id\n1\n")
    digest = checksum(source)
    atomic_write_json(root / "build/downloads.json", {
        "files": {source.name: {"sha256": digest, "stat": stat_signature(source)}}})
    result = {"gate": "V-A", "status": "PASS", "created_at": "2001-01-01T00:00:00+00:00",
              "source_hashes": {source.name: digest},
              "source_stats": {source.name: stat_signature(source)}}
    atomic_write_json(root / "build/validation_data.json", result)
    return source, result


def test_report_retains_bound_pass_without_rehashing_inputs(tmp_path, monkeypatch):
    _bound_passing_gate(tmp_path)

    def unexpected_hash(*args):
        raise AssertionError("Report must not rehash large source files")

    monkeypatch.setattr("flybrain.fetch.checksum", unexpected_hash)
    assert "| V-A | Data integrity | PASS |" in write_report(tmp_path).read_text()


def test_report_invalidates_pass_when_source_changes(tmp_path):
    source, original = _bound_passing_gate(tmp_path)
    source.write_text("id\n2\n")
    previous_mtime = original["source_stats"][source.name]["mtime_ns"]
    os.utime(source, ns=(previous_mtime + 1_000_000, previous_mtime + 1_000_000))
    report = write_report(tmp_path).read_text()
    assert "| V-A | Data integrity | NOT-RUN |" in report
    assert "Input changed since validation" in report
    # Historical evidence is retained rather than overwritten as a new run.
    assert json.loads((tmp_path / "build/validation_data.json").read_text())["status"] == "PASS"


@pytest.mark.parametrize("failure_kind", ["manifest", "integrity", "later_stage", "missing_input"])
def test_report_invalidates_stale_evidence(tmp_path, failure_kind):
    source, _ = _bound_passing_gate(tmp_path)
    if failure_kind == "manifest":
        atomic_write_json(tmp_path / "build/downloads.json", {
            "files": {source.name: {"sha256": "changed"}}})
    elif failure_kind == "integrity":
        atomic_write_json(tmp_path / "build/integrity_failures.json", {
            source.name: {"error": "publisher checksum failed"}})
    elif failure_kind == "later_stage":
        record_error(tmp_path, "fetch", ValueError("cached source changed"))
    else:
        source.unlink()
    report = write_report(tmp_path).read_text()
    assert "| V-A | Data integrity | NOT-RUN |" in report
    assert '"previous_status": "PASS"' in report


def test_resolved_older_error_does_not_invalidate_newer_gate(tmp_path):
    _bound_passing_gate(tmp_path)
    atomic_write_json(tmp_path / "build/stage_errors.json", [
        {"stage": "fetch", "time": "2000-01-01T00:00:00+00:00", "error": "old failure"}])
    assert "| V-A | Data integrity | PASS |" in write_report(tmp_path).read_text()


def test_unbound_pass_and_corrupt_manifest_are_not_reported_as_current(tmp_path):
    atomic_write_json(tmp_path / "build/validation_data.json", {"gate": "V-A", "status": "PASS"})
    assert "| V-A | Data integrity | NOT-RUN |" in write_report(tmp_path).read_text()
    source, _ = _bound_passing_gate(tmp_path)
    (tmp_path / "build/downloads.json").write_text("{truncated")
    report = write_report(tmp_path).read_text()
    assert "| V-A | Data integrity | NOT-RUN |" in report
    assert "Cannot read downloads.json" in report
