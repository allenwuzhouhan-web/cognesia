#!/usr/bin/env python3
"""Audit Git upload candidates and optionally export a clean source snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIRS = {'.git', '.venv', '.pytest_cache', '__pycache__', 'data', 'build',
                'runs', 'sessions', 'checkpoints', 'boundaries', 'release', 'dist', '_site'}
SECRET = re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|'
                    rb'AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9_-]{24,}|'
                    rb'cg[kc]_[A-Za-z0-9_-]{32,}|'
                    rb'cgnk_[a-f0-9]{32}\.[A-Za-z0-9_-]{43}|'
                    rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
LOCAL_PATH = re.compile(rb'(?:/Users/|/home/)[A-Za-z0-9_.-]+/')


def audit_file(relative, path):
    issues = []
    if set(relative.parts) & PRIVATE_DIRS or relative.name == '.DS_Store':
        issues.append('private/generated path')
    if ((relative.name.startswith('.env') and relative.name != '.env.example')
            or relative.suffix.lower() in {'.pem', '.key', '.p12', '.pfx'}
            or relative.name in {'credentials.json', 'id_rsa', 'id_ed25519'}):
        issues.append('credential-like filename')
    if path.is_symlink():
        return issues + ['symlink requires explicit review']
    if path.stat().st_size >= 50 * 1024 * 1024:
        return issues + ['file exceeds the 50 MiB source-package limit']
    content = path.read_bytes()
    if SECRET.search(content):
        issues.append('possible credential; value withheld')
    # Binary artwork is excluded from machine-path checks.
    try:
        content.decode('utf-8')
    except UnicodeDecodeError:
        pass
    else:
        if LOCAL_PATH.search(content):
            issues.append('machine-specific home path')
    return issues


def candidates(root):
    top = subprocess.check_output(['git', '-C', str(root), 'rev-parse', '--show-toplevel'], text=True).strip()
    if Path(top).resolve() != root.resolve():
        raise ValueError('Initialize this source folder as its own Git repository first')
    result = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--cached', '--others', '--exclude-standard', '-z'])
    return sorted({Path(p) for p in result.decode().split('\0') if p and (root / p).exists()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Audit only (also the default)')
    parser.add_argument('--export', action='store_true', help='Write an upload folder, ZIP and external checksum manifest')
    args = parser.parse_args()
    files = candidates(ROOT)
    findings = {str(p): issues for p in files if (issues := audit_file(p, ROOT / p))}
    if findings:
        print(json.dumps({'status': 'review required', 'findings': findings}, indent=2))
        raise SystemExit(1)
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    print(f'Upload candidates: {len(files)} files, {sum((ROOT/p).stat().st_size for p in files):,} bytes')
    print('No configured credential-pattern, home-path, oversized-file or forbidden-path findings.')
    print('This bounded scan is not a guarantee that all sensitive information has been detected.')
    if not args.export:
        return
    name = f'Cognesia-v{version}'
    destination = ROOT / 'release' / name
    archive = destination.parent / (name + '.zip')
    manifest_path = destination.parent / (name + '.manifest.json')
    if any(p.exists() for p in (destination, archive, manifest_path)):
        raise FileExistsError('Release output already exists; move the previous export before regenerating')
    destination.mkdir(parents=True)
    entries = []
    for relative in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
        entries.append({'path': relative.as_posix(), 'bytes': target.stat().st_size,
                        'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
        for entry in entries:
            output.write(destination / entry['path'], name + '/' + entry['path'])
    manifest_path.write_text(json.dumps({'version': version, 'files': entries,
        'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
        'scope': 'Current source files only; no Git history, downloaded datasets or local run artifacts.'}, indent=2) + '\n')
    print(f'Upload folder: {destination}\nArchive: {archive}\nManifest: {manifest_path}')


if __name__ == '__main__':
    main()
