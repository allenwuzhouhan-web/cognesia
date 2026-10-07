"""Failure reporting must distinguish a tested audit from a validated model."""
import json

from flybrain import cli
from flybrain.report import write_report


def test_neuromod_cli_returns_nonzero_and_renders_count_failure(tmp_path, monkeypatch, capsys):
    from flybrain.neuromod import pipeline
    result = {"gate": "V-NM-C", "status": "FAIL", "checks": [
        {"name": "ALPN_neurons", "status": "FAIL", "expected": 2960, "observed": 685}
    ], "stop_reason": "Exact release-count mismatch; dependent stages stopped."}
    monkeypatch.setattr(pipeline, "build_neuromod", lambda root: result)
    monkeypatch.setattr(cli, "write_report", lambda root: None)
    assert cli.main(["--root", str(tmp_path), "neuromod", "build"]) == 1
    output = capsys.readouterr().out
    assert "expected 2960; observed 685" in output
    assert "V-NM-C: FAIL" in output
    assert "dependent stages stopped" in output


def test_corrected_source_audit_success_exits_zero(tmp_path, monkeypatch, capsys):
    from flybrain.neuromod import pipeline
    monkeypatch.setattr(pipeline, "build_neuromod", lambda root: {"gate": "V-NM-C", "status": "PASS"})
    monkeypatch.setattr(cli, "write_report", lambda root: None)
    assert cli.main(["--root", str(tmp_path), "neuromod", "build"]) == 0
    assert "V-NM-C: PASS" in capsys.readouterr().out


def test_reference_validation_returns_nonzero_despite_correct_kernel_tests(tmp_path, monkeypatch, capsys):
    from flybrain.neuromod import plasticity
    monkeypatch.setattr(plasticity, "validate_plasticity", lambda root: {
        "gate": "V-NM-E", "status": "FAIL",
        "checks": [{"name": "twelve_point_reference_within_1e-3", "status": "FAIL", "expected": True, "observed": False}],
        "metrics": {"max_absolute_reference_error": .076743},
        "stop_reason": "Reference mismatch; no network training executed."})
    monkeypatch.setattr(cli, "write_report", lambda root: None)
    assert cli.main(["--root", str(tmp_path), "validate", "--gate", "V-NM-E"]) == 1
    output = capsys.readouterr().out
    assert "V-NM-E: FAIL" in output
    assert "twelve_point_reference_within_1e-3" in output
    assert "no network training executed" in output
    assert "Mean firing-rate correlation" not in output


def test_headless_pipeline_stops_before_dependent_stages(tmp_path, monkeypatch):
    from flybrain.neuromod import pipeline
    calls = []
    def stage(name, status):
        def run(root):
            calls.append(name)
            return {"gate": name, "status": status}
        return run
    monkeypatch.setattr(pipeline, "build_sources", stage("V-NM-C", "PASS"))
    monkeypatch.setattr(pipeline, "build_compartments", stage("V-NM-COMP", "FAIL"))
    for name in ("validate_field", "build_odours", "validate_core_stationarity", "validate_receptors"):
        monkeypatch.setattr(pipeline, name, stage(name, "PASS"))
    result = pipeline.build_neuromod(tmp_path)
    assert result["status"] == "FAIL"
    assert calls == ["V-NM-C", "V-NM-COMP"]
    assert "dependent stages were not run" in result["stop_reason"]


def test_report_preserves_failed_source_measurement_and_missing_gates(tmp_path):
    (tmp_path / "NEUROMOD_BUILD_BRIEF.md").write_text("fixture specification")
    build = tmp_path / "build"
    build.mkdir()
    (build / "validation_neuromod_sources.json").write_text(json.dumps({
        "gate": "V-NM-C", "status": "FAIL", "checks": [
            {"name": "ALPN_neurons", "status": "FAIL", "expected": 2960, "observed": 685}
        ]}))
    report = write_report(tmp_path).read_text()
    assert "| ALPN_neurons | 2960 | 685 | FAIL |" in report
    assert "| V-NM-B | software | 60 s event-log replay determinism | NOT-RUN | not measured |" in report
    assert "| V-NM-F' | software | 60 s real-time budget and resident memory | NOT-RUN | not measured |" in report


def test_neuromod_parameters_survive_report_regeneration(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "parameters.yaml").write_text("parameters: {}\n")
    (config / "neuromod.yaml").write_text("parameters:\n  policy:\n    value: true\n    unit: boolean\n    source: ASSUMPTION\n    sweep: [true, false]\n")
    write_report(tmp_path)
    assert "| policy | True | boolean | ASSUMPTION |" in (tmp_path / "PARAMETERS.md").read_text()


def test_changed_base_or_derived_artifact_invalidates_historical_pass(tmp_path):
    from flybrain.fetch import checksum
    from flybrain.neuromod.report import _verify_artifacts
    build = tmp_path / "build"
    build.mkdir()
    (build / "base.npz").write_bytes(b"base fixture")
    (build / "source.parquet").write_bytes(b"source fixture")
    entry = {"gate": "V-NM-C", "status": "PASS",
             "base_artifact_hashes": {"base.npz": checksum(build / "base.npz")},
             "artifact_hashes": {"source.parquet": checksum(build / "source.parquet")}}
    assert _verify_artifacts(entry, tmp_path)["status"] == "PASS"
    (build / "base.npz").write_bytes(b"modified fixture")
    changed = _verify_artifacts(entry, tmp_path)
    assert changed["status"] == "NOT-RUN"
    assert "base.npz" in " ".join(changed["stale_evidence_reasons"])
    (build / "source.parquet").unlink()
    missing = _verify_artifacts(entry, tmp_path)
    assert "source.parquet" in " ".join(missing["stale_evidence_reasons"])


def test_changed_base_configuration_invalidates_historical_pass(tmp_path):
    from flybrain.fetch import checksum
    from flybrain.neuromod.report import _verify_artifacts
    config = tmp_path / "config"
    config.mkdir()
    path = config / "sign_overrides.csv"
    path.write_text("original fixture")
    entry = {"gate": "V-NM-A", "status": "PASS", "base_config_hashes": {path.name: checksum(path)}}
    assert _verify_artifacts(entry, tmp_path)["status"] == "PASS"
    path.write_text("changed fixture")
    changed = _verify_artifacts(entry, tmp_path)
    assert changed["status"] == "NOT-RUN"
    assert "Base configuration changed" in changed["stale_evidence_reasons"][0]


def test_stale_upstream_gate_invalidates_downstream_pass_transitively():
    from flybrain.neuromod.report import _propagate_dependency_status
    results = {gate: ({"status": "PASS"}, gate + ".json") for gate in
               ("V-NM-C", "V-NM-COMP", "V-NM-CORE", "V-NM-ODOUR", "V-NM-D", "V-NM-A")}
    results["V-NM-COMP"] = ({"status": "NOT-RUN", "previous_status": "PASS"}, "comp.json")
    _propagate_dependency_status(results)
    assert results["V-NM-D"][0]["status"] == "NOT-RUN"
    assert results["V-NM-A"][0]["status"] == "NOT-RUN"
    assert results["V-NM-CORE"][0]["status"] == "PASS"
    assert results["V-NM-ODOUR"][0]["status"] == "PASS"
    assert "V-NM-D" in results["V-NM-A"][0]["stale_evidence_reasons"][0]


def test_failed_measurement_is_preserved_as_history_when_inputs_change(tmp_path):
    from flybrain.fetch import checksum
    from flybrain.report import _current_result
    from flybrain.neuromod.report import _verify_artifacts
    config = tmp_path / 'config'
    config.mkdir()
    path = config / 'neuromod.yaml'
    path.write_text('original configuration')
    entry = {'gate': 'V-NM-ODSP', 'status': 'FAIL',
             'config_hashes': {'neuromod.yaml': checksum(path)},
             'dependency_hashes': {'config/neuromod.yaml': checksum(path)}}
    path.write_text('changed configuration')
    current = _current_result(entry, tmp_path, {}, {}, [], [])
    assert current['status'] == 'NOT-RUN'
    assert current['previous_status'] == 'FAIL'
    assert any('neuromod.yaml' in reason for reason in current['stale_evidence_reasons'])
    derived = _verify_artifacts(entry, tmp_path)
    assert derived['status'] == 'NOT-RUN'
    assert derived['previous_status'] == 'FAIL'
    assert entry['status'] == 'FAIL'
