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
			 patch.object(status, "_upstream_commit_gap", return_value=((84, 7, [{
				"sha": "fc8d431", "subject": "[security] Update roundcube", "security_marked": True,
			}]), None)):
			kind, text, extra = status._version_badge({}, self.manifest)

		self.assertEqual(kind, "error")
		self.assertIn("baza tag v76", text)
		self.assertIn("7 commituri", text)
		self.assertIn("1 de securitate neevaluat", text)
		self.assertTrue(any("upstream: -7" in item["text"] for item in extra))

	def test_reviewed_security_commit_is_ok_when_the_gap_is_intentional(self):
		self.manifest["upstream_commit_reviews"] = [{"sha": "fc8d431", "verdict": "applied"}]
		self.manifest["upstream_review_summary"] = "1 aplicat"
		with patch.dict(sys.modules, {"status_checks": self.status_checks}), \
			 patch.object(status, "_upstream_commit_gap", return_value=((84, 7, [{
				"sha": "fc8d431a3c1de4f5678901234567890abcdef1234", "subject": "[security] Update roundcube", "security_marked": True,
			}]), None)):
			kind, text, extra = status._version_badge({}, self.manifest)

		self.assertEqual(kind, "ok")
		self.assertIn("graful Git rămâne divergent cu 7 commituri", text)
		self.assertIn("integrează selectiv, nu face merge complet", text)
		self.assertIn("Verdict: 1 aplicat", text)
		self.assertIn("1 commit de securitate acoperit local", text)
		self.assertTrue(any("neevaluate: 0" in item["text"] for item in extra))

	def test_unverifiable_upstream_is_not_reported_as_ok(self):
		with patch.object(status, "_upstream_commit_gap", return_value=(None, "fetch timeout")):
			kind, text, _extra = status._version_badge({}, self.manifest)

		self.assertEqual(kind, "warning")
		self.assertIn("nu s-a putut verifica", text)


if __name__ == "__main__":
	unittest.main()
