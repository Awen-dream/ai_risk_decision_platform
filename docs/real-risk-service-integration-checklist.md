# Real Risk Service Integration Checklist

Use this checklist when replacing the local mock risk service with a real external service.

## 1. Service contract

- [ ] Send `docs/risk-service-integration-form.md` to the service owner
- [ ] Confirm the real service exposes metric snapshot lookup.
- [ ] Confirm the real service exposes historical case lookup.
- [ ] Confirm the real service exposes order profile lookup.
- [ ] Confirm the real service exposes strategy profile lookup.
- [ ] Confirm the real service exposes strategy simulation lookup.
- [ ] Confirm the real service exposes graph relation lookup.
- [ ] Confirm 404 behavior for missing resources.
- [ ] Confirm response payload fields cover investigation, strategy, graph, and copilot needs.

## 2. Endpoint mapping

- [ ] Fill `AI_RISK_TOOL_HTTP_BASE_URL`
- [ ] Fill `AI_RISK_TOOL_HTTP_METRIC_PATH`
- [ ] Fill `AI_RISK_TOOL_HTTP_CASE_PATH`
- [ ] Fill `AI_RISK_TOOL_HTTP_ORDER_PATH_TEMPLATE`
- [ ] Fill `AI_RISK_TOOL_HTTP_STRATEGY_PROFILE_PATH_TEMPLATE`
- [ ] Fill `AI_RISK_TOOL_HTTP_STRATEGY_SIMULATION_PATH_TEMPLATE`
- [ ] Fill `AI_RISK_TOOL_HTTP_GRAPH_RELATION_PATH_TEMPLATE`
- [ ] Fill `AI_RISK_TOOL_HTTP_COUNTRY_PARAM`
- [ ] Fill `AI_RISK_TOOL_HTTP_CHANNEL_PARAM`

## 3. Authentication

- [ ] Decide auth mode: `none`, `bearer`, or `api_key`
- [ ] Fill `AI_RISK_TOOL_HTTP_AUTH_MODE`
- [ ] Fill `AI_RISK_TOOL_HTTP_AUTH_HEADER`
- [ ] Fill `AI_RISK_TOOL_HTTP_AUTH_TOKEN_FILE` through a mounted secret
- [ ] Avoid raw `AI_RISK_TOOL_HTTP_AUTH_TOKEN` outside local development
- [ ] Verify `GET /admin/runtime` shows the expected auth mode, auth header, and timeout

## 3.5. Admin endpoint protection

- [ ] Set `AI_RISK_ADMIN_AUTH_ENABLED=true`
- [ ] Fill `AI_RISK_ADMIN_AUTH_HEADER`
- [ ] Fill `AI_RISK_ADMIN_AUTH_TOKEN_FILE` through a mounted secret
- [ ] Verify `/admin/runtime`, `/admin/metrics`, `/admin/audit-events`, and `/metrics` reject missing tokens
- [ ] Verify CLI and Prometheus/staging checks pass with the admin token header
- [ ] Run `python3 -m validation.readiness --agent-base-url ... --admin-token-file ...`

## 4. Timeouts and networking

- [ ] Fill `AI_RISK_TOOL_HTTP_TIMEOUT_SEC`
- [ ] Tune `AI_RISK_TOOL_HTTP_RETRY_ATTEMPTS` and `AI_RISK_TOOL_HTTP_RETRY_BACKOFF_SEC`
- [ ] Tune `AI_RISK_TOOL_HTTP_CIRCUIT_BREAKER_FAILURE_THRESHOLD` and `AI_RISK_TOOL_HTTP_CIRCUIT_BREAKER_RESET_SEC`
- [ ] Verify the API host can reach the external service
- [ ] Verify error and retry behavior for timeout / 4xx / 5xx responses
- [ ] Verify `GET /admin/runtime` shows the expected resilience policy
- [ ] Confirm `AI_RISK_TOOL_HTTP_AUDIT_ENABLED=true` and set the audit path
- [ ] Set `AI_RISK_TOOL_HTTP_AUDIT_MAX_BYTES` and `AI_RISK_TOOL_HTTP_AUDIT_MAX_FILES`
- [ ] Set `AI_RISK_TOOL_HTTP_AUDIT_INTEGRITY_ENABLED=true`
- [ ] Configure `AI_RISK_AUDIT_CENTRAL_ENABLED=true`, `AI_RISK_AUDIT_CENTRAL_URL`, and central audit token file for shared environments

## 5. Functional verification

- [ ] Run the full signoff flow in `docs/staging-signoff-runbook.md`
- [ ] Run local dry-run with `make signoff-local` before using staging secrets
- [ ] Verify `.data/reports/staging-signoff-*/signoff-evidence.json` is passed
- [ ] Archive `.data/reports/staging-signoff-*/*.json`
- [ ] Run staging contract validation with `make validate-staging RISK_BASE_URL=... AGENT_BASE_URL=...`
- [ ] Archive the generated staging validation JSON report
- [ ] Run `make recovery-drill` and archive the recovery report
- [ ] Run `python3 cli.py runtime`
- [ ] Confirm session and case backends are `postgres` with DSN from file for shared or horizontally scaled environments
- [ ] Run `python3 -m validation.postgres_smoke --dsn-file ...`
- [ ] Restart the API and verify session/case records remain available
- [ ] Confirm Prometheus can scrape `GET /metrics` with the admin token header when protection is enabled
- [ ] Query `GET /admin/audit-events` and confirm credentials and entity IDs are redacted
- [ ] Confirm `/admin/runtime` reports bounded audit rotation and retention settings
- [ ] Query `GET /admin/audit-integrity` and confirm status is not `failed`
- [ ] Confirm `/admin/runtime` reports central audit sink configuration without exposing secrets
- [ ] Validate the SLO and alert baseline in `docs/observability-slo.md`
- [ ] Confirm `config/prometheus/ai-risk-alerts.yml` is loaded by Prometheus
- [ ] Verify `supported_capabilities` is exactly `knowledge`, `investigation`, `strategy`, `graph`, `copilot`
- [ ] Verify `capability_contract` and `http_endpoint_contract` match the agreed Phase 1 surface
- [ ] Run `python3 cli.py agents`
- [ ] Run one `knowledge` query
- [ ] Run one `investigation` query with `country/channel`
- [ ] Run one `investigation` query with `order_id`
- [ ] Run one `strategy` query
- [ ] Run one `graph` query
- [ ] Run one `copilot` query
- [ ] Check session history through `python3 cli.py session <session_id>`

## 6. Knowledge verification

- [ ] Confirm `AI_RISK_KNOWLEDGE_BACKEND=file`
- [ ] Confirm knowledge documents are loaded from the expected directory
- [ ] Run `python3 cli.py reload-knowledge`
- [ ] Verify `GET /admin/runtime` shows the expected indexed document count

## 7. Production hardening follow-ups

- [x] Add structured request IDs / trace IDs between agent API and risk service
- [x] Add token-file based secret loading for external and admin tokens
- [x] Add admin protection for `/admin/*` and `/metrics`
- [x] Add retry / circuit-breaker policy for transient upstream failures
- [x] Add transactional single-instance persistence for sessions and cases
- [x] Add Prometheus metrics and latency/state instrumentation
- [x] Add deployable Prometheus alert rules and readiness gate
- [x] Add PostgreSQL session/case store baseline before horizontal scaling
- [x] Add centralized audit sink support with local fallback
- [x] Add append-only, redacted audit logging for external tool requests
- [x] Add reusable contract validation for a staging endpoint
- [x] Add automated retry, circuit-breaker, and recovery drill
- [ ] Run and sign off validation against the real staging endpoint
