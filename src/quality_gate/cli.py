"""Minimal JSON CLI; no implicit network, Git, subprocess or write side effects."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .engine import GateInputError, evaluate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate evidence-backed readiness; NEVER approve/merge")
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--assessment", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--expected-policy-sha256", help="digest anchored independently of the candidate")
    args = parser.parse_args(argv)
    try:
        policy_bytes = args.policy.read_bytes()
        digest = hashlib.sha256(policy_bytes).hexdigest()
        if args.expected_policy_sha256 is not None and digest != args.expected_policy_sha256.lower():
            raise GateInputError("policy SHA-256 does not match trusted expectation")
        policy = json.loads(policy_bytes)
        assessment = json.loads(args.assessment.read_text(encoding="utf-8"))
        report = evaluate(policy, assessment, args.evidence_root)
        report["policy_sha256"] = digest
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        report = {
            "schema_version": "1.0",
            "state": "HOLD",
            "ready_to_merge": False,
            "human_approval_required": True,
            "reasons": [{"code": "INVALID_INPUT", "message": str(error)}],
        }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return {"READY_FOR_HUMAN_REVIEW": 0, "REWORK": 1}.get(report["state"], 2)


if __name__ == "__main__":
    sys.exit(main())
