"""Independent decimal-byte accounting, including atomic temporary copies."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

CAMPAIGN_LIMIT_BYTES = 20_000_000_000
RECOVERY_RESERVE_BYTES = 2_000_000


class CampaignStorageExhausted(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


class CampaignBudget:
    def __init__(self, path, limit_bytes=CAMPAIGN_LIMIT_BYTES, recovery_reserve_bytes=RECOVERY_RESERVE_BYTES):
        self.root = Path(path).absolute()
        if self.root.resolve() != self.root:
            raise ValueError('Campaign path must not contain symlinks')
        if type(limit_bytes) is not int or not 0 < limit_bytes <= CAMPAIGN_LIMIT_BYTES:
            raise ValueError('Campaign limit must be a positive integer <= 20 decimal GB')
        if type(recovery_reserve_bytes) is not int or not 0 <= recovery_reserve_bytes < limit_bytes:
            raise ValueError('Recovery reserve must fit the campaign limit')
        self.limit_bytes = limit_bytes
        self.recovery_reserve_bytes = recovery_reserve_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        self.accounting_root = self.root
        for candidate in (self.root, *self.root.parents):
            marker = candidate / '.campaign-budget-anchor.json'
            if marker.exists():
                if marker.is_symlink() or marker.stat().st_nlink != 1:
                    raise ValueError('Campaign accounting anchor must be ordinary')
                anchor = json.loads(marker.read_text())
                if (anchor.get('schema') != 'transmission-shared-campaign-budget-v1' or
                        type(anchor.get('limit_bytes')) is not int or
                        not 0 < anchor['limit_bytes'] <= CAMPAIGN_LIMIT_BYTES):
                    raise ValueError('Invalid campaign accounting anchor')
                self.accounting_root = candidate
                self.limit_bytes = min(self.limit_bytes, anchor['limit_bytes'])
                break

    def path(self, relative):
        relative = Path(relative)
        if relative.is_absolute() or '..' in relative.parts or not relative.parts:
            raise ValueError('Campaign-relative ordinary path required')
        path = self.root / relative
        if path.resolve() != path:
            raise ValueError('Campaign files must not be symlinks')
        if path.exists() and path.is_file() and path.stat().st_nlink != 1:
            raise ValueError('Campaign files must not be hardlink aliases')
        return path

    @contextmanager
    def locked(self):
        lock = self.accounting_root / '.budget.lock'
        if lock.resolve() != lock or (lock.exists() and lock.stat().st_nlink != 1):
            raise ValueError('Campaign accounting lock must be ordinary')
        with lock.open('a+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def snapshot(self):
        used, files = 0, 0
        for folder, directories, names in os.walk(self.accounting_root, followlinks=False):
            for name in directories + names:
                path = Path(folder) / name
                if path.is_symlink():
                    raise ValueError('Unaccounted campaign symlink: ' + str(path))
            for name in names:
                path = Path(folder) / name
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    continue
                if stat.st_nlink != 1:
                    raise ValueError('Unaccounted hardlink: ' + str(path))
                used += stat.st_size
                files += 1
        return dict(limit_bytes=self.limit_bytes, used_bytes=used, files=files,
                    accounting_root=str(self.accounting_root),
                    recovery_reserve_bytes=self.recovery_reserve_bytes,
                    available_bytes=max(0, self.limit_bytes - used - self.recovery_reserve_bytes),
                    physical_free_bytes=shutil.disk_usage(self.root).free)

    def check(self, additional_bytes=0, *, recovery=False):
        if type(additional_bytes) is not int or additional_bytes < 0:
            raise ValueError('Nonnegative integral reservation required')
        snap = self.snapshot()
        reserve = 0 if recovery else self.recovery_reserve_bytes
        if snap['used_bytes'] + additional_bytes + reserve > self.limit_bytes:
            raise CampaignStorageExhausted('Campaign storage ceiling reached')
        if additional_bytes + reserve > snap['physical_free_bytes']:
            raise CampaignStorageExhausted('Physical disk headroom exhausted')
        return snap

    def write_bytes(self, relative, payload, *, recovery=False):
        if not isinstance(payload, bytes):
            raise TypeError('bytes required')
        destination = self.path(relative)
        with self.locked():
            # The full old file remains during atomic replacement.
            self.check(len(payload), recovery=recovery)
            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.atomic-', dir=destination.parent)
            try:
                with os.fdopen(fd, 'wb') as handle:
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
        return {'path': str(relative), 'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)}

    def write_json(self, relative, value, *, recovery=False):
        return self.write_bytes(relative, canonical(value) + b'\n', recovery=recovery)

    def copy_file(self, source, relative):
        source = Path(source)
        destination = self.path(relative)
        with self.locked():
            self.check(source.stat().st_size)
            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.atomic-', dir=destination.parent)
            try:
                with source.open('rb') as src, os.fdopen(fd, 'wb') as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                    dst.flush()
                    os.fsync(dst.fileno())
                if file_sha(source) != file_sha(temporary):
                    raise RuntimeError('Source changed while freezing ' + str(source))
                os.replace(temporary, destination)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return {'path': str(relative), 'sha256': file_sha(destination), 'bytes': destination.stat().st_size}
