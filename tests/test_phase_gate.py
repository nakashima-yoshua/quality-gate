"""Offline phase gate contract tests; all evidence here is synthetic."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path

from quality_gate.engine import GateInputError
from quality_gate.phase_cli import main
from quality_gate.phase_gate import PHASES, evaluate_phase

SHA = "a" * 40
OLD = "b" * 40


class PhaseGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ("spec.md", "review.md", "run.log"):
            (self.root / name).write_text(f"synthetic {name}\n", encoding="utf-8")
        self.policy = {
            "schema_version": "1.0",
            "policy_id": "policy-01",
            "scope_id": "CHG-001",
            "phase": "requirements",
            "source_revision": SHA,
            "required_item_ids": ["REQ-1", "REQ-2"],
        }
        self.assessment = {
            "schema_version": "1.0",
            "scope_id": "CHG-001",
            "phase": "requirements",
            "source_revision": SHA,
            "verifications": [self.spec("REQ-1", "AT-1"), self.spec("REQ-2", "AT-2")],
            "review": {
                "status": "COMPLETE",
                "reviewer_ref": "reviewer-01",
                "source_revision": SHA,
                "evidence": self.evidence("review.md"),
            },
            "open_items": [],
        }

    def evidence(self, name):
        return {
            "path": name,
            "sha256": hashlib.sha256((self.root / name).read_bytes()).hexdigest(),
        }

    def spec(self, item_id, test_id):
        return {
            "item_id": item_id,
            "test_spec_id": test_id,
            "kind": "acceptance",
            "status": "READY",
            "basis_revision": SHA,
            "oracle_ref": f"spec#{item_id}",
            "method_ref": f"test-plan#{test_id}",
            "evidence": self.evidence("spec.md"),
        }

    def to_run(self, phase="implementation", kind="unit"):
        self.policy["phase"] = self.assessment["phase"] = phase
        del self.assessment["review"]
        for check in self.assessment["verifications"]:
            check.update(
                kind=kind, status="PASS",
                run_id=f"run-{check['test_spec_id']}",
                evidence=self.evidence("run.log"),
            )
            del check["method_ref"]

    def report(self):
        return evaluate_phase(self.policy, self.assessment, self.root)

    def codes(self):
        return {entry["code"] for entry in self.report()["reasons"]}

    def test_prepared_requirements_only_ready_for_approval(self):
        result = self.report()
        self.assertEqual(result["state"], "READY_FOR_PHASE_APPROVAL")
        self.assertEqual(result["verified_item_ids"], ["REQ-1", "REQ-2"])
        self.assertFalse(result["phase_complete"])
        self.assertTrue(result["human_approval_required"])
        self.assertFalse(result["ready_to_merge"])

    def test_all_six_phases(self):
        base_policy, base_assessment = deepcopy(self.policy), deepcopy(self.assessment)
        for phase, (mode, kinds) in PHASES.items():
            with self.subTest(phase=phase):
                self.policy, self.assessment = deepcopy(base_policy), deepcopy(base_assessment)
                if mode == "run":
                    self.to_run(phase, sorted(kinds)[0])
                else:
                    self.policy["phase"] = self.assessment["phase"] = phase
                    for item in self.assessment["verifications"]:
                        item["kind"] = sorted(kinds)[0]
                self.assertEqual(self.report()["state"], "READY_FOR_PHASE_APPROVAL")

    def test_missing_required_item_holds_and_shows_denominator(self):
        self.assessment["verifications"].pop()
        result = self.report()
        self.assertEqual(result["state"], "HOLD")
        self.assertEqual(result["unverified_item_ids"], ["REQ-2"])
        self.assertIn("UNCOVERED_ITEM", self.codes())

    def test_not_ready_spec_never_fakes_evidence(self):
        self.assessment["verifications"][0] = {
            "item_id": "REQ-1", "test_spec_id": "AT-1",
            "kind": "acceptance", "status": "NOT_READY",
        }
        self.assertEqual(self.report()["state"], "HOLD")
        self.assertIn("VERIFICATION_UNAVAILABLE", self.codes())

    def test_rejected_spec_rework_even_if_no_ready_for_same_item(self):
        self.assessment["verifications"][0] = {
            "item_id": "REQ-1", "test_spec_id": "AT-1",
            "kind": "acceptance", "status": "REJECTED",
        }
        self.assertEqual(self.report()["state"], "REWORK")
        self.assertEqual(self.report()["unverified_item_ids"], ["REQ-1"])

    def test_not_reviewed_holds(self):
        self.assessment["review"] = {"status": "NOT_RUN"}
        self.assertEqual(self.report()["state"], "HOLD")
        self.assertIn("REVIEW_NOT_RUN", self.codes())

    def test_rejected_review_reworks(self):
        self.assessment["review"] = {"status": "REJECTED"}
        self.assertEqual(self.report()["state"], "REWORK")

    def test_stale_review_holds(self):
        self.assessment["review"]["source_revision"] = OLD
        self.assertIn("STALE_REVIEW", self.codes())

    def test_missing_oracle_is_invalid(self):
        del self.assessment["verifications"][0]["oracle_ref"]
        with self.assertRaises(GateInputError):
            self.report()

    def test_stale_assessment_is_invalid(self):
        self.assessment["source_revision"] = OLD
        with self.assertRaises(GateInputError):
            self.report()

    def test_stale_case_holds(self):
        self.assessment["verifications"][0]["basis_revision"] = OLD
        self.assertIn("STALE_VERIFICATION", self.codes())

    def test_material_open_item_holds(self):
        self.assessment["open_items"] = [
            {"id": "Q-1", "status": "OPEN", "material": True},
        ]
        self.assertIn("MATERIAL_OPEN_ITEM", self.codes())

    def test_nonmaterial_open_item_does_not_silently_change_denominator(self):
        self.assessment["open_items"] = [
            {"id": "STYLE-1", "status": "OPEN", "material": False},
        ]
        self.assertEqual(self.report()["required_item_ids"], ["REQ-1", "REQ-2"])

    def test_tampered_evidence_holds(self):
        (self.root / "spec.md").write_text("tampered")
        self.assertIn("VERIFICATION_EVIDENCE_INVALID", self.codes())
        self.assertIn("REQ-1", self.report()["unverified_item_ids"])

    def test_symlink_evidence_holds(self):
        (self.root / "link.md").symlink_to(self.root / "spec.md")
        self.assessment["verifications"][0]["evidence"] = self.evidence("link.md")
        self.assertIn("VERIFICATION_EVIDENCE_INVALID", self.codes())

    def test_outside_policy_denominator_invalid(self):
        self.assessment["verifications"][0]["item_id"] = "REQ-OTHER"
        with self.assertRaises(GateInputError):
            self.report()

    def test_duplicate_item_and_spec_invalid(self):
        self.assessment["verifications"].append(
            deepcopy(self.assessment["verifications"][0])
        )
        with self.assertRaises(GateInputError):
            self.report()

    def test_duplicate_required_items_invalid(self):
        self.policy["required_item_ids"].append("REQ-1")
        with self.assertRaises(GateInputError):
            self.report()

    def test_test_kind_must_match_phase(self):
        self.assessment["verifications"][0]["kind"] = "unit"
        with self.assertRaises(GateInputError):
            self.report()

    def test_run_evidence_ready_for_approval(self):
        self.to_run()
        self.assertEqual(self.report()["state"], "READY_FOR_PHASE_APPROVAL")

    def test_run_fail_is_rework_not_uncovered_hold(self):
        self.to_run()
        self.assessment["verifications"][0]["status"] = "FAIL"
        result = self.report()
        self.assertEqual(result["state"], "REWORK")
        self.assertEqual(result["unverified_item_ids"], ["REQ-1"])

    def test_run_not_run_is_hold_not_pass(self):
        self.to_run()
        self.assessment["verifications"][0] = {
            "item_id": "REQ-1", "test_spec_id": "AT-1",
            "kind": "unit", "status": "NOT_RUN",
        }
        self.assertEqual(self.report()["state"], "HOLD")

    def test_stale_run_holds(self):
        self.to_run()
        self.assessment["verifications"][0]["basis_revision"] = OLD
        self.assertIn("STALE_VERIFICATION", self.codes())

    def test_missing_run_evidence_holds(self):
        self.to_run()
        del self.assessment["verifications"][0]["evidence"]
        self.assertIn("VERIFICATION_EVIDENCE_INVALID", self.codes())

    def test_cli_policy_digest_mismatch_holds(self):
        p, a = self.root / "policy.json", self.root / "assessment.json"
        p.write_text(json.dumps(self.policy))
        a.write_text(json.dumps(self.assessment))
        output = StringIO()
        with redirect_stdout(output):
            code = main([
                "--policy", str(p), "--assessment", str(a),
                "--evidence-root", str(self.root),
                "--expected-policy-sha256", "0" * 64,
            ])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["state"], "HOLD")

    def test_cli_ready_never_claims_phase_completion(self):
        p, a = self.root / "policy.json", self.root / "assessment.json"
        p.write_text(json.dumps(self.policy))
        a.write_text(json.dumps(self.assessment))
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        output = StringIO()
        with redirect_stdout(output):
            code = main([
                "--policy", str(p), "--assessment", str(a),
                "--evidence-root", str(self.root),
                "--expected-policy-sha256", digest,
            ])
        self.assertEqual(code, 0)
        self.assertIs(json.loads(output.getvalue())["phase_complete"], False)


if __name__ == "__main__":
    unittest.main()
