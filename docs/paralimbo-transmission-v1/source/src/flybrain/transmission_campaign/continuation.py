"""Prepare a separately identified, outcome-blind continuation; never launch it.

Completed trajectories remain ordinary files in the shared accounting tree.
Only their source-key namespace changes, under a pinned equivalence review.
"""
from __future__ import annotations

import ast
import copy
from contextlib import ExitStack, contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import sqlite3
import time
import uuid

from . import controller
from .budget import CampaignBudget, canonical, digest, file_sha
from .ledger import JobLedger

EXECUTION = 'src/flybrain/transmission_campaign/execution.py'
BRIDGE_KEY = 'continuation/reuse-contract.json'
BRIDGE_PATH = 'frozen/continuation-reuse-contract.json'
FORBIDDEN = ('observations', 'predictions', 'predictions-t4d', 'scores.json', 'scores-t4d.json',
             'selected-candidates.json', 'input-selection.json', 'scientific-plan-seal.json',
             'calibration-schedules.json', 'sensitivity.json')
COPY_METADATA = ('schedule.json', 'pilot.json', 'site-inventory.json', 'causal-controls.json')
POLICY = 'failure-aware-sensitivity-v1'


def ordinary(path, within=None):
    path = Path(path).absolute()
    if path.resolve() != path or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError('Ordinary existing file required: ' + str(path))
    if within is not None and not path.is_relative_to(Path(within).absolute()):
        raise ValueError('Reference escapes the shared accounting tree')
    return path


def read(path):
    return json.loads(ordinary(path).read_bytes())


def _rows(output):
    path = ordinary(Path(output) / 'jobs.sqlite3')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute('SELECT * FROM jobs ORDER BY id')]


def assert_execution_equivalent(before, after, *, allow_policy=True):
    """Undo precisely the logging edits; only sensitivity policy may differ."""
    old, new = ast.parse(before), ast.parse(after)
    original_sensitivity = next(n for n in old.body if isinstance(n, ast.FunctionDef) and n.name == 'sensitivity')
    allowed_helpers = {'_failure_scalar', 'NativeNumericalFailure'}
    if allow_policy:
        allowed_helpers.add('_sensitivity_rejection')
    new.body = [n for n in new.body if not isinstance(n, (ast.FunctionDef, ast.ClassDef)) or
                n.name not in allowed_helpers]

    class UndoLogging(ast.NodeTransformer):
        def visit_Assign(self, node):
            if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and
                    node.targets[0].id == 'start_step' and ast.unparse(node.value) == 'runner.engine.step'):
                return None
            return self.generic_visit(node)

        def visit_If(self, node):
            if (ast.unparse(node.test) == "not repeated['completed']" and len(node.body) == 1 and
                    isinstance(node.body[0], ast.Raise) and isinstance(node.body[0].exc, ast.Call) and
                    isinstance(node.body[0].exc.func, ast.Name) and node.body[0].exc.func.id == 'NativeNumericalFailure'):
                return None
            return self.generic_visit(node)

        def visit_Raise(self, node):
            if (isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name) and
                    node.exc.func.id == 'NativeNumericalFailure'):
                return ast.parse("raise ValueError('Native numerical failure: ' + str(part['failure_reason']))").body[0]
            return node

    for index, node in enumerate(new.body):
        if isinstance(node, ast.FunctionDef) and node.name == '_checkpointed_run':
            UndoLogging().visit(node)
        elif allow_policy and isinstance(node, ast.FunctionDef) and node.name == 'sensitivity':
            new.body[index] = copy.deepcopy(original_sensitivity)
    if ast.dump(old, include_attributes=False) != ast.dump(new, include_attributes=False):
        raise ValueError('Trajectory code changed outside reviewed logging/sensitivity policy')


def _no_worker(previous, state):
    import psutil
    script = str(previous / 'frozen/workspace/scripts/run_transmission_campaign.py')
    for process in psutil.process_iter(['pid', 'cmdline', 'status'], ad_value=None):
        row = process.info
        if row['status'] == psutil.STATUS_ZOMBIE:
            continue
        if row['pid'] == state.get('pid') or (row['cmdline'] and script in row['cmdline'] and '_worker' in row['cmdline']):
            raise ValueError('Predecessor worker identity is still present or ambiguous')


def _reference(value, previous, accounting, references):
    """Rewrite only content-verified receipt paths; never copy trajectory bytes."""
    if isinstance(value, list):
        return [_reference(x, previous, accounting, references) for x in value]
    if not isinstance(value, dict):
        return value
    if {'path', 'sha256', 'bytes'} <= value.keys():
        path = ordinary(previous / value['path'], accounting)
        key = str(path)
        record = {'path': key, 'sha256': value['sha256'], 'bytes': value['bytes']}
        if key not in references:
            if path.stat().st_size != record['bytes'] or file_sha(path) != record['sha256']:
                raise ValueError('Reusable artifact bytes changed: ' + key)
            references[key] = record
        elif references[key] != record:
            raise ValueError('Conflicting receipts for one artifact')
        return {**value, 'path': key}
    return {k: _reference(v, previous, accounting, references) for k, v in value.items()}


def _validate_replay(previous, manifest, rows, replay_result, review, accounting):
    result_path = ordinary(replay_result, accounting)
    replay_path = ordinary(result_path.parent / 'manifest.json', accounting)
    replay, result = read(replay_path), read(result_path)
    if (file_sha(result_path) != review['replay_result_sha256'] or
            file_sha(replay_path) != review['replay_manifest_sha256'] or
            replay.get('schema') != 'transmission-single-probe-replay-v1' or
            replay.get('identity') != digest({k:v for k,v in replay.items() if k != 'identity'}) or
            replay.get('source_attempt') != str(previous) or
            replay.get('source_identity') != manifest['source_identity'] or
            replay.get('source_manifest_sha256') != file_sha(previous / 'manifest.json') or
            replay.get('source_ledger_sha256') != file_sha(previous / 'jobs.sqlite3') or
            (replay.get('source_state_sha256') is not None and replay['source_state_sha256'] != file_sha(previous / 'state.json')) or
            result.get('execution_identity') != replay['identity'] or
            result.get('job_id') != replay.get('job_id') or
            result.get('native_executed') is not True or result.get('status') != 'NUMERICAL_FAILURE'):
        raise ValueError('Replay does not establish the exact predecessor numerical rejection')
    _validate_denied_imports(previous, manifest, replay_path.parent, replay, result, review)
    failed = next((r for r in rows if r['id'] == replay['job_id'] and r['state'] == 'failed'), None)
    if failed is None or json.loads(failed['specification']) != replay.get('specification'):
        raise ValueError('Replay physical specification differs from failed job')
    for record in replay['files'].values():
        path = ordinary(replay_path.parent / record['path'], accounting)
        if file_sha(path) != record['sha256'] or path.stat().st_size != record['bytes']:
            raise ValueError('Replay sealed source changed')
    old_source = (previous / manifest['files'][EXECUTION]['path']).read_text()
    overlay = replay_path.parent / replay['files']['execution.py']['path']
    assert_execution_equivalent(old_source, overlay.read_text(), allow_policy=False)
    receipt = result.get('receipt') or {}
    diagnostic = receipt.get('diagnostics') or {}
    numeric = ('clamps', 'nonfinite_voltage_updates', 'nonfinite_synaptic_updates', 'nonfinite_release_updates')
    if (receipt.get('schema') != 'transmission-native-numerical-failure-v1' or
            receipt.get('job_id') != failed['id'] or
            receipt.get('failure_reason') != 'COMPILED_STATE_CHECK_FAILED' or
            diagnostic.get('pass') is not False or diagnostic.get('simulated_population') != 175401 or
            diagnostic.get('invalid_delayed_spikes') != 0 or diagnostic.get('endpoint_finite') is not True or
            not all(type(diagnostic.get(k)) is int and diagnostic[k] >= 0 for k in numeric) or
            diagnostic['clamps'] <= 0 or any(diagnostic[k] for k in numeric if k != 'clamps') or
            receipt.get('stage') != 'integration'):
        raise ValueError('Replay failure is not a classified numerical rejection')
    return {'job_id': failed['id'], 'receipt': receipt,
            'manifest': {'path': str(replay_path), 'sha256': file_sha(replay_path), 'bytes': replay_path.stat().st_size},
            'result': {'path': str(result_path), 'sha256': file_sha(result_path), 'bytes': result_path.stat().st_size}}


def _validate_denied_imports(previous, source_manifest, replay_root, replay, result, review):
    """Retained cache misses may be reviewed; never infer an exhaustive deny log."""
    denials = result.get('denied_io', [])
    if not denials:
        return
    attestation = review.get('denied_io_attestation') or {}
    if (attestation.get('status') != 'PASS' or attestation.get('kind') != 'missing_bytecode_cache_only' or
            attestation.get('replay_result_sha256') != review['replay_result_sha256'] or
            attestation.get('reported_entries_limit') != 8 or attestation.get('full_deny_log_available') is not False or
            len(denials) > 8):
        raise ValueError('Explicit independent review of retained denied cache reads required')
    launcher = ordinary(replay_root / replay['files']['launcher.py']['path'])
    source = launcher.read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'ReadBoundary')
    import hashlib
    if hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest() != attestation.get('read_boundary_sha256'):
        raise ValueError('Reviewed Python audit boundary changed')
    bindings = attestation.get('registered_source_bindings', [])
    if len(bindings) != len(denials):
        raise ValueError('Every retained denied lookup requires a registered source binding')
    dependency = source_manifest['frozen_dependencies']
    base = previous / dependency['directory']
    for denial, binding in zip(denials, bindings):
        path = Path(denial['path'])
        if (denial.get('writing') is not False or not path.is_absolute() or path.resolve() != path or
                path.exists() or path.parent.name != '__pycache__' or path.suffix != '.pyc' or
                not path.is_relative_to(base) or binding.get('denied_path') != str(path)):
            raise ValueError('Denied access is not an absent registered dependency bytecode lookup')
        stem = path.name.split('.cpython-', 1)
        if len(stem) != 2 or not stem[0] or not stem[1].endswith('.pyc'):
            raise ValueError('Unrecognized dependency bytecode cache name')
        python_source = ordinary(path.parent.parent / (stem[0] + '.py'), base)
        registered = dependency['files'].get(str(python_source.relative_to(base)))
        if (not registered or binding.get('source_path') != str(python_source) or
                binding.get('source_sha256') != registered['sha256'] or file_sha(python_source) != registered['sha256']):
            raise ValueError('Denied bytecode lookup has no matching frozen source')


def remaining_forecast(pilot, rows, inventory, targets, remaining_seconds, freeze_bytes, *, calibration_seconds_remaining=None):
    """Upper bound remaining work, deliberately claiming no T4 cache savings."""
    if remaining_seconds <= 0:
        raise ValueError('Original elapsed deadline has expired')
    direct_done = sum(json.loads(r['specification'])['kind'] == 'direct' and
        json.loads(r['specification'])['protocol']['label'] in
        {'matched-site-probe', 'preselected-silencing', 'preselected-rescue'} for r in rows)
    diagnosis = 2 * len(inventory['sites']) * 4 + 4 * sum(bool(x['rescue_root_id']) for x in targets.values())
    sensitivity_done = sum(json.loads(r['specification'])['kind'] == 'direct' and
        json.loads(r['specification'])['protocol']['label'] == 'sensitivity-active-coverage' for r in rows)
    counts = {'diagnostic': max(0, diagnosis - direct_done), 'sensitivity': max(0, 166 - sensitivity_done),
              'input_calibration': 30, 'calibration': 80, 'evaluation_and_refinement': 108,
              'independent_verification': 8}
    rate = max(pilot['quiet_seconds_per_simulated_second'], pilot['active_seconds_per_simulated_second'])
    duration = max(1., pilot['maximum_case_seconds'])
    startup = pilot['startup_seconds']
    if not all(math.isfinite(x) and x >= 0 for x in (rate, duration, startup)) or rate == 0:
        raise ValueError('Finite measured pilot required')
    pre = counts['diagnostic'] + duration * (2 * counts['sensitivity'] + counts['input_calibration'] + counts['calibration'])
    post = duration * (2 * counts['evaluation_and_refinement'] + counts['independent_verification'])
    pre_seconds = 2 * rate * pre + startup * sum(counts[k] for k in ('diagnostic', 'sensitivity', 'input_calibration', 'calibration'))
    forecast = pre_seconds + 2 * rate * post + startup * (counts['evaluation_and_refinement'] + counts['independent_verification'])
    direct_bytes = counts['diagnostic'] * pilot['direct_retained_bytes']
    # Sensitivity includes 26 direct probes; account their larger whole-state result too.
    native_jobs = sum(counts[k] for k in ('sensitivity', 'input_calibration', 'calibration', 'evaluation_and_refinement'))
    future_bytes = direct_bytes + native_jobs * max(pilot['direct_retained_bytes'], pilot['t4_retained_bytes_bound'])
    classification_bytes = 2 * len(inventory['sites']) * 3 * (175401 * 3 + 1024)
    required_bytes = int(freeze_bytes + future_bytes + classification_bytes + 2 * pilot['checkpoint_peak_bytes'] + 40_000_000)
    cutoff_remaining = .75 * remaining_seconds if calibration_seconds_remaining is None else min(.75 * remaining_seconds, calibration_seconds_remaining)
    if forecast > remaining_seconds or pre_seconds > cutoff_remaining:
        raise ValueError('Remaining eight-proposal workload does not preserve time/25-percent evaluation reserve')
    return {'counts_upper_bound': counts, 'forecast_seconds': forecast, 'pre_evaluation_seconds': pre_seconds,
            'remaining_seconds': remaining_seconds, 'required_additional_bytes': required_bytes,
            'freeze_bytes_bound': int(freeze_bytes), 'evaluation_reserve_fraction': .25, 'forecast_multiplier': 2.,
            'calibration_seconds_remaining': cutoff_remaining,
            'classification_recreation_bytes': classification_bytes,
            'native_t4_cache_savings_claimed': 0, 'proposals_per_arm': 8}


def inspect_continuation(root, predecessor, output, review_path, replay_result_path, *, now=None):
    root, previous, output = (Path(p).absolute() for p in (root, predecessor, output))
    if output.exists():
        raise ValueError('Continuation requires a fresh output path; partial preparations are not resumed')
    manifest = controller.validate_frozen(previous)
    state, config, schedule = (read(previous / p) for p in ('state.json', 'configuration.json', 'schedule.json'))
    if state['status'] not in controller.TERMINAL:
        raise ValueError('Predecessor must remain terminal')
    _no_worker(previous, state)
    if any((previous / name).exists() for name in FORBIDDEN):
        raise ValueError('Continuation is allowed only before outcome access and scientific-plan sealing')
    if schedule.get('status') != 'FROZEN' or schedule.get('proposals_per_arm') != 8:
        raise ValueError('Exactly the already frozen eight proposals per arm required')
    if (config.get('population') != 175401 or config.get('max_elapsed_seconds') != controller.MAX_ELAPSED_SECONDS or
            config.get('models') != {k:list(v) for k,v in controller.MODELS.items()}):
        raise ValueError('Predecessor scientific configuration is outside this continuation contract')
    started = state.get('started_at')
    if not isinstance(started, (int, float)) or not math.isfinite(started) or started <= 0:
        raise ValueError('Original start time required')
    budget = CampaignBudget(previous)
    accounting = budget.accounting_root
    if output.resolve() != output or not output.is_relative_to(accounting / 'successors'):
        raise ValueError('Continuation must remain inside the original shared campaign budget')
    review = read(review_path)
    if (review.get('schema') != 'transmission-continuation-review-v1' or review.get('status') != 'PASS' or
            review.get('policy') != POLICY or review.get('predecessor_source_identity') != manifest['source_identity']):
        raise ValueError('Independent pinned continuation review required')
    changes = {}
    for relative, record in manifest['files'].items():
        current = ordinary(root / relative)
        actual = file_sha(current)
        if actual != record['sha256']:
            if (relative != EXECUTION or review.get('execution_before_sha256') != record['sha256'] or
                    review.get('execution_after_sha256') != actual):
                raise ValueError('Unreviewed source/model/input change: ' + relative)
            assert_execution_equivalent((previous / record['path']).read_text(), current.read_text())
            changes[relative] = {'before': record['sha256'], 'after': actual}
    if EXECUTION not in changes:
        raise ValueError('A separately reviewed sensitivity policy correction is required')
    added = {str(p.relative_to(root)): file_sha(ordinary(p)) for p in controller._source_files(root)
             if str(p.relative_to(root)) not in manifest['files']}
    if added != review.get('approved_added_files', {}):
        raise ValueError('Added executable files differ from reviewed inventory')
    if controller.dependency_identity() != manifest['dependencies']:
        raise ValueError('Interpreter/package identity changed')
    dependencies = manifest['frozen_dependencies']
    for relative, record in dependencies['files'].items():
        index, rest = relative.split('/', 1)
        path = Path(dependencies['source_roots'][int(index.removeprefix('root-'))]) / rest
        # Dependency freezing dereferences installed file links into ordinary copied bytes.
        if not path.is_file() or path.stat().st_size != record['bytes'] or file_sha(path) != record['sha256']:
            raise ValueError('Installed dependency bytes changed: ' + relative)
    rows = _rows(previous)
    references, imports = {}, []
    for row in rows:
        spec = json.loads(row['specification'])
        if (row['id'] != digest(spec) or spec.get('source') != manifest['source_identity'] or
                spec.get('kind') not in {'direct', 'native_t4'} or row['state'] not in {'complete', 'failed'} or
                type(row['attempts']) is not int or row['attempts'] < 1):
            raise ValueError('Only complete or failed fully identified physical jobs may be imported')
        result = json.loads(row['result']) if row['result'] else None
        if row['state'] == 'complete' and (not result or result.get('status') != 'PASS' or 'arrays' not in result or
                                          ('summary' not in result and spec['kind'] == 'direct')):
            raise ValueError('Completed job lacks qualified physical result receipts')
        if row['state'] == 'complete':
            for name in ('arrays', 'summary') if spec['kind'] == 'direct' else ('arrays',):
                if not isinstance(result[name], dict) or not {'path', 'sha256', 'bytes'} <= result[name].keys():
                    raise ValueError('Completed job contains an unbound physical artifact')
        imports.append({**row, 'specification': spec,
            'original_result_sha256': digest(result),
            'result': _reference(result, previous, accounting, references)})
    replay = _validate_replay(previous, manifest, rows, replay_result_path, review, accounting)
    metadata = {name: _reference(read(previous / name), previous, accounting, references) for name in COPY_METADATA}
    metadata['schedule.json'] = {**metadata['schedule.json'], 'pilot_identity': digest(metadata['pilot.json']),
        'continuation_provenance': {'original_schedule_sha256': file_sha(previous / 'schedule.json'),
            'original_pilot_identity': schedule.get('pilot_identity'),
            'forecast_scope': 'Historical full-workload forecast; admission uses frozen continuation reuse contract remaining_work'}}
    source_bytes = sum(r['bytes'] for r in manifest['files'].values()) + sum((root / p).stat().st_size for p in added)
    freeze_bytes = source_bytes + dependencies['copied_bytes'] + 64_000_000
    clock = time.time() if now is None else now
    forecast = remaining_forecast(metadata['pilot.json'], rows, metadata['site-inventory.json'], metadata['causal-controls.json'],
        started + config['max_elapsed_seconds'] - clock, freeze_bytes,
        calibration_seconds_remaining=started + .75 * config['max_elapsed_seconds'] - clock)
    budget.check(forecast['required_additional_bytes'])
    bridge = {'schema': 'transmission-continuation-reuse-v1', 'policy': POLICY,
        'predecessor': str(previous), 'predecessor_source_identity': manifest['source_identity'],
        'predecessor_manifest_sha256': file_sha(previous / 'manifest.json'),
        'predecessor_ledger_sha256': file_sha(previous / 'jobs.sqlite3'),
        'predecessor_state_sha256': file_sha(previous / 'state.json'),
        'original_started_at': started, 'deadline': started + config['max_elapsed_seconds'],
        'review_sha256': file_sha(review_path), 'review': review, 'source_changes': changes,
        'added_source_files': added, 'shared_accounting_root': str(accounting),
        'referenced_artifacts': references, 'replay': replay, 'remaining_work': forecast,
        'metadata_sha256': {name:file_sha(previous / name) for name in COPY_METADATA},
        'jobs': [{'original_job_id':r['id'], 'state':r['state'], 'attempts':r['attempts'],
                  'specification_sha256':digest(r['specification']), 'result_sha256':r['original_result_sha256'],
                  'error':r['error']} for r in imports],
        'outcomes_accessed': False, 'source_key_policy': 'Only specification.source changes; original runtime identities retained'}
    return {'bridge': bridge, 'imports': imports, 'metadata': metadata, 'previous_manifest': manifest, 'previous_state': state,
            'output': str(output), 'root': str(root), 'status': 'READY_TO_PREPARE'}


def validate_imported_failure(supervisor, key, payload):
    """Verify a source-only imported failure against frozen predecessor/replay bytes."""
    manifest = supervisor.manifest
    if digest(manifest['files']) != manifest['source_identity']:
        raise ValueError('Imported failure manifest identity changed')
    record = manifest['files'][BRIDGE_KEY]
    path = ordinary(Path(supervisor.output) / record['path'])
    if file_sha(path) != record['sha256'] or path.stat().st_size != record['bytes']:
        raise ValueError('Imported failure reuse contract changed')
    bridge = read(path)
    provenance = payload.get('provenance') or {}
    replay = bridge['replay']
    original_id = provenance.get('original_job_id')
    bound = next((r for r in bridge['jobs'] if r['original_job_id'] == original_id and r['state'] == 'failed'), None)
    if (bound is None or bridge.get('schema') != 'transmission-continuation-reuse-v1' or
            provenance.get('schema') != 'transmission-imported-failure-v1' or
            provenance.get('reuse_contract_sha256') != record['sha256'] or
            provenance.get('original_source_identity') != bridge['predecessor_source_identity'] or
            provenance.get('original_attempt') != bridge['predecessor'] or original_id != replay['job_id']):
        raise ValueError('Imported failure provenance is not bound by the frozen contract')
    for name in ('result', 'manifest'):
        expected = replay[name]
        source = ordinary(expected['path'], bridge['shared_accounting_root'])
        if (provenance.get('replay_' + name + '_sha256') != expected['sha256'] or
                manifest['files']['continuation/replay-' + name] != expected or
                file_sha(source) != expected['sha256'] or source.stat().st_size != expected['bytes']):
            raise ValueError('Imported failure replay bytes changed')
    replay_result, replay_manifest = read(replay['result']['path']), read(replay['manifest']['path'])
    previous = Path(bridge['predecessor'])
    if file_sha(ordinary(previous / 'jobs.sqlite3')) != bridge['predecessor_ledger_sha256']:
        raise ValueError('Imported failure predecessor ledger changed')
    original = next((r for r in _rows(previous) if r['id'] == original_id), None)
    current = supervisor.ledger.get(key)
    if original is None or current is None:
        raise ValueError('Imported physical job is missing')
    spec = json.loads(original['specification'])
    expected_spec = {**spec, 'source': manifest['source_identity']}
    if (digest(spec) != original_id or digest(spec) != bound['specification_sha256'] or
            original['state'] != 'failed' or current['state'] != 'failed' or
            key != digest(expected_spec) or json.loads(current['specification']) != expected_spec or
            payload.get('error') != original['error'] or current['error'] != original['error'] or
            payload.get('receipt') != replay_result.get('receipt') or replay['receipt'] != payload.get('receipt') or
            payload['receipt'].get('job_id') != original_id or replay_result.get('job_id') != original_id or
            replay_result.get('execution_identity') != replay_manifest['identity'] or
            replay_manifest.get('specification') != spec):
        raise ValueError('Imported failure changed its physical specification or evidence')
    return payload['receipt']


@contextmanager
def _exclusive(path, *, existing=False):
    path = Path(path)
    if path.resolve() != path or (path.exists() and path.stat().st_nlink != 1):
        raise ValueError('Ordinary exclusive lock required')
    if existing and not path.is_file():
        raise ValueError('Predecessor supervisor lock is missing')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def prepare_continuation(root, predecessor, output, review_path, replay_result_path, *, apply=False):
    plan = inspect_continuation(root, predecessor, output, review_path, replay_result_path)
    if not apply:
        return {k:plan[k] for k in ('status', 'output', 'bridge')}
    previous, final_output = Path(predecessor).absolute(), Path(output).absolute()
    output = final_output.parent / ('.preparing-' + final_output.name + '-' + uuid.uuid4().hex)
    shared = CampaignBudget(plan['bridge']['shared_accounting_root'])
    original_status = controller.status
    original_budget = controller.CampaignBudget
    with ExitStack() as stack:
        stack.enter_context(_exclusive(shared.path('maintenance/.maintenance.lock')))
        if final_output.exists():
            raise ValueError('Final continuation output appeared before locked preparation')
        stack.enter_context(_exclusive(previous / '.supervisor.lock', existing=True))
        # The new worker cannot execute while the manifest/import transaction is incomplete.
        stack.enter_context(_exclusive(output / '.supervisor.lock'))
        # controller.prepare's status(previous) must not open the old ledger writable.
        def read_only_prior(path=controller.DEFAULT_OUTPUT):
            if Path(path).absolute() == previous:
                _no_worker(previous, plan['previous_state'])
                return {**plan['previous_state'], 'worker_alive': False}
            return original_status(path)
        class UnpublishedBudget(original_budget):
            def write_json(self, relative, value, **kwargs):
                if self.root == shared.root and str(relative) == 'active-campaign.json':
                    return {'path': str(relative), 'sha256': digest(value), 'bytes': len(canonical(value)), 'publication_deferred': True}
                return super().write_json(relative, value, **kwargs)
        controller.status = read_only_prior
        controller.CampaignBudget = UnpublishedBudget
        try:
            if (file_sha(previous / 'jobs.sqlite3') != plan['bridge']['predecessor_ledger_sha256'] or
                    file_sha(previous / 'state.json') != plan['bridge']['predecessor_state_sha256']):
                raise ValueError('Predecessor changed after inspection')
            controller.prepare(root, output, predecessor=previous)
            budget = CampaignBudget(output)
            manifest = read(output / 'manifest.json')
            manifest['output'] = str(final_output)
            old = plan['previous_manifest']
            for relative, record in old['files'].items():
                expected = plan['bridge']['source_changes'].get(relative, {}).get('after', record['sha256'])
                if manifest['files'][relative]['sha256'] != expected:
                    raise ValueError('Source changed while freezing continuation')
            for relative, sha in plan['bridge']['added_source_files'].items():
                if manifest['files'][relative]['sha256'] != sha:
                    raise ValueError('Added source changed while freezing continuation')
            if set(manifest['files']) != set(old['files']) | set(plan['bridge']['added_source_files']):
                raise ValueError('Unexpected frozen source/input inventory')
            if (manifest['frozen_dependencies']['files'] != old['frozen_dependencies']['files'] or
                    manifest['dependencies'] != old['dependencies'] or
                    manifest['frozen_dependencies'].get('host_runtime') != old['frozen_dependencies'].get('host_runtime') or
                    manifest['frozen_dependencies'].get('python_flags') != old['frozen_dependencies'].get('python_flags')):
                raise ValueError('Dependencies changed while freezing continuation')
            if read(output / 'benchmark.json') != read(previous / 'benchmark.json'):
                raise ValueError('Benchmark changed while preparing continuation')
            old_config, new_config = read(previous / 'configuration.json'), read(output / 'configuration.json')
            mutable = {'threads', 'memory_gb', 'agent_reserve_gb'}
            if ({k:v for k,v in old_config.items() if k not in mutable} !=
                    {k:v for k,v in new_config.items() if k not in mutable} or
                    not 1 <= new_config['threads'] <= old_config['threads'] or
                    not 0 < new_config['memory_gb'] <= old_config['memory_gb'] or
                    not new_config['agent_reserve_gb'] >= old_config['agent_reserve_gb']):
                raise ValueError('Prepared configuration altered scientific or resource limits')
            clock = time.time()
            plan['bridge']['remaining_work'] = remaining_forecast(plan['metadata']['pilot.json'],
                [{**r, 'specification': canonical(r['specification']).decode()} for r in plan['imports']],
                plan['metadata']['site-inventory.json'], plan['metadata']['causal-controls.json'],
                plan['bridge']['deadline'] - clock, 0,
                calibration_seconds_remaining=plan['bridge']['original_started_at'] + .75 * controller.MAX_ELAPSED_SECONDS - clock)
            budget.check(plan['bridge']['remaining_work']['required_additional_bytes'])
            for name, value in plan['metadata'].items():
                budget.write_json(name, value)
            record = budget.write_json(BRIDGE_PATH, plan['bridge'])
            manifest['files'][BRIDGE_KEY] = record
            for index, record in enumerate(plan['bridge']['referenced_artifacts'].values()):
                manifest['files']['continuation/artifact-' + str(index)] = record
            for name in ('manifest', 'result'):
                manifest['files']['continuation/replay-' + name] = plan['bridge']['replay'][name]
            manifest['source_identity'] = digest(manifest['files'])
            budget.write_json('manifest.json', manifest)
            # Source identity is final before any imported ledger key is derived.
            ledger = JobLedger(output / 'jobs.sqlite3')
            try:
                if ledger.rows():
                    raise ValueError('Continuation ledger is not empty')
                with ledger.db:
                    for row in plan['imports']:
                        spec = {**row['specification'], 'source': manifest['source_identity']}
                        key = digest(spec)
                        provenance = {'schema': 'transmission-imported-job-v1', 'original_job_id': row['id'],
                            'original_attempt': str(previous), 'original_source_identity': old['source_identity'],
                            'reuse_contract_sha256': manifest['files'][BRIDGE_KEY]['sha256']}
                        result = copy.deepcopy(row['result'])
                        if result is not None:
                            result['import_provenance'] = provenance
                        ledger.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)',
                            (key, canonical(spec).decode(), row['state'], row['attempts'], row['started'], row['finished'],
                             canonical(result).decode() if result is not None else None, row['error']))
                        if row['id'] == plan['bridge']['replay']['job_id']:
                            replay = plan['bridge']['replay']
                            provenance.update(schema='transmission-imported-failure-v1',
                                replay_manifest_sha256=replay['manifest']['sha256'], replay_result_sha256=replay['result']['sha256'])
                            budget.write_json('failures/' + key + '.json', {'error': row['error'],
                                'receipt': replay['receipt'], 'provenance': provenance})
            finally:
                ledger.close()
            state = read(output / 'state.json')
            state.update(source_identity=manifest['source_identity'], status='PREPARED', phase='continuation_prepared',
                completed_jobs=sum(r['state'] == 'complete' for r in plan['imports']))
            budget.write_json('state.json', state)
            controller.validate_frozen(output)
            if final_output.exists():
                raise ValueError('Final continuation output appeared during preparation')
            os.rename(output, final_output)
            descriptor = os.open(final_output.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            shared.write_json('active-campaign.json', {'output': str(final_output), 'source_identity': manifest['source_identity'],
                'predecessor': str(previous)})
            return {'status': 'PREPARED', 'output': str(final_output), 'source_identity': manifest['source_identity'],
                'imported_complete': state['completed_jobs'], 'imported_failed': sum(r['state'] == 'failed' for r in plan['imports']),
                'started_at': state['started_at'], 'remaining_work': plan['bridge']['remaining_work'], 'worker_launched': False}
        except BaseException as exc:
            # Keep partial bytes for inspection; make the new attempt unlaunchable.
            budget = CampaignBudget(output if output.exists() else final_output)
            budget.write_json('control.json', {'command': 'stop', 'at': time.time()}, recovery=True)
            budget.write_json('state.json', {'status': 'FAILED', 'phase': 'continuation_preparation_failed',
                'started_at': plan['bridge']['original_started_at'], 'reason': str(exc),
                'source_identity': read(budget.root / 'manifest.json').get('source_identity') if (budget.root / 'manifest.json').exists() else None}, recovery=True)
            shared.write_json('active-campaign.json', {'output': str(previous), 'source_identity': old['source_identity'] if 'old' in locals() else plan['previous_manifest']['source_identity']}, recovery=True)
            raise
        finally:
            controller.status = original_status
            controller.CampaignBudget = original_budget
