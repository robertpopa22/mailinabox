#!/usr/bin/env python3
"""
Email indexer for Mail-in-a-Box (Dovecot maildir) → SQLite FTS5.

Modes:
  --incremental   Scan only files with mtime > last_run_ts (default, ~10min cron)
  --full          Scan all files + reconcile deletions (nightly)
  --stats         Print index statistics
  --search QUERY  Quick FTS5 query test

Maildir layout (Mail-in-a-Box / Dovecot):
  /home/user-data/mail/mailboxes/<domain>/<user>/{cur,new,tmp}/
  /home/user-data/mail/mailboxes/<domain>/<user>/.<FolderName>/{cur,new,tmp}/

Each file = one RFC822 message. Filename includes Dovecot UID + flags
(e.g. "1234.M567P890.host:2,S"). Flags change file rename → mtime updates.

Output: SQLite FTS5 DB at /var/lib/email-indexer/live.db (configurable via env).
"""
from __future__ import annotations

import argparse
import email as email_mod
import email.policy as email_policy
import logging
import multiprocessing
import os
import re
import sqlite3
import sys
import time
from email.utils import parsedate_to_datetime, getaddresses
from pathlib import Path

DEFAULT_MAILBOX_ROOT = Path(os.environ.get("MAILBOX_ROOT", "/home/user-data/mail/mailboxes"))
DEFAULT_DB_PATH = Path(os.environ.get("EMAIL_INDEX_DB", "/var/lib/email-indexer/live.db"))

# Skip these mailbox subfolders (huge or noisy, low value to index)
SKIP_FOLDERS = {".Trash", ".Spam", ".Junk"}

MAX_BODY_LEN = 8000
MAX_FILE_BYTES = 5 * 1024 * 1024  # skip files > 5 MB (rare, mostly mailing lists with big attachments)
COMMIT_BATCH = 2000

# Worker count: cap at 80% of cores to leave headroom for Dovecot/Postfix
DEFAULT_WORKERS = max(2, int((os.cpu_count() or 4) * 0.8))
# Files per worker batch — large batches amortize IPC cost
WORKER_BATCH_SIZE = 200

HTML_TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

log = logging.getLogger("email_indexer")


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level="DEFERRED", timeout=120.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=120000")  # 120s wait for locks
    conn.execute("PRAGMA cache_size=-65536")  # 64 MB
    conn.execute("PRAGMA mmap_size=268435456")  # 256 MB

    conn.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT,
            folder TEXT NOT NULL,
            file_path TEXT NOT NULL UNIQUE,
            date_str TEXT,
            date_ts REAL,
            from_addr TEXT,
            to_addr TEXT,
            cc_addr TEXT,
            subject TEXT,
            body_snippet TEXT,
            size_bytes INTEGER,
            mtime REAL,
            indexed_at REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_emails_message_id ON emails(message_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_emails_folder ON emails(folder)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_emails_date_ts ON emails(date_ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_emails_mtime ON emails(mtime)")

    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
            subject, from_addr, to_addr, body_text, message_id,
            content='emails',
            content_rowid='id',
            tokenize='unicode61 remove_diacritics 2'
        )
    """)
    # Triggers keep FTS in sync
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS emails_ai AFTER INSERT ON emails BEGIN
            INSERT INTO emails_fts(rowid, subject, from_addr, to_addr, body_text, message_id)
            VALUES (new.id, new.subject, new.from_addr, new.to_addr, new.body_snippet, new.message_id);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS emails_ad AFTER DELETE ON emails BEGIN
            INSERT INTO emails_fts(emails_fts, rowid, subject, from_addr, to_addr, body_text, message_id)
            VALUES('delete', old.id, old.subject, old.from_addr, old.to_addr, old.body_snippet, old.message_id);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS emails_au AFTER UPDATE ON emails BEGIN
            INSERT INTO emails_fts(emails_fts, rowid, subject, from_addr, to_addr, body_text, message_id)
            VALUES('delete', old.id, old.subject, old.from_addr, old.to_addr, old.body_snippet, old.message_id);
            INSERT INTO emails_fts(rowid, subject, from_addr, to_addr, body_text, message_id)
            VALUES (new.id, new.subject, new.from_addr, new.to_addr, new.body_snippet, new.message_id);
        END
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    return conn


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


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
        date_ts = 0.0
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
            "message_id": _safe_header(msg, "Message-ID").strip(),
            "date_str": date_str,
            "date_ts": date_ts,
            "from_addr": _safe_addrs(msg, "From"),
            "to_addr": _safe_addrs(msg, "To"),
            "cc_addr": _safe_addrs(msg, "Cc"),
            "subject": _safe_header(msg, "Subject").strip(),
            "body_snippet": body,
            "size_bytes": size,
        }
    except Exception:
        return None


def upsert_email(conn: sqlite3.Connection, file_path: str, folder: str, mtime: float, parsed: dict) -> None:
    now = time.time()
    conn.execute(
        """
        INSERT INTO emails(
            message_id, folder, file_path, date_str, date_ts,
            from_addr, to_addr, cc_addr, subject, body_snippet,
            size_bytes, mtime, indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            message_id=excluded.message_id,
            folder=excluded.folder,
            date_str=excluded.date_str,
            date_ts=excluded.date_ts,
            from_addr=excluded.from_addr,
            to_addr=excluded.to_addr,
            cc_addr=excluded.cc_addr,
            subject=excluded.subject,
            body_snippet=excluded.body_snippet,
            size_bytes=excluded.size_bytes,
            mtime=excluded.mtime,
            indexed_at=excluded.indexed_at
        """,
        (
            parsed["message_id"], folder, file_path,
            parsed["date_str"], parsed["date_ts"],
            parsed["from_addr"], parsed["to_addr"], parsed["cc_addr"],
            parsed["subject"], parsed["body_snippet"],
            parsed["size_bytes"], mtime, now,
        ),
    )


def reconcile_deletions(conn: sqlite3.Connection, root: Path) -> int:
    """Remove rows whose file_path no longer exists. Only safe in --full mode."""
    deleted = 0
    cur = conn.execute("SELECT id, file_path FROM emails")
    rows = cur.fetchall()
    for row_id, fpath in rows:
        if not Path(fpath).exists():
            conn.execute("DELETE FROM emails WHERE id = ?", (row_id,))
            deleted += 1
    return deleted


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


def run_indexer(mode: str, db_path: Path, mailbox_root: Path, workers: int = DEFAULT_WORKERS) -> dict:
    t0 = time.time()
    conn = init_db(db_path)
    last_run = float(get_meta(conn, "last_incremental_ts", "0") or 0)
    since = 0.0 if mode == "full" else max(0.0, last_run - 60.0)  # 60s overlap
    log.info(
        "Mode=%s | root=%s | db=%s | since_mtime=%.0f | workers=%d | batch=%d",
        mode, mailbox_root, db_path, since, workers, WORKER_BATCH_SIZE,
    )

    processed = 0
    skipped = 0
    pending = 0

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
                upsert_email(conn, fpath_str, folder, mtime, parsed)
            except Exception as e:
                log.warning("Skipping %s: %s", fpath_str, e)
                skipped += 1
                continue
            processed += 1
            pending += 1
            if pending >= COMMIT_BATCH:
                conn.commit()
                pending = 0
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
                        upsert_email(conn, fpath_str, folder, mtime, parsed)
                    except Exception as e:
                        log.warning("Upsert failed for %s: %s", fpath_str, e)
                        skipped += 1
                        continue
                    processed += 1
                    pending += 1
                if pending >= COMMIT_BATCH:
                    conn.commit()
                    pending = 0
                if processed and (processed // 10000) != ((processed - len(batch_result)) // 10000):
                    rate = processed / max(0.001, time.time() - t0)
                    log.info(
                        "Progress: %d processed, %d skipped (%.1fs, %.0f msg/s)",
                        processed, skipped, time.time() - t0, rate,
                    )

    if pending:
        conn.commit()

    deleted = 0
    if mode == "full":
        log.info("Reconciling deletions…")
        deleted = reconcile_deletions(conn, mailbox_root)
        conn.commit()

    now = time.time()
    set_meta(conn, "last_incremental_ts" if mode == "incremental" else "last_full_ts", str(now))
    if mode == "full":
        set_meta(conn, "last_incremental_ts", str(now))  # full subsumes incremental
    set_meta(conn, "last_mode", mode)
    set_meta(conn, "last_duration_s", str(round(now - t0, 2)))
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
    # Checkpoint WAL into main DB so the file is consistent for rsync/scp
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError:
        pass
    conn.close()

    stats = {
        "mode": mode,
        "processed": processed,
        "skipped": skipped,
        "deleted": deleted,
        "total_indexed": total,
        "duration_s": round(now - t0, 2),
    }
    log.info("Done: %s", stats)
    return stats


def cmd_stats(db_path: Path) -> None:
    if not db_path.exists():
        print(f"DB not initialized: {db_path}")
        return
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    total = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
    by_folder = conn.execute(
        "SELECT folder, COUNT(*) FROM emails GROUP BY folder ORDER BY 2 DESC LIMIT 20"
    ).fetchall()
    last_inc = conn.execute("SELECT value FROM meta WHERE key='last_incremental_ts'").fetchone()
    last_full = conn.execute("SELECT value FROM meta WHERE key='last_full_ts'").fetchone()
    print(f"Total emails: {total}")
    print(f"Last incremental: {time.ctime(float(last_inc[0])) if last_inc else 'never'}")
    print(f"Last full:        {time.ctime(float(last_full[0])) if last_full else 'never'}")
    print("Top 20 folders:")
    for f, c in by_folder:
        print(f"  {c:>8}  {f}")
    conn.close()


def cmd_search(db_path: Path, query: str) -> None:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = conn.execute(
        """
        SELECT e.folder, e.date_str, e.from_addr, e.subject, e.message_id
        FROM emails_fts f
        JOIN emails e ON e.id = f.rowid
        WHERE emails_fts MATCH ?
        ORDER BY e.date_ts DESC
        LIMIT 20
        """,
        (query,),
    ).fetchall()
    for folder, date, frm, subj, mid in rows:
        print(f"{date or '?':30s}  {folder:40s}  {frm[:40]:40s}  {subj[:70]}  {mid}")
    conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--incremental", action="store_true", help="Scan only files with mtime > last_run")
    parser.add_argument("--full", action="store_true", help="Full rescan + reconcile deletions")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--search", type=str, default="")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
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
        cmd_stats(args.db)
        return 0
    if args.search:
        cmd_search(args.db, args.search)
        return 0

    mode = "full" if args.full else "incremental"
    if not (args.full or args.incremental):
        parser.error("Specify --incremental, --full, --stats, or --search")
    run_indexer(mode, args.db, args.root, workers=args.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
