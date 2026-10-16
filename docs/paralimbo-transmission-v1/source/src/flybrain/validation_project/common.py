"""Immutable artifacts charged to the existing shared scientific budget."""
from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import shutil
import uuid
import zipfile

import numpy as np

from flybrain.session_storage import SessionBudget, StorageLimitError

GROUP_ID = '6102c51b265d4235bbe2aebd5ffcd74b'
DEFAULT_OUTPUT = 'build/biological-benchmark/finite-validation-v3-r3'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False,
                      ensure_ascii=False).encode() + b'\n'


def identity(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def runtime_files(root):
    root = Path(root)
    files = sorted((root / 'src/flybrain').rglob('*.py'))
    files += [root / p for p in ('scripts/run_finite_validation.py', 'pyproject.toml', 'requirements.lock')
              if (root / p).is_file()]
    return {str(p.relative_to(root)): file_hash(p) for p in files}


def dependency_versions():
    return {name: importlib.metadata.version(name) for name in ('numpy', 'scipy', 'pandas', 'pyarrow')}


class BudgetStore:
    """Content-idempotent files and an atomically consumed workload reservation.

    The private ledger lock is deliberately used for reservation-to-file transfer:
    releasing credit and writing in separate calls would leave a race between jobs.
    The existing SessionBudget remains the single accounting authority.
    """
    def __init__(self, root, output=None, group_id=GROUP_ID, *, limit_bytes=2_000_000_000,
                 runtime_root=None):
        self.root = Path(root).resolve()
        self.output = Path(output or self.root / DEFAULT_OUTPUT)
        if not self.output.is_absolute():
            self.output = self.root / self.output
        self.output = self.output.absolute()
        corpus = self.root / 'build/biological-benchmark/t4-v1'
        if (not self.output.is_relative_to(self.root) or self.output.resolve() != self.output
                or self.output.is_relative_to(corpus) or corpus.is_relative_to(self.output)):
            raise ValueError('Output must be a separate unsymlinked workspace directory')
        self.budget = SessionBudget(self.root, group_id, limit_bytes=limit_bytes)
        self.budget.register(self.output, 'Finite validation project v3')
        self.reservation_id = 'validation-' + hashlib.sha256(str(self.output).encode()).hexdigest()[:20]
        self.runtime_root = Path(runtime_root).resolve() if runtime_root else self.root
        if runtime_root and self.runtime_root != Path(__file__).resolve().parents[3]:
            raise ValueError('Runtime identity must describe the actually loaded source')
        self.source_identity = identity(runtime_files(self.runtime_root))

    def path(self, relative):
        relative = Path(relative)
        if relative.is_absolute() or '..' in relative.parts or not relative.parts:
            raise ValueError('An artifact path must be confined and relative')
        path = self.output / relative
        if path.resolve() != path or not path.is_relative_to(self.output):
            raise ValueError('Symlink or escaping artifact path')
        if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
            raise ValueError('Artifact must be an ordinary unaliased file')
        return path

    def reservation_bytes(self):
        with self.budget._locked() as state:
            return state['reservations'].get(self.reservation_id, {}).get('bytes', 0)

    def reserve(self, size):
        self.budget.reserve(int(size), 'Remaining finite validation workload', self.reservation_id, minimum=True)

    def release(self):
        self.budget.release(self.reservation_id)

    def compact_registration(self):
        """Remove redundant child ledger entries; retain every artifact byte."""
        parent = self.budget._relative(self.output)
        with self.budget._locked() as state:
            if parent not in state['paths']:
                raise ValueError('Recursive project storage registration is missing')
            before = self.budget._usage(state)
            redundant = [name for name in state['paths'] if name != parent
                         and Path(name).is_relative_to(parent)]
            for name in redundant:
                del state['paths'][name]
            if self.budget._usage(state) != before:
                raise ValueError('Storage compaction changed charged artifact coverage')
            self.budget._save(state)
        return {'removed_redundant_registrations': len(redundant),
                'charged_bytes_before_ledger_rewrite': before, 'artifact_bytes_changed': 0}

    def ensure_space(self, size):
        if not isinstance(size, (int, np.integer)) or size < 0:
            raise ValueError('Nonnegative integer storage estimate required')
        with self.budget._locked() as state:
            credit = state['reservations'].get(self.reservation_id, {}).get('bytes', 0)
            if size > self.budget._snapshot(state)['available_bytes'] + credit:
                raise StorageLimitError('Finite workload does not fit shared scientific storage')

    def bytes(self, relative, payload):
        payload = bytes(payload)
        path = self.path(relative)
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError('Immutable artifact differs: ' + str(relative))
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
        with self.budget._locked() as state:
            # The registered parent recursively charges final files and hidden
            # atomic temporaries, including leftovers from interrupted writes.
            if self.budget._relative(self.output) not in state['paths']:
                raise ValueError('Recursive project storage registration is missing')
            if path.exists():
                if path.read_bytes() != payload:
                    raise ValueError('Concurrent immutable artifact differs')
                return path
            credit = state['reservations'].get(self.reservation_id, {}).get('bytes', 0)
            available = self.budget._snapshot(state)['available_bytes'] + credit
            if len(payload) + 4096 > available or len(payload) + 65536 > shutil.disk_usage(path.parent).free:
                raise StorageLimitError('Scientific artifact exceeds shared allowance')
            if credit:
                state['reservations'][self.reservation_id]['bytes'] = max(0, credit-len(payload))
            self.budget._save(state)
            try:
                with temporary.open('xb') as handle:
                    handle.write(payload); handle.flush(); os.fsync(handle.fileno())
                state['peak_bytes'] = max(state['peak_bytes'], self.budget._usage(state))
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
                self.budget._save(state)
        return path

    def json(self, relative, value):
        return self.bytes(relative, canonical(value))

    def npz(self, relative, **arrays):
        checked = {k: np.asarray(v) for k, v in arrays.items()}
        if any(v.dtype.hasobject for v in checked.values()):
            raise ValueError('Object arrays are forbidden')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for name, value in sorted(checked.items()):
                if not name or '/' in name or '\\' in name or '..' in name:
                    raise ValueError('Unsafe array name')
                data = io.BytesIO(); np.lib.format.write_array(data, value, allow_pickle=False)
                info = zipfile.ZipInfo(name + '.npy', (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, data.getvalue())
        return self.bytes(relative, buffer.getvalue())

    def read_json(self, relative):
        return json.loads(self.path(relative).read_bytes())

    def load_npz(self, relative):
        with np.load(self.path(relative), allow_pickle=False) as data:
            return {key: data[key].copy() for key in data.files}

    def digest(self, relative):
        return file_hash(self.path(relative))

    def inventory(self, prefix=None):
        folder = self.output / (prefix or '')
        return {str(p.relative_to(self.output)): file_hash(p) for p in sorted(folder.rglob('*'))
                if p.is_file() and not p.name.startswith('.')}
