# Independent latest-stable migrations

## BP-MIAB-005 — Validate web roots and runtime backup coherence

Roundcube 1.7 changed its HTTP document root to `public_html`. The old root can
return HTTP 200 with a configuration instruction, which is not a usable login.
Validate the actual authenticated UI and CardDAV, then update both nginx alias
and FastCGI filename mapping. CLI schema success alone is insufficient.

A side-by-side PHP install is also insufficient evidence of traffic cutover.
Persist the selected FPM service and have backups stop/start that service.
Otherwise a backup may stop an obsolete idle runtime while application writers
remain active. The marker falls back to the prior runtime until cutover and
rejects malformed service names. Directive: MIAB-03, MIAB-07, MIAB-11.

PHP package layouts also change: PHP 8.5 exposes OPcache without the previous
`cli/conf.d/10-opcache.ini` loader file. Probe the capability, then create an
edition-owned settings ini for CLI/FPM; do not assume a vendor loader path exists.

## BP-MIAB-006 — Preserve identities while maintaining authentication

The stable upstream user_external 4.0.0 declaration stops at Nextcloud 34.
The edition builds its own IMAP-only app with its own ID, namespace and version
from reviewed, hash-checked Base/IMAP code and the guarded upstream migration.
The vendor payload, signature and compatibility declaration remain unchanged.
Preserve backend arguments, the users_external table, UIDs and display names;
refuse an unknown backend instead of silently changing it.

Validate consecutive server migrations, real login, wrong-password rejection,
DAV CRUD and byte-normalized fingerprints of existing contacts, events and users.
Nextcloud 35 retains deleted calendar tombstones, so deletion proof checks that
the owned synthetic object is inactive rather than assuming an HTTP 404 or a
physical row deletion. Directive: MIAB-04, MIAB-07, MIAB-11.

## BP-MIAB-007 — Preserve webmail encryption state

Regenerating Roundcube des_key on every install invalidates persistent cookies
and can invalidate encrypted plugin credentials. Read and validate the key before
replacing application code; generate a key only for a new installation. Keep it
in command substitution/in-memory configuration, never in diagnostic output.
Validate fingerprints and real authentication after the update. Directive:
MIAB-03, MIAB-05, MIAB-07.

Primary references reviewed 2026-10-07:
- [Roundcube 1.7.4](https://github.com/roundcube/roundcubemail/releases/tag/1.7.4)
- [Nextcloud 35 requirements](https://docs.nextcloud.com/server/stable/admin_manual/installation/system_requirements.html)
- [Upstream user_external 4.0.0](https://github.com/nextcloud/user_external/tree/v4.0.0)

Deployment evidence and raw logs stay in the private operations repository/server.
