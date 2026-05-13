-- Transfer ownership of email tables + indexes to email_indexer role.
-- This lets the indexer DROP/CREATE indexes during bulk migration.
ALTER TABLE emails OWNER TO email_indexer;
ALTER TABLE indexer_meta OWNER TO email_indexer;
ALTER INDEX emails_tsv_gin OWNER TO email_indexer;
ALTER INDEX emails_folder_trgm OWNER TO email_indexer;
ALTER INDEX emails_date_ts OWNER TO email_indexer;
ALTER INDEX emails_message_id OWNER TO email_indexer;
ALTER INDEX emails_source_mtime OWNER TO email_indexer;
ALTER INDEX emails_source_folder OWNER TO email_indexer;
ALTER INDEX emails_source_path_uk OWNER TO email_indexer;
ALTER SEQUENCE emails_id_seq OWNER TO email_indexer;
GRANT SELECT ON emails, indexer_meta TO email_reader;
