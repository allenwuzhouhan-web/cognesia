"""Fetch the public eye-column table on a fresh visual-viewer installation."""
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import shutil

import pandas as pd

from .fetch import checksum, download
from .inspect_data import atomic_write_json

COLUMN_URL = 'https://storage.googleapis.com/flywire-data/codex/data/fafb/783/column_assignment.csv.gz'


def ensure_column_data(root):
    root = Path(root)
    target = root / 'data/raw/codex/column_assignment.csv'
    record = root / 'build/visual_column_source.json'
    if not target.exists():
        compressed = target.with_suffix('.csv.gz')
        if not compressed.exists():
            download(COLUMN_URL, compressed)
        partial = target.with_suffix('.csv.part')
        try:
            with gzip.open(compressed, 'rb') as source, partial.open('wb') as output:
                shutil.copyfileobj(source, output)
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
    digest = checksum(target)
    if record.exists() and json.loads(record.read_text())['sha256'] != digest:
        raise ValueError('Eye column source changed since it was recorded; inspect the source before continuing')
    frame = pd.read_csv(target, nrows=3)
    if not {'root_id', 'hemisphere', 'type', 'column_id', 'p', 'q', 'x', 'y'} <= set(frame.columns):
        raise ValueError('Unexpected eye column source schema')
    if not record.exists():
        atomic_write_json(record, {'url': COLUMN_URL, 'sha256': digest, 'bytes': target.stat().st_size,
                                   'recorded_at': datetime.now(timezone.utc).isoformat()})
    return target
