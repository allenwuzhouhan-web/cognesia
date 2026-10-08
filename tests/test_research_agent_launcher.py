"""Launcher contracts without touching running Cognesia or model processes."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import stat
import sys
import time
from types import SimpleNamespace

import pytest


@pytest.fixture
def launcher(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location('research_launcher_under_test', scripts / 'start_research_agent.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verified_model(root, evidence='valid'):
    model = root / 'data/models/gpt-oss-20b/gpt-oss-20b-MXFP4.gguf'
    model.parent.mkdir(parents=True)
    model.write_bytes(b'GGUFtest-model')
    info = model.stat()
    manifest = model.with_suffix('.verified.json')
    values = {'verified': True, 'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns, 'sha256': 'a' * 64}
    if evidence == 'missing':
        return model
    if evidence == 'malformed':
        manifest.write_text('{incomplete')
        return model
    if evidence == 'array':
        values = []
    elif evidence == 'changed':
        values['mtime_ns'] -= 1
    elif evidence == 'truthy':
        values['verified'] = 'yes'
    elif evidence == 'no-hash':
        del values['sha256']
    manifest.write_text(json.dumps(values))
    return model


def mock_services(module, monkeypatch, viewer_port=8794, agent_port=8797):
    services, processes, viewers = {}, [], []
    viewer_url = f'http://127.0.0.1:{viewer_port}'
    agent_url = f'http://127.0.0.1:{agent_port}'
    monkeypatch.setattr(module, '_read_health', lambda url: services.get(url))
    monkeypatch.setattr(module, '_port_occupied', lambda port: False)
    monkeypatch.setattr(module, '_model_executable', lambda: '/trusted/llama-server')
    monkeypatch.setattr(module.webbrowser, 'open', lambda url: pytest.fail('Native launch must not open a browser'))
    def start_viewer(root, **kwargs):
        viewers.append(kwargs)
        services[viewer_url] = {'service': module.VIEWER_SERVICE, 'access_required':True}
        return viewer_url
    def popen(command, **kwargs):
        processes.append((command, kwargs))
        time.sleep(.02)
        services[agent_url] = {'service': module.AGENT_SERVICE, 'viewer_url': viewer_url, 'access_required':True}
        return SimpleNamespace(pid=34567, poll=lambda: None)
    monkeypatch.setattr(module, 'start_viewer', start_viewer)
    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    return SimpleNamespace(services=services, processes=processes, viewers=viewers,
                           viewer_url=viewer_url, agent_url=agent_url)


def test_concurrent_launchers_start_one_console_and_keep_runtime_files_private(launcher,monkeypatch,tmp_path):
    f = mock_services(launcher, monkeypatch)
    verified_model(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(launcher.start, tmp_path, open_browser=False) for _ in range(2)]
        assert [future.result(timeout=5) for future in futures] == [f.agent_url, f.agent_url]
    assert len(f.processes) == 1 and len(f.viewers) == 1
    assert '--start-model' in f.processes[0][0]
    assert f.viewers[0] == {'port':8794, 'open_browser':False}
    runtime = tmp_path / 'build/runtime'
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o700
    for path in [*runtime.iterdir(), *(tmp_path / 'runs').iterdir()]:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_custom_native_ports_and_no_start_model_are_forwarded(launcher,monkeypatch,tmp_path):
    f = mock_services(launcher, monkeypatch, viewer_port=9024, agent_port=9027)
    model = verified_model(tmp_path)
    assert launcher.start(tmp_path, viewer_port=9024, agent_port=9027,
                          open_browser=False, start_model=False) == f.agent_url
    command = f.processes[0][0]
    assert command[command.index('--port') + 1] == '9027'
    assert command[command.index('--viewer-url') + 1] == f.viewer_url
    assert command[command.index('--model-file') + 1] == str(model)
    assert '--start-model' not in command
    assert (tmp_path / 'build/runtime/research-agent-9027.pid').read_text() == '34567\n'


@pytest.mark.parametrize('evidence',['missing','malformed','array','changed','truthy','no-hash'])
def test_unverified_or_malformed_manifest_only_prefills_setup(launcher,monkeypatch,tmp_path,evidence):
    f = mock_services(launcher, monkeypatch)
    verified_model(tmp_path, evidence)
    launcher.start(tmp_path, open_browser=False)
    command = f.processes[0][0]
    assert '--model-file' in command and '--llama-server' in command
    assert '--start-model' not in command


@pytest.mark.parametrize('problem',['wrong-service','occupied','wrong-viewer'])
def test_occupied_or_mismatched_agent_port_fails_without_spawning(launcher,monkeypatch,tmp_path,problem):
    f = mock_services(launcher, monkeypatch)
    if problem == 'wrong-service':
        f.services[f.agent_url] = {'service':'another-app'}
    elif problem == 'wrong-viewer':
        f.services[f.agent_url] = {'service':launcher.AGENT_SERVICE, 'viewer_url':'http://127.0.0.1:9999', 'access_required':True}
    else:
        monkeypatch.setattr(launcher, '_port_occupied', lambda port: port == 8797)
    with pytest.raises(RuntimeError, match='another|occupied'):
        launcher.start(tmp_path, open_browser=False)
    assert not f.processes and not f.viewers


def test_wrong_viewer_port_fails_before_launching_services(launcher,monkeypatch,tmp_path):
    f = mock_services(launcher, monkeypatch)
    f.services[f.viewer_url] = {'service':'unrelated-server'}
    with pytest.raises(RuntimeError, match='another service'):
        launcher.start(tmp_path, open_browser=False)
    assert not f.processes and not f.viewers


def test_existing_model_listener_does_not_launch_duplicate_weights(launcher,monkeypatch,tmp_path):
    f = mock_services(launcher, monkeypatch)
    verified_model(tmp_path)
    f.services[f.viewer_url] = {'service':launcher.VIEWER_SERVICE, 'access_required':True}
    monkeypatch.setattr(launcher, '_port_occupied', lambda port: port == 8080)
    with pytest.raises(RuntimeError, match='no second model'):
        launcher.start(tmp_path, open_browser=False)
    assert not f.processes and not f.viewers


def test_native_cli_switches_and_port_validation(launcher,monkeypatch,tmp_path):
    captured = []
    monkeypatch.setattr(launcher, 'start', lambda root, **kwargs: captured.append(kwargs))
    launcher.main(['--no-browser','--viewer-port','9024','--agent-port','9027','--no-start-model'])
    assert captured == [{'viewer_port':9024,'agent_port':9027,'open_browser':False,'start_model':False}]
    assert launcher._port(8797) == 8797
    for bad in (True,0,65536,'8797'):
        with pytest.raises(ValueError):launcher._port(bad)


def test_older_ungated_service_is_never_reused(launcher,monkeypatch,tmp_path):
    f = mock_services(launcher, monkeypatch)
    f.services[f.agent_url] = {'service':launcher.AGENT_SERVICE, 'viewer_url':f.viewer_url}
    with pytest.raises(RuntimeError, match='unprotected'):
        launcher.start(tmp_path, open_browser=False)
    assert not f.processes and not f.viewers
