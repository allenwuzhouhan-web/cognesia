"""Local, atomic storage for research chats and their captured figures."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import time
import uuid


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value) is not None


class ResearchHistory:
    def __init__(self, directory=None):
        self.directory = Path(directory).expanduser().resolve() if directory is not None else None
        self.index = {}
        self.memory = {}
        self.images = {}
        self.errors = []
        if self.directory is not None:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            for path in self.directory.glob('*/study.json'):
                try:
                    run = self._read(path)
                    if run['id'] != path.parent.name:
                        raise ValueError('Study identity does not match its folder')
                    # A process restart never silently resumes inference or experiments.
                    if run['status'] == 'running':
                        run['status'] = 'interrupted'
                        run['finished_at'] = time.time()
                        run['events'].append({'kind': 'notice', 'time': time.time(),
                            'message': 'The research service restarted before this chat finished. Submitted experiments may still exist in the workbench.'})
                        self.save(run)
                    else:
                        self._index(run)
                except (OSError, ValueError, TypeError, KeyError):
                    self.errors.append('A saved chat could not be read. Its files were left in place.')

    @staticmethod
    def _read(path):
        # Unlimited studies can exceed the former 8 MiB history ceiling. Load
        # our local archive without a separate copy of its complete JSON string.
        with path.open(encoding='utf-8') as stream:
            run = json.load(stream)
        if (not isinstance(run, dict) or not valid_id(run.get('id'))
                or not isinstance(run.get('events'), list)
                or not isinstance(run.get('prompt'), str)
                or not isinstance(run.get('started_at'), (float, int))):
            raise ValueError('Invalid saved chat')
        return run

    def _index(self, run):
        self.index[run['id']] = {'id': run['id'],
            'title': (run.get('report') or {}).get('title') or run.get('prompt', 'Untitled study')[:100],
            'started_at': run['started_at'], 'status': run['status'],
            'has_report': bool(run.get('report')), 'calls_used': run.get('calls_used', 0)}

    def summaries(self):
        return sorted(self.index.values(), key=lambda item: item['started_at'], reverse=True)

    @staticmethod
    def _atomic(path, data):
        temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('xb') as stream:
                os.chmod(temporary, 0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def save(self, run, figures=None):
        if not valid_id(run.get('id')):
            raise ValueError('Invalid study identity')
        if self.directory is None:
            self.memory[run['id']] = deepcopy(run)
            if figures is not None:
                self.images[run['id']] = deepcopy(figures)
        else:
            folder = self.directory / run['id']
            folder.mkdir(exist_ok=True, mode=0o700)
            # Images are written first so the committed JSON never references an
            # image still being written. Existing immutable snapshots are reused.
            for identifier, figure in (figures or {}).items():
                if not re.fullmatch(r'[a-f0-9]{24}', identifier):
                    raise ValueError('Invalid figure identity')
                path = folder / (identifier + '.png')
                if not path.exists():
                    self._atomic(path, figure['png'])
            self._atomic(folder / 'study.json', json.dumps(run, ensure_ascii=False,
                allow_nan=False, separators=(',', ':')).encode('utf-8'))
        self._index(run)

    def get(self, identifier):
        if not valid_id(identifier) or identifier not in self.index:
            return None
        if self.directory is None:
            return deepcopy(self.memory[identifier])
        return self._read(self.directory / identifier / 'study.json')

    def figures(self, run):
        if self.directory is None:
            return deepcopy(self.images.get(run['id'], {}))
        figures = {}
        for metadata in run.get('figures', []):
            identifier = metadata['figure_id']
            if not re.fullmatch(r'[a-f0-9]{24}', identifier):
                raise ValueError('Invalid saved figure identity')
            path = self.directory / run['id'] / (identifier + '.png')
            if path.stat().st_size > 1_500_000:
                raise ValueError('Saved figure exceeds the size limit')
            figures[identifier] = {'metadata': metadata, 'png': path.read_bytes()}
        return figures
