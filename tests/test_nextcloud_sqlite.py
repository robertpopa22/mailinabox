import importlib.util
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location('sqlite_fix', Path(__file__).parents[1] / 'setup/geseidl_edition/nextcloud_sqlite.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
DDL = 'CREATE TABLE oc_federated_invites (id INTEGER PRIMARY KEY, user_id TEXT, recipient_email TEXT, accepted INTEGER NOT NULL DEFAULT 0)'


def fixture(tmp_path, duplicates=False):
    path = tmp_path / 'db.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE oc_cards (id INTEGER PRIMARY KEY, carddata BLOB)')
        db.execute('INSERT INTO oc_cards VALUES (1, ?)', (b'original card',))
        db.execute('CREATE TABLE oc_job_classes_registry (class_id INTEGER PRIMARY KEY, class_name TEXT)')
        db.execute("INSERT INTO oc_job_classes_registry VALUES (1, 'job')")
        if duplicates:
            db.execute("INSERT INTO oc_job_classes_registry VALUES (2, 'job')")
    return path


def test_additive_idempotent_and_unique(tmp_path):
    path = fixture(tmp_path)
    with patch.object(module.subprocess, 'check_output', return_value=DDL) as publisher:
        module.repair(tmp_path, path, 'php8.5')
        module.repair(tmp_path, path, 'php8.5')
        assert publisher.call_count == 1
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM oc_cards').fetchall() == [(1, b'original card')]
        db.execute("INSERT INTO oc_federated_invites VALUES (1, 'user', 'email', 0)")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO oc_federated_invites VALUES (2, 'user', 'email', 0)")
        db.execute("INSERT INTO oc_federated_invites VALUES (3, 'user', 'email', 1)")


def test_duplicate_jobs_roll_back_table_creation(tmp_path):
    path = fixture(tmp_path, duplicates=True)
    with patch.object(module.subprocess, 'check_output', return_value=DDL):
        with pytest.raises(sqlite3.IntegrityError):
            module.repair(tmp_path, path, 'php8.5')
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='oc_federated_invites'").fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM oc_cards').fetchone()[0] == 1


def test_unexpected_publisher_sql_rejected(tmp_path):
    path = fixture(tmp_path)
    with patch.object(module.subprocess, 'check_output', return_value=DDL + '; DROP TABLE oc_cards'):
        with pytest.raises(RuntimeError):
            module.repair(tmp_path, path, 'php8.5')
