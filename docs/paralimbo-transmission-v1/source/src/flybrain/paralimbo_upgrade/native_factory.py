"""Gated full-graph construction; no campaign, fitting or scoring entry point.

The coordinator supplies complete science contracts and a content-bound review
receipt. The factory requires the *live* area-06 full_graph context before any
file read, native load or construction. It prepares only the explicitly reviewed
quiescent hypothesis, retaining failure receipts. No native run is authorized by
importing this module, by a tiny wiring test, or by a serialized admission record.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

import numpy as np
from scipy import sparse

from . import dynamics, inputs, observation, resources
from .interfaces import INTERFACE_VERSION, DynamicsVariant, EvaluationSpec, ObservationSpec, Registration, identity
from .runtime import CheckedRunner, _state_digest
from .registrations.factories import graph_identity
from ..config import parameters
from ..hybrid_engine import HybridEngine
from ..experiment_session import snapshot_state
from ..model_registry import load_model_network
from ..neural_baseline import complete_residual, initialize_equilibrium

PRIMARY_ROOT = Path(__file__).resolve().parents[3]
GROUP_ID = '6102c51b265d4235bbe2aebd5ffcd74b'
FACTORY_SCHEMA = 'paralimbo-native-factory-v1'
REVIEW_SCHEMA = 'paralimbo-native-science-review-v1'
PREPARATION_SCHEMA = 'paralimbo-native-preparation-plan-v1'
ASSET_NAMES = ('neurons.parquet', 'graded_data.npy', 'graded_indices.npy', 'graded_indptr.npy',
               'spiking_data.npy', 'spiking_indices.npy', 'spiking_indptr.npy')
EVIDENCE_PURPOSES = frozenset({'anatomy', 'physiology', 'sensory_input', 'observation', 'preparation', 'evaluation_schedule'})
NATIVE_EVIDENCE_CLASSES = frozenset({'measured', 'independently_supported', 'transferred',
                                    'development_estimated', 'assumed'})


class NativeFactoryError(ValueError):
    """Structured refusal/failure; callers retain this through their budget writer."""
    def __init__(self, code, reason, *, receipt=None):
        self.code = code
        self.receipt = copy.deepcopy(receipt or {})
        super().__init__(f'{code}: {reason}')


def _refuse(code, reason, *, receipt=None):
    raise NativeFactoryError(code, reason, receipt=receipt)


def _sha(value, name):
    if not isinstance(value, str) or re.fullmatch('[a-f0-9]{64}', value) is None or len(set(value)) < 2:
        _refuse('IDENTITY_REQUIRED', name + ' requires a non-placeholder SHA-256')
    return value


def _evidence_tree(value):
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in {'evidence_class', 'classification'}:
                if not isinstance(item, str) or item not in NATIVE_EVIDENCE_CLASSES:
                    _refuse('UNSUPPORTED_SCIENCE', 'Native evidence classification must be an explicit allowed string')
            if isinstance(key, str) and (key.endswith('_sha256') or key.endswith('_digest') or key == 'assignment_identity'):
                _sha(item, key)
            _evidence_tree(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _evidence_tree(item)


@dataclass(frozen=True)
class NativeFactoryRequest:
    """Input-only contracts; no paths to training or evaluation responses."""
    case_id: str
    workload_name: str
    anatomy_registration: Registration
    sensory_registration: Registration
    physiology_registration: Registration
    context: inputs.InputRuntimeContext
    movie: inputs.NativeMovie
    variant: DynamicsVariant
    observation: ObservationSpec
    evaluation: EvaluationSpec
    schedule: tuple[resources.Workload, ...]
    preparation_plan: Mapping
    source_parameters_sha256: str
    dt_ms: float
    record_dt_ms: float
    duration_ms: float
    physical_origin_ms: float
    event_onset_ms: float
    sample_time_ms: tuple[float, ...]
    threads: int = 1

    def bindings(self):
        package = Path(__file__).parent
        sources = [package / name for name in ('native_factory.py', 'dynamics.py', 'inputs.py',
                   'observation.py', 'runtime.py', 'resources.py', 'interfaces.py')]
        sources += [package.parent / name for name in ('config.py', 'hybrid_engine.py', 'neural_baseline.py', 'model_registry.py')]
        return {'schema': FACTORY_SCHEMA, 'interface_version': INTERFACE_VERSION,
                'case_id': self.case_id, 'workload_name': self.workload_name, 'anatomy_registration': self.anatomy_registration.digest,
                'sensory_registration': self.sensory_registration.digest,
                'physiology_registration': self.physiology_registration.digest,
                'context': self.context.digest, 'movie': self.movie.digest, 'variant': self.variant.digest,
                'observation': self.observation.digest, 'evaluation': self.evaluation.digest,
                'schedule': identity([asdict(row) for row in self.schedule]),
                'preparation_plan': identity(self.preparation_plan),
                'source_parameters_sha256': self.source_parameters_sha256,
                'dt_ms': self.dt_ms, 'record_dt_ms': self.record_dt_ms, 'duration_ms': self.duration_ms,
                'physical_origin_ms': self.physical_origin_ms, 'event_onset_ms': self.event_onset_ms,
                'sample_time_ms': list(self.sample_time_ms), 'threads': self.threads,
                'implementation_sha256': {p.name: _file_sha(p) for p in sources}}

    @property
    def digest(self):
        return identity(self.bindings())


def _live_admission(threads, *, expected=None, digest=None):
    current = resources.current_admission()
    if not isinstance(current, dict) or current.get('scope') != 'full_graph' or current.get('admitted') is not True:
        _refuse('FULL_GRAPH_ADMISSION_REQUIRED', 'A live area-06 full_graph pilot/campaign context is mandatory')
    if current.get('kind') not in {'pilot', 'campaign'} or current.get('reasons') != []:
        _refuse('ADMISSION_INVALID', 'Admission must be an unrefused pilot or campaign')
    if current.get('group_id') != GROUP_ID or current.get('lock_root') != str(PRIMARY_ROOT / 'build/runtime'):
        _refuse('ADMISSION_INVALID', 'Admission must own the primary-root locks and original shared group')
    if current.get('forecast', {}).get('scope') != 'full_graph':
        _refuse('ADMISSION_INVALID', 'A fixture forecast cannot admit native construction')
    policy = current.get('policy', {})
    if type(threads) is not int or not 1 <= threads <= policy.get('threads', 0) or policy.get('tier') == 'dummy':
        _refuse('ADMISSION_INVALID', 'Requested threads exceed the admitted saved compute policy')
    if expected is not None and (current is not expected or identity(current) != digest):
        _refuse('ADMISSION_CHANGED', 'The live admission changed or ended during native construction/use')
    return current


def _ordinary_file(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path or not path.is_relative_to(PRIMARY_ROOT) or not path.is_file():
        _refuse('ARTIFACT_PATH_INVALID', 'Artifacts must be ordinary files under the absolute primary root')
    return path


def _file_sha(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _control_json(path, digest):
    _sha(digest, 'control artifact hash')
    path = _ordinary_file(path)
    relative = path.relative_to(PRIMARY_ROOT).as_posix()
    if not (relative.startswith('docs/paralimbo-upgrade/') or relative.startswith('build/biological-benchmark/paralimbo-upgrade')):
        _refuse('ARTIFACT_PATH_INVALID', 'Review/evidence reads are restricted to upgrade control artifacts')
    if path.suffix != '.json' or path.stat().st_size > 16_000_000:
        _refuse('ARTIFACT_PATH_INVALID', 'A bounded JSON control artifact is required')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != _sha(digest, 'control artifact hash'):
        _refuse('ARTIFACT_CHANGED', str(path))
    try:
        value = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        _refuse('ARTIFACT_INVALID', str(exc))
    if not isinstance(value, dict):
        _refuse('ARTIFACT_INVALID', 'Control artifact must be an object')
    return value


def _review(request, admission, path, digest):
    review = _control_json(path, digest)
    if (review.get('schema') != REVIEW_SCHEMA or review.get('interface_version') != INTERFACE_VERSION
            or review.get('owner_area') != '00' or review.get('decision') != 'approved'
            or review.get('scope') != 'restricted_hypothesis' or review.get('execution_kind') != admission['kind']
            or review.get('contract_sha256') != request.digest):
        _refuse('SCIENCE_REVIEW_REQUIRED', 'Coordinator review must bind this exact complete contract and execution kind')
    if review.get('missing_requirements') != [] or review.get('unsupported_quantities') != []:
        _refuse('UNSUPPORTED_SCIENCE', 'The reviewed contract still has missing or unsupported quantities')
    artifacts = review.get('evidence_artifacts', [])
    if {row.get('purpose') for row in artifacts} != EVIDENCE_PURPOSES:
        _refuse('SCIENCE_REVIEW_REQUIRED', 'Six explicit scientific evidence/control artifact purposes are required')
    for row in artifacts:
        _control_json(row['path'], row['sha256'])
    if admission['kind'] == 'campaign':
        if admission['forecast'].get('schedule_identity') != request.bindings()['schedule']:
            _refuse('SCHEDULE_MISMATCH', 'The live campaign forecast is for another finite schedule')
        numerical = review.get('numerical_qualification', {})
        qualified = _control_json(numerical.get('path', ''), numerical.get('sha256'))
        if (qualified.get('scope') != 'full_graph' or qualified.get('status') != 'PASS'
                or qualified.get('contract_sha256') != request.digest or qualified.get('population') != dynamics.NATIVE_POPULATION
                or _sha(qualified.get('pilot_runtime_identity'), 'qualified native pilot identity') != admission['forecast'].get('pilot_identity')):
            _refuse('NUMERICAL_QUALIFICATION_REQUIRED', 'Full native qualification must bind this contract')
        checks = qualified.get('checks', {})
        if set(checks) != {'timestep', 'input', 'optical', 'observation', 'checkpoint', 'hidden_state'} or any(row.get('pass') is not True for row in checks.values()):
            _refuse('NUMERICAL_QUALIFICATION_REQUIRED', 'All declared native numerical/replay checks must pass')
        for name in ('timestep', 'input', 'optical', 'observation'):
            value = checks[name].get('max_abs_discrepancy_mv')
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not np.isfinite(value) or not 0 <= value <= .001:
                _refuse('NUMERICAL_QUALIFICATION_REQUIRED', 'Native discrepancy must be finite and <=0.001 mV')
        if checks['checkpoint'].get('serialized_full_state_replay_exact') is not True or checks['hidden_state'].get('finite') is not True or checks['hidden_state'].get('clamps') != 0:
            _refuse('NUMERICAL_QUALIFICATION_REQUIRED', 'Full-state replay, finiteness and zero clamps must be explicit')
    return review


def _validate_science(request):
    if not isinstance(request, NativeFactoryRequest):
        _refuse('SCIENCE_CONTRACT_REQUIRED', 'Supply a NativeFactoryRequest with complete explicit contracts')
    c = request.context
    candidate = dynamics.candidate_manifest(request.variant)
    if (c.model_id, c.model_sha256) != (candidate['reference_model_id'], candidate['reference_model_sha256']):
        _refuse('REGISTRATION_MISMATCH', 'Requested variant belongs to a different pinned provider')
    if c.scope != 'restricted_hypothesis' or c.full_graph_neuron_count != dynamics.NATIVE_POPULATION or len(c.root_ids) != dynamics.NATIVE_POPULATION:
        _refuse('FULL_POPULATION_REQUIRED', 'Exactly 175401 retained native roots are required')
    if c.disabled_pathway_ids or any(not r.isdecimal() for r in c.root_ids):
        _refuse('ROOT_OR_PATHWAY_MISMATCH', 'Use source-ordered decimal roots and no suppression claims')
    for reg in (request.anatomy_registration, request.sensory_registration, request.physiology_registration):
        if reg.scope != c.scope or reg.evidence_class in {'synthetic', 'unsupported'} or not reg.assumptions:
            _refuse('UNSUPPORTED_SCIENCE', 'Every native registration needs explicit restricted-hypothesis evidence')
        for field in ('model_id', 'model_sha256', 'source_id', 'source_sha256'):
            if getattr(reg, field) != getattr(c, field):
                _refuse('REGISTRATION_MISMATCH', field + ' differs between native contracts')
        evidence = reg.to_dict()
        # Area-02's immutable origin ledger records quantities intentionally
        # left to 03/05. Resolve only those named dependencies through the
        # complete new contracts below; never rewrite or promote that ledger.
        ledger = evidence['spatial_correspondence'].pop('requirements', {})
        deferred = {'input_sign_and_kinetics', 'holding_state', 'frozen_latent_distribution', 'voltage_observation'}
        for name, row in ledger.items():
            if name not in deferred:
                _evidence_tree(row)
        _evidence_tree(evidence)
    if c.source_id != 'banc:888' or tuple(request.physiology_registration.root_ids) != c.root_ids:
        _refuse('FULL_POPULATION_REQUIRED', 'Physiology roots must cover the complete ordered BANC-family graph')
    physiological = request.physiology_registration.spatial_correspondence.get('physiology', {})
    targets = tuple(physiological.get('target_root_ids', ()))
    target_set = set(targets)
    if (physiological.get('equation_id') != dynamics.EQUATION_ID or not targets or len(target_set) != len(targets)
            or not target_set <= set(c.root_ids) or targets != tuple(root for root in c.root_ids if root in target_set)
            or not set(dynamics.ASSUMPTIONS) <= set(request.physiology_registration.assumptions)):
        _refuse('PHYSIOLOGY_CONTRACT_INCOMPLETE', 'Declare the exact ordered target scope, equation and inherited assumptions')
    if request.movie.scope != c.scope or not set(request.sensory_registration.root_ids) <= set(c.root_ids):
        _refuse('REGISTRATION_MISMATCH', 'Movie scope or sensory membership differs')
    from .registrations.adapter_bridge import compose_adapter_registration
    adapter_spec = request.sensory_registration.spatial_correspondence.get('sensory_adapter', {})
    composed = compose_adapter_registration(request.anatomy_registration, adapter_spec)
    if composed.digest != request.sensory_registration.digest:
        _refuse('REGISTRATION_MISMATCH', 'Sensory registration is not the exact area-02 composition')
    if any(channel.get('contribution_mode') != 'complement' for channel in adapter_spec.get('channels', [])):
        _refuse('REPLACEMENT_UNIMPLEMENTED', 'This factory preserves pathways and only admits complement inputs')
    obs = request.observation
    if obs.units != 'mV' or obs.state_variable != 'voltage_mv' or not set(obs.root_ids) <= set(c.root_ids):
        _refuse('OBSERVATION_UNSUPPORTED', 'Native point voltage requires a registered physical-mV observation')
    try:
        assignment = observation.CellAssignment(**obs.parameters['assignment'])
    except (KeyError, TypeError, ValueError) as exc:
        _refuse('OBSERVATION_UNSUPPORTED', str(exc))
    if (assignment.scope != c.scope or assignment.evidence_class in {'unsupported', 'synthetic'}
            or assignment.registration_id != request.anatomy_registration.registration_id
            or assignment.digest != obs.parameters.get('assignment_identity') or assignment.root_ids != tuple(obs.root_ids)):
        _refuse('OBSERVATION_UNSUPPORTED', 'Observation assignment must bind the reviewed area-02 registration')
    _evidence_tree(obs.to_dict())
    if request.case_id not in request.evaluation.case_ids or not request.evaluation.retrospective or request.evaluation.units != 'mV':
        _refuse('EVALUATION_MISMATCH', 'This native T4 construction retains the registered retrospective case suite')
    if not request.schedule or {row.phase for row in request.schedule} != resources.SCHEDULE_PHASES:
        _refuse('SCHEDULE_MISSING', 'Prediction, refinement, uncertainty and fitting phases must all be explicit')
    if len({row.name for row in request.schedule}) != len(request.schedule):
        _refuse('SCHEDULE_MISSING', 'Workload names must be unique')
    for row in request.schedule:
        resources.Workload(**asdict(row))
    plan = request.preparation_plan
    if (set(plan) != {'schema', 'protocol', 'assumptions', 'residual_tolerance', 'undriven_roots_policy', 'failure_policy'}
            or plan['schema'] != PREPARATION_SCHEMA or plan['protocol'] != 'constant_background_equilibrium_v1'
            or not plan['assumptions'] or plan['undriven_roots_policy'] != 'zero_external_drive_preserve_endogenous_release'
            or plan['failure_policy'] != 'retain_and_refuse_no_fallback'):
        _refuse('PREPARATION_UNSUPPORTED', 'An explicit complete quiescent hypothesis is required')
    tol = plan['residual_tolerance']
    if isinstance(tol, bool) or not isinstance(tol, (float, int)) or not np.isfinite(tol) or not 0 < tol <= 1e-8:
        _refuse('PREPARATION_UNSUPPORTED', 'Preparation tolerance cannot be loosened')
    _sha(request.source_parameters_sha256, 'source_parameters_sha256')
    _sha(c.graph_sha256, 'graph_sha256')
    _sha(request.movie.source_sha256, 'movie source_sha256')
    for name in ('dt_ms', 'record_dt_ms', 'duration_ms', 'physical_origin_ms', 'event_onset_ms'):
        value = getattr(request, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
            _refuse('CLOCK_INVALID', name + ' must be explicit finite milliseconds')
    from .numerics import integer_steps
    requested_steps = integer_steps(request.duration_ms, request.dt_ms)
    integer_steps(request.record_dt_ms, request.dt_ms, 'record_dt_ms')
    workload = [row for row in request.schedule if row.name == request.workload_name]
    if len(workload) != 1 or workload[0].runs < 1 or workload[0].integration_steps != requested_steps:
        _refuse('SCHEDULE_MISMATCH', 'Selected positive-run workload must bind the exact requested neural duration')
    samples = np.asarray(request.sample_time_ms, dtype=float)
    sample_ms = obs.parameters.get('sample_ms')
    if samples.ndim != 1 or len(samples) < 2 or not np.isfinite(samples).all() or not isinstance(sample_ms, (int, float)) or sample_ms <= 0 or not np.allclose(np.diff(samples), sample_ms, atol=1e-9, rtol=0):
        _refuse('OBSERVATION_UNSUPPORTED', 'Explicit regular registered observation times are required')
    step = obs.filter_spec.get('step_ms', 0.)
    half = obs.filter_spec.get('half_width_ms', float('inf'))
    if not isinstance(step, (int, float)) or not isinstance(half, (int, float)) or step <= 0 or not np.isfinite(half) or 2 * half / step > 100_000:
        _refuse('OBSERVATION_UNSUPPORTED', 'Bounded registered acquisition FIR required')
    offsets, _ = observation.acquisition_fir(obs.filter_spec)
    if (samples[0] + request.event_onset_ms - offsets[-1] < request.physical_origin_ms - 1e-9
            or samples[-1] + request.event_onset_ms - offsets[0] > request.physical_origin_ms + request.duration_ms - request.record_dt_ms + 1e-9):
        _refuse('OBSERVATION_SUPPORT_MISSING', 'Simulation clock must cover baseline/observation and both FIR margins')
    if obs.baseline_spec.get('kind') == 'mean':
        if set(obs.baseline_spec) != {'kind', 'window_ms', 'end_exclusive'} or obs.baseline_spec['end_exclusive'] is not True:
            _refuse('OBSERVATION_UNSUPPORTED', 'Baseline mean needs its exact exclusive physical window')
        lo, hi = obs.baseline_spec['window_ms']
        if not np.isfinite([lo, hi]).all() or hi <= lo or not np.any((samples >= lo) & (samples < hi)):
            _refuse('OBSERVATION_SUPPORT_MISSING', 'Observation samples omit the registered baseline window')
    elif dict(obs.baseline_spec) != {'kind': 'none'}:
        _refuse('OBSERVATION_UNSUPPORTED', 'Unknown baseline transformation')
    if (obs.parameters.get('version') != observation.OBSERVATION_VERSION
            or obs.parameters.get('resampling') != 'linear_in_physical_time_no_extrapolation'
            or obs.repeat_aggregation not in {'none', 'equal_eligible_repeat_mean'}):
        _refuse('OBSERVATION_UNSUPPORTED', 'Observation implementation/version/aggregation must be explicit')


def _input_preflight(request):
    # Area 03 shares this entire validation path with its runtime adapter.
    validate = getattr(inputs, 'preflight_registered_input', None)
    if not callable(validate):
        _refuse('INPUT_API_UNAVAILABLE', 'Area-03 public complete input preflight is required')
    receipt = validate(request.sensory_registration, request.movie, request.context,
        dt_ms=request.dt_ms, physical_origin_ms=request.physical_origin_ms)
    payload = {key: value for key, value in receipt.items() if key != 'digest'}
    expected = {'registration_digest': request.sensory_registration.digest, 'movie_digest': request.movie.digest,
                'context_digest': request.context.digest, 'dt_ms': request.dt_ms,
                'physical_origin_ms': request.physical_origin_ms}
    if (receipt.get('schema') != 'sensory-input-preflight-v1' or receipt.get('status') != 'VALIDATED'
            or receipt.get('scope') != request.context.scope or receipt.get('digest') != identity(payload)
            or receipt.get('runtime_admitted') is not False or receipt.get('preparation_passed') is not False
            or any(receipt.get('bindings', {}).get(key) != value for key, value in expected.items())):
        _refuse('INPUT_BINDING_INVALID', 'Input validation receipt must bind the complete unprepared contract')
    return receipt


def _holding_preflight(request):
    # Area 03 owns all units, evidence checks and once-per-root pA conversion.
    derive = getattr(inputs, 'registered_background_from_registration', None)
    if not callable(derive):
        _refuse('HOLDING_API_UNAVAILABLE', 'Area-03 public pre-construction holding validation is required')
    indices, drive = derive(request.sensory_registration, request.context)
    receipt = {'schema': 'paralimbo-native-holding-derivation-v1',
               'registration_digest': request.sensory_registration.digest, 'context_digest': request.context.digest,
               'movie_digest': request.movie.digest, 'dt_ms': request.dt_ms, 'physical_origin_ms': request.physical_origin_ms,
               'inputs_source_sha256': _file_sha(Path(inputs.__file__)),
               'units': 'normalized_mV', 'indices': indices.tolist(), 'drive_mv': drive.tolist(),
               'preparation_passed': False}
    return {'indices': indices, 'drive_mv': drive, 'receipt': receipt, 'digest': identity(receipt)}


class _AdmissionBoundRunner(CheckedRunner):
    def bind_native_admission(self, admission, request_digest, *, total_steps, record_indices):
        self._native_admission = admission
        self._native_admission_digest = identity(admission)
        self._native_total_steps = total_steps
        self._native_records = np.array(record_indices, dtype=np.int32, copy=True)
        self.runtime_identity = identity({'checked_runtime': self.runtime_identity,
            'factory_source': _file_sha(Path(__file__)), 'factory_contract': request_digest})

    def run(self, duration_ms, *, record_indices, block_ms=5.):
        _live_admission(self.engine.threads, expected=self._native_admission, digest=self._native_admission_digest)
        from .numerics import integer_steps
        steps = integer_steps(duration_ms, self.engine.dt)
        if self.engine.step + steps > self._native_total_steps or not np.array_equal(record_indices, self._native_records):
            _refuse('SCHEDULE_MISMATCH', 'Native continuation or recorded roots exceed the reviewed workload')
        return super().run(duration_ms, record_indices=record_indices, block_ms=block_ms)


@dataclass
class NativeFactoryResult:
    runner: CheckedRunner
    receipt: dict
    request: NativeFactoryRequest
    record_indices: np.ndarray

    def observe(self, trace):
        """Apply the reviewed physical clock and area-05 operator; no scoring."""
        if self.request.digest != self.receipt['contract_sha256']:
            _refuse('CONTRACT_CHANGED', 'Factory observation contract was modified')
        if trace.get('scope') != 'full_graph' or trace.get('completed') is not True or trace.get('runtime_identity') != self.runner.runtime_identity:
            _refuse('TRACE_BINDING_INVALID', 'Observe only a completed trace from this bound full-graph runtime')
        return observation.observe_trace(np.asarray(trace['time_ms']) + self.request.physical_origin_ms,
            {'voltage_mv': trace['voltage_mv']}, trace['root_ids'], self.request.observation,
            self.request.sample_time_ms, source_units='mV', event_onset_ms=self.request.event_onset_ms)


def build_native_runner(request: NativeFactoryRequest, *, review_path: Path, review_sha256: str) -> NativeFactoryResult:
    """Construct + prepare only inside an admitted context; never simulate/fit.

    Missing science/admission/holding evidence refuses before the native loader.
    Failed preparation raises NativeFactoryError with a retained-ready receipt;
    the coordinator must save it using the existing shared budget writer.
    """
    admission = _live_admission(getattr(request, 'threads', 1))
    admission_digest = identity(admission)
    try:
        _validate_science(request)
    except NativeFactoryError:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        _refuse('SCIENCE_CONTRACT_INVALID', str(exc))
    binding = request.digest
    review = _review(request, admission, review_path, review_sha256)
    try:
        input_preflight = _input_preflight(request)
        holding = _holding_preflight(request)
    except NativeFactoryError:
        raise
    except inputs.UnsupportedInput as exc:
        _refuse('INPUT_CONTRACT_INVALID', str(exc), receipt=exc.record)
    except (ValueError, TypeError, KeyError) as exc:
        _refuse('INPUT_CONTRACT_INVALID', str(exc))
    # Both public validation receipts are checked before native loading.
    indices = np.asarray(holding['indices'])
    drive = np.asarray(holding['drive_mv'], dtype=np.float64)
    receipt = holding['receipt']
    expected = {'registration_digest': request.sensory_registration.digest, 'context_digest': request.context.digest,
                'movie_digest': request.movie.digest, 'dt_ms': request.dt_ms, 'physical_origin_ms': request.physical_origin_ms}
    if any(receipt.get(k) != v for k, v in expected.items()) or holding.get('digest') != identity(receipt):
        _refuse('HOLDING_BINDING_INVALID', 'Public holding receipt does not match the exact input contract')
    lookup = {root: index for index, root in enumerate(request.context.root_ids)}
    target_roots = set(request.sensory_registration.root_ids)
    target_indices = np.array([i for i, r in enumerate(request.context.root_ids) if r in target_roots], dtype=np.int32)
    if indices.ndim != 1 or indices.dtype.kind not in 'iu' or not np.array_equal(indices, target_indices) or drive.shape != indices.shape or not np.isfinite(drive).all():
        _refuse('HOLDING_BINDING_INVALID', 'Holding must cover every sensory target once in full-graph order')
    if receipt.get('indices') != indices.tolist() or receipt.get('drive_mv') != drive.tolist():
        _refuse('HOLDING_BINDING_INVALID', 'Holding receipt must bind its returned numeric vector')
    if input_preflight.get('indices') != indices.tolist():
        _refuse('INPUT_BINDING_INVALID', 'Complete input validation and holding must have identical targets')
    _live_admission(request.threads, expected=admission, digest=admission_digest)
    if request.digest != binding:
        _refuse('CONTRACT_CHANGED', 'Science contract changed during preflight')
    config_path = _ordinary_file(PRIMARY_ROOT / 'config/parameters.yaml')
    if _file_sha(config_path) != request.source_parameters_sha256:
        _refuse('SOURCE_CHANGED', 'Source parameter file no longer matches the review')
    folder = PRIMARY_ROOT / 'build/model-versions' / request.context.model_sha256
    if not folder.is_dir() or folder.resolve() != folder:
        _refuse('PINNED_ASSETS_MISSING', 'Do not migrate/rebuild frozen providers during construction')
    for name in ASSET_NAMES + ('manifest.json',):
        _ordinary_file(folder / name)
    network = load_model_network(PRIMARY_ROOT, request.context.model_id, request.context.model_sha256)
    _live_admission(request.threads, expected=admission, digest=admission_digest)
    manifest, neurons = network['manifest'], network['neurons']
    roots = tuple(neurons.root_id.astype('int64').astype(str))
    mask = neurons.is_graded.to_numpy()
    types = tuple(neurons.cell_type.fillna('').astype(str).replace('', '<untyped>'))
    if roots != request.context.root_ids or types != request.context.cell_types or mask.dtype != np.bool_ or len(roots) != dynamics.NATIVE_POPULATION:
        _refuse('FROZEN_GRAPH_MISMATCH', 'Frozen row order, cell types, electrical mask or population differs')
    # The verified loader and area-02 registrations bind the same full provider
    # envelope; an ad-hoc flat asset hash is a different identity, not a graph.
    graph_digest = graph_identity(manifest, manifest['output_hashes']['neurons.parquet'])
    if graph_digest != request.context.graph_sha256 or manifest['output_hashes']['neurons.parquet'] != request.context.source_sha256:
        _refuse('FROZEN_GRAPH_MISMATCH', 'Full frozen graph/source hashes differ from the reviewed context')
    for kind in ('graded', 'spiking'):
        matrix = network[kind]
        if not sparse.issparse(matrix) or matrix.shape != (dynamics.NATIVE_POPULATION, dynamics.NATIVE_POPULATION):
            _refuse('FROZEN_GRAPH_MISMATCH', 'Every frozen partition must retain the full graph')
    params = dynamics.native_engine_parameters(request.variant, manifest, parameters(PRIMARY_ROOT),
                                               dt_ms=request.dt_ms, record_dt_ms=request.record_dt_ms)
    science = dynamics.native_contract(request.variant, request.physiology_registration, request.observation, roots, mask)
    _live_admission(request.threads, expected=admission, digest=admission_digest)
    engine = HybridEngine(network['graded'], network['spiking'], mask, params, dt=request.dt_ms, threads=request.threads)
    preparation = {'schema': 'paralimbo-native-preparation-receipt-v1', 'status': 'FAILED',
                   'contract_sha256': binding, 'holding_digest': holding['digest'],
                   'plan_digest': identity(request.preparation_plan), 'resource_admission_digest': admission_digest,
                   'physiology_digest': request.physiology_registration.digest, 'variant_digest': request.variant.digest}
    try:
        preparation['solver'] = initialize_equilibrium(engine, indices, drive)
        residual = complete_residual(engine, indices, drive)
        preparation['residual'] = residual
        diagnostics = dynamics.full_state_diagnostics(engine)
        preparation['diagnostics'] = diagnostics
        tol = request.preparation_plan['residual_tolerance']
        if not diagnostics['numerically_clean'] or not residual['finite'] or residual['queued_spikes'] or any(not np.isfinite(residual[k]) or not 0 <= residual[k] <= tol for k in ('max_abs_dvdt_mv_per_ms', 'max_abs_dgdt_mv_per_ms', 'max_delay_history_residual_mv')):
            raise ValueError('Complete quiescent preparation residual failed')
        preparation['initial_state_digest'] = _state_digest(snapshot_state(engine))
    except (ValueError, FloatingPointError) as exc:
        preparation['reason'] = str(exc)
        _refuse('PREPARATION_FAILED', str(exc), receipt=preparation)
    preparation['status'] = 'PASS'
    preparation_digest = identity(preparation)
    _live_admission(request.threads, expected=admission, digest=admission_digest)
    adapter_admission = {'registration_digest': request.sensory_registration.digest,
        'observation_digest': request.observation.digest, 'resource_admission_digest': admission_digest,
        'preparation_digest': preparation_digest, 'allowed_stimulus_ids': [request.movie.stimulus_id],
        'hypothesis_digest': identity(request.sensory_registration.spatial_correspondence['sensory_adapter']['hypothesis'])}
    adapter = inputs.DeterministicInputAdapter(request.sensory_registration, request.movie, request.context,
        dt_ms=request.dt_ms, physical_origin_ms=request.physical_origin_ms, admission=adapter_admission)
    if adapter.input_preflight_receipt != input_preflight:
        _refuse('INPUT_BINDING_INVALID', 'Final adapter validation differs from the pre-load input receipt')
    actual_indices, actual_drive = adapter.registered_background_input()
    if not np.array_equal(actual_indices, indices) or not np.array_equal(actual_drive, drive):
        _refuse('HOLDING_BINDING_INVALID', 'Final adapter background differs from pre-construction holding')
    runner = _AdmissionBoundRunner(engine, adapter, roots, expected_population=dynamics.NATIVE_POPULATION, scope='full_graph')
    record_indices = np.array([lookup[r] for r in request.observation.root_ids], dtype=np.int32)
    runner.bind_native_admission(admission, binding,
        total_steps=round(request.duration_ms / request.dt_ms), record_indices=record_indices)
    check = runner.register_preparation(request.preparation_plan['protocol'], indices=indices, drive=drive,
        initialize=False, residual_tolerance=request.preparation_plan['residual_tolerance'], assumptions=request.preparation_plan['assumptions'])
    if not check['pass'] or check.get('initial_state_digest') != preparation['initial_state_digest']:
        _refuse('PREPARATION_FAILED', 'CheckedRunner rejected the complete prepared state', receipt=check)
    _live_admission(request.threads, expected=admission, digest=admission_digest)
    if request.digest != binding:
        _refuse('CONTRACT_CHANGED', 'Contract changed during construction')
    output = {'schema': FACTORY_SCHEMA, 'scope': 'restricted_hypothesis', 'contract_sha256': binding,
        'review_sha256': review_sha256, 'execution_kind': admission['kind'], 'resource_admission_digest': admission_digest,
        'resource_admission': copy.deepcopy(admission), 'input_preflight': input_preflight,
        'holding_receipt': receipt, 'preparation_receipt': preparation,
        'preparation_digest': preparation_digest, 'checked_preparation': check, 'science_contract': science,
        'runtime_identity': runner.runtime_identity, 'population': len(roots), 'graph_sha256': graph_digest,
        'origin_requirement_ledger': copy.deepcopy(request.anatomy_registration.spatial_correspondence.get('requirements', {})),
        'dependency_resolution': {'input_sign_and_kinetics': request.sensory_registration.digest,
            'frozen_latent_distribution': request.sensory_registration.digest,
            'holding_state': preparation_digest, 'voltage_observation': request.observation.digest},
        'simulated_ms': 0., 'biological_accuracy': 'NOT_EVALUATED',
        'numerical_qualification': 'PENDING_NATIVE_PILOT' if admission['kind'] == 'pilot' else copy.deepcopy(review['numerical_qualification'])}
    return NativeFactoryResult(runner, output, request, record_indices)
