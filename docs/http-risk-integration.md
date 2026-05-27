# HTTP Risk Integration

This project supports replacing the local mock risk service with a real external HTTP service.

## Required endpoints

The agent API expects the risk service to provide:

1. `GET /metric-snapshots`
   Query params:
   - `country`
   - `channel`

2. `GET /case-records`
   Query params:
   - `country`
   - `channel`

3. `GET /order-profiles/{order_id}`

## Environment variables

Start by copying the example file:

```bash
cp .env.example .env.local
```

Use these variables to point the agent API to a real risk service:

```bash
export AI_RISK_KNOWLEDGE_BACKEND=file
export AI_RISK_TOOL_BACKEND=http
export AI_RISK_TOOL_HTTP_BASE_URL=https://risk-api.example.com
export AI_RISK_TOOL_HTTP_TIMEOUT_SEC=5
```

If the external service uses custom endpoint paths or query parameter names:

```bash
export AI_RISK_TOOL_HTTP_METRIC_PATH=/v2/metrics
export AI_RISK_TOOL_HTTP_CASE_PATH=/v2/cases/search
export AI_RISK_TOOL_HTTP_ORDER_PATH_TEMPLATE=/v2/orders/{order_id}/profile
export AI_RISK_TOOL_HTTP_COUNTRY_PARAM=market
export AI_RISK_TOOL_HTTP_CHANNEL_PARAM=payment_channel
```

If the external service requires authentication:

Bearer token:

```bash
export AI_RISK_TOOL_HTTP_AUTH_MODE=bearer
export AI_RISK_TOOL_HTTP_AUTH_TOKEN=your-token
export AI_RISK_TOOL_HTTP_AUTH_HEADER=Authorization
```

API key header:

```bash
export AI_RISK_TOOL_HTTP_AUTH_MODE=api_key
export AI_RISK_TOOL_HTTP_AUTH_TOKEN=your-api-key
export AI_RISK_TOOL_HTTP_AUTH_HEADER=X-API-Key
```

## Local verification

Use these commands to inspect the running configuration:

```bash
make run-api-http
python3 cli.py runtime
python3 cli.py agents
python3 cli.py ask knowledge "营销套利案件的标准排查 SOP 是什么？"
```

The `GET /admin/runtime` endpoint also shows the active HTTP paths, auth mode, and registered tools.

For rollout readiness, use:

```bash
docs/real-risk-service-integration-checklist.md
```
