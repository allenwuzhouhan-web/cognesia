#!/usr/bin/env python3
"""Inspect a frozen campaign; --apply permits bounded recovery and verification.

This is a one-shot maintenance command, not another simulation worker. Receipts
live under the original shared accounting root, including across successors.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
import fcntl
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from flybrain.transmission_campaign import controller
from flybrain.transmission_campaign.budget import CampaignBudget, canonical, digest, file_sha

MAX_RECOVERIES = 3
MAX_VERIFICATIONS = 8
MAX_JOB_ATTEMPTS = 4  # Original attempt plus the controller's three I/O retries.
LAUNCH_GRACE_SECONDS = 120
COMMAND_TIMEOUT_SECONDS = 60
MAX_RECEIPT_BYTES = 32_768
POLICY_PATH = 'maintenance/recovery.json'
LATEST_PATH = 'maintenance/latest.json'
LOCK_PATH = 'maintenance/.maintenance.lock'
HEAVY_LOCKS = ('optical-mapping.lock', 'neural-baseline.lock', 'cgnsa-heavy-compute.lock')
TERMINAL_ARTIFACTS = (
    'manifest.json', 'configuration.json', 'benchmark.json', 'scientific-plan-seal.json',
    'schedule.json', 'selected-candidates.json', 'input-selection.json',
    'predictions/prediction-seal.json', 'predictions-t4d/prediction-seal.json',
    'scores.json', 'scores-t4d.json', 'comparison.json', 'report.json',
    'experimental-model.json', 'failure.json',
)


def read_json(path):
    path = Path(path)
    if path.resolve() != path or path.stat().st_nlink != 1:
        raise ValueError('Ordinary campaign artifact required: ' + str(path))
    return json.loads(path.read_text())


def ledger_rows(output):
    """Do not invoke JobLedger/status: opening them can write to the ledger."""
    path = Path(output) / 'jobs.sqlite3'
    if path.resolve() != path or path.stat().st_nlink != 1:
        raise ValueError('Ordinary job ledger required')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute('SELECT * FROM jobs ORDER BY id')]


def inspect_processes(output, state, manifest):
    """Attest exact argv, uid, executable and creation time; scan launch races."""
    import psutil

    output = Path(output)
    script = str(output / 'frozen/workspace/scripts/run_transmission_campaign.py')
    expected_tail = [*manifest.get('frozen_dependencies', {}).get('python_flags', []),
                     script, '_worker', '--output', str(output)]
    expected_exe = Path(sys.executable).resolve()
    workers, unknown = [], []
    recorded_pid = state.get('pid')
    recorded_seen = False
    for process in psutil.process_iter(['pid', 'cmdline', 'uids', 'exe', 'create_time', 'status'], ad_value=None):
        info = process.info
        pid = info['pid']
        if pid == recorded_pid:
            recorded_seen = True
        uids, args = info.get('uids'), info.get('cmdline')
        if (uids is not None and
                (uids.real != os.getuid() or uids.effective != os.geteuid()) and
                pid != recorded_pid):
            continue
        if info.get('status') == psutil.STATUS_ZOMBIE:
            continue
        # An inaccessible process owned by this user may be a launching worker.
        if args is None:
            if pid == recorded_pid or (uids is not None and uids.real == os.getuid() and
                                       uids.effective == os.geteuid()):
                unknown.append({'pid': pid, 'reason': 'Process command unavailable'})
            continue
        candidate = pid == recorded_pid or (script in args and '_worker' in args)
        if not candidate:
            continue
        created = info.get('create_time')
        matches = (args[1:] == expected_tail and uids is not None and
                   uids.real == os.getuid() and uids.effective == os.geteuid() and
                   info.get('exe') is not None and
                   Path(info['exe']).resolve() == expected_exe and
                   isinstance(created, (int, float)) and
                   created >= state['started_at'] - 2)
        if matches:
            workers.append({'pid': pid, 'created_at': created, 'uid': uids.real, 'effective_uid': uids.effective,
                            'executable': str(expected_exe), 'script': script})
        else:
            unknown.append({'pid': pid, 'reason': 'PID or worker command identity mismatch'})
    return {'workers': workers, 'unknown': unknown, 'recorded_pid_seen': recorded_seen}


@contextmanager
def try_lock(path, *, create=False):
    path = Path(path)
    if path.resolve() != path or (path.exists() and path.stat().st_nlink != 1):
        raise ValueError('Ordinary lock path required: ' + str(path))
    if not path.exists() and not create:
        yield True
        return
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b' if create else 'rb') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            try:
                yield True
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def lock_evidence(output, root):
    paths = [Path(output) / '.supervisor.lock']
    paths += [Path(root) / 'build/runtime' / name for name in HEAVY_LOCKS]
    result = {}
    with ExitStack() as stack:
        for path in paths:
            result[str(path)] = 'free' if stack.enter_context(try_lock(path)) else 'held'
    return result


def inspect(output, now):
    output = Path(output).absolute()
    if not output.is_dir() or output.resolve() != output:
        raise ValueError('Existing ordinary campaign directory required')
    manifest = read_json(output / 'manifest.json')
    config = read_json(output / 'configuration.json')
    state = read_json(output / 'state.json')
    control = read_json(output / 'control.json')
    if (manifest.get('output') != str(output) or
            digest(manifest['files']) != manifest['source_identity'] or
            digest(config) != manifest['configuration_sha256'] or
            digest(read_json(output / 'benchmark.json')) != manifest['benchmark_sha256'] or
            state.get('source_identity') != manifest['source_identity']):
        raise ValueError('Campaign identities do not match')
    if (config.get('max_elapsed_seconds') != controller.MAX_ELAPSED_SECONDS or
            config.get('population') != 175401 or
            not 1 <= config.get('threads', 0) <= 16 or
            not 0 < config.get('memory_gb', 0) <= 24 or
            not 0 < config.get('storage_bytes', 0) <= 20_000_000_000):
        raise ValueError('Frozen operating limits are outside the authorized contract')
    started = state.get('started_at')
    if not isinstance(started, (int, float)) or not math.isfinite(started) or started <= 0:
        raise ValueError('Maintenance requires an already launched campaign')
    predecessor = manifest.get('predecessor')
    if predecessor and predecessor.get('original_started_at') != started:
        raise ValueError('Successor reset the original elapsed clock')
    if control.get('command') not in {'resume', 'pause', 'stop'}:
        raise ValueError('Unknown operator control')
    budget = CampaignBudget(output)
    rows = ledger_rows(output)
    if any(r['state'] not in {'pending', 'running', 'complete', 'failed'} or
           type(r['attempts']) is not int or r['attempts'] < 0 for r in rows):
        raise ValueError('Unknown ledger state')
    processes = inspect_processes(output, state, manifest)
    locks = lock_evidence(output, manifest['source_root'])
    schedule_path = output / 'schedule.json'
    schedule = read_json(schedule_path) if schedule_path.exists() else None
    return {'output': output, 'manifest': manifest, 'state': state, 'control': control,
            'config': config, 'budget': budget, 'rows': rows, 'processes': processes,
            'locks': locks, 'schedule': schedule, 'deadline': started + config['max_elapsed_seconds'],
            'storage': budget.snapshot(), 'now': now}


def maintenance_state(budget, started):
    path = budget.path(POLICY_PATH)
    if path.exists():
        saved = read_json(path)
        if (saved.get('schema') != 'transmission-maintenance-v1' or
                saved.get('max_recoveries') != MAX_RECOVERIES or
                saved.get('max_verifications') != MAX_VERIFICATIONS or
                saved.get('original_started_at') != started or
                len(saved.get('recoveries', [])) > MAX_RECOVERIES or
                len(saved.get('verifications', [])) > MAX_VERIFICATIONS):
            raise ValueError('Maintenance policy changed or exceeded its finite limits')
        return saved
    return {'schema': 'transmission-maintenance-v1', 'original_started_at': started,
            'max_recoveries': MAX_RECOVERIES, 'max_verifications': MAX_VERIFICATIONS,
            'recoveries': [], 'verifications': []}


def write_receipt(budget, relative, value, *, recovery=False):
    if len(canonical(value)) + 1 > MAX_RECEIPT_BYTES:
        raise ValueError('Bounded maintenance receipt exceeded')
    return budget.write_json(relative, value, recovery=recovery)


def terminal_identity(context):
    output = context['output']
    files = {name: file_sha(output / name) for name in TERMINAL_ARTIFACTS if (output / name).is_file()}
    return digest({'files': files, 'status': context['state']['status'],
                   'started_at': context['state']['started_at'], 'ledger': context['rows']})


def frozen_command(output, command, manifest):
    """Only the sealed controller starts workers or performs scientific scoring."""
    if command not in {'recover', 'verify'}:
        raise ValueError('Only frozen worker recovery and terminal verification are supported')
    # Check the files executed before importing a frozen controller. Its own
    # start/verify then validate the full source/dependency/input manifest.
    for relative in ('scripts/run_transmission_campaign.py',
                     'src/flybrain/transmission_campaign/controller.py'):
        row = manifest['files'][relative]
        path = output / row['path']
        if path.resolve() != path or file_sha(path) != row['sha256']:
            raise ValueError('Frozen lifecycle executable changed')
    if file_sha(sys.executable) != manifest['dependencies']['executable_sha256']:
        raise ValueError('Python executable changed')
    dependencies = manifest.get('frozen_dependencies', {})
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join(
        [str(output / 'frozen/workspace/src')] + [str(output / p) for p in dependencies.get('pythonpath', [])]),
        PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1',
        MKL_NUM_THREADS='1', NUMBA_CACHE_DIR=str(output / 'cache/numba'))
    argv = [sys.executable, *dependencies.get('python_flags', []),
            str(output / 'frozen/workspace/scripts/run_transmission_campaign.py'),
            '_worker' if command == 'recover' else 'verify', '--output', str(output)]
    if command == 'recover':
        # start/resume overwrite control.json. An interrupted campaign already
        # has resume there, so use their exact frozen worker entrypoint without
        # rewriting controls. A concurrent human pause/stop remains effective.
        with open(os.devnull, 'wb') as null:
            process = subprocess.Popen(argv, cwd=output, env=environment, stdin=subprocess.DEVNULL,
                stdout=null, stderr=null, start_new_session=True)
            if Path('/usr/bin/caffeinate').exists():
                subprocess.Popen(['/usr/bin/caffeinate', '-s', '-w', str(process.pid)],
                    stdin=subprocess.DEVNULL, stdout=null, stderr=null, start_new_session=True)
        return {'status': 'RETURNED', 'controller_status': 'LAUNCHING', 'pid': process.pid}
    result = subprocess.run(argv, cwd=output, env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=COMMAND_TIMEOUT_SECONDS, check=False)
    if result.returncode:
        return {'status': 'COMMAND_FAILED', 'returncode': result.returncode,
                'error': result.stderr.decode(errors='replace')[-2048:]}
    payload = json.loads(result.stdout)
    return {'status': 'RETURNED', 'result_identity': digest(payload),
            **{k: payload[k] for k in ('pid', 'scientific_status', 'frozen_files_valid', 'storage_valid') if k in payload},
            'controller_status': payload.get('status'),
            'independent_metrics_pass': (payload.get('independent_metrics') or {}).get('pass')}


def _maintain(output, apply, now):
    c = inspect(output, now)
    budget = CampaignBudget(c['budget'].accounting_root)
    policy = maintenance_state(budget, c['state']['started_at'])
    result = {'schema': 'transmission-maintenance-result-v1', 'applied': apply, 'checked_at': now,
              'output': str(c['output']), 'source_identity': c['manifest']['source_identity'],
              'campaign_status': c['state']['status'], 'phase': c['state'].get('phase'),
              'original_started_at': c['state']['started_at'], 'deadline': c['deadline'],
              'remaining_seconds': max(0., c['deadline'] - now), 'processes': c['processes'],
              'locks': c['locks'], 'storage': c['storage'],
              'jobs': {name: sum(r['state'] == name for r in c['rows'])
                       for name in ('pending', 'running', 'complete', 'failed')},
              'proposals_per_arm': (c['schedule'] or {}).get('proposals_per_arm'),
              'recoveries_used': len(policy['recoveries']), 'max_recoveries': MAX_RECOVERIES}

    def finish(action, reason, *, emergency=False):
        result.update(action=action, reason=reason)
        if apply:
            try:
                receipt = write_receipt(budget, LATEST_PATH, result, recovery=emergency)
                result['receipt'] = receipt
            except Exception as exc:
                result['receipt_error'] = str(exc)[:1024]
        return result

    if c['processes']['unknown'] or len(c['processes']['workers']) > 1:
        return finish('BLOCKED_PROCESS_IDENTITY', 'Unknown or multiple worker identities; no lifecycle action')
    workers = c['processes']['workers']
    terminal = c['state']['status'] in controller.TERMINAL
    if workers:
        if c['control']['command'] in {'pause', 'stop'} or c['state']['status'] == 'PAUSED':
            return finish('OPERATOR_HOLD', 'Attested worker is processing the existing pause/stop request')
        return finish('DEADLINE_WAITING_FOR_WORKER' if now >= c['deadline'] else 'HEALTHY',
                      'Attested worker retained; frozen controller owns admission and shutdown')
    if c['locks'][str(c['output'] / '.supervisor.lock')] != 'free':
        return finish('BLOCKED_WORKER_LOCK', 'Worker lock held without an attested process')
    if terminal:
        identity = terminal_identity(c)
        result['terminal_identity'] = identity
        prior = next((r for r in policy['verifications'] if r['identity'] == identity), None)
        if prior:
            result['verification'] = prior
            return finish('TERMINAL_ALREADY_CHECKED', 'Verification was already attempted for this artifact identity', emergency=True)
        if len(policy['verifications']) >= MAX_VERIFICATIONS:
            return finish('VERIFICATION_LIMIT', 'Finite terminal verification identities exhausted', emergency=True)
        if not apply:
            return finish('WOULD_VERIFY', 'Terminal artifact identity has no maintenance verification receipt')
        record = {'identity': identity, 'output': str(c['output']), 'at': now, 'status': 'INTENT'}
        policy['verifications'].append(record)
        # Reserve room for the existing verifier and atomic maintenance receipts.
        c['budget'].check(4 * MAX_RECEIPT_BYTES, recovery=True)
        write_receipt(budget, POLICY_PATH, policy, recovery=True)
        try:
            record.update(frozen_command(c['output'], 'verify', c['manifest']))
        except Exception as exc:
            record.update(status='COMMAND_FAILED', error=str(exc)[:2048])
        write_receipt(budget, POLICY_PATH, policy, recovery=True)
        result['verification'] = record
        return finish('TERMINAL_VERIFIED' if record.get('status') == 'RETURNED' and
                      record.get('scientific_status') != 'FAILED' else 'TERMINAL_VERIFICATION_FAILED',
                      'Frozen verification attempted once; failure never triggers scientific tuning', emergency=True)
    if c['control']['command'] in {'pause', 'stop'} or c['state']['status'] == 'PAUSED':
        return finish('OPERATOR_HOLD', 'Explicit pause/stop takes precedence over recovery')
    if now >= c['deadline']:
        return finish('DEADLINE_NO_RECOVERY', 'Original deadline expired; retained artifacts are available for review', emergency=True)
    if c['state']['status'] not in {'RUNNING', 'WAITING_FOR_COMPUTE'}:
        return finish('UNSUPPORTED_STATE', 'Only interrupted previously running campaigns can recover')
    if any(r['state'] in {'running', 'pending'} and r['attempts'] >= MAX_JOB_ATTEMPTS for r in c['rows']):
        return finish('JOB_RETRY_LIMIT', 'Recovery would exceed the controller maximum of four job claims')
    if len(policy['recoveries']) >= MAX_RECOVERIES:
        return finish('RECOVERY_LIMIT', 'Three process recovery attempts already reserved')
    if policy['recoveries'] and now - policy['recoveries'][-1]['at'] < LAUNCH_GRACE_SECONDS:
        return finish('LAUNCH_GRACE', 'Retain previous launch intent during its bounded startup grace')
    if any(value != 'free' for value in c['locks'].values()):
        return finish('WAITING_FOR_COMPUTE', 'Existing heavy-compute admission is occupied')
    activity, reasons = controller.activity_check(Path(c['manifest']['source_root']))
    result['activity'] = {k: activity[k] for k in ('known', 'idle', 'source') if k in activity}
    if reasons:
        return finish('WAITING_FOR_COMPUTE', 'Authenticated activity check rejected admission: ' + ', '.join(reasons))
    # The frozen controller rechecks these live ceilings throughout execution.
    live = controller.live_policy(Path(c['manifest']['source_root']))
    result['compute_limits'] = {'threads': min(c['config']['threads'], live['threads']),
        'memory_gb': min(c['config']['memory_gb'], live['memory_gb']),
        'agent_reserve_gb': live['agent_reserve_gb']}
    c['budget'].check(8_000_000 + 4 * MAX_RECEIPT_BYTES)
    if not apply:
        return finish('WOULD_RECOVER', 'Confirmed interruption; existing frozen worker recovery is eligible')
    # Refresh user controls and process/lock evidence immediately before launch.
    fresh = inspect(c['output'], time.time())
    if (fresh['state'] != c['state'] or fresh['control'] != c['control'] or
            fresh['processes']['workers'] or fresh['processes']['unknown'] or
            any(value != 'free' for value in fresh['locks'].values()) or
            fresh['now'] >= c['deadline']):
        return finish('CHANGED_DURING_INSPECTION', 'State, operator controls, processes or admission changed; retry inspection later')
    record = {'output': str(c['output']), 'source_identity': c['manifest']['source_identity'],
              'at': now, 'status': 'INTENT', 'reason': 'Attested absent worker and free controller/admission locks',
              'ledger_identity': digest(c['rows']), 'maximum_unfinished_attempts': max(
                  [r['attempts'] for r in c['rows'] if r['state'] in {'running', 'pending'}] or [0])}
    policy['recoveries'].append(record)
    write_receipt(budget, POLICY_PATH, policy)
    # The intent itself can take time to commit. Never treat it as permission to
    # ignore a newer human control request. The actual recovery launcher never
    # writes control.json, so requests during subprocess launch also survive.
    last_control = read_json(c['output'] / 'control.json')
    last_processes = inspect_processes(c['output'], c['state'], c['manifest'])
    if (last_control != c['control'] or last_processes['workers'] or last_processes['unknown'] or
            time.time() >= c['deadline']):
        record.update(status='CANCELLED', reason='Operator control, process identity or deadline changed after intent')
        write_receipt(budget, POLICY_PATH, policy, recovery=True)
        result.update(recoveries_used=len(policy['recoveries']), recovery=record)
        return finish('CHANGED_DURING_INSPECTION', record['reason'])
    try:
        record.update(frozen_command(c['output'], 'recover', c['manifest']))
    except Exception as exc:
        record.update(status='COMMAND_FAILED', error=str(exc)[:2048])
    write_receipt(budget, POLICY_PATH, policy, recovery=True)
    result.update(recoveries_used=len(policy['recoveries']), recovery=record)
    return finish('RECOVERY_REQUESTED' if record['status'] == 'RETURNED' else 'RECOVERY_COMMAND_FAILED',
                  'Used one durable process recovery attempt; completed and failed jobs stay in their ledger', emergency=True)


def maintain(output=None, *, apply=False, now=None):
    """Return JSON-compatible evidence; all unexpected ambiguity fails closed."""
    try:
        output = Path(output or controller.active_output()).absolute()
        if not output.is_dir():
            raise ValueError('Campaign is not prepared')
        now = time.time() if now is None else now
        if not apply:
            return _maintain(output, False, now)
        budget = CampaignBudget(output)
        shared = CampaignBudget(budget.accounting_root)
        shared.check(0, recovery=True)
        with try_lock(shared.path(LOCK_PATH), create=True) as acquired:
            if not acquired:
                return {'action': 'MAINTENANCE_BUSY', 'applied': False, 'output': str(output)}
            return _maintain(output, True, now)
    except Exception as exc:
        return {'action': 'BLOCKED', 'applied': apply, 'output': str(output),
                'error': str(exc)[:2048], 'error_type': type(exc).__name__}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Defaults to the current active frozen attempt')
    parser.add_argument('--apply', action='store_true', help='Permit bounded recovery and terminal verification')
    args = parser.parse_args()
    print(json.dumps(maintain(args.output, apply=args.apply), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
