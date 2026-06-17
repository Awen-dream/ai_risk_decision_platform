from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from services.observability import get_context


REDACTED = "[REDACTED]"
VERSION_SEGMENT_PATTERN = re.compile(r"^v\d+$", re.IGNORECASE)


class AuditLog(Protocol):
    def record(self, event: dict[str, Any]) -> None:
        ...

    def list_events(
        self,
        *,
        limit: int = 100,
        outcome: str | None = None,
        upstream_client: str | None = None,
        request_id: str | None = None,
    ) -> list[dict[str, Any]]:
        ...


class NoopAuditLog:
    def record(self, event: dict[str, Any]) -> None:
        return None

    def list_events(
        self,
        *,
        limit: int = 100,
        outcome: str | None = None,
        upstream_client: str | None = None,
        request_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return []


class JsonLinesAuditLog:
    """Append-only, single-instance audit log for external HTTP calls."""

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = 10 * 1024 * 1024,
        max_files: int = 5,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be greater than or equal to 1")
        if max_files < 1:
            raise ValueError("max_files must be greater than or equal to 1")
        self.path = path
        self.max_bytes = max_bytes
        self.max_files = max_files
        self._lock = Lock()

    def record(self, event: dict[str, Any]) -> None:
        rendered = json.dumps(event, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed(len(rendered.encode("utf-8")) + 1)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(rendered + "\n")

    def list_events(
        self,
        *,
        limit: int = 100,
        outcome: str | None = None,
        upstream_client: str | None = None,
        request_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            lines: list[str] = []
            for path in self._retained_paths_oldest_first():
                if path.exists():
                    lines.extend(path.read_text(encoding="utf-8").splitlines())
        events = [_parse_event(line) for line in lines if line.strip()]
        filtered = [
            event
            for event in events
            if event is not None
            and (outcome is None or event.get("outcome") == outcome)
            and (upstream_client is None or event.get("upstream_client") == upstream_client)
            and (request_id is None or event.get("request_id") == request_id)
        ]
        return filtered[-limit:][::-1]

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if not self.path.exists():
            return
        if self.path.stat().st_size == 0:
            return
        if self.path.stat().st_size + incoming_bytes <= self.max_bytes:
            return
        if self.max_files == 1:
            self.path.unlink(missing_ok=True)
            return
        oldest = self._rotated_path(self.max_files - 1)
        oldest.unlink(missing_ok=True)
        for index in range(self.max_files - 2, 0, -1):
            source = self._rotated_path(index)
            if source.exists():
                source.replace(self._rotated_path(index + 1))
        self.path.replace(self._rotated_path(1))

    def _retained_paths_oldest_first(self) -> list[Path]:
        rotated = [
            self._rotated_path(index)
            for index in range(self.max_files - 1, 0, -1)
        ]
        return [*rotated, self.path]

    def _rotated_path(self, index: int) -> Path:
        return self.path.with_name(f"{self.path.name}.{index}")


def build_upstream_audit_event(
    *,
    upstream_client: str,
    method: str,
    url: str,
    outcome: str,
    attempt: int | None,
    total_attempts: int | None,
    duration_seconds: float | None = None,
    status_code: int | None = None,
    error_type: str | None = None,
    request_header_names: list[str] | None = None,
) -> dict[str, Any]:
    context = get_context()
    return {
        "event_id": uuid4().hex,
        "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event_type": "upstream_http_request",
        "upstream_client": upstream_client,
        "method": method,
        "target_url": redact_url(url),
        "outcome": outcome,
        "status_code": status_code,
        "attempt": attempt,
        "total_attempts": total_attempts,
        "duration_ms": (
            round(duration_seconds * 1000, 3)
            if duration_seconds is not None
            else None
        ),
        "error_type": error_type,
        "request_id": context.get("request_id"),
        "trace_id": context.get("trace_id"),
        "session_id": context.get("session_id"),
        "agent_name": context.get("agent_name"),
        "request_header_names": sorted(request_header_names or []),
    }


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    path_segments = [
        _redact_path_segment(segment)
        for segment in parts.path.split("/")
    ]
    redacted_query = urlencode(
        [(name, REDACTED) for name, _ in parse_qsl(parts.query, keep_blank_values=True)]
    )
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc.rsplit("@", 1)[-1],
            "/".join(path_segments),
            redacted_query,
            "",
        )
    )


def _redact_path_segment(segment: str) -> str:
    if VERSION_SEGMENT_PATTERN.fullmatch(segment):
        return segment
    if any(character.isdigit() for character in segment):
        return REDACTED
    return segment


def _parse_event(line: str) -> dict[str, Any] | None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None
