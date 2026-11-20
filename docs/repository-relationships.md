# Related repositories / 関連リポジトリ

**quality-gate** の責務と他リポジトリとの関係を示します。This is a navigation/ownership map, not a dependency manifest. Links alone do **not** imply an implemented API integration or permission to execute, merge, or deploy.

| Repository | Relationship | State and boundary |
| --- | --- | --- |
| [system-understanding-architecture](https://github.com/nakashima-yoshua/system-understanding-architecture) | System scope and invariants can inform host-controlled readiness policies | Guidance only; no shared authoritative policy |
| [feature-map-workflow](https://github.com/nakashima-yoshua/feature-map-workflow) | Feature-level knowledge identifies affected guarantees and test references | Not executable proof or automatic approval |
| [cli-test-mcp](https://github.com/nakashima-yoshua/cli-test-mcp) | Test outcomes may be supplied as separately sealed, revision-matched evidence | No direct runner invocation; host adapter required |
| [architecture-decision-system](https://github.com/nakashima-yoshua/architecture-decision-system) | Optional ADS knowledge-lint evidence adapter validates supplied report/digests | Implemented optional adapter, not certification of business truth |

## Source-of-truth boundaries / 正本の境界

- [system-understanding-architecture](https://github.com/nakashima-yoshua/system-understanding-architecture): system-understanding reference and onboarding templates. The adopting project owns real system facts and permissions.
- [feature-map-workflow](https://github.com/nakashima-yoshua/feature-map-workflow): durable per-feature knowledge and pointers, not actual source/test execution.
- [cli-test-mcp](https://github.com/nakashima-yoshua/cli-test-mcp): deterministic native test execution and evidence where approved; a declared case is not a PASS.
- [quality-gate](https://github.com/nakashima-yoshua/quality-gate): deterministic readiness checks; human and host retain review, merge and release authority.
- [architecture-decision-system](https://github.com/nakashima-yoshua/architecture-decision-system): versioned architecture decisions/rules and optional knowledge validation; patterns do not grant permissions.

Update relationships when a connection is implemented or retired. Mark **implemented**, **optional/prototype**, or **planned** accurately. Avoid duplicating another repository's records or introducing mandatory runtime dependencies.