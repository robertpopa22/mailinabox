# Zona spam — rspamd (Geseidl Edition)

rspamd înlocuiește SpamAssassin ca filtru de spam. Cel mai mare subsistem din overlay.

## Amprentă (fișiere)

| Fișier | Rol | Tip în overlay |
|--------|-----|----------------|
| `setup/rspamd.sh` (446 linii) | Installer rspamd (configs local.d/override.d, maps, DQS, hardening) | fork-tracked în `setup/` — **NU conflictează cu upstream** (upstream n-are rspamd.sh) |
| `setup/mail-postfix.sh` | content_filter SA→rspamd (milter) | patch peste upstream — **TODO** |
| `setup/spamassassin.sh` | reverse-migration rspamd→SA | patch peste upstream — **TODO** |
| `management/daemon.py` | API: `/system/spam-filter` (GET/POST), `/system/spam-whitelist` (GET/POST) | patch/hook — **TODO** |
| `management/templates/system-spam.html`, `index.html` | UI admin spam + whitelist | patch — **TODO** |
| `management/status_checks.py` | check „rspamd active" | deja prezent (baked) |

## Stare

- **Producție (MAIL02): rspamd activ + `spam_filter: rspamd`** → `apply.sh` sare (nu re-provisionează filtrul live).
- Installer-ul `setup/rspamd.sh` rămâne fork-tracked (nu conflictează la `git pull upstream`).
- **De finalizat (trecere dedicată):** extragerea patch-urilor de integrare (mail-postfix, spamassassin, daemon API, templates UI) ca artefacte overlay, ca reconstituirea pe upstream pristine să fie completă. Necesită baseline upstream-v75 per fișier + verificare clasificare spam/API/UI.

## Reconstituire (sistem pristine)

`spam_filter: rspamd` în settings.yaml → setup-ul MiaB rulează `setup/rspamd.sh`. Integrarea
(milter postfix, dezactivare SA) e aplicată în cadrul setup-ului. `apply.sh` asigură selecția.

## DQS

Cheia Spamhaus DQS e în configul rspamd (`/etc/rspamd/`), citită runtime de zona **status**
pentru re-verificarea RBL. Vezi `management/geseidl_edition/dnsutil.py:get_dqs_key()`.
