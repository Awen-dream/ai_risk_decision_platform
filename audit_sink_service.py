from __future__ import annotations

import os
from datetime import datetime, timezone
from secrets import compare_digest
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse


class InMemoryAuditSink:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._lock = Lock()

    def append(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._events.append(
                {
                    **event,
                    "central_received_at": (
                        datetime.now(timezone.utc)
                        .isoformat(timespec="microseconds")
                        .replace("+00:00", "Z")
                    ),
                }
            )

    def list_events(self, *, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events[-limit:][::-1])


def create_audit_sink_app() -> FastAPI:
    sink = InMemoryAuditSink()
    auth_header = os.getenv("AI_RISK_AUDIT_SINK_AUTH_HEADER", "X-Audit-Token")
    auth_token = os.getenv("AI_RISK_AUDIT_SINK_AUTH_TOKEN", "")
    fastapi_app = FastAPI(
        title="AI Risk Mock Central Audit Sink",
        version="0.1.0",
        description="Local central audit receiver for recovery drills.",
    )

    @fastapi_app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if request.url.path != "/healthz" and auth_token:
            provided = request.headers.get(auth_header)
            if provided is None or not compare_digest(provided, auth_token):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Audit sink authentication required"},
                )
        return await call_next(request)

    @fastapi_app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @fastapi_app.post("/audit-events")
    async def ingest_event(request: Request) -> dict[str, str]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Audit event must be a JSON object")
        sink.append(payload)
        return {"status": "accepted"}

    @fastapi_app.get("/admin/events")
    def list_events(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
        return {
            "events": sink.list_events(limit=limit),
        }

    return fastapi_app


audit_sink_app = create_audit_sink_app()
