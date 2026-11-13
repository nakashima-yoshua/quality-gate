"""Optional evidence-bound knowledge lint readiness gate; never approve or merge."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .engine import GateInputError
from .knowledge_gate import evaluate_knowledge


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--expected-report-sha256", required=True)
    p.add_argument("--expected-bundle-sha256", required=True)
    p.add_argument("--expected-head-sha", required=True)
    args = p.parse_args(argv)
    try:
        result = evaluate_knowledge(
            args.report, args.bundle, args.expected_report_sha256,
            args.expected_bundle_sha256, args.expected_head_sha,
        )
    except (GateInputError, OSError, ValueError) as exc:
        result = {
            "schema_version": "1.0", "state": "HOLD",
            "ready_to_merge": False, "human_approval_required": True,
            "reasons": [{"code": "UNTRUSTED_KNOWLEDGE_LINT", "message": str(exc)}],
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["state"] == "READY_FOR_HUMAN_REVIEW" else 2


if __name__ == "__main__":
    sys.exit(main())
