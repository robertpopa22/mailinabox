"""Semantic comparison keys for daily Mail-in-a-Box status notifications."""

import ipaddress
import json
import re
from difflib import SequenceMatcher


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


def probe_outbound_smtp(shell):
	"""Capture nc diagnostics; only the structured status reaches the report."""
	code, _diagnostics = shell("check_output", ["/bin/nc", "-z", "-w5", "aspmx.l.google.com", "25"],
		capture_stderr=True, trap=True)
	return code, code


def parse_apt_updates(text):
	"""Count actual Inst records, including packages without a prior version."""
	packages = []
	for line in text.splitlines():
		if not line.startswith("Inst "):
			continue
		match = re.match(r"^Inst (\S+)(?: \[([^]]*)\])? \((\S+)", line)
		if not match:
			raise ValueError("Unrecognized APT installation record")
		packages.append({"package": match[1], "current_version": match[2] or "", "version": match[3]})
	return packages


def pending_apt_updates(shell):
	# Include new dependencies (e.g. kernel packages) without permitting removals.
	text = shell("check_output", ["/usr/bin/apt-get", "-qq", "-s", "--with-new-pkgs", "upgrade"])
	return parse_apt_updates(text)


def held_apt_updates(shell):
	held = shell("check_output", ["/usr/bin/apt-mark", "showhold"]).split()
	if not held:
		return []
	policy = shell("check_output", ["/usr/bin/apt-cache", "policy", *held])
	versions, package = {}, None
	for line in policy.splitlines():
		if re.match(r"^\S+:$", line):
			package = line[:-1]
			versions[package] = {}
		else:
			match = re.match(r"^\s+(Installed|Candidate):\s+(\S+)$", line)
			if package and match:
				versions[package][match[1]] = match[2]
	result = []
	for package in held:
		values = versions.get(package, {})
		if set(values) != {"Installed", "Candidate"}:
			raise ValueError("Held package candidate could not be determined")
		if values["Candidate"] == "(none)":
			continue
		code, _ = shell("check_call", ["/usr/bin/dpkg", "--compare-versions",
			values["Candidate"], "gt", values["Installed"]], trap=True, capture_stderr=True)
		if code == 0:
			result.append({"package": package, "current_version": values["Installed"], "version": values["Candidate"]})
	return result


def report_software_updates(packages, reboot_needed, output, shell):
	"""Keep installable, held and reboot states explicit and separate."""
	try:
		held = held_apt_updates(shell)
	except Exception:
		held = None
		output.print_warning("Could not determine updates held by administrator policy.")
	if reboot_needed:
		output.print_error("System updates have been installed and a reboot of the machine is required.")
	if packages:
		count = len(packages)
		output.print_error("There is 1 software package that can be updated." if count == 1 else
			"There are %d software packages that can be updated." % count)
		for package in packages:
			output.print_line("{} ({} -> {})".format(package["package"],
				package["current_version"] or "not installed", package["version"]))
	elif not reboot_needed and held == []:
		output.print_ok("System software is up to date.")
	if held:
		count = len(held)
		output.print_warning("1 package update is held by administrator policy." if count == 1 else
			"%d package updates are held by administrator policy." % count)
		for package in held:
			output.print_line("{} ({} -> {}; held)".format(package["package"],
				package["current_version"], package["version"]))


def render_category_changes(category, previous, current, output):
	"""Emit at most one previous/current block per category, with all changes."""
	if previous is None:
		output.add_heading(category + " -- Added")
		for method, args, kwargs in current:
			getattr(output, method)(*args, **kwargs)
		return
	matcher = SequenceMatcher(None, [semantic_line_key(line) for line in previous],
		[semantic_line_key(line) for line in current], autojunk=False)
	old_changes, new_changes = [], []
	for operation, i1, i2, j1, j2 in matcher.get_opcodes():
		if operation == "equal":
			continue
		old_changes.extend(previous[i1:i2])
		new_changes.extend(current[j1:j2])
	for label, lines in [("Previously (changed items):", old_changes),
		("Currently (changed items):", new_changes)]:
		if lines:
			output.add_heading(category + " -- " + label)
			for method, args, kwargs in lines:
				getattr(output, method)(*args, **kwargs)
