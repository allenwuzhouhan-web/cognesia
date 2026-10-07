"""Small polling watcher for application code, configuration, and browser assets.

No platform watcher service or additional package is required. Only application
directories are traversed; simulation outputs and environments are never scanned.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import tomllib


_IGNORED_DIRECTORIES = {
    "__pycache__", "data", "build", "runs", "node_modules", "dist",
    "coverage", "htmlcov", "venv", "env",
}
_IGNORED_SUFFIXES = {
    ".pyc", ".pyo", ".tmp", ".temp", ".bak", ".orig", ".rej", ".swp",
    ".swo", ".log", ".lock",
}
_LARGE_WEB_FILE = 2 * 1024 * 1024


@dataclass(frozen=True)
class _File:
    kind: str
    stat_key: tuple[int, int, int, int]
    digest: str
    content: bytes | None = None


def _ignored(name: str, *, directory: bool = False) -> bool:
    return (
        name.startswith((".", "~", "#"))
        or name.endswith(("~", "#"))
        or (directory and name in _IGNORED_DIRECTORIES)
        or (not directory and Path(name).suffix.lower() in _IGNORED_SUFFIXES)
    )


class ProjectWatcher:
    """Watch supported project inputs, accepting edits after a quiet interval.

    ``poll(now=...)`` supports a monotonic test clock. ``snapshot()`` is a cheap,
    thread-safe read that does not touch the filesystem. ``changed_paths`` lists
    paths relative to ``root`` (absolute paths for an external source install).
    It remains available after a revision is accepted until the next edit.
    Invalid edits leave both revisions unchanged and expose a path-qualified
    ``error``; a subsequent valid edit automatically resumes watching.
    """

    def __init__(
        self,
        root: Path | str,
        source_root: Path | str | None = None,
        debounce_seconds: float = 0.6,
    ) -> None:
        if debounce_seconds < 0:
            raise ValueError("debounce_seconds must be nonnegative")
        self.root = Path(root).resolve()
        self.source_root = Path(source_root or Path(__file__).parent).resolve()
        self.debounce_seconds = float(debounce_seconds)
        self._lock = threading.Lock()
        self._cache: dict[Path, _File] = {}
        self._accepted: dict[Path, _File] = {}
        self._observed: dict[Path, _File] = {}
        self._pending_since: float | None = None
        self._pending = False
        self._changed_paths: list[str] = []
        self._error: str | None = None
        self._invalid: dict[Path, tuple[str, str]] | None = None
        try:
            initial = self._scan()
            self._observed = initial
            try:
                self._validate(initial, sorted(initial))
            except ValueError as exc:
                self._invalid = self._signature(initial)
                self._changed_paths = [self._label(path) for path in sorted(initial)]
                self._error = str(exc)
            else:
                self._accepted = initial
        except OSError as exc:
            self._error = f"Unable to inspect project files: {exc}"
        self._web_revision = self._revision(self._accepted, "web")
        self._backend_revision = self._revision(self._accepted, "backend")

    def _label(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    def _walk(self, directory: Path):
        if directory.is_symlink() or not directory.exists():
            return

        def raise_error(exc: OSError) -> None:
            raise exc

        for parent, dirs, names in os.walk(directory, onerror=raise_error, followlinks=False):
            base = Path(parent)
            dirs[:] = sorted(
                name for name in dirs
                if not _ignored(name, directory=True) and not (base / name).is_symlink()
            )
            for name in sorted(names):
                path = base / name
                if not _ignored(name) and not path.is_symlink():
                    yield path

    def _inputs(self):
        web_root = self.source_root / "web"
        for path in self._walk(self.source_root):
            if path.suffix == ".py":
                yield path, "backend"
            elif path.is_relative_to(web_root):
                yield path, "web"
        for directory in (self.root / "config", self.root / "protocols"):
            for path in self._walk(directory):
                yield path, "backend"
        project_file = self.root / "pyproject.toml"
        if project_file.exists() and not project_file.is_symlink():
            yield project_file, "backend"

    def _scan(self) -> dict[Path, _File]:
        scanned: dict[Path, _File] = {}
        for path, kind in self._inputs():
            stat = path.stat()
            key = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            previous = self._cache.get(path)
            if previous is not None and previous.stat_key == key and previous.kind == kind:
                scanned[path] = previous
                continue
            if kind == "web" and stat.st_size > _LARGE_WEB_FILE:
                # Meshes, textures, and other large assets need no content read.
                digest = hashlib.sha256(repr(key).encode()).hexdigest()
                content = None
            else:
                content = path.read_bytes()
                after = path.stat()
                after_key = (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                if after_key != key:
                    raise OSError(f"{self._label(path)} changed while being read; retrying")
                digest = hashlib.sha256(content).hexdigest()
                if kind == "web":
                    content = None
            scanned[path] = _File(kind, key, digest, content)
        self._cache = scanned
        return scanned

    @staticmethod
    def _signature(files: dict[Path, _File]) -> dict[Path, tuple[str, str]]:
        return {path: (record.kind, record.digest) for path, record in files.items()}

    def _revision(self, files: dict[Path, _File], kind: str) -> str:
        digest = hashlib.sha256()
        for path in sorted(files):
            record = files[path]
            if record.kind == kind:
                digest.update(self._label(path).encode())
                digest.update(b"\0")
                digest.update(record.digest.encode())
                digest.update(b"\0")
        return digest.hexdigest()

    def _validate(self, files: dict[Path, _File], changed: list[Path]) -> None:
        for path in changed:
            record = files.get(path)
            if record is None or record.kind != "backend":
                continue
            try:
                if path.suffix == ".py":
                    compile(record.content, str(path), "exec")
                elif path.suffix.lower() == ".json":
                    json.loads(record.content)
                elif path.suffix.lower() == ".toml":
                    tomllib.loads(record.content.decode("utf-8"))
                elif path.suffix.lower() in {".yaml", ".yml"}:
                    import yaml  # Already a flybrain runtime dependency.

                    yaml.safe_load(record.content)
            except Exception as exc:
                raise ValueError(f"{self._label(path)}: {exc}") from exc

    def _status(self) -> dict:
        return {
            "enabled": True,
            "web_revision": self._web_revision,
            "backend_revision": self._backend_revision,
            "pending": self._pending,
            "changed_paths": list(self._changed_paths),
            "error": self._error,
        }

    def snapshot(self) -> dict:
        with self._lock:
            return self._status()

    def poll(self, now: float | None = None) -> dict:
        current_time = time.monotonic() if now is None else float(now)
        with self._lock:
            try:
                current = self._scan()
            except (OSError, ValueError) as exc:
                self._error = f"Unable to inspect project files: {exc}"
                return self._status()
            signature = self._signature(current)
            if signature != self._signature(self._observed):
                self._observed = current
                self._pending_since = current_time
                self._invalid = None
                self._error = None
            accepted_signature = self._signature(self._accepted)
            changed = sorted(
                path for path in accepted_signature.keys() | signature.keys()
                if accepted_signature.get(path) != signature.get(path)
            )
            if not changed:
                self._pending = False
                self._pending_since = None
                self._error = None
                return self._status()
            self._changed_paths = [self._label(path) for path in changed]
            if self._invalid == signature:
                self._pending = False
                return self._status()
            self._pending = True
            if self._pending_since is None:
                self._pending_since = current_time
            if current_time - self._pending_since < self.debounce_seconds:
                return self._status()
            try:
                self._validate(current, changed)
            except ValueError as exc:
                self._invalid = signature
                self._error = str(exc)
                self._pending = False
                return self._status()
            self._accepted = current
            self._web_revision = self._revision(current, "web")
            self._backend_revision = self._revision(current, "backend")
            self._pending = False
            self._pending_since = None
            self._error = None
            return self._status()
