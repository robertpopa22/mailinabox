# TODO — upstream-facing decided items

> Charter: [`CHARTER.md`](CHARTER.md). One row = one decided item that has not started yet.
> Close a row by commit, by a note in `ROADMAP.md`, or by an explicit withdrawal recorded here.
> Format: `- [ ] YYYY-MM-DD · <author> · <what> — <why> · <who> · <deadline/trigger> · <decision source>`
> Server operations (purges, quotas, resizing) are deployment matters and are not tracked here.

- [x] 2026-10-06 · Robert Popa · Triage `df7f245`, `d317da1`, `60b7ca2` — completed 2026-10-07; verdicts in `.geseidl-edition`, application release pins in `dc62afd` · MIAB-02
- [ ] 2026-10-07 · Robert Popa · Validate publisher stable Roundcube 1.7.4 and CardDAV 5.1.4 together with authentication and enabled plugins on an isolated clone · maintainers · next component migration · MIAB-11
- [ ] 2026-10-07 · Robert Popa · Validate sequential Nextcloud 33→34→35 migrations toward 35.0.1 and current stable Contacts/Calendar; resolve the user_external 4.0.0 published maximum Nextcloud 34 before 35, without overriding compatibility checks · maintainers · next component migration · MIAB-11
- [ ] 2026-10-06 · Robert Popa · Decouple Nextcloud from the Mail-in-a-Box pin (standalone Nextcloud instance) so it no longer depends on the pinned chain in `setup/nextcloud.sh` · maintainers · when the Nextcloud 33 line nears end of support · `CLAUDE.md:136` ("Ramas: decuplare NC intr-un VM standalone")
