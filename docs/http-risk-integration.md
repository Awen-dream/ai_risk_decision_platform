# HTTP Risk Integration

This project supports replacing the local mock risk service with a real external HTTP service.

## Phase 1 capability target

Phase 1 must keep the full agent surface available after the HTTP switch:

- `knowledge`: file-backed knowledge retrieval
- `investigation`: metric snapshot, case lookup, order profile
- `strategy`: strategy profile, strategy simulation, graph relation
- `graph`: graph relation
- `copilot`: orchestrates investigation + strategy + graph

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

4. `GET /strategy-profiles/{strategy_id}`

5. `GET /strategy-simulations/{strategy_id}`

6. `GET /graph-relations/{entity_id}`

The runtime declaration in `GET /admin/runtime` should match this exact surface through:

- `supported_capabilities`
- `capability_contract`
- `http_endpoint_contract`

## Environment variables

Start by copying the example file:

```bash
cp .env.example .env.local
```

If the external service already has a fixed auth style, you can also start from:

```bash
cp .env.local.bearer.example .env.local
```

or:

```bash
cp .env.local.api-key.example .env.local
```

Use these variables to point the agent API to a real risk service:

```bash
export AI_RISK_KNOWLEDGE_BACKEND=file
export AI_RISK_TOOL_BACKEND=http
export AI_RISK_SESSION_STORE_BACKEND=sqlite
export AI_RISK_CASE_STORE_BACKEND=sqlite
export AI_RISK_DATABASE_PATH=.data/platform.db
export AI_RISK_TOOL_HTTP_BASE_URL=https://risk-api.example.com
export AI_RISK_TOOL_HTTP_TIMEOUT_SEC=5
export AI_RISK_TOOL_HTTP_RETRY_ATTEMPTS=2
export AI_RISK_TOOL_HTTP_RETRY_BACKOFF_SEC=0.1
export AI_RISK_TOOL_HTTP_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
export AI_RISK_TOOL_HTTP_CIRCUIT_BREAKER_RESET_SEC=30
export AI_RISK_TOOL_HTTP_AUDIT_ENABLED=true
export AI_RISK_TOOL_HTTP_AUDIT_PATH=.data/upstream-audit.jsonl
export AI_RISK_TOOL_HTTP_AUDIT_MAX_BYTES=10485760
export AI_RISK_TOOL_HTTP_AUDIT_MAX_FILES=5
export AI_RISK_TOOL_HTTP_AUDIT_INTEGRITY_ENABLED=true
export AI_RISK_AUDIT_CENTRAL_ENABLED=false
export AI_RISK_AUDIT_CENTRAL_URL=
export AI_RISK_AUDIT_CENTRAL_AUTH_TOKEN_FILE=
```

Retries use exponential backoff and apply only to network errors, timeouts, HTTP
408/425/429, and 5xx responses. After the configured number of consecutive
failed requests, the per-client circuit breaker opens and allows one half-open
probe after the reset interval.

The SQLite settings provide the transactional single-instance persistence
baseline described in `docs/sqlite-persistence.md`. For shared or horizontally
scaled environments, switch both stores to PostgreSQL and provide
`AI_RISK_POSTGRES_DSN_FILE`.

If the external service uses custom endpoint paths or query parameter names:

```bash
export AI_RISK_TOOL_HTTP_METRIC_PATH=/v2/metrics
export AI_RISK_TOOL_HTTP_CASE_PATH=/v2/cases/search
export AI_RISK_TOOL_HTTP_ORDER_PATH_TEMPLATE=/v2/orders/{order_id}/profile
export AI_RISK_TOOL_HTTP_STRATEGY_PROFILE_PATH_TEMPLATE=/v2/strategies/{strategy_id}
export AI_RISK_TOOL_HTTP_STRATEGY_SIMULATION_PATH_TEMPLATE=/v2/strategies/{strategy_id}/simulation
export AI_RISK_TOOL_HTTP_GRAPH_RELATION_PATH_TEMPLATE=/v2/graph/{entity_id}
export AI_RISK_TOOL_HTTP_COUNTRY_PARAM=market
export AI_RISK_TOOL_HTTP_CHANNEL_PARAM=payment_channel
```

If the external service requires authentication:

Bearer token:

```bash
export AI_RISK_TOOL_HTTP_AUTH_MODE=bearer
export AI_RISK_TOOL_HTTP_AUTH_HEADER=Authorization
export AI_RISK_TOOL_HTTP_AUTH_TOKEN_FILE=/run/secrets/risk-api-bearer-token
```

API key header:

```bash
export AI_RISK_TOOL_HTTP_AUTH_MODE=api_key
export AI_RISK_TOOL_HTTP_AUTH_HEADER=X-API-Key
export AI_RISK_TOOL_HTTP_AUTH_TOKEN_FILE=/run/secrets/risk-api-key
```

Raw `AI_RISK_TOOL_HTTP_AUTH_TOKEN` is still supported for local testing, but
shared environments should mount the value through `AI_RISK_TOOL_HTTP_AUTH_TOKEN_FILE`.

Protect operator endpoints in shared environments:

```bash
export AI_RISK_ADMIN_AUTH_ENABLED=true
export AI_RISK_ADMIN_AUTH_HEADER=X-Admin-Token
export AI_RISK_ADMIN_AUTH_TOKEN_FILE=/run/secrets/ai-risk-admin-token
```

## Recommended rollout flow

1. Copy the closest env template into `.env.local`
2. Fill real base URL, endpoint paths, parameter names, and token-file paths
3. Start the API with `make run-api-http`
4. Verify config with `python3 cli.py --admin-token-file /run/secrets/ai-risk-admin-token runtime`
5. Check `supported_capabilities`, `capability_contract`, and `http_endpoint_contract`
6. Run one `knowledge` query and one query for each of `investigation`, `strategy`, `graph`, `copilot`
7. Check `/admin/audit-events` and `/admin/audit-integrity` for redacted, correlated, tamper-evident external-call records
8. For environments with queryable central audit, run `validation.staging` with `--central-audit-base-url ...`
9. If using PostgreSQL, run `python3 -m validation.postgres_smoke --dsn-file ...`
10. Run `python3 -m validation.readiness --agent-base-url ... --admin-token-file ...`
11. Use `docs/real-risk-service-integration-checklist.md` to complete the final validation

## Local verification

Use these commands to inspect the running configuration:

```bash
make run-api-http
python3 cli.py runtime
python3 cli.py agents
python3 cli.py ask knowledge "营销套利案件的标准排查 SOP 是什么？"
python3 cli.py ask investigation "为什么巴西信用卡支付失败率从昨晚开始突然升高？" --country BR --channel credit_card
python3 cli.py ask strategy "请评估策略 STRAT-001 是否应该调整阈值" --strategy-id STRAT-001
python3 cli.py ask graph "请分析用户 U10001 是否属于团伙网络" --entity-id U10001
python3 cli.py ask copilot "请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议" --order-id O10001 --strategy-id STRAT-001 --entity-id U10001
```

If `AI_RISK_ADMIN_AUTH_ENABLED=true`, add
`--admin-token-file /run/secrets/ai-risk-admin-token` to `runtime` and
`reload-knowledge` CLI calls.

The `GET /admin/runtime` endpoint also shows the active HTTP paths, auth mode,
timeout, retry, circuit-breaker and audit policy, parameter mapping, registered
tools, and the Phase 1 capability declaration.

For rollout readiness, use:

```bash
docs/real-risk-service-integration-checklist.md
```
