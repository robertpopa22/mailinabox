import importlib.util
import sys
import unittest
import zipfile
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from dataclasses import replace
from datetime import UTC, datetime, timedelta


MODULE_PATH = Path(__file__).parents[1] / "setup" / "geseidl_edition" / "zones" / "mail" / "dmarc_alerts.py"
SPEC = importlib.util.spec_from_file_location("dmarc_alerts", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class DmarcAlertsTest(unittest.TestCase):
	def process(self, connection, report=None, now=None, dry_run=False):
		scan = MODULE.ScanResult(problems=[MODULE.InboxReport(uid='42', report=report)] if report else [])
		return MODULE.process_scan(scan, 'dmarc-reports@example.com', connection,
			'dmarc-reports@example.com', 'postmaster@example.com', {'192.0.2.99'}, dry_run,
			now=now or datetime(2026, 1, 1, 17, tzinfo=UTC))

	def test_source_only_alignment_pass_queues_persistently_and_archives_original(self):
		report = MODULE.parse_report_xml(MODULE._sample_xml(dkim='pass', spf='fail'))
		with TemporaryDirectory() as state_dir:
			connection = MODULE.open_state(Path(state_dir))
			with patch.object(MODULE, 'submit_alert') as submit, patch.object(MODULE, 'move_message') as move:
				result = self.process(connection, report)
				self.assertEqual(result['digest_queued'], 1)
				self.assertFalse(result['alert_sent'])
				submit.assert_not_called()
				move.assert_called_once_with('dmarc-reports@example.com', '42', 'Archive')
			connection.close()
			connection = MODULE.open_state(Path(state_dir))
			self.assertTrue(MODULE.was_processed(connection, report.report_key))
			with patch.object(MODULE, 'submit_alert') as submit, patch.object(MODULE, 'move_message'):
				self.process(connection, now=datetime(2026, 1, 2, 7, 59, tzinfo=UTC))
				submit.assert_not_called()
				result = self.process(connection, now=datetime(2026, 1, 2, 8, 1, tzinfo=UTC))
				self.assertTrue(result['digest_sent'])
				self.assertIn('DMARC digest', submit.call_args.args[0]['Subject'])
				self.process(connection, now=datetime(2026, 1, 2, 8, 16, tzinfo=UTC))
				submit.assert_called_once()
			connection.close()

	def test_policy_errors_and_real_authentication_failures_stay_immediate(self):
		base = MODULE.parse_report_xml(MODULE._sample_xml(dkim='pass', spf='fail'))
		variants = [replace(base, policy='none'), replace(base, percentage=50), replace(base, errors=('report error',)),
			replace(base, records=(replace(base.records[0], dkim='fail', spf='fail'),)),
			replace(base, records=(replace(base.records[0], disposition='quarantine'),))]
		for report in variants:
			with self.subTest(report=report), TemporaryDirectory() as state_dir:
				connection = MODULE.open_state(Path(state_dir))
				with patch.object(MODULE, 'submit_alert') as submit, patch.object(MODULE, 'move_message'):
					result = self.process(connection, report)
					self.assertTrue(result['alert_sent'])
					self.assertEqual(result['digest_queued'], 0)
					submit.assert_called_once()
				connection.close()

	def test_mixed_report_and_unknown_disposition_cannot_enter_digest(self):
		base = MODULE.parse_report_xml(MODULE._sample_xml(dkim='pass', spf='fail'))
		mixed = replace(base, records=base.records + (replace(base.records[0], dkim='fail', spf='fail'),))
		self.assertFalse(MODULE.digest_only(mixed, {'192.0.2.99'}))
		unknown = replace(base, records=(replace(base.records[0], disposition='unknown'),))
		self.assertFalse(MODULE.digest_only(unknown, {'192.0.2.99'}))
		spf_only = replace(base, records=(replace(base.records[0], dkim='fail', spf='pass'),))
		self.assertTrue(MODULE.digest_only(spf_only, {'192.0.2.99'}))

	def test_unconfirmed_submission_is_durable_and_never_replayed(self):
		report = MODULE.parse_report_xml(MODULE._sample_xml(dkim='fail', spf='fail', disposition='reject'))
		with TemporaryDirectory() as state_dir:
			connection = MODULE.open_state(Path(state_dir))
			with patch.object(MODULE, 'submit_alert', side_effect=TimeoutError) as submit, patch.object(MODULE, 'move_message'):
				result = self.process(connection, report)
				self.assertEqual(result['uncertain_outbox'], 1)
				self.assertFalse(result['alert_sent'])
				self.process(connection, report)
				submit.assert_called_once()
			self.assertTrue(MODULE.was_processed(connection, report.report_key))
			self.assertEqual(connection.execute('SELECT status FROM notification_outbox').fetchone()[0], 'uncertain')
			connection.close()

	def test_crash_after_reservation_cannot_replay_and_duplicate_rows_are_deduplicated(self):
		report = MODULE.parse_report_xml(MODULE._sample_xml(dkim='fail', spf='fail', disposition='reject'))
		now = datetime(2026, 1, 1, 17, tzinfo=UTC)
		with TemporaryDirectory() as state_dir:
			connection = MODULE.open_state(Path(state_dir))
			with patch.object(MODULE, 'submit_alert', side_effect=KeyboardInterrupt):
				with self.assertRaises(KeyboardInterrupt):
					MODULE.send_once(connection, [report, report], 'sender@example.com', 'postmaster@example.com', set(), now)
			connection.close()
			connection = MODULE.open_state(Path(state_dir))
			with patch.object(MODULE, 'submit_alert') as submit:
				self.assertFalse(MODULE.send_once(connection, [report], 'sender@example.com', 'postmaster@example.com', set(), now))
				submit.assert_not_called()
			self.assertEqual(connection.execute('SELECT count(*) FROM outbox_reports').fetchone()[0], 1)
			connection.close()

	def test_digest_has_one_batch_per_day_and_dry_run_does_not_enqueue(self):
		base = MODULE.parse_report_xml(MODULE._sample_xml(dkim='pass', spf='fail'))
		now = datetime(2026, 1, 2, 8, 1, tzinfo=UTC)
		with TemporaryDirectory() as state_dir:
			connection = MODULE.open_state(Path(state_dir))
			with patch.object(MODULE, 'submit_alert') as submit, patch.object(MODULE, 'move_message') as move:
				self.process(connection, base, now=now, dry_run=True)
				self.assertEqual(connection.execute('SELECT count(*) FROM digest_reports').fetchone()[0], 0)
				move.assert_not_called()
				MODULE.queue_digest(connection, base, now-timedelta(hours=1), 8, 'UTC')
				self.process(connection, now=now)
				other = replace(base, report_id='second-report')
				MODULE.queue_digest(connection, other, now-timedelta(hours=1), 8, 'UTC')
				self.process(connection, now=now+timedelta(minutes=15))
				submit.assert_called_once()
			connection.close()
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
		self.assertEqual(report.get_problem_codes({"192.0.2.99"}), ("unexpected_source_ip",))

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
						"dmarc-reports@example.com",
						connection,
						"dmarc-reports@example.com",
						"postmaster@example.com",
						{"192.0.2.10"},
						False,
					)
			finally:
				connection.close()
		self.assertFalse(summary["alert_sent"])
		submit.assert_not_called()
		move.assert_called_once_with("dmarc-reports@example.com", "42", "Archive")

	def test_namespace_and_zip_message_are_supported(self):
		xml = MODULE._sample_xml(dkim="pass", spf="pass").replace(b"<feedback>", b'<feedback xmlns="urn:ietf:params:xml:ns:dmarc-2.0">')
		buffer = BytesIO()
		with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
			archive.writestr("report.xml", xml)
		message = EmailMessage()
		message["Subject"] = "Report domain: example.com"
		message.set_content("aggregate report")
		message.add_attachment(buffer.getvalue(), maintype="application", subtype="zip", filename="report.zip")
		report = MODULE.parse_message(message.as_bytes(), {"example.com"})
		self.assertEqual(report.policy_domain, "example.com")

	def test_doctype_is_rejected(self):
		xml = MODULE._sample_xml(dkim="pass", spf="pass").replace(b"<feedback>", b"<!DOCTYPE feedback><feedback>")
		with self.assertRaises(MODULE.ReportError):
			MODULE.parse_report_xml(xml)

	def test_domain_allowlist_is_enforced(self):
		xml = MODULE._sample_xml(dkim="pass", spf="pass", domain="outside.example")
		message = EmailMessage()
		message.add_attachment(xml, maintype="application", subtype="xml", filename="report.xml")
		with self.assertRaises(MODULE.ReportError):
			MODULE.parse_message(message.as_bytes(), {"example.com"})

	def test_alert_is_multipart_and_metadata_only(self):
		report = MODULE.parse_report_xml(MODULE._sample_xml(dkim="fail", spf="fail", disposition="reject"))
		message = MODULE.build_alert_message([report], "dmarc-reports@example.com", "postmaster@example.com", {"192.0.2.10"})
		self.assertTrue(message.is_multipart())
		self.assertEqual(message["To"], "postmaster@example.com")
		self.assertEqual(message["X-Geseidl-Status"], "WARN")
		self.assertEqual(message["X-Geseidl-Source"], "dmarc-aggregate")
		self.assertIn("dmarc_alignment_failed", message.get_body(preferencelist=("plain",)).get_content())
		self.assertNotIn("http://", message.get_body(preferencelist=("html",)).get_content())
		self.assertNotIn("https://", message.get_body(preferencelist=("html",)).get_content())


if __name__ == "__main__":
	unittest.main()
