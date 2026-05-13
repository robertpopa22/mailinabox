#!/usr/bin/env python3
"""
Migrate SQLite email index (FTS5 schema) → PostgreSQL emails table.

Usage:
    ./migrate-from-sqlite.py --sqlite /var/lib/email-indexer/live.db --source live
    ./migrate-from-sqlite.py --sqlite /tmp/email_archive.db --source archive

Reads SQLite `emails` table, writes to PG via COPY FROM STDIN (fastest path).
Skips the SQLite emails_fts shadow tables (PG has its own generated tsvector).
Idempotent: ON CONFLICT (source, file_path) DO UPDATE keeps re-runs safe.
"""
from __future__ import annotations
import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

import psycopg

CHUNK = 5000

# Match emails table columns (skipping the GENERATED body_tsv + id).
PG_COLS = [
    "source", "message_id", "folder", "file_path",
    "date_str", "date_ts", "from_addr", "to_addr", "cc_addr",
    "subject", "body_snippet", "size_bytes", "mtime", "indexed_at",
]

# SQLite columns from indexer.py + email_indexer.py schemas.
# Live (MAIL02) has `mtime` + `indexed_at`. Archive (GES051WS) has `indexed_at` only
# (no mtime — mbox files). Detect dynamically.
SQLITE_BASE_COLS = [
    "message_id", "folder", "file_path",
    "date_str", "date_ts", "from_addr", "to_addr", "cc_addr",
    "subject", "body_snippet", "size_bytes",
]


def detect_columns(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute("PRAGMA table_info(emails)")
    return [row[1] for row in cur.fetchall()]


def fmt_ts(ts: float | None) -> str | None:
    if ts is None or ts == 0:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def clean_text(value):
    """PG text fields cannot contain NUL bytes. Strip them. Also trim very long strings."""
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return value
    # Strip NUL bytes — they appear in raw email bodies sometimes
    if "\x00" in value:
        value = value.replace("\x00", "")
    return value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", required=True, type=Path)
    ap.add_argument("--source", required=True, choices=["live", "archive"])
    ap.add_argument("--dsn", default=os.environ.get("PG_DSN_INDEXER", ""),
                    help="psycopg DSN (default $PG_DSN_INDEXER)")
    ap.add_argument("--limit", type=int, default=0, help="Limit rows for testing (0=all)")
    args = ap.parse_args()

    if not args.sqlite.exists():
        sys.exit(f"sqlite db not found: {args.sqlite}")
    if not args.dsn:
        sys.exit("PG_DSN_INDEXER env var or --dsn required")

    t0 = time.time()
    sl = sqlite3.connect(f"file:{args.sqlite}?mode=ro", uri=True)
    sqlite_cols = detect_columns(sl)
    print(f"SQLite columns: {sqlite_cols}", flush=True)

    has_mtime = "mtime" in sqlite_cols
    has_indexed_at = "indexed_at" in sqlite_cols

    total = sl.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
    print(f"SQLite total rows: {total}", flush=True)

    sl.row_factory = sqlite3.Row

    select_cols = list(SQLITE_BASE_COLS)
    if has_mtime:
        select_cols.append("mtime")
    if has_indexed_at:
        select_cols.append("indexed_at")
    sql = f"SELECT {','.join(select_cols)} FROM emails"
    if args.limit:
        sql += f" LIMIT {args.limit}"

    with psycopg.connect(args.dsn) as pg:
        with pg.cursor() as cur:
            # Pre-check: if any rows exist for this source, must use staging+upsert.
            cur.execute("SELECT count(*) FROM emails WHERE source = %s", (args.source,))
            existing = cur.fetchone()[0]
            direct_mode = existing == 0
            if direct_mode:
                print(f"[+] Direct COPY mode (target empty for source={args.source})", flush=True)
                cur.execute("CREATE TEMP TABLE emails_stage (LIKE emails INCLUDING DEFAULTS) ON COMMIT DROP")
                cur.execute("ALTER TABLE emails_stage DROP COLUMN body_tsv")
                cur.execute("ALTER TABLE emails_stage DROP COLUMN id")
                # Drop indexes on staging? It's a TEMP table, no indexes inherited unless INCLUDING INDEXES.
            else:
                print(f"[+] Staging+upsert mode ({existing} existing rows for source={args.source})", flush=True)
                cur.execute("CREATE TEMP TABLE emails_stage (LIKE emails INCLUDING DEFAULTS) ON COMMIT DROP")
                cur.execute("ALTER TABLE emails_stage DROP COLUMN body_tsv")
                cur.execute("ALTER TABLE emails_stage DROP COLUMN id")

            # psycopg default COPY uses text format with proper escaping for embedded
            # tabs/newlines/etc. We just need to strip NUL bytes (PG text fields reject them).
            copy_sql = f"COPY emails_stage ({','.join(PG_COLS)}) FROM STDIN"

            processed = 0
            with cur.copy(copy_sql) as copy:
                for row in sl.execute(sql):
                    date_ts = fmt_ts(row["date_ts"])
                    indexed_at = fmt_ts(row["indexed_at"]) if has_indexed_at else None
                    if indexed_at is None:
                        from datetime import datetime, timezone
                        indexed_at = datetime.now(timezone.utc).isoformat()
                    mtime = row["mtime"] if has_mtime else None

                    record = (
                        args.source,
                        clean_text(row["message_id"]) or None,
                        clean_text(row["folder"]) or "",
                        clean_text(row["file_path"]) or "",
                        clean_text(row["date_str"]),
                        date_ts,
                        clean_text(row["from_addr"]),
                        clean_text(row["to_addr"]),
                        clean_text(row["cc_addr"]),
                        clean_text(row["subject"]),
                        clean_text(row["body_snippet"]),
                        row["size_bytes"] if row["size_bytes"] is not None else None,
                        mtime,
                        indexed_at,
                    )
                    copy.write_row(record)
                    processed += 1
                    if processed % 50000 == 0:
                        print(f"  ... {processed}/{total} ({processed*100/total:.1f}%) "
                              f"@ {processed/(time.time()-t0):.0f} rows/s", flush=True)

            print(f"Staged {processed} rows in {time.time()-t0:.1f}s. {'Direct insert' if direct_mode else 'Upserting'}...", flush=True)
            # Always drop GIN body_tsv index before bulk INSERT; recreate CONCURRENTLY after.
            # Saves >10x time on body_tsv updates per row.
            # NOTE: do NOT commit here — TEMP table is ON COMMIT DROP, would vanish.
            print("[+] Dropping GIN body_tsv index temporarily...", flush=True)
            cur.execute("DROP INDEX IF EXISTS emails_tsv_gin")
            if direct_mode:
                t_ins = time.time()
                cur.execute("""
                    INSERT INTO emails (source, message_id, folder, file_path,
                        date_str, date_ts, from_addr, to_addr, cc_addr,
                        subject, body_snippet, size_bytes, mtime, indexed_at)
                    SELECT source, message_id, folder, file_path,
                        date_str, date_ts, from_addr, to_addr, cc_addr,
                        subject, body_snippet, size_bytes, mtime, indexed_at
                    FROM emails_stage
                """)
                pg.commit()
                print(f"[+] INSERT complete in {time.time()-t_ins:.1f}s.", flush=True)
            else:
                # UPSERT path — chunked to avoid single massive transaction
                t_ins = time.time()
                cur.execute("SELECT count(*) FROM emails_stage")
                stage_total = cur.fetchone()[0]
                chunk_size = 50000
                done = 0
                while done < stage_total:
                    cur.execute("""
                        WITH batch AS (
                            SELECT * FROM emails_stage
                            ORDER BY file_path
                            OFFSET %s LIMIT %s
                        )
                        INSERT INTO emails (source, message_id, folder, file_path,
                            date_str, date_ts, from_addr, to_addr, cc_addr,
                            subject, body_snippet, size_bytes, mtime, indexed_at)
                        SELECT source, message_id, folder, file_path,
                            date_str, date_ts, from_addr, to_addr, cc_addr,
                            subject, body_snippet, size_bytes, mtime, indexed_at
                        FROM batch
                        ON CONFLICT (source, file_path) DO UPDATE SET
                            message_id = EXCLUDED.message_id,
                            folder = EXCLUDED.folder,
                            date_str = EXCLUDED.date_str,
                            date_ts = EXCLUDED.date_ts,
                            from_addr = EXCLUDED.from_addr,
                            to_addr = EXCLUDED.to_addr,
                            cc_addr = EXCLUDED.cc_addr,
                            subject = EXCLUDED.subject,
                            body_snippet = EXCLUDED.body_snippet,
                            size_bytes = EXCLUDED.size_bytes,
                            mtime = EXCLUDED.mtime,
                            indexed_at = EXCLUDED.indexed_at
                    """, (done, chunk_size))
                    pg.commit()
                    done += chunk_size
                    print(f"  upsert progress {min(done, stage_total)}/{stage_total} @ {min(done, stage_total)/(time.time()-t_ins):.0f} rows/s", flush=True)
            print("[+] Recreating GIN body_tsv index CONCURRENTLY...", flush=True)
            t_idx = time.time()
            pg.autocommit = True
            cur.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS emails_tsv_gin ON emails USING GIN (body_tsv)")
            pg.autocommit = False
            print(f"[+] GIN index rebuilt in {time.time()-t_idx:.1f}s.", flush=True)
            row_count = cur.execute(
                "SELECT count(*) FROM emails WHERE source = %s", (args.source,)
            ).fetchone()[0]

    elapsed = time.time() - t0
    print(f"DONE: {processed} rows migrated for source='{args.source}' in {elapsed:.1f}s "
          f"({processed/elapsed:.0f} rows/s). PG total for source: {row_count}.")


if __name__ == "__main__":
    main()
