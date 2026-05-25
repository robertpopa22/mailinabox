"""Read the .geseidl-edition manifest (marker file).

Format minimal, parsat fara dependinta de rtyaml/PyYAML (vezi precedentul
whitelist: evitam venv/rtyaml in cai care pot rula fara venv):

    edition: geseidl
    upstream_base: v75
    zones:
      - status
      - spam
"""

import os


def find_marker(start=None):
	"""Walk up from this file to find the .geseidl-edition marker.

	Returns absolute path to the marker file, or None if not found.
	"""
	d = os.path.abspath(start or os.path.dirname(__file__))
	for _ in range(6):
		candidate = os.path.join(d, ".geseidl-edition")
		if os.path.exists(candidate):
			return candidate
		parent = os.path.dirname(d)
		if parent == d:
			break
		d = parent
	return None


def _strip_comment(line):
	# Drop trailing inline comments (we don't quote '#' anywhere in the manifest).
	i = line.find("#")
	return line if i < 0 else line[:i]


def load_manifest(start=None):
	"""Parse the manifest. Returns a dict with keys: edition, upstream_base, zones, active, path."""
	path = find_marker(start)
	data = {"edition": None, "overlay_version": None, "upstream_base": None,
		"zones": [], "active": False, "path": path}
	if not path:
		return data
	data["active"] = True
	in_zones = False
	try:
		with open(path, encoding="utf-8") as f:
			for raw in f:
				line = _strip_comment(raw.rstrip("\n"))
				if not line.strip():
					continue
				if line.lstrip().startswith("- "):
					if in_zones:
						data["zones"].append(line.lstrip()[2:].strip())
					continue
				if ":" in line and not line.startswith((" ", "\t")):
					key, _, val = line.partition(":")
					key = key.strip()
					val = val.strip()
					in_zones = (key == "zones")
					if key == "zones":
						# zones may be inline ([a, b]) or a block list below
						if val.startswith("[") and val.endswith("]"):
							data["zones"] = [z.strip() for z in val[1:-1].split(",") if z.strip()]
							in_zones = False
					elif key in ("edition", "upstream_base", "overlay_version"):
						data[key] = val
	except OSError:
		pass
	return data


def zone_enabled(zone, start=None):
	return zone in load_manifest(start)["zones"]
