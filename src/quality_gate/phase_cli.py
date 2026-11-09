"""Read-only CLI for verification-driven phase readiness (separate from code gate)."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .engine import GateInputError
from .phase_gate import evaluate_phase


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check phase verification readiness; never approve a phase")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--assessment", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--expected-policy-sha256", help="host-controlled policy digest")
    args = parser.parse_args(argv)
    try:
        policy_bytes = args.policy.read_bytes()
        digest = hashlib.sha256(policy_bytes).hexdigest()
        if args.expected_policy_sha256 is not None and digest != args.expected_policy_sha256.lower():
            raise GateInputError("policy SHA-256 does not match trusted expectation")
        policy = json.loads(policy_bytes)
        assessment = json.loads(args.assessment.read_text(encoding="utf-8"))
        report = evaluate_phase(policy, assessment, args.evidence_root)
        report["policy_sha256"] = digest
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        report = {
            "schema_version": "1.0",
            "state": "HOLD",
            "phase_complete": False,
            "human_approval_required": True,
            "ready_to_merge": False,
            "reasons": [{"code": "INVALID_INPUT", "message": str(error)}],
        }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return {"READY_FOR_PHASE_APPROVAL": 0, "REWORK": 1}.get(report["state"], 2)


if __name__ == "__main__":
    sys.exit(main())
