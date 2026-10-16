"""One serialized native worker, finite diagnosis, calibration and sealed scoring."""
from __future__ import annotations

from dataclasses import asdict, replace
import gc
import io
import json
from pathlib import Path
import time

import numpy as np

from .budget import digest, file_sha
from .controller import CampaignHalt, MODELS, read_json, select_schedule


def npz_bytes(**arrays):
    stream = io.BytesIO()
    np.savez_compressed(stream, **arrays)
    return stream.getvalue()


def arrays_at(output, receipt):
    path = Path(output) / receipt['path']
    if file_sha(path) != receipt['sha256']:
        raise ValueError('Cached physical result changed')
    with np.load(path, allow_pickle=False) as archive:
        return {k: archive[k].copy() for k in archive.files}


def _failure_scalar(value):
    """Keep failure evidence strict-JSON-safe without copying state arrays."""
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if np.isfinite(value) else ('NaN' if np.isnan(value) else ('Infinity' if value > 0 else '-Infinity'))
    if isinstance(value, str):
        return value[:512]
    return '<omitted ' + type(value).__name__ + '>'


class NativeNumericalFailure(ValueError):
    """Retain checked-run evidence through the controller's failure receipts."""
    def __init__(self, key, runner, part, start_step, duration, *, stage='integration'):
        from .dynamics import DEFAULTS
        engine = runner.engine
        binding = getattr(runner, 'receipt', {})
        contract = binding.get('parameter_contract', {})
        parameter_names = (*DEFAULTS, 'graded_input_cap', 'dt', 'dt_graded', 'record_dt_ms',
                           'synaptic_delay', 'graded_release', 'v_threshold', 'v_reset',
                           'voltage_min', 'voltage_max')
        parameters = dict(getattr(engine, 'parameters', {}))
        parameters.update(contract.get('parameters', {}))
        diagnostic_names = ('nonfinite_voltage_updates', 'nonfinite_synaptic_updates',
            'nonfinite_release_updates', 'invalid_delayed_spikes', 'clamps',
            'first_failure_step', 'endpoint_finite', 'simulated_population', 'pass')
        diagnostics = part.get('diagnostics', {})
        blocks = part.get('blocks', [])
        block_summary = lambda row: {name: _failure_scalar(row[name]) for name in
            ('start_step', 'stop_step', 'wall_seconds') if name in row}
        self.receipt = {
            'schema': 'transmission-native-numerical-failure-v1', 'job_id': key,
            'failure_reason': _failure_scalar(part.get('failure_reason')), 'stage': stage,
            'runtime_identity': _failure_scalar(part.get('runtime_identity', getattr(runner, 'runtime_identity', None))),
            'diagnostics': {name: _failure_scalar(diagnostics[name]) for name in diagnostic_names if name in diagnostics},
            'parameters': {name: _failure_scalar(parameters[name]) for name in parameter_names if name in parameters},
            'parameter_contract_identity': _failure_scalar(contract.get('identity')),
            'context': {name: _failure_scalar(value) for name, value in {
                'start_step': start_step, 'stop_step': engine.step, 'total_steps': runner.total_steps,
                'dt_ms': engine.dt, 'requested_duration_ms': duration,
                'simulated_ms': part.get('simulated_ms'), 'block_ms': 10.}.items()},
            'blocks': {'count': len(blocks), 'first': block_summary(blocks[0]) if blocks else None,
                       'retained': [block_summary(row) for row in blocks[-20:]],
                       'omitted_count': max(0, len(blocks) - 20)},
            'nonfinite_encoding': 'Nonfinite scalar values are strings; state and trace arrays are omitted',
        }
        for name in ('model_id', 'model_sha256', 'protocol_identity', 'source_request_sha256', 'scope'):
            if name in binding:
                self.receipt[name] = _failure_scalar(binding[name])
        # T4 bindings carry model identity in the already validated request.
        request = getattr(runner, 'request', None)
        if request is not None:
            for name in ('model_id', 'model_sha256'):
                if name not in self.receipt:
                    self.receipt[name] = _failure_scalar(getattr(request.context, name))
        super().__init__('Native numerical failure: ' + str(self.receipt['failure_reason']))


def _checkpointed_run(supervisor, key, runner, *, verify_replay=False):
    """Atomic complete physical state + accumulated selected recordings.

    At most 200 simulated ms is replayed after a crash. Completed jobs and all
    previously checkpointed samples are reused without double accumulation.
    """
    relative = 'active/' + key + '.npz'
    path = supervisor.output / relative
    traces = {'time_ms': np.empty(0), 'voltage_mv': np.empty((0, len(runner.record_indices))),
              'spike_indices': np.empty(0, np.int32), 'spike_times_ms': np.empty(0)}
    accumulated_wall = checkpoint_seconds = 0.
    checkpoint_peak_bytes = 0
    if path.exists():
        with np.load(path, allow_pickle=False) as archive:
            runner.restore_bytes(archive['checkpoint'].tobytes())
            traces = {k: archive[k].copy() for k in traces}
            accumulated_wall = float(archive['wall_seconds'])
            checkpoint_seconds = float(archive['checkpoint_seconds'])
    began = time.perf_counter()
    replay_exact = None
    while runner.engine.step < runner.total_steps:
        start_step = runner.engine.step
        duration = min(200., (runner.total_steps - runner.engine.step) * runner.engine.dt)
        replay_start = runner.checkpoint_bytes() if verify_replay and runner.engine.step + round(duration / runner.engine.dt) == runner.total_steps else None
        part = runner.run(duration, block_ms=10.)
        if not part['completed']:
            raise NativeNumericalFailure(key, runner, part, start_step, duration)
        for name in traces:
            traces[name] = np.concatenate((traces[name], part[name]))
        if replay_start is not None:
            from flybrain.paralimbo_upgrade.runtime import _state_digest
            ending = _state_digest(runner.snapshot())
            runner.restore_bytes(replay_start)
            repeated = runner.run(duration, block_ms=10.)
            if not repeated['completed']:
                raise NativeNumericalFailure(key, runner, repeated, start_step, duration, stage='checkpoint_replay')
            replay_exact = repeated['completed'] and ending == _state_digest(runner.snapshot()) and all(
                np.array_equal(part[name], repeated[name]) for name in traces)
            if not replay_exact:
                raise ValueError('Serialized native checkpoint replay differs, including diagnostics')
        then = time.perf_counter()
        payload = npz_bytes(
            checkpoint=np.frombuffer(runner.checkpoint_bytes(), dtype=np.uint8), **traces,
            wall_seconds=np.array(accumulated_wall + time.perf_counter() - began),
            checkpoint_seconds=np.array(checkpoint_seconds))
        checkpoint_peak_bytes = max(checkpoint_peak_bytes, len(payload))
        supervisor.budget.write_bytes(relative, payload)
        checkpoint_seconds += time.perf_counter() - then
    traces['root_ids'] = np.array(runner.root_ids)[runner.record_indices]
    return traces, {'wall_seconds': accumulated_wall + time.perf_counter() - began,
                    'checkpoint_seconds': checkpoint_seconds, 'checkpoint_path': relative,
                    'checkpoint_peak_bytes': checkpoint_peak_bytes,
                    'serialized_checkpoint_replay_exact': replay_exact}


class NativeWorker:
    def __init__(self, supervisor):
        from .runtime import FrozenModelCache
        self.s = supervisor
        self.cache = FrozenModelCache(supervisor.frozen_root)
        self._outgoing = {}

    def reachable(self, arm, source_index):
        from scipy.sparse.csgraph import breadth_first_order
        if arm not in self._outgoing:
            network = self.network(arm)
            self._outgoing[arm] = (network['graded'] + network['spiking']).transpose().tocsr()
            self._outgoing[arm].eliminate_zeros()
        indices = breadth_first_order(self._outgoing[arm], source_index, directed=True, return_predecessors=False)
        mask = np.zeros(self._outgoing[arm].shape[0], dtype=bool)
        mask[indices] = True
        return mask

    def network(self, arm):
        return self.cache.get(*MODELS[arm], admission=self.s.admission)

    def direct(self, arm, protocol, parameters=None, *, retain_arrays=True):
        from .runtime import build_direct_runner
        from .calibration import DEFAULTS
        specification = {'kind': 'direct', 'model': MODELS[arm], 'parameters': parameters or DEFAULTS,
                         'protocol': asdict(protocol), 'source': self.s.manifest['source_identity']}
        def compute(key):
            then = time.perf_counter()
            runner = build_direct_runner(self.s.frozen_root, *MODELS[arm], protocol,
                                        parameters=parameters, threads=self.s.state['threads'],
                                        admission=self.s.admission, model_cache=self.cache)
            startup = time.perf_counter() - then
            trace, timing = _checkpointed_run(self.s, key, runner, verify_replay=protocol.label.startswith('instrumented-pilot'))
            full = runner.summary()
            arrays = {name: value for name, value in full.items() if isinstance(value, np.ndarray)}
            arrays['population_root_ids'] = arrays.pop('root_ids')
            summary = {name: value for name, value in full.items() if not isinstance(value, np.ndarray)}
            trace_receipt = self.s.budget.write_bytes('cache/results/' + key + '.npz', npz_bytes(**trace, **arrays))
            receipt = self.s.budget.write_json('diagnostics/' + key + '.json', summary)
            result = {'status': 'PASS', 'arrays': trace_receipt, 'summary': receipt,
                      'runtime_identity': runner.runtime_identity, 'startup_seconds': startup,
                      'population': runner.engine.n_neurons, **timing}
            self.s.budget.path(timing['checkpoint_path']).unlink(missing_ok=True)
            del runner
            gc.collect()
            return result
        return self.s.run_job(specification, compute)

    def t4(self, arm, protocol, case_id, parameters, multiplier, *, dt_ms=.1,
           sensitivity='primary', optical=False):
        from .data import build_t4_request
        from .runtime import build_t4_runner
        from flybrain.paralimbo_upgrade.observation import observe_trace
        request = build_t4_request(protocol, MODELS[arm][0], case_id,
                                   input_multiplier=multiplier, sensitivity_id=sensitivity,
                                   runtime_root=self.s.frozen_root,
                                   dt_ms=dt_ms, refinement='optical' if optical else None)
        request = replace(request, threads=self.s.config['threads'])
        physical_request = request.bindings()
        physical_request.pop('threads', None)
        specification = {'kind': 'native_t4', 'model': MODELS[arm], 'parameters': parameters,
                         'physical_request_sha256': digest(physical_request), 'multiplier': multiplier,
                         'source': self.s.manifest['source_identity']}
        def compute(key):
            then = time.perf_counter()
            runner = build_t4_runner(self.s.frozen_root, request, parameters=parameters,
                                     admission=self.s.admission, model_cache=self.cache)
            startup = time.perf_counter() - then
            trace, timing = _checkpointed_run(self.s, key, runner)
            measured = observe_trace(trace['time_ms'] + request.physical_origin_ms,
                {'voltage_mv': trace['voltage_mv']}, trace['root_ids'], request.observation,
                request.sample_time_ms, source_units='mV', event_onset_ms=request.event_onset_ms)
            refined_spec = replace(request.observation, filter_spec={**request.observation.filter_spec,
                'step_ms': request.observation.filter_spec['step_ms'] / 2.})
            refined_observation = observe_trace(trace['time_ms'] + request.physical_origin_ms,
                {'voltage_mv': trace['voltage_mv']}, trace['root_ids'], refined_spec,
                request.sample_time_ms, source_units='mV', event_onset_ms=request.event_onset_ms)
            observation_error = float(np.max(np.abs(measured['values'] - refined_observation['values'])))
            receipt = self.s.budget.write_bytes('cache/results/' + key + '.npz', npz_bytes(
                **trace, observation_time_ms=measured['time_ms'], observation_values_mv=measured['values'],
                refined_observation_values_mv=refined_observation['values'],
                final_voltage_mv=runner.engine.v, final_synaptic_mv=runner.engine.g))
            summary = runner.summary(include_arrays=False)
            self.s.budget.write_json('diagnostics/' + key + '.json', summary)
            result = {'status': 'PASS', 'arrays': receipt, 'request_sha256': request.digest,
                      'runtime_identity': runner.runtime_identity, 'startup_seconds': startup,
                      'population': runner.engine.n_neurons, 'dt_ms': dt_ms,
                      'physical_duration_ms': request.duration_ms, 'numerics': runner.diagnostics(), **timing}
            result['observation_refinement_max_abs_mv'] = observation_error
            self.s.budget.path(timing['checkpoint_path']).unlink(missing_ok=True)
            del runner
            gc.collect()
            return result
        return self.s.run_job(specification, compute)


def _require(result):
    if result.get('status') != 'PASS':
        raise ValueError('Required finite native experiment failed: ' + str(result.get('error')))
    return result


def pilot(worker, inventory, protocol):
    from .runtime import DirectProtocol, DirectPulse
    s = worker.s
    roots = tuple(row['root_id'] for row in inventory['sites'])
    records = []
    _require(worker.direct('paralimbo', DirectProtocol(10., (DirectPulse(roots, 0., 10., 10.),),
        recording_roots=roots, label='outcome-blind-kernel-warmup')))
    for arm in MODELS:
        for label, amplitude in (('quiet', 0.), ('active', 10.)):
            direct_protocol = DirectProtocol(1000., (DirectPulse(roots, 0., 100., amplitude),),
                                             recording_roots=roots, label='instrumented-pilot-' + label)
            result = _require(worker.direct(arm, direct_protocol))
            records.append({'arm': arm, 'condition': label, **result})
    from .calibration import DEFAULTS
    case_id = protocol['development_case_ids'][0]
    t4_records = []
    for arm in MODELS:
        ordinary = _require(worker.t4(arm, protocol, case_id, DEFAULTS, 1.))
        refined = _require(worker.t4(arm, protocol, case_id, DEFAULTS, 1., dt_ms=.05))
        optical = _require(worker.t4(arm, protocol, case_id, DEFAULTS, 1., optical=True))
        a, b, c = [arrays_at(s.output, r['arrays'])['observation_values_mv'] for r in (ordinary, refined, optical)]
        errors = {'timestep_mv': float(np.max(np.abs(a - b))), 'optical_mv': float(np.max(np.abs(a - c))),
                  'observation_mv': ordinary['observation_refinement_max_abs_mv']}
        if max(errors.values()) > .001:
            raise ValueError('Input-only native T4 pilot numerical qualification failed: ' + str(errors))
        t4_records.append({'arm': arm, 'case_id': case_id, 'qualification': errors, 'result': ordinary,
                           'refined': refined, 'optical': optical})
    rates = {label: max(r['wall_seconds'] for r in records if r['condition'] == label) for label in ('quiet', 'active')}
    rates['active'] = max(rates['active'], max(r['result']['wall_seconds'] / (r['result']['physical_duration_ms'] / 1000.) for r in t4_records))
    result = {'quiet_seconds_per_simulated_second': rates['quiet'],
              'active_seconds_per_simulated_second': rates['active'],
              'startup_seconds': max([r['startup_seconds'] for r in records] + [r['result']['startup_seconds'] for r in t4_records]),
              'maximum_case_seconds': 2., 'records': records,
              'direct_retained_bytes': max(r['arrays']['bytes'] + r['summary']['bytes'] for r in records),
              't4_retained_bytes_bound': 8_000_000,
              'checkpoint_peak_bytes': max(r['checkpoint_peak_bytes'] for r in records),
              'native_t4_input_only_pilots': t4_records,
              'population': 175401, 'threads': s.state['threads'], 'instrumented': True}
    s.budget.write_json('pilot.json', result)
    return result


def diagnose(worker, inventory, targets):
    from .runtime import DirectProtocol, DirectPulse
    from .instrumentation import STAT_NAMES, COUNT_NAMES
    s = worker.s
    rows = []
    for site in inventory['sites']:
        source = site['root_id']
        downstream = targets[source]['rescue_root_id']
        recordings = tuple(dict.fromkeys([source] + ([downstream] if downstream else [])))
        for arm in MODELS:
            actual = worker.network(arm)['neurons'].iloc[site['index']]
            if str(actual.root_id) != source:
                raise ValueError('Arm neuron order differs from frozen inventory')
            arm_mode = 'graded' if bool(actual.is_graded) else 'spiking'
            results = {}
            for amplitude in (0., 5., 10., -5.):
                protocol = DirectProtocol(1000., (DirectPulse((source,), 0., 100., amplitude),),
                    recording_roots=recordings, label='matched-site-probe')
                results[str(amplitude)] = worker.direct(arm, protocol)
            controls = {}
            if downstream:
                for kind in ('silencing', 'rescue'):
                    pulses = [DirectPulse((source,), 0., 100., 10.)]
                    if kind == 'rescue':
                        pulses.append(DirectPulse((downstream,), 0., 100., 10.))
                    protocol = DirectProtocol(1000., tuple(pulses), recording_roots=recordings,
                        silenced_roots=(source,), label='preselected-' + kind)
                    controls[kind] = worker.direct(arm, protocol)
            row = {'source': source, 'arm': arm, 'arm_mode': arm_mode, 'site': site, 'anatomical_control': targets[source],
                   'probes': results, 'causal_controls': controls, 'mechanisms': [],
                   'causal_attribution': 'UNESTABLISHED', 'mode_reassignment': 'NONE'}
            if not downstream:
                row['mechanisms'].append('missing_direct_anatomical_route')
            if all(r['status'] == 'PASS' for r in results.values()):
                base = arrays_at(s.output, results['0.0']['arrays'])
                quiet_drift = float(np.max(base['stats'][:, 0]))
                if quiet_drift > .001:
                    row['mechanisms'].append('QUIET_DRIFT_EXCEEDS_NUMERICAL_TOLERANCE')
                    row['classification_status'] = 'AMBIGUOUS_BACKGROUND_DRIFT'
                    rows.append(row)
                    continue
                row['quiet_max_drift_mv'] = quiet_drift
                reachable = worker.reachable(arm, site['index'])
                modes = worker.network(arm)['neurons'].is_graded.to_numpy()
                classifications = {}
                for amplitude in ('5.0', '10.0', '-5.0'):
                    probe = arrays_at(s.output, results[amplitude]['arrays'])
                    delta = probe['stats'] - base['stats']
                    positive = delta[:, 3] + delta[:, 5]
                    negative = delta[:, 4] + delta[:, 6]
                    drive_present = np.abs(positive) + np.abs(negative) > .001
                    spikes = probe['counts'][:, 3] - base['counts'][:, 3]
                    response = probe['stats'][:, 0] >= .001
                    codes = np.zeros(len(reachable), np.uint16)
                    flags = {
                        'missing_anatomical_route': (~reachable, 1),
                        'absent_detectable_synaptic_drive': (reachable & ~drive_present, 2),
                        'threshold_gating': (reachable & ~modes & drive_present & (spikes == 0), 4),
                        'inhibition_or_cancellation': (drive_present & (negative < -.001) &
                            (positive + negative < .1 * (np.abs(positive) + np.abs(negative))), 8),
                        'gain_attenuation': (drive_present & (probe['cap_scale'] < 1.), 16),
                        'refractory_rejection': (probe['counts'][:, 5] > base['counts'][:, 5], 32),
                        'late_response_duration_limit': (probe['first_steps'][:, 0] * .1 >= 900., 64),
                        'display_filtering': (response & (probe['stats'][:, 0] < .1), 128),
                        'absent_output_change': (drive_present & np.where(modes, np.abs(delta[:, 10]) < .001, spikes == 0), 256)}
                    for mask, bit in flags.values():
                        codes[mask] |= bit
                    receipt = s.budget.write_bytes('classifications/' + arm + '-' + source + '-' + amplitude + '.npz',
                        npz_bytes(codes=codes, anatomical_reachable=reachable,
                                  root_order_sha256=np.array(digest(probe['population_root_ids'].tolist()))))
                    classifications[amplitude] = {'arrays': receipt, 'flags': {name: bit for name, (_, bit) in flags.items()},
                        'counts': {name: int(mask.sum()) for name, (mask, _) in flags.items()},
                        'interpretation': 'Mechanism-consistent flags; causal attribution requires paired interventions. Negative drive and attenuation are not automatically defects.'}
                row['whole_graph_classification'] = classifications
                driven = arrays_at(s.output, results['10.0']['arrays'])
                i = site['index']
                stats, counts = driven['stats'], driven['counts']
                peak = float(np.max(np.abs(driven['voltage_mv'][:, 0] - base['voltage_mv'][:, 0])))
                row['source_control_subtracted_peak_mv'] = peak
                if peak < .001:
                    row['mechanisms'].append('absent_detectable_input_response')
                elif arm_mode == 'spiking' and counts[i, COUNT_NAMES.index('spikes')] == 0:
                    row['mechanisms'].append('threshold_gating')
                if stats[i, STAT_NAMES.index('spike_negative_forcing_mv')] + stats[i, STAT_NAMES.index('graded_negative_forcing_mv')] < 0:
                    row['mechanisms'].append('inhibitory_drive_present_not_causally_attributed')
                if counts[i, COUNT_NAMES.index('rejected_refractory_spike_edges')] > 0:
                    row['mechanisms'].append('refractory_rejection')
                if driven['cap_scale'][i] < 1:
                    row['mechanisms'].append('gain_attenuation')
                if .001 <= peak < .1:
                    row['mechanisms'].append('would_be_hidden_by_0.1mV_display_threshold')
                if downstream and all(r['status'] == 'PASS' for r in controls.values()):
                    silent = arrays_at(s.output, controls['silencing']['arrays'])
                    rescue = arrays_at(s.output, controls['rescue']['arrays'])
                    upstream_effect = float(np.max(np.abs(driven['voltage_mv'][:, 1] - silent['voltage_mv'][:, 1])))
                    rescue_effect = float(np.max(np.abs(rescue['voltage_mv'][:, 1] - silent['voltage_mv'][:, 1])))
                    row['silencing_effect_mv'] = upstream_effect
                    row['rescue_effect_mv'] = rescue_effect
                    row['causal_attribution'] = ('SOURCE_OUTPUT_CONTRIBUTES_TO_TARGET' if upstream_effect > .001 and rescue_effect > .001
                                                else 'UNESTABLISHED')
                row['duration_limit'] = 'Responses beyond the fixed 900ms follow-up are untested; not classified as absent.'
            else:
                row['mechanisms'].append('NUMERICAL_OR_EXECUTION_FAILURE')
            rows.append(row)
            s.budget.write_json('transmission-diagnosis.json', {'status': 'IN_PROGRESS', 'sites_completed': len(rows), 'rows': rows})
    s.budget.write_json('transmission-diagnosis.json', {'status': 'COMPLETE', 'rows': rows,
        'correction_outcome': 'No automatic equations or cell-mode edits. Unresolved assignments remain hypotheses.',
        'classification_limit': 'All-neuron reachability and measured-drive flags; causal counterfactuals on longer paths and longer durations remain untested.'})


def _sensitivity_rejection(s, result, parameters):
    """Admit only a retained finite-state voltage-clamp rejection as unknown.

    This never makes a trajectory numerically valid. Defaults/refinement do not
    use this path. Infrastructure faults, nonfinite states, delay corruption and
    checkpoint replay failures still stop the campaign.
    """
    from .calibration import DEFAULTS
    key = result.get('job_id')
    if result.get('status') != 'FAILED' or not isinstance(key, str) or len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
        raise ValueError('Unclassified sensitivity failure remains fatal')
    row = s.ledger.get(key)
    if row is None or row['state'] != 'failed':
        raise ValueError('Sensitivity failure must remain failed in the durable ledger')
    specification = json.loads(row['specification'])
    if digest(specification) != key or specification.get('parameters') != parameters:
        raise ValueError('Sensitivity failure physical identity differs')
    path = s.output / 'failures' / (key + '.json')
    if not path.is_file() or path.resolve() != path or path.stat().st_nlink != 1:
        raise ValueError('Sensitivity failure requires an ordinary retained numerical receipt')
    payload = read_json(path)
    if payload.get('provenance'):
        from .continuation import validate_imported_failure
        receipt = validate_imported_failure(s, key, payload)
    else:
        receipt = payload.get('receipt', {})
        if receipt.get('job_id') != key:
            raise ValueError('Sensitivity failure receipt names another job')
    diagnostics = receipt.get('diagnostics', {})
    counts = ('nonfinite_voltage_updates', 'nonfinite_synaptic_updates',
              'nonfinite_release_updates', 'invalid_delayed_spikes')
    if (receipt.get('schema') != 'transmission-native-numerical-failure-v1' or
            receipt.get('failure_reason') != 'COMPILED_STATE_CHECK_FAILED' or
            receipt.get('stage') != 'integration' or not receipt.get('runtime_identity') or
            diagnostics.get('pass') is not False or diagnostics.get('endpoint_finite') is not True or
            diagnostics.get('simulated_population') != 175401 or
            type(diagnostics.get('clamps')) is not int or diagnostics['clamps'] <= 0 or
            type(diagnostics.get('first_failure_step')) is not int or diagnostics['first_failure_step'] < 0 or
            any(type(diagnostics.get(k)) is not int or diagnostics[k] != 0 for k in counts) or
            any(receipt.get('parameters', {}).get(k) != parameters[k] for k in DEFAULTS) or
            receipt.get('model_id') != specification['model'][0] or
            receipt.get('model_sha256') != specification['model'][1]):
        raise ValueError('Sensitivity failure is not a verified finite-state voltage-clamp rejection')
    return {'status': 'FAILED', 'effect': 'UNKNOWN', 'job_id': key,
            'reason': 'zero-clamp numerical admission requirement rejected this nondefault trajectory',
            'failure_receipt': {'path': str(path.relative_to(s.output)), 'sha256': file_sha(path)},
            'diagnostics': diagnostics, 'provenance': payload.get('provenance')}


def sensitivity(worker, protocol):
    from .calibration import DEFAULTS, BOUNDS, sensitivity_pruning
    s = worker.s
    changes, details, failures, uncertain = {}, [], [], set()
    refinement_error = 0.
    for arm in MODELS:
        changes[arm] = {name: 0. for name in BOUNDS}
        for case in protocol['development_case_ids']:
            baseline = _require(worker.t4(arm, protocol, case, DEFAULTS, 1.))
            base = arrays_at(s.output, baseline['arrays'])
            refined = _require(worker.t4(arm, protocol, case, DEFAULTS, 1., dt_ms=.05))
            fine = arrays_at(s.output, refined['arrays'])
            discrepancy = float(np.max(np.abs(base['observation_values_mv'] - fine['observation_values_mv'])))
            refinement_error = max(refinement_error, discrepancy)
            if discrepancy > .001:
                raise ValueError('Default timestep refinement failed before outcome access')
            for name, bounds in BOUNDS.items():
                for value in bounds:
                    parameters = dict(DEFAULTS, **{name: value})
                    result = worker.t4(arm, protocol, case, parameters, 1.)
                    if result.get('status') != 'PASS':
                        failure = _sensitivity_rejection(s, result, parameters)
                        row = {'arm': arm, 'case_id': case, 'parameter': name, 'value': value,
                               'max_change_mv': None, 'failure': failure, 'result': result}
                        details.append(row); failures.append(row); uncertain.add(name)
                        continue
                    altered = arrays_at(s.output, result['arrays'])
                    delta = max(float(np.max(np.abs(altered[field] - base[field]))) for field in
                                ('observation_values_mv', 'final_voltage_mv', 'final_synaptic_mv'))
                    changes[arm][name] = max(changes[arm][name], delta)
                    details.append({'arm': arm, 'case_id': case, 'parameter': name, 'value': value,
                                    'max_change_mv': delta, 'result': result})
        # A pooled active engineering probe additionally covers all64 frozen
        # anatomical/mode sites without touching biological response arrays.
        from .runtime import DirectProtocol, DirectPulse
        roots = tuple(r['root_id'] for r in read_json(s.output / 'site-inventory.json')['sites'])
        probe = DirectProtocol(1000., (DirectPulse(roots, 0., 100., 10.),), recording_roots=roots,
                               label='sensitivity-active-coverage')
        base = arrays_at(s.output, _require(worker.direct(arm, probe, DEFAULTS))['arrays'])
        for name, bounds in BOUNDS.items():
            for value in bounds:
                parameters = dict(DEFAULTS, **{name: value})
                trial = worker.direct(arm, probe, parameters)
                if trial.get('status') != 'PASS':
                    failure = _sensitivity_rejection(s, trial, parameters)
                    row = {'arm': arm, 'probe': '64-site-active', 'parameter': name, 'value': value,
                           'max_change_mv': None, 'failure': failure, 'result': trial}
                    details.append(row); failures.append(row); uncertain.add(name)
                    continue
                altered = arrays_at(s.output, trial['arrays'])
                delta = float(np.max(np.abs(altered['voltage_mv'] - base['voltage_mv'])))
                changes[arm][name] = max(changes[arm][name], delta)
                details.append({'arm': arm, 'probe': '64-site-active', 'parameter': name,
                                'value': value, 'max_change_mv': delta})
    result = sensitivity_pruning(changes, refinement_error)
    result['measured_max_change_mv'] = dict(result['parameter_max_change_mv'])
    result['active_parameters'] = sorted(set(result['active_parameters']) | uncertain)
    result['inactive_parameters'] = sorted(set(result['inactive_parameters']) - uncertain)
    for name in uncertain:
        result['parameter_max_change_mv'][name] = None
    result['uncertain_parameters'] = sorted(uncertain)
    result['failed_probes'] = failures
    result['policy'] = 'failure-aware-sensitivity-v1'
    result['rule'] += '; unknown finite-state clamp effects keep the dimension active for both arms'
    result['measured_maximum_scope'] = 'Valid probes only; a lower bound when a required probe was rejected'
    result['measurements'] = details
    result['input_case_ids'] = protocol['development_case_ids']
    result['coverage'] = 'All five development input conditions plus64-site active probe; no biological outcomes'
    result['outcomes_accessed'] = False
    from ..paralimbo_upgrade.interfaces import identity
    result['sensitivity_sha256'] = identity({k: v for k, v in result.items() if k != 'sensitivity_sha256'})
    s.budget.write_json('sensitivity.json', result)
    return result


def training_score(worker, protocol, arm, parameters, multiplier, observations):
    from .scoring import balanced_error
    results, scores = {}, []
    for case in protocol['development_case_ids']:
        result = worker.t4(arm, protocol, case, parameters, multiplier)
        results[case] = result
        row = {'case_id': case, 'status': result['status']}
        if result['status'] == 'PASS':
            arrays = arrays_at(worker.s.output, result['arrays'])
            obs = observations[case]
            if not np.array_equal(arrays['observation_time_ms'], obs['time_ms']):
                raise ValueError('Development observation grid mismatch')
            selected = obs['time_ms'] >= 0
            row.update(prediction=arrays['observation_values_mv'][selected], observation=obs['values_mv'][selected])
        scores.append(row)
    score = balanced_error(scores, protocol['development_case_ids'])
    return {'status': 'PASS' if score['status'] == 'SCORED' else 'FAILED',
            'split': 'development', 'balanced_training_mse': score['balanced_mse'],
            'case_ids': list(protocol['development_case_ids']), 'predictions': results}


def evaluate(worker, protocol, selections, multiplier, *, sensitivity_id='primary', directory='predictions'):
    from .scoring import seal_predictions
    s = worker.s
    records = []
    all_cases = protocol['development_case_ids'] + protocol['evaluation_case_ids']
    for arm in MODELS:
        winner = selections[arm]['selected']
        for case in all_cases:
            key = arm + ':' + case
            row = {'key': key, 'arm': arm, 'case_id': case, 'status': 'FAILED',
                   'selection_sha256': selections[arm]['selection_sha256'], 'input_multiplier': multiplier,
                   'sensitivity_id': sensitivity_id}
            if winner is None:
                row['reason'] = 'No complete successful development candidate'
                records.append(row)
                continue
            parameters = winner['parameters']
            result = worker.t4(arm, protocol, case, parameters, multiplier, sensitivity=sensitivity_id)
            refined = worker.t4(arm, protocol, case, parameters, multiplier, dt_ms=.05, sensitivity=sensitivity_id)
            optical = worker.t4(arm, protocol, case, parameters, multiplier, sensitivity=sensitivity_id, optical=True)
            row.update(parameters=parameters, model=list(MODELS[arm]), results=[result, refined, optical])
            if all(r['status'] == 'PASS' for r in (result, refined, optical)):
                coarse, fine, opt = [arrays_at(s.output, r['arrays']) for r in (result, refined, optical)]
                errors = {'timestep_max_abs_mv': float(np.max(np.abs(coarse['observation_values_mv'] - fine['observation_values_mv']))),
                          'optical_max_abs_mv': float(np.max(np.abs(coarse['observation_values_mv'] - opt['observation_values_mv']))),
                          'observation_max_abs_mv': result['observation_refinement_max_abs_mv']}
                row['qualification'] = errors
                if max(errors.values()) <= .001:
                    relative = key.replace(':', '_') + '.npz'
                    s.budget.write_bytes(directory + '/' + relative, npz_bytes(
                        time_ms=coarse['observation_time_ms'], values_mv=coarse['observation_values_mv']))
                    row.update(status='PASS', path=relative)
                else:
                    row['reason'] = 'Numerical refinement exceeded 0.001mV'
            else:
                row['reason'] = 'Native prediction or refinement failed'
            records.append(row)
    s.budget.check(2_000_000)
    return seal_predictions(s.output / directory, protocol['protocol_sha256'], [r['key'] for r in records], records)


def execute(s):
    from .runtime import campaign_admission
    from .inventory import site_inventory, causal_targets
    from .data import load_development_observations, load_evaluation_observations, input_specs, activate_frozen_inputs, retain_observations
    from .calibration import candidate_schedule, select_shared_input_multiplier, select_candidate, DEFAULTS
    from .scoring import score_sealed_predictions, independently_verify
    from .integrity import write_once_json, seal_scientific_plan
    benchmark = read_json(s.output / 'benchmark.json')
    if benchmark['benchmark_id'] != 'native_t4':
        raise ValueError('Downstream registration requires a separately frozen supported observation execution contract')
    protocol = benchmark['t4_protocol']
    activate_frozen_inputs(protocol, s.frozen_root)
    with campaign_admission(s.admission):
        worker = NativeWorker(s)
        s.save(phase='input_inventory')
        network = worker.network('paralimbo')
        inventory = site_inventory(network['neurons'])
        targets = causal_targets(network, inventory)
        s.budget.write_json('site-inventory.json', inventory)
        s.budget.write_json('causal-controls.json', targets)
        s.save(phase='instrumented_pilots')
        measured = read_json(s.output / 'pilot.json') if (s.output / 'pilot.json').exists() else pilot(worker, inventory, protocol)
        from .data import build_t4_request
        maximum_case = max(build_t4_request(protocol, MODELS['banc'][0], case,
            runtime_root=s.frozen_root).duration_ms / 1000. for case in
            protocol['development_case_ids'] + protocol['evaluation_case_ids'])
        if maximum_case > measured['maximum_case_seconds']:
            measured['maximum_case_seconds'] = maximum_case
            s.budget.write_json('pilot.json', measured)
        schedule_path = s.output / 'schedule.json'
        if schedule_path.exists():
            schedule = read_json(schedule_path)
        else:
            schedule = select_schedule(measured, s.config['max_elapsed_seconds'] - (time.time() - s.state['started_at']),
                                       storage_available_bytes=s.budget.snapshot()['available_bytes'])
            s.budget.write_json('schedule.json', schedule)
        if schedule['status'] != 'FROZEN':
            raise CampaignHalt('RESOURCE_LIMIT', schedule['reason'])
        s.save(phase='transmission_diagnosis', forecast_seconds=schedule['forecast_seconds'],
               measured_seconds_per_simulated_second=max(measured[k] for k in
                  ('quiet_seconds_per_simulated_second', 'active_seconds_per_simulated_second')))
        diagnose(worker, inventory, targets)
        s.save(phase='outcome_blind_sensitivity')
        sens = read_json(s.output / 'sensitivity.json') if (s.output / 'sensitivity.json').exists() else sensitivity(worker, protocol)
        schedules = {arm: candidate_schedule(arm, schedule['proposals_per_arm'], sens['active_parameters']) for arm in MODELS}
        write_once_json(s.budget, 'calibration-schedules.json', schedules)
        seal_scientific_plan(s.budget)
        if time.time() - s.state['started_at'] > .75 * s.config['max_elapsed_seconds']:
            raise CampaignHalt('RESOURCE_LIMIT', 'Evaluation/verification reserve reached before calibration')
        s.save(phase='development_input_calibration')
        retain_observations(protocol, 'development', s.budget)
        development = load_development_observations(protocol, retained_root=s.output)
        input_rows = []
        for index, multiplier in enumerate((1., .5, 2.)):
            for arm in MODELS:
                row = training_score(worker, protocol, arm, DEFAULTS, multiplier, development)
                input_rows.append(dict(row, proposal_index=index, multiplier=multiplier, arm=arm))
        shared = select_shared_input_multiplier(input_rows, expected_training_case_ids=protocol['development_case_ids'])
        write_once_json(s.budget, 'input-selection.json', shared)
        if shared['shared_multiplier'] is None:
            raise ValueError('No paired successful development input multiplier')
        multiplier = shared['shared_multiplier']
        selections = {}
        s.save(phase='intrinsic_calibration')
        rows_by_arm = {arm: [] for arm in MODELS}
        for index in range(len(schedules['banc']['proposals'])):
            for arm in MODELS:
                parameters = schedules[arm]['proposals'][index]
                if time.time() - s.state['started_at'] > .75 * s.config['max_elapsed_seconds']:
                    raise CampaignHalt('RESOURCE_LIMIT', 'Reserved evaluation/verification time reached')
                row = training_score(worker, protocol, arm, parameters, multiplier, development)
                rows_by_arm[arm].append(dict(row, proposal_index=index, parameters=parameters))
                s.budget.write_json('calibration/' + arm + '.json', {'attempts': rows_by_arm[arm]})
        for arm in MODELS:
            selections[arm] = select_candidate(rows_by_arm[arm], protocol['development_case_ids'])
        write_once_json(s.budget, 'selected-candidates.json', selections)
        s.save(phase='sealed_evaluation_prediction')
        seal = evaluate(worker, protocol, selections, multiplier)
        retain_observations(protocol, 'evaluation', s.budget, seal=seal, prediction_dir=s.output / 'predictions')
        evaluation = load_evaluation_observations(protocol, seal, s.output / 'predictions', retained_root=s.output)
        observations = dict(development, **evaluation)
        cases = input_specs(protocol, 'development') + input_specs(protocol, 'evaluation')
        scores = score_sealed_predictions(seal, s.output / 'predictions', observations, cases)
        s.budget.write_json('scores.json', scores)
        # The alternate correspondence never enters candidate/input selection.
        s.save(phase='t4d_correspondence_sensitivity')
        alternate = evaluate(worker, protocol, selections, multiplier,
                             sensitivity_id='alternate_vertical_subtype', directory='predictions-t4d')
        alternate_scores = score_sealed_predictions(alternate, s.output / 'predictions-t4d', observations, cases)
        s.budget.write_json('scores-t4d.json', alternate_scores)
        s.save(phase='independent_verification')
        independent = independently_verify(s.output)
        s.budget.write_json('verification.json', independent)
        candidate = {'schema': 'transmission-experimental-model-v1', 'status': 'EXPERIMENTAL',
                     'base_model': MODELS['paralimbo'], 'selection': selections['paralimbo'],
                     'input_multiplier': multiplier, 'source_identity': s.manifest['source_identity'],
                     'evidence': scores, 'default_changed': False, 'published_claims_changed': False}
        candidate['model_identity'] = digest(candidate)
        s.budget.write_json('experimental-model.json', candidate)
        failed = [row for row in s.ledger.rows() if row['state'] == 'failed']
        s.budget.write_json('comparison.json', {
            'engineering_correctness': {'status': 'PASS' if independent['pass'] and not failed and
                                         seal['status'] == alternate['status'] == 'COMPLETE' else 'INCOMPLETE',
                                        'failed_jobs': [r['id'] for r in failed]},
            'predictive_comparison': scores,
            'biological_evidence_status': {'primary': benchmark['primary_gate'],
                'fallback': 'One-cell retrospective T4 evidence; downstream recruitment and animal generalization unestablished'},
            'correspondence_sensitivity': alternate_scores, 'independent_verification': independent})
