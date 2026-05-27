# Risk Service Integration Form

Use this form with the external risk service owner when replacing the local mock service.

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

## 7. Error and compatibility notes

| Item | Value |
|---|---|
| 4xx error schema | |
| 5xx error schema | |
| Empty result handling | |
| Encoding / locale notes | |
| Any field mapping differences | |

## 8. Config mapping back to this project

Fill these values after the service owner confirms the contract:

```bash
AI_RISK_TOOL_HTTP_BASE_URL=
AI_RISK_TOOL_HTTP_TIMEOUT_SEC=
AI_RISK_TOOL_HTTP_AUTH_MODE=
AI_RISK_TOOL_HTTP_AUTH_HEADER=
AI_RISK_TOOL_HTTP_AUTH_TOKEN=
AI_RISK_TOOL_HTTP_METRIC_PATH=
AI_RISK_TOOL_HTTP_CASE_PATH=
AI_RISK_TOOL_HTTP_ORDER_PATH_TEMPLATE=
AI_RISK_TOOL_HTTP_COUNTRY_PARAM=
AI_RISK_TOOL_HTTP_CHANNEL_PARAM=
```
