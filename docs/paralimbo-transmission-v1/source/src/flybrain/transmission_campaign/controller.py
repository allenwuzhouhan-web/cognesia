"""Detached, resumable campaign lifecycle and resource enforcement."""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import errno
import fcntl
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from . import SCHEMA
from .budget import CampaignBudget, CampaignStorageExhausted, canonical, digest, file_sha
from .ledger import JobLedger

DEFAULT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = DEFAULT_ROOT / 'build/biological-benchmark/paralimbo-transmission-v1'
MAX_ELAPSED_SECONDS = 7 * 24 * 3600
TERMINAL = {'COMPLETE', 'STOPPED', 'DEADLINE', 'RESOURCE_LIMIT', 'FAILED'}
MODELS = {'banc': ('banc-888', '60d220182e6f65b98a78b008c764bb13b802d1dc5b85a798cc9028a6557665de'),
          'paralimbo': ('paralimbo-visual-graded-v1', '229f9970e0b67cfa14658142dbc3adae8614d49887cd131521bf02e4d86cd884')}


class CampaignHalt(RuntimeError):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason
        super().__init__(reason)


def read_json(path):
    return json.loads(Path(path).read_text())


def deadline_exceeded(now, started, max_elapsed=MAX_ELAPSED_SECONDS):
    return now >= started + max_elapsed


def dependency_identity():
    return {'python': sys.version, 'executable_sha256': file_sha(sys.executable),
            'packages': {name: importlib.metadata.version(name) for name in
                         ('numpy', 'scipy', 'numba', 'pandas', 'pyarrow', 'psutil', 'PyYAML')}}


def select_schedule(pilot, remaining_seconds, *, development_cases=5, evaluation_cases=4, folds=1,
                    storage_available_bytes=None):
    """Conservative entire-workload forecast frozen before response access.

    Rates include preparation and instrumented active/quiet execution. Refinement
    doubles the integration steps and a factor of two covers scientific failures,
    I/O, source checks, verification, silencing/rescue and performance variation.
    """
    rate = max(pilot['quiet_seconds_per_simulated_second'], pilot['active_seconds_per_simulated_second'])
    if not 0 < rate < float('inf') or remaining_seconds <= 0:
        return {'status': 'RESOURCE_LIMIT', 'reason': 'No usable instrumented pilot or elapsed budget'}
    maximum_case_seconds = max(1., pilot.get('maximum_case_seconds', 1.))
    rows = []
    for proposals in (32, 16, 8):
        counts = dict(diagnostic=2 * 64 * 4, causal_controls=2 * 64 * 2,
                      sensitivity=2 * (15 * development_cases + 13), input_calibration=folds * 2 * 3 * development_cases,
                      calibration=folds * 2 * proposals * development_cases,
                      evaluation=folds * 2 * evaluation_cases,
                      correspondence_sensitivity=folds * 2 * (development_cases + evaluation_cases),
                      refinement=folds * 2 * 4 * (development_cases + evaluation_cases),
                      independent_verification=folds * 2 * evaluation_cases)
        integration = (counts['diagnostic'] + counts['causal_controls'] + maximum_case_seconds * counts['sensitivity'] +
                       maximum_case_seconds * (sum(v for k, v in counts.items() if k not in
                          ('diagnostic', 'causal_controls', 'sensitivity', 'refinement')) + 2 * counts['refinement']))
        forecast = 2 * rate * integration + pilot.get('startup_seconds', 0) * sum(counts.values())
        pre_evaluation = forecast * (counts['diagnostic'] + counts['causal_controls'] + counts['sensitivity'] +
                         counts['input_calibration'] + counts['calibration']) / sum(counts.values())
        direct_jobs = counts['diagnostic'] + counts['causal_controls'] + 26
        other_jobs = sum(counts.values()) - direct_jobs
        retained = int(1.25 * (direct_jobs * pilot.get('direct_retained_bytes', 0) +
                              other_jobs * pilot.get('t4_retained_bytes_bound', 0)))
        classification_bytes = 2 * 64 * 3 * (175401 * 3 + 1024)
        required_bytes = retained + classification_bytes + 2 * pilot.get('checkpoint_peak_bytes', 0) + 32_000_000
        rows.append({'proposals_per_arm': proposals, 'counts': counts, 'forecast_seconds': forecast,
                     'pre_evaluation_seconds': pre_evaluation, 'required_additional_bytes': required_bytes})
        if (forecast <= remaining_seconds and pre_evaluation <= .75 * remaining_seconds and
                (storage_available_bytes is None or required_bytes <= storage_available_bytes)):
            return {'status': 'FROZEN', **rows[-1], 'alternatives_checked': rows,
                    'remaining_seconds_at_freeze': remaining_seconds, 'evaluation_reserve_fraction': .25,
                    'forecast_multiplier': 2., 'pilot_identity': digest(pilot)}
    return {'status': 'RESOURCE_LIMIT', 'reason': 'Even eight proposals per arm do not fit', 'alternatives_checked': rows}


def _source_files(root):
    paths = list((root / 'src').rglob('*.py')) + list((root / 'scripts').glob('*.py'))
    paths += list((root / 'config').glob('*'))
    paths += [root / 'pyproject.toml']
    return sorted(p for p in paths if p.is_file() and '__pycache__' not in p.parts)


def prepare(root=DEFAULT_ROOT, output=DEFAULT_OUTPUT, *, predecessor=None):
    root, output = Path(root).absolute(), Path(output).absolute()
    predecessor_record = None
    if predecessor is not None:
        previous = Path(predecessor).absolute()
        prior = status(previous)
        if prior['status'] not in TERMINAL or prior.get('worker_alive'):
            raise ValueError('A substantive successor requires a terminal predecessor')
        previous_budget = CampaignBudget(previous)
        accounting_root = previous_budget.accounting_root
        if not output.is_relative_to(accounting_root / 'successors'):
            raise ValueError('Successors must remain inside the original campaign budget tree')
        from .integrity import write_once_json
        write_once_json(CampaignBudget(accounting_root), '.campaign-budget-anchor.json',
                        {'schema': 'transmission-shared-campaign-budget-v1',
                         'limit_bytes': previous_budget.limit_bytes})
        predecessor_record = {'path': str(previous), 'manifest_sha256': file_sha(previous / 'manifest.json'),
                              'status': prior['status'], 'original_started_at': prior.get('started_at'),
                              'reason': 'Separately frozen implementation correction; no search or elapsed/storage budget expansion'}
    budget = CampaignBudget(output)
    if (output / 'manifest.json').exists():
        validate_frozen(output)
        return status(output)
    from .data import resolve_benchmark
    benchmark = resolve_benchmark(root)
    policy = live_policy(root)
    config = {'schema': SCHEMA, 'max_elapsed_seconds': MAX_ELAPSED_SECONDS, 'threads': min(16, policy['threads']),
              'memory_gb': min(24., policy['memory_gb']), 'storage_bytes': budget.limit_bytes,
              'agent_reserve_gb': policy['agent_reserve_gb'], 'models': MODELS,
              'population': 175401, 'sites': 64, 'dt_ms': .1, 'record_dt_ms': 1.,
              'pulse_amplitudes_mv': [5., 10., -5.], 'pulse_duration_ms': 100.,
              'observation_duration_ms': 900., 'numerical_tolerance_mv': .001,
              'claim_limit': 'Experimental; no fully-surpasses-BANC or biological-validation claim'}
    budget.write_json('configuration.json', config)
    budget.write_json('benchmark.json', benchmark)
    files = {}
    for path in _source_files(root):
        relative = path.relative_to(root).as_posix()
        files[relative] = budget.copy_file(path, 'frozen/workspace/' + relative)
    for model_id, model_hash in MODELS.values():
        for path in sorted((root / 'build/model-versions' / model_hash).rglob('*')):
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                files[relative] = budget.copy_file(path, 'frozen/workspace/' + relative)
    # Input and anatomy copies contain no evaluation responses. Data module
    # supplies the exact list so the executable cannot discover new cases later.
    from .data import frozen_input_files
    for path in frozen_input_files(benchmark):
        path = Path(path)
        relative = path.relative_to(root).as_posix()
        files[relative] = budget.copy_file(path, 'frozen/workspace/' + relative)
    deps = dependency_identity()
    from .freezing import freeze_dependencies
    frozen_dependencies = freeze_dependencies(budget)
    manifest = {'schema': SCHEMA, 'source_root': str(root), 'output': str(output),
                'created_at': time.time(), 'configuration_sha256': digest(config),
                'benchmark_sha256': digest(benchmark), 'files': files, 'dependencies': deps,
                'source_identity': digest(files), 'frozen_dependencies': frozen_dependencies, 'predecessor': predecessor_record,
                'dependency_policy': 'Copied and hashed third-party packages; -S ignores live site-packages; interpreter and standard library content checked before restart'}
    budget.write_json('manifest.json', manifest)
    budget.write_json('control.json', {'command': 'pause', 'at': time.time()})
    budget.write_json('state.json', {'status': 'PREPARED', 'phase': 'prepared',
                                    'started_at': predecessor_record['original_started_at'] if predecessor_record else None,
                                    'completed_jobs': 0, 'source_identity': manifest['source_identity']})
    JobLedger(output / 'jobs.sqlite3').close()
    if predecessor_record:
        CampaignBudget(budget.accounting_root).write_json('active-campaign.json', {
            'output': str(output), 'source_identity': manifest['source_identity'],
            'predecessor': str(predecessor)})
    return status(output)


def active_output():
    pointer = DEFAULT_OUTPUT / 'active-campaign.json'
    if not pointer.exists():
        return DEFAULT_OUTPUT
    row = read_json(pointer)
    output = Path(row['output'])
    if (not output.is_relative_to(DEFAULT_OUTPUT / 'successors') or output.resolve() != output or
            read_json(output / 'manifest.json')['source_identity'] != row['source_identity']):
        raise ValueError('Active campaign pointer is invalid')
    return output


def validate_frozen(output, *, dependencies=True):
    output = Path(output)
    manifest = read_json(output / 'manifest.json')
    if digest(read_json(output / 'configuration.json')) != manifest['configuration_sha256']:
        raise ValueError('Frozen campaign configuration changed')
    if digest(read_json(output / 'benchmark.json')) != manifest['benchmark_sha256']:
        raise ValueError('Frozen benchmark changed')
    if digest(manifest['files']) != manifest['source_identity']:
        raise ValueError('Source identity does not match its manifest')
    for row in manifest['files'].values():
        path = output / row['path']
        if path.resolve() != path or file_sha(path) != row['sha256']:
            raise ValueError('Frozen file changed: ' + str(path))
    if dependencies:
        if 'frozen_dependencies' in manifest:
            from .freezing import validate_dependencies
            validate_dependencies(output, manifest['frozen_dependencies'])
        elif dependency_identity() != manifest['dependencies']:
            raise ValueError('Dependency identity changed; successor campaign required')
    return manifest


def live_policy(root):
    from flybrain.compute_policy import ComputePolicy
    saved = read_json(Path(root) / 'build/runtime/compute-policy.json')
    policy = ComputePolicy(root).snapshot()
    if any(saved.get(k) != policy[k] for k in ('tier', 'threads', 'memory_gb', 'agent_reserve_gb')):
        raise CampaignHalt('RESOURCE_LIMIT', 'Saved compute policy is invalid')
    if policy['tier'] == 'dummy':
        raise CampaignHalt('RESOURCE_LIMIT', 'Compute policy disables simulation')
    return policy


def activity_check(root):
    """Authenticated existing service check, or positive closed-port evidence."""
    from flybrain.graded_benchmark import authenticated_activity, _activity_reasons
    activity = authenticated_activity(root)
    reasons = _activity_reasons(activity)
    if reasons == ['AUTHENTICATED_ACTIVITY_UNKNOWN']:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(1.)
            code = connection.connect_ex(('127.0.0.1', 8794))
        if code == errno.ECONNREFUSED:
            return {'known': True, 'idle': True, 'source': 'local_simulation_service_port_closed'}, []
    return activity, reasons


def _pid_running(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def status(output=DEFAULT_OUTPUT):
    output = Path(output)
    if not (output / 'state.json').exists():
        return {'status': 'NOT_PREPARED', 'output': str(output)}
    state = read_json(output / 'state.json')
    state['worker_alive'] = _pid_running(state.get('pid'))
    if state.get('started_at'):
        state['elapsed_seconds'] = time.time() - state['started_at']
        state['remaining_seconds'] = max(0, MAX_ELAPSED_SECONDS - state['elapsed_seconds'])
    state['storage'] = CampaignBudget(output).snapshot()
    if (output / 'jobs.sqlite3').exists():
        ledger = JobLedger(output / 'jobs.sqlite3')
        state['jobs'] = ledger.counts()
        ledger.close()
    state['output'] = str(output)
    return state


def request_control(command, output=DEFAULT_OUTPUT):
    if command not in {'pause', 'resume', 'stop'}:
        raise ValueError('Unknown control command')
    output = Path(output)
    current = status(output)
    if current['status'] in TERMINAL:
        raise ValueError('Terminal campaign requires a separately identified successor')
    CampaignBudget(output).write_json('control.json', {'command': command, 'at': time.time()}, recovery=True)
    if command == 'resume':
        return start(output)
    if not current['worker_alive']:
        state = read_json(output / 'state.json')
        state['status'] = 'STOPPED' if command == 'stop' else 'PAUSED'
        CampaignBudget(output).write_json('state.json', state, recovery=True)
    return status(output)


def start(output=DEFAULT_OUTPUT):
    output = Path(output).absolute()
    manifest = validate_frozen(output)
    current = status(output)
    if current['status'] in TERMINAL:
        raise ValueError('Terminal campaign cannot be resumed')
    if current['worker_alive']:
        return current
    budget = CampaignBudget(output)
    budget.write_json('control.json', {'command': 'resume', 'at': time.time()}, recovery=True)
    dependency_paths = manifest.get('frozen_dependencies', {}).get('pythonpath', [])
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join([str(output / 'frozen/workspace/src')] +
                                                            [str(output / p) for p in dependency_paths]),
                       PYTHONDONTWRITEBYTECODE='1', NUMBA_CACHE_DIR=str(output / 'cache/numba'),
                       OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    script = output / 'frozen/workspace/scripts/run_transmission_campaign.py'
    # Pipe-free detached worker survives the chat and terminal exiting. Job
    # errors go to bounded JSON artifacts, not an unbounded stdout logfile.
    with open(os.devnull, 'wb') as null:
        flags = manifest.get('frozen_dependencies', {}).get('python_flags', [])
        process = subprocess.Popen([sys.executable, *flags, str(script), '_worker', '--output', str(output)],
                                   cwd=output, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=null, stderr=null, start_new_session=True)
        if Path('/usr/bin/caffeinate').exists():
            subprocess.Popen(['/usr/bin/caffeinate', '-s', '-w', str(process.pid)],
                             stdin=subprocess.DEVNULL, stdout=null, stderr=null, start_new_session=True)
    return {'status': 'LAUNCHING', 'pid': process.pid, 'output': str(output)}


class Supervisor:
    def __init__(self, output):
        self.output = Path(output).absolute()
        self.budget = CampaignBudget(self.output)
        self.manifest = validate_frozen(self.output)
        from .integrity import validate_scientific_plan
        validate_scientific_plan(self.output)
        self.root = Path(self.manifest['source_root'])
        self.frozen_root = self.output / 'frozen/workspace'
        self.config = read_json(self.output / 'configuration.json')
        self.state = read_json(self.output / 'state.json')
        self.state.update(status='RUNNING', pid=os.getpid())
        self.state['started_at'] = self.state.get('started_at') or time.time()
        self.ledger = JobLedger(self.output / 'jobs.sqlite3')
        self.ledger.recover()
        self._last_check = 0.
        self._live = False
        self.guard = None

    def save(self, **fields):
        self.state.update(fields, updated_at=time.time())
        self.budget.write_json('state.json', self.state, recovery=True)

    def admission(self):
        if not self._live:
            raise RuntimeError('Native simulation requires live primary locks and memory guard')
        now = time.time()
        if deadline_exceeded(now, self.state['started_at'], self.config['max_elapsed_seconds']):
            raise CampaignHalt('DEADLINE', 'Seven-day elapsed deadline reached')
        control = read_json(self.output / 'control.json')['command']
        if control in {'pause', 'stop'}:
            raise CampaignHalt('PAUSED' if control == 'pause' else 'STOPPED', 'Operator requested ' + control)
        if now - self._last_check >= 2:
            policy = live_policy(self.root)
            if policy['threads'] < self.state['threads']:
                import numba
                self.state['threads'] = policy['threads']
                numba.set_num_threads(policy['threads'])
            if self.guard:
                self.guard.limit = int(min(self.config['memory_gb'], policy['memory_gb']) * 1e9)
                self.guard.check()
            self.budget.check(8_000_000)  # bounded next block/checkpoint overhead
            self.save(peak_rss_bytes=self.guard.peak_rss if self.guard else 0,
                      memory_limit_gb=min(self.config['memory_gb'], policy['memory_gb']))
            self._last_check = now
        return {'admitted': True, 'threads': self.state['threads'], 'scope': 'full_graph',
                'source_identity': self.manifest['source_identity']}

    def run_job(self, specification, callback):
        from flybrain.memguard import MemoryLimitExceeded
        key = self.ledger.add(specification)
        row = self.ledger.get(key)
        if row['state'] == 'complete':
            return json.loads(row['result'])
        if row['state'] == 'failed':
            return {'status': 'FAILED', 'error': row['error'], 'job_id': key}
        while self.ledger.claim(key):
            self.admission()
            self.save(current_job=key, current_specification=specification)
            try:
                result = callback(key)
                self.ledger.complete(key, result)
                self.save(completed_jobs=self.ledger.counts().get('complete', 0))
                return result
            except (CampaignHalt, CampaignStorageExhausted, MemoryLimitExceeded):
                raise
            except OSError as exc:
                if exc.errno in {errno.ENOSPC, errno.EDQUOT}:
                    raise CampaignStorageExhausted('Filesystem storage exhausted during native artifact commit') from exc
                transient = exc.errno in {errno.EIO, errno.ETIMEDOUT, errno.EAGAIN, errno.EINTR, errno.ECONNRESET}
                if self.ledger.fail(key, repr(exc), transient=transient) == 'pending':
                    continue
                return {'status': 'FAILED', 'error': repr(exc), 'job_id': key}
            except Exception as exc:
                if hasattr(exc, 'receipt'):
                    self.budget.write_json('failures/' + key + '.json', {'error': repr(exc), 'receipt': exc.receipt})
                self.ledger.fail(key, repr(exc))
                return {'status': 'FAILED', 'error': repr(exc), 'job_id': key}

    def report(self, terminal, reason=None):
        report_path = self.output / 'comparison.json'
        report = read_json(report_path) if report_path.exists() else {
            'engineering_correctness': {'status': 'INCOMPLETE'},
            'predictive_comparison': {'status': 'INCONCLUSIVE'},
            'biological_evidence_status': read_json(self.output / 'benchmark.json').get('primary_gate')}
        report.update(campaign_status=terminal, reason=reason, jobs=self.ledger.counts(),
                      source_identity=self.manifest['source_identity'],
                      claims='Experimental. This campaign does not establish fully surpassing BANC.')
        self.budget.write_json('report.json', report, recovery=True)
        if terminal != 'PAUSED' and not (self.output / 'experimental-model.json').exists():
            candidate = {'schema': 'transmission-experimental-model-v1', 'status': 'UNSUCCESSFUL_OR_INCOMPLETE',
                         'base_model': MODELS['paralimbo'], 'source_identity': self.manifest['source_identity'],
                         'parameters': None, 'campaign_status': terminal, 'reason': reason,
                         'default_changed': False, 'biological_superiority': 'NOT_ESTABLISHED'}
            if (self.output / 'selected-candidates.json').exists():
                candidate['selection'] = read_json(self.output / 'selected-candidates.json')['paralimbo']
            candidate['model_identity'] = digest(candidate)
            self.budget.write_json('experimental-model.json', candidate, recovery=True)
        lines = ['# ParaLimbo transmission campaign', '', 'Status: ' + terminal,
                 '', reason or 'Frozen workload finished.', '',
                 'Engineering correctness: ' + json.dumps(report['engineering_correctness']), '',
                 'Predictive comparison: ' + json.dumps(report['predictive_comparison']), '',
                 'Biological evidence: ' + json.dumps(report['biological_evidence_status']), '',
                 'Detailed endpoints, failed jobs and diagnostics remain in the accompanying JSON artifacts.']
        self.budget.write_bytes('REPORT.md', ('\n'.join(lines) + '\n').encode(), recovery=True)

    def run(self):
        from flybrain.paralimbo_upgrade.resources import primary_locks
        from flybrain.memguard import MemoryGuard, MemoryLimitExceeded
        try:
            policy = live_policy(self.root)
            self.save(threads=min(self.config['threads'], policy['threads']), phase='admission')
            with ExitStack() as stack:
                while True:
                    if deadline_exceeded(time.time(), self.state['started_at'], self.config['max_elapsed_seconds']):
                        raise CampaignHalt('DEADLINE', 'Elapsed deadline reached while waiting for compute')
                    command = read_json(self.output / 'control.json')['command']
                    if command in {'pause', 'stop'}:
                        raise CampaignHalt('PAUSED' if command == 'pause' else 'STOPPED', 'Operator requested ' + command)
                    activity, reasons = activity_check(self.root)
                    lock_context = primary_locks()
                    if not reasons:
                        try:
                            lock_context.__enter__()
                        except RuntimeError as exc:
                            reasons = [str(exc)]
                        else:
                            stack.callback(lock_context.__exit__, None, None, None)
                            break
                    self.save(status='WAITING_FOR_COMPUTE', phase='waiting_for_compute', activity=activity,
                              waiting_reasons=reasons)
                    time.sleep(5.)
                guard = stack.enter_context(MemoryGuard(min(self.config['memory_gb'], policy['memory_gb'])))
                self.guard, self._live = guard, True
                self.save(status='RUNNING')
                self.admission()
                from .execution import execute
                execute(self)
                self.report('COMPLETE')
                self.save(status='COMPLETE', phase='complete', finished_at=time.time())
        except CampaignHalt as exc:
            self.report(exc.status, exc.reason)
            self.save(status=exc.status, reason=exc.reason)
        except (CampaignStorageExhausted, MemoryLimitExceeded) as exc:
            self.report('RESOURCE_LIMIT', str(exc))
            self.save(status='RESOURCE_LIMIT', reason=str(exc))
        except Exception as exc:
            import traceback
            self.budget.write_json('failure.json', {'error': repr(exc), 'traceback': traceback.format_exc()}, recovery=True)
            self.report('FAILED', str(exc))
            self.save(status='FAILED', reason=str(exc))
        finally:
            self._live = False
            self.ledger.close()


def worker(output):
    budget = CampaignBudget(output)
    with budget.path('.supervisor.lock').open('a+b') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'ALREADY_RUNNING'}
        try:
            Supervisor(output).run()
        except Exception as exc:
            import traceback
            budget.write_json('failure.json', {'error': repr(exc), 'traceback': traceback.format_exc()}, recovery=True)
            current = read_json(budget.path('state.json'))
            current.update(status='FAILED', reason=str(exc), pid=os.getpid())
            budget.write_json('state.json', current, recovery=True)
    return status(output)


def verify(output=DEFAULT_OUTPUT):
    output = Path(output)
    manifest = validate_frozen(output)
    budget = CampaignBudget(output)
    budget.check(0, recovery=True)
    ledger = JobLedger(output / 'jobs.sqlite3')
    rows = ledger.rows()
    ledger.close()
    report = {'source_identity': manifest['source_identity'], 'frozen_files_valid': True,
              'storage_valid': True, 'jobs': len(rows),
              'failed_jobs': [r['id'] for r in rows if r['state'] == 'failed'],
              'scientific_status': 'PENDING', 'independent_metrics': None}
    if (output / 'predictions/prediction-seal.json').exists():
        from .scoring import independently_verify
        report['independent_metrics'] = independently_verify(output)
        report['scientific_status'] = 'VERIFIED' if report['independent_metrics']['pass'] else 'FAILED'
    budget.write_json('verification.json', report, recovery=True)
    return report
