import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


MANAGEMENT_DIR = Path(__file__).parents[1] / "management"
sys.path.insert(0, str(MANAGEMENT_DIR))

from geseidl_edition.zones import status


class GeseidlVersionStatusTest(unittest.TestCase):
	def setUp(self):
		self.manifest = {
			"overlay_version": "0.9.0",
			"path": str(Path(__file__).parents[1] / ".geseidl-edition"),
		}
		self.status_checks = types.SimpleNamespace(
			what_version_is_this=lambda _env: "geseidl-v76-20260806",
			get_latest_miab_version=lambda: "v76")

	def test_unintegrated_security_commit_is_an_error(self):
		with patch.dict(sys.modules, {"status_checks": self.status_checks}), \
			 patch.object(status, "_upstream_commit_gap", return_value=((84, 7, 1), None)):
			kind, text, extra = status._version_badge({}, self.manifest)

		self.assertEqual(kind, "error")
		self.assertIn("baza tag v76", text)
		self.assertIn("7 commituri", text)
		self.assertIn("1 commit marcat explicit ca securitate", text)
		self.assertTrue(any("upstream: -7" in item["text"] for item in extra))

	def test_unverifiable_upstream_is_not_reported_as_ok(self):
		with patch.object(status, "_upstream_commit_gap", return_value=(None, "fetch timeout")):
			kind, text, _extra = status._version_badge({}, self.manifest)

		self.assertEqual(kind, "warning")
		self.assertIn("nu s-a putut verifica", text)


if __name__ == "__main__":
	unittest.main()
