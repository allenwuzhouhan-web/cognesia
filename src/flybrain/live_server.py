"""Keep the local viewer available across edits, including failed imports."""
from pathlib import Path
import os
import signal
import subprocess
import sys
import time

from .live_reload import ProjectWatcher

RELOAD_EXIT = 75


def clear_source_bytecode(source_root):
    # Timestamp-based pyc files can otherwise hide same-size edits within one
    # second. Only discard regenerable Python bytecode, never Numba/model data.
    for path in Path(source_root).rglob('*.pyc'):
        if path.parent.name == '__pycache__':
            path.unlink(missing_ok=True)


def supervise(root, port=8794, open_browser=False, memory_limit_gb=40):
    root = Path(root).resolve()
    watcher = ProjectWatcher(root)
    child = None
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGINT)

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        while not stopping:
            clear_source_bytecode(Path(__file__).parent)
            attempted_revision = watcher.snapshot()['backend_revision']
            command = [sys.executable, '-m', 'flybrain.cli', '--root', str(root),
                       '--mem-limit-gb', str(memory_limit_gb), 'view', '--port', str(port), '--reload-child']
            if open_browser:
                command.append('--open')
            environment = {**os.environ, 'PYTHONUNBUFFERED': '1'}
            child = subprocess.Popen(command, cwd=root, env=environment)
            while True:
                try:
                    result = child.wait(timeout=.5)
                    break
                except subprocess.TimeoutExpired:
                    watcher.poll()
            if stopping or result == 0:
                return 0
            if result == RELOAD_EXIT:
                open_browser = False
                continue
            # Keep the launcher PID alive so the native app does not spawn a
            # competing server. Fixing the source automatically retries startup.
            print(f'Viewer exited ({result}); waiting for a source/configuration fix.', flush=True)
            status = watcher.snapshot()
            if (not status['pending'] and not status['error']
                    and status['backend_revision'] != attempted_revision):
                continue
            while not stopping:
                time.sleep(.5)
                status = watcher.poll()
                if (not status['pending'] and not status['error']
                        and status['backend_revision'] != attempted_revision):
                    break
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGINT)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=5)
    return 0
