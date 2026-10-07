#!/usr/bin/env python3
"""Explicit operator migration for a read-only-consumer mail user database.

Writers and readers must be stopped by the caller. This command changes only
journaling metadata; it never restores an old database or changes table records.
It is not called from package postinst or routine setup.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3


def fingerprint(connection):
    result = {}
    for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        table = '"' + name.replace('"', '""') + '"'
        rows = sorted(repr(row) for row in connection.execute('SELECT * FROM ' + table))
        result[name] = (len(rows), hashlib.sha256('\n'.join(rows).encode()).hexdigest())
    return result


def migrate(database, timeout=5):
    if database.is_symlink() or not database.is_file():
        raise ValueError('Expected an existing regular database')
    connection = sqlite3.connect(database.resolve().as_uri() + '?mode=rw', uri=True,
                                 timeout=timeout, isolation_level=None)
    try:
        previous = connection.execute('PRAGMA journal_mode').fetchone()[0]
        connection.execute('BEGIN EXCLUSIVE')
        before = fingerprint(connection)
        connection.commit()
        current = connection.execute('PRAGMA journal_mode=DELETE').fetchone()[0]
        if current != 'delete':
            raise RuntimeError('Journal mode migration refused')
        if fingerprint(connection) != before:
            raise RuntimeError('Database changed concurrently; preserve current data and investigate')
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Database integrity check failed')
        return {'previous': previous, 'current': current, 'records_unchanged': True,
                'changed': previous != current, 'old_data_restored': False}
    finally:
        connection.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--migrate', action='store_true')
    args = parser.parse_args()
    if not args.migrate:
        raise SystemExit('Explicit --migrate and stopped database consumers are required')
    print(json.dumps(migrate(args.database)))
