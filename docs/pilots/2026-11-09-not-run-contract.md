# Pilot 01: Represent unexecuted observations without fabricated evidence

Date: 2026-11-09
Scope: `quality-gate` only. The pilot changes no release, merge, CI permission, or external repository.

## Goal and requirement

**Requirement P01:** A caller must be able to report a required check or independent review as `NOT_RUN` without inventing a revision, run log, hash, or reviewer identity.

**Safety invariant:** Missing/unfinished observations **must evaluate to `HOLD`**, never `READY_FOR_HUMAN_REVIEW`. Completed checks and reviews still need the exact candidate revision and independently protected evidence. A `PASS` without evidence remains invalid/held.

Baseline problem: `quality-gate` previously required `head_sha` and `evidence` for all required checks, including `NOT_RUN`, and required all review provenance for `NOT_RUN`. A caller that had not executed a check could only supply invented placeholders or receive an input error instead of a structured hold decision.

## Single-change workflow

| Stage | Source of truth | What this pilot verifies | Not attempted |
| --- | --- | --- | --- |
| Requirement | This pilot contract and approved PR scope | `P01` and fail-closed invariant | No real customer requirements |
| Feature understanding | [feature-map-workflow](https://github.com/nakashima-yoshua/feature-map-workflow) | Its knowledge/reference ownership boundary is respected | No Feature Map XML change: this is a generic gate contract, not a business feature |
| Design decision | [architecture-decision-system](https://github.com/nakashima-yoshua/architecture-decision-system) | Existing ADS evaluation remains independent; no new decision catalog entry required for this local change | No claim that ADS evaluated or approved this PR |
| Implementation | `src/quality_gate/engine.py` | Optional provenance on unexecuted items; strict provenance on completed items | No changes to public command-line options or approval authority |
| Verification | `tests/test_engine.py`, repository CI | Missing evidence => `HOLD`; stale optional revision => `HOLD`; completed evidence remains mandatory | No external execution adapter, no `cli-test-mcp` test run |
| Readiness | `quality-gate` evaluator + human reviewer | `HOLD` for missing observations, `READY_FOR_HUMAN_REVIEW` only for independently verified complete observations | No automatic approval, merge, deploy, or release |

The currently merged `cli-test-mcp` main branch is a design repository. A test engine is proposed in staged PRs (#2, #3, #4), so this pilot deliberately uses **repository unit tests**, not a hypothetical `cli-test-mcp` run. Their statuses must not be treated as `PASS` unless verified.

## Acceptance checks

1. Required check `NOT_RUN` with only `id` and `status` => `HOLD` + `CHECK_UNAVAILABLE`.
2. Required check `NOT_RUN` with a supplied stale `head_sha` => `HOLD` + `STALE_CHECK`.
3. Independent review `NOT_RUN` with only `status` => `HOLD` + `REVIEW_UNAVAILABLE`.
4. Review `COMPLETE` without provenance => rejected, not accepted.
5. Check `PASS` without evidence => `HOLD` + `CHECK_EVIDENCE_INVALID`.
6. Existing evaluation tests and CI remain green. Confirm this from the actual PR checks after the run; no preset result is asserted here.

When `NOT_RUN`, optional provenance fields are still validated if present. The change adds no fake evidence, trust origin, or user approvals. The top-level assessment still requires the candidate SHA and changed file list, and the gate never authorizes a merge.

## Pilot evidence and decision record

Collect these after actual execution, rather than filling estimated values:

- PR URL, candidate commit SHA, exact changed files.
- CI run URL, conclusion and started/finished timestamps.
- Acceptance-test count and any failures, as reported by CI.
- Independent human review status and material findings, if performed.
- Human active minutes, rework minutes, cost and comparison baseline (if measured).
- Decision: `ACCEPT`, `REWORK`, or `HOLD`, with person/date and rationale.

**Verified CI observation (candidate `045ab8b79a2ce31acaff2c9bc57fd038679ced1a`):** [GitHub Actions run 42609389047](https://github.com/nakashima-yoshua/quality-gate/actions/runs/42609389047), `unit-tests` **success**, 34 unit tests **OK**, and workflow compileall step successful. The five new regression tests are present in the job log. This observation covers repository tests only; it does not attest to external trusted evidence or reviewer independence.

**Still NOT_VERIFIED:** Independent PR review, integrated four-repository execution, time/cost measurements, and human acceptance. CI must be rechecked for the final PR head after subsequent commits.

## Stop/rollback conditions

Stop on green-appearing results with incomplete evidence, regression in completed-record validation, or any implicit merge authorization. Roll back only this PR if these appear; preserve all other repository behavior. Future integration should use trusted CI-derived evidence and SHA-bound independent review, with FMW/ADS references rather than duplicated authoritative data.
