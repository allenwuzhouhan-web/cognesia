"""Reproducible draft schedules; no simulation, inferred biology, or hidden runs."""
from copy import deepcopy
import hashlib
import json

import numpy as np


def plan_replicates(payload, root=None):
    if not isinstance(payload, dict) or set(payload) - {'master_seed', 'replicates', 'options'}:
        raise ValueError('Expected master_seed, replicates and options')
    seed, count = payload.get('master_seed', 7), payload.get('replicates', 3)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 4294967295:
        raise ValueError('master_seed must be an unsigned 32-bit integer')
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 50:
        raise ValueError('replicates must be an integer from 1 to 50')
    options = payload.get('options', {})
    if not isinstance(options, dict):
        raise ValueError('options must be an object')
    if any(key in options for key in ('legacy_protocol', 'from_checkpoint', 'prepare_reference')):
        raise ValueError('Replicate plans require fresh visual experiment starts; replay/checkpoint studies need their own declared design')
    from .visual_server import VisualState
    options = VisualState.options(options, root=root)
    canonical = json.dumps(options, sort_keys=True, allow_nan=False, separators=(',', ':'))
    options_hash = hashlib.sha256(canonical.encode()).hexdigest()
    children = np.random.SeedSequence(seed).spawn(count)
    seeds = [int(child.generate_state(1, dtype=np.uint32)[0]) for child in children]
    if len(set(seeds)) != count:
        raise ValueError('Seed collision; choose a different master seed')
    runs = []
    for index, child_seed in enumerate(seeds):
        request = deepcopy(options)
        request['neural_overrides'] = {**request.get('neural_overrides', {}), 'seed':child_seed}
        runs.append({'replicate_index':index, 'seed':child_seed, 'options':request})
    return {
        'schema_version':1, 'status':'draft', 'master_seed':seed,
        'seed_method':'numpy.SeedSequence.spawn / uint32', 'options_sha256':options_hash,
        'replicates':runs, 'execute_order':'sequential; wait for a terminal job result before starting the next',
        'interpretation':'Computational repeats. The visual solver is deterministic; seed changes optical ray sampling, not individual flies. Biological replication is not supplied.',
        'controls':'Existing paired visual baseline uses the same seed and configuration. Chemical/electrical controls require an explicitly declared comparison design.',
        'required_report_fields':['model_hash','source_hashes','software_hash','seed','options','run_id','completion_status','stability_warnings','clamp_count'],
        'exclusions':'Retain failed, cancelled and unstable runs; report exclusion criteria before comparing results.',
    }
