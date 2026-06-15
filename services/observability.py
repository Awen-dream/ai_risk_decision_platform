from __future__ import annotations

import json
import logging
import math
import re
from contextlib import contextmanager
from contextvars import ContextVar, Token
from threading import Lock
from typing import Any, Iterable, Iterator


LOGGER_NAME = "ai_risk_decision_platform"
REQUEST_ID_HEADER = "X-Request-Id"
TRACE_ID_HEADER = "X-Trace-Id"

_context: ContextVar[dict[str, Any]] = ContextVar("observability_context", default={})
_metrics_lock = Lock()
_counters: dict[str, int] = {}
_gauges: dict[str, float] = {}
_histograms: dict[str, dict[str, Any]] = {}

DEFAULT_DURATION_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


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
        return dict(sorted(_counters.items()))


def get_gauges_snapshot() -> dict[str, float]:
    with _metrics_lock:
        return dict(sorted(_gauges.items()))


def get_histograms_snapshot() -> dict[str, dict[str, Any]]:
    with _metrics_lock:
        return {
            name: {
                "count": value["count"],
                "sum": value["sum"],
                "buckets": dict(value["buckets"]),
            }
            for name, value in sorted(_histograms.items())
        }


def increment_counter(name: str, amount: int = 1) -> None:
    with _metrics_lock:
        _counters[name] = _counters.get(name, 0) + amount


def set_gauge(name: str, value: float) -> None:
    with _metrics_lock:
        _gauges[name] = value


def add_gauge(name: str, amount: float) -> None:
    with _metrics_lock:
        _gauges[name] = _gauges.get(name, 0.0) + amount


def observe_histogram(
    name: str,
    value: float,
    *,
    buckets: Iterable[float] = DEFAULT_DURATION_BUCKETS,
) -> None:
    bucket_bounds = tuple(buckets)
    with _metrics_lock:
        histogram = _histograms.setdefault(
            name,
            {
                "count": 0,
                "sum": 0.0,
                "buckets": {bound: 0 for bound in bucket_bounds},
            },
        )
        histogram["count"] += 1
        histogram["sum"] += value
        for bound in bucket_bounds:
            if value <= bound:
                histogram["buckets"][bound] += 1


def render_prometheus(
    *,
    extra_gauges: dict[str, float] | None = None,
) -> str:
    counters = get_metrics_snapshot()
    gauges = {**get_gauges_snapshot(), **(extra_gauges or {})}
    histograms = get_histograms_snapshot()
    lines: list[str] = []
    for name, value in counters.items():
        metric_name = _prometheus_name(name, counter=True)
        lines.extend((f"# TYPE {metric_name} counter", f"{metric_name} {value}"))
    for name, value in gauges.items():
        metric_name = _prometheus_name(name)
        lines.extend((f"# TYPE {metric_name} gauge", f"{metric_name} {_format_number(value)}"))
    for name, histogram in histograms.items():
        metric_name = _prometheus_name(name)
        lines.append(f"# TYPE {metric_name} histogram")
        for bound, count in histogram["buckets"].items():
            lines.append(
                f'{metric_name}_bucket{{le="{_format_number(bound)}"}} {count}'
            )
        lines.append(f'{metric_name}_bucket{{le="+Inf"}} {histogram["count"]}')
        lines.append(f'{metric_name}_sum {_format_number(histogram["sum"])}')
        lines.append(f'{metric_name}_count {histogram["count"]}')
    return "\n".join(lines) + "\n"


def _increment_metrics(event: str, fields: dict[str, Any]) -> None:
    metric_names = [f"events.{event}", "events.total"]
    agent_name = get_context().get("agent_name") or fields.get("requested_agent")
    if event.startswith("http_request_"):
        metric_names.append(f"http.requests.{event.removeprefix('http_request_')}")
        if event == "http_request_started":
            metric_names.append("http.requests.total")
        status_code = fields.get("status_code")
        if isinstance(status_code, int):
            metric_names.append(f"http.responses.status_{status_code // 100}xx")
    if event.startswith("upstream_http_request_"):
        metric_names.append(
            f"upstream.requests.{event.removeprefix('upstream_http_request_')}"
        )
        if event == "upstream_http_request_started":
            metric_names.append("upstream.requests.total")
    if event.startswith("agent_execution_"):
        metric_names.append(f"agent.executions.{event.removeprefix('agent_execution_')}")
        if event == "agent_execution_started":
            metric_names.append("agent.executions.total")
        if agent_name and event == "agent_execution_started":
            metric_names.append(f"agent.executions.by_agent.{agent_name}")
    if event == "session_created":
        metric_names.append("sessions.created")
    if event == "case_created":
        metric_names.append("cases.created")
    if event == "case_status_updated":
        metric_names.append("cases.status_updated")
    if event == "agent_request_failed":
        metric_names.append("agent.requests.failed")
        if agent_name:
            metric_names.append(f"agent.requests.failed.by_agent.{agent_name}")
    with _metrics_lock:
        for name in metric_names:
            _counters[name] = _counters.get(name, 0) + 1
    duration_seconds = fields.get("duration_seconds")
    if isinstance(duration_seconds, (int, float)):
        histogram_name = _duration_histogram_name(event)
        if histogram_name:
            observe_histogram(histogram_name, float(duration_seconds))


def _duration_histogram_name(event: str) -> str | None:
    if event in {"http_request_completed", "http_request_failed"}:
        return "http.request.duration_seconds"
    if event in {"agent_execution_completed", "agent_execution_failed"}:
        return "agent.execution.duration_seconds"
    if event in {"upstream_http_request_completed", "upstream_http_request_failed"}:
        return "upstream.http.request.duration_seconds"
    return None


def _prometheus_name(name: str, *, counter: bool = False) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_:]", "_", name)
    normalized = re.sub(r"_+", "_", normalized).strip("_").lower()
    metric_name = f"ai_risk_{normalized}"
    if counter and not metric_name.endswith("_total"):
        metric_name = f"{metric_name}_total"
    return metric_name


def _format_number(value: float) -> str:
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    return f"{value:.12g}"
