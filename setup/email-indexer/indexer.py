#!/usr/bin/env python3
"""
Email indexer for Mail-in-a-Box (Dovecot maildir) → PostgreSQL FTS (tsvector).

Modes:
  --incremental   Scan only files with mtime > last_run_ts (default, ~10min cron)
  --full          Scan all files + reconcile deletions (nightly)
  --stats         Print index statistics
  --search QUERY  Quick FTS query test (websearch_to_tsquery)

Maildir layout (Mail-in-a-Box / Dovecot):
  /home/user-data/mail/mailboxes/<domain>/<user>/{cur,new,tmp}/
  /home/user-data/mail/mailboxes/<domain>/<user>/.<FolderName>/{cur,new,tmp}/

Each file = one RFC822 message. Filename includes Dovecot UID + flags
(e.g. "1234.M567P890.host:2,S"). Flags change file rename → mtime updates.

Output: PostgreSQL database `emails` on MAIL02 (10.0.1.89:5432).
DSN read from env PG_DSN, or fallback to /etc/mailinabox/postgres.env
(line `PG_DSN_INDEXER=...`).

Schema (managed by setup/postgres/schema.sql):
  emails(id, source ENUM('live','archive'), message_id, folder, file_path,
         date_str, date_ts TIMESTAMPTZ, from_addr, to_addr, cc_addr,
         subject, body_snippet, size_bytes, mtime, indexed_at,
         body_tsv GENERATED ALWAYS AS (...) STORED)
  UNIQUE (source, file_path)
  indexer_meta(source, key, value) PK(source, key)

This script ALWAYS writes source='live' (Dovecot live maildir on MAIL02).
The archive indexer on GES051WS writes source='archive'.
"""
from __future__ import annotations

import argparse
import email as email_mod
import email.policy as email_policy
import logging
import multiprocessing
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime, getaddresses
from pathlib import Path

import psycopg
from psycopg import sql

DEFAULT_MAILBOX_ROOT = Path(os.environ.get("MAILBOX_ROOT", "/home/user-data/mail/mailboxes"))
DEFAULT_PG_ENV_FILE = Path(os.environ.get("PG_ENV_FILE", "/etc/mailinabox/postgres.env"))
SOURCE = "live"  # this indexer always targets the live Dovecot maildir on MAIL02

# Skip these mailbox subfolders (huge or noisy, low value to index)
SKIP_FOLDERS = {".Trash", ".Spam", ".Junk"}

MAX_BODY_LEN = 8000
MAX_FILE_BYTES = 5 * 1024 * 1024  # skip files > 5 MB (rare, mostly mailing lists with big attachments)
COMMIT_BATCH = 500  # rows per executemany batch (PG round-trip)

# Worker count: cap at 80% of cores to leave headroom for Dovecot/Postfix
DEFAULT_WORKERS = max(2, int((os.cpu_count() or 4) * 0.8))
# Files per worker batch — large batches amortize IPC cost
WORKER_BATCH_SIZE = 200

HTML_TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
NUL_RE = re.compile(r"\x00")

log = logging.getLogger("email_indexer")


# ----- DSN / connection helpers -----------------------------------------------

def _read_env_file(path: Path) -> dict[str, str]:
    """Parse a shell-style env file (KEY=VALUE per line). Strips quotes."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):]
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip()
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                out[k.strip()] = v
    except OSError:
        pass
    return out


def resolve_dsn(env_file: Path = DEFAULT_PG_ENV_FILE) -> str:
    """Return PostgreSQL DSN from env or /etc/mailinabox/postgres.env."""
    dsn = os.environ.get("PG_DSN", "").strip()
    if dsn:
        return dsn
    env = _read_env_file(env_file)
    dsn = env.get("PG_DSN_INDEXER") or env.get("PG_DSN") or ""
    if not dsn:
        raise RuntimeError(
            f"No PG_DSN in env and {env_file} missing/empty. "
            "Expected PG_DSN_INDEXER=... in the env file."
        )
    return dsn


def get_pg_conn(dsn: str | None = None) -> psycopg.Connection:
    """Open a psycopg connection. Application_name eases pg_stat_activity triage."""
    if dsn is None:
        dsn = resolve_dsn()
    conn = psycopg.connect(
        dsn,
        autocommit=False,
        application_name="email-indexer-mail02",
    )
    # Smoke test
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()
    return conn


# ----- text sanitation --------------------------------------------------------

def _clean(value: str) -> str:
    """Strip NUL bytes (illegal in PG TEXT) and normalize whitespace edges.

    NULs occur in malformed RFC822 bodies (e.g. binary chunks misdeclared as
    text/plain). PostgreSQL rejects them with `invalid byte sequence`.
    """
    if not value:
        return ""
    if "\x00" in value:
        value = NUL_RE.sub("", value)
    return value


# ----- indexer_meta accessors -------------------------------------------------

def get_meta(conn: psycopg.Connection, key: str, default: str = "") -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT value FROM indexer_meta WHERE source = %s AND key = %s",
            (SOURCE, key),
        )
        row = cur.fetchone()
    return row[0] if row else default


def set_meta(conn: psycopg.Connection, key: str, value: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO indexer_meta (source, key, value)
            VALUES (%s, %s, %s)
            ON CONFLICT (source, key) DO UPDATE SET value = EXCLUDED.value
            """,
            (SOURCE, key, value),
        )


# ----- maildir traversal ------------------------------------------------------

def derive_folder_label(maildir_path: Path, root: Path) -> str:
    """Convert /…/geseidl.ro/robert.popa/.Archive/cur → geseidl.ro/robert.popa/Archive."""
    try:
        rel = maildir_path.relative_to(root)
    except ValueError:
        return str(maildir_path)
    parts = rel.parts
    # Drop trailing cur/new/tmp
    if parts and parts[-1] in ("cur", "new", "tmp"):
        parts = parts[:-1]
    # Convert leading-dot subfolders → no-dot (Dovecot convention)
    cleaned = [p[1:] if p.startswith(".") and len(p) > 1 else p for p in parts]
    return "/".join(cleaned) if cleaned else "INBOX"


def walk_maildir_files(root: Path, since_mtime: float = 0.0):
    """Yield (file_path, mtime, folder_label) for every message file under root.

    Only walks `cur/` and `new/` (skip `tmp/` — in-flight deliveries).
    Skips folders listed in SKIP_FOLDERS.
    """
    if not root.exists():
        return
    # Iterate every domain/user/{cur,new,...} via two-level scan
    for domain_dir in root.iterdir():
        if not domain_dir.is_dir():
            continue
        for user_dir in domain_dir.iterdir():
            if not user_dir.is_dir():
                continue
            # INBOX (top-level cur/new) + subfolders (.<Folder>/cur,new)
            for sub in user_dir.iterdir():
                if not sub.is_dir():
                    continue
                if sub.name in SKIP_FOLDERS:
                    continue
                # Identify maildir leaves (those containing cur/)
                leaves: list[Path] = []
                if sub.name in ("cur", "new"):
                    leaves.append(sub)
                elif (sub / "cur").is_dir():
                    leaves.append(sub / "cur")
                    if (sub / "new").is_dir():
                        leaves.append(sub / "new")
                for leaf in leaves:
                    folder_label = derive_folder_label(leaf, root)
                    try:
                        with os.scandir(leaf) as it:
                            for entry in it:
                                if not entry.is_file(follow_symlinks=False):
                                    continue
                                try:
                                    stat = entry.stat(follow_symlinks=False)
                                except OSError:
                                    continue
                                if since_mtime and stat.st_mtime <= since_mtime:
                                    continue
                                yield Path(entry.path), stat.st_mtime, folder_label
                    except (PermissionError, FileNotFoundError):
                        continue


# ----- RFC822 parsing ---------------------------------------------------------

def _decode_header(val) -> str:
    if not val:
        return ""
    try:
        return str(val)
    except Exception:
        return ""


def _addrs(headers, name: str) -> str:
    vals = headers.get_all(name) or []
    if not vals:
        return ""
    pairs = getaddresses(vals)
    return ", ".join(addr for _, addr in pairs if addr)


def _extract_body(msg) -> str:
    """Extract plain-text body (or stripped HTML fallback), capped at MAX_BODY_LEN."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                try:
                    body = part.get_content()
                except Exception:
                    body = part.get_payload(decode=True) or b""
                    if isinstance(body, bytes):
                        body = body.decode(part.get_content_charset() or "utf-8", errors="replace")
                if body:
                    break
        if not body:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    try:
                        html = part.get_content()
                    except Exception:
                        html = part.get_payload(decode=True) or b""
                        if isinstance(html, bytes):
                            html = html.decode(part.get_content_charset() or "utf-8", errors="replace")
                    body = HTML_TAG_RE.sub(" ", html)
                    if body:
                        break
    else:
        try:
            body = msg.get_content() if msg.get_content_type().startswith("text/") else ""
        except Exception:
            body = ""
        if msg.get_content_type() == "text/html":
            body = HTML_TAG_RE.sub(" ", body)
    body = WS_RE.sub(" ", body).strip()
    return body[:MAX_BODY_LEN]


def _safe_header(msg, name: str) -> str:
    """Robust header read — Python 3.12 default policy crashes on some malformed headers."""
    try:
        return _decode_header(msg.get(name, ""))
    except Exception:
        return ""


def _safe_addrs(msg, name: str) -> str:
    try:
        return _addrs(msg, name)
    except Exception:
        return ""


def parse_email_file(fpath: Path) -> dict | None:
    try:
        size = fpath.stat().st_size
    except OSError:
        return None
    if size > MAX_FILE_BYTES:
        return None
    try:
        with fpath.open("rb") as f:
            raw = f.read()
    except (PermissionError, OSError):
        return None
    # compat32 policy is the legacy parser — tolerant of malformed RFC822/2822
    # headers that crash the strict 'default' policy on Python 3.12+
    # (e.g. IndexError in _header_value_parser.parse_message_id on weird Message-IDs).
    try:
        msg = email_mod.message_from_bytes(raw, policy=email_policy.compat32)
    except Exception:
        return None
    try:
        date_str = _safe_header(msg, "Date")
        date_ts: float = 0.0
        if date_str:
            try:
                dt = parsedate_to_datetime(date_str)
                if dt:
                    date_ts = dt.timestamp()
            except (TypeError, ValueError):
                pass
        try:
            body = _extract_body(msg)
        except Exception:
            body = ""
        return {
            "message_id": _clean(_safe_header(msg, "Message-ID").strip()),
            "date_str": _clean(date_str),
            "date_ts": date_ts,  # float unix-epoch; converted to TIMESTAMPTZ at upsert
            "from_addr": _clean(_safe_addrs(msg, "From")),
            "to_addr": _clean(_safe_addrs(msg, "To")),
            "cc_addr": _clean(_safe_addrs(msg, "Cc")),
            "subject": _clean(_safe_header(msg, "Subject").strip()),
            "body_snippet": _clean(body),
            "size_bytes": size,
        }
    except Exception:
        return None


# ----- upsert -----------------------------------------------------------------

INSERT_SQL = """
INSERT INTO emails (
    source, message_id, folder, file_path,
    date_str, date_ts, from_addr, to_addr, cc_addr,
    subject, body_snippet, size_bytes, mtime, indexed_at
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (source, file_path) DO UPDATE SET
    message_id  = EXCLUDED.message_id,
    folder      = EXCLUDED.folder,
    date_str    = EXCLUDED.date_str,
    date_ts     = EXCLUDED.date_ts,
    from_addr   = EXCLUDED.from_addr,
    to_addr     = EXCLUDED.to_addr,
    cc_addr     = EXCLUDED.cc_addr,
    subject     = EXCLUDED.subject,
    body_snippet= EXCLUDED.body_snippet,
    size_bytes  = EXCLUDED.size_bytes,
    mtime       = EXCLUDED.mtime,
    indexed_at  = EXCLUDED.indexed_at
"""


def _ts_to_dt(ts: float | None) -> datetime | None:
    """SQLite stored UNIX epoch (float). PG wants TIMESTAMPTZ. NULL for unparsable."""
    if not ts or ts <= 0:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _row_tuple(file_path: str, folder: str, mtime: float, parsed: dict, now: float) -> tuple:
    return (
        SOURCE,
        parsed["message_id"] or None,
        _clean(folder),
        _clean(file_path),
        parsed["date_str"] or None,
        _ts_to_dt(parsed["date_ts"]),
        parsed["from_addr"] or None,
        parsed["to_addr"] or None,
        parsed["cc_addr"] or None,
        parsed["subject"] or None,
        parsed["body_snippet"] or None,
        int(parsed["size_bytes"]),
        _ts_to_dt(mtime),
        _ts_to_dt(now),
    )


def flush_batch(conn: psycopg.Connection, rows: list[tuple]) -> int:
    """executemany INSERT…ON CONFLICT for a row batch. Commits on success."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(INSERT_SQL, rows)
    conn.commit()
    return len(rows)


# ----- reconcile (full mode) --------------------------------------------------

def reconcile_deletions(conn: psycopg.Connection, root: Path) -> int:
    """Remove rows whose file_path no longer exists. Only safe in --full mode."""
    deleted = 0
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, file_path FROM emails WHERE source = %s",
            (SOURCE,),
        )
        rows = cur.fetchall()
    stale_ids: list[int] = []
    for row_id, fpath in rows:
        if not Path(fpath).exists():
            stale_ids.append(row_id)
    if stale_ids:
        # Delete in chunks to avoid massive single statements
        with conn.cursor() as cur:
            for i in range(0, len(stale_ids), 5000):
                chunk = stale_ids[i:i + 5000]
                cur.execute(
                    "DELETE FROM emails WHERE source = %s AND id = ANY(%s)",
                    (SOURCE, chunk),
                )
                deleted += cur.rowcount or 0
        conn.commit()
    return deleted


# ----- multiprocessing parse workers ------------------------------------------

def _worker_parse_batch(tasks: list[tuple[str, float, str]]) -> list[tuple[str, float, str, dict | None]]:
    """Worker: parse a batch of files. Returns list of (path, mtime, folder, parsed_or_None).

    Top-level function so multiprocessing.Pool can pickle it. Catches all
    exceptions per-file so a single bad message cannot poison the batch.
    """
    out: list[tuple[str, float, str, dict | None]] = []
    for fpath_str, mtime, folder in tasks:
        try:
            parsed = parse_email_file(Path(fpath_str))
        except Exception:
            parsed = None
        out.append((fpath_str, mtime, folder, parsed))
    return out


def _chunked(iterable, size: int):
    """Yield lists of up to `size` items from iterable."""
    buf: list = []
    for item in iterable:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


# ----- main run ---------------------------------------------------------------

def run_indexer(mode: str, mailbox_root: Path, workers: int = DEFAULT_WORKERS) -> dict:
    t0 = time.time()
    conn = get_pg_conn()
    try:
        last_run = float(get_meta(conn, "last_incremental_ts", "0") or 0)
        since = 0.0 if mode == "full" else max(0.0, last_run - 60.0)  # 60s overlap
        log.info(
            "Mode=%s | root=%s | since_mtime=%.0f | workers=%d | batch=%d | source=%s",
            mode, mailbox_root, since, workers, WORKER_BATCH_SIZE, SOURCE,
        )

        processed = 0
        skipped = 0
        pending_rows: list[tuple] = []

        # Tasks streamed from walk → string paths (pickle-friendly for workers)
        def task_iter():
            for fpath, mtime, folder in walk_maildir_files(mailbox_root, since_mtime=since):
                yield (str(fpath), mtime, folder)

        if workers <= 1:
            # Fallback single-threaded path
            for fpath_str, mtime, folder in task_iter():
                try:
                    parsed = parse_email_file(Path(fpath_str))
                    if parsed is None:
                        skipped += 1
                        continue
                    pending_rows.append(_row_tuple(fpath_str, folder, mtime, parsed, time.time()))
                except Exception as e:
                    log.warning("Skipping %s: %s", fpath_str, e)
                    skipped += 1
                    continue
                processed += 1
                if len(pending_rows) >= COMMIT_BATCH:
                    flush_batch(conn, pending_rows)
                    pending_rows = []
                if processed % 10000 == 0:
                    log.info("Progress: %d processed, %d skipped (%.1fs)", processed, skipped, time.time() - t0)
        else:
            # Multiprocessing path — workers parse files (CPU-bound), main writes DB (I/O serialized)
            ctx = multiprocessing.get_context("fork")
            with ctx.Pool(processes=workers) as pool:
                batches = _chunked(task_iter(), WORKER_BATCH_SIZE)
                for batch_result in pool.imap_unordered(_worker_parse_batch, batches):
                    for fpath_str, mtime, folder, parsed in batch_result:
                        if parsed is None:
                            skipped += 1
                            continue
                        try:
                            pending_rows.append(_row_tuple(fpath_str, folder, mtime, parsed, time.time()))
                        except Exception as e:
                            log.warning("Row build failed for %s: %s", fpath_str, e)
                            skipped += 1
                            continue
                        processed += 1
                    if len(pending_rows) >= COMMIT_BATCH:
                        try:
                            flush_batch(conn, pending_rows)
                        except Exception as e:
                            # On batch failure, retry rows one-by-one to isolate the bad one
                            log.warning("Batch insert failed (%s); retrying individually", e)
                            conn.rollback()
                            for row in pending_rows:
                                try:
                                    with conn.cursor() as cur:
                                        cur.execute(INSERT_SQL, row)
                                    conn.commit()
                                except Exception as e2:
                                    log.warning("Row insert failed (file_path=%s): %s", row[3], e2)
                                    conn.rollback()
                                    skipped += 1
                                    processed = max(0, processed - 1)
                        pending_rows = []
                    if processed and (processed // 10000) != ((processed - len(batch_result)) // 10000):
                        rate = processed / max(0.001, time.time() - t0)
                        log.info(
                            "Progress: %d processed, %d skipped (%.1fs, %.0f msg/s)",
                            processed, skipped, time.time() - t0, rate,
                        )

        if pending_rows:
            try:
                flush_batch(conn, pending_rows)
            except Exception as e:
                log.warning("Final batch failed (%s); retrying individually", e)
                conn.rollback()
                for row in pending_rows:
                    try:
                        with conn.cursor() as cur:
                            cur.execute(INSERT_SQL, row)
                        conn.commit()
                    except Exception as e2:
                        log.warning("Row insert failed (file_path=%s): %s", row[3], e2)
                        conn.rollback()
                        skipped += 1

        deleted = 0
        if mode == "full":
            log.info("Reconciling deletions...")
            deleted = reconcile_deletions(conn, mailbox_root)

        now = time.time()
        set_meta(conn, "last_incremental_ts" if mode == "incremental" else "last_full_ts", str(now))
        if mode == "full":
            set_meta(conn, "last_incremental_ts", str(now))  # full subsumes incremental
        set_meta(conn, "last_mode", mode)
        set_meta(conn, "last_duration_s", str(round(now - t0, 2)))
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM emails WHERE source = %s", (SOURCE,))
            total = cur.fetchone()[0]

        stats = {
            "mode": mode,
            "source": SOURCE,
            "processed": processed,
            "skipped": skipped,
            "deleted": deleted,
            "total_indexed": total,
            "duration_s": round(now - t0, 2),
        }
        log.info("Done: %s", stats)
        return stats
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ----- CLI commands -----------------------------------------------------------

def cmd_stats() -> None:
    conn = get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM emails WHERE source = %s", (SOURCE,))
            total = cur.fetchone()[0]
            cur.execute(
                """
                SELECT folder, COUNT(*) FROM emails
                WHERE source = %s
                GROUP BY folder ORDER BY 2 DESC LIMIT 20
                """,
                (SOURCE,),
            )
            by_folder = cur.fetchall()
            cur.execute(
                "SELECT key, value FROM indexer_meta WHERE source = %s",
                (SOURCE,),
            )
            meta = {k: v for k, v in cur.fetchall()}
        print(f"Source:        {SOURCE}")
        print(f"Total emails:  {total}")
        last_inc = meta.get("last_incremental_ts")
        last_full = meta.get("last_full_ts")
        print(f"Last incremental: {time.ctime(float(last_inc)) if last_inc else 'never'}")
        print(f"Last full:        {time.ctime(float(last_full)) if last_full else 'never'}")
        print(f"Last duration:    {meta.get('last_duration_s', '?')}s ({meta.get('last_mode', '?')})")
        print("Top 20 folders:")
        for f, c in by_folder:
            print(f"  {c:>8}  {f}")
    finally:
        conn.close()


def cmd_search(query: str) -> None:
    """Full-text search via PG tsvector. websearch_to_tsquery supports OR/AND/quotes."""
    conn = get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT folder, date_str, from_addr, subject, message_id
                FROM emails
                WHERE source = %s
                  AND body_tsv @@ websearch_to_tsquery('simple', %s)
                ORDER BY date_ts DESC NULLS LAST
                LIMIT 20
                """,
                (SOURCE, query),
            )
            rows = cur.fetchall()
        for folder, date, frm, subj, mid in rows:
            print(f"{(date or '?'):30s}  {(folder or ''):40s}  {(frm or '')[:40]:40s}  {(subj or '')[:70]}  {mid or ''}")
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--incremental", action="store_true", help="Scan only files with mtime > last_run")
    parser.add_argument("--full", action="store_true", help="Full rescan + reconcile deletions")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--search", type=str, default="")
    parser.add_argument("--root", type=Path, default=DEFAULT_MAILBOX_ROOT)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"Worker processes (default {DEFAULT_WORKERS} = 80%% of cores)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    if args.stats:
        cmd_stats()
        return 0
    if args.search:
        cmd_search(args.search)
        return 0

    mode = "full" if args.full else "incremental"
    if not (args.full or args.incremental):
        parser.error("Specify --incremental, --full, --stats, or --search")
    run_indexer(mode, args.root, workers=args.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
