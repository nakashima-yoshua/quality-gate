# Verification-Driven Phase Gates (v1)

## Purpose and scope

This is an optional, offline, read-only evaluator for **verification readiness at each development phase**. It does not create test cases, execute tests, approve a phase, merge code, or release software.

The existing code readiness gate stays unchanged. Feature-map-workflow remains the feature knowledge and traceability layer; cli-test-mcp remains the execution/evidence owner. A future test-design-engine may select and optimize tests. This proposal deliberately adds no required dependencies and no FMW XML/XSD changes.

## Phase-level conditions

| Phase key | Mode | What must be verifiable |
| --- | --- | --- |
| requirements | spec | Accepted requirements have independently derived acceptance test specs and expected results |
| basic_design | spec | Relevant scenarios and integration boundaries have verifiable specs |
| detailed_design | spec | Required unit/service/DB/integration behavior has verifiable specs |
| implementation | run | Required unit/service/DB tests ran and have evidence |
| integration | run | Required integration/scenario tests ran and have evidence |
| acceptance | run | Required acceptance/scenario tests ran and have evidence |

This mapping is a default profile for the MVP, not a mandated waterfall or a demand to write all test types. A project can assess one changed feature/slice at a time. The test layer is selected for the behavior and risk. Requirements and design also require substantive review of correctness, feasibility, security, data ownership, etc.; a generated test-spec file alone does not establish their validity.

## Input contracts

Call the separate CLI with an immutable, externally approved policy and a phase assessment:

    PYTHONPATH=src python -m quality_gate.phase_cli \
      --policy examples/phase-gate/policy.json \
      --assessment examples/phase-gate/assessment.json \
      --evidence-root examples/phase-gate/evidence

For real CI usage, additionally supply --expected-policy-sha256 with a digest anchored outside the candidate changes and model write permissions. Without this independent anchor, an actor could remove required cases from its own policy.

### Policy JSON v1.0

    {
      "schema_version": "1.0",
      "policy_id": "approved-001",
      "scope_id": "CHG-001",
      "phase": "requirements",
      "source_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "required_item_ids": ["REQ-001"]
    }

The required-item set is the approved, version-bound denominator. It must not be silently reduced when verification becomes expensive. source_revision is a full 40- or 64-hex-character Git SHA. The sample SHA is fictional. Only the authorizing project owner can accept substantive scope changes; this evaluator never does.

### Assessment JSON v1.0

    {
      "schema_version": "1.0",
      "scope_id": "CHG-001",
      "phase": "requirements",
      "source_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "verifications": [
        {
          "item_id": "REQ-001",
          "test_spec_id": "AT-001",
          "kind": "acceptance",
          "status": "READY",
          "basis_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "oracle_ref": "requirements/REQ-001#expected",
          "method_ref": "tests/AT-001#procedure",
          "evidence": { "path": "test-spec.txt", "sha256": "<digest>" }
        }
      ],
      "review": {
        "status": "COMPLETE",
        "reviewer_ref": "authorized-reviewer-reference",
        "source_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "evidence": { "path": "review.txt", "sha256": "<digest>" }
      },
      "open_items": []
    }

For the upstream spec phases, verification status is READY, NOT_READY or REJECTED. READY requires a revision-matched oracle reference, method reference and actual evidence. A review record must be COMPLETE with a reviewer reference, matching revision and evidence; NOT_RUN holds and REJECTED requests rework.

For downstream run phases, verification status is PASS, FAIL, NOT_RUN, BLOCKED or ERROR. PASS and FAIL require revision-matched oracle reference, actual run ID and real evidence. A test definition or a run not performed is never converted into PASS. Review/release authorization remains a separate external gate.

Each verification's item_id must match an approved required item. Multiple distinct test specs can cover the same item; duplicate item/test pairs are invalid. open_items must be present; each item has an ID, boolean material flag and OPEN/RESOLVED status. A material OPEN item causes HOLD.

Evidence has an allowed relative path and a SHA-256 and is checked using the existing quality-gate evidence verifier, including path traversal and symlink rejection. A matching hash proves only that bytes match the **supplied digest**. It does not prove the claimed test ran, the test's assertion was correct, or the reviewer identity was authenticated. Real users must protect the evidence store and digest independently.

## Output contract

The evaluator produces JSON with state, policy_id, scope_id, phase, source_revision, required_item_ids, verified_item_ids, unverified_item_ids and reasons.

- READY_FOR_PHASE_APPROVAL: Exit 0. Required declared verification and evidence are present and mechanically consistent. Human approval is still needed.
- REWORK: Exit 1. An observed FAIL/REJECTED case or rejected review needs correction, provided there is no separate HOLD condition.
- HOLD: Exit 2. Missing, not-run, invalid/stale evidence, unreconciled scope, material open issues or malformed inputs block a decision.

Even in READY_FOR_PHASE_APPROVAL, phase_complete=false, human_approval_required=true, ready_to_merge=false. This is a *readiness* evaluation, never automatic completion or human authority.

## Adoption and limits

1. Freeze the required checks for a single approved change slice and the exact revision.
2. Prepare and review independent test oracles and methods for upstream phases. Collect real results and evidence for downstream phases.
3. Evaluate the corresponding phase; follow the gap/reason report. Retain rejected, failed, blocked and not-run history in the original project records.
4. Pass readiness results to a human decision maker. Do not automatically advance a workflow, merge or deploy.
5. Pilot on one real change before treating a time or quality benefit as demonstrated.

Existing FMW lifecycle remains authoritative for feature knowledge; this standalone evaluator adds no workflow scheduler and no proprietary input format to FMW. The existing code quality gate must still validate real revision-bound checks/reviews where applicable. Further phase kinds, operational/security performance conditions or adapted execution formats require separate, risk-based decisions.
