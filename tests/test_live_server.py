"""Reload admission and HTTP behavior without loading release model data."""

from concurrent.futures import Future
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import signal
import threading
from types import SimpleNamespace

import pytest

from flybrain import live_server, visual_server
from flybrain.live_reload import ProjectWatcher
from flybrain.visual_server import ACTIVE_STATUSES, VisualState, make_handler


@pytest.fixture
def state(tmp_path):
    state = VisualState.__new__(VisualState)
    state.root = tmp_path
    state.lock = threading.Lock()
    state.jobs = {}
    state.model_jobs = {}
    state.morphology_job = None
    state.processes = {}
    state.futures = {}
    state.active_requests = 0
    state.reload_draining = False
    state.live_watcher = None
    state.instance_id = "test-instance"
    state.loaded_backend_revision = None
    return state


def test_reload_waits_for_existing_requests_and_rejects_new_requests(state):
    with state.request_operation():
        assert state.active_requests == 1
        with state.request_operation():
            assert state.active_requests == 2
            assert not state.begin_reload()
        assert state.active_requests == 1
        assert not state.reload_draining
    assert state.active_requests == 0
    assert state.begin_reload()
    with pytest.raises(RuntimeError, match="Applying project changes"):
        with state.request_operation():
            pytest.fail("New operations cannot enter a draining server")
    assert state.active_requests == 0


def test_request_failure_releases_reload_admission(state):
    with pytest.raises(ValueError, match="failed request"):
        with state.request_operation():
            raise ValueError("failed request")
    assert state.active_requests == 0
    assert state.begin_reload()


@pytest.mark.parametrize("status", ACTIVE_STATUSES)
@pytest.mark.parametrize("kind", ["session", "model", "morphology"])
def test_live_work_blocks_reload_even_when_paused(state, kind, status):
    job = {"status": status}
    if kind == "session":
        state.jobs["test"] = job
    elif kind == "model":
        state.model_jobs["test"] = job
    else:
        state.morphology_job = job
    assert state.live_reload_status()["busy"] is True
    assert not state.begin_reload()
    assert not state.reload_draining
    job["status"] = "complete"
    assert not state.live_reload_status()["busy"]
    assert state.begin_reload()


def test_process_and_unfinished_future_block_reload_after_status_finishes(state):
    state.jobs["test"] = {"status": "complete"}
    state.processes["test"] = SimpleNamespace(is_alive=lambda: True)
    assert not state.begin_reload()
    state.processes["test"] = SimpleNamespace(is_alive=lambda: False)
    future = Future()
    state.futures["test"] = future
    assert state.live_reload_status()["busy"]
    assert not state.begin_reload()
    future.set_result(None)
    assert not state.live_reload_status()["busy"]
    assert state.begin_reload()


def test_disabled_watcher_status_is_explicit(state):
    assert state.live_reload_status() == {
        "enabled": False, "instance_id": "test-instance", "busy": False,
        "restart_pending": False,
    }


def test_backend_revision_requests_restart_but_web_revision_does_not(state):
    snapshot = {"enabled": True, "backend_revision": "backend-one", "web_revision": "web-one"}
    state.live_watcher = SimpleNamespace(snapshot=lambda: dict(snapshot))
    state.loaded_backend_revision = "backend-one"
    assert not state.live_reload_status()["restart_pending"]
    snapshot["web_revision"] = "web-two"
    assert not state.live_reload_status()["restart_pending"]
    snapshot["backend_revision"] = "backend-two"
    assert state.live_reload_status()["restart_pending"]
    assert state.begin_reload()
    snapshot["backend_revision"] = "backend-one"
    assert state.live_reload_status()["restart_pending"]


@contextmanager
def http_client(state):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        yield client
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request(client, method, path, body=None, headers=None):
    client.request(method, path, body=body, headers=headers or {})
    response = client.getresponse()
    return response.status, response.headers, response.read()


def test_live_reload_endpoint_and_html_share_snapshot_and_disable_cache(state, monkeypatch, tmp_path):
    source = tmp_path / "src" / "flybrain"
    static = source / "web"
    static.mkdir(parents=True)
    (source / "engine.py").write_text("value = 1\n")
    (static / "index.html").write_text("<!doctype html><html><head></head><body>test</body></html>")
    (static / "app.js").write_text("const value = 1;\n")
    monkeypatch.setattr(visual_server, "STATIC", static)
    state.live_watcher = ProjectWatcher(tmp_path, source, debounce_seconds=0)
    state.loaded_backend_revision = state.live_watcher.snapshot()["backend_revision"]
    with http_client(state) as client:
        status, headers, body = request(client, "GET", "/api/live-reload")
        assert status == 200
        snapshot = json.loads(body)
        assert snapshot == state.live_reload_status()
        assert "no-store" in headers["Cache-Control"]
        for path in ("/", "/index.html"):
            status, headers, body = request(client, "GET", path)
            assert status == 200
            assert "no-store" in headers["Cache-Control"]
            injected = body.decode().split("window.__COGNESIA_LIVE_RELOAD__=", 1)[1].split(";</script>", 1)[0]
            assert json.loads(injected) == snapshot
        status, headers, body = request(client, "GET", "/app.js")
        assert status == 200
        modified = headers["Last-Modified"]
        status, headers, body = request(client, "GET", "/app.js", headers={"If-Modified-Since": modified})
        assert status == 200
        assert body == b"const value = 1;\n"
        assert "no-store" in headers["Cache-Control"]
    assert state.active_requests == 0


def test_draining_server_keeps_health_and_reload_status_available(state):
    assert state.begin_reload()
    with http_client(state) as client:
        for path in ("/api/health", "/api/live-reload"):
            status, _, body = request(client, "GET", path)
            assert status == 200
            assert json.loads(body)
        for method, path, body in (("GET", "/api/sessions", None), ("GET", "/", None),
                                   ("POST", "/api/simulate", "{}")):
            status, _, body = request(client, method, path, body)
            assert status == 503
            assert "Applying project changes" in json.loads(body)["error"]
    assert state.active_requests == 0


def test_http_no_watch_serves_disabled_status_and_plain_html(state, monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<html><head></head><body>plain</body></html>")
    monkeypatch.setattr(visual_server, "STATIC", tmp_path)
    with http_client(state) as client:
        status, _, body = request(client, "GET", "/api/live-reload")
        assert status == 200
        assert json.loads(body)["enabled"] is False
        status, _, body = request(client, "GET", "/")
        assert status == 200
        assert "__COGNESIA_LIVE_RELOAD__" not in body.decode()


def test_clear_bytecode_preserves_source_and_non_python_cache(tmp_path):
    cached = tmp_path / "pkg" / "__pycache__"
    cached.mkdir(parents=True)
    regenerable = cached / "app.cpython-312.pyc"
    protected = [tmp_path / "pkg" / "app.py", cached / "engine.nbc", tmp_path / "evidence.pyc"]
    for path in [regenerable, *protected]:
        path.write_bytes(b"keep")
    live_server.clear_source_bytecode(tmp_path)
    assert not regenerable.exists()
    assert all(path.read_bytes() == b"keep" for path in protected)


def test_supervisor_restarts_child_and_opens_browser_only_once(tmp_path, monkeypatch):
    commands = []
    exit_codes = iter([live_server.RELOAD_EXIT, 0])
    snapshot = {"backend_revision": "current", "pending": False, "error": None}
    monkeypatch.setattr(live_server, "ProjectWatcher", lambda root: SimpleNamespace(snapshot=lambda: snapshot))
    monkeypatch.setattr(live_server, "clear_source_bytecode", lambda root: None)
    monkeypatch.setattr(live_server.signal, "signal", lambda sig, handler: signal.SIG_DFL)

    def launch(command, **kwargs):
        commands.append((command, kwargs))
        code = next(exit_codes)
        return SimpleNamespace(wait=lambda timeout=None: code, poll=lambda: code)

    monkeypatch.setattr(live_server.subprocess, "Popen", launch)
    assert live_server.supervise(tmp_path, port=9876, open_browser=True, memory_limit_gb=12) == 0
    assert len(commands) == 2
    first, options = commands[0]
    assert first[first.index("--root") + 1] == str(tmp_path)
    assert first[first.index("--port") + 1] == "9876"
    assert first[first.index("--mem-limit-gb") + 1] == "12"
    assert "--reload-child" in first
    assert "--open" in first
    assert "--open" not in commands[1][0]
    assert options["cwd"] == tmp_path


def test_supervisor_waits_for_valid_stable_source_after_failed_start(tmp_path, monkeypatch):
    baseline = {"backend_revision": "old", "pending": False, "error": None}
    revisions = iter([
        {"backend_revision": "new", "pending": True, "error": None},
        {"backend_revision": "new", "pending": False, "error": "bad syntax"},
        {"backend_revision": "old", "pending": False, "error": None},
        {"backend_revision": "new", "pending": False, "error": None},
    ])
    polls, launches = [], []

    def poll():
        result = next(revisions)
        polls.append(result)
        return result

    monkeypatch.setattr(live_server, "ProjectWatcher", lambda root: SimpleNamespace(poll=poll, snapshot=lambda: baseline))
    monkeypatch.setattr(live_server, "clear_source_bytecode", lambda root: None)
    monkeypatch.setattr(live_server.signal, "signal", lambda sig, handler: signal.SIG_DFL)
    monkeypatch.setattr(live_server.time, "sleep", lambda seconds: None)

    def launch(command, **kwargs):
        launches.append(len(polls))
        code = 1 if len(launches) == 1 else 0
        return SimpleNamespace(wait=lambda timeout=None: code, poll=lambda: code)

    monkeypatch.setattr(live_server.subprocess, "Popen", launch)
    assert live_server.supervise(tmp_path) == 0
    assert launches == [0, 4]


def test_supervisor_retries_fix_accepted_while_old_child_is_still_failing(tmp_path, monkeypatch):
    current = {"backend_revision": "broken-at-launch", "pending": False, "error": None}
    launches = []
    waits = []
    polls = []

    def poll():
        assert not polls, "Recovery must not require another edit after the fix was accepted"
        polls.append(True)
        current["backend_revision"] = "fixed-during-startup"
        return dict(current)

    def launch(command, **kwargs):
        launches.append(current["backend_revision"])
        if len(launches) == 2:
            return SimpleNamespace(wait=lambda timeout=None: 0, poll=lambda: 0)

        def wait(timeout=None):
            waits.append(True)
            if len(waits) == 1:
                raise live_server.subprocess.TimeoutExpired(command, timeout)
            return 1

        return SimpleNamespace(wait=wait, poll=lambda: 1)

    def unexpected_sleep(seconds):
        pytest.fail("A stable fix already accepted during startup must be retried immediately")

    watcher = SimpleNamespace(snapshot=lambda: dict(current), poll=poll)
    monkeypatch.setattr(live_server, "ProjectWatcher", lambda root: watcher)
    monkeypatch.setattr(live_server, "clear_source_bytecode", lambda root: None)
    monkeypatch.setattr(live_server.signal, "signal", lambda sig, handler: signal.SIG_DFL)
    monkeypatch.setattr(live_server.time, "sleep", unexpected_sleep)
    monkeypatch.setattr(live_server.subprocess, "Popen", launch)

    assert live_server.supervise(tmp_path) == 0
    assert launches == ["broken-at-launch", "fixed-during-startup"]
    assert len(polls) == 1
