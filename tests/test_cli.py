from pathlib import Path
from flybrain import cli
from flybrain import validate_hybrid


def _install_result(monkeypatch, result):
    monkeypatch.setattr(validate_hybrid, "validate_hybrid", lambda *a, **kw: result)
    monkeypatch.setattr(cli, "write_report", lambda root: root / "REPORT.md")


def test_failed_hybrid_launcher_is_nonzero(tmp_path, monkeypatch, capsys):
    result = {"stage4_status": "FAIL", "gates": [{"gate": "V-C", "status": "FAIL"}, {"gate": "V-D", "status": "NOT-RUN"}]}
    _install_result(monkeypatch, result)
    assert cli.main(["--root", str(tmp_path), "run", "dark"]) == 1
    output = capsys.readouterr().out
    assert "V-C: FAIL" in output and "V-D: NOT-RUN" in output


def test_unfinished_vc_is_not_a_successful_gate(tmp_path, monkeypatch):
    _install_result(monkeypatch, {"stage4_status": "PASS", "gates": [{"gate": "V-C", "status": "NOT-RUN"}, {"gate": "V-D", "status": "PASS"}]})
    assert cli.main(["--root", str(tmp_path), "validate", "--gate", "V-C"]) == 1


def test_nonfinite_failure_can_be_displayed(capsys):
    cli.print_result({"gate": "V-C", "status": "FAIL", "equilibration": {"max_abs_dvdt_mV_per_ms": None, "unstable_neurons": 1, "clamp_events": 0}}, Path("/project"))
    assert "non-finite" in capsys.readouterr().out


def test_dark_does_not_silently_ignore_reference_options(tmp_path, monkeypatch):
    failures = []
    monkeypatch.setattr(cli, "record_error", lambda root, stage, error: failures.append(str(error)))
    assert cli.main(["--root", str(tmp_path), "run", "dark", "--integrator", "exact_linear"]) == 1
    assert "not accepted" in failures[0]


def test_failed_capacity_writes_report_and_exits_nonzero(tmp_path, monkeypatch):
    from flybrain.rt import capacity
    reports = []
    monkeypatch.setattr(capacity, 'measure_capacity', lambda *a, **kw: {
        'status': 'FAIL', 'checks': [{'name': 'capacity_execution', 'status': 'FAIL'}]})
    monkeypatch.setattr(cli, 'write_report', lambda root: reports.append(root))
    assert cli.main(['--root', str(tmp_path), 'capacity', '--full']) == 1
    assert reports == [tmp_path.resolve()]
