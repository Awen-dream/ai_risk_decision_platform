# Observability and SLO Baseline

The API exposes:

- `GET /admin/metrics`: JSON diagnostics for operators and local debugging.
- `GET /metrics`: Prometheus text exposition for scraping and alerting.
- `GET /admin/runtime`: active observability contract and readiness details.
- `GET /admin/audit-events`: redacted external-tool audit records with bounded filtering.

In shared environments, set `AI_RISK_ADMIN_AUTH_ENABLED=true`; `/admin/*` and
`/metrics` then require the configured admin header.

## Trial-run SLOs

| Signal | Trial-run objective |
| --- | --- |
| API availability | >= 99.5% over 30 days |
| API p95 latency | <= 2 seconds over 5 minutes |
| Agent execution p95 latency | <= 5 seconds over 5 minutes |
| Upstream HTTP p95 latency | <= 1.5 seconds over 5 minutes |
| API 5xx ratio | < 1% over 5 minutes |
| SQLite readiness | Must remain `1` |
| PostgreSQL readiness | Must remain `1` when enabled |

Counters ending in `requests_total` and `executions_total` count started
operations exactly once. Completion and failure counters are separate, so they
can safely be used as SLO numerators without double-counting the denominator.

## Planner and Tool Quality

V2 planner quality metrics are emitted after each agent turn when the response
contains a planner artifact. They are available in both `/admin/metrics` and
Prometheus:

- `agent.planner.plans.total`: total planned turns across copilot,
  investigation, and strategy.
- `agent.planner.plans.by_agent.<agent>`: planned turns per agent.
- `agent.planner.plans.by_backend.<backend>`: rule, OpenAI, or fallback planner
  usage.
- `agent.planner.fallbacks.total`: planner calls that fell back to the rule
  plan.
- `agent.planner.validation_errors.total`: rejected or repaired candidate-plan
  issues, such as missing required tools or unsupported tools.
- `agent.planner.last_selected_step_count.by_agent.<agent>`: last selected
  plan width for the agent.
- `agent.tools.executions.by_status.<status>`: tool execution outcomes across
  success, degraded, and failed traces.

Suggested trial-run guardrails:

| Signal | Trial-run objective |
| --- | --- |
| Planner fallback rate | < 5% over 30 minutes |
| Planner validation error rate | < 2% over 30 minutes |
| Global-plan needs-attention rate | < 5% over 30 minutes |
| Tool failed trace rate | < 1% over 10 minutes |
| Tool degraded trace rate | Investigate any sustained increase |

Planner fallback rate:

```promql
sum(increase(ai_risk_agent_planner_fallbacks_total[30m]))
/
clamp_min(sum(increase(ai_risk_agent_planner_plans_total[30m])), 1)
> 0.05
```

Planner validation error rate:

```promql
sum(increase(ai_risk_agent_planner_validation_errors_total[30m]))
/
clamp_min(sum(increase(ai_risk_agent_planner_plans_total[30m])), 1)
> 0.02
```

Tool failed trace rate:

```promql
sum(increase(ai_risk_agent_tools_executions_by_status_failed_total[10m]))
/
clamp_min(sum(increase(ai_risk_agent_tools_executions_total[10m])), 1)
> 0.01
```

Tool degraded trace rate:

```promql
sum(increase(ai_risk_agent_tools_executions_by_status_degraded_total[10m]))
/
clamp_min(sum(increase(ai_risk_agent_tools_executions_total[10m])), 1)
> 0.05
```

Global-plan needs-attention rate:

```promql
sum(increase(ai_risk_agent_global_plan_quality_needs_attention_total[30m]))
/
clamp_min(sum(increase(ai_risk_agent_global_plan_quality_evaluations_total[30m])), 1)
> 0.05
```

## Prometheus Alert Baseline

Deployable alert rules live in
`config/prometheus/ai-risk-alerts.yml`. The readiness gate verifies that this
file contains the required alert set before a trial run is accepted.

API 5xx ratio:

```promql
sum(rate(ai_risk_http_responses_status_5xx_total[5m]))
/
sum(rate(ai_risk_http_requests_total[5m]))
> 0.01
```

API p95 latency:

```promql
histogram_quantile(
  0.95,
  sum(rate(ai_risk_http_request_duration_seconds_bucket[5m])) by (le)
) > 2
```

Agent p95 latency:

```promql
histogram_quantile(
  0.95,
  sum(rate(ai_risk_agent_execution_duration_seconds_bucket[5m])) by (le)
) > 5
```

Database failure or unhealthy state:

```promql
increase(ai_risk_database_sqlite_transactions_failed_total[5m]) > 0
or
ai_risk_database_sqlite_ready == 0
or
increase(ai_risk_database_postgres_transactions_failed_total[5m]) > 0
or
ai_risk_database_postgres_ready == 0
```

Any circuit remaining open:

```promql
max({__name__=~"ai_risk_upstream_circuit_.*_open"}) > 0
```

Tool-using agents missing auditable intermediate state:

```promql
(
  sum(increase({__name__=~"ai_risk_agent_planner_plans_by_agent_(investigation|strategy|graph)_total"}[30m]))
  -
  sum(increase({__name__=~"ai_risk_agent_intermediate_states_by_agent_(investigation|strategy|graph)_total"}[30m]))
)
/
clamp_min(
  sum(increase({__name__=~"ai_risk_agent_planner_plans_by_agent_(investigation|strategy|graph)_total"}[30m])),
  1
)
> 0.01
```

Evidence gap rate:

```promql
sum(increase(ai_risk_agent_intermediate_states_evidence_gaps_total[30m]))
/
clamp_min(sum(increase(ai_risk_agent_intermediate_states_total[30m])), 1)
> 0.10
```

V3 session-memory reuse can be monitored with:

```promql
sum(increase(ai_risk_agent_memory_session_refs_total[30m]))
```

V3 long-term workflow-case memory reuse can be monitored with:

```promql
sum(increase(ai_risk_agent_memory_long_term_refs_total[30m]))
```

V3 global-plan quality attention rate can be monitored with:

```promql
sum(increase(ai_risk_agent_global_plan_quality_needs_attention_total[30m]))
/
clamp_min(sum(increase(ai_risk_agent_global_plan_quality_evaluations_total[30m])), 1)
```

V3 execution-readiness outcomes can be monitored with:

```promql
sum(increase(ai_risk_agent_execution_readiness_evaluations_total[30m])) by (__name__)
```

V4 root-cause analysis volume and top-confidence can be monitored with:

```promql
sum(increase(ai_risk_agent_root_cause_analyses_total[30m]))
```

```promql
ai_risk_agent_root_cause_last_top_confidence_by_agent_root_cause
```

V4 root-cause quality score can be monitored with:

```promql
ai_risk_agent_root_cause_quality_last_overall_score_by_agent_root_cause
```

V4 root-cause readiness outcomes can be monitored with:

```promql
sum(increase(ai_risk_agent_root_cause_readiness_evaluations_total[30m]))
```

V4e root-cause handoffs also surface through case action-plan gauges such as
`ai_risk_cases_action_plan_queue_strategy_shadow_queue` and
`ai_risk_cases_action_plan_queue_root_cause_review_queue`.

External HTTP audit writes are append-only JSONL records. Audit records retain
request/trace/session correlation, outcome, latency, status, and header names,
but omit payloads and credential values and redact query values and entity IDs.
The local trial-run store must also declare bounded rotation with
`AI_RISK_TOOL_HTTP_AUDIT_MAX_BYTES` and `AI_RISK_TOOL_HTTP_AUDIT_MAX_FILES`.
Enable `AI_RISK_TOOL_HTTP_AUDIT_INTEGRITY_ENABLED` so each retained record can
be checked through `/admin/audit-integrity`.
Enable `AI_RISK_AUDIT_CENTRAL_ENABLED` in shared environments to mirror the
same hash-chained events to a centralized immutable audit sink.
See `docs/upstream-audit.md` for operating guidance.

SQLite remains the local single-instance baseline. Shared or horizontally
scaled environments should use `AI_RISK_SESSION_STORE_BACKEND=postgres` and
`AI_RISK_CASE_STORE_BACKEND=postgres`, with the DSN loaded from a secret file.
Add instance-level labels and cross-instance dashboards before production scale.

## Readiness Gate

Run the gate against an API with admin protection enabled:

```bash
python3 -m validation.readiness \
  --agent-base-url http://127.0.0.1:8000 \
  --admin-token-file /run/secrets/ai-risk-admin-token
```

The gate verifies health, admin endpoint protection, runtime readiness,
admin-token file usage, audit enablement, audit retention bounds,
audit integrity verification, authenticated Prometheus scraping, and the
required alert rule pack.
