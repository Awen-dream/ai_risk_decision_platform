# Observability and SLO Baseline

The API exposes:

- `GET /admin/metrics`: JSON diagnostics for operators and local debugging.
- `GET /metrics`: Prometheus text exposition for scraping and alerting.
- `GET /admin/runtime`: active observability contract and readiness details.

## Trial-run SLOs

| Signal | Trial-run objective |
| --- | --- |
| API availability | >= 99.5% over 30 days |
| API p95 latency | <= 2 seconds over 5 minutes |
| Agent execution p95 latency | <= 5 seconds over 5 minutes |
| Upstream HTTP p95 latency | <= 1.5 seconds over 5 minutes |
| API 5xx ratio | < 1% over 5 minutes |
| SQLite readiness | Must remain `1` |

Counters ending in `requests_total` and `executions_total` count started
operations exactly once. Completion and failure counters are separate, so they
can safely be used as SLO numerators without double-counting the denominator.

## Prometheus Alert Baseline

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
```

Any circuit remaining open:

```promql
max({__name__=~"ai_risk_upstream_circuit_.*_open"}) > 0
```

SQLite remains the single-instance persistence baseline. Before horizontal
scaling, move persistence to PostgreSQL and add instance-level labels and
cross-instance dashboards.
