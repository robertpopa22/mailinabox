"""Verificare PUBLICA a realitatii — folosit de zonele overlay.

Box-ul are resolver split-horizon (AD intern) -> nu putem avea incredere in ce
vede el. Aici interogam resolvere PUBLICE (1.1.1.1 / 8.8.8.8) + HTTP + TLS, ca sa
stabilim adevarul vazut din internet. Toate functiile sunt defensive (timeout,
try/except, valori sigure la esec).
"""

import os
import socket
import ssl
import datetime
import urllib.request

PUBLIC_RESOLVERS = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
TIMEOUT = 5

try:
	import dns.resolver
	import dns.message
	import dns.query
	import dns.flags
	import dns.rdatatype
	import dns.rcode
	_HAVE_DNS = True
except Exception:  # pragma: no cover
	_HAVE_DNS = False


def _resolver():
	r = dns.resolver.Resolver(configure=False)
	r.nameservers = list(PUBLIC_RESOLVERS)
	r.lifetime = TIMEOUT
	r.timeout = TIMEOUT
	return r


def query(domain, rtype):
	"""Public DNS lookup. Returns list of str answers (empty on NXDOMAIN/error)."""
	if not _HAVE_DNS:
		return []
	try:
		ans = _resolver().resolve(domain, rtype, raise_on_no_answer=False)
		out = []
		for r in ans:
			out.append(r.to_text())
		return out
	except Exception:
		return []


def get_a(domain):
	"""Public A records (IPv4 strings)."""
	return [x.strip() for x in query(domain, "A")]


def get_ns(domain):
	"""Public NS hostnames (lowercased, no trailing dot)."""
	return sorted({x.rstrip(".").lower() for x in query(domain, "NS")})


def get_mx(domain):
	"""Public MX as list of (preference:int, exchange:str-without-trailing-dot)."""
	out = []
	for rec in query(domain, "MX"):
		parts = rec.split()
		if len(parts) >= 2:
			try:
				out.append((int(parts[0]), parts[1].rstrip(".").lower()))
			except ValueError:
				pass
	return sorted(out)


def is_external_dns(domain, env):
	"""True daca domeniul e pe DNS extern (NS public != box-ul).

	Box-ul e nameserver propriu doar daca NS-ul public puncteaza catre el
	(ns1/ns2.<primary_hostname>). Altfel (Cloudflare, AD public, etc.) = extern.
	"""
	# urca la zona apex daca e subdomeniu (ex: www.x.ro -> x.ro)
	apex = registrable_domain(domain)
	ns = get_ns(apex)
	if not ns:
		return False  # nu putem stabili -> nu presupunem extern
	primary = env.get("PRIMARY_HOSTNAME", "").lower()
	box_ns_markers = {primary}
	if primary:
		box_ns_markers.add("ns1." + primary)
		box_ns_markers.add("ns2." + primary)
	for n in ns:
		if n in box_ns_markers or n.endswith("." + primary) or n == primary:
			return False  # box-ul e (printre) nameservere -> NU extern
	return True


def registrable_domain(domain):
	"""Aproximare apex zona: ultimele 2 etichete, cu tratare .co.uk-style minima.

	Pentru domeniile noastre (.ro, .com) e suficient ultimele 2 etichete.
	"""
	domain = domain.rstrip(".").lower()
	parts = domain.split(".")
	two_level_tlds = {"co.uk", "org.uk", "com.ro"}
	if len(parts) >= 3 and ".".join(parts[-2:]) in two_level_tlds:
		return ".".join(parts[-3:])
	if len(parts) >= 2:
		return ".".join(parts[-2:])
	return domain


def dnssec_status(domain):
	"""Returns 'secure' | 'insecure' | 'bogus' | 'unknown'.

	secure   = semnat si validat public (AD bit la resolver validator)
	insecure = nesemnat (fara DS) -> ok, optional
	bogus    = DS prezent dar validarea pica (SERVFAIL la resolver validator)
	"""
	if not _HAVE_DNS:
		return "unknown"
	apex = registrable_domain(domain)
	ds = query(apex, "DS")
	try:
		q = dns.message.make_query(apex, dns.rdatatype.SOA, want_dnssec=True)
		resp = dns.query.udp(q, PUBLIC_RESOLVERS[0], timeout=TIMEOUT)
		if resp.rcode() == dns.rcode.SERVFAIL:
			return "bogus" if ds else "unknown"
		if resp.flags & dns.flags.AD:
			return "secure"
		return "insecure" if not ds else "secure"
	except Exception:
		return "unknown"


def http_live(domain, timeout=TIMEOUT):
	"""GET https://<domain>/ (fallback http). Returns dict(ok, status, final, server, error)."""
	for scheme in ("https", "http"):
		url = f"{scheme}://{domain}/"
		try:
			req = urllib.request.Request(url, method="GET", headers={
				"User-Agent": "Mozilla/5.0 (Geseidl-Edition status overlay)",
			})
			with urllib.request.urlopen(req, timeout=timeout) as resp:
				return {
					"ok": 200 <= resp.status < 400,
					"status": resp.status,
					"final": resp.geturl(),
					"server": resp.headers.get("Server", ""),
					"error": None,
				}
		except urllib.error.HTTPError as e:
			# 4xx/5xx: site raspunde (e "live"), dar nu 2xx
			return {"ok": e.code < 500, "status": e.code, "final": url, "server": "", "error": None}
		except Exception as e:
			last = str(e)
			continue
	return {"ok": False, "status": None, "final": None, "server": "", "error": last}


def smtp_reachable(host, port=25, timeout=TIMEOUT):
	"""TCP connect + read greeting. Returns (ok, banner|error)."""
	try:
		with socket.create_connection((host, port), timeout=timeout) as s:
			s.settimeout(timeout)
			banner = s.recv(256).decode("utf-8", "replace").strip()
			return (banner.startswith("220"), banner)
	except Exception as e:
		return (False, str(e))


def tls_cert_days(host, port=443, timeout=TIMEOUT):
	"""Zile pana la expirarea certului prezentat de host:port. None la esec."""
	try:
		ctx = ssl.create_default_context()
		with socket.create_connection((host, port), timeout=timeout) as sock:
			with ctx.wrap_socket(sock, server_hostname=host) as ssock:
				cert = ssock.getpeercert()
		not_after = cert.get("notAfter")
		if not not_after:
			return None
		exp = datetime.datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
		return (exp - datetime.datetime.utcnow()).days
	except Exception:
		return None


_DQS_KEY = None
_DQS_SCANNED = False


def get_dqs_key():
	"""Citeste cheia Spamhaus DQS din configul rspamd (NU hardcodata in repo).

	Cauta pattern-ul <key>.{zen,dbl}.dq.spamhaus in /etc/rspamd/. Returns key sau None.
	"""
	global _DQS_KEY, _DQS_SCANNED
	if _DQS_SCANNED:
		return _DQS_KEY
	_DQS_SCANNED = True
	import re as _re
	pat = _re.compile(r"([a-z0-9]{20,})\.(?:zen|dbl)\.dq\.spamhaus", _re.I)
	for base in ("/etc/rspamd", "/home/user-data/conf/rspamd"):
		if not os.path.isdir(base):
			continue
		for root, _dirs, names in os.walk(base):
			for n in names:
				try:
					with open(os.path.join(root, n), encoding="utf-8", errors="ignore") as f:
						m = pat.search(f.read())
						if m:
							_DQS_KEY = m.group(1)
							return _DQS_KEY
				except OSError:
					pass
	return _DQS_KEY


def _dqs_lookup(qname):
	"""Returns 'clean' (NXDOMAIN), 'listed' (127.x.x.x), 'error'/'nokey'/'unknown'."""
	ans = query(qname, "A")
	if not ans:
		# distinge NXDOMAIN (clean) de eroare? query() inghite ambele -> tratam empty=clean
		return "clean"
	if any(a.startswith("127.") for a in ans):
		# 127.255.255.x = erori DQS (cheie invalida/limita), nu listare reala
		if any(a.startswith("127.255.255.") for a in ans):
			return "error"
		return "listed"
	return "unknown"


def spamhaus_ip(ip):
	"""Verifica IP in zen via DQS. Returns dict(ok, status, codes)."""
	key = get_dqs_key()
	if not key:
		return {"ok": None, "status": "nokey", "codes": None}
	parts = ip.split(".")
	if len(parts) != 4:
		return {"ok": None, "status": "badip", "codes": None}
	rev = ".".join(reversed(parts))
	qname = f"{rev}.{key}.zen.dq.spamhaus.net"
	st = _dqs_lookup(qname)
	codes = query(qname, "A") if st == "listed" else None
	return {"ok": st == "clean", "status": st, "codes": codes}


def spamhaus_domain(domain):
	"""Verifica domeniu in dbl via DQS. Returns dict(ok, status, codes)."""
	key = get_dqs_key()
	if not key:
		return {"ok": None, "status": "nokey", "codes": None}
	qname = f"{domain}.{key}.dbl.dq.spamhaus.net"
	st = _dqs_lookup(qname)
	codes = query(qname, "A") if st == "listed" else None
	return {"ok": st == "clean", "status": st, "codes": codes}


def mta_sts_present(domain, timeout=TIMEOUT):
	"""Verifica MTA-STS real: TXT _mta-sts.<domain> + policy la mta-sts.<domain>.

	Returns dict(ok, has_txt, has_policy, detail).
	"""
	txt = query("_mta-sts." + domain, "TXT")
	has_txt = any("v=STSv1" in t for t in txt)
	has_policy = False
	detail = ""
	try:
		url = f"https://mta-sts.{domain}/.well-known/mta-sts.txt"
		req = urllib.request.Request(url, headers={"User-Agent": "Geseidl-Edition"})
		with urllib.request.urlopen(req, timeout=timeout) as resp:
			body = resp.read(4096).decode("utf-8", "replace")
			has_policy = "version: STSv1" in body or "version:STSv1" in body
			if not has_policy:
				detail = "policy fara version: STSv1"
	except Exception as e:
		detail = f"policy inaccesibila ({e})"
	return {
		"ok": has_txt and has_policy,
		"has_txt": has_txt,
		"has_policy": has_policy,
		"detail": detail,
	}
