# TODO — upstream-facing decided items

> Charter: [`CHARTER.md`](CHARTER.md). One row = one decided item that has not started yet.
> Close a row by commit, by a note in `ROADMAP.md`, or by an explicit withdrawal recorded here.
> Format: `- [ ] YYYY-MM-DD · <author> · <what> — <why> · <who> · <deadline/trigger> · <decision source>`
> Server operations (purges, quotas, resizing) are deployment matters and are not tracked here.

- [ ] 2026-10-06 · Robert Popa · Triage the 3 upstream commits not yet reviewed — `df7f245` (v77), `d317da1` (Roundcube 1.6.19), `60b7ca2` (revert of the python3-gnupg package); record a verdict for each in `.geseidl-edition` (`upstream_commit_reviews`, `upstream_review_summary`) · maintainers · next upstream review; Roundcube first (security-adjacent) · MIAB-02; `.geseidl-edition:17-18` lists the 7 commits already reviewed (10 upstream commits behind, 105 ahead at 2026-10-06)
- [ ] 2026-10-06 · Robert Popa · Decouple Nextcloud from the Mail-in-a-Box pin (standalone Nextcloud instance) so it no longer depends on the pinned chain in `setup/nextcloud.sh` · maintainers · when the Nextcloud 33 line nears end of support · `CLAUDE.md:136` ("Ramas: decuplare NC intr-un VM standalone")
