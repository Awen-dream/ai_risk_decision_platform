# External HTTP Audit Trail

Every external HTTP tool attempt writes one append-only JSONL audit record.
Auditing defaults to enabled and is configured with:

```bash
AI_RISK_TOOL_HTTP_AUDIT_ENABLED=true
AI_RISK_TOOL_HTTP_AUDIT_PATH=.data/upstream-audit.jsonl
```

Query recent records through:

```bash
curl "http://127.0.0.1:8000/admin/audit-events?limit=50"
curl "http://127.0.0.1:8000/admin/audit-events?outcome=http_error"
curl "http://127.0.0.1:8000/admin/audit-events?request_id=<request-id>"
```

Records include correlation IDs, upstream client, result, status, latency,
attempt number, and request header names. They deliberately exclude request and
response payloads, header values, exception text, URL query values, and entity
IDs embedded in paths.

The JSONL store is the single-instance trial-run baseline. Before horizontal
scaling, ship these events to a centralized immutable audit store with access
control, retention policy, integrity protection, and alerting on audit-write
failures.
