"""Durable finite jobs; completed physical identities are never rerun."""
from __future__ import annotations

import json
import sqlite3
import time

from .budget import canonical, digest


class JobLedger:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, specification TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, started REAL, finished REAL, result TEXT, error TEXT)')
        self.db.commit()

    def add(self, specification):
        key = digest(specification)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO jobs(id,specification,state) VALUES (?,?,?)',
                            (key, canonical(specification).decode(), 'pending'))
        return key

    def recover(self):
        with self.db:
            self.db.execute("UPDATE jobs SET state='pending', error='Interrupted; recover from checkpoint' WHERE state='running'")

    def get(self, key):
        row = self.db.execute('SELECT * FROM jobs WHERE id=?', (key,)).fetchone()
        return dict(row) if row else None

    def claim(self, key):
        with self.db:
            result = self.db.execute("UPDATE jobs SET state='running', attempts=attempts+1, started=? WHERE id=? AND state='pending'", (time.time(), key))
        return bool(result.rowcount)

    def complete(self, key, result):
        with self.db:
            self.db.execute("UPDATE jobs SET state='complete', finished=?, result=?, error=NULL WHERE id=? AND state='running'", (time.time(), canonical(result).decode(), key))

    def fail(self, key, error, *, transient=False):
        row = self.get(key)
        if row is None:
            raise KeyError(key)
        if row['state'] != 'running':
            return row['state']
        state = 'pending' if transient and row['attempts'] <= 3 else 'failed'
        with self.db:
            self.db.execute("UPDATE jobs SET state=?, finished=?, error=? WHERE id=? AND state='running'", (state, time.time(), str(error), key))
        return state

    def rows(self):
        return [dict(row) for row in self.db.execute('SELECT * FROM jobs ORDER BY rowid')]

    def counts(self):
        return dict(self.db.execute('SELECT state,count(*) FROM jobs GROUP BY state').fetchall())

    def close(self):
        self.db.close()
