"""Copy third-party runtime dependencies into the campaign's byte budget.

The worker launches Python with ``-S`` and only these copied site-package roots
on PYTHONPATH. Editable-install .pth files and their executable statements never
run. The Python executable and standard-library files remain an explicit host
dependency, bound by content hashes and verified before each restart.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import site
import sys
import sysconfig
import tempfile

from .budget import canonical, digest, file_sha


def _runtime_files(root):
    """List runtime bytes deterministically without following directory links."""
    root = Path(root).resolve()
    result = []
    for folder, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in {'__pycache__', 'site-packages'})
        for name in directories:
            if (Path(folder) / name).is_symlink():
                raise ValueError('Linked dependency directories require an explicit ordinary copy')
        for name in sorted(names):
            path = Path(folder) / name
            if path.suffix in {'.pyc', '.pyo', '.pth'}:
                continue
            if not path.is_file():
                raise ValueError('Dependencies must consist of ordinary readable files')
            result.append(path)
    return result


def _file_rows(root):
    root = Path(root).resolve()
    return {p.relative_to(root).as_posix(): {'sha256': file_sha(p), 'bytes': p.stat().st_size}
            for p in _runtime_files(root)}


def host_runtime_identity(*, standard_library=None):
    """Pin the interpreter and stdlib, including dynamically loaded extensions."""
    standard_library = Path(standard_library or sysconfig.get_path('stdlib')).resolve()
    body = {'python': sys.version, 'executable': str(Path(sys.executable).resolve()),
            'executable_sha256': file_sha(sys.executable),
            'standard_library': str(standard_library), 'files': _file_rows(standard_library)}
    return body | {'identity': digest(body)}


def freeze_dependencies(budget, *, roots=None, standard_library=None):
    """Return content-bound frozen dependency paths for a ``python -S`` worker.

``roots`` and ``standard_library`` allow small fixtures in tests. Production
uses every site-package root of the preparing interpreter. The whole copy holds
one budget lock and preflights its aggregate size, avoiding a tree scan per file.
"""
    manifest_path = budget.path('frozen/dependencies-manifest.json')
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        validate_dependencies(budget.root, manifest)
        return manifest
    sealed_tree = budget.path('frozen/dependencies/_sealed-manifest.json')
    if sealed_tree.is_file():
        # A crash after atomic tree rename but before the outside manifest write
        # can resume from the manifest committed inside that same tree.
        manifest = json.loads(sealed_tree.read_text())
        validate_dependencies(budget.root, manifest)
        budget.write_json('frozen/dependencies-manifest.json', manifest)
        return manifest
    roots = list(dict.fromkeys(str(Path(p).resolve()) for p in
                               (site.getsitepackages() if roots is None else roots)
                               if Path(p).is_dir()))
    if not roots:
        raise ValueError('No installed dependency roots were found')
    source_files = [(index, Path(root), p) for index, root in enumerate(roots)
                    for p in _runtime_files(root)]
    source_stats = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for _, _, p in source_files}
    total_bytes = sum(size for size, _ in source_stats.values())
    runtime = host_runtime_identity(standard_library=standard_library)
    # Hash manifest overhead is budgeted conservatively before copying.
    overhead = 2 * len(canonical(runtime)) + len(source_files) * 800 + 65_536
    parent = budget.path('frozen')
    parent.mkdir(parents=True, exist_ok=True)
    destination = budget.path('frozen/dependencies')
    if destination.exists():
        raise ValueError('Unsealed dependency tree exists; preserve it and use a successor preparation')
    with budget.locked():
        budget.check(total_bytes + overhead)
        temporary = Path(tempfile.mkdtemp(prefix='.dependencies-', dir=parent))
        rows = {}
        try:
            for index, root, source in source_files:
                relative = Path('root-' + str(index)) / source.relative_to(root)
                target = temporary / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                # copyfile dereferences file links into separately owned bytes.
                shutil.copyfile(source, target, follow_symlinks=True)
                rows[relative.as_posix()] = {'sha256': file_sha(target), 'bytes': target.stat().st_size}
                if rows[relative.as_posix()]['bytes'] != source_stats[str(source)][0]:
                    raise RuntimeError('Dependency changed while copying: ' + str(source))
            for _, _, source in source_files:
                current = source.stat()
                if (current.st_size, current.st_mtime_ns) != source_stats[str(source)]:
                    raise RuntimeError('Dependency installation changed during freeze: ' + str(source))
            body = {'schema': 'transmission-frozen-dependencies-v1',
                    'directory': 'frozen/dependencies', 'files': rows,
                    'pythonpath': ['frozen/dependencies/root-' + str(i) for i in range(len(roots))],
                    'copied_bytes': total_bytes, 'source_roots': roots,
                    'host_runtime': runtime, 'python_flags': ['-S'],
                    'excluded': ['__pycache__', '*.pyc', '*.pyo', '*.pth']}
            manifest = body | {'identity': digest(body)}
            with (temporary / '_sealed-manifest.json').open('wb') as handle:
                handle.write(canonical(manifest) + b'\n')
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    budget.write_json('frozen/dependencies-manifest.json', manifest)
    validate_dependencies(budget.root, manifest, verify_host=False)
    return manifest


def validate_dependencies(output, manifest, *, verify_host=True):
    """Refuse altered or additional executable dependency bytes before launch."""
    if (manifest.get('schema') != 'transmission-frozen-dependencies-v1' or
            manifest.get('identity') != digest({k: v for k, v in manifest.items() if k != 'identity'})):
        raise ValueError('Frozen dependency manifest changed')
    output = Path(output).absolute()
    directory = output / manifest['directory']
    if directory.resolve() != directory:
        raise ValueError('Frozen dependency directory must be ordinary')
    actual = {}
    retained_manifest = directory / '_sealed-manifest.json'
    if not retained_manifest.is_file() or json.loads(retained_manifest.read_text()) != manifest:
        raise ValueError('Frozen dependency tree seal changed')
    for folder, _, names in os.walk(directory, followlinks=False):
        if any(Path(name).suffix in {'.pyc', '.pyo', '.pth'} for name in names):
            raise ValueError('Unregistered executable dependency cache or path file')
    for path in _runtime_files(directory):
        if path == retained_manifest:
            continue
        if path.is_symlink() or path.stat().st_nlink != 1:
            raise ValueError('Frozen dependency aliases are forbidden')
        actual[path.relative_to(directory).as_posix()] = {'sha256': file_sha(path), 'bytes': path.stat().st_size}
    if actual != manifest['files']:
        raise ValueError('Frozen dependency bytes changed')
    if verify_host:
        expected = manifest['host_runtime']
        if host_runtime_identity(standard_library=expected['standard_library']) != expected:
            raise ValueError('Host Python runtime changed; a successor is required')
    return manifest
