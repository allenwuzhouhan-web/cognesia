"""Consent-based hardware inventory and enforceable local compute envelopes.

Tiers describe resource ceilings and suggested resolution, never biological
accuracy. Reading the saved policy does not inspect the machine.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import platform
import threading

import psutil


TIERS = (
    dict(id='dummy', label='Dummy', memory_gb=2, threads=1, minimum_ram_gb=0,
         dt_ms=.2, optics_samples=4096, description='Inspect sources and plan experiments; simulation disabled.'),
    dict(id='starter', label='Starter', memory_gb=4, threads=2, minimum_ram_gb=8,
         dt_ms=.1, optics_samples=4096, description='Short, selected-circuit experiments; large models may exceed this budget.'),
    dict(id='plus', label='Plus', memory_gb=8, threads=4, minimum_ram_gb=16,
         dt_ms=.1, optics_samples=4096, description='More memory for selected circuits and recordings.'),
    dict(id='pro', label='Pro', memory_gb=16, threads=8, minimum_ram_gb=32,
         dt_ms=.05, optics_samples=8192, description='Paired whole-model experiments where the model fits.'),
    dict(id='max', label='Max', memory_gb=40, threads=16, minimum_ram_gb=60,
         dt_ms=.025, optics_samples=16384, description='64 GB class laptops; fine time and optical sampling.'),
    dict(id='ultra', label='Ultra', memory_gb=80, threads=32, minimum_ram_gb=120,
         dt_ms=.025, optics_samples=16384, description='128 GB class workstations; larger memory envelope.'),
    dict(id='super', label='Super', memory_gb=160, threads=64, minimum_ram_gb=240,
         dt_ms=.025, optics_samples=16384, description='256 GB class workstations; explicit opt-in only.'),
)
TIER_MAP = {tier['id']: tier for tier in TIERS}


def inspect_hardware(root):
    """Called only following explicit consent. No file, process or identity scan."""
    memory = psutil.virtual_memory()
    return {
        'os': platform.system(), 'architecture': platform.machine(),
        'logical_cpus': psutil.cpu_count(logical=True) or 1,
        'physical_cpus': psutil.cpu_count(logical=False) or 1,
        'ram_gb': round(memory.total / 1e9, 2),
        'available_ram_gb': round(memory.available / 1e9, 2),
        'free_disk_gb': round(psutil.disk_usage(str(root)).free / 1e9, 2),
        'gpu': 'Not probed; the current neural simulation uses CPU kernels.',
    }


def recommend_tier(hardware):
    eligible = [tier for tier in TIERS if hardware['ram_gb'] >= tier['minimum_ram_gb']
                and hardware['logical_cpus'] >= min(tier['threads'], 12)]
    return eligible[-1]['id'] if eligible else 'dummy'


def _number(value, name, lower, upper, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    if not lower <= value <= upper or (integer and int(value) != value):
        raise ValueError(f'{name} must be in [{lower}, {upper}]' + (' and an integer' if integer else ''))
    return int(value) if integer else float(value)


class ComputePolicy:
    def __init__(self, root, operator_limit_gb=40):
        self.root = Path(root)
        self.path = self.root / 'build' / 'runtime' / 'compute-policy.json'
        self.lock = threading.RLock()
        self.operator_limit = _number(operator_limit_gb, 'operator memory limit', .1, 1024)
        self.data = dict(consent=None, hardware=None, tier='starter', memory_gb=min(4., self.operator_limit),
                         threads=2, agent_reserve_gb=0.)
        if self.path.is_file():
            try:
                saved = json.loads(self.path.read_text())
                if saved.get('consent') not in (True, False, None):
                    raise ValueError('Invalid consent')
                self.data.update(consent=saved.get('consent'),
                                 hardware=saved.get('hardware') if saved.get('consent') is True else None)
                self._select(saved, persist=False)
            except (ValueError, TypeError, KeyError, OSError):
                self.data = dict(consent=None, hardware=None, tier='starter',
                                 memory_gb=min(4., self.operator_limit), threads=2, agent_reserve_gb=0.)

    def _save(self):
        from .inspect_data import atomic_write_json
        atomic_write_json(self.path, self.data)

    def snapshot(self):
        with self.lock:
            hardware = self.data['hardware']
            return {
                **deepcopy(self.data), 'tiers': deepcopy(TIERS),
                'recommended': recommend_tier(hardware) if hardware else None,
                'operator_limit_gb': self.operator_limit,
                'scope': 'OS, CPU architecture/count, RAM totals and free disk space only. No personal files, serial numbers, installed apps or network upload.',
                'enforcement': 'CPU worker count and cooperative process-tree RAM guard. Not a CPU percentage, GPU allocation or hard OS sandbox.',
                'accuracy_note': 'Resolution presets change numerical sampling. More compute does not validate the biology. Existing recording and model limits still apply.',
            }

    def consent(self, granted):
        if not isinstance(granted, bool):
            raise ValueError('granted must be true or false')
        with self.lock:
            hardware = inspect_hardware(self.root) if granted else None
            self.data.update(consent=granted, hardware=hardware)
            # Revocation also drops allocations that depended on an inventory.
            self._select({'tier': self.data['tier'] if granted else 'starter'}, persist=False)
            self._save()
            return self.snapshot()

    def _select(self, payload, persist=True):
        tier_id = payload.get('tier', self.data['tier'])
        if tier_id not in TIER_MAP:
            raise ValueError('Unknown compute tier')
        tier = TIER_MAP[tier_id]
        hardware = self.data['hardware']
        if tier_id in ('ultra', 'super') and not hardware:
            raise ValueError('Allow the hardware check before selecting Ultra or Super')
        reserve = _number(payload.get('agent_reserve_gb', self.data['agent_reserve_gb']), 'agent reserve', 0, 256)
        ceiling = min(tier['memory_gb'], self.operator_limit)
        cores = tier['threads']
        if hardware:
            # OS + explicit local-model reservation; model and simulator share RAM.
            ceiling = min(ceiling, hardware['ram_gb'] * .8 - reserve)
            cores = min(cores, hardware['logical_cpus'])
        elif reserve:
            raise ValueError('Allow the hardware check before reserving RAM for a local model')
        if ceiling < .1:
            raise ValueError('The local model reserve leaves no simulation memory')
        memory = _number(payload.get('memory_gb', math.floor(ceiling * 100) / 100), 'memory_gb', .1, ceiling)
        threads = _number(payload.get('threads', cores), 'threads', 1, cores, integer=True)
        self.data.update(tier=tier_id, memory_gb=memory, threads=threads, agent_reserve_gb=reserve)
        if persist:
            self._save()
        return self.snapshot()

    def select(self, payload):
        if not isinstance(payload, dict) or set(payload) - {'tier', 'memory_gb', 'threads', 'agent_reserve_gb'}:
            raise ValueError('Expected tier, memory_gb, threads and/or agent_reserve_gb')
        with self.lock:
            return self._select(payload)

    def apply(self, payload, available_threads):
        """Enforce permissions after request normalization, without changing science."""
        with self.lock:
            if self.data['tier'] == 'dummy':
                raise ValueError('Dummy is inspection only. Choose Starter or above to run an experiment.')
            result = deepcopy(payload)
            if 'legacy_protocol' not in result:
                cap = min(self.data['threads'], available_threads)
                result['threads'] = min(result.get('threads', cap), cap)
            return result

    def suggested_options(self):
        tier = TIER_MAP[self.data['tier']]
        return {'threads': self.data['threads'], 'record_dt_ms': 20,
                'neural_overrides': {'dt': tier['dt_ms']},
                'visual_overrides': {'optics_samples': tier['optics_samples']}}
