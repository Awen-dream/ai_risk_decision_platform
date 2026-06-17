# External HTTP Audit Trail

Every external HTTP tool attempt writes one append-only JSONL audit record.
Auditing defaults to enabled and is configured with:

```bash
AI_RISK_TOOL_HTTP_AUDIT_ENABLED=true
AI_RISK_TOOL_HTTP_AUDIT_PATH=.data/upstream-audit.jsonl
AI_RISK_TOOL_HTTP_AUDIT_MAX_BYTES=10485760
AI_RISK_TOOL_HTTP_AUDIT_MAX_FILES=5
```

Query recent records through:

```bash
curl "http://127.0.0.1:8000/admin/audit-events?limit=50"
curl "http://127.0.0.1:8000/admin/audit-events?outcome=http_error"
curl "http://127.0.0.1:8000/admin/audit-events?request_id=<request-id>"
```

When admin protection is enabled, include the configured admin header:

```bash
curl -H "X-Admin-Token: $(cat /run/secrets/ai-risk-admin-token)" \
  "http://127.0.0.1:8000/admin/audit-events?limit=50"
```

Records include correlation IDs, upstream client, result, status, latency,
attempt number, and request header names. They deliberately exclude request and
response payloads, header values, exception text, URL query values, and entity
IDs embedded in paths.

The local JSONL store rotates before a write would exceed
`AI_RISK_TOOL_HTTP_AUDIT_MAX_BYTES`. Retained files use `.1`, `.2`, and so on;
`GET /admin/audit-events` reads across the retained files newest-first.

The JSONL store is the single-instance trial-run baseline. Before horizontal
scaling, ship these events to a centralized immutable audit store with access
control, retention policy, integrity protection, and alerting on audit-write
failures.
