# Zona spam — rspamd (Geseidl Edition)

rspamd înlocuiește SpamAssassin ca filtru de spam. Cel mai mare subsistem din overlay.
Selecția filtrului = `spam_filter: rspamd` în `settings.yaml`; tot codul de integrare
e condiționat de această cheie.

## Amprentă (fișiere)

Două tipuri de artefacte — vezi `apply.sh`:

### 1. Fișiere noi (fork-tracked, NU conflictează la `git merge upstream`)

| Fișier | Rol |
|--------|-----|
| `setup/rspamd.sh` (446 linii) | Installer rspamd (configs local.d/override.d, maps, DQS, hardening, IMAPSieve learn) |
| `management/templates/system-spam.html` | UI admin: comutare filtru + whitelist/blacklist + link rspamd UI |

Upstream nu are aceste fișiere → rămân în repo, fără conflict. `apply.sh` doar verifică prezența.

### 2. Patch-uri peste fișiere upstream (`patches/`, idempotente)

| Patch | Țintă upstream | Conținut | Signature (idempotență) |
|-------|----------------|----------|-------------------------|
| `mail-postfix.patch` | `setup/mail-postfix.sh` | content_filter SA→rspamd: `virtual_transport` 10026 + `smtpd_milters` 11332/8891/8893 condiționat de `spam_filter` | `inet:127.0.0.1:11332` |
| `spamassassin.patch` | `setup/spamassassin.sh` | dacă rspamd → `source setup/rspamd.sh; exit 0`; altfel reverse-migration (rspamd→SA) + generare whitelist/blacklist din settings.yaml | `source setup/rspamd.sh` |
| `daemon-spam-api.patch` | `management/daemon.py` | API `/system/spam-filter` (GET/POST), `/system/spam-whitelist` (GET/POST), proxy rspamd UI (`/rspamd-auth`, `/rspamd/`) | `/system/spam-filter` |
| `index-html.patch` | `management/templates/index.html` | nav link + `<div id="panel_spam_filter">` include system-spam.html | `panel_spam_filter` |

**Notă:** hook-ul de status din `daemon.py` (`# >>> GESEIDL EDITION OVERLAY >>>` la `system_status()`)
NU e în aceste patch-uri — îl gestionează `management/geseidl_edition/apply_overlay.py` (zona status, runtime).
`check „rspamd active"` în `status_checks.py` e baked upstream-side (nu necesită patch aici).

## Cum aplică `apply.sh` (signature-gate + dry-run + syntax-check + auto-revert)

Pentru fiecare patch: dacă signature deja prezentă în țintă → **skip** (baked sau deja aplicat);
altfel `patch --dry-run` → dacă trece, aplică real → verifică sintaxa (py `ast.parse` via stdin /
shell `bash -n`) → la eroare **revert automat**. Apoi setează `spam_filter: rspamd` în settings.yaml
(dacă lipsește), ca reconstituirea pristine să selecteze rspamd.

**Box LIVE cu rspamd activ:** filtrul NU se re-provisionează. Patch-urile sar (signature prezente),
selecția există → no-op sigur.

**⚠️ Efect:** patch-urile pe `setup/*.sh` prind efect la următorul `sudo mailinabox` (full setup),
nu doar la `systemctl restart mailinabox` (care reîncarcă doar daemon-ul → API/UI).

## Reconstituire (sistem pristine upstream)

```bash
git pull upstream                                          # fișierele upstream rămân curate
python3 management/geseidl_edition/apply_overlay.py apply  # hook runtime (status) + restul
sudo bash setup/geseidl_edition/apply_setup_overlay.sh     # aplică patch-urile spam (+ celelalte zone)
sudo mailinabox                                            # full setup: instalează+integrează rspamd
```

Verificat pe checkout pristine v75: cele 4 patch-uri se aplică curat, sintaxă OK, signature prezente.
A doua rulare = skip-all (idempotent).

## DQS

Cheia Spamhaus DQS e în configul rspamd (`/etc/rspamd/`), citită runtime de zona **status**
pentru re-verificarea RBL. Vezi `management/geseidl_edition/dnsutil.py:get_dqs_key()`.
