from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Iterator


LOGGER_NAME = "ai_risk_decision_platform"
REQUEST_ID_HEADER = "X-Request-Id"
TRACE_ID_HEADER = "X-Trace-Id"

_context: ContextVar[dict[str, Any]] = ContextVar("observability_context", default={})


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
    payload = {"event": event, **get_context(), **fields}
    logging.getLogger(LOGGER_NAME).info(
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )
