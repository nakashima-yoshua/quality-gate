# Optional OKF knowledge lint evidence gate

This is an **advisory, read-only** compatibility adapter for the
`architecture-decision-system` (ADS) OKF v0.2 linter. It validates a
host-sealed lint report against the exact candidate Git revision and the
current bundle bytes; it does **not** parse YAML, decide design patterns,
certify business claims, approve a PR, or merge.

## Trusted workflow

1. The host checks out an **exact Git commit**, controls the working bundle,
   and runs `ads knowledge lint --bundle knowledge/bundle --json-report
   --head-sha <head-commit-sha>` in the ADS environment. Capture stdout as
   `lint-report.json`. Failed lint produces no PASS report.
2. A trusted host (outside candidate/model write access) records the SHA-256
   of that report and the `bundle_sha256` digest, and independently anchors
   the exact commit SHA, e.g., in a protected CI job/manifest.
3. In the same immutable checkout, call:

```sh
PYTHONPATH=src python -m quality_gate.knowledge_cli \
  --report lint-report.json \
  --bundle knowledge/bundle \
  --expected-report-sha256 "<host-controlled-sha256>" \
  --expected-bundle-sha256 "<host-controlled-bundle-sha256>" \
  --expected-head-sha "<host-controlled-40-hex-commit>"
```

Exit `0` means `READY_FOR_HUMAN_REVIEW`, **not** that the knowledge is true
or the PR may merge. Exit `2` means `HOLD`. Every result has
`ready_to_merge: false`, `human_approval_required: true`.
The existing quality-gate code readiness and phase readiness CLIs are unchanged.

## Report schema and SHA algorithm

The ADS JSON report has exactly these keys:
`schema_version=1.0`, `producer=ads-okf-lint`, `state=PASS`,
`head_sha`, `bundle_sha256`, `concepts` (positive integer), and `pages`
(integer greater than concepts). A signed/anchored hash, not the JSON
claim alone, is the trust source.

For the bundle digest: traverse all regular files (including non-Markdown
references) under the bundle in lexicographic relative-path order. For each
file, feed SHA-256 with `4-byte big-endian path-length`, UTF-8 POSIX relative
path, `8-byte big-endian content-length`, then exact file bytes. Symlinks
are rejected. The adapter caps bundle size at 64 MiB.

## Trust and limitations

A report, digest, or Git SHA supplied **by the same untrusted agent** as the
candidate is not valid independent evidence. Protect anchors and source
files using CI permissions, immutable artifacts and least-privilege ACLs.
Neither a linter PASS nor this adapter checks whether generated knowledge
is correct, contradicts another source, or has a human review. Distinguish
OKF draft from approved canonical XML/FMW knowledge. Retry from a trusted
checkout after any file or commit change. The gate itself performs no
subprocess, network access, or repository mutation.
