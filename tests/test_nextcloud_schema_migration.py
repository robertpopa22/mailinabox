"""Atomic data preservation and refusal, not only expected metadata."""
import importlib.util
from pathlib import Path
import sqlite3

import pytest

spec = importlib.util.spec_from_file_location('schema_migration', Path(__file__).parents[1] /
    'setup/geseidl_edition/components/nextcloud_schema_migration.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(tmp_path):
    path = tmp_path / 'application.sqlite'
    ddl = {}
    with sqlite3.connect(path) as db:
        for table in module.TABLES:
            if table == 'oc_share':
                db.execute('CREATE TABLE oc_share (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, attributes CLOB DEFAULT NULL)')
                db.execute('INSERT INTO oc_share(id,attributes) VALUES (?,?)', (2**40, '[["permissions","download",true]]'))
                ddl[table] = 'CREATE TABLE oc_share (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, attributes CLOB DEFAULT NULL --(DC2Type:json)\n)'
            else:
                db.execute(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, value CLOB)')
                db.execute(f'INSERT INTO {table}(id,value) VALUES (?,?)', (2**40, 'Unicode: șț / 001 / \x00 preserved'))
                ddl[table] = f'CREATE TABLE {table} (id BIGINT UNSIGNED NOT NULL, value CLOB, PRIMARY KEY(id))'
        db.execute('CREATE UNIQUE INDEX existing_unique ON oc_jobs(value) WHERE value IS NOT NULL')
        db.execute('CREATE TABLE historical_metadata (payload BLOB)')
        db.execute('INSERT INTO historical_metadata VALUES (?)', (b'\x00\xff\x01',))
    return path, ddl


def test_all_rows_indexes_large_ids_and_second_apply_survive(tmp_path):
    path, ddl = fixture(tmp_path)
    before = module.fingerprint(path)
    assert module.repair_database(path, ddl) == before
    assert module.repair_database(path, ddl) == before
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute("SELECT sql FROM sqlite_master WHERE name='existing_unique'").fetchone()[0].endswith('WHERE value IS NOT NULL')
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('INSERT INTO oc_jobs(id,value) SELECT ?,value FROM oc_jobs LIMIT 1', (2**40+1,))
        assert db.execute("SELECT type FROM pragma_table_info('oc_jobs') WHERE name='id'").fetchone()[0] == 'BIGINT UNSIGNED'


def test_changed_publisher_columns_roll_back_prior_table_and_every_row(tmp_path):
    path, ddl = fixture(tmp_path)
    before = module.fingerprint(path)
    with sqlite3.connect(path) as db:
        sql_before = db.execute("SELECT sql FROM sqlite_master WHERE name='oc_share'").fetchone()[0]
    ddl['oc_jobs'] = 'CREATE TABLE oc_jobs (id BIGINT UNSIGNED NOT NULL, value CLOB, unreviewed TEXT, PRIMARY KEY(id))'
    with pytest.raises(AssertionError, match='Publisher columns differ'):
        module.repair_database(path, ddl)
    assert module.fingerprint(path) == before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT sql FROM sqlite_master WHERE name='oc_share'").fetchone()[0] == sql_before
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'geseidl_repair_%'").fetchall()


def test_invalid_json_refuses_without_rewriting_or_losing_values(tmp_path):
    path, ddl = fixture(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute('UPDATE oc_share SET attributes=?', ('invalid json',))
    before = module.fingerprint(path)
    with pytest.raises(AssertionError):
        module.repair_database(path, ddl)
    assert module.fingerprint(path) == before
