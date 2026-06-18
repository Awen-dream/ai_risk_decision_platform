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

Before using real staging credentials, run the local dry-run. It starts the mock
risk service, agent API, and central audit sink, then exercises the same signoff
script with PostgreSQL explicitly skipped:

```bash
make signoff-local
```

The local dry-run is only a harness check. It does not replace real staging
signoff because it does not prove real upstream data, network, auth, or
PostgreSQL connectivity.

```bash
make signoff-staging
```

The script writes reports under:

```text
.data/reports/staging-signoff-<UTC timestamp>/
```

Local dry-run reports use:

```text
.data/reports/local-signoff-<UTC timestamp>/
```

Expected files:

- `postgres-smoke.json`
- `readiness.json`
- `staging-validation.json`
- `signoff-summary.json`
- `signoff-manifest.json`
- `signoff-evidence.json`

To re-check an archived or copied report directory before release signoff:

```bash
make validate-signoff-evidence \
  REPORT_DIR=.data/reports/staging-signoff-<UTC timestamp>
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

- `signoff-summary.json` has `"status": "passed"`.
- `signoff-manifest.json` has SHA256 entries for the required report files.
- `signoff-evidence.json` has `"status": "passed"`.
- `postgres-smoke.json`, `readiness.json`, and `staging-validation.json` are
  archived with the release or staging signoff record.
- `docs/real-risk-service-integration-checklist.md` has the relevant P0 items
  checked or linked to the archived evidence.
- Any skipped check is explicitly accepted by the owner responsible for that
  environment.
