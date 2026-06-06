from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from threading import Lock
from typing import Any, Iterator


LOGGER_NAME = "ai_risk_decision_platform"
REQUEST_ID_HEADER = "X-Request-Id"
TRACE_ID_HEADER = "X-Trace-Id"

_context: ContextVar[dict[str, Any]] = ContextVar("observability_context", default={})
_metrics_lock = Lock()
_metrics: dict[str, int] = {}


def get_context() -> dict[str, Any]:
    return dict(_context.get())


def current_headers() -> dict[str, str]:
    context = get_context()
    headers: dict[str, str] = {}
    request_id = context.get("request_id")
    trace_id = context.get("trace_id")
    if request_id:
        headers[REQUEST_ID_HEADER] = str(request_id)
    if trace_id:
        headers[TRACE_ID_HEADER] = str(trace_id)
    return headers


@contextmanager
def bind_context(**values: Any) -> Iterator[None]:
    current = get_context()
    updated = {**current, **{key: value for key, value in values.items() if value is not None}}
    token: Token[dict[str, Any]] = _context.set(updated)
    try:
        yield
    finally:
        _context.reset(token)


def emit_event(event: str, **fields: Any) -> None:
    _increment_metrics(event, fields)
    payload = {"event": event, **get_context(), **fields}
    logging.getLogger(LOGGER_NAME).info(
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def get_metrics_snapshot() -> dict[str, int]:
    with _metrics_lock:
        return dict(sorted(_metrics.items()))


def _increment_metrics(event: str, fields: dict[str, Any]) -> None:
    metric_names = [f"events.{event}", "events.total"]
    agent_name = get_context().get("agent_name") or fields.get("requested_agent")
    if event.startswith("http_request_"):
        metric_names.append("http.requests.total")
        metric_names.append(f"http.requests.{event.removeprefix('http_request_')}")
    if event.startswith("upstream_http_request_"):
        metric_names.append("upstream.requests.total")
        metric_names.append(
            f"upstream.requests.{event.removeprefix('upstream_http_request_')}"
        )
    if event.startswith("agent_execution_"):
        metric_names.append("agent.executions.total")
        metric_names.append(f"agent.executions.{event.removeprefix('agent_execution_')}")
        if agent_name:
            metric_names.append(f"agent.executions.by_agent.{agent_name}")
    if event == "session_created":
        metric_names.append("sessions.created")
    if event == "agent_request_failed":
        metric_names.append("agent.requests.failed")
        if agent_name:
            metric_names.append(f"agent.requests.failed.by_agent.{agent_name}")
    with _metrics_lock:
        for name in metric_names:
            _metrics[name] = _metrics.get(name, 0) + 1
