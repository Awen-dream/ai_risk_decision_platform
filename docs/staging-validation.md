# Staging Validation and Recovery Drill

The validation suite turns the Phase 1 contract and resilience requirements
into repeatable checks. It produces a machine-readable JSON report and exits
non-zero when any check fails.

## Validate a real staging environment

Start the agent API configured for the real staging risk service, then run:

```bash
make validate-staging \
  RISK_BASE_URL=https://risk-staging.example.com \
  AGENT_BASE_URL=http://127.0.0.1:8000
```

If the agent API protects `/admin/*` and `/metrics`, pass the admin token:

```bash
python3 -m validation.staging \
  --risk-base-url https://risk-staging.example.com \
  --agent-base-url http://127.0.0.1:8000 \
  --agent-admin-token-file /run/secrets/ai-risk-admin-token
```

The suite validates:

- Health and the six required risk-service endpoint schemas.
- Exact Phase 1 capabilities, registered tools, and runtime readiness.
- One functional request for every Phase 1 agent.
- Prometheus scrape availability.

If staging uses PostgreSQL persistence, run the persistence smoke gate before
the contract suite:

```bash
python3 -m validation.postgres_smoke \
  --dsn-file /run/secrets/ai-risk-postgres-dsn \
  --output .data/reports/postgres-smoke.json
```

To save the report explicitly:

```bash
python3 -m validation.staging \
  --risk-base-url https://risk-staging.example.com \
  --agent-base-url http://127.0.0.1:8000 \
  --output .data/reports/staging-validation.json
```

## Run the local recovery drill

```bash
make recovery-drill
```

The script starts an isolated local stack on ports `18080` and `18090`, enables
admin protection for the agent API, starts a mock central audit sink on port
`18091`, enables fault injection only for the mock risk service, and verifies:

1. A transient 503 recovers through retry.
2. Repeated exhausted requests open the circuit.
3. Clearing the fault and waiting for reset permits a half-open probe and
   closes the circuit.
4. Retry failures, circuit rejection, and recovery success remain available as
   redacted audit evidence.
5. Audit logging remains bounded by configured local rotation and retention.
6. Retained audit records expose a verifiable hash chain.
7. Central audit sink and PostgreSQL readiness are declared through runtime
   configuration when enabled.
8. The mock central audit sink receives tamper-evident, redacted records during
   both the contract run and the recovery drill.

The default report is written to `.data/reports/recovery-drill.json`.
The readiness gate report is written to `.data/reports/readiness-drill.json`.
The drill refuses to start if either isolated port is already in use. Override
them with `AI_RISK_DRILL_API_PORT`, `AI_RISK_DRILL_RISK_PORT`, and
`AI_RISK_DRILL_AUDIT_SINK_PORT` when needed.

`AI_RISK_RISK_SERVICE_FAULT_INJECTION_ENABLED` defaults to `false`. Never enable
the mock fault-control endpoints on a shared or real risk service.
