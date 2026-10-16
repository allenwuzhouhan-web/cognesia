#!/usr/bin/env python3
"""Prepare/check a sealed one-probe diagnostic replay; run requires explicit CLI action."""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import ast
from contextlib import contextmanager
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / 'build/biological-benchmark/paralimbo-transmission-v1'
SOURCE = CAMPAIGN / 'successors/0002'
OUTPUT = CAMPAIGN / 'maintenance/replay-0002-e4366706-v1'
JOB_ID = 'e43667062fa2d5f76129d032c31ff344f58fb37fa7484a447f5f78f34c29ec05'
SOURCE_ID = '3a9c10b4a941a064e184fc11c2ac1b82c1cf5198fc9c2b0b2e93afc8268ea6dc'
DEADLINE = 1792502587.076374
REPLAY_BYTES = 1_000_000_000
HEADROOM_BYTES = 128_000_000
MAX_WALL_SECONDS = 900
EXECUTION = 'src/flybrain/transmission_campaign/execution.py'


def read(path):
    path = Path(path).absolute()
    if path.resolve() != path or path.stat().st_nlink != 1:
        raise ValueError('Ordinary artifact required: ' + str(path))
    return json.loads(path.read_text())


def toolkit():
    from flybrain.transmission_campaign.budget import CampaignBudget, digest, file_sha
    from flybrain.transmission_campaign.integrity import write_once_json
    return CampaignBudget, digest, file_sha, write_once_json


def assert_logging_only(original, repaired):
    """Undo only the reviewed logging AST edits and demand identical old code."""
    old, new = ast.parse(original), ast.parse(repaired)
    new.body = [node for node in new.body if not isinstance(node, (ast.ClassDef, ast.FunctionDef)) or
                node.name not in {'_failure_scalar', 'NativeNumericalFailure'}]

    class UndoLogging(ast.NodeTransformer):
        def visit_Assign(self, node):
            if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and
                    node.targets[0].id == 'start_step' and
                    ast.unparse(node.value) == 'runner.engine.step'):
                return None
            return self.generic_visit(node)

        def visit_If(self, node):
            if (ast.unparse(node.test) == "not repeated['completed']" and len(node.body) == 1 and
                    isinstance(node.body[0], ast.Raise) and isinstance(node.body[0].exc, ast.Call) and
                    isinstance(node.body[0].exc.func, ast.Name) and
                    node.body[0].exc.func.id == 'NativeNumericalFailure'):
                return None
            return self.generic_visit(node)

        def visit_Raise(self, node):
            if isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name) and node.exc.func.id == 'NativeNumericalFailure':
                return ast.parse("raise ValueError('Native numerical failure: ' + str(part['failure_reason']))").body[0]
            return node

    for node in new.body:
        if isinstance(node, ast.FunctionDef) and node.name == '_checkpointed_run':
            UndoLogging().visit(node)
    if ast.dump(old, include_attributes=False) != ast.dump(new, include_attributes=False):
        raise ValueError('Execution overlay contains changes beyond reviewed diagnostic retention')


def source_job(source):
    _, digest, file_sha, _ = toolkit()
    manifest, state, config = [read(source / p) for p in ('manifest.json', 'state.json', 'configuration.json')]
    if (manifest['source_identity'] != SOURCE_ID or state['source_identity'] != SOURCE_ID or
            state['status'] != 'FAILED' or state['current_job'] != JOB_ID or
            state['started_at'] + config['max_elapsed_seconds'] != DEADLINE or
            config['population'] != 175401 or config['threads'] > 16 or config['memory_gb'] > 24 or
            config['storage_bytes'] != 20_000_000_000):
        raise ValueError('Failed source attempt or original limits differ')
    with sqlite3.connect((source / 'jobs.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('SELECT * FROM jobs WHERE id=?', (JOB_ID,)).fetchone()
    if row is None or row['state'] != 'failed' or row['attempts'] != 1:
        raise ValueError('Exactly the original once-failed job is required')
    spec = json.loads(row['specification'])
    if digest(spec) != JOB_ID or spec != state['current_specification'] or spec['kind'] != 'direct':
        raise ValueError('Exact physical job identity differs')
    if (source / 'observations').exists() or (source / 'predictions/prediction-seal.json').exists():
        raise ValueError('Replay is restricted to the original outcome-blind attempt')
    return manifest, state, config, dict(row), spec


def prepare(output=OUTPUT, source=SOURCE, *, execution_overlay=None):
    Budget, digest, file_sha, once = toolkit()
    output, source = Path(output).absolute(), Path(source).absolute()
    if not output.is_relative_to(CAMPAIGN / 'maintenance'):
        raise ValueError('Replay must remain inside the original campaign accounting tree')
    budget = Budget(output)
    if budget.accounting_root != CAMPAIGN:
        raise ValueError('Original shared accounting anchor required')
    if budget.path('manifest.json').exists():
        return validate(output)
    from flybrain.transmission_campaign.controller import validate_frozen
    original, state, config, job, specification = source_job(source)
    validate_frozen(source)
    original_execution = source / original['files'][EXECUTION]['path']
    repaired = Path(execution_overlay) if execution_overlay else ROOT / EXECUTION
    assert_logging_only(original_execution.read_text(), repaired.read_text())
    files = {
        'launcher.py': budget.copy_file(Path(__file__).absolute(), 'sealed/launcher.py'),
        'execution.py': budget.copy_file(repaired, 'sealed/execution.py'),
    }
    body = {'schema': 'transmission-single-probe-replay-v1', 'source_attempt': str(source),
        'source_manifest_sha256': file_sha(source / 'manifest.json'), 'source_identity': SOURCE_ID,
        'source_job': job, 'job_id': JOB_ID, 'specification': specification,
        'source_ledger_sha256': file_sha(source / 'jobs.sqlite3'),
        'original_started_at': state['started_at'], 'deadline': DEADLINE,
        'source_state_sha256': file_sha(source / 'state.json'), 'files': files,
        'frozen_dependencies_identity': original['frozen_dependencies']['identity'],
        'limits': {'attempts': 1, 'population': 175401, 'threads': min(16, config['threads']),
            'memory_gb': min(24., config['memory_gb']), 'agent_reserve_gb': config['agent_reserve_gb'],
            'shared_storage_bytes': 20_000_000_000, 'replay_storage_bytes': REPLAY_BYTES,
            'wall_seconds': MAX_WALL_SECONDS},
        'policy': 'Exact engineering replay only; no scorer, biological responses, retries, or campaign continuation',
        'source_policy': 'Frozen original source/dependencies/inputs plus the sealed diagnostic-only execution overlay',
        'prepared_at': time.time()}
    once(budget, 'manifest.json', body | {'identity': digest(body)})
    return validate(output)


def validate(output):
    Budget, digest, file_sha, _ = toolkit()
    output = Path(output).absolute()
    m = read(output / 'manifest.json')
    if m.get('schema') != 'transmission-single-probe-replay-v1' or m['identity'] != digest({k:v for k,v in m.items() if k != 'identity'}):
        raise ValueError('Replay manifest changed')
    source = Path(m['source_attempt'])
    original, state, config, job, spec = source_job(source)
    expected_limits = {'attempts':1,'population':175401,'threads':min(16,config['threads']),
        'memory_gb':min(24.,config['memory_gb']),'agent_reserve_gb':config['agent_reserve_gb'],
        'shared_storage_bytes':20_000_000_000,'replay_storage_bytes':REPLAY_BYTES,'wall_seconds':MAX_WALL_SECONDS}
    if (m['job_id'] != JOB_ID or m['specification'] != spec or m['source_job'] != job or
            m['deadline'] != DEADLINE or m['original_started_at'] != state['started_at'] or
            m['source_manifest_sha256'] != file_sha(source / 'manifest.json') or
            m['source_state_sha256'] != file_sha(source / 'state.json') or
            m['source_ledger_sha256'] != file_sha(source / 'jobs.sqlite3') or m['limits'] != expected_limits):
        raise ValueError('Replay no longer matches the preserved failed attempt')
    for row in m['files'].values():
        path = output / row['path']
        if path.resolve() != path or path.stat().st_nlink != 1 or file_sha(path) != row['sha256']:
            raise ValueError('Sealed replay source changed')
    from flybrain.transmission_campaign.controller import validate_frozen
    validate_frozen(source)
    assert_logging_only((source / original['files'][EXECUTION]['path']).read_text(),
                        (output / m['files']['execution.py']['path']).read_text())
    budget = Budget(output)
    if budget.accounting_root != CAMPAIGN or budget.limit_bytes > 20_000_000_000:
        raise ValueError('Shared campaign accounting changed')
    return m


@contextmanager
def exclusive(path):
    path = Path(path)
    if path.resolve() != path or (path.exists() and path.stat().st_nlink != 1):
        raise ValueError('Ordinary exclusion lock required')
    with path.open('a+b') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def admission(output, m, *, guard=None, began=None):
    Budget, _, _, _ = toolkit()
    from flybrain.transmission_campaign.controller import live_policy, CampaignHalt
    if time.time() >= m['deadline'] or (began is not None and time.monotonic() - began >= MAX_WALL_SECONDS):
        raise CampaignHalt('DEADLINE','Original deadline or bounded replay wall-time reached')
    source = Path(m['source_attempt'])
    if read(source / 'control.json')['command'] in {'pause', 'stop'}:
        raise CampaignHalt('PAUSED','Operator pause/stop prevents replay')
    budget = Budget(output)
    budget.check(HEADROOM_BYTES)
    used = sum(p.stat().st_size for p in Path(output).rglob('*') if p.is_file())
    if used + HEADROOM_BYTES > REPLAY_BYTES:
        raise CampaignHalt('RESOURCE_LIMIT','Replay storage allowance exhausted')
    live = live_policy(ROOT)
    threads = min(m['limits']['threads'], live['threads'])
    memory = min(m['limits']['memory_gb'], live['memory_gb'])
    if live['agent_reserve_gb'] < m['limits']['agent_reserve_gb']:
        raise CampaignHalt('RESOURCE_LIMIT','Local-model memory reserve was lowered')
    if guard is not None:
        guard.limit = int(memory * 1e9)
        guard.check()
    return {'admitted': True, 'threads': threads, 'memory_gb': memory,
            'agent_reserve_gb': live['agent_reserve_gb'], 'scope': 'full_graph', 'source_identity': SOURCE_ID}


def check(output):
    m = validate(output)
    result = {'status': 'READY', 'identity': m['identity'], 'job_id': JOB_ID, 'deadline': DEADLINE,
              'admission': admission(output, m), 'native_executed': False}
    import psutil
    from flybrain.transmission_campaign.controller import activity_check
    state = read(Path(m['source_attempt']) / 'state.json')
    if (Path(output)/('active/'+JOB_ID+'.npz')).exists() and not (Path(output)/'execution-started.json').exists():
        raise ValueError('Replay must cold-start; pre-existing checkpoint is forbidden')
    if state.get('pid') and psutil.pid_exists(state['pid']):
        raise RuntimeError('Original worker PID is alive or reused; ownership must be resolved')
    activity, reasons = activity_check(ROOT)
    if reasons:
        raise RuntimeError('Compute activity prevents replay: ' + ', '.join(reasons))
    result['activity'] = {k:activity[k] for k in ('known','idle','source') if k in activity}
    from flybrain.paralimbo_upgrade.resources import primary_locks
    with exclusive(Path(m['source_attempt']) / '.supervisor.lock'), primary_locks():
        result['locks'] = 'all original supervisor and heavy-compute locks acquired/released'
    if (Path(output) / 'launch.json').exists():
        result['status'] = 'ALREADY_ATTEMPTED'
    return result


def run(output):
    Budget, _, _, once = toolkit()
    output = Path(output).absolute()
    budget = Budget(output)
    with exclusive(budget.path('.launch.lock')):
        if budget.path('launch.json').exists():
            return {'status': 'ALREADY_ATTEMPTED', 'launch': read(budget.path('launch.json'))}
        try:
            evidence = check(output)
        except Exception as exc:
            budget.write_json('non-execution.json', {'status':'NON_EXECUTED','error':str(exc),
                'at':time.time(),'native_executed':False}, recovery=True)
            return read(budget.path('non-execution.json'))
        m = read(budget.path('manifest.json'))
        source = Path(m['source_attempt'])
        original = read(source / 'manifest.json')
        deps = original['frozen_dependencies']
        once(budget, 'launch.json', {'identity':m['identity'],'job_id':JOB_ID,'at':time.time(),
                                    'attempt':1,'admission':evidence})
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(source/'frozen/workspace/src')] +
            [str(source/p) for p in deps['pythonpath']]), PYTHONDONTWRITEBYTECODE='1',
            NUMBA_CACHE_DIR=str(output/'cache/numba'), TMPDIR=str(output/'tmp'),
            OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
        budget.path('tmp').mkdir(exist_ok=True)
        with open(os.devnull, 'wb') as null:
            child = subprocess.Popen([sys.executable, *deps['python_flags'],
                str(output/m['files']['launcher.py']['path']), '_worker', '--output', str(output)],
                env=env,cwd=output,stdin=subprocess.DEVNULL,stdout=null,stderr=null,start_new_session=True)
            if Path('/usr/bin/caffeinate').exists():
                subprocess.Popen(['/usr/bin/caffeinate','-s','-w',str(child.pid)],
                    stdin=subprocess.DEVNULL,stdout=null,stderr=null,start_new_session=True)
        result={'status':'LAUNCHING','pid':child.pid,'identity':m['identity'],'attempt':1}
        budget.write_json('process.json',result,recovery=True)
        return result


class ReadBoundary:
    """Python I/O allowlist: registered sources/inputs, sealed runtime, output and live policy only."""
    def __init__(self, output, m, original):
        source = Path(m['source_attempt'])
        self.output = Path(output).resolve()
        self.reads = {str((source/r['path']).resolve()) for r in original['files'].values()}
        deps = original['frozen_dependencies']
        self.reads.update(str((source/deps['directory']/p).resolve()) for p in deps['files'])
        host = deps['host_runtime']
        self.reads.update(str((Path(host['standard_library'])/p).resolve()) for p in host['files'])
        self.reads.update(str(p.resolve()) for p in (source/'control.json',ROOT/'build/runtime/compute-policy.json',
            CAMPAIGN/'.campaign-budget-anchor.json',CAMPAIGN/'.budget.lock'))
        self.write_exceptions = {str((CAMPAIGN/'.budget.lock').resolve())}
        self.denied = []

    def __call__(self,event,args):
        if event != 'open' or isinstance(args[0],int):
            return
        path = Path(os.fsdecode(args[0])).absolute().resolve()
        mode, flags = args[1], args[2]
        writing = (isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC))
        allowed = path.is_relative_to(self.output) or str(path) in (self.write_exceptions if writing else self.reads)
        if not allowed:
            if len(self.denied)<8:
                self.denied.append({'path':str(path),'writing':bool(writing)})
            raise PermissionError('Unregistered replay I/O denied: ' + str(path))


def execute_once(output, m):
    """One physical direct probe; never calls campaign execution or a scorer."""
    Budget, _, _, _ = toolkit()
    from flybrain.transmission_campaign.runtime import build_direct_runner, DirectProtocol, DirectPulse
    from flybrain.memguard import MemoryGuard
    original = read(Path(m['source_attempt'])/'manifest.json')
    overlay_path=Path(output)/m['files']['execution.py']['path']
    spec=importlib.util.spec_from_file_location('flybrain.transmission_campaign.execution',overlay_path)
    overlay=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(overlay)
    budget=Budget(output)
    policy=admission(output,m)
    began=time.monotonic()
    physics=m['specification']; protocol=dict(physics['protocol'])
    protocol['pulses']=tuple(DirectPulse(**pulse) for pulse in protocol['pulses'])
    protocol=DirectProtocol(**protocol)
    boundary=ReadBoundary(output,m,original)
    sys.addaudithook(boundary)
    result={'job_id':JOB_ID,'execution_identity':m['identity'],'native_executed':False,
            'evaluation_response_access':'DENIED_BY_REGISTERED_FILE_ALLOWLIST'}
    with MemoryGuard(policy['memory_gb']) as guard:
        def admit():
            return admission(output,m,guard=guard,began=began)
        try:
            result['native_executed']=True
            runner=build_direct_runner(Path(m['source_attempt'])/'frozen/workspace',*physics['model'],
                protocol,parameters=physics['parameters'],threads=policy['threads'],admission=admit)
            supervisor=type('ReplayOutput',(),{'output':Path(output),'budget':budget})()
            trace,timing=overlay._checkpointed_run(supervisor,JOB_ID,runner)
            result.update(status='COMPLETED',diagnostics=runner.diagnostics(),
                          runtime_identity=runner.runtime_identity,timing=timing)
            # No additional diagnostic probe or full-population arrays are saved.
            result['recorded_samples']=len(trace['time_ms'])
        except Exception as exc:
            result.update(status='NUMERICAL_FAILURE' if hasattr(exc,'receipt') else 'INTERRUPTED_OR_REFUSED',
                          error=type(exc).__name__+': '+str(exc),receipt=getattr(exc,'receipt',None))
        result.update(peak_rss_bytes=guard.peak_rss,wall_seconds=time.monotonic()-began,
                      denied_io=boundary.denied)
        budget.write_json('result.json',result,recovery=True)
    return result


def worker(output):
    Budget, _, _, once = toolkit()
    output=Path(output).absolute(); budget=Budget(output)
    with exclusive(budget.path('.worker.lock')):
        if budget.path('execution-started.json').exists() or budget.path('result.json').exists():
            return {'status':'ALREADY_ATTEMPTED'}
        try:
            m=validate(output)
            if read(budget.path('launch.json'))['identity']!=m['identity']:
                raise ValueError('Sealed launch intent required')
            evidence=check(output)
            from flybrain.paralimbo_upgrade.resources import primary_locks
            with exclusive(Path(m['source_attempt'])/'.supervisor.lock'),primary_locks():
                admission(output,m)
                once(budget,'execution-started.json',{'identity':m['identity'],'job_id':JOB_ID,
                     'attempt':1,'pid':os.getpid(),'at':time.time(),'admission':evidence})
                return execute_once(output,m)
        except Exception as exc:
            retained=read(budget.path('result.json')) if budget.path('result.json').exists() else {}
            result={'status':'NON_EXECUTED' if not budget.path('execution-started.json').exists() else 'INTERRUPTED_OR_REFUSED',
                    'error':type(exc).__name__+': '+str(exc),'at':time.time(),
                    'native_executed':retained.get('native_executed',False),'prior_result':retained or None}
            budget.write_json('result.json',result,recovery=True)
            return result


def main():
    sys.dont_write_bytecode = True
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','check','run','_worker'])
    parser.add_argument('--output',type=Path,default=OUTPUT)
    parser.add_argument('--execution-overlay',type=Path,help='Prepare only: existing reviewed logging overlay')
    args=parser.parse_args()
    if Path(__file__).parent.name=='sealed':
        m=read(args.output/'manifest.json')
        source=Path(m['source_attempt']); original=read(source/'manifest.json')
        dependencies=original['frozen_dependencies']
        standard_library=Path(dependencies['host_runtime']['standard_library'])
        sys.path[:]=[str(source/'frozen/workspace/src'),
            *[str(source/p) for p in dependencies['pythonpath']],
            str(standard_library),str(standard_library/'lib-dynload')]
    elif args.command=='_worker':
        raise ValueError('Native replay requires the sealed launcher')
    else:
        sys.path.insert(0,str(ROOT/'src'))
    if args.command=='prepare':
        result=prepare(args.output,execution_overlay=args.execution_overlay)
    else:
        if args.execution_overlay is not None:
            raise ValueError('Execution overlay can only be selected while preparing')
        result=globals()['worker' if args.command=='_worker' else args.command](args.output)
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__=='__main__':
    main()
