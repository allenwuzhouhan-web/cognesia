"""Start a persistent local console, wait for its HTTP listener, then open it."""
from pathlib import Path
import json
import subprocess
import time
import urllib.error
import urllib.request
import webbrowser


def start(root, port=8795, *, open_browser=True):
    root=Path(root).resolve();url=f'http://127.0.0.1:{port}'
    def running():
        try:
            with urllib.request.urlopen(url+'/api/status',timeout=1) as response:
                status=json.load(response)
                return 't_sim_ms' in status and 'status' in status
        except (OSError,ValueError): return False
    if not running():
        (root/'runs').mkdir(exist_ok=True)
        log=root/'runs/neuromod-console.log'
        with log.open('ab',buffering=0) as stream:
            process=subprocess.Popen([str(root/'.venv/bin/flybrain'),'--root',str(root),'rt','serve','--core','--port',str(port)],
                cwd=root,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        (root/'runs/neuromod-console.pid').write_text(str(process.pid)+'\n')
        for _ in range(120):
            if running(): break
            if process.poll() is not None:
                raise RuntimeError(f'Console exited; inspect {log}')
            time.sleep(.25)
        else: raise RuntimeError(f'Console listener did not become ready; inspect {log}')
    if open_browser: webbrowser.open(url)
    print(url,flush=True)
    return url


if __name__=='__main__':
    start(Path(__file__).resolve().parents[1])
