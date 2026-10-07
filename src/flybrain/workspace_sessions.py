"""Portable, local research-session archives. Saving never advances the engine."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from uuid import uuid4
import zipfile

IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,180}$")
MAX_ARCHIVE_INPUT = 2 * 1024**3


def checked_session(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('notes'), dict):
        raise ValueError('A session needs a notes document and workspace state')
    document = payload['notes']
    if document.get('schema_version') != 1 or not isinstance(document.get('notes'), list):
        raise ValueError('Unsupported notes format')
    title = document.get('session_title', '')
    if not isinstance(title, str) or len(title) > 240 or len(document['notes']) > 1000:
        raise ValueError('Session title or note count exceeds the supported limit')
    ids = set()
    for note in document['notes']:
        if not isinstance(note, dict) or not IDENTIFIER.fullmatch(str(note.get('id', ''))):
            raise ValueError('Every note needs a safe unique identifier')
        if note['id'] in ids:
            raise ValueError('Duplicate note identifier')
        ids.add(note['id'])
        if not isinstance(note.get('text'), str) or len(note['text']) > 100000:
            raise ValueError('Note text must contain at most 100,000 characters')
        anchor = note.get('anchor')
        if not isinstance(anchor, dict):
            raise ValueError('Every note needs its saved context')
        linked_runs=anchor.get('run_ids', [])
        if not isinstance(linked_runs,list) or len(linked_runs)>100:
            raise ValueError('Invalid linked recordings')
        for run in [anchor.get('run_id'),*linked_runs]:
            if run is not None and not IDENTIFIER.fullmatch(str(run)):
                raise ValueError('Invalid recording identifier')
        if anchor.get('time_ms') is not None:
            value = anchor['time_ms']
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('Note time must be finite')
    workspace = payload.get('workspace', {})
    if not isinstance(workspace, dict):
        raise ValueError('Workspace state must be an object')
    run = workspace.get('run_id')
    if run is not None and not IDENTIFIER.fullmatch(str(run)):
        raise ValueError('Invalid workspace recording identifier')
    # Reject NaN and unsupported objects before writing any file.
    json.dumps(payload, allow_nan=False)
    return document, workspace


def note_documents(document):
    """Extractive summary and explicit context links; never invent a conclusion."""
    title = document.get('session_title') or 'Research session'
    groups = defaultdict(list)
    notes = document['notes']
    for note in notes:
        anchor = note['anchor']
        runs=anchor.get('run_ids') or []
        groups[(anchor.get('run_id') or (' + '.join(runs) if runs else 'Unrecorded draft'), anchor.get('panel_title') or anchor.get('panel_id') or 'Workspace')].append(note)
    summary = [f'# {title}', '', f'{len(notes)} notes across {len(groups)} recording/view groups.', '',
               'Summary excerpts come from your notes. Connections below mean shared recording and view context, not biological causation.', '']
    full = [f'# {title} — original notes', '']
    links = []
    for (run, panel), items in groups.items():
        summary += [f'## {run} · {panel}', '']
        for note in items:
            text = ' '.join(note['text'].split())
            excerpt = text if len(text) <= 220 else text[:217] + '…'
            time = note['anchor'].get('time_ms')
            stamp = f' at {time:g} ms' if isinstance(time, (int, float)) else ''
            summary.append(f'- [{excerpt or "Empty note"}](Notes.md#note-{note["id"]}){stamp}')
        summary.append('')
        for first, second in zip(items, items[1:]):
            links.append({'from': first['id'], 'to': second['id'], 'relationship': 'shared recording and view', 'run_id': run, 'panel': panel})
    summary += ['## Connected observations', '']
    summary += [f'- [Note {link["from"]}](Notes.md#note-{link["from"]}) ↔ [Note {link["to"]}](Notes.md#note-{link["to"]}) — {link["panel"]}, {link["run_id"]}.' for link in links] or ['No notes share a recording and view yet.']
    for note in notes:
        full += [f'<a id="note-{note["id"]}"></a>', f'## Note {note["id"]}', '', note['text'], '',
                 'Saved context:', '```json', json.dumps(note['anchor'], ensure_ascii=False, indent=2), '```', '']
    return '\n'.join(summary) + '\n', '\n'.join(full), links


def session_archive_path(root, session_id):
    if not IDENTIFIER.fullmatch(session_id):
        raise ValueError('Invalid saved-session identifier')
    return Path(root) / 'build' / 'saved-sessions' / f'{session_id}.cognesia-session.zip'


def save_workspace_session(root, payload):
    document, workspace = checked_session(payload)
    root = Path(root).resolve()
    runs = sorted({a for a in [workspace.get('run_id'), *(n['anchor'].get('run_id') for n in document['notes']), *(run for n in document['notes'] for run in n['anchor'].get('run_ids', []))] if a})
    files, missing, total = [], [], 0
    for run in runs:
        directory = root / 'runs' / run
        if directory.is_symlink() or not directory.is_dir():
            missing.append(run)
            continue
        # Include the immutable recording and its saved anatomy, not global source datasets.
        for path in sorted(directory.rglob('*')):
            if not path.is_file():
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
                raise ValueError('Recording contains an external file link; archive was not created')
            if path.name.endswith(('.tmp', '.lock')):
                continue
            total += path.stat().st_size
            if total > MAX_ARCHIVE_INPUT:
                raise ValueError('Recordings exceed the 2 GiB session archive limit; save fewer recording-linked notes together')
            files.append((path, str(Path('recordings') / run / path.relative_to(directory))))
    session_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:12]
    target = session_archive_path(root, session_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    summary, full, connections = note_documents(document)
    manifest = {'schema_version': 1, 'session_id': session_id, 'created_at': datetime.now(timezone.utc).isoformat(),
                'title': document.get('session_title', ''), 'notes_count': len(document['notes']), 'recordings': runs,
                'unavailable_recordings': missing, 'connections': connections, 'files': [],
                'scope': 'Workspace, exact notes, extractive summary, and existing recording files. Full source datasets and live engine memory are not bundled.'}
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
            for name, value in [('workspace.json', workspace), ('notes.json', document), ('connections.json', connections)]:
                archive.writestr(name, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
            archive.writestr('Summary.md', summary)
            archive.writestr('Notes.md', full)
            archive.writestr('README.txt', 'Open Summary.md for the linked session summary. Notes.md and notes.json preserve the original notes. workspace.json records draft, layout, display and playback state. recordings/ contains the linked saved experiments. Source model identifiers remain in their manifests. This archive does not certify biological validity.\n')
            for path, name in files:
                checksum = hashlib.sha256()
                size = 0
                before = path.stat()
                with path.open('rb') as source, archive.open(name, 'w', force_zip64=True) as output:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        checksum.update(chunk); size += len(chunk); output.write(chunk)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('Recording changed during saving; retry after the recording finishes')
                manifest['files'].append({'path': name, 'bytes': size, 'sha256': checksum.hexdigest()})
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        temporary.replace(target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {'session_id': session_id, 'download_url': f'/api/workspace-sessions/{session_id}/download',
            'bytes': target.stat().st_size, 'recording_bytes': total, 'summary': summary,
            'unavailable_recordings': missing, 'path': str(target)}
