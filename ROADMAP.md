# Roadmap — Mail-in-a-Box, Geseidl Edition

> Charter: [`CHARTER.md`](CHARTER.md). Directions and stages, not daily tasks (those are in `TODO.md`).
> States: **proposed** → **approved** → **in progress** → **delivered** | **retired**.
> A row moves state only with a decision recorded in the Charter's decisions register or in a commit.

| Direction | State | Depends on | Decision / evidence |
|-----------|-------|------------|---------------------|
| Sovereign fork baseline: Ubuntu 24.04, Nextcloud 33 (chain 26→33, SHA1 pinned), PHP 8.2/8.3, Roundcube 1.6.16 | delivered | — | `CHARTER.md` §5 (2026-06-09); `CLAUDE.md` "Executat" |
| Overlay zones `status`, `dns`, `ssl`, `mail`, `web`, `spam` | delivered | MIAB-01 | `.geseidl-edition` (`overlay_version`, `zones`) |
| Upstream review ledger (`upstream_commit_reviews`) kept current with every upstream release | in progress | MIAB-02 | `.geseidl-edition:17-18`; `TODO.md` |
| Move remaining inline fork edits (e.g. `setup/nextcloud.sh` chain, `setup/rspamd.sh`) behind overlay zones where practical | proposed | MIAB-01 | — |
| Self-contained governance (charter, TODO, roadmap, BP index, coverage guard) | delivered | MIAB-09 | this repository, 2026-10-06 |
| Standalone Nextcloud decoupled from the Mail-in-a-Box pin | proposed | Nextcloud support window | `TODO.md` |
| Migration to feature branches per customisation | retired | — | Replaced by overlay zones (2026-06-09) |
