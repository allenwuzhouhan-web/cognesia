"""Start the unified whole-brain viewer, idle, independently of the terminal."""
from pathlib import Path
import json
import subprocess
import time
import urllib.request
import webbrowser


def start(root, port=8794, *, open_browser=True):
    root = Path(root).resolve()
    url = f"http://127.0.0.1:{port}"

    def running():
        try:
            with urllib.request.urlopen(url + '/api/health', timeout=1) as response:
                health = json.load(response)
                if health.get('service') == 'flybrain-visual' and health.get('access_required') is not True:
                    raise RuntimeError('An older unprotected viewer is running; stop it and restart the current Cognesia release.')
                return health.get('service') == 'flybrain-visual'
        except (OSError, ValueError):
            return False

    if not running():
        (root / 'runs').mkdir(exist_ok=True)
        log = root / 'runs/flybrain-viewer.log'
        with log.open('ab', buffering=0) as stream:
            process = subprocess.Popen(
                [str(root / '.venv/bin/flybrain'), '--root', str(root),
                 'view', '--port', str(port)],
                cwd=root, stdin=subprocess.DEVNULL, stdout=stream,
                stderr=subprocess.STDOUT, start_new_session=True)
        (root / 'runs/flybrain-viewer.pid').write_text(str(process.pid) + '\n')
        for _ in range(160):
            if running():
                break
            if process.poll() is not None:
                raise RuntimeError(f'Viewer exited; inspect {log}')
            time.sleep(.25)
        else:
            raise RuntimeError(f'Viewer is still starting; inspect {log}')
    if open_browser:
        webbrowser.open(url)
    print(url, flush=True)
    return url


if __name__ == '__main__':
    start(Path(__file__).resolve().parents[1])
