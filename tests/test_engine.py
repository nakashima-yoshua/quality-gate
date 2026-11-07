"""No mocks of production run: this suite verifies only the offline gate contract."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from quality_gate.cli import main
from quality_gate.engine import GateInputError, evaluate


SHA = "a" * 40
OTHER = "b" * 40


class QualityGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.root.joinpath("build.log").write_text("build passed\n")
        self.root.joinpath("tests.log").write_text("tests passed\n")
        self.root.joinpath("security.log").write_text("security passed\n")
        self.root.joinpath("repo.log").write_text("repo passed\n")
        self.root.joinpath("review.log").write_text("independent review\n")
        self.policy = {
            "schema_version": "1.0",
            "policy_id": "test",
            "max_review_passes": 3,
            "high_risk_paths": ["auth/", ".github/workflows/", "migrations/"],
            "required_checks": {
                "LOW": ["repo"],
                "MEDIUM": ["build", "tests"],
                "HIGH": ["build", "tests", "security"],
            },
        }
        self.assessment = {
            "schema_version": "1.0",
            "candidate": {
                "repository": "test/quality-gate",
                "head_sha": SHA,
                "changed_files": ["src/main.py"],
            },
            "risk": {"minimum_tier": "LOW", "unknown_material": False},
            "checks": [
                self.check("build", "build.log"),
                self.check("tests", "tests.log"),
                self.check("security", "security.log"),
                self.check("repo", "repo.log"),
            ],
            "review": {
                "status": "COMPLETE",
                "reviewed_sha": SHA,
                "implementation_session": "build-01",
                "review_session": "review-02",
                "passes": 1,
                "evidence": self.evidence("review.log"),
                "findings": [],
            },
        }

    def tearDown(self):
        self.tmp.cleanup()

    def evidence(self, name):
        return {"path": name, "sha256": hashlib.sha256((self.root / name).read_bytes()).hexdigest()}

    def check(self, name, log):
        return {"id": name, "status": "PASS", "head_sha": SHA, "evidence": self.evidence(log)}

    def result(self, assessment=None, policy=None):
        return evaluate(policy or self.policy, assessment or self.assessment, self.root)

    def codes(self, result):
        return {reason["code"] for reason in result["reasons"]}

    def test_pass_is_never_merge_approval(self):
        report = self.result()
        self.assertEqual(report["state"], "READY_FOR_HUMAN_REVIEW")
        self.assertEqual(report["risk_tier"], "MEDIUM")
        self.assertIs(report["ready_to_merge"], False)
        self.assertIs(report["human_approval_required"], True)

    def test_doc_only_needs_low_checks(self):
        self.assessment["candidate"]["changed_files"] = ["README.md"]
        self.assessment["checks"] = [self.check("repo", "repo.log")]
        self.assertEqual(self.result()["risk_tier"], "LOW")
        self.assertEqual(self.result()["state"], "READY_FOR_HUMAN_REVIEW")

    def test_sensitive_path_requires_high_checks(self):
        self.assessment["candidate"]["changed_files"].append("auth/session.py")
        self.assessment["checks"] = self.assessment["checks"][:2]
        report = self.result()
        self.assertEqual(report["risk_tier"], "HIGH")
        self.assertIn("MISSING_CHECK", self.codes(report))

    def test_risk_hint_only_elevates(self):
        self.assessment["risk"]["minimum_tier"] = "HIGH"
        self.assertEqual(self.result()["risk_tier"], "HIGH")

    def test_failed_check_requests_rework(self):
        self.assessment["checks"][0]["status"] = "FAIL"
        self.assertEqual(self.result()["state"], "REWORK")

    def test_not_run_check_holds(self):
        self.assessment["checks"][0]["status"] = "NOT_RUN"
        self.assertIn("CHECK_UNAVAILABLE", self.codes(self.result()))

    def test_missing_check_holds(self):
        self.assessment["checks"] = self.assessment["checks"][1:]
        self.assertIn("MISSING_CHECK", self.codes(self.result()))

    def test_stale_check_holds(self):
        self.assessment["checks"][0]["head_sha"] = OTHER
        self.assertIn("STALE_CHECK", self.codes(self.result()))

    def test_corrupted_evidence_holds(self):
        self.root.joinpath("build.log").write_text("modified after saving hash\n")
        self.assertIn("CHECK_EVIDENCE_INVALID", self.codes(self.result()))

    def test_path_traversal_holds(self):
        self.assessment["checks"][0]["evidence"]["path"] = "../secret"
        self.assertIn("CHECK_EVIDENCE_INVALID", self.codes(self.result()))

    def test_symlink_evidence_holds(self):
        (self.root / "link.log").symlink_to(self.root / "build.log")
        self.assessment["checks"][0]["evidence"] = self.evidence("link.log")
        self.assertIn("CHECK_EVIDENCE_INVALID", self.codes(self.result()))

    def test_missing_review_holds(self):
        self.assessment["review"]["status"] = "NOT_RUN"
        self.assertIn("REVIEW_UNAVAILABLE", self.codes(self.result()))

    def test_same_session_review_holds(self):
        self.assessment["review"]["review_session"] = "build-01"
        self.assertIn("NON_INDEPENDENT_REVIEW", self.codes(self.result()))

    def test_stale_review_holds(self):
        self.assessment["review"]["reviewed_sha"] = OTHER
        self.assertIn("STALE_REVIEW", self.codes(self.result()))

    def test_important_finding_requests_rework(self):
        self.assessment["review"]["findings"] = [self.finding("IMPORTANT", "OPEN")]
        self.assertIn("IMPORTANT_FINDING", self.codes(self.result()))

    def test_review_cap_stops_rework(self):
        self.assessment["review"]["passes"] = 3
        self.assessment["review"]["findings"] = [self.finding("IMPORTANT", "OPEN")]
        report = self.result()
        self.assertEqual(report["state"], "HOLD")
        self.assertIn("REVIEW_NOT_CONVERGED", self.codes(report))

    def test_unverified_finding_holds(self):
        self.assessment["review"]["findings"] = [self.finding("UNVERIFIED", "OPEN")]
        self.assertIn("UNVERIFIED_FINDING", self.codes(self.result()))

    def test_dismissal_without_evidence_holds(self):
        self.assessment["review"]["findings"] = [self.finding("IMPORTANT", "DISMISSED")]
        self.assertIn("UNVERIFIED_DISPOSITION", self.codes(self.result()))

    def test_dismissal_with_reason_does_not_override_checks(self):
        finding = self.finding("IMPORTANT", "DISMISSED")
        finding["verification"] = "Reproduction shows only a style difference"
        self.assessment["review"]["findings"] = [finding]
        self.assertEqual(self.result()["state"], "READY_FOR_HUMAN_REVIEW")

    def test_human_decision_holds(self):
        self.assessment["review"]["findings"] = [self.finding("IMPORTANT", "HUMAN_DECISION")]
        self.assertIn("FINDING_HUMAN_DECISION", self.codes(self.result()))

    def test_preexisting_and_nit_do_not_block(self):
        self.assessment["review"]["findings"] = [
            self.finding("PRE_EXISTING", "OPEN", "PRE-1"),
            self.finding("NIT", "OPEN", "NIT-1"),
        ]
        self.assertEqual(self.result()["state"], "READY_FOR_HUMAN_REVIEW")

    def test_unknown_material_risk_holds(self):
        self.assessment["risk"]["unknown_material"] = True
        self.assertIn("UNKNOWN_MATERIAL_RISK", self.codes(self.result()))

    def test_critical_risk_holds(self):
        self.assessment["risk"]["minimum_tier"] = "CRITICAL"
        self.assertIn("CRITICAL_RISK", self.codes(self.result()))

    def test_no_changed_paths_rejected(self):
        self.assessment["candidate"]["changed_files"] = []
        with self.assertRaises(GateInputError):
            self.result()

    def test_bad_revision_rejected(self):
        self.assessment["candidate"]["head_sha"] = "not-a-sha"
        with self.assertRaises(GateInputError):
            self.result()

    def test_duplicate_checks_rejected(self):
        self.assessment["checks"].append(deepcopy(self.assessment["checks"][0]))
        with self.assertRaises(GateInputError):
            self.result()

    def test_nonboolean_unknown_risk_rejected(self):
        self.assessment["risk"]["unknown_material"] = "false"
        with self.assertRaises(GateInputError):
            self.result()

    def test_policy_missing_required_checks_rejected(self):
        del self.policy["required_checks"]["HIGH"]
        with self.assertRaises(GateInputError):
            self.result()

    def test_cli_expected_policy_digest_mismatch_fails_closed(self):
        policy_file = self.root / "policy.json"
        assessment_file = self.root / "assessment.json"
        policy_file.write_text(json.dumps(self.policy))
        assessment_file.write_text(json.dumps(self.assessment))
        from contextlib import redirect_stdout
        from io import StringIO
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["--policy", str(policy_file), "--assessment", str(assessment_file),
                              "--evidence-root", str(self.root), "--expected-policy-sha256", "0" * 64])
        self.assertEqual(exit_code, 2)
        self.assertEqual(json.loads(output.getvalue())["state"], "HOLD")

    @staticmethod
    def finding(category, disposition, identifier="ISS-1"):
        return {"id": identifier, "category": category, "disposition": disposition}


if __name__ == "__main__":
    unittest.main()
