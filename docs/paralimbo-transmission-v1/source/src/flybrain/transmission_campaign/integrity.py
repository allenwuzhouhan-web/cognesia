"""Immutable scientific-stage artifacts and a pre-outcome plan seal."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .budget import CampaignBudget, canonical, digest, file_sha

REQUIRED_PLAN_FILES = ('pilot.json', 'site-inventory.json', 'causal-controls.json',
                       'schedule.json', 'sensitivity.json', 'calibration-schedules.json')
SEAL_PATH = 'scientific-plan-seal.json'


def write_once_json(budget, relative, value):
    """Atomically create a canonical JSON value, or verify identical old bytes.

    A resumed worker may call this again with the same value. It cannot change a
    frozen schedule or selection in place after seeing response data.
    """
    payload = canonical(value) + b'\n'
    destination = budget.path(relative)
    with budget.locked():
        if destination.exists():
            if destination.read_bytes() != payload:
                raise ValueError('Immutable scientific artifact changed: ' + str(relative))
        else:
            budget.check(len(payload))
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix='.atomic-seal-', dir=destination.parent)
            try:
                with os.fdopen(descriptor, 'wb') as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, destination)
                directory = os.open(destination.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    return {'path': str(relative), 'sha256': file_sha(destination), 'bytes': len(payload)}


def seal_scientific_plan(budget, relative_paths=REQUIRED_PLAN_FILES):
    """Bind the finite scientific plan before development responses are loaded."""
    paths = list(relative_paths)
    if len(paths) != len(set(paths)) or not set(REQUIRED_PLAN_FILES) <= set(paths):
        raise ValueError('Scientific plan must include every required stage identity once')
    files = {}
    for relative in sorted(paths):
        path = budget.path(relative)
        if not path.is_file():
            raise ValueError('Scientific plan artifact missing: ' + relative)
        files[relative] = {'sha256': file_sha(path), 'bytes': path.stat().st_size}
    body = {'schema': 'transmission-scientific-plan-seal-v1', 'files': files,
            'development_outcomes_opened': False, 'evaluation_outcomes_opened': False,
            'policy': 'No equation, bound, input, candidate schedule, or repair expansion after sealing'}
    seal = body | {'identity': digest(body)}
    write_once_json(budget, SEAL_PATH, seal)
    return validate_scientific_plan(budget.root, required=True)


def validate_scientific_plan(output, *, required=False):
    """Validate every stage byte; an absent seal is allowed only before freezing."""
    budget = CampaignBudget(output)
    path = budget.path(SEAL_PATH)
    if not path.exists():
        if required:
            raise ValueError('Scientific plan must be sealed before response access')
        return None
    seal = json.loads(path.read_text())
    if (seal.get('schema') != 'transmission-scientific-plan-seal-v1' or
            seal.get('identity') != digest({k: v for k, v in seal.items() if k != 'identity'}) or
            seal.get('development_outcomes_opened') is not False or
            seal.get('evaluation_outcomes_opened') is not False or
            not set(REQUIRED_PLAN_FILES) <= set(seal.get('files', {}))):
        raise ValueError('Scientific plan seal changed or is incomplete')
    for relative, record in seal['files'].items():
        source = budget.path(relative)
        if (not source.is_file() or source.stat().st_size != record['bytes'] or
                file_sha(source) != record['sha256']):
            raise ValueError('Sealed scientific plan changed: ' + relative)
    return seal
