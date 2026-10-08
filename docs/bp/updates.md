# Application updates

### BP-MIAB-021 — Keep the distribution package and contain its verification role
- Context: Ubuntu's current OpenDKIM package has new CVEs still under evaluation; Rspamd already verifies incoming DKIM.
- Mistake: treating a current distribution candidate as proof that every disclosed issue is patched, or assuming signing mode alone skips received signature tags.
- Cause: libopendkim processes received DKIM-Signature tags during signing unless the skip-header option excludes them. Duplicate verifiers also complicate Authentication-Results trust.
- Correct: retain the authenticated Ubuntu package; with Rspamd selected, use signer-only mode, omit received DKIM-Signature tags and preserve the verifier's cleaned results. Keep package evaluation explicit. Switching to another filter needs a fresh security review.
- Proof: native private signing/authenticated/untrusted probes; independent signature verification and body-tamper failure; forged results removal and native OpenDMARC alignment. Pause SMTP/queue writers during the signer restart, preserve current queues/keys/DNS and test recovery from the retained configuration.
- Directive: MIAB-03, MIAB-07, MIAB-11, MIAB-12.

### BP-MIAB-020 — Reconcile SQLite metadata with native DDL and current rows

- Context: historical upgrades left six ID columns as implicit rowid/autoincrement and a JSON column without its native Doctrine type comment.
- Mistake: treating all schema findings as runtime damage or all differences as harmless SQLite representation.
- Cause: actual column migrations, postSchemaChange indexes, historical tables and disabled-app migrations have distinct semantics. Compare a native fresh installation and publisher-generated DDL, not only version numbers.
- Correct: use the installed release's schema SQL, refuse changed columns, non-integer IDs, invalid JSON, foreign keys or triggers needing a separate review. Preserve every row and existing index in an atomic transaction. Test authenticated CRUD and old-metadata recovery over current new rows; never restore stale application data.
- Proof: `tests/test_nextcloud_schema_migration.py`; deployment clone evidence stays private. Existing partial UNIQUE and descending indexes are runtime guarantees, not objects to remove for a clean replay-based checker. Historical data is retained, and remaining unrecognised differences stay visible (MIAB-06/07/09).

### BP-MIAB-001 — Review release pins as well as the fork Git head
- Context: the fork was synchronized while its application pins still lagged behind supported maintenance releases.
- Mistake: interpreting a current fork commit as evidence that every component is current.
- Cause: OS packages, fork commits and downloaded application releases have separate update paths.
- Correct: inspect upstream changes individually, verify the publisher's latest stable release and checksum independently of upstream (MIAB-11), compare against the installed version, and test migrations on copied code/configuration/databases before production. Include major releases in the target inventory; document any compatibility blocker and the supported migration hops. A temporary maintenance-branch update does not satisfy the global latest-stable target. Pin Linux script line endings to LF and run `bash -n` on the exact transferred bytes before execution.
- Proof: Roundcube `1.6.19` pin/hash ported from upstream `d317da1`; Nextcloud `33.0.9` archive verified with the publisher's SHA256 before recording its SHA1 pin. Application upgrade rehearsals use isolated database copies. Deployment-specific results stay outside this public repository.
- Directive: MIAB-02, MIAB-04, MIAB-07, MIAB-11.

Sources checked 2026-10-07:
- [Roundcube security release](https://roundcube.net/news/2026/09/06/security-updates-1.6.19-and-1.7.4).
- [Nextcloud supported maintenance releases](https://nextcloud.com/changelog/).
- [Upstream Roundcube update](https://github.com/mail-in-a-box/mailinabox/commit/d317da15e14fbf28df802df38c8420b06c0ee8e7).

### BP-MIAB-002 — Isolate clone instance IDs and temporary state
- Context: an upgrade rehearsal used copied application code, configuration and databases on the same OS as the live instance.
- Mistake: preserving the live `instanceid` while running the rehearsal under another Unix user.
- Cause: Nextcloud `FileSequence` names lock files in the system temporary directory using the instance ID. A root-owned `0600` lock can prevent the web service user from continuing a live migration.
- Correct: assign a unique instance ID and private temporary directory before starting a same-host rehearsal. Run under the intended service identity when feasible. After a migration succeeds, explicitly finish maintenance mode before app configuration steps; verify schema state before resuming a failed installer.
- Proof: inspect `lib/private/Snowflake/FileSequence.php`; the rehearsal config must override both `instanceid` and `tempdirectory`. Recovery is limited to the verified regular lock file and matching service owner, followed by native `occ upgrade` and status checks. Database copies are not restored under newer application code.
- Directive: MIAB-03, MIAB-07.

### BP-MIAB-003 — Set generated webmail config readability explicitly
- Context: an installer inherited a restrictive root backup umask.
- Mistake: newly generated PHP configuration files were root-owned `0600`, so webmail returned a service-unavailable page even though its CLI migration succeeded.
- Cause: relying on inherited umask and existing-file modes for application configuration readability.
- Correct: explicitly set generated main and password-plugin configuration files to `root:www-data` and `0640`. Keep backups private and give installer subprocesses their intended umask. Verify file reads and an authenticated inbox through the web runtime.
- Proof: `setup/webmail.sh` applies ownership/mode after generating each file; a service-user read probe and real webmail login test validate the deployed result.
- Directive: MIAB-03, MIAB-07.
