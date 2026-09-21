import unittest

from management.geseidl_edition.status_changes import semantic_line_key


class SemanticStatusChangeTests(unittest.TestCase):
	def test_healthy_counters_do_not_change_key(self):
		before = ["print_ok", ["rspamd active: 51223 scanned, 23593 learned"], {}]
		after = ["print_ok", ["rspamd active: 51281 scanned, 23593 learned"], {}]
		self.assertEqual(semantic_line_key(before), semantic_line_key(after))

	def test_healthy_translation_does_not_change_key(self):
		before = ["print_ok", ["Adresa IPv4 nu este listata de Spamhaus."], {}]
		after = ["print_ok", ["IPv4 address is not blacklisted by Spamhaus."], {}]
		self.assertEqual(semantic_line_key(before), semantic_line_key(after))

	def test_cloudflare_ip_order_does_not_change_key(self):
		before = ["print_line", ["gazduit la 172.67.73.135, 104.26.3.65, 104.26.2.65 / cloudflare"], {"monospace": True}]
		after = ["print_line", ["gazduit la 104.26.2.65, 172.67.73.135, 104.26.3.65 / cloudflare"], {"monospace": True}]
		self.assertEqual(semantic_line_key(before), semantic_line_key(after))

	def test_real_degradation_remains_visible(self):
		healthy = ["print_ok", ["SSH Login is running."], {}]
		degraded = ["print_error", ["SSH Login is not running (port 22)."], {}]
		self.assertNotEqual(semantic_line_key(healthy), semantic_line_key(degraded))

	def test_error_detail_change_remains_visible(self):
		before = ["print_error", ["There are 9 software packages that can be updated."], {}]
		after = ["print_error", ["There are 10 software packages that can be updated."], {}]
		self.assertNotEqual(semantic_line_key(before), semantic_line_key(after))


if __name__ == "__main__":
	unittest.main()
