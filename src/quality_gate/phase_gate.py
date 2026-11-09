"""Read-only verification-driven phase gate; never completes or authorizes a phase."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .engine import GateInputError, require_list, require_object, require_revision, require_string, verify_evidence

# These are verification categories, not a mandated waterfall or test-count target.
PHASES: dict[str, tuple[str, frozenset[str]]] = {
    "requirements": ("spec", frozenset({"acceptance"})),
    "basic_design": ("spec", frozenset({"scenario", "integration"})),
    "detailed_design": ("spec", frozenset({"unit", "service", "db", "integration", "scenario"})),
    "implementation": ("run", frozenset({"unit", "service", "db", "integration", "scenario"})),
    "integration": ("run", frozenset({"integration", "scenario"})),
    "acceptance": ("run", frozenset({"acceptance", "scenario"})),
}
SPEC_STATUSES = {"READY", "NOT_READY", "REJECTED"}
RUN_STATUSES = {"PASS", "FAIL", "NOT_RUN", "BLOCKED", "ERROR"}


def _reason(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "message": detail}


def validate_phase_policy(policy: Any) -> dict[str, Any]:
    policy = require_object(policy, "phase policy")
    if policy.get("schema_version") != "1.0":
        raise GateInputError("phase policy: unsupported schema_version")
    require_string(policy.get("policy_id"), "phase policy.policy_id")
    require_string(policy.get("scope_id"), "phase policy.scope_id")
    phase = require_string(policy.get("phase"), "phase policy.phase")
    if phase not in PHASES:
        raise GateInputError("phase policy.phase: unsupported phase")
    require_revision(policy.get("source_revision"), "phase policy.source_revision")
    required = require_list(policy.get("required_item_ids"), "phase policy.required_item_ids")
    if not required:
        raise GateInputError("phase policy.required_item_ids: non-empty required")
    ids = [require_string(item, "required_item_ids entry") for item in required]
    if len(ids) != len(set(ids)):
        raise GateInputError("phase policy.required_item_ids: duplicate ID")
    return policy


def evaluate_phase(policy: Any, assessment: Any, evidence_root: Path) -> dict[str, Any]:
    """Evaluate a frozen stage slice and its evidence, not the correctness of the spec."""
    policy = validate_phase_policy(policy)
    assessment = require_object(assessment, "phase assessment")
    if assessment.get("schema_version") != "1.0":
        raise GateInputError("phase assessment: unsupported schema_version")
    phase = policy["phase"]
    if assessment.get("phase") != phase or assessment.get("scope_id") != policy["scope_id"]:
        raise GateInputError("phase assessment: phase/scope mismatch")
    source_revision = require_revision(assessment.get("source_revision"), "assessment.source_revision")
    if source_revision != policy["source_revision"].lower():
        raise GateInputError("phase assessment: stale source revision")
    root = Path(evidence_root).resolve(strict=True)
    if not root.is_dir():
        raise GateInputError("evidence_root: expected directory")

    mode, kinds = PHASES[phase]
    required = set(policy["required_item_ids"])
    verified: set[str] = set()
    observed: set[str] = set()
    seen: set[tuple[str, str]] = set()
    hold: list[dict[str, str]] = []
    rework: list[dict[str, str]] = []
    for index, raw in enumerate(require_list(assessment.get("verifications"), "assessment.verifications")):
        item = require_object(raw, f"verifications[{index}]")
        item_id = require_string(item.get("item_id"), "verification.item_id")
        check_id = require_string(item.get("test_spec_id"), "verification.test_spec_id")
        if item_id not in required:
            raise GateInputError(f"verification {check_id}: item {item_id} outside approved denominator")
        observed.add(item_id)
        if (item_id, check_id) in seen:
            raise GateInputError(f"verifications: duplicate item/test pair {item_id}/{check_id}")
        seen.add((item_id, check_id))
        if item.get("kind") not in kinds:
            raise GateInputError(f"verification {check_id}: unsupported test kind for {phase}")
        status = item.get("status")
        if status not in (SPEC_STATUSES if mode == "spec" else RUN_STATUSES):
            raise GateInputError(f"verification {check_id}: invalid status")
        if status in {"READY", "PASS", "FAIL"}:
            basis = require_revision(item.get("basis_revision"), f"verification {check_id}.basis_revision")
            if basis != source_revision:
                hold.append(_reason("STALE_VERIFICATION", f"{check_id}: different source revision"))
            require_string(item.get("oracle_ref"), f"verification {check_id}.oracle_ref")
            if mode == "spec":
                require_string(item.get("method_ref"), f"verification {check_id}.method_ref")
            else:
                require_string(item.get("run_id"), f"verification {check_id}.run_id")
            valid_evidence = True
            try:
                verify_evidence(item.get("evidence"), root, f"verification {check_id}.evidence")
            except GateInputError as error:
                hold.append(_reason("VERIFICATION_EVIDENCE_INVALID", str(error)))
                valid_evidence = False
            if status in {"READY", "PASS"} and basis == source_revision and valid_evidence:
                verified.add(item_id)
        elif "evidence" in item:
            try:
                verify_evidence(item["evidence"], root, f"verification {check_id}.evidence")
            except GateInputError as error:
                hold.append(_reason("VERIFICATION_EVIDENCE_INVALID", str(error)))
        if status in {"NOT_READY", "NOT_RUN", "BLOCKED", "ERROR"}:
            hold.append(_reason("VERIFICATION_UNAVAILABLE", f"{item_id}/{check_id}: {status}"))
        elif status in {"REJECTED", "FAIL"}:
            rework.append(_reason("VERIFICATION_FAILED", f"{item_id}/{check_id}: {status}"))

    for item_id in policy["required_item_ids"]:
        if item_id not in observed:
            hold.append(_reason("UNCOVERED_ITEM", f"Required item has no matching case/spec: {item_id}"))

    if mode == "spec":
        review = require_object(assessment.get("review"), "assessment.review")
        state = review.get("status")
        if state not in {"COMPLETE", "NOT_RUN", "REJECTED"}:
            raise GateInputError("assessment.review.status: invalid value")
        if state == "COMPLETE":
            reviewer = require_string(review.get("reviewer_ref"), "assessment.review.reviewer_ref")
            reviewed_revision = require_revision(review.get("source_revision"), "assessment.review.source_revision")
            if reviewed_revision != source_revision:
                hold.append(_reason("STALE_REVIEW", f"Review by {reviewer} targets another revision"))
            try:
                verify_evidence(review.get("evidence"), root, "assessment.review.evidence")
            except GateInputError as error:
                hold.append(_reason("REVIEW_EVIDENCE_INVALID", str(error)))
        elif state == "REJECTED":
            rework.append(_reason("REVIEW_REJECTED", "Verification specification review rejected"))
        else:
            hold.append(_reason("REVIEW_NOT_RUN", "Verification specification review missing"))
        if state != "COMPLETE" and "evidence" in review:
            try:
                verify_evidence(review["evidence"], root, "assessment.review.evidence")
            except GateInputError as error:
                hold.append(_reason("REVIEW_EVIDENCE_INVALID", str(error)))

    open_items = require_list(assessment.get("open_items"), "assessment.open_items")
    open_ids: set[str] = set()
    for index, raw in enumerate(open_items):
        issue = require_object(raw, f"open_items[{index}]")
        issue_id = require_string(issue.get("id"), "open_items.id")
        if issue_id in open_ids:
            raise GateInputError(f"open_items: duplicate ID {issue_id}")
        open_ids.add(issue_id)
        if type(issue.get("material")) is not bool or issue.get("status") not in {"OPEN", "RESOLVED"}:
            raise GateInputError(f"open_items {issue_id}: invalid status/material")
        if issue["material"] and issue["status"] == "OPEN":
            hold.append(_reason("MATERIAL_OPEN_ITEM", f"Material unresolved item: {issue_id}"))

    missing = [item_id for item_id in policy["required_item_ids"] if item_id not in verified]
    state = "HOLD" if hold else ("REWORK" if rework else "READY_FOR_PHASE_APPROVAL")
    return {
        "schema_version": "1.0",
        "policy_id": policy["policy_id"],
        "scope_id": policy["scope_id"],
        "phase": phase,
        "source_revision": source_revision,
        "state": state,
        "required_item_ids": list(policy["required_item_ids"]),
        "verified_item_ids": sorted(verified),
        "unverified_item_ids": missing,
        "reasons": hold + rework,
        "phase_complete": False,
        "human_approval_required": True,
        "ready_to_merge": False,
    }
