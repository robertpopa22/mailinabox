-- Email index schema for MAIL02 PostgreSQL
-- Source of truth for both 'live' (MAIL02 maildir) and 'archive' (GES051WS Thunderbird) indexers.
-- FTS via tsvector STORED generated column + GIN index, with unaccent extension to mimic
-- SQLite FTS5 'unicode61 remove_diacritics 2' behavior (existing queries stay compatible).

\set ON_ERROR_STOP on

CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- unaccent must be IMMUTABLE for use in a STORED generated column.
-- Default unaccent() is STABLE; we wrap it in an immutable shim.
CREATE OR REPLACE FUNCTION public.immutable_unaccent(text)
RETURNS text
LANGUAGE sql
IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT unaccent('unaccent'::regdictionary, $1) $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'email_source') THEN
        CREATE TYPE email_source AS ENUM ('live', 'archive');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS emails (
    id           BIGSERIAL PRIMARY KEY,
    source       email_source NOT NULL,
    message_id   TEXT,
    folder       TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    date_str     TEXT,
    date_ts      TIMESTAMPTZ,
    from_addr    TEXT,
    to_addr      TEXT,
    cc_addr      TEXT,
    subject      TEXT,
    body_snippet TEXT,
    size_bytes   BIGINT,
    mtime        DOUBLE PRECISION,
    indexed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    body_tsv     tsvector GENERATED ALWAYS AS (
        to_tsvector('simple',
            public.immutable_unaccent(
                coalesce(subject,'') || ' ' ||
                coalesce(from_addr,'') || ' ' ||
                coalesce(to_addr,'') || ' ' ||
                coalesce(body_snippet,'')))
    ) STORED,
    CONSTRAINT emails_source_path_uk UNIQUE (source, file_path)
);

CREATE INDEX IF NOT EXISTS emails_tsv_gin       ON emails USING GIN (body_tsv);
CREATE INDEX IF NOT EXISTS emails_folder_trgm   ON emails USING GIN (folder gin_trgm_ops);
CREATE INDEX IF NOT EXISTS emails_date_ts       ON emails (date_ts DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS emails_message_id    ON emails (message_id) WHERE message_id IS NOT NULL AND message_id <> '';
CREATE INDEX IF NOT EXISTS emails_source_mtime  ON emails (source, mtime) WHERE mtime IS NOT NULL;
CREATE INDEX IF NOT EXISTS emails_source_folder ON emails (source, folder);

CREATE TABLE IF NOT EXISTS indexer_meta (
    source email_source NOT NULL,
    key    TEXT NOT NULL,
    value  TEXT,
    PRIMARY KEY (source, key)
);
