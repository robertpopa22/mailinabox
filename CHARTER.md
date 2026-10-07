# Charter — Mail-in-a-Box, Geseidl Edition

Version 1.1 · 2026-10-07 · Owner: Geseidl IT Solutions (maintainers of this fork)

This charter is self-contained. It defines what this fork is, what it is not, and the
directives (`MIAB-NN`) every change must respect. Day-to-day status lives in `TODO.md` and
`ROADMAP.md`; lessons learned live in `BEST_PRACTICES.md`.

## 1. Scope

This repository is the **geseidl-edition overlay on upstream
[Mail-in-a-Box](https://github.com/mail-in-a-box/mailinabox)**: a sovereign fork that keeps
upstream code recognisable and keeps every edition-specific customisation in clearly separated
zones (`management/geseidl_edition/`, `setup/geseidl_edition/`, marker `.geseidl-edition`).

In scope: the overlay zones (`status`, `dns`, `ssl`, `mail`, `web`, `spam`), fork-tracked setup
changes needed to run on a newer OS / Nextcloud / PHP than upstream supports, and the guides in
this repository.

Out of scope: any deployment-specific data (addresses, hostnames, key names, credentials,
internal paths, client names), server operations runbooks and capacity planning, and any
change that belongs upstream and should be sent there instead.

## 2. Precedence

1. Security of the code and of users' mail.
2. This charter (`MIAB-NN` directives).
3. `CLAUDE.md` (working mode of contributors and agents).
4. Everything else in the repository.

## 3. Directives

| ID | Directive |
|----|-----------|
| MIAB-01 | **Overlay zones.** Edition-specific logic lives only under `management/geseidl_edition/` and `setup/geseidl_edition/`. Hooks inside upstream files are limited to blocks delimited by `# >>> GESEIDL EDITION OVERLAY >>>` / `# <<< GESEIDL EDITION OVERLAY <<<` and contain no logic beyond a call into the overlay. |
| MIAB-02 | **Cherry-pick policy.** Upstream is a reference remote, not a merge source. Every upstream commit is reviewed once and recorded in `.geseidl-edition` (`upstream_commit_reviews`, `upstream_review_summary`) with a verdict: applied, already covered, not applicable, or tag-only. Security fixes are triaged first. A divergent Git graph is never reported as "up to date". |
| MIAB-03 | **Idempotent, reversible overlay.** Every applier can be re-run safely, supports a dry-run or status mode, and verifies its result; provisioning steps that can break service roll back automatically when verification fails. |
| MIAB-04 | **No deployment data in the repository.** No secrets, tokens, private addresses, real hostnames, SSH key names, client or user names, or filesystem paths of any private environment. Examples use `example.com`, `example.org` and the documentation ranges `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`. Deployment values are read from the environment or from files on the server. |
| MIAB-05 | **Fail closed on configuration.** Features that need a deployment value (allowed networks, report mailbox, notification address) refuse to act, or skip with a clear log line, when the value is missing; they never fall back to a hardcoded production value. |
| MIAB-06 | **Do not mask reality.** Status overlays re-verify against the public world (public DNS, HTTP, TLS) and turn a check green only when it is truly fine; unrecognised errors stay visible. |
| MIAB-07 | **Test before production.** Setup scripts are tested upstream only on the upstream-supported OS; any change that touches them is validated on a clone before it is deployed. |
| MIAB-08 | **Line endings.** Artefacts executed on Linux (`*.sh`, `*.patch`, overlay Python) are forced to LF through `.gitattributes`. |
| MIAB-09 | **Lessons become evidence.** A confirmed bug, regression or incident produces a `BP-MIAB-NNN` entry in `BEST_PRACTICES.md` and a row in `docs/TRACEABILITY.md`; `scripts/check_bp_coverage.py` must pass before commit. A lesson that demands a new rule becomes a directive here, with a new ID (IDs are never reused). |
| MIAB-10 | **Branding.** The public README keeps the "Maintained by" section and the makeitcount footer. |
| MIAB-11 | **Always latest stable, independently of upstream.** This fork targets and maintains each component's latest publisher-declared stable release, including new major versions, independently of Mail-in-a-Box upstream. Compatibility problems are maintenance work we resolve in the fork through reviewed adaptations and regression tests, rather than a permanent reason to retain an older major. Record installed and global latest versions, source/date and migration evidence. Use supported version hops; validate runtime, authentication, plugins, data and recovery on an isolated clone before production. An untested version override is not a compatibility fix. Any temporary blocker remains open with an owner and next action until resolved; never report an older maintenance branch as latest global. Distribution packages and kernel tracks retain an explicit lifecycle choice; maintained backports and upstream version numbers are reported separately. |

## 4. Document roles

| File | Holds | Does not hold |
|------|-------|---------------|
| `CHARTER.md` | scope, limits, directives, decisions register | status, journal |
| `CLAUDE.md` | working mode of agents/contributors, commands, guards | copies of directives |
| `TODO.md` | decided, not-yet-started items facing upstream/fork | deployment operations, undecided ideas |
| `ROADMAP.md` | directions with state | daily tasks |
| `BEST_PRACTICES.md` | index of lessons | long write-ups (put them in `docs/bp/`) |
| `docs/TRACEABILITY.md` | BP → test / pattern / gap | new lessons |

## 5. Decisions register

| Date | Decision | Directive |
|------|----------|-----------|
| 2026-10-07 | The sovereign fork always targets latest publisher stable, including major releases. Resolve compatibility in the fork, prove migrations and recovery, then deploy; temporary blockers are unfinished maintenance work. | MIAB-11 |
| 2026-06-09 | The fork becomes sovereign: no more `git merge upstream/main`; selective cherry-pick only; OS, Nextcloud and PHP versions are decided by this fork. | MIAB-02 |
| 2026-06-09 | Customisation model is overlay zones, not feature branches. | MIAB-01 |
| 2026-10-06 | Public repository is separated from any private deployment: deployment data removed, self-contained governance added. | MIAB-04, MIAB-05 |
