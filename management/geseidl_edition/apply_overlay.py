#!/usr/bin/env python3
"""Applier idempotent pentru hook-urile overlay Geseidl Edition.

Inserează/scoate blocuri marcate `# >>> GESEIDL EDITION OVERLAY >>>` în fișierele
upstream (daemon.py, status_checks.py). De rulat după fiecare `git pull upstream`.

Comenzi:
  apply     insereaza hook-urile lipsa (idempotent)
  remove    scoate hook-urile (revine la upstream curat)
  status    arata ce e aplicat / lipsa
  selftest  ruleaza engine-ul pe un esantion, fara server

Activ doar daca markerul .geseidl-edition exista (vezi manifest.py).
"""

import os
import sys
import json
import hashlib
import datetime

MARK_START = "# >>> GESEIDL EDITION OVERLAY >>>"
MARK_END = "# <<< GESEIDL EDITION OVERLAY <<<"

MGMT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_DIR = os.path.dirname(os.path.abspath(__file__))
STAMP_FILE = os.path.join(PKG_DIR, ".deployed")


def compute_fingerprint():
	"""sha256 peste sursa overlay (toate .py + zones). Identifica exact ce ruleaza."""
	h = hashlib.sha256()
	files = []
	for root, dirs, names in os.walk(PKG_DIR):
		dirs[:] = [d for d in dirs if d != "__pycache__"]
		for n in sorted(names):
			if n.endswith(".py"):
				files.append(os.path.join(root, n))
	for path in sorted(files):
		rel = os.path.relpath(path, PKG_DIR).replace("\\", "/")
		h.update(rel.encode())
		with open(path, "rb") as f:
			h.update(f.read())
	return h.hexdigest()


def overlay_version():
	sys.path.insert(0, MGMT_DIR)
	from geseidl_edition import manifest
	return manifest.load_manifest().get("overlay_version") or "?"


def write_stamp():
	stamp = {
		"overlay_version": overlay_version(),
		"fingerprint": compute_fingerprint(),
		"applied_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
	}
	try:
		with open(STAMP_FILE, "w", encoding="utf-8") as f:
			json.dump(stamp, f, indent=2)
	except OSError:
		pass
	return stamp


def read_stamp():
	try:
		with open(STAMP_FILE, encoding="utf-8") as f:
			return json.load(f)
	except (OSError, ValueError):
		return None


def _t(s):
	# normalizeaza: blocurile sunt scrise cu TAB-uri (stil MiaB)
	return s


# Fiecare hook: file, mode (after|replace), anchor (linie exacta), signature
# (substring unic care indica ca e aplicat), block (text inserat, fara marker).
HOOKS = [
	{
		"name": "daemon:/system/status",
		"file": "daemon.py",
		"mode": "after",
		"anchor": "\t\trun_checks(False, env, output, pool)",
		"signature": "_ges_apply(output, env, pool)",
		"block": (
			"\t\ttry:\n"
			"\t\t\tfrom geseidl_edition import apply_overlay as _ges_apply\n"
			"\t\t\t_ges_apply(output, env, pool)\n"
			"\t\texcept Exception as _ges_e:\n"
			"\t\t\toutput.items.append({\"type\": \"warning\", \"text\": \"Geseidl overlay: %s\" % _ges_e, \"extra\": []})\n"
		),
		"indent": "\t\t",
	},
	{
		"name": "status_checks:daily-email",
		"file": "status_checks.py",
		"mode": "after",
		"anchor": "\trun_checks(True, env, cur, pool)",
		"signature": "_ges_apply_buf(cur.buf, env)",
		"block": (
			"\ttry:\n"
			"\t\tfrom geseidl_edition import apply_overlay_buffer as _ges_apply_buf\n"
			"\t\t_ges_apply_buf(cur.buf, env)\n"
			"\texcept Exception:\n"
			"\t\tpass\n"
		),
		"indent": "\t",
	},
	{
		"name": "status_checks:console",
		"file": "status_checks.py",
		"mode": "replace",
		"anchor": "\t\t\trun_checks(False, env, ConsoleOutput(), pool)",
		"signature": "_ges_buf = BufferedOutput()",
		"block": (
			"\t\t\ttry:\n"
			"\t\t\t\tfrom geseidl_edition import apply_overlay_buffer as _ges_apply_buf\n"
			"\t\t\t\t_ges_buf = BufferedOutput()\n"
			"\t\t\t\trun_checks(False, env, _ges_buf, pool)\n"
			"\t\t\t\t_ges_apply_buf(_ges_buf.buf, env)\n"
			"\t\t\t\t_ges_buf.playback(ConsoleOutput())\n"
			"\t\t\texcept Exception:\n"
			"\t\t\t\trun_checks(False, env, ConsoleOutput(), pool)\n"
		),
		"indent": "\t\t\t",
	},
]


def _read(path):
	with open(path, encoding="utf-8") as f:
		return f.read()


def _write(path, text):
	with open(path, "w", encoding="utf-8", newline="\n") as f:
		f.write(text)


def _wrapped(hook):
	ind = hook["indent"]
	return f"{ind}{MARK_START}\n{hook['block']}{ind}{MARK_END}\n"


def is_applied(hook, text):
	return hook["signature"] in text


def apply_hook(hook):
	path = os.path.join(MGMT_DIR, hook["file"])
	text = _read(path)
	if is_applied(hook, text):
		return "already"
	lines = text.split("\n")
	anchor = hook["anchor"]
	for i, line in enumerate(lines):
		if line == anchor:
			block = _wrapped(hook).rstrip("\n")
			if hook["mode"] == "after":
				lines[i] = anchor + "\n" + block
			else:  # replace
				lines[i] = block
			_write(path, "\n".join(lines))
			return "applied"
	return "anchor-not-found"


def remove_hook(hook):
	path = os.path.join(MGMT_DIR, hook["file"])
	text = _read(path)
	if not is_applied(hook, text):
		return "absent"
	lines = text.split("\n")
	out, i = [], 0
	removed = False
	while i < len(lines):
		if lines[i].strip() == MARK_START and any(hook["signature"] in lines[j] for j in range(i, min(i + 15, len(lines)))):
			# sari pana la MARK_END
			j = i
			while j < len(lines) and lines[j].strip() != MARK_END:
				j += 1
			if hook["mode"] == "replace":
				out.append(hook["anchor"])
			i = j + 1
			removed = True
			continue
		out.append(lines[i])
		i += 1
	if removed:
		_write(path, "\n".join(out))
		return "removed"
	return "not-removed"


def cmd_version():
	man_ver = overlay_version()
	fp = compute_fingerprint()
	print(f"Geseidl Edition overlay v{man_ver}")
	print(f"  fingerprint: {fp[:12]} ({fp})")
	st = read_stamp()
	if st:
		match = "MATCH" if st.get("fingerprint") == fp else "DRIFT (sursa difera de ce s-a aplicat ultima data!)"
		print(f"  deployed:    v{st.get('overlay_version')} @ {st.get('applied_utc')} -> {match}")
	else:
		print("  deployed:    (fara stamp; ruleaza 'apply')")


def cmd_status():
	sys.path.insert(0, MGMT_DIR)
	from geseidl_edition import manifest
	man = manifest.load_manifest()
	print(f"marker: {man['path']} (active={man['active']}, zones={man['zones']})")
	print(f"overlay: v{man.get('overlay_version')}  fingerprint={compute_fingerprint()[:12]}")
	st = read_stamp()
	if st:
		print(f"deployed: v{st.get('overlay_version')} @ {st.get('applied_utc')} "
			f"({'match' if st.get('fingerprint') == compute_fingerprint() else 'DRIFT'})")
	for h in HOOKS:
		path = os.path.join(MGMT_DIR, h["file"])
		try:
			applied = is_applied(h, _read(path))
		except OSError:
			applied = None
		print(f"  [{'OK ' if applied else '-- '}] {h['name']} ({h['file']})")


def cmd_apply():
	for h in HOOKS:
		print(f"{h['name']}: {apply_hook(h)}")
	stamp = write_stamp()
	print(f"stamp: v{stamp['overlay_version']} fp={stamp['fingerprint'][:12]} @ {stamp['applied_utc']}")


def cmd_remove():
	for h in HOOKS:
		print(f"{h['name']}: {remove_hook(h)}")


def cmd_selftest():
	"""Ruleaza engine-ul pe un esantion reprezentativ (fara server)."""
	# adauga management/ in sys.path pt import absolut geseidl_edition
	sys.path.insert(0, MGMT_DIR)
	from geseidl_edition import engine

	class FakeWeb:
		def __init__(self, items):
			self.items = items

	def ok(t):
		return {"type": "ok", "text": t, "extra": []}

	def err(t):
		return {"type": "error", "text": t, "extra": []}

	def head(t):
		return {"type": "heading", "text": t, "extra": []}

	def warn(t):
		return {"type": "warning", "text": t, "extra": []}

	items = [
		head("System"),
		err("A new version of Mail-in-a-Box is available. You are running version geseidl-v75-2204to2404-validated. The latest version is v75."),
		warn("Backups are disabled. It is recommended to enable a backup for your box."),
		head("Network"),
		warn("Mail-in-a-Box is configured to use a public DNS server. This is not supported by spamhaus. Could not determine whether this box's IPv4 address is blacklisted."),
		head("geseidl.ro"),
		warn("Mail-in-a-Box is configured to use a public DNS server. This is not supported by spamhaus. Could not determine whether the domain geseidl.ro is blacklisted."),
		err("The nameservers set on this domain are incorrect. They are currently tim.ns.cloudflare.com; tina.ns.cloudflare.com."),
		err("This domain should resolve to this box's IP address (A 81.196.135.66) ... currently resolves to 104.26.3.65."),
		err("MTA-STS policy is missing: STSFetchResult.NONE"),
	]
	env = {"PRIMARY_HOSTNAME": "mail.geseidl.ro", "PUBLIC_IP": "81.196.135.66"}
	out = FakeWeb(list(items))
	engine.apply_overlay(out, env)
	print("=== DUPA OVERLAY ===")
	for it in out.items:
		sym = {"heading": "##", "ok": "OK", "error": "XX", "warning": "??"}.get(it["type"], "  ")
		print(f"{sym} {it['text']}")
		for e in it.get("extra", []):
			print(f"      | {e['text']}")


def main(argv):
	if sys.platform == "win32":
		try:
			sys.stdout.reconfigure(encoding="utf-8", errors="replace")
			sys.stderr.reconfigure(encoding="utf-8", errors="replace")
		except Exception:
			pass
	cmd = argv[1] if len(argv) > 1 else "status"
	if cmd == "apply":
		cmd_apply()
	elif cmd == "remove":
		cmd_remove()
	elif cmd == "status":
		cmd_status()
	elif cmd == "version":
		cmd_version()
	elif cmd == "selftest":
		cmd_selftest()
	else:
		print(__doc__)
		return 2
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv))
