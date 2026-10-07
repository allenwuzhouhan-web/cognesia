"""Replay controls against the exact saved implementation/configuration identity."""
import json
import math
from pathlib import Path
import yaml


def replay_session(events_path, root, *, runtime=None):
    from .engine_rt import CoreRuntime
    path = Path(events_path)
    manifest = yaml.safe_load(path.with_name('session.yaml').read_text())
    if not isinstance(manifest,dict) or manifest.get('schema_version') != 1:
        raise ValueError('Replay requires a version-1 session manifest')
    digests=manifest.get('digests')
    if not isinstance(digests,dict) or set(digests)!={'spike_indices','spike_steps','weights'}:
        raise ValueError('Replay requires all three exact output digests')
    if any(not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v) for v in digests.values()):
        raise ValueError('Replay digests must be SHA-256 hex values')
    duration=manifest.get('duration_ms')
    seed=manifest.get('seed')
    if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<0 or duration!=round(duration):
        raise ValueError('Replay duration must be a nonnegative integer number of ms')
    if isinstance(seed,bool) or not isinstance(seed,int) or seed<0:
        raise ValueError('Replay seed must be a nonnegative integer')
    if not isinstance(manifest.get('config_hash'),str) or len(manifest['config_hash'])!=64:
        raise ValueError('Replay requires an implementation/configuration fingerprint')
    own = runtime is None
    runtime = CoreRuntime(root,seed=manifest['seed']) if own else runtime
    try:
        if runtime.config_hash != manifest['config_hash']:
            raise ValueError('Replay implementation/configuration differs from the recorded session')
        runtime.reset(manifest['seed'])
        position = 0
        for line in path.read_text().splitlines():
            if not line.strip(): continue
            event = json.loads(line)
            t = event['t_sim_ms']
            if isinstance(t,bool) or not isinstance(t,(int,float)) or t!=round(t) or t<position or t>manifest['duration_ms']:
                raise ValueError('Replay event time is out of order, off-grid or outside session')
            runtime.advance(int(t-position))
            runtime.control(event['control_id'],event['value'])
            position = t
        runtime.advance(int(manifest['duration_ms']-position))
        got = runtime.digests()
        checks = {k:got[k]==value for k,value in manifest['digests'].items()}
        return {'status':'PASS' if all(checks.values()) else 'FAIL','duration_ms':manifest['duration_ms'],
            'checks':checks,'recorded':manifest['digests'],'replayed':got,'config_hash':runtime.config_hash}
    finally:
        if own: runtime.close()
