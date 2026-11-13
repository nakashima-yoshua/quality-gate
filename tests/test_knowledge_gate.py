"""Fail-closed compatibility tests for a sealed ADS knowledge lint report."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from quality_gate.engine import GateInputError
from quality_gate.knowledge_gate import bundle_digest, evaluate_knowledge

ROOT = Path(__file__).resolve().parents[1]
HEAD = "a" * 40


class KnowledgeGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        (self.bundle / "index.md").write_text("# test\n", encoding="utf-8")
        (self.bundle / "concept.md").write_text("---\ntype: Test\n---\n", encoding="utf-8")
        self.report_file = self.root / "report.json"
        self.bundle_sha = bundle_digest(self.bundle)
        self.report = {
            "schema_version": "1.0", "producer": "ads-okf-lint", "state": "PASS",
            "head_sha": HEAD, "bundle_sha256": self.bundle_sha,
            "concepts": 1, "pages": 2,
        }
        self.save_report()

    def save_report(self):
        data = json.dumps(self.report, sort_keys=True).encode()
        self.report_file.write_bytes(data)
        self.report_sha = hashlib.sha256(data).hexdigest()

    def verify(self, **kw):
        return evaluate_knowledge(
            kw.get("report_file", self.report_file),
            kw.get("bundle", self.bundle),
            kw.get("expected_report_sha256", self.report_sha),
            kw.get("expected_bundle_sha256", self.bundle_sha),
            kw.get("expected_head_sha", HEAD),
        )

    def test_exact_artifacts_only_ready_for_human_review(self):
        result = self.verify()
        self.assertEqual(result["state"], "READY_FOR_HUMAN_REVIEW")
        self.assertFalse(result["ready_to_merge"])
        self.assertTrue(result["human_approval_required"])

    def test_report_tamper_rejected(self):
        self.report_file.write_bytes(self.report_file.read_bytes() + b" ")
        with self.assertRaisesRegex(GateInputError, "report SHA-256 mismatch"):
            self.verify()

    def test_bundle_tamper_rejected(self):
        (self.bundle / "concept.md").write_text("changed")
        with self.assertRaisesRegex(GateInputError, "knowledge files changed"):
            self.verify()

    def test_mismatched_head_rejected(self):
        with self.assertRaisesRegex(GateInputError, "different candidate"):
            self.verify(expected_head_sha="b" * 40)

    def test_fake_pass_without_trusted_digest_rejected(self):
        with self.assertRaisesRegex(GateInputError, "bundle digest differs"):
            self.verify(expected_bundle_sha256="b" * 64)

    def test_failed_lint_rejected(self):
        self.report["state"] = "FAIL"
        self.save_report()
        with self.assertRaisesRegex(GateInputError, "did not pass"):
            self.verify()

    def test_duplicate_report_key_rejected(self):
        self.report_file.write_text(self.report_file.read_text()[:-1] + ',"state":"PASS"}')
        self.report_sha = hashlib.sha256(self.report_file.read_bytes()).hexdigest()
        with self.assertRaisesRegex(GateInputError, "duplicate report JSON key"):
            self.verify()

    def test_symlink_in_bundle_rejected(self):
        (self.bundle / "alias.md").symlink_to(self.bundle / "concept.md")
        with self.assertRaisesRegex(GateInputError, "symlink prohibited"):
            self.verify()

    def test_cli_hold_for_invalid_anchor(self):
        command = [
            sys.executable, "-m", "quality_gate.knowledge_cli",
            "--report", str(self.report_file), "--bundle", str(self.bundle),
            "--expected-report-sha256", "0" * 64,
            "--expected-bundle-sha256", self.bundle_sha,
            "--expected-head-sha", HEAD,
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["state"], "HOLD")


if __name__ == "__main__":
    unittest.main()
