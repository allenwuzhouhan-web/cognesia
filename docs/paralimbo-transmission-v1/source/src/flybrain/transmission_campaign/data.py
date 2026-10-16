"""Response-blind benchmark selection, native input composition, staged outcomes.

DN metadata is pinned here without acquiring physiological recordings. Missing
ROI identity/expression evidence triggers the user-approved native T4 fallback;
it never turns anonymous imaging ROIs into identified connectome neurons.
"""
from __future__ import annotations

import copy
import json
import math
from functools import lru_cache
from pathlib import Path
import threading

import numpy as np

from ..paralimbo_upgrade.interfaces import identity
from ..validation_project.common import file_hash, identity as historical_identity

ROOT = Path(__file__).resolve().parents[3]
T4_SOURCE = 'build/biological-benchmark/paralimbo-upgrade-native-retrospective-20261012-v3/protocol.json'
T4_SOURCE_ID = 'a78a968b766014514657269da41cf1402489ca7936a497b00b4ef847e437baef'
T4_INPUT = 'build/biological-benchmark/t4-fit-v1'
DN_DOI = 'doi:10.7910/DVN/INYAYV'
DN_METADATA_FILE_ID = 7363021
DN_METADATA_MD5 = 'ab2aa172172f1a0f797db9ef9649c818'
DN_SOURCE_COMMIT = 'b9e66203ab825187e5d9bd651a63e46c2d5f0ab0'
_COMPOSER_LOCK = threading.RLock()
_ACTIVE_RUNTIME_ROOTS = {}
DN_TARGETS = {
    'DNp09': ['720575941566493282', '720575941433155799'],
    'MDN3': ['720575941491012809', '720575941499708745', '720575941491065653', '720575941614906387'],
}
_DN_ROWS = (
    ('DNp09',44,7352005,7351988), ('DNp09',46,7351979,7351969), ('DNp09',61,7352015,7351987),
    ('MDN3',34,7351993,7351972), ('MDN3',42,7351966,7352004), ('MDN3',50,7352014,7351977),
    ('MDN3',51,7351975,7351995), ('MDN3',62,7351997,7351992),
    ('PR',11,7352073,7352072), ('PR',65,7351996,7351963),
)
SOURCE_FILES = (
    'src/flybrain/transmission_campaign/data.py',
    'src/flybrain/transmission_campaign/calibration.py',
    'src/flybrain/transmission_campaign/scoring.py',
    'src/flybrain/paralimbo_upgrade/retrospective_contract.py',
    'src/flybrain/paralimbo_upgrade/retrospective_scoring.py',
    'src/flybrain/paralimbo_upgrade/native_factory.py',
    'src/flybrain/paralimbo_upgrade/registrations/factories.py',
    'src/flybrain/paralimbo_upgrade/registrations/adapter_bridge.py',
    'src/flybrain/t4_fit_project/data.py',
)


def dn_metadata():
    rows = [{'group':g, 'animal_id':str(a), 'recording_file_id':r, 'roi_file_id':m,
             'outcomes_acquired':False} for g,a,r,m in _DN_ROWS]
    body = {'schema':'transmission-dn-metadata-v1', 'doi':DN_DOI, 'version':'1.0',
            'metadata_file_id':DN_METADATA_FILE_ID, 'metadata_md5':DN_METADATA_MD5,
            'source_commit':DN_SOURCE_COMMIT, 'records':rows, 'targets':copy.deepcopy(DN_TARGETS),
            'compressed_starter_bytes':2882130206,
            'selection':'first available pre-CO2 ball/xz laser recording with ROI companion per animal',
            'missing_dnp09_animal_archives':['15','18'], 'aDN2':'UNSUPPORTED_TARGET_CORRESPONDENCE',
            'trial_count_eligibility':'UNVERIFIED_UNTIL_STIMULUS_ONLY_IMPORT',
            'minimum_selected_pulses':10, 'windows_seconds':[-5.,0.,5.,10.],
            'roi_identity':'anonymous; pixel alignment does not identify connectome neurons'}
    return body | {'metadata_sha256':identity(body)}


def _safe_file(root, relative):
    root = Path(root).resolve()
    p = Path(relative)
    path = root / p
    if p.is_absolute() or '..' in p.parts or not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError('Missing or unsafe evidence path')
    return path


def dn_registration_gate(root=ROOT, registration=None):
    """Require content-bound independent evidence; no network or outcome reads.

The supplied manifest needs evidence for target_membership, observation_mapping,
opto_adapter and calcium_adapter. Each evidence item binds a local source file
by SHA256 and must be measured or independently_supported and reviewed. The
observation mapping must explicitly identify recorded ROIs; a population mask
alone is not silently promoted into a per-neuron benchmark.
"""
    required = ('target_membership','observation_mapping','opto_adapter','calcium_adapter')
    reasons = []
    if registration is None:
        reasons.append('UNSUPPORTED_OBSERVATION_MAPPING')
    else:
        if registration.get('schema') != 'transmission-dn-registration-v1':
            reasons.append('INVALID_REGISTRATION_SCHEMA')
        for name in required:
            row = registration.get('evidence',{}).get(name,{})
            if row.get('classification') not in {'measured','independently_supported'} or row.get('review_status') != 'PASS':
                reasons.append('UNSUPPORTED_'+name.upper()); continue
            try:
                if file_hash(_safe_file(root,row['path'])) != row['sha256']:
                    reasons.append('CHANGED_'+name.upper())
            except (KeyError, ValueError):
                reasons.append('MISSING_'+name.upper())
        mapping = registration.get('roi_to_root',{})
        expected_animals = {str(r[1]) for r in _DN_ROWS}
        if set(mapping) != expected_animals or any(not isinstance(v,dict) or not v for v in mapping.values()):
            reasons.append('UNSUPPORTED_OBSERVATION_MAPPING')
        recorded = registration.get('recorded_roi_ids_by_animal',{})
        if (set(recorded)!=expected_animals or set(mapping)!=expected_animals
                or any(not isinstance(recorded.get(a),list) or not isinstance(mapping.get(a),dict)
                    or len(recorded[a])!=len(set(recorded[a])) or set(recorded[a])!=set(mapping[a])
                    or any(not isinstance(roi,str) or not roi for roi in mapping[a])
                    or any(not isinstance(root_id,str) or len(root_id)!=18 or not root_id.isdecimal()
                           for root_id in mapping[a].values()) for a in expected_animals)):
            reasons.append('UNSUPPORTED_OBSERVATION_MAPPING')
        # Mapping values must be bound by the independently reviewed artifact,
        # not merely asserted alongside an unrelated evidence-file checksum.
        try:
            item = registration['evidence']['observation_mapping']
            observed = json.loads(_safe_file(root,item['path']).read_bytes())
            if (observed.get('roi_to_root')!=mapping or observed.get('recorded_roi_ids_by_animal')!=recorded
                    or observed.get('metadata_sha256')!=dn_metadata()['metadata_sha256']):
                reasons.append('UNBOUND_OBSERVATION_MAPPING')
        except (KeyError,ValueError,TypeError):
            reasons.append('UNBOUND_OBSERVATION_MAPPING')
        if registration.get('anonymous_roi_mapping') is not False:
            reasons.append('ANONYMOUS_ROI_MAPPING_REFUSED')
        if registration.get('targets') != DN_TARGETS:
            reasons.append('UNSUPPORTED_TARGET_CORRESPONDENCE')
    reasons = sorted(set(reasons))
    body = {'schema':'transmission-dn-gate-v1', 'status':'SUPPORTED' if not reasons else 'UNSUPPORTED',
            'reasons':reasons, 'metadata_sha256':dn_metadata()['metadata_sha256'],
            'registration_sha256':identity(registration) if registration else None,
            'outcome_access':False, 'fallback':'native_t4' if reasons else None}
    return body | {'gate_sha256':identity(body)}


def dn_loao_folds(records=None):
    """One animal per test fold; all of its recordings remain held out together."""
    records = copy.deepcopy(records if records is not None else dn_metadata()['records'])
    if not records or any(not r.get('animal_id') or not r.get('group') for r in records):
        raise ValueError('Animal and intervention group identity required')
    animals = sorted({str(r['animal_id']) for r in records})
    if any(len({str(r['animal_id']) for r in records if r['group']==group}) < 2
           for group in {r['group'] for r in records}):
        raise ValueError('INSUFFICIENT_COHORT: at least two intact animals per group')
    return [{'fold_id':'animal-'+a, 'training_animal_ids':[x for x in animals if x!=a],
             'evaluation_animal_ids':[a],
             'training_records':[r for r in records if str(r['animal_id'])!=a],
             'evaluation_records':[r for r in records if str(r['animal_id'])==a]} for a in animals]


def build_t4_protocol(root=ROOT):
    """Reuse the nine binding-complete native requests; read input artifacts only."""
    from ..paralimbo_upgrade.retrospective_contract import InputStore, selected_cases
    from ..t4_fit_project import data as t4
    root = Path(root).resolve()
    source = json.loads(_safe_file(root,T4_SOURCE).read_bytes())
    if (source.get('protocol_sha256') != T4_SOURCE_ID or
            identity({k:v for k,v in source.items() if k!='protocol_sha256'}) != T4_SOURCE_ID):
        raise ValueError('Pinned native T4 source protocol changed')
    native = copy.deepcopy(source['contract'])
    store = InputStore(root/T4_INPUT)
    manifest = t4.manifest(store)
    if store.digest('inputs/manifest.json') != native['input_manifest_sha256']:
        raise ValueError('Native T4 input manifest changed')
    if selected_cases(manifest) != native['cases']:
        raise ValueError('Nine-condition source selection changed')
    required = {(m,c['case_id']) for m in native['models'] for c in native['cases']}
    if {(r['model_id'],r['case_id']) for r in source['requests']} != required:
        raise ValueError('Source native input bindings incomplete')
    # The new campaign registers its secondary hypothesis before calibration;
    # the historical compact source only executed the primary T4c assignment.
    native['sensitivity_ids'] = ['primary','alternate_vertical_subtype']
    native['templates']['alternate_vertical_subtype'] = 'right_mirror_proxy|T4d|primary'
    native['limits'] = [s for s in native['limits'] if not s.startswith('Only the assumed T4c assignment')]
    native['limits'].append('T4c primary and T4d alternate are separately reported assumed correspondences; identical selected parameters and input multiplier are used for both.')
    for case in native['cases']:
        t4.input_case(store,case)  # checks input bytes; forbidden response members fail
    # Only hash/identity metadata is read here, never response-array bytes.
    observation_sources = {}
    for case in native['cases']:
        family = 'flash' if case['family']=='flash' else 'motion'
        relative = f"observations/{family}/{case['case_id']}.json"
        path = _safe_file(store.output,relative)
        meta = json.loads(path.read_bytes())
        if (meta.get('observation_identity') != historical_identity({k:v for k,v in meta.items() if k!='observation_identity'})
                or meta.get('case_id')!=case['case_id'] or meta.get('input_identity')!=manifest['input_identity']
                or meta.get('source_trace_sha256')!=case['source_trace_sha256']):
            raise ValueError('Observation hash metadata does not bind the selected input')
        observation_sources[case['case_id']] = {'metadata_path':relative,'metadata_sha256':file_hash(path),
            'response_path':meta['path'],'response_sha256':meta['sha256'],
            'observation_identity':meta['observation_identity']}
    body = {'schema':'transmission-t4-protocol-v1', 'root':str(root), 'native_contract':native,
            'original_protocol_sha256':T4_SOURCE_ID, 'source_protocol_path':T4_SOURCE,
            'input_root':str(root/T4_INPUT),
            'observation_sources':observation_sources,
            'development_case_ids':[c['case_id'] for c in native['cases'] if c['family']=='flash'],
            'evaluation_case_ids':[c['case_id'] for c in native['cases'] if c['family']=='moving'],
            'historical_outcome_exposure':True,
            'scope':'retrospective_restricted_native_t4_hypothesis',
            'biological_superiority':'NOT_ESTABLISHED',
            'limits':['One previously exposed recorded cell; not whole-brain biological validation.',
                      'Native connectivity and source-assumed T4 assignment retained; no fitted response surrogate.'],
            'source_files':list(SOURCE_FILES)}
    return body | {'protocol_sha256':identity(body)}


def _check_protocol(protocol):
    if (protocol.get('schema')!='transmission-t4-protocol-v1' or
            protocol.get('protocol_sha256')!=identity({k:v for k,v in protocol.items() if k!='protocol_sha256'})):
        raise ValueError('Transmission input protocol changed')


def resolve_benchmark(root=ROOT, dn_registration=None):
    gate = dn_registration_gate(root,dn_registration)
    return {'benchmark_id':'dn_recruitment' if gate['status']=='SUPPORTED' else 'native_t4',
            'primary_gate':gate, 'automatic_fallback_authorized':True,
            'fallback_reason':gate['reasons'],
            't4_protocol':build_t4_protocol(root) if gate['status']!='SUPPORTED' else None,
            'dn_metadata':dn_metadata()}


def input_specs(protocol, split):
    _check_protocol(protocol)
    if split not in ('development','evaluation'):
        raise ValueError('Explicit development/evaluation split required')
    ids = set(protocol[split+'_case_ids'])
    return [copy.deepcopy(c) for c in protocol['native_contract']['cases'] if c['case_id'] in ids]


def frozen_input_files(benchmark):
    """Input/anatomy/config and outcome hash metadata; no response arrays."""
    if benchmark['benchmark_id']!='native_t4':
        raise ValueError('DN acquisition requires its separately admitted observation registration')
    from ..paralimbo_upgrade.registrations import factories, providers
    protocol = benchmark['t4_protocol']
    _check_protocol(protocol)
    root = Path(protocol['root'])
    relative = {T4_SOURCE, T4_INPUT+'/inputs/manifest.json', 'config/parameters.yaml'}
    relative.update(T4_INPUT+'/'+c['input_path'] for c in protocol['native_contract']['cases'])
    relative.update(T4_INPUT+'/'+r['metadata_path'] for r in protocol['observation_sources'].values())
    index_path = factories.OUTPUT+'/index.json'
    index = json.loads(_safe_file(root,index_path).read_bytes())
    relative.add(index_path)
    relative.update(factories.OUTPUT+'/'+p for p in index['files'])
    for model in protocol['native_contract']['models']:
        folder = 'build/model-versions/'+providers.PROVIDERS[model]['model_hash']
        relative.update((folder+'/manifest.json',folder+'/neurons.parquet'))
    paths = [_safe_file(root,p) for p in sorted(relative)]
    if any('observations' in p.parts and p.suffix!='.json' for p in paths):
        raise ValueError('Response artifact in input freeze inventory')
    return paths


def activate_frozen_inputs(protocol, frozen_root):
    """Bind the input-only composer to verified campaign copies in this worker.

    This does not edit the protocol or its original observation source paths.
    It changes only process-local input factories; parameter/outcome selection
    continues to reference the immutable campaign protocol identity.
    """
    from ..paralimbo_upgrade import retrospective_contract as native
    _check_protocol(protocol)
    root = Path(frozen_root).resolve()
    if file_hash(_safe_file(root,T4_INPUT+'/inputs/manifest.json')) != protocol['native_contract']['input_manifest_sha256']:
        raise ValueError('Frozen input manifest differs from campaign protocol')
    for case in protocol['native_contract']['cases']:
        if file_hash(_safe_file(root,T4_INPUT+'/'+case['input_path'])) != case['input_sha256']:
            raise ValueError('Frozen stimulus differs from campaign protocol')
    with _COMPOSER_LOCK:
        if native.ROOT != root or native._input_store().output != root/T4_INPUT:
            for cache in (native._input_store,native._artifacts,native._context,native._physiology):
                cache.cache_clear()
            native.ROOT,native.INPUT_ROOT = root,root/T4_INPUT
            native._input_store = lru_cache(maxsize=1)(lambda: native.InputStore(root/T4_INPUT))
        _ACTIVE_RUNTIME_ROOTS[protocol['protocol_sha256']] = root
    return {'protocol_sha256':protocol['protocol_sha256'],'runtime_root':str(root),
            'input_root':str(root/T4_INPUT),'outcome_access':False}


def build_t4_request(protocol, model_id, case_id, input_multiplier=1., runtime_root=None, **kwargs):
    """Multiply actual source adapter gains; never scale a predicted waveform."""
    from ..paralimbo_upgrade import retrospective_contract as native
    _check_protocol(protocol)
    if not math.isfinite(input_multiplier) or input_multiplier <= 0:
        raise ValueError('Positive finite input multiplier required')
    contract = copy.deepcopy(protocol['native_contract'])
    for name, value in contract['sensory_boundary']['gain_mv_per_contrast'].items():
        contract['sensory_boundary']['gain_mv_per_contrast'][name] = value*input_multiplier
    # The native composer predates relocatable campaigns. Bind its existing
    # input-only factories to the frozen workspace inside this process-local
    # lock, without changing the scientific request or original protocol ID.
    target_root = Path(runtime_root or _ACTIVE_RUNTIME_ROOTS.get(protocol['protocol_sha256'],protocol['root'])).resolve()
    with _COMPOSER_LOCK:
        previous = native.ROOT,native.INPUT_ROOT,native._input_store
        caches = (native._input_store,native._artifacts,native._context,native._physiology)
        changed = target_root!=native.ROOT
        if changed:
            for cache in caches: cache.cache_clear()
            native.ROOT,native.INPUT_ROOT = target_root,target_root/T4_INPUT
            native._input_store = lru_cache(maxsize=1)(lambda: native.InputStore(target_root/T4_INPUT))
        try:
            return native.build_request(contract,model_id,case_id,**kwargs)
        finally:
            if changed:
                native._input_store.cache_clear()
                native.ROOT,native.INPUT_ROOT,native._input_store = previous
                for cache in caches: cache.cache_clear()


def _retained_observation_manifest(protocol, split, retained_root):
    root = Path(retained_root)
    manifest = json.loads(_safe_file(root,f'observations/{split}/manifest.json').read_bytes())
    body = {k:v for k,v in manifest.items() if k!='retention_sha256'}
    if (manifest.get('schema')!='transmission-retained-observations-v1'
            or manifest.get('protocol_sha256')!=protocol['protocol_sha256']
            or manifest.get('split')!=split or manifest.get('retention_sha256')!=identity(body)
            or set(manifest.get('cases',{}))!=set(protocol[split+'_case_ids'])):
        raise ValueError('Retained observation manifest differs from frozen split')
    for cid,row in manifest['cases'].items():
        source = protocol['observation_sources'][cid]
        for kind,expected in [('metadata',source['metadata_sha256']),('response',source['response_sha256'])]:
            if row[kind]['sha256']!=expected or file_hash(_safe_file(root,row[kind]['path']))!=expected:
                raise ValueError('Retained observation differs from frozen source hash')
    return manifest


def retain_observations(protocol, split, budget, *, seal=None, prediction_dir=None):
    """Copy response bytes only after the frozen development/evaluation gate.

    Development requires a sealed scientific plan and both calibration schedules. Evaluation
    requires a complete prediction seal, including explicit failed requests.
    Copies and the manifest are charged to the dedicated campaign budget.
    """
    from .integrity import validate_scientific_plan
    specs = input_specs(protocol,split)
    if split=='evaluation':
        from .scoring import verify_prediction_seal
        if seal is None or prediction_dir is None:
            raise ValueError('Evaluation retention requires sealed predictions')
        verify_prediction_seal(seal,prediction_dir,protocol['protocol_sha256'],
            expected_case_ids=protocol['evaluation_case_ids'],
            allowed_case_ids=protocol['evaluation_case_ids']+protocol['development_case_ids'])
        validate_scientific_plan(budget.root,required=True)
        gate_sha256 = seal['prediction_seal_sha256']
    else:
        from .calibration import validate_schedule
        plan = validate_scientific_plan(budget.root,required=True)
        schedules = json.loads(_safe_file(budget.root,'calibration-schedules.json').read_bytes())
        if set(schedules)!={'banc','paralimbo'}:
            raise ValueError('Both frozen arm calibration schedules required before response retention')
        for arm,schedule in schedules.items():
            validate_schedule(schedule)
            if schedule['arm']!=arm: raise ValueError('Calibration arm identity mismatch')
        gate_sha256 = plan['identity']
    destination = f'observations/{split}/manifest.json'
    if (budget.root/destination).exists():
        retained = _retained_observation_manifest(protocol,split,budget.root)
        if retained['access_gate_sha256']!=gate_sha256:
            raise ValueError('Observation access gate changed after retention')
        return retained
    rows = {}
    for case in specs:
        cid = case['case_id']; frozen = protocol['observation_sources'][cid]
        rows[cid] = {}
        for kind,relative,expected in [('metadata',frozen['metadata_path'],frozen['metadata_sha256']),
                                      ('response',frozen['response_path'],frozen['response_sha256'])]:
            source = _safe_file(protocol['input_root'],relative)
            if file_hash(source)!=expected:
                raise ValueError('Observation source changed after campaign freeze')
            target = f'observations/{split}/{cid}'+('.json' if kind=='metadata' else '.npz')
            receipt = budget.copy_file(source,target)
            if receipt['sha256']!=expected:
                raise ValueError('Observation copy differs from frozen hash')
            rows[cid][kind] = receipt
    body = {'schema':'transmission-retained-observations-v1','protocol_sha256':protocol['protocol_sha256'],
            'split':split,'access_gate_sha256':gate_sha256,'cases':rows}
    manifest = body | {'retention_sha256':identity(body)}
    budget.write_json(destination,manifest)
    return _retained_observation_manifest(protocol,split,budget.root)


def _load_observations(protocol, split, case_ids=None, retained_root=None):
    from ..paralimbo_upgrade.retrospective_contract import InputStore
    from ..paralimbo_upgrade.retrospective_scoring import observation_target
    from ..t4_fit_project import data as t4
    specs = input_specs(protocol,split)
    allowed = {c['case_id'] for c in specs}
    wanted = allowed if case_ids is None else set(case_ids)
    if not wanted <= allowed or not wanted:
        raise ValueError('Outcome request crosses the frozen split')
    retained = _retained_observation_manifest(protocol,split,retained_root) if retained_root is not None else None
    input_root = Path(retained_root)/'frozen/workspace'/T4_INPUT if retained_root is not None else Path(protocol['input_root'])
    store = InputStore(input_root)
    manifest = t4.manifest(store)
    output = {}
    for case in specs:
        cid = case['case_id']
        if cid not in wanted: continue
        folder = 'flash' if split=='development' else 'motion'
        relative = f'observations/{folder}/{cid}.npz'
        metadata_path = (_safe_file(retained_root,retained['cases'][cid]['metadata']['path']) if retained is not None
                         else _safe_file(store.output,relative.replace('.npz','.json')))
        metadata = json.loads(metadata_path.read_bytes())
        frozen = protocol['observation_sources'][cid]
        if (file_hash(metadata_path)!=frozen['metadata_sha256']
                or metadata.get('sha256')!=frozen['response_sha256']
                or metadata.get('observation_identity')!=frozen['observation_identity']):
            raise ValueError('Observation source changed after campaign freeze')
        if metadata.get('observation_identity') != historical_identity({k:v for k,v in metadata.items() if k!='observation_identity'}):
            raise ValueError('Historical outcome identity changed')
        source = (_safe_file(retained_root,retained['cases'][cid]['response']['path']) if retained is not None
                  else _safe_file(store.output,relative))
        if (metadata.get('case_id')!=cid or metadata.get('path')!=relative or
                metadata.get('source_trace_sha256')!=case['source_trace_sha256'] or
                metadata.get('eligible_trial_indices')!=case['eligible_trial_indices'] or
                metadata.get('input_identity')!=manifest['input_identity'] or file_hash(source)!=metadata['sha256']):
            raise ValueError('Historical outcome provenance changed')
        with np.load(source,allow_pickle=False) as z: arrays = {k:z[k] for k in z.files}
        inputs = t4.input_case(store,case)
        t4._validate_outcomes(arrays,case,inputs['time_ms'])
        values, _, indices = observation_target(protocol['native_contract'],case,arrays)
        output[cid] = {'case_id':cid,'time_ms':arrays['time_ms'].copy(),'values_mv':values.copy(),
                       'split':split,'trial_indices':indices,'source_sha256':metadata['sha256'],
                       'historical_observation_identity':metadata['observation_identity']}
    return output


def load_development_observations(protocol, case_ids=None, *, retained_root=None):
    return _load_observations(protocol,'development',case_ids,retained_root)


def load_evaluation_observations(protocol, seal, prediction_dir, *, retained_root=None):
    from .scoring import verify_prediction_seal
    _check_protocol(protocol)
    verify_prediction_seal(seal,prediction_dir,protocol['protocol_sha256'],
                           expected_case_ids=protocol['evaluation_case_ids'],
                           allowed_case_ids=protocol['evaluation_case_ids']+protocol['development_case_ids'])
    if retained_root is not None:
        retained = _retained_observation_manifest(protocol,'evaluation',retained_root)
        if retained['access_gate_sha256']!=seal['prediction_seal_sha256']:
            raise ValueError('Evaluation observation retention is bound to a different prediction seal')
    return _load_observations(protocol,'evaluation',retained_root=retained_root)
