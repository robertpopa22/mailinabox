# Geseidl Edition — Overlay Framework

> Customizările Geseidl pentru Mail-in-a-Box, ca **addon (overlay)** peste un upstream curat.
> Scop: rămânem 100% aliniați cu `upstream/main`, iar tot ce e Geseidl trăiește în pachete
> separate aplicate peste, grupate pe zone. La fiecare upgrade upstream: `git pull` + re-aplicare overlay.

---

## De ce overlay și nu fork divergent

Varianta veche (`geseidl-edition` branch) edita inline fișierele upstream — ~200 linii
împrăștiate doar în `status_checks.py`. Rezultat: **conflicte de merge la fiecare upgrade**.

Overlay-ul inversează raportul:

- **Cod upstream**: rămâne neatins (sau atins minim, în blocuri marcate `# >>> GESEIDL ... # <<< GESEIDL`).
- **Cod Geseidl**: în pachete proprii (`management/geseidl_edition/`, `setup/geseidl_edition/`),
  care nu intră niciodată în conflict cu upstream.
- **Marker + manifest** (`.geseidl-edition`): dacă există, applier-ul aplică zonele active.

Reaplicare = rulezi două appliers idempotente; ele reinserează hook-urile mici și
re-rulează delta-urile de provisioning. Logica grea nu se atinge.

---

## Componente

```
.geseidl-edition                       # MANIFEST + MARKER (la radacina repo / /root/mailinabox)
management/geseidl_edition/            # overlay RUNTIME (Python, hooks in daemon/management)
  __init__.py
  manifest.py                          # citeste .geseidl-edition (zone active, upstream_base)
  engine.py                            # normalizeaza rezultatele check + ruleaza procesoarele de zona
  dnsutil.py                           # interogari DNS PUBLIC (1.1.1.1/8.8.8.8) + HTTP live + TLS
  apply_overlay.py                     # applier idempotent: insert/remove/status/selftest hooks
  zones/
    __init__.py                        # registry zone runtime
    status.py                          # zona status: re-verificare check-uri + badge versiune
  OVERLAY.md                           # acest document
setup/geseidl_edition/                 # overlay PROVISIONING (shell/config, rulat dupa setup upstream)
  apply_setup_overlay.sh               # applier idempotent pe zone (spam/mail/dns/web/ssl)
```

### Manifest `.geseidl-edition`

```yaml
edition: geseidl
upstream_base: v75          # versiunea upstream pe care e bazat overlay-ul
zones:                      # zone active (runtime si/sau provisioning)
  - status
  # - spam      (de migrat)
  # - mail      (de migrat)
  # - dns       (de migrat)
  # - web       (de migrat)
  # - ssl       (de migrat)
```

Prezența fișierului = overlay activ. Lista `zones` decide ce se aplică.

---

## Harta zonelor (inventar complet)

Toate customizările Geseidl, grupate. Sursă: feature branches existente + check-uri noi.

| Zonă | Conținut | Tip | Status |
|------|----------|-----|--------|
| **status** | external-dns/nat false-positives, badge versiune fork, site-live, MX afirmativ, cert expiry, DNSSEC public, MTA-STS real | runtime | **implementat** |
| **spam** | rspamd-spam-filter, rspamd-hardening, whitelist/blacklist API, spamhaus DQS | provisioning + runtime (API) | de migrat |
| **mail** | email-archive (`always_bcc`), imapsieve-trash-fix | provisioning + settings | de migrat |
| **dns** | external-dns-settings, spamhaus bind9 forwarders | provisioning (bind9) + settings | de migrat |
| **web** | webmail-subdomain (nginx + Roundcube per-domeniu), aliases UI fix | provisioning (nginx) + UI | de migrat |
| **ssl** | cert-renewal-public-dns-check | provisioning/runtime | de migrat |

Runtime vs provisioning:
- **runtime** = cod Python care se cuplează în daemon-ul de management la rulare (hook marcat).
- **provisioning** = pași de setup / fișiere de config aplicate **după** `setup/start.sh` upstream,
  idempotent, de către `apply_setup_overlay.sh`.

---

## Zona `status` — comportament

Pagina admin `#system_status` apelează `/system/status` (daemon.py), care rulează
`run_checks()` upstream și colectează rezultate într-o listă structurată. Overlay-ul
**post-procesează** acea listă.

Principiu cheie: **NU mascăm orbește**. Re-verificăm fiecare eroare față de realitatea
**publică** (DNS 1.1.1.1/8.8.8.8, HTTP, TLS) și o trecem pe verde DOAR dacă chiar e în regulă
în lumea reală. Erorile pe care nu le recunoaștem rămân vizibile (nu ascundem probleme noi).

Cauze rădăcină ale false-pozitivelor pe acest box:
1. **DNS extern** — domeniile sunt pe Cloudflare; MiaB se așteaptă să fie EL nameserverul.
2. **NAT + resolver split-horizon** — box `82.79.229.146` public / `10.0.1.89` privat; resolverul
   intern (AD) întoarce IP-uri interne. Publicul e corect.

| Check upstream | Re-verificare overlay | Rezultat |
|---|---|---|
| Versiune nouă MiaB disponibilă | comparăm baza upstream din tag-ul fork (`geseidl-vNN-...`) cu ultima upstream | ✓ „Geseidl Edition — aliniat cu upstream vNN" + badge |
| NS / glue records „incorecte" | dacă NS public ≠ box ⇒ DNS extern intenționat | ✓ „DNS gestionat extern" |
| „trebuie să rezolve la IP-ul box" (subdomenii servite) | A public == IP public box? | ✓ dacă da, altfel rămâne ✖ |
| „ar trebui să rezolve la box" (site găzduit altundeva) | înlocuit cu **site-live** (HTTP/HTTPS GET) | ✓ dacă site răspunde |
| MX „lipsă" | MX public == `mail.geseidl.ro`? | ✓ dacă da, altfel ✖ |
| DNSSEC DS lipsă/greșit | lanț DNSSEC valid în DNS public? | ✓ dacă valid, altfel ✖ |
| MTA-STS lipsă | policy reală (TXT `_mta-sts` + `https://mta-sts.<d>/.well-known/mta-sts.txt`) | ✓ dacă există, ✖ acționabil dacă nu |

Check-uri **noi** adăugate per domeniu: site-live, MX-afirmativ + SMTP 25 reachable,
cert expiry pe subdomeniile servite (`mail.`/`autoconfig.`/`autodiscover.`), DNSSEC validat public.

---

## Workflow upgrade upstream

```bash
# 1. Aliniere cu upstream (curat)
git fetch upstream && git merge upstream/main      # conflicte doar pe blocurile marcate (mici)

# 2. Reaplicare overlay (idempotent, citeste .geseidl-edition)
python3 management/geseidl_edition/apply_overlay.py apply
sudo bash setup/geseidl_edition/apply_setup_overlay.sh   # cand zonele provisioning sunt migrate

# 3. Restart daemon management
sudo systemctl restart mailinabox
```

`apply_overlay.py`:
- `status`  — arată ce hook-uri sunt aplicate / lipsesc
- `apply`   — inserează blocurile marcate lipsă (idempotent)
- `remove`  — scoate blocurile marcate (revine la upstream curat)
- `selftest`— rulează engine-ul pe un eșantion de rezultate, fără server

---

## Reguli

- Hook în fișier upstream = **doar** bloc marcat `# >>> GESEIDL EDITION OVERLAY >>>` / `# <<< ... <<<`,
  cât mai mic, cu `try/except` (o eroare în overlay nu trebuie să spargă pagina de status).
- Logica reală trăiește **exclusiv** în `geseidl_edition/` — niciodată în corpul funcțiilor upstream.
- Orice check nou re-verifică realitatea; nu presupune, nu maschează.
- O zonă nouă = un fișier în `zones/` (runtime) și/sau un folder în `setup/.../zones/` (provisioning),
  înregistrat în manifest.

---

## Vezi și

- Infra MAIL02: `NET-ADMIN/GESEIDL/GES-MAIL01/` (folder = denumire veche; serverul e MAIL02)
- Fork: `robertpopa22/mailinabox`
