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

	def test_package_count_only_and_old_cache_migration_are_quiet(self):
		before = ["print_error", ["There are 9 software packages that can be updated."], {}]
		after = ["print_line", ["There are 10 software packages that can be updated."], {}]
		self.assertEqual(semantic_line_key(before), semantic_line_key(after))
		serialized = ["print_line", ["There are 10 software packages that can be updated."], {"monospace": False}]
		self.assertEqual(semantic_line_key(before), semantic_line_key(serialized))

	def test_package_count_rejects_unexpected_serializer_kwargs(self):
		legacy = ["print_error", ["There are 9 software packages that can be updated."], {}]
		for kwargs in ({"monospace": True}, {"monospace": 0}, {"monospace": "false"},
			{"monospace": False, "other": False}, {"other": False}):
			with self.subTest(kwargs=kwargs):
				candidate = ["print_line", ["There are 10 software packages that can be updated."], kwargs]
				self.assertNotEqual(semantic_line_key(legacy), semantic_line_key(candidate))
		legacy_with_kwargs = ["print_error", legacy[1], {"monospace": False}]
		self.assertNotEqual(semantic_line_key(legacy), semantic_line_key(legacy_with_kwargs))

	def test_unknown_error_detail_change_remains_visible(self):
		before = ["print_error", ["There are 9 packages with failed security checks."], {}]
		after = ["print_error", ["There are 10 packages with failed security checks."], {}]
		self.assertNotEqual(semantic_line_key(before), semantic_line_key(after))

	def test_pending_packages_are_not_healthy_or_held(self):
		pending = ["print_line", ["There is 1 software package that can be updated."], {}]
		for other in (["print_ok", ["System software is up to date."], {}],
			["print_warning", ["1 package update is held by administrator policy."], {}],
			["print_error", ["There is 1 software package that can be updated. Reboot failed."], {}]):
			self.assertNotEqual(semantic_line_key(pending), semantic_line_key(other))


if __name__ == "__main__":
	unittest.main()
