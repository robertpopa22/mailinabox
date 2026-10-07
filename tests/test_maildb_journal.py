import importlib.util
from pathlib import Path
import sqlite3

import pytest

spec = importlib.util.spec_from_file_location('maildb_journal',
    Path(__file__).resolve().parents[1] / 'setup/geseidl_edition/components/maildb_journal.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(path):
    connection = sqlite3.connect(path)
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('CREATE TABLE users(email TEXT UNIQUE, quota INTEGER)')
    connection.execute('INSERT INTO users VALUES (?, ?)', ('alpha@example.test', 1024))
    connection.commit()
    return connection


def test_records_survive_journal_migration_and_replay(tmp_path):
    path = tmp_path / 'users.sqlite'
    writer = fixture(path)
    writer.close()
    result = module.migrate(path)
    assert result['records_unchanged'] and result['previous'] == 'wal'
    connection = sqlite3.connect(path)
    assert connection.execute('SELECT * FROM users').fetchall() == [('alpha@example.test', 1024)]
    assert connection.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
    connection.close()
    assert not module.migrate(path)['changed']


def test_active_transaction_refuses_migration_without_record_loss(tmp_path):
    path = tmp_path / 'users.sqlite'
    writer = fixture(path)
    writer.execute('BEGIN IMMEDIATE')
    writer.execute('UPDATE users SET quota=2048')
    with pytest.raises(sqlite3.OperationalError):
        module.migrate(path, timeout=0.1)
    writer.rollback()
    assert writer.execute('SELECT quota FROM users').fetchone()[0] == 1024
    assert writer.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    writer.close()
