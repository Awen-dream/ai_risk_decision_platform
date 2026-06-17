# External HTTP Audit Trail

Every external HTTP tool attempt writes one append-only JSONL audit record.
Auditing defaults to enabled and is configured with:

```bash
AI_RISK_TOOL_HTTP_AUDIT_ENABLED=true
AI_RISK_TOOL_HTTP_AUDIT_PATH=.data/upstream-audit.jsonl
AI_RISK_TOOL_HTTP_AUDIT_MAX_BYTES=10485760
AI_RISK_TOOL_HTTP_AUDIT_MAX_FILES=5
AI_RISK_TOOL_HTTP_AUDIT_INTEGRITY_ENABLED=true
AI_RISK_AUDIT_CENTRAL_ENABLED=false
AI_RISK_AUDIT_CENTRAL_URL=
AI_RISK_AUDIT_CENTRAL_AUTH_TOKEN_FILE=
```

Query recent records through:

```bash
curl "http://127.0.0.1:8000/admin/audit-events?limit=50"
curl "http://127.0.0.1:8000/admin/audit-events?outcome=http_error"
curl "http://127.0.0.1:8000/admin/audit-events?request_id=<request-id>"
curl "http://127.0.0.1:8000/admin/audit-integrity"
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

When `AI_RISK_TOOL_HTTP_AUDIT_INTEGRITY_ENABLED=true`, each new record includes
`audit_previous_hash` and `audit_hash`. `GET /admin/audit-integrity` verifies
the retained hash chain and reports `passed`, `partial`, `legacy`, `empty`, or
`failed`. A `failed` status means at least one retained record was modified or
the hash link between retained records is broken.

When `AI_RISK_AUDIT_CENTRAL_ENABLED=true`, the API writes the local JSONL record
first, then mirrors the same tamper-evident event to
`AI_RISK_AUDIT_CENTRAL_URL`. Central sink failures do not break user traffic,
but they emit the existing audit failure metric and alert.

The JSONL store is the local recovery baseline. Shared environments should ship
these events to a centralized immutable audit store with access control,
retention policy, integrity protection, and alerting on audit-write failures.
