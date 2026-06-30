# Real Staging Signoff Runbook

Use this runbook to produce the P0 signoff evidence for a real staging risk
service. The signoff is not complete until the generated JSON reports are
archived and `docs/real-risk-service-integration-checklist.md` is updated.

## Required inputs

```bash
export RISK_BASE_URL=https://risk-staging.example.com
export AGENT_BASE_URL=https://ai-risk-agent-staging.example.com
export AI_RISK_ADMIN_AUTH_TOKEN_FILE=/run/secrets/ai-risk-admin-token
export AI_RISK_POSTGRES_DSN_FILE=/run/secrets/ai-risk-postgres-dsn
```

For queryable central audit environments, also set:

```bash
export AI_RISK_SIGNOFF_CENTRAL_AUDIT_BASE_URL=https://audit-staging.example.com
export AI_RISK_AUDIT_CENTRAL_AUTH_HEADER=Authorization
export AI_RISK_AUDIT_CENTRAL_AUTH_TOKEN_FILE=/run/secrets/ai-risk-audit-token
```

For release acceptance evidence, bind the signoff package to the release,
change, owner, and approver:

```bash
export AI_RISK_SIGNOFF_REQUIRE_RELEASE_METADATA=true
export AI_RISK_SIGNOFF_ENVIRONMENT=staging
export AI_RISK_SIGNOFF_RELEASE_ID=risk-agent-2026.06.20
export AI_RISK_SIGNOFF_CHANGE_ID=CHG-12345
export AI_RISK_SIGNOFF_OWNER=risk-platform
export AI_RISK_SIGNOFF_APPROVER=risk-ops
```

By default, PostgreSQL signoff is required. If the staging environment is
intentionally single-instance SQLite, set:

```bash
export AI_RISK_SIGNOFF_REQUIRE_POSTGRES=false
```

If central audit query verification is mandatory for the environment, set:

```bash
export AI_RISK_SIGNOFF_REQUIRE_CENTRAL_AUDIT=true
```

## Run signoff

Before using real staging credentials, run the CI signoff gate. It runs the
unit test suite, the offline planner golden-set evaluation, then the local
signoff with release metadata enforcement enabled and writes a CI sidecar
summary next to the signoff archive:

```bash
make ci-signoff
```

The CI gate writes reports under:

```text
.data/reports/ci-signoff-<UTC timestamp>/
```

The GitHub Actions template in `.github/workflows/ci-signoff.yml` runs the same
gate on pull requests, pushes to `main`, and manual dispatches. It uploads the
CI report directory as an artifact even when the gate fails, so failed runs still
retain `ci-signoff-summary.json` for diagnosis.

The planner evaluation report is written as `planner-eval.json` in the CI
report directory. It is a local demo-runtime quality gate, so it complements
but does not replace the real staging readiness and contract checks.
For `make ci-signoff`, planner evaluation is required signoff evidence: the
manifest and archive include `planner-eval.json`, and `signoff-evidence.json`
requires the V2 intermediate-state, V3 global-planning, and V4 root-cause
quality metrics to pass:

- `intermediate_state_coverage_rate == 1.0`
- `tool_reason_coverage_rate == 1.0`
- `evidence_gap_accuracy == 1.0`
- `global_planning_coverage_rate == 1.0`

For V3 copilot cases, `global_planning_coverage_rate` requires
`global_plan_quality.version == "v3d"` and `overall_score >= 0.75`, so the
signoff evidence covers the global plan, evidence graph, working memory, quality
score, and `execution_readiness.version == "v3f"` execution gate together.
The default planner golden set also includes a V4a `root_cause` case that must
rank root-cause hypotheses from metric, dashboard, SQL, and rule evidence.

To compare planner quality against a previous CI report, set:

```bash
export AI_RISK_PLANNER_EVAL_BASELINE_FILE=.data/reports/previous/planner-eval.json
export AI_RISK_PLANNER_EVAL_MAX_ALLOWED_REGRESSION=0.01
```

For a faster local harness check, run the local dry-run. It starts the mock risk
service, agent API, and central audit sink, then exercises the same signoff
script with PostgreSQL explicitly skipped:

```bash
make signoff-local
```

The CI gate and local dry-run do not replace real staging signoff because they
do not prove real upstream data, network, auth, or PostgreSQL connectivity.

```bash
make signoff-staging
```

If preflight or downstream validation fails, the script still writes a failed
signoff package whenever possible. Archive the failed package as troubleshooting
evidence; do not treat it as a release signoff.

The script writes reports under:

```text
.data/reports/staging-signoff-<UTC timestamp>/
```

Local dry-run reports use:

```text
.data/reports/local-signoff-<UTC timestamp>/
```

Expected files:

- `signoff-preflight.json`
- `postgres-smoke.json`
- `readiness.json`
- `staging-validation.json`
- `signoff-summary.json`
- `signoff-manifest.json`
- `signoff-evidence.json`
- `signoff-archive.tar.gz`
- `signoff-archive.sha256`
- `planner-eval.json` for `make ci-signoff` runs only
- `ci-signoff-summary.json` for `make ci-signoff` runs only

To re-check an archived or copied report directory before release signoff:

```bash
make validate-signoff-evidence \
  REPORT_DIR=.data/reports/staging-signoff-<UTC timestamp>
```

To require planner evaluation evidence when validating a copied CI signoff
directory:

```bash
make validate-signoff-evidence \
  REPORT_DIR=.data/reports/ci-signoff-<UTC timestamp> \
  SIGNOFF_EVIDENCE_ARGS="--require-planner-eval"
```

To create or re-create the distributable archive for a copied report directory:

```bash
make archive-signoff \
  REPORT_DIR=.data/reports/staging-signoff-<UTC timestamp>
```

To verify an existing archive and checksum pair:

```bash
make verify-signoff-archive \
  REPORT_DIR=.data/reports/staging-signoff-<UTC timestamp>
```

If the receiving system only has the archive and checksum files, use archive-only
verification:

```bash
make verify-signoff-archive-file \
  SIGNOFF_ARCHIVE_ARGS="--archive signoff-archive.tar.gz --checksum signoff-archive.sha256"
```

For intentionally SQLite-only environments, the owner must explicitly accept the
PostgreSQL skip:

```bash
make validate-signoff-evidence \
  REPORT_DIR=.data/reports/staging-signoff-<UTC timestamp> \
  SIGNOFF_EVIDENCE_ARGS="--allow-postgres-skipped"
```

## What the signoff checks

- PostgreSQL persistence: readiness, session create/append, case creation
  idempotency, status update, list/count queries.
- Readiness: admin protection, token-file usage, audit settings, runtime
  readiness, Prometheus scrapeability, alert rule pack.
- Staging contract: real risk-service endpoint schemas, Phase 1 runtime
  contract, one functional request for every Phase 1 agent, upstream audit,
  audit hash-chain integrity, Prometheus scrapeability.
- Central audit, when queryable: mirrored tamper-evident and redacted external
  HTTP audit events.

## Done criteria

- `signoff-preflight.json` has `"status": "passed"`.
- `signoff-summary.json` has `"status": "passed"`.
- `signoff-summary.json` includes complete `release` metadata when the package
  is used as release acceptance evidence.
- `signoff-manifest.json` has SHA256 entries for the required report files.
- `signoff-evidence.json` has `"status": "passed"`.
- `signoff-archive.sha256` matches `signoff-archive.tar.gz`.
- `make verify-signoff-archive REPORT_DIR=...` has `"status": "passed"`.
- Archive-only verification has `"status": "passed"` when the report directory
  is not available to the receiving system.
- `postgres-smoke.json`, `readiness.json`, and `staging-validation.json` are
  archived with the release or staging signoff record.
- `docs/real-risk-service-integration-checklist.md` has the relevant P0 items
  checked or linked to the archived evidence.
- Any skipped check is explicitly accepted by the owner responsible for that
  environment.
- Failed signoff packages are retained for incident/troubleshooting evidence but
  are not accepted as release signoff artifacts.
