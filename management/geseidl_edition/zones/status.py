"""Zona STATUS — corecteaza false-pozitivele paginii de status si adauga badge versiune.

Principiu: NU mascam orbeste. Fiecare eroare upstream o re-verificam fata de
realitatea PUBLICA (DNS 1.1.1.1, HTTP, TLS) si o trecem pe verde DOAR daca chiar e
in regula. Ce nu recunoastem ramane neatins (nu ascundem probleme noi).
"""

import re

from .. import dnsutil
from ..engine import mk

EDITION = "Geseidl Edition"

# ---- detectie host din mesaj ---------------------------------------------

_HOST_PREFIX = re.compile(r"^([a-z0-9][a-z0-9_.-]*\.[a-z]{2,}):\s")


def _host_from(text, default):
	m = _HOST_PREFIX.match(text.strip())
	return (m.group(1) if m else default).lower()


def _box_served(host, env):
	"""Subdomenii pe care box-ul le serveste direct (trebuie sa puncteze la box)."""
	host = host.lower()
	if host == env.get("PRIMARY_HOSTNAME", "").lower():
		return True
	apex = dnsutil.registrable_domain(host)
	return host in {f"autoconfig.{apex}", f"autodiscover.{apex}", f"mail.{apex}"}


# ---- version badge --------------------------------------------------------

_VER_MARKERS = (
	"version of Mail-in-a-Box is available",
	"Mail-in-a-Box is up to date",
	"version check disabled by privacy",
	"version could not be determined",
	"You are running version Mail-in-a-Box",
)


def _version_badge(env, manifest=None):
	"""Returneaza (kind, text, extra) pentru linia de versiune fork-aware."""
	ov = (manifest or {}).get("overlay_version") or "?"
	this_ver = latest = base = None
	try:
		from status_checks import what_version_is_this, get_latest_miab_version
		try:
			this_ver = what_version_is_this(env)
		except Exception:
			this_ver = None
		latest = get_latest_miab_version()
	except Exception:
		pass

	m = re.match(r"geseidl[-_](v[0-9][0-9.]*)", this_ver or "", re.I)
	base = m.group(1) if m else None
	logo = [{"text": f"◈ Mail-in-a-Box {EDITION} v{ov} — overlay activ", "monospace": True}]

	if base and latest and base == latest:
		return ("ok",
			f"{EDITION}: la zi, aliniat cu upstream {latest}. (rulezi {this_ver})",
			logo)
	if base and latest and base != latest:
		# Fork controlat de noi: ramane VERDE; upstream nou = info, nu eroare.
		note = list(logo) + [{"text": f"↑ upstream {latest} disponibil — rebase optional", "monospace": True}]
		return ("ok",
			f"{EDITION}: rulezi {this_ver} (bazat pe upstream {base}).",
			note)
	if this_ver:
		return ("ok", f"{EDITION}: rulezi {this_ver}." + (f" Upstream: {latest}." if latest else ""), logo)
	return ("ok", f"{EDITION}: overlay activ.", logo)


# ---- re-verificare per item ----------------------------------------------

def _reverify_item(item, domain, env, external):
	"""Returneaza un record nou (transformat) sau None ca sa pastram itemul neatins.

	`domain` = numele sectiunii (apex sau subdomeniu). `external` = DNS extern pe apex.
	"""
	if item["kind"] not in ("error", "warning"):
		return None
	t = item["text"]
	public_ip = env.get("PUBLIC_IP", "")
	primary = env.get("PRIMARY_HOSTNAME", "")

	# 1) NS / glue records "incorecte" -> daca DNS extern, e intentionat
	if "glue records are incorrect" in t or "nameservers set on this domain are incorrect" in t:
		if external:
			ns = ", ".join(dnsutil.get_ns(dnsutil.registrable_domain(domain))) or "extern"
			return mk("ok", f"{domain}: DNS gestionat extern ({ns}) — corect pentru setup-ul nostru. [{EDITION}]")
		return None  # box ar trebui sa fie NS dar nu e -> real

	# 2) "must/should resolve to this box's IP"
	if "resolve to this box's IP" in t:
		host = _host_from(t, domain)
		pub_a = dnsutil.get_a(host)
		if _box_served(host, env):
			if public_ip in pub_a:
				return mk("ok", f"{host}: rezolva public corect la IP-ul box ({public_ip}) — verificat 1.1.1.1. [{EDITION}]")
			return mk("error", f"{host}: NU rezolva public la box ({public_ip}); public={', '.join(pub_a) or 'n/a'}. De adaugat A in DNS extern. [{EDITION}]")
		# domeniu web gazduit altundeva -> nu trebuie sa puncteze la box; verificam ca site-ul e VIU
		live = dnsutil.http_live(host)
		where = ", ".join(pub_a) or "n/a"
		if live["ok"]:
			extra = [{"text": f"gazduit la {where}{(' / ' + live['server']) if live['server'] else ''}", "monospace": True}]
			return mk("ok", f"{host}: site activ (HTTP {live['status']}) — gazduit extern, nu pe box (corect). [{EDITION}]", extra)
		return mk("error", f"{host}: site nu raspunde (HTTP) la {where}. {live.get('error') or ''} [{EDITION}]")

	# 3) MX lipsa -> verificam MX public real
	if "DNS MX record is not set" in t or "MX record" in t and "not set" in t:
		mx = dnsutil.get_mx(domain)
		ok = any(ex == primary.lower() or ex.endswith("." + primary.lower()) or ex == primary.lower() for _, ex in mx)
		if ok:
			mxs = ", ".join(f"{p} {ex}" for p, ex in mx)
			return mk("ok", f"{domain}: MX public corect ({mxs}) — mailul ajunge la box. Verificat 1.1.1.1. [{EDITION}]")
		return mk("error", f"{domain}: MX public NU puncteaza la {primary} (gasit: {mx or 'niciunul'}). [{EDITION}]")

	# 4) DNSSEC DS lipsa / incorect -> verificam lantul public
	if "DNSSEC DS record" in t:
		st = dnsutil.dnssec_status(domain)
		if st == "secure":
			return mk("ok", f"{domain}: DNSSEC semnat & validat public. [{EDITION}]")
		if st == "insecure":
			return mk("ok", f"{domain}: DNSSEC neactivat (optional) — DNS gestionat extern. [{EDITION}]")
		if st == "bogus":
			return mk("error", f"{domain}: DNSSEC INVALID public (lant rupt) — de corectat la registrar/Cloudflare. [{EDITION}]")
		return None  # unknown -> nu atingem

	# 5) MTA-STS lipsa -> il vrem ACTIV pe toate; verificam policy reala
	if "MTA-STS policy is missing" in t or ("MTA-STS" in t and "missing" in t):
		res = dnsutil.mta_sts_present(domain)
		if res["ok"]:
			return mk("ok", f"{domain}: MTA-STS prezent (TXT _mta-sts + policy). Verificat public. [{EDITION}]")
		miss = []
		if not res["has_txt"]:
			miss.append("TXT _mta-sts")
		if not res["has_policy"]:
			miss.append("policy host")
		return mk("error", f"{domain}: MTA-STS lipseste ({', '.join(miss)}) — de provizionat (Cloudflare TXT + mta-sts.{domain}). [{EDITION}]")

	# 6) spamhaus RBL "could not determine" (shared resolver) -> re-verificam via DQS
	if "configured to use a public DNS server" in t or ("spamhaus" in t.lower() and "Could not determine" in t):
		if "this box" in t or "IPv4 address is blacklisted" in t:
			res = dnsutil.spamhaus_ip(public_ip)
			target = f"IP {public_ip}"
		else:
			m = re.search(r"whether the domain (\S+?) is blacklisted", t)
			dom = m.group(1) if m else domain
			res = dnsutil.spamhaus_domain(dom)
			target = dom
		if res["status"] == "clean":
			return mk("ok", f"{target}: nu e pe lista Spamhaus (verificat DQS). [{EDITION}]")
		if res["status"] == "listed":
			return mk("error", f"{target}: LISTAT Spamhaus {res['codes']} — afecteaza livrarea! [{EDITION}]")
		return None  # nokey/error/unknown -> lasam ? informativ (nu mascam)

	# necunoscut -> pastram neatins (nu mascam)
	return None


def _process_domain_section(section, env):
	domain = (section["name"] or "").lower()
	if not domain or "." not in domain:
		return
	apex = dnsutil.registrable_domain(domain)
	external = dnsutil.is_external_dns(domain, env)

	apex_sitelive_done = False
	new_items = []
	for item in section["items"]:
		try:
			rep = _reverify_item(item, domain, env, external)
		except Exception:
			rep = None  # un check picat nu trebuie sa darame sectiunea
		if rep is None:
			new_items.append(item)
		else:
			new_items.append(rep)
			if "site activ" in rep["text"] and _host_from(item["text"], domain) == domain:
				apex_sitelive_done = True
	section["items"] = new_items

	# Check NOU: site activ pentru apex web (gazduit altundeva), daca nu a fost deja convertit
	is_served = _box_served(domain, env)
	if not is_served and domain == apex and not apex_sitelive_done:
		live = dnsutil.http_live(domain)
		pub_a = ", ".join(dnsutil.get_a(domain)) or "n/a"
		if live["status"] is not None:
			if live["ok"]:
				section["items"].append(mk("ok", f"{domain}: site activ (HTTP {live['status']}) — gazduit la {pub_a}. [{EDITION}]"))
			else:
				section["items"].append(mk("warning", f"{domain}: site raspunde HTTP {live['status']} la {pub_a}. [{EDITION}]"))


# ---- entrypoint zona ------------------------------------------------------

def process_sections(sections, env, pool, manifest):
	for section in sections:
		name = (section["name"] or "")
		if name == "System":
			# inlocuieste linia de versiune cu badge-ul fork
			kind, text, extra = _version_badge(env, manifest)
			replaced = False
			for item in section["items"]:
				if item["kind"] in ("ok", "error", "warning") and any(mk_ in item["text"] for mk_ in _VER_MARKERS):
					item["kind"], item["text"], item["extra"] = kind, text, extra
					replaced = True
					break
			if not replaced:
				section["items"].append(mk(kind, text, extra))
			# Backup: gestionat extern (GES-BACKUP), nu prin MiaB
			for item in section["items"]:
				if item["kind"] == "warning" and "Backups are disabled" in item["text"]:
					item["kind"] = "ok"
					item["text"] = f"Backup gestionat extern (GES-BACKUP), nu prin MiaB. [{EDITION}]"
		elif name == "Network":
			# re-verifica spamhaus pt IP-ul box-ului (DQS); restul ramane
			def _safe(it):
				try:
					return _reverify_item(it, "", env, False) or it
				except Exception:
					return it
			section["items"] = [_safe(it) for it in section["items"]]
		elif name in ("", None):
			continue
		else:
			_process_domain_section(section, env)
