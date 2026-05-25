"""Overlay engine: normalizeaza rezultatele check-urilor si ruleaza procesoarele de zona.

Doua surse de rezultate upstream:
  - WebOutput.items  (daemon /system/status): list[dict{type,text,extra}]
  - BufferedOutput.buf (raport email zilnic / consola): list[tuple(attr,args,kwargs)]

Le aducem la o reprezentare comuna (records), aplicam zonele active din manifest,
apoi serializam inapoi in formatul sursei.
"""

from . import manifest as _manifest


# ---- normalizare ----------------------------------------------------------

def _from_web(items):
	records, section = [], None
	for it in items:
		if it.get("type") == "heading":
			section = it.get("text")
		records.append({
			"kind": it.get("type"),
			"text": it.get("text", ""),
			"extra": list(it.get("extra", [])),
			"section": section,
		})
	return records


def _to_web(records):
	return [{"type": r["kind"], "text": r["text"], "extra": r.get("extra", [])} for r in records]


def _from_buffer(buf):
	records, section = [], None
	for entry in buf:
		attr, args, kwargs = entry
		msg = args[0] if args else ""
		if attr == "add_heading":
			section = msg
			records.append({"kind": "heading", "text": msg, "extra": [], "section": section})
		elif attr in ("print_ok", "print_error", "print_warning"):
			kind = {"print_ok": "ok", "print_error": "error", "print_warning": "warning"}[attr]
			records.append({"kind": kind, "text": msg, "extra": [], "section": section})
		elif attr in ("print_line", "print_block"):
			mono = bool(kwargs.get("monospace", False))
			if records:
				records[-1]["extra"].append({"text": msg, "monospace": mono})
			else:
				records.append({"kind": "line", "text": msg, "extra": [], "section": section})
	return records


def _to_buffer(records):
	buf = []
	for r in records:
		if r["kind"] == "heading":
			buf.append(("add_heading", (r["text"],), {}))
		elif r["kind"] in ("ok", "error", "warning"):
			attr = {"ok": "print_ok", "error": "print_error", "warning": "print_warning"}[r["kind"]]
			buf.append((attr, (r["text"],), {}))
			for e in r.get("extra", []):
				buf.append(("print_line", (e["text"],), {"monospace": e.get("monospace", False)}))
		elif r["kind"] == "line":
			buf.append(("print_line", (r["text"],), {}))
	return buf


# ---- grupare pe sectiuni --------------------------------------------------

def group_sections(records):
	"""[{name, head, items:[record,...]}] in ordinea aparitiei."""
	sections, current = [], None
	for r in records:
		if r["kind"] == "heading":
			current = {"name": r["text"], "head": r, "items": []}
			sections.append(current)
		elif current is None:
			current = {"name": None, "head": None, "items": [r]}
			sections.append(current)
		else:
			current["items"].append(r)
	return sections


def flatten_sections(sections):
	out = []
	for s in sections:
		if s["head"] is not None:
			out.append(s["head"])
		out.extend(s["items"])
	return out


# ---- helpers pentru zone --------------------------------------------------

def mk(kind, text, extra=None):
	return {"kind": kind, "text": text, "extra": extra or [], "section": None}


# ---- pipeline -------------------------------------------------------------

def _processors():
	# import tarziu ca sa evitam ciclu la import
	from .zones import REGISTRY
	return REGISTRY


def process(records, env, pool=None):
	man = _manifest.load_manifest()
	if not man["active"]:
		return records
	sections = group_sections(records)
	registry = _processors()
	for zone in man["zones"]:
		fn = registry.get(zone)
		if fn is None:
			continue
		try:
			fn(sections, env, pool, man)
		except Exception as e:  # o zona nu trebuie sa darame restul
			sections.append({
				"name": None, "head": None,
				"items": [mk("warning", f"Geseidl overlay: zona '{zone}' a esuat: {e}")],
			})
	return flatten_sections(sections)


def apply_overlay(output, env, pool=None):
	"""Pentru WebOutput (are .items list[dict]). Muteaza output.items in loc."""
	records = _from_web(output.items)
	records = process(records, env, pool)
	output.items = _to_web(records)
	return output


def apply_overlay_buffer(buf, env, pool=None):
	"""Pentru BufferedOutput.buf (list[tuple]). Muteaza lista in loc."""
	records = _from_buffer(buf)
	records = process(records, env, pool)
	buf[:] = _to_buffer(records)
	return buf
