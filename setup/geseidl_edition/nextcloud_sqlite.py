#!/usr/bin/env python3
"""Restore additive SQLite schema guarantees missing after historical app upgrades.

Never drop tables, rebuild populated tables, or alter application data. Table DDL
comes from the installed publisher migration schema, not a parallel definition.
"""
import argparse
import os
from pathlib import Path
import sqlite3
import subprocess


def repair(code, database, php):
    with sqlite3.connect(database, timeout=30) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='oc_cards'").fetchone()[0] == 1
        statements = []
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='oc_federated_invites'").fetchone():
            ddl = subprocess.check_output([php, str(code / 'occ'), 'db:schema:expected',
                'oc_federated_invites', '--sql'], text=True).strip()
            if not ddl.startswith('CREATE TABLE oc_federated_invites (') or ';' in ddl:
                raise RuntimeError('Unexpected publisher schema SQL; refusing to apply')
            statements.append(ddl)
        statements += [
            'CREATE UNIQUE INDEX IF NOT EXISTS class_index ON oc_job_classes_registry (class_name)',
            'CREATE UNIQUE INDEX IF NOT EXISTS fed_inv_open_email_uniq ON oc_federated_invites '
            '(user_id, recipient_email) WHERE recipient_email IS NOT NULL AND accepted = 0',
        ]
        db.execute('BEGIN IMMEDIATE')
        for sql in statements:
            db.execute(sql)
        db.commit()
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        print('SQLite additive schema guarantees verified; application rows untouched')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--php', required=True)
    args = parser.parse_args()
    if not args.database.is_file() or args.database.is_symlink():
        parser.error('Expected an existing regular SQLite database')
    if os.geteuid() == 0:
        # Provisioning sources may live below /root. Load this script as root,
        # then perform every application/SQLite operation as the database owner.
        owner = args.database.stat()
        if owner.st_uid == 0:
            parser.error('Database owner must be an application user')
        os.setgroups([])
        os.setgid(owner.st_gid)
        os.setuid(owner.st_uid)
    dbtype = subprocess.check_output([args.php, str(args.code / 'occ'),
        'config:system:get', 'dbtype'], text=True).strip()
    datadir = subprocess.check_output([args.php, str(args.code / 'occ'),
        'config:system:get', 'datadirectory'], text=True).strip()
    if dbtype != 'sqlite3' or Path(datadir).resolve() != args.database.parent.resolve():
        parser.error('Configured application database does not match the target')
    repair(args.code, args.database, args.php)
