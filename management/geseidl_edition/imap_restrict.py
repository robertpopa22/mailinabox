#!/usr/bin/env python3
"""Geseidl Edition — IMAP per-account source-IP restriction CLI.

Manages the `geseidl_imap_restrictions` sidecar table in the MiaB users
database (`users.sqlite`). When an account has a row here, Dovecot's patched
`password_query` returns its `allow_nets`, so login (IMAP/POP/Submission) is
allowed ONLY from those networks. Accounts without a row are unrestricted
(allow_nets resolves to NULL via LEFT JOIN, which Dovecot ignores).

The table and the password_query patch are provisioned by the mail zone:
    setup/geseidl_edition/zones/mail/apply.sh

Usage:
    python3 imap_restrict.py list
    python3 imap_restrict.py add <email> [--nets "10.0.1.0/24 192.168.2.0/24 ..."]
    python3 imap_restrict.py remove <email>

Notes:
- `add` is INSERT-or-UPDATE (idempotent).
- Default nets (LAN + WG ZTNA POWER + Tailscale) intentionally EXCLUDE
  127.0.0.1 -> blocks public-facing Roundcube webmail for these accounts.
- Changes take effect immediately (Dovecot reads the table per auth); no reload
  needed for table edits, only for the one-time query patch in apply.sh.
"""

import argparse
import ipaddress
import os
import sqlite3
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# LAN intern + WG ZTNA POWER + Tailscale. 127.0.0.1 EXCLUS (blocheaza webmail).
DEFAULT_NETS = "10.0.1.0/24 192.168.2.0/24 100.64.0.0/10"

STORAGE_ROOT = os.environ.get("STORAGE_ROOT", "/home/user-data")
DB_PATH = os.path.join(STORAGE_ROOT, "mail", "users.sqlite")


def _connect():
    if not os.path.exists(DB_PATH):
        sys.exit(f"EROARE: users.sqlite negasit la {DB_PATH} "
                 f"(seteaza STORAGE_ROOT daca difera).")
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS geseidl_imap_restrictions "
        "(email TEXT PRIMARY KEY, allow_nets TEXT NOT NULL);"
    )
    return conn


def _user_exists(conn, email):
    row = conn.execute(
        "SELECT 1 FROM users WHERE email = ?;", (email,)
    ).fetchone()
    return row is not None


def _validate_nets(nets):
    """Validate a space-separated list of CIDR networks; return normalized str."""
    parts = nets.split()
    if not parts:
        sys.exit("EROARE: lista de retele goala.")
    norm = []
    for p in parts:
        try:
            net = ipaddress.ip_network(p, strict=False)
        except ValueError as e:
            sys.exit(f"EROARE: retea invalida '{p}': {e}")
        norm.append(str(net))
    return " ".join(norm)


def cmd_list(args):
    conn = _connect()
    rows = conn.execute(
        "SELECT email, allow_nets FROM geseidl_imap_restrictions ORDER BY email;"
    ).fetchall()
    if not rows:
        print("(niciun cont restrictionat)")
        return
    width = max(len(e) for e, _ in rows)
    print(f"{'EMAIL'.ljust(width)}  ALLOW_NETS")
    for email, nets in rows:
        print(f"{email.ljust(width)}  {nets}")


def cmd_add(args):
    conn = _connect()
    email = args.email.strip().lower()
    if not _user_exists(conn, email):
        sys.exit(f"EROARE: contul '{email}' nu exista in tabela users. "
                 f"Creeaza-l intai in MiaB Admin.")
    nets = _validate_nets(args.nets)
    conn.execute(
        "INSERT INTO geseidl_imap_restrictions (email, allow_nets) VALUES (?, ?) "
        "ON CONFLICT(email) DO UPDATE SET allow_nets = excluded.allow_nets;",
        (email, nets),
    )
    conn.commit()
    print(f"OK: {email} -> allow_nets = {nets}")
    print("Login IMAP/POP/Submission permis DOAR de la aceste retele.")


def cmd_remove(args):
    conn = _connect()
    email = args.email.strip().lower()
    cur = conn.execute(
        "DELETE FROM geseidl_imap_restrictions WHERE email = ?;", (email,)
    )
    conn.commit()
    if cur.rowcount:
        print(f"OK: {email} — restrictie eliminata (acces nerestrictionat).")
    else:
        print(f"(nimic de sters: {email} nu era restrictionat)")


def main():
    p = argparse.ArgumentParser(
        prog="imap_restrict.py",
        description="Gestiune restrictie acces IMAP per-cont la source IP (Dovecot allow_nets).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="afiseaza conturile restrictionate").set_defaults(func=cmd_list)

    pa = sub.add_parser("add", help="restrictioneaza un cont (INSERT/UPDATE)")
    pa.add_argument("email")
    pa.add_argument("--nets", default=DEFAULT_NETS,
                    help=f"retele permise, separate prin spatiu (default: '{DEFAULT_NETS}')")
    pa.set_defaults(func=cmd_add)

    pr = sub.add_parser("remove", help="elimina restrictia unui cont")
    pr.add_argument("email")
    pr.set_defaults(func=cmd_remove)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
