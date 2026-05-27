# Real Risk Service Integration Checklist

Use this checklist when replacing the local mock risk service with a real external service.

## 1. Service contract

- [ ] Confirm the real service exposes metric snapshot lookup.
- [ ] Confirm the real service exposes historical case lookup.
- [ ] Confirm the real service exposes order profile lookup.
- [ ] Confirm 404 behavior for missing resources.
- [ ] Confirm response payload fields cover the current investigation agent needs.

## 2. Endpoint mapping

- [ ] Fill `AI_RISK_TOOL_HTTP_BASE_URL`
- [ ] Fill `AI_RISK_TOOL_HTTP_METRIC_PATH`
- [ ] Fill `AI_RISK_TOOL_HTTP_CASE_PATH`
- [ ] Fill `AI_RISK_TOOL_HTTP_ORDER_PATH_TEMPLATE`
- [ ] Fill `AI_RISK_TOOL_HTTP_COUNTRY_PARAM`
- [ ] Fill `AI_RISK_TOOL_HTTP_CHANNEL_PARAM`

## 3. Authentication

- [ ] Decide auth mode: `none`, `bearer`, or `api_key`
- [ ] Fill `AI_RISK_TOOL_HTTP_AUTH_MODE`
- [ ] Fill `AI_RISK_TOOL_HTTP_AUTH_HEADER`
- [ ] Fill `AI_RISK_TOOL_HTTP_AUTH_TOKEN`
- [ ] Verify the runtime shows the expected auth mode in `GET /admin/runtime`

## 4. Timeouts and networking

- [ ] Fill `AI_RISK_TOOL_HTTP_TIMEOUT_SEC`
- [ ] Verify the API host can reach the external service
- [ ] Verify error behavior for timeout / 4xx / 5xx responses

## 5. Functional verification

- [ ] Run `python3 cli.py runtime`
- [ ] Run `python3 cli.py agents`
- [ ] Run one `knowledge` query
- [ ] Run one `investigation` query with `country/channel`
- [ ] Run one `investigation` query with `order_id`
- [ ] Check session history through `python3 cli.py session <session_id>`

## 6. Knowledge verification

- [ ] Confirm `AI_RISK_KNOWLEDGE_BACKEND=file`
- [ ] Confirm knowledge documents are loaded from the expected directory
- [ ] Run `python3 cli.py reload-knowledge`
- [ ] Verify `GET /admin/runtime` shows the expected indexed document count

## 7. Production hardening follow-ups

- [ ] Add structured request IDs / trace IDs between agent API and risk service
- [ ] Add secret management instead of raw env token injection
- [ ] Add retry / circuit-breaker policy if the external service is unstable
- [ ] Add audit logging for external tool requests
- [ ] Add integration tests against a staging endpoint
