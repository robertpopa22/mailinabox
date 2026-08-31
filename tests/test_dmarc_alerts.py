import importlib.util
import sys
import unittest
import zipfile
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "setup" / "geseidl_edition" / "zones" / "mail" / "dmarc_alerts.py"
SPEC = importlib.util.spec_from_file_location("dmarc_alerts", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class DmarcAlertsTest(unittest.TestCase):
	def test_healthy_report_has_no_problem(self):
		report = MODULE.parse_report_xml(MODULE._sample_xml(dkim="pass", spf="pass"))
		self.assertEqual(report.get_problem_codes({"192.0.2.10"}), ())
		self.assertEqual(report.get_affected_messages({"192.0.2.10"}), 0)

	def test_alignment_failure_and_disposition_are_actionable(self):
		report = MODULE.parse_report_xml(MODULE._sample_xml(dkim="fail", spf="fail", disposition="reject"))
		codes = report.get_problem_codes({"192.0.2.10"})
		self.assertIn("dmarc_alignment_failed", codes)
		self.assertIn("disposition_reject", codes)
		self.assertEqual(report.get_affected_messages({"192.0.2.10"}), 2)

	def test_one_aligned_mechanism_is_not_failure(self):
		report = MODULE.parse_report_xml(MODULE._sample_xml(dkim="fail", spf="pass"))
		self.assertEqual(report.get_problem_codes({"192.0.2.10"}), ())

	def test_unexpected_source_ip_is_actionable_even_when_dmarc_passes(self):
		report = MODULE.parse_report_xml(MODULE._sample_xml(dkim="pass", spf="pass"))
		self.assertEqual(report.get_problem_codes({"81.196.135.66"}), ("unexpected_source_ip",))

	def test_retransmitted_report_is_archived_without_another_alert(self):
		report = MODULE.parse_report_xml(MODULE._sample_xml(dkim="fail", spf="fail", disposition="reject"))
		with TemporaryDirectory() as state_dir:
			connection = MODULE.open_state(Path(state_dir))
			try:
				MODULE.mark_processed(connection, report, "alerted")
				scan = MODULE.ScanResult(duplicates=[MODULE.InboxReport(uid="42", report=report)])
				with patch.object(MODULE, "submit_alert") as submit, patch.object(MODULE, "move_message") as move:
					summary = MODULE.process_scan(
						scan,
						"gesit-alerte@geseidl.ro",
						connection,
						"gesit-alerte@geseidl.ro",
						"dit@geseidl.ro",
						{"192.0.2.10"},
						False,
					)
			finally:
				connection.close()
		self.assertFalse(summary["alert_sent"])
		submit.assert_not_called()
		move.assert_called_once_with("gesit-alerte@geseidl.ro", "42", "Archive")

	def test_namespace_and_zip_message_are_supported(self):
		xml = MODULE._sample_xml(dkim="pass", spf="pass").replace(b"<feedback>", b'<feedback xmlns="urn:ietf:params:xml:ns:dmarc-2.0">')
		buffer = BytesIO()
		with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
			archive.writestr("report.xml", xml)
		message = EmailMessage()
		message["Subject"] = "Report domain: geseidl.ro"
		message.set_content("aggregate report")
		message.add_attachment(buffer.getvalue(), maintype="application", subtype="zip", filename="report.zip")
		report = MODULE.parse_message(message.as_bytes(), {"geseidl.ro"})
		self.assertEqual(report.policy_domain, "geseidl.ro")

	def test_doctype_is_rejected(self):
		xml = MODULE._sample_xml(dkim="pass", spf="pass").replace(b"<feedback>", b"<!DOCTYPE feedback><feedback>")
		with self.assertRaises(MODULE.ReportError):
			MODULE.parse_report_xml(xml)

	def test_domain_allowlist_is_enforced(self):
		xml = MODULE._sample_xml(dkim="pass", spf="pass", domain="outside.example")
		message = EmailMessage()
		message.add_attachment(xml, maintype="application", subtype="xml", filename="report.xml")
		with self.assertRaises(MODULE.ReportError):
			MODULE.parse_message(message.as_bytes(), {"geseidl.ro"})

	def test_alert_is_multipart_and_metadata_only(self):
		report = MODULE.parse_report_xml(MODULE._sample_xml(dkim="fail", spf="fail", disposition="reject"))
		message = MODULE.build_alert_message([report], "gesit-alerte@geseidl.ro", "dit@geseidl.ro", {"192.0.2.10"})
		self.assertTrue(message.is_multipart())
		self.assertEqual(message["To"], "dit@geseidl.ro")
		self.assertEqual(message["X-Geseidl-Status"], "WARNING")
		self.assertIn("dmarc_alignment_failed", message.get_body(preferencelist=("plain",)).get_content())
		self.assertNotIn("http://", message.get_body(preferencelist=("html",)).get_content())
		self.assertNotIn("https://", message.get_body(preferencelist=("html",)).get_content())


if __name__ == "__main__":
	unittest.main()
