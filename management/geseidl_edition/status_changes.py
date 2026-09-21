"""Semantic comparison keys for daily Mail-in-a-Box status notifications."""

import ipaddress
import json
import re


_CLOUDFLARE_HOSTING = re.compile(
	r"^(?P<prefix>gazduit la )(?P<ips>[0-9a-fA-F:., ]+)(?P<suffix> / cloudflare)$"
)


def _sorted_ip_set(text):
	match = _CLOUDFLARE_HOSTING.match(text)
	if not match:
		return text
	values = [value.strip() for value in match.group("ips").split(",")]
	try:
		values = sorted({str(ipaddress.ip_address(value)) for value in values})
	except ValueError:
		return text
	return match.group("prefix") + ", ".join(values) + match.group("suffix")


def semantic_line_key(line):
	"""Return a stable key while preserving warning/error detail changes."""
	line_type, line_args, line_kwargs = line
	if line_type == "print_ok":
		# A healthy check remains healthy when its wording, translated label,
		# counters, or exact free-space value changes. A degradation changes the
		# method to print_warning/print_error and is therefore still reported.
		return json.dumps([line_type, ["healthy"], {}], sort_keys=True)
	if line_type == "print_line" and line_args:
		args = list(line_args)
		args[0] = _sorted_ip_set(args[0])
		return json.dumps([line_type, args, line_kwargs], sort_keys=True)
	return json.dumps(line, sort_keys=True)
