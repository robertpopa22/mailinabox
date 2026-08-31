#!/usr/bin/env python3
"""Consume aggregate DMARC reports and notify only on actionable findings.

The service reads reports from a dedicated local Dovecot mailbox, retains a
small idempotency ledger, archives processed messages, and submits one local
multipart alert per run when DMARC failures or policy/report errors exist.
It never forwards the original aggregate report or message content.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import logging
import re
import sqlite3
import subprocess
import sys
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import format_datetime, formataddr
from io import BytesIO
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

LOGGER = logging.getLogger("geseidl-dmarc-alerts")

DEFAULT_MAILBOX = "gesit-alerte@geseidl.ro"
DEFAULT_NOTIFY = "dit@geseidl.ro"
DEFAULT_SENDER = "gesit-alerte@geseidl.ro"
DEFAULT_STATE_DIR = Path("/var/lib/geseidl-dmarc-alerts")
DEFAULT_ALLOWED_DOMAINS = (
	"asociatiahcd.ro",
	"biamco.ro",
	"conta-ploiesti.ro",
	"energycycling.ro",
	"geseidl.ro",
)
DEFAULT_ALLOWED_SOURCE_IPS = ("81.196.135.66",)

SUBJECT_QUERIES = ("Report domain:", "DMARC Aggregate Report")
MAX_ENCODED_PART_BYTES = 25 * 1024 * 1024
MAX_XML_BYTES = 50 * 1024 * 1024
COMMAND_TIMEOUT_SECONDS = 45
SAFE_DOMAIN = re.compile(r"(?i)^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")


class ReportError(ValueError):
	"""Raised when a message is not a safe, valid aggregate DMARC report."""


@dataclass(frozen=True)
class DmarcRecord:
	source_ip: str
	count: int
	disposition: str
	dkim: str
	spf: str
	header_from: str
	reasons: tuple[str, ...] = ()

	def get_problem_codes(self, allowed_source_ips: set[str]) -> tuple[str, ...]:
		codes: list[str] = []
		if self.dkim.lower() != "pass" and self.spf.lower() != "pass":
			codes.append("dmarc_alignment_failed")
		if self.disposition.lower() in {"quarantine", "reject"}:
			codes.append(f"disposition_{self.disposition.lower()}")
		if self.source_ip not in allowed_source_ips:
			codes.append("unexpected_source_ip")
		return tuple(codes)


@dataclass(frozen=True)
class DmarcReport:
	org_name: str
	report_id: str
	period_begin: int
	period_end: int
	policy_domain: str
	policy: str
	percentage: int
	records: tuple[DmarcRecord, ...]
	errors: tuple[str, ...] = ()

	@property
	def report_key(self) -> str:
		identity = "\0".join(
			(
				self.policy_domain.lower(),
				self.org_name.lower(),
				self.report_id,
				str(self.period_begin),
				str(self.period_end),
			)
		)
		return hashlib.sha256(identity.encode()).hexdigest()

	def get_problem_codes(self, allowed_source_ips: set[str]) -> tuple[str, ...]:
		codes: list[str] = []
		if self.policy.lower() != "reject":
			codes.append(f"observed_policy_{self.policy.lower() or 'missing'}")
		if self.errors:
			codes.append("report_error")
		for record in self.records:
			codes.extend(record.get_problem_codes(allowed_source_ips))
		return tuple(sorted(set(codes)))

	def get_problematic_records(self, allowed_source_ips: set[str]) -> tuple[DmarcRecord, ...]:
		return tuple(record for record in self.records if record.get_problem_codes(allowed_source_ips))

	def get_affected_messages(self, allowed_source_ips: set[str]) -> int:
		return sum(record.count for record in self.get_problematic_records(allowed_source_ips))


@dataclass(frozen=True)
class InboxReport:
	uid: str
	report: DmarcReport


@dataclass
class ScanResult:
	healthy: list[InboxReport] = field(default_factory=list)
	problems: list[InboxReport] = field(default_factory=list)
	duplicates: list[InboxReport] = field(default_factory=list)
	invalid: list[dict[str, str]] = field(default_factory=list)


def _local_name(tag: str) -> str:
	return tag.rsplit("}", 1)[-1]


def _strip_namespaces(root: ET.Element) -> ET.Element:
	for element in root.iter():
		if isinstance(element.tag, str):
			element.tag = _local_name(element.tag)
	return root


def _text(parent: ET.Element, path: str, default: str = "") -> str:
	element = parent.find(path)
	if element is None or element.text is None:
		return default
	return element.text.strip()


def _bounded_gzip(payload: bytes) -> bytes:
	with gzip.GzipFile(fileobj=BytesIO(payload)) as stream:
		data = stream.read(MAX_XML_BYTES + 1)
	if len(data) > MAX_XML_BYTES:
		raise ReportError("gzip payload exceeds the XML size limit")
	return data


def _bounded_zip(payload: bytes) -> list[bytes]:
	result: list[bytes] = []
	with zipfile.ZipFile(BytesIO(payload)) as archive:
		for info in archive.infolist():
			if info.is_dir() or not info.filename.lower().endswith(".xml"):
				continue
			if info.file_size > MAX_XML_BYTES:
				raise ReportError("zip member exceeds the XML size limit")
			with archive.open(info) as stream:
				data = stream.read(MAX_XML_BYTES + 1)
			if len(data) > MAX_XML_BYTES:
				raise ReportError("zip member exceeds the XML size limit")
			result.append(data)
	return result


def extract_xml_payloads(message: Message) -> list[bytes]:
	payloads: list[bytes] = []
	for part in message.walk():
		if part.is_multipart():
			continue
		payload = part.get_payload(decode=True) or b""
		if len(payload) > MAX_ENCODED_PART_BYTES:
			raise ReportError("MIME part exceeds the encoded size limit")
		content_type = part.get_content_type().lower()
		filename = (part.get_filename() or "").lower()
		try:
			if content_type in {"application/zip", "application/x-zip-compressed"} or filename.endswith(".zip"):
				payloads.extend(_bounded_zip(payload))
			elif content_type in {"application/gzip", "application/x-gzip"} or filename.endswith(".gz"):
				payloads.append(_bounded_gzip(payload))
			elif content_type in {"application/xml", "text/xml"} or filename.endswith(".xml"):
				payloads.append(payload)
		except (gzip.BadGzipFile, OSError, zipfile.BadZipFile) as exc:
			raise ReportError(f"compressed attachment is invalid: {type(exc).__name__}") from exc
	return payloads


def parse_report_xml(xml_payload: bytes) -> DmarcReport:
	if len(xml_payload) > MAX_XML_BYTES:
		raise ReportError("XML exceeds the size limit")
	lowered = xml_payload[:4096].lower()
	if b"<!doctype" in lowered or b"<!entity" in lowered:
		raise ReportError("DTD/entity declarations are not permitted")
	try:
		root = _strip_namespaces(ET.fromstring(xml_payload))
	except ET.ParseError as exc:
		raise ReportError("invalid XML") from exc
	if root.tag != "feedback":
		raise ReportError("XML root is not DMARC feedback")

	metadata = root.find("report_metadata")
	policy_published = root.find("policy_published")
	if metadata is None or policy_published is None:
		raise ReportError("required DMARC report sections are missing")

	domain = _text(policy_published, "domain").lower().rstrip(".")
	if not domain or not SAFE_DOMAIN.fullmatch(domain):
		raise ReportError("invalid policy domain")

	records: list[DmarcRecord] = []
	for record in root.findall("record"):
		try:
			count = int(_text(record, "row/count", "0"))
		except ValueError as exc:
			raise ReportError("record count is not an integer") from exc
		if count < 0:
			raise ReportError("record count is negative")
		reasons = tuple(
			filter(
				None,
				(
					": ".join(filter(None, (_text(reason, "type"), _text(reason, "comment"))))
					for reason in record.findall("row/policy_evaluated/reason")
				),
			)
		)
		records.append(
			DmarcRecord(
				source_ip=_text(record, "row/source_ip"),
				count=count,
				disposition=_text(record, "row/policy_evaluated/disposition", "none"),
				dkim=_text(record, "row/policy_evaluated/dkim", "unknown"),
				spf=_text(record, "row/policy_evaluated/spf", "unknown"),
				header_from=_text(record, "identifiers/header_from"),
				reasons=reasons,
			)
		)

	try:
		period_begin = int(_text(metadata, "date_range/begin", "0"))
		period_end = int(_text(metadata, "date_range/end", "0"))
		percentage = int(_text(policy_published, "pct", "100"))
	except ValueError as exc:
		raise ReportError("report period or percentage is not an integer") from exc

	errors = tuple(
		text
		for element in root.iter("error")
		if (text := " ".join("".join(element.itertext()).split()))
	)
	return DmarcReport(
		org_name=_text(metadata, "org_name", "unknown"),
		report_id=_text(metadata, "report_id"),
		period_begin=period_begin,
		period_end=period_end,
		policy_domain=domain,
		policy=_text(policy_published, "p", "missing"),
		percentage=percentage,
		records=tuple(records),
		errors=errors,
	)


def parse_message(raw_message: bytes, allowed_domains: set[str]) -> DmarcReport:
	message = BytesParser(policy=policy.default).parsebytes(raw_message)
	payloads = extract_xml_payloads(message)
	if not payloads:
		raise ReportError("no XML aggregate report attachment found")
	reports = [parse_report_xml(payload) for payload in payloads]
	if len(reports) != 1:
		raise ReportError("expected exactly one aggregate report per message")
	report = reports[0]
	if report.policy_domain not in allowed_domains:
		raise ReportError("report domain is outside the configured allowlist")
	return report


def run_command(arguments: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
	return subprocess.run(
		arguments,
		input=input_bytes,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		check=True,
		timeout=COMMAND_TIMEOUT_SECONDS,
	)


def search_report_uids(mailbox: str) -> list[str]:
	uids: set[str] = set()
	for subject in SUBJECT_QUERIES:
		result = run_command(["doveadm", "search", "-u", mailbox, "mailbox", "INBOX", "HEADER", "Subject", subject])
		for line in result.stdout.decode("utf-8", "replace").splitlines():
			candidate = line.rsplit(maxsplit=1)[-1]
			if candidate.isdigit():
				uids.add(candidate)
	return sorted(uids, key=int)


def fetch_message(mailbox: str, uid: str) -> bytes:
	result = run_command(["doveadm", "fetch", "-u", mailbox, "text", "mailbox", "INBOX", "uid", uid])
	raw = result.stdout
	if raw.startswith(b"text: "):
		raw = raw[6:]
	return raw.rstrip(b"\r\n\f")


def move_message(mailbox: str, uid: str, destination: str) -> None:
	run_command(["doveadm", "move", "-u", mailbox, destination, "mailbox", "INBOX", "uid", uid])


def open_state(state_dir: Path) -> sqlite3.Connection:
	state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
	state_dir.chmod(0o700)
	connection = sqlite3.connect(state_dir / "state.sqlite")
	connection.execute(
		"""
		CREATE TABLE IF NOT EXISTS processed_reports (
			report_key TEXT PRIMARY KEY,
			report_id TEXT NOT NULL,
			policy_domain TEXT NOT NULL,
			org_name TEXT NOT NULL,
			period_begin INTEGER NOT NULL,
			period_end INTEGER NOT NULL,
			result TEXT NOT NULL CHECK(result IN ('healthy', 'alerted')),
			completed_utc TEXT NOT NULL
		)
		"""
	)
	return connection


def was_processed(connection: sqlite3.Connection, report_key: str) -> bool:
	return connection.execute("SELECT 1 FROM processed_reports WHERE report_key = ?", (report_key,)).fetchone() is not None


def mark_processed(connection: sqlite3.Connection, report: DmarcReport, result: str) -> None:
	connection.execute(
		"""
		INSERT OR IGNORE INTO processed_reports
		(report_key, report_id, policy_domain, org_name, period_begin, period_end, result, completed_utc)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)
		""",
		(
			report.report_key,
			report.report_id,
			report.policy_domain,
			report.org_name,
			report.period_begin,
			report.period_end,
			result,
			datetime.now(UTC).isoformat(),
		),
	)
	connection.commit()


def _format_epoch(value: int) -> str:
	if not value:
		return "necunoscut"
	return datetime.fromtimestamp(value, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def build_alert_message(reports: Iterable[DmarcReport], sender: str, notify: str, allowed_source_ips: set[str]) -> EmailMessage:
	reports = tuple(reports)
	domains = sorted({report.policy_domain for report in reports})
	affected = sum(report.get_affected_messages(allowed_source_ips) for report in reports)
	digest = hashlib.sha256("\n".join(sorted(report.report_key for report in reports)).encode()).hexdigest()[:24]

	plain_lines = [
		"Au fost detectate probleme în rapoartele agregate DMARC.",
		"",
		f"Domenii: {', '.join(domains)}",
		f"Mesaje afectate: {affected}",
		"",
	]
	rows: list[str] = []
	for report in reports:
		problem_codes = report.get_problem_codes(allowed_source_ips)
		plain_lines.append(
			f"- {report.policy_domain} / {report.org_name} / {report.report_id}: "
			f"{', '.join(problem_codes)}; interval {_format_epoch(report.period_begin)} — {_format_epoch(report.period_end)}"
		)
		if report.errors:
			plain_lines.append(f"  Erori raport: {'; '.join(report.errors)}")
		for record in report.get_problematic_records(allowed_source_ips):
			plain_lines.append(
				f"  IP {record.source_ip or 'necunoscut'}: count={record.count}, "
				f"disposition={record.disposition}, DKIM={record.dkim}, SPF={record.spf}, From={record.header_from or 'necunoscut'}"
			)
		rows.append(
			"<tr>"
			f"<td>{html.escape(report.policy_domain)}</td>"
			f"<td>{html.escape(report.org_name)}</td>"
			f"<td>{html.escape(report.report_id)}</td>"
			f"<td>{html.escape(', '.join(problem_codes))}</td>"
			f"<td>{report.get_affected_messages(allowed_source_ips)}</td>"
			"</tr>"
		)

	plain_lines.extend(
		(
			"",
			"Acesta este un rezumat automat. Rapoartele XML originale rămân în mailboxul tehnic gesit-alerte@geseidl.ro.",
		)
	)
	html_body = f"""<!doctype html>
<html lang="ro"><body style="margin:0;background:#f4f7f5;font-family:Arial,sans-serif;color:#1f2933">
<div style="max-width:760px;margin:24px auto;background:#fff;border:1px solid #d8e2dc;border-radius:10px;overflow:hidden">
<div style="padding:20px 24px;background:#174f3a;color:#fff"><h1 style="margin:0;font-size:20px">Alertă DMARC</h1></div>
<div style="padding:24px"><p style="margin-top:0">Au fost detectate rezultate DMARC care necesită verificare.</p>
<p><strong>Domenii:</strong> {html.escape(', '.join(domains))}<br><strong>Mesaje afectate:</strong> {affected}</p>
<table style="width:100%;border-collapse:collapse;font-size:13px">
<thead><tr style="background:#eef5f1"><th style="padding:8px;text-align:left">Domeniu</th><th style="padding:8px;text-align:left">Raportor</th><th style="padding:8px;text-align:left">Report-ID</th><th style="padding:8px;text-align:left">Problemă</th><th style="padding:8px;text-align:right">Mesaje</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p style="margin-bottom:0;margin-top:20px;color:#52606d;font-size:12px">Rezumat automat; conținutul mesajelor nu este inclus. XML-urile originale rămân în mailboxul tehnic.</p>
</div></div></body></html>"""

	message = EmailMessage(policy=policy.SMTP)
	message["From"] = formataddr(("Geseidl DMARC Monitor", sender))
	message["To"] = notify
	message["Subject"] = f"[ALERTĂ DMARC] {affected} mesaje afectate — {', '.join(domains)}"
	message["Date"] = format_datetime(datetime.now(UTC))
	message["Message-ID"] = f"<dmarc-alert-{digest}@geseidl.ro>"
	message["Auto-Submitted"] = "auto-generated"
	message["X-Geseidl-Status"] = "WARNING"
	message["X-Geseidl-Alert-Key"] = digest
	message.set_content("\n".join(plain_lines))
	message.add_alternative(html_body, subtype="html")
	return message


def submit_alert(message: EmailMessage) -> None:
	run_command(["/usr/sbin/sendmail", "-t", "-oi"], input_bytes=message.as_bytes())


def scan_mailbox(
	mailbox: str,
	allowed_domains: set[str],
	connection: sqlite3.Connection,
	max_messages: int,
	allowed_source_ips: set[str],
) -> ScanResult:
	result = ScanResult()
	for uid in search_report_uids(mailbox)[:max_messages]:
		try:
			report = parse_message(fetch_message(mailbox, uid), allowed_domains)
		except (ReportError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
			result.invalid.append({"uid": uid, "error": str(exc)})
			continue
		item = InboxReport(uid=uid, report=report)
		if was_processed(connection, report.report_key):
			result.duplicates.append(item)
		elif report.get_problem_codes(allowed_source_ips):
			result.problems.append(item)
		else:
			result.healthy.append(item)
	return result


def process_scan(
	scan: ScanResult,
	mailbox: str,
	connection: sqlite3.Connection,
	sender: str,
	notify: str,
	allowed_source_ips: set[str],
	dry_run: bool,
) -> dict[str, object]:
	summary: dict[str, object] = {
		"healthy": len(scan.healthy),
		"problems": len(scan.problems),
		"duplicates": len(scan.duplicates),
		"invalid": scan.invalid,
		"alert_sent": False,
		"dry_run": dry_run,
	}
	if dry_run:
		summary["problem_reports"] = [
			{**asdict(item.report), "problem_codes": item.report.get_problem_codes(allowed_source_ips)} for item in scan.problems
		]
		return summary

	for item in (*scan.duplicates, *scan.healthy):
		if item in scan.healthy:
			mark_processed(connection, item.report, "healthy")
		move_message(mailbox, item.uid, "Archive")

	for item in scan.invalid:
		move_message(mailbox, item["uid"], "Invalid")

	if scan.problems:
		message = build_alert_message((item.report for item in scan.problems), sender, notify, allowed_source_ips)
		submit_alert(message)
		for item in scan.problems:
			mark_processed(connection, item.report, "alerted")
			move_message(mailbox, item.uid, "Archive")
		summary["alert_sent"] = True
	return summary


def _sample_xml(*, dkim: str, spf: str, disposition: str = "none", domain: str = "geseidl.ro") -> bytes:
	return f"""<?xml version="1.0"?>
<feedback>
<report_metadata><org_name>self-test</org_name><report_id>self-test-{dkim}-{spf}-{disposition}</report_id><date_range><begin>1788048000</begin><end>1788134399</end></date_range></report_metadata>
<policy_published><domain>{domain}</domain><p>reject</p><pct>100</pct></policy_published>
<record><row><source_ip>192.0.2.10</source_ip><count>2</count><policy_evaluated><disposition>{disposition}</disposition><dkim>{dkim}</dkim><spf>{spf}</spf></policy_evaluated></row><identifiers><header_from>{domain}</header_from></identifiers></record>
</feedback>""".encode()


def self_test() -> dict[str, object]:
	healthy = parse_report_xml(_sample_xml(dkim="pass", spf="pass"))
	problem = parse_report_xml(_sample_xml(dkim="fail", spf="fail", disposition="reject"))
	allowed_source_ips = {"192.0.2.10"}
	if healthy.get_problem_codes(allowed_source_ips):
		raise RuntimeError("healthy self-test report was classified as a problem")
	if "dmarc_alignment_failed" not in problem.get_problem_codes(allowed_source_ips):
		raise RuntimeError("failed self-test report was not detected")
	return {
		"ok": True,
		"healthy_codes": healthy.get_problem_codes(allowed_source_ips),
		"problem_codes": problem.get_problem_codes(allowed_source_ips),
	}


def parse_args(argv: list[str]) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--mailbox", default=DEFAULT_MAILBOX)
	parser.add_argument("--notify", default=DEFAULT_NOTIFY)
	parser.add_argument("--sender", default=DEFAULT_SENDER)
	parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
	parser.add_argument("--allowed-domain", action="append", dest="allowed_domains")
	parser.add_argument("--allowed-source-ip", action="append", dest="allowed_source_ips")
	parser.add_argument("--max-messages", type=int, default=250)
	parser.add_argument("--dry-run", action="store_true")
	parser.add_argument("--self-test", action="store_true")
	parser.add_argument("--inspect-file", type=Path)
	return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
	args = parse_args(argv or sys.argv[1:])
	logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
	allowed_domains = {domain.lower().rstrip(".") for domain in (args.allowed_domains or DEFAULT_ALLOWED_DOMAINS)}
	allowed_source_ips = set(args.allowed_source_ips or DEFAULT_ALLOWED_SOURCE_IPS)
	if args.self_test:
		print(json.dumps(self_test(), sort_keys=True))
		return 0
	if args.inspect_file:
		report = parse_message(args.inspect_file.read_bytes(), allowed_domains)
		print(json.dumps(asdict(report), indent=2, sort_keys=True))
		return 0
	if args.max_messages < 1:
		raise SystemExit("--max-messages must be positive")

	connection = open_state(args.state_dir)
	try:
		scan = scan_mailbox(args.mailbox, allowed_domains, connection, args.max_messages, allowed_source_ips)
		summary = process_scan(scan, args.mailbox, connection, args.sender, args.notify, allowed_source_ips, args.dry_run)
	finally:
		connection.close()
	print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
