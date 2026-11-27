# PostgreSQL email index

### BP-MIAB-027 — Schema-qualify functions used by generated columns

- Context: Major upgrade of the email index cluster from PostgreSQL 16 to 19 with `pg_upgradecluster`.
- Mistake: `public.immutable_unaccent` called `unaccent('unaccent'::regdictionary, $1)` without a schema. The STORED generated column `body_tsv` uses it.
- Cause: `pg_upgrade` and `pg_restore` run with an empty `search_path`. Neither the function nor the dictionary resolves, so restoring `body_tsv` fails and the upgrade stops.
- Correct: Call `public.unaccent('public.unaccent'::regdictionary, $1)`. The result is the same, and it does not depend on `search_path`. When the generated expression changes between majors, recompute only the rows that differ.
- Proof: `tests/test_postgres_setup.py` refuses an unqualified call in `setup/postgres/schema.sql`. It also checks that `install.sh` and the tuned configuration name the same major version.
- Directive: MIAB-07, MIAB-11.
