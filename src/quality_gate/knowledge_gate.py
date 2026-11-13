"""Read-only bridge from an independently sealed ADS OKF lint report.

Never infer a business fact, a human knowledge approval, or merge authority.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .engine import GateInputError

SHA40 = re.compile(r"[0-9a-fA-F]{40}\Z")
SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
MAX_BUNDLE_BYTES = 64 * 1024 * 1024


def bundle_digest(bundle: Path) -> str:
    """Mirror ADS's length-prefixed path-and-content digest for all files."""
    if bundle.is_symlink() or not bundle.is_dir():
        raise GateInputError("knowledge bundle unavailable or symlinked")
    bundle = bundle.resolve()
    digest = hashlib.sha256()
    total = 0
    for path in sorted(bundle.rglob("*"), key=lambda p: p.relative_to(bundle).as_posix()):
        if path.is_symlink():
            raise GateInputError(f"knowledge bundle symlink prohibited: {path}")
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if total > MAX_BUNDLE_BYTES:
            raise GateInputError("knowledge bundle exceeds 64 MiB limit")
        relative = path.relative_to(bundle).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _unique_json(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise GateInputError(f"duplicate report JSON key: {key}")
        document[key] = value
    return document


def evaluate_knowledge(
    report_file: Path,
    bundle: Path,
    expected_report_sha256: str,
    expected_bundle_sha256: str,
    expected_head_sha: str,
) -> dict:
    """Verify host-supplied anchors against a sealed producer report and bundle.

    These arguments MUST originate from a trusted host, not the candidate/agent.
    The contract is advisory even after all digests match.
    """
    if not SHA256.fullmatch(expected_report_sha256) or not SHA256.fullmatch(expected_bundle_sha256):
        raise GateInputError("trusted expected SHA-256 values are required")
    if not SHA40.fullmatch(expected_head_sha):
        raise GateInputError("trusted exact candidate 40-hex Git SHA required")
    if report_file.is_symlink() or not report_file.is_file():
        raise GateInputError("sealed lint report unavailable or symlinked")
    if report_file.stat().st_size > 64 * 1024:
        raise GateInputError("lint report exceeds size limit")
    report_bytes = report_file.read_bytes()
    if hashlib.sha256(report_bytes).hexdigest() != expected_report_sha256.lower():
        raise GateInputError("lint report SHA-256 mismatch")
    try:
        report = json.loads(report_bytes, object_pairs_hook=_unique_json)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GateInputError(f"invalid lint report JSON: {exc}") from exc
    if not isinstance(report, dict) or set(report) != {
        "schema_version", "producer", "state", "head_sha", "bundle_sha256", "concepts", "pages"
    }:
        raise GateInputError("unsupported lint report schema")
    if report["schema_version"] != "1.0" or report["producer"] != "ads-okf-lint":
        raise GateInputError("unexpected knowledge lint producer or schema version")
    if report["state"] != "PASS":
        raise GateInputError("knowledge lint did not pass")
    if not isinstance(report["head_sha"], str) or report["head_sha"].lower() != expected_head_sha.lower():
        raise GateInputError("lint result is for a different candidate revision")
    if not isinstance(report["bundle_sha256"], str) or report["bundle_sha256"].lower() != expected_bundle_sha256.lower():
        raise GateInputError("lint report bundle digest differs from trusted expectation")
    if type(report["concepts"]) is not int or report["concepts"] < 1:
        raise GateInputError("lint report needs at least one concept")
    if type(report["pages"]) is not int or report["pages"] <= report["concepts"]:
        raise GateInputError("lint report pages count invalid")
    if bundle_digest(bundle) != expected_bundle_sha256.lower():
        raise GateInputError("knowledge files changed since the trusted digest")
    return {
        "schema_version": "1.0",
        "state": "READY_FOR_HUMAN_REVIEW",
        "ready_to_merge": False,
        "human_approval_required": True,
        "head_sha": expected_head_sha.lower(),
        "bundle_sha256": expected_bundle_sha256.lower(),
        "checks": ["OKF_STRUCTURE_AND_PROVENANCE_LINT_ANCHORED"],
        "reasons": [{"code": "LINT_EVIDENCE_VERIFIED", "message": "A sealed lint PASS matches the exact supplied files and revision; factual truth is not certified."}],
    }
