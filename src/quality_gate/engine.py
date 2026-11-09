"""Fail-closed quality gate. No AI calls, command execution, or GitHub writes."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Any


class GateInputError(ValueError):
    """Invalid policy or assessment; never interpret as a successful gate."""


TIERS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
STATUSES = {"PASS", "FAIL", "NOT_RUN", "BLOCKED", "ERROR"}
FINDING_CATEGORIES = {"IMPORTANT", "NIT", "PRE_EXISTING", "UNVERIFIED"}
DISPOSITIONS = {"OPEN", "FIXED", "DISMISSED", "HUMAN_DECISION"}
SHA_PATTERN = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
DIGEST_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")


def require_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GateInputError(f"{context}: expected object")
    return value


def require_list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise GateInputError(f"{context}: expected list")
    return value


def require_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateInputError(f"{context}: expected non-empty string")
    return value


def require_revision(value: Any, context: str) -> str:
    value = require_string(value, context)
    if not SHA_PATTERN.fullmatch(value):
        raise GateInputError(f"{context}: expected full Git SHA (40 or 64 hex characters)")
    return value.lower()


def require_path(value: Any, context: str) -> str:
    """Repo/evidence paths use POSIX relative paths, without dot/traversal segments."""
    value = require_string(value, context)
    parts = value.split("/")
    if ("\\" in value or "\x00" in value or value.startswith("/")
            or any(part in ("", ".", "..") for part in parts)
            or PurePosixPath(value).is_absolute()):
        raise GateInputError(f"{context}: unsafe relative path")
    return value


def validate_policy(policy: Any) -> dict[str, Any]:
    policy = require_object(policy, "policy")
    if policy.get("schema_version") != "1.0":
        raise GateInputError("policy: unsupported schema_version")
    require_string(policy.get("policy_id"), "policy.policy_id")
    required = require_object(policy.get("required_checks"), "policy.required_checks")
    for tier in TIERS[:3]:
        checks = require_list(required.get(tier), f"policy.required_checks.{tier}")
        if not checks or any(not isinstance(c, str) or not c.strip() for c in checks):
            raise GateInputError(f"policy.required_checks.{tier}: non-empty check IDs required")
        if len(checks) != len(set(checks)):
            raise GateInputError(f"policy.required_checks.{tier}: duplicate check IDs")
    cap = policy.get("max_review_passes")
    if type(cap) is not int or not (1 <= cap <= 10):
        raise GateInputError("policy.max_review_passes: expected integer 1..10")
    paths = require_list(policy.get("high_risk_paths"), "policy.high_risk_paths")
    for path in paths:
        # A trailing slash denotes a directory prefix; all others are exact paths.
        require_path(path.rstrip("/"), "policy.high_risk_paths entry")
    if len(paths) != len(set(paths)):
        raise GateInputError("policy.high_risk_paths: duplicate entry")
    return policy


def _path_is_sensitive(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if pattern.endswith("/") and path.startswith(pattern):
            return True
        if not pattern.endswith("/") and path == pattern:
            return True
    return False


def classify_risk(candidate: dict[str, Any], risk: dict[str, Any], policy: dict[str, Any]) -> str:
    files = require_list(candidate.get("changed_files"), "candidate.changed_files")
    if not files:
        raise GateInputError("candidate.changed_files: at least one changed file required")
    paths = [require_path(path, "candidate.changed_files entry") for path in files]
    if len(paths) != len(set(paths)):
        raise GateInputError("candidate.changed_files: duplicate path")
    hint = risk.get("minimum_tier", "LOW")
    if hint not in TIERS:
        raise GateInputError("risk.minimum_tier: invalid tier")
    unknown = risk.get("unknown_material", False)
    if type(unknown) is not bool:
        raise GateInputError("risk.unknown_material: expected boolean")
    documentation = all(path.lower().endswith((".md", ".rst", ".txt")) for path in paths)
    inferred = "LOW" if documentation else "MEDIUM"
    if any(_path_is_sensitive(path, policy["high_risk_paths"]) for path in paths):
        inferred = "HIGH"
    return TIERS[max(TIERS.index(inferred), TIERS.index(hint))]


def verify_evidence(value: Any, root: Path, context: str) -> None:
    evidence = require_object(value, context)
    name = require_path(evidence.get("path"), f"{context}.path")
    expected = require_string(evidence.get("sha256"), f"{context}.sha256")
    if not DIGEST_PATTERN.fullmatch(expected):
        raise GateInputError(f"{context}.sha256: invalid SHA-256")
    # No arbitrary paths and no symlinks at any level. Host ACLs must prevent races.
    current = root
    for part in name.split("/"):
        current = current / part
        if current.is_symlink():
            raise GateInputError(f"{context}: symlink evidence is prohibited")
    if not current.is_file():
        raise GateInputError(f"{context}: evidence file unavailable")
    if not current.resolve().is_relative_to(root):
        raise GateInputError(f"{context}: evidence escapes root")
    digest = hashlib.sha256()
    with current.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected.lower():
        raise GateInputError(f"{context}: evidence SHA-256 mismatch")


def _reason(code: str, explanation: str) -> dict[str, str]:
    return {"code": code, "message": explanation}


def evaluate(policy: Any, assessment: Any, evidence_root: Path) -> dict[str, Any]:
    """Evaluate host-provided records. An in-memory result is NOT merge authorization."""
    policy = validate_policy(policy)
    assessment = require_object(assessment, "assessment")
    if assessment.get("schema_version") != "1.0":
        raise GateInputError("assessment: unsupported schema_version")
    candidate = require_object(assessment.get("candidate"), "assessment.candidate")
    require_string(candidate.get("repository"), "candidate.repository")
    head_sha = require_revision(candidate.get("head_sha"), "candidate.head_sha")
    risk = require_object(assessment.get("risk"), "assessment.risk")
    tier = classify_risk(candidate, risk, policy)
    root = Path(evidence_root).resolve(strict=True)
    if not root.is_dir():
        raise GateInputError("evidence_root: expected directory")
    hold: list[dict[str, str]] = []
    rework: list[dict[str, str]] = []
    if risk.get("unknown_material", False):
        hold.append(_reason("UNKNOWN_MATERIAL_RISK", "Material change risk is not resolved"))
    if tier == "CRITICAL":
        hold.append(_reason("CRITICAL_RISK", "Human-led assessment required"))

    checks = require_list(assessment.get("checks"), "assessment.checks")
    indexed: dict[str, dict[str, Any]] = {}
    for entry in checks:
        item = require_object(entry, "checks entry")
        name = require_string(item.get("id"), "checks.id")
        if name in indexed:
            raise GateInputError(f"checks: duplicate ID {name}")
        indexed[name] = item
    required_ids = policy["required_checks"].get(tier, [])
    for check_id in required_ids:
        item = indexed.get(check_id)
        if item is None:
            hold.append(_reason("MISSING_CHECK", f"Missing required check: {check_id}"))
            continue
        status = item.get("status")
        if status not in STATUSES:
            raise GateInputError(f"checks.{check_id}: invalid status")
        unavailable = status in ("NOT_RUN", "BLOCKED", "ERROR")
        # No revision or artifact is required for an unexecuted check. If supplied,
        # validate it anyway; missing observations must never turn into PASS.
        if not unavailable or "head_sha" in item:
            revision = require_revision(item.get("head_sha"), f"checks.{check_id}.head_sha")
            if revision != head_sha:
                hold.append(_reason("STALE_CHECK", f"{check_id} result targets another revision"))
        if unavailable:
            hold.append(_reason("CHECK_UNAVAILABLE", f"{check_id}: {status}"))
        elif status == "FAIL":
            rework.append(_reason("CHECK_FAILED", f"{check_id}: FAIL"))
        # A completed result must carry evidence, including FAIL. Optional
        # evidence for an unavailable check is still verified when supplied.
        if not unavailable or "evidence" in item:
            try:
                verify_evidence(item.get("evidence"), root, f"checks.{check_id}.evidence")
            except GateInputError as error:
                hold.append(_reason("CHECK_EVIDENCE_INVALID", str(error)))

    review = require_object(assessment.get("review"), "assessment.review")
    review_status = review.get("status")
    if review_status not in {"COMPLETE", "NOT_RUN", "ERROR"}:
        raise GateInputError("review.status: invalid value")
    if review_status != "COMPLETE":
        hold.append(_reason("REVIEW_UNAVAILABLE", f"Independent review: {review_status}"))
    complete = review_status == "COMPLETE"
    if complete or "reviewed_sha" in review:
        reviewed_sha = require_revision(review.get("reviewed_sha"), "review.reviewed_sha")
        if reviewed_sha != head_sha:
            hold.append(_reason("STALE_REVIEW", "Review does not match candidate revision"))
    if complete or "implementation_session" in review:
        implementer = require_string(review.get("implementation_session"), "review.implementation_session")
    else:
        implementer = None
    if complete or "review_session" in review:
        reviewer = require_string(review.get("review_session"), "review.review_session")
    else:
        reviewer = None
    if implementer is not None and reviewer is not None and implementer == reviewer:
        hold.append(_reason("NON_INDEPENDENT_REVIEW", "Reviewer shares implementation session"))
    passes = review.get("passes", 0 if not complete else None)
    if type(passes) is not int or passes < 0:
        raise GateInputError("review.passes: expected non-negative integer")
    if passes > policy["max_review_passes"]:
        hold.append(_reason("REVIEW_BUDGET_EXCEEDED", "Review pass cap exceeded"))
    if complete and passes == 0:
        hold.append(_reason("REVIEW_NOT_PERFORMED", "Completed review requires one or more passes"))
    if complete or "evidence" in review:
        try:
            verify_evidence(review.get("evidence"), root, "review.evidence")
        except GateInputError as error:
            hold.append(_reason("REVIEW_EVIDENCE_INVALID", str(error)))

    findings = require_list(review.get("findings", [] if not complete else None), "review.findings")
    seen: set[str] = set()
    for item in findings:
        finding = require_object(item, "review.findings entry")
        identifier = require_string(finding.get("id"), "finding.id")
        if identifier in seen:
            raise GateInputError(f"review.findings: duplicate ID {identifier}")
        seen.add(identifier)
        category = finding.get("category")
        disposition = finding.get("disposition")
        if category not in FINDING_CATEGORIES or disposition not in DISPOSITIONS:
            raise GateInputError(f"finding {identifier}: invalid category/disposition")
        if disposition in ("FIXED", "DISMISSED"):
            reason = finding.get("verification")
            if not isinstance(reason, str) or not reason.strip():
                hold.append(_reason("UNVERIFIED_DISPOSITION", f"{identifier}: verification is missing"))
        if disposition == "HUMAN_DECISION":
            hold.append(_reason("FINDING_HUMAN_DECISION", f"{identifier}: human disposition required"))
        elif category == "UNVERIFIED" and disposition == "OPEN":
            hold.append(_reason("UNVERIFIED_FINDING", f"{identifier}: outcome not verified"))
        elif category == "IMPORTANT" and disposition == "OPEN":
            if passes >= policy["max_review_passes"]:
                hold.append(_reason("REVIEW_NOT_CONVERGED", f"{identifier}: review pass cap reached"))
            else:
                rework.append(_reason("IMPORTANT_FINDING", f"{identifier}: important issue remains"))

    state = "HOLD" if hold else ("REWORK" if rework else "READY_FOR_HUMAN_REVIEW")
    return {
        "schema_version": "1.0",
        "policy_id": policy["policy_id"],
        "repository": candidate["repository"],
        "head_sha": head_sha,
        "risk_tier": tier,
        "state": state,
        "ready_to_merge": False,
        "human_approval_required": True,
        "required_checks": required_ids,
        "reasons": hold + rework,
    }
