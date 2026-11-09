# quality-gate

An **offline, deterministic, fail-closed readiness gate** for AI-assisted code changes. Python 3.10+, standard library only. This project does **not** execute tests, invoke an LLM, approve a pull request, merge, or deploy.

The gate evaluates *the exact candidate revision* against a host-controlled policy, test-run evidence, and an independent-review record. A successful result is **`READY_FOR_HUMAN_REVIEW`**, never authorization to merge.

## Optional verification-driven phase readiness

A separate [phase gate](docs/phase-gates.md) evaluates whether the required verification specifications (requirements/design) or real test results (implementation/integration/acceptance) cover an approved change slice. Run `python -m quality_gate.phase_cli` with its own policy/assessment/evidence inputs. This is an **advisory readiness check**, not phase completion, PR merge authorization, or a replacement for the code readiness gate above.

## Ownership and boundaries

| Component | Owner | Boundary |
| --- | --- | --- |
| [feature-map-workflow](https://github.com/nakashima-yoshua/feature-map-workflow) | Requirements, business rules, change scope and evidence references | No duplicate feature registry or XML schema |
| [cli-test-mcp](https://github.com/nakashima-yoshua/cli-test-mcp) | Test definition, execution and individual attempt evidence | Its MCP/engine is still designed, not a working dependency |
| **quality-gate** | Risk classification, mandatory-check evaluation, evidence-file hash verification, review dispositions and decision report | Never infers test PASS, human approval or permission from an AI response |
| Host CI + human | Repository Rulesets, identity, permission, approval, merge/release | Not implemented by this tool |

## Quick start

```sh
PYTHONPATH=src python -m quality_gate.cli \
  --policy examples/policy.json \
  --assessment examples/assessment.json \
  --evidence-root examples/evidence

PYTHONPATH=src python -m unittest discover -s tests -v
```

To pin the policy to an independently obtained digest, add `--expected-policy-sha256 <64-hex-digest>`; **production automation must provide this from a host-controlled value**. A digest submitted by an AI is not an approval or authorization.

Exit status: `0` = `READY_FOR_HUMAN_REVIEW`, `1` = `REWORK`, `2` = `HOLD` or malformed/untrusted input. JSON report to stdout. CI must additionally enforce real required checks, SHA-bound human approval, and protected merge permissions.

### Input contracts (v1)

- `policy`: `schema_version`, `policy_id`, `required_checks` mapping `LOW/MEDIUM/HIGH` to check IDs, `max_review_passes`, and `high_risk_paths` (repository-relative prefixes). The policy is supplied from an operator-controlled location, **not the candidate worktree**.
- `assessment`: `schema_version`, `candidate` (`repository`, `head_sha`, `changed_files`), `risk` (`minimum_tier`, `unknown_material`), `checks` (`id`, `status`, `head_sha`, `evidence`), `review` (`status`, `reviewed_sha`, distinct `implementation_session` and `review_session`, `passes`, `evidence`, `findings`).
- Each `evidence` is `{ "path": "relative/file", "sha256": "..." }` and refers to an existing regular file under the trusted `--evidence-root`. Symlinks, traversal, missing files and changed content are rejected. The gate **checks bytes against a supplied hash**, not the authenticity of the supplied hash. Protect the catalog/digest separately (see [trust model](docs/architecture.md)).
- Check `status`: `PASS`, `FAIL`, `NOT_RUN`, `BLOCKED`, `ERROR`; the gate accepts no generic `success` marker. `review.status`: `COMPLETE`, `NOT_RUN`, `ERROR`. Findings categories: `IMPORTANT`, `NIT`, `PRE_EXISTING`, `UNVERIFIED`; dispositions: `OPEN`, `FIXED`, `DISMISSED`, `HUMAN_DECISION`. An `IMPORTANT` finding cannot be dismissed without a concrete verification reason; an unresolved finding blocks advancement.

For a pilot, the example uses *synthetic evidence* to exercise the contract; it is **not** a real project run or proof of production readiness.

## Decision rules

1. **HOLD** for untrusted/invalid evidence, missing required checks, stale SHA, unavailable independent review, unknown material risk, CRITICAL risk, a human decision, or unresolved `UNVERIFIED` findings.
2. **REWORK** for an observed failing required check or open `IMPORTANT` finding, unless a HOLD condition also applies. At the configured review-pass cap, unresolved `IMPORTANT` findings become HOLD.
3. **READY_FOR_HUMAN_REVIEW** only after all required checks PASS with matching revision and verifiable evidence, independent review is complete on that revision, and no blocking findings remain.

Risk is computed from **all** changed file paths, not only an AI-supplied tier. Documentation-only changes can be LOW; any other ordinary change is at least MEDIUM; configured sensitive paths are HIGH; a risk hint can only elevate. `unknown_material=true` and `CRITICAL` always HOLD. Checks are selected by the resulting tier, so HIGH cannot inherit a weaker MEDIUM test set.

## Integrating an actual workflow

1. Host freezes candidate SHA, changed-file paths, approved policy digest and expected checks. Keep the policy and trusted evidence store outside model write permission.
2. Run deterministic CI/tests via the target system / `cli-test-mcp` once available. Copy **real native** results into a protected evidence store, independently seal them, and create the assessment JSON from that trusted execution adapter. Never copy `PASS` from an overall run to individual checks.
3. Run a *separate, read-only* Codex/AI review session using [REVIEW.md](REVIEW.md) and a narrow Feature Map/diff context; independently triage the findings. Populate its structured, revision-bound review record, seal and anchor the evidence.
4. Evaluate with the gate. Post the compact report to the PR for **human** judgment. Require GitHub Rulesets and authenticated approval on the exact SHA. A new commit invalidates prior check/review evidence; re-run the affected requirements.
5. Start with one representative non-production PR. Compare detected defects, false alarms, human time, and failure modes. Add parallel specialists only if measured benefit justifies their cost.

Further design, threat model, mapped vendor learnings, tests and roadmap: [docs/architecture.md](docs/architecture.md).
