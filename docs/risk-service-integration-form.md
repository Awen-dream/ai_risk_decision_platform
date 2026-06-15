# Risk Service Integration Form

Use this form with the external risk service owner when replacing the local mock service.

Phase 1 target surface:

- `knowledge`: knowledge retrieval stays file-backed in this project
- `investigation`: metric snapshot + case record + order profile
- `strategy`: strategy profile + strategy simulation + graph relation
- `graph`: graph relation
- `copilot`: composes investigation + strategy + graph

## 1. Service owner

| Item | Value |
|---|---|
| Team name | |
| Owner name | |
| Owner contact | |
| Service name | |
| Environment | |

## 2. Base access

| Item | Value | Example |
|---|---|---|
| Base URL | | `https://risk-api.example.com` |
| Network restriction | | office/VPN/internal only |
| Timeout recommendation | | `5` |
| Expected rate limit | | |

## 3. Authentication

| Item | Value | Notes |
|---|---|---|
| Auth mode | | `none` / `bearer` / `api_key` |
| Auth header name | | `Authorization` / `X-API-Key` |
| Token / key delivery method | | vault / env / temp token |
| Token rotation rule | | |

## 4. Metric snapshot endpoint

| Item | Value | Example |
|---|---|---|
| Endpoint path | | `/metric-snapshots` |
| Country param name | | `country` |
| Channel param name | | `channel` |
| Sample request | | `GET /metric-snapshots?country=BR&channel=credit_card` |
| 404 behavior | | |

Expected response fields:

| Field | Available? | Notes |
|---|---|---|
| `country` | | |
| `channel` | | |
| `metric_name` | | |
| `anomaly_started_at` | | |
| `current_value` | | |
| `baseline_value` | | |
| `recent_change` | | |
| `suspected_driver` | | |

## 5. Case record endpoint

| Item | Value | Example |
|---|---|---|
| Endpoint path | | `/case-records` |
| Country param name | | `country` |
| Channel param name | | `channel` |
| Sample request | | `GET /case-records?country=BR&channel=credit_card` |
| 404 behavior | | |

Expected response fields:

| Field | Available? | Notes |
|---|---|---|
| `case_id` | | |
| `country` | | |
| `channel` | | |
| `title` | | |

## 6. Order profile endpoint

| Item | Value | Example |
|---|---|---|
| Endpoint path template | | `/order-profiles/{order_id}` |
| Sample request | | `GET /order-profiles/O10001` |
| 404 behavior | | |

Expected response fields:

| Field | Available? | Notes |
|---|---|---|
| `order_id` | | |
| `country` | | |
| `channel` | | |
| `recent_attempts` | | |
| `triggered_rules` | | |
| `risk_labels` | | |
| `recommended_action` | | |

## 7. Strategy profile endpoint

| Item | Value | Example |
|---|---|---|
| Endpoint path template | | `/strategy-profiles/{strategy_id}` |
| Sample request | | `GET /strategy-profiles/STRAT-001` |
| 404 behavior | | |

Expected response fields:

| Field | Available? | Notes |
|---|---|---|
| `strategy_id` | | |
| `name` | | |
| `country` | | |
| `channel` | | |
| `status` | | |
| `current_threshold` | | |
| `hit_rate` | | |
| `risk_capture_rate` | | |
| `false_positive_rate` | | |
| `recent_issue` | | |
| `top_impacted_entities` | | |

## 8. Strategy simulation endpoint

| Item | Value | Example |
|---|---|---|
| Endpoint path template | | `/strategy-simulations/{strategy_id}` |
| Sample request | | `GET /strategy-simulations/STRAT-001` |
| 404 behavior | | |

Expected response fields:

| Field | Available? | Notes |
|---|---|---|
| `strategy_id` | | |
| `recommended_threshold` | | |
| `delta_intercepts` | | |
| `delta_false_positives` | | |
| `estimated_risk_reduction` | | |
| `estimated_revenue_impact` | | |
| `simulation_window` | | |
| `recommendation_reason` | | |

## 9. Graph relation endpoint

| Item | Value | Example |
|---|---|---|
| Endpoint path template | | `/graph-relations/{entity_id}` |
| Sample request | | `GET /graph-relations/U10001` |
| 404 behavior | | |

Expected response fields:

| Field | Available? | Notes |
|---|---|---|
| `entity_id` | | |
| `entity_type` | | |
| `risk_level` | | |
| `shared_devices` | | |
| `shared_ips` | | |
| `linked_accounts` | | |
| `linked_orders` | | |
| `community_size` | | |
| `key_path` | | |
| `risk_reason` | | |

## 10. Error and compatibility notes

| Item | Value |
|---|---|
| 4xx error schema | |
| 5xx error schema | |
| Empty result handling | |
| Encoding / locale notes | |
| Any field mapping differences | |

## 11. Config mapping back to this project

Fill these values after the service owner confirms the contract:

```bash
AI_RISK_TOOL_HTTP_BASE_URL=
AI_RISK_TOOL_HTTP_TIMEOUT_SEC=
AI_RISK_SESSION_STORE_BACKEND=sqlite
AI_RISK_CASE_STORE_BACKEND=sqlite
AI_RISK_DATABASE_PATH=
AI_RISK_TOOL_HTTP_RETRY_ATTEMPTS=
AI_RISK_TOOL_HTTP_RETRY_BACKOFF_SEC=
AI_RISK_TOOL_HTTP_CIRCUIT_BREAKER_FAILURE_THRESHOLD=
AI_RISK_TOOL_HTTP_CIRCUIT_BREAKER_RESET_SEC=
AI_RISK_TOOL_HTTP_AUDIT_ENABLED=true
AI_RISK_TOOL_HTTP_AUDIT_PATH=
AI_RISK_TOOL_HTTP_AUTH_MODE=
AI_RISK_TOOL_HTTP_AUTH_HEADER=
AI_RISK_TOOL_HTTP_AUTH_TOKEN=
AI_RISK_TOOL_HTTP_METRIC_PATH=
AI_RISK_TOOL_HTTP_CASE_PATH=
AI_RISK_TOOL_HTTP_ORDER_PATH_TEMPLATE=
AI_RISK_TOOL_HTTP_STRATEGY_PROFILE_PATH_TEMPLATE=
AI_RISK_TOOL_HTTP_STRATEGY_SIMULATION_PATH_TEMPLATE=
AI_RISK_TOOL_HTTP_GRAPH_RELATION_PATH_TEMPLATE=
AI_RISK_TOOL_HTTP_COUNTRY_PARAM=
AI_RISK_TOOL_HTTP_CHANNEL_PARAM=
```
