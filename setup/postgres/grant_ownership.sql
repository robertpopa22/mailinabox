-- Transfer ownership of email tables + indexes to ges_mail_indexer role.
-- This lets the indexer DROP/CREATE indexes during bulk migration.
ALTER TABLE emails OWNER TO ges_mail_indexer;
ALTER TABLE indexer_meta OWNER TO ges_mail_indexer;
ALTER INDEX emails_tsv_gin OWNER TO ges_mail_indexer;
ALTER INDEX emails_folder_trgm OWNER TO ges_mail_indexer;
ALTER INDEX emails_date_ts OWNER TO ges_mail_indexer;
ALTER INDEX emails_message_id OWNER TO ges_mail_indexer;
ALTER INDEX emails_source_mtime OWNER TO ges_mail_indexer;
ALTER INDEX emails_source_folder OWNER TO ges_mail_indexer;
ALTER INDEX emails_source_path_uk OWNER TO ges_mail_indexer;
ALTER SEQUENCE emails_id_seq OWNER TO ges_mail_indexer;
GRANT SELECT ON emails, indexer_meta TO ges_mail_reader;
