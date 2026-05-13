#!/bin/bash
# End-to-end test suite for the PostgreSQL email index migration.
# Runs syntax checks, PG smoke tests, MCP function tests, indexer dry-runs.
# Exit code = number of failures.

set +e

PASS=0
FAIL=0
FAIL_MSGS=()

ok() { echo "  [OK] $1"; PASS=$((PASS+1)); }
err() { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); FAIL_MSGS+=("$1"); }

# Env
ENV_FILE=/etc/mailinabox/postgres.env
if [[ -f $ENV_FILE ]]; then . $ENV_FILE; fi

# ---------------------------------------------------------------------------
echo "=== 1. Python syntax ==="
for f in /opt/email-indexer/indexer.py /tmp/postgres/migrate-from-sqlite.py; do
    if [[ -f $f ]]; then
        if python3 -c "import ast; ast.parse(open('$f').read())" 2>/dev/null; then
            ok "syntax $f"
        else
            err "syntax $f"
        fi
    fi
done

# ---------------------------------------------------------------------------
echo "=== 2. PostgreSQL connectivity ==="
if PGPASSWORD="$EMAIL_READER_PW" psql -h 10.0.1.89 -U email_reader emails -c "SELECT 1" >/dev/null 2>&1; then
    ok "PG reader connect"
else
    err "PG reader connect"
fi
if PGPASSWORD="$EMAIL_INDEXER_PW" psql -h 10.0.1.89 -U email_indexer emails -c "SELECT 1" >/dev/null 2>&1; then
    ok "PG indexer connect"
else
    err "PG indexer connect"
fi

# ---------------------------------------------------------------------------
echo "=== 3. Schema sanity ==="
SCHEMA_CHECK=$(PGPASSWORD="$EMAIL_READER_PW" psql -h 10.0.1.89 -U email_reader emails -tAc "
    SELECT
        (SELECT count(*) FROM pg_extension WHERE extname='unaccent') AS ext_unaccent,
        (SELECT count(*) FROM pg_extension WHERE extname='pg_trgm') AS ext_trgm,
        (SELECT count(*) FROM pg_indexes WHERE indexname='emails_tsv_gin') AS gin_index,
        (SELECT count(*) FROM information_schema.columns WHERE table_name='emails' AND column_name='body_tsv') AS body_tsv_col
" 2>&1)
echo "  $SCHEMA_CHECK"
if [[ "$SCHEMA_CHECK" == "1|1|1|1" ]]; then ok "schema complete"; else err "schema incomplete: $SCHEMA_CHECK"; fi

# ---------------------------------------------------------------------------
echo "=== 4. Row counts ==="
ROWS=$(PGPASSWORD="$EMAIL_READER_PW" psql -h 10.0.1.89 -U email_reader emails -tAc "SELECT source, count(*) FROM emails GROUP BY source ORDER BY source")
echo "$ROWS" | while read -r line; do echo "  $line"; done
LIVE=$(echo "$ROWS" | grep '^live|' | cut -d'|' -f2)
ARCHIVE=$(echo "$ROWS" | grep '^archive|' | cut -d'|' -f2)
[[ ${LIVE:-0} -gt 500000 ]] && ok "live rows $LIVE > 500K" || err "live rows $LIVE < 500K"
[[ ${ARCHIVE:-0} -gt 800000 ]] && ok "archive rows $ARCHIVE > 800K" || err "archive rows $ARCHIVE < 800K"

# ---------------------------------------------------------------------------
echo "=== 5. FTS query basic ==="
if PGPASSWORD="$EMAIL_READER_PW" psql -h 10.0.1.89 -U email_reader emails -tAc "
    SELECT count(*) FROM emails WHERE body_tsv @@ websearch_to_tsquery('simple', public.immutable_unaccent('factura'))
" 2>&1 | grep -q '^[0-9]\+$'; then
    ok "FTS 'factura' returns numeric count"
else
    err "FTS 'factura' query failed"
fi

# ---------------------------------------------------------------------------
echo "=== 6. Message-ID exact match (Grigoras forwarded email) ==="
MID='06139703-d4c7-4ff9-815f-94515f91ce7c@geseidl.ro'
COUNT=$(PGPASSWORD="$EMAIL_READER_PW" psql -h 10.0.1.89 -U email_reader emails -tAc "
    SELECT count(*) FROM emails WHERE message_id LIKE '%$MID%'
" 2>&1)
echo "  Message-ID hits: $COUNT"
[[ ${COUNT:-0} -ge 1 ]] && ok "Message-ID '$MID' found ($COUNT rows)" || err "Message-ID '$MID' NOT found"

# ---------------------------------------------------------------------------
echo "=== 7. Romanian diacritics search ==="
DIAC=$(PGPASSWORD="$EMAIL_READER_PW" psql -h 10.0.1.89 -U email_reader emails -tAc "
    SELECT count(*) FROM emails
    WHERE body_tsv @@ websearch_to_tsquery('simple', public.immutable_unaccent('salariu'))
" 2>&1)
[[ ${DIAC:-0} -gt 0 ]] && ok "diacritic 'salariu' search returns $DIAC rows" || err "diacritic search failed: $DIAC"

# ---------------------------------------------------------------------------
echo "=== 8. Folder breakdown ==="
FOLDERS=$(PGPASSWORD="$EMAIL_READER_PW" psql -h 10.0.1.89 -U email_reader emails -tAc "
    SELECT count(DISTINCT folder) FROM emails
" 2>&1)
[[ ${FOLDERS:-0} -gt 100 ]] && ok "$FOLDERS unique folders" || err "only $FOLDERS folders"

# ---------------------------------------------------------------------------
echo "=== 9. Indexer DSN resolve test ==="
if [[ -x /opt/email-indexer/indexer.py ]] || [[ -f /opt/email-indexer/indexer.py ]]; then
    if PG_DSN="$PG_DSN_INDEXER" python3 /opt/email-indexer/indexer.py --stats 2>&1 | grep -q 'Total emails'; then
        ok "indexer --stats works"
    else
        err "indexer --stats failed: $(PG_DSN="$PG_DSN_INDEXER" python3 /opt/email-indexer/indexer.py --stats 2>&1 | tail -3)"
    fi
else
    err "indexer.py not deployed at /opt/email-indexer/indexer.py"
fi

# ---------------------------------------------------------------------------
echo "=== 10. Indexer search test ==="
SEARCH_OUT=$(PG_DSN="$PG_DSN_INDEXER" python3 /opt/email-indexer/indexer.py --search "Grigoras" 2>&1 | head -3)
if echo "$SEARCH_OUT" | grep -q "Grigoras\|geseidl\|@"; then
    ok "indexer --search 'Grigoras' returned matches"
else
    err "indexer --search failed: $SEARCH_OUT"
fi

# ---------------------------------------------------------------------------
echo "=== 11. Systemd timers ==="
for unit in email-indexer-incremental email-indexer-full pg-backup-emails; do
    if systemctl list-unit-files "$unit.timer" 2>/dev/null | grep -q "$unit.timer"; then
        STATE=$(systemctl is-enabled "$unit.timer" 2>&1)
        ok "$unit.timer state=$STATE"
    else
        err "$unit.timer not found"
    fi
done

# ---------------------------------------------------------------------------
echo
echo "============================="
echo "TOTAL: PASS=$PASS FAIL=$FAIL"
echo "============================="
if [[ $FAIL -gt 0 ]]; then
    echo "Failures:"
    for m in "${FAIL_MSGS[@]}"; do echo "  - $m"; done
fi
exit $FAIL
