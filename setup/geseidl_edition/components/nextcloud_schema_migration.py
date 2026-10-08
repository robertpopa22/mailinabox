#!/usr/bin/env python3
"""Reconcile seven historical Nextcloud 35 SQLite column definitions.

Uses publisher-generated DDL. Explicit operator migration: quiesce application
writers, retain a coherent backup, prove data/recovery on a private clone first.
Never remove historical tables or app data. Rebuilds are one atomic transaction.
"""
from pathlib import Path

import argparse

import hashlib

import json

import os

import sqlite3

import subprocess

import re

import time

import importlib.util

TABLES = ['oc_share','oc_jobs','oc_preview_locations','oc_preview_versions','oc_previews',
          'oc_share_external','oc_text_documents']

def fingerprint(database):
    result={}
    with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as db:
        for table, in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"):
            digest=hashlib.sha256()
            # Ordering by all columns is deterministic even without a primary key.
            names=sorted(row[1] for row in db.execute('pragma table_info("'+table+'")'))
            columns=','.join('"'+name.replace('"','""')+'"' for name in names)
            count=0
            for row in db.execute('select '+columns+' from "'+table+'" order by '+columns):
                encoded=json.dumps(row,ensure_ascii=False,default=lambda b:{'bytes':b.hex()},separators=(',',':')).encode()
                digest.update(len(encoded).to_bytes(8,'big')+encoded)
                count+=1
            result[table]={'count':count,'sha256':digest.hexdigest()}
    return result

def repair_database(database,ddl):
    before=fingerprint(database)
    with sqlite3.connect(database,timeout=30) as db:
        assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
        # All changes are atomic. Keep every original index and all data.
        db.execute('begin immediate')
        try:
            for table in TABLES:
                sql=ddl[table]
                assert sql.startswith('CREATE TABLE '+table+' (')
                # Native --sql emits one CREATE TABLE followed by CREATE INDEX lines.
                chunks=re.split(r'\n(?=CREATE (?:UNIQUE )?INDEX )',sql.strip())
                create=chunks[0]
                assert ';' not in create and not any(token in create.upper() for token in ['DROP ','ALTER ','INSERT '])
                info=db.execute('pragma table_info("'+table+'")').fetchall()
                old_sql=db.execute('select sql from sqlite_master where type=? and name=?',('table',table)).fetchone()[0]
                if table=='oc_share':
                    if 'DC2Type:json' in old_sql:
                        continue
                    assert 'attributes CLOB' in old_sql and 'DC2Type:json' in create
                    assert db.execute('select count(*) from oc_share where attributes is not null and not json_valid(attributes)').fetchone()[0]==0
                else:
                    idcol=next(c for c in info if c[1]=='id')
                    if idcol[2] in ('BIGINT','BIGINT UNSIGNED') and 'AUTOINCREMENT' not in old_sql:
                        continue
                    assert idcol[2]=='INTEGER' and idcol[5]==1
                    assert db.execute('select count(*) from "'+table+'" where typeof(id)!=\'integer\' or id<0').fetchone()[0]==0
                    assert re.search(r'\bid BIGINT(?: UNSIGNED)? NOT NULL',create)
                    assert 'AUTOINCREMENT' not in create
                assert not db.execute('pragma foreign_key_list("'+table+'")').fetchall()
                assert not db.execute("select 1 from sqlite_master where tbl_name=? and type='trigger'",(table,)).fetchall()
                indexes=[s[0] for s in db.execute("select sql from sqlite_master where tbl_name=? and type='index' and sql is not null",(table,))]
                tmp='geseidl_repair_'+table
                assert not db.execute('select 1 from sqlite_master where name=?',(tmp,)).fetchone()
                db.execute(create.replace('CREATE TABLE '+table+' (','CREATE TABLE '+tmp+' (',1))
                target_names=[c[1] for c in db.execute('pragma table_info("'+tmp+'")')]
                names=[c[1] for c in info]
                assert set(target_names)==set(names),'Publisher columns differ; refusing'
                columns=','.join('"'+n+'"' for n in names)
                db.execute('INSERT INTO "'+tmp+'" ('+columns+') SELECT '+columns+' FROM "'+table+'"')
                assert db.execute('select count(*) from "'+tmp+'"').fetchone()==db.execute('select count(*) from "'+table+'"').fetchone()
                # Compare both directions before dropping the transaction's old table.
                assert db.execute('SELECT '+columns+' FROM "'+table+'" EXCEPT SELECT '+columns+' FROM "'+tmp+'"').fetchone() is None
                assert db.execute('SELECT '+columns+' FROM "'+tmp+'" EXCEPT SELECT '+columns+' FROM "'+table+'"').fetchone() is None
                db.execute('DROP TABLE "'+table+'"')
                db.execute('ALTER TABLE "'+tmp+'" RENAME TO "'+table+'"')
                for index in indexes:
                    db.execute(index)
            assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
            db.commit()
        except BaseException:
            db.rollback()
            raise
    after=fingerprint(database)
    assert before==after,'Application rows changed; keep service quiesced and inspect'
    return after
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code',type=Path,required=True)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--php',required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--backup',type=Path)
    args=parser.parse_args()
    if not args.database.is_file() or args.database.is_symlink():
        parser.error('Existing regular SQLite database required')
    def occ(*params):
        return subprocess.check_output([args.php,str(args.code/'occ'),*params],text=True).strip()
    status=json.loads(occ('status','--output=json'))
    if status['versionstring']!='35.0.1' or status['needsDbUpgrade']:
        parser.error('Reviewed native migration target is Nextcloud 35.0.1')
    if occ('config:system:get','dbtype')!='sqlite3' or Path(occ('config:system:get','datadirectory')).resolve()!=args.database.parent.resolve():
        parser.error('Application/database binding differs')
    ddl={t:occ('db:schema:expected',t,'--sql') for t in TABLES}
    if not args.apply:
        print(json.dumps({'mode':'plan','tables':TABLES,'publisher_ddl':ddl}))
        return
    if not status['maintenance']:
        parser.error('Enable maintenance and quiesce all writers before applying')
    if not args.backup or args.backup.exists() or args.backup.is_symlink():
        parser.error('New explicit backup path required')
    with sqlite3.connect('file:'+str(args.database)+'?mode=ro',uri=True) as src,sqlite3.connect(args.backup) as dst:
        src.backup(dst)
        assert dst.execute('pragma integrity_check').fetchone()[0]=='ok'
    os.chmod(args.backup,0o600)
    result=repair_database(args.database,ddl)
    print(json.dumps({'ok':True,'all_application_rows_identical':True,'table_count':len(result)}))

if __name__=='__main__':
    main()
