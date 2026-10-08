"""Launch the local research workspace, reusing matching services and verified weights."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import urllib.request
import webbrowser

from start_flybrain import start as start_viewer

AGENT_SERVICE = 'cognesia-research-agent'
VIEWER_SERVICE = 'flybrain-visual'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def _read_health(url):
    """Use only the requested loopback service, never system proxies or redirects."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(url + '/api/health', timeout=1) as response:
            body = response.read(16385)
            if len(body) > 16384:
                return None
            result = json.loads(body)
            return result if isinstance(result, dict) else None
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _port_occupied(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(.25)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def _validate_health(health, service, url, viewer_url=None):
    if health.get('service') != service:
        raise RuntimeError(f'{url} belongs to another service; choose another port or stop that service yourself.')
    if health.get('access_required') is not True:
        raise RuntimeError(f'{url} is an older unprotected service; stop it and restart the current Cognesia release.')
    if viewer_url is not None and health.get('viewer_url') != viewer_url:
        raise RuntimeError(f'{url} uses another workbench ({health.get("viewer_url", "unspecified")}); '
                           'choose another agent port or the matching viewer port.')


def _running(url, port, service, viewer_url=None):
    health = _read_health(url)
    if health is not None:
        _validate_health(health, service, url, viewer_url)
        return True
    if _port_occupied(port):
        raise RuntimeError(f'Port {port} is occupied but does not identify itself as {service}. '
                           'Choose another port or stop the existing service yourself; no process was replaced.')
    return False


@contextmanager
def _private_file(path, mode='ab'):
    flags = os.O_CREAT | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0)
    flags |= os.O_APPEND if 'a' in mode else os.O_TRUNC
    descriptor = os.open(path, flags, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, mode, buffering=0) as stream:
        yield stream


@contextmanager
def _launch_lock(directory, timeout=45):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    # A project-wide lock also serializes two consoles that share a viewer port.
    with _private_file(directory / 'research-launch.lock') as lock:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Another research launcher is still starting; try again after it finishes.') from None
                time.sleep(.1)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _verified_model(model):
    """Reuse saved checksum evidence only while the verified file metadata matches."""
    try:
        manifest = model.with_suffix('.verified.json')
        if not model.is_file() or not manifest.is_file() or manifest.stat().st_size > 16384:
            return False
        evidence = json.loads(manifest.read_text())
        if not isinstance(evidence, dict):
            return False
        info = model.stat()
        if (evidence.get('verified') is not True
                or type(evidence.get('bytes')) is not int
                or type(evidence.get('mtime_ns')) is not int
                or evidence['bytes'] != info.st_size
                or evidence['mtime_ns'] != info.st_mtime_ns
                or not isinstance(evidence.get('sha256'), str)
                or not re.fullmatch(r'[0-9a-fA-F]{64}', evidence['sha256'])):
            return False
        with model.open('rb') as stream:
            return stream.read(4) == b'GGUF'
    except (OSError, ValueError, UnicodeDecodeError):
        return False


def _model_executable():
    executable = shutil.which('llama-server')
    if executable:
        return executable
    for candidate in ('/opt/homebrew/bin/llama-server', '/usr/local/bin/llama-server'):
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _port(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1024 <= value <= 65535:
        raise ValueError('Service ports must be integers from 1024 to 65535')
    return value


def start(root, *, viewer_port=8794, agent_port=8797, open_browser=True, start_model=True):
    root = Path(root).resolve()
    viewer_port, agent_port = _port(viewer_port), _port(agent_port)
    if viewer_port == agent_port:
        raise ValueError('Viewer and research agent must use different ports')
    viewer_url = f'http://127.0.0.1:{viewer_port}'
    url = f'http://127.0.0.1:{agent_port}'
    runtime = root / 'build/runtime'
    with _launch_lock(runtime):
        agent_running = _running(url, agent_port, AGENT_SERVICE, viewer_url)
        viewer_running = _running(viewer_url, viewer_port, VIEWER_SERVICE)
        if not viewer_running:
            runs = root / 'runs'
            runs.mkdir(exist_ok=True)
            # start_flybrain opens these existing files without replacing their mode.
            for name in ('flybrain-viewer.log', 'flybrain-viewer.pid'):
                with _private_file(runs / name):
                    pass
            start_viewer(root, port=viewer_port, open_browser=False)
            if not _running(viewer_url, viewer_port, VIEWER_SERVICE):
                raise RuntimeError('The viewer launcher returned before its health endpoint became available.')
        if not agent_running:
            model = root / 'data/models/gpt-oss-20b/gpt-oss-20b-MXFP4.gguf'
            executable = _model_executable()
            command = [str(root / '.venv/bin/python'), '-m', 'flybrain.local_agent',
                       '--port', str(agent_port), '--viewer-url', viewer_url,
                       '--history-dir', str(root / 'sessions/research'),
                       '--model-file', str(model)]
            if executable:
                command += ['--llama-server', executable]
            if start_model and executable and _verified_model(model):
                if _port_occupied(8080):
                    raise RuntimeError('Model port 8080 is already occupied. Reuse the existing research console '
                                       'or launch with --no-start-model; no second model was started.')
                command.append('--start-model')
            suffix = '' if agent_port == 8797 else f'-{agent_port}'
            log_path = runtime / f'research-agent{suffix}.log'
            with _private_file(log_path) as log:
                process = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            with _private_file(runtime / f'research-agent{suffix}.pid', 'wb') as pid:
                pid.write((str(process.pid) + '\n').encode('ascii'))
            for _ in range(100):
                health = _read_health(url)
                if health is not None:
                    _validate_health(health, AGENT_SERVICE, url, viewer_url)
                    break
                if process.poll() is not None:
                    raise RuntimeError(f'Research agent exited; inspect {log_path}')
                time.sleep(.2)
            else:
                raise RuntimeError(f'Research agent did not become ready within 20 seconds; inspect {log_path}')
    if open_browser:
        webbrowser.open(url)
    print(url, flush=True)
    return url


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true', help='Start services without opening a browser')
    parser.add_argument('--viewer-port', type=int, default=8794)
    parser.add_argument('--agent-port', type=int, default=8797)
    parser.add_argument('--no-start-model', action='store_true', help='Prefill model paths without starting inference')
    args = parser.parse_args(argv)
    try:
        return start(Path(__file__).resolve().parents[1], viewer_port=args.viewer_port,
                     agent_port=args.agent_port, open_browser=not args.no_browser,
                     start_model=not args.no_start_model)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f'Cognesia research launcher: {exc}\n')


if __name__ == '__main__':
    main()
