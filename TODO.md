# TODO — upstream-facing decided items

> Charter: [`CHARTER.md`](CHARTER.md). One row = one decided item that has not started yet.
> Close a row by commit, by a note in `ROADMAP.md`, or by an explicit withdrawal recorded here.
> Format: `- [ ] YYYY-MM-DD · <author> · <what> — <why> · <who> · <deadline/trigger> · <decision source>`
> Server operations (purges, quotas, resizing) are deployment matters and are not tracked here.

- [x] 2026-10-06 · Robert Popa · Triage `df7f245`, `d317da1`, `60b7ca2` — completed 2026-10-07; verdicts in `.geseidl-edition`, application release pins in `dc62afd` · MIAB-02
- [x] 2026-10-07 · Robert Popa · Roundcube 1.7.4/CardDAV 5.1.4 validated: authenticated inbox and controlled CardDAV sync on clone; PHP 8.5 compatibility and cipher key preservation · delivered in c381ef8/37bb6ab · MIAB-11
- [x] 2026-10-07 · Robert Popa · Nextcloud 33→34.0.4→35.0.1, Contacts 8.9.1/Calendar 6.6.2 validated: separate edition IMAP app, positive/negative authentication, DAV CRUD and preserved data fingerprints · delivered in c381ef8/37bb6ab · MIAB-11
- [ ] 2026-10-07 · Robert Popa · Classify remaining upgraded SQLite schema differences against a fresh NC35 installation; preserve obsolete and disabled-app tables until a data-safe migration is demonstrated · maintainers · next schema review · MIAB-07/MIAB-11
- [ ] 2026-10-06 · Robert Popa · Decouple Nextcloud from the Mail-in-a-Box pin (standalone Nextcloud instance) so it no longer depends on the pinned chain in `setup/nextcloud.sh` · maintainers · when the Nextcloud 33 line nears end of support · `CLAUDE.md:136` ("Ramas: decuplare NC intr-un VM standalone")
