from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from services.observability import emit_event, get_context


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

    def verify_integrity(self) -> dict[str, Any]:
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

    def verify_integrity(self) -> dict[str, Any]:
        return {
            "status": "disabled",
            "integrity_enabled": False,
            "total_records": 0,
            "verified_records": 0,
            "legacy_records": 0,
            "invalid_records": 0,
            "broken_links": 0,
            "first_event_hash": None,
            "last_event_hash": None,
        }


class CompositeAuditLog:
    """Writes audit records locally first, then mirrors them to external sinks."""

    def __init__(self, primary: AuditLog, mirrors: list[AuditLog]) -> None:
        self._primary = primary
        self._mirrors = mirrors

    def record(self, event: dict[str, Any]) -> None:
        if hasattr(self._primary, "record_and_return"):
            written_event = self._primary.record_and_return(event)  # type: ignore[attr-defined]
        else:
            self._primary.record(event)
            written_event = dict(event)
        for mirror in self._mirrors:
            try:
                mirror.record(dict(written_event))
            except Exception as exc:
                emit_event(
                    "upstream_http_audit_failed",
                    upstream_client=written_event.get("upstream_client"),
                    error_type=type(exc).__name__,
                    audit_sink=mirror.__class__.__name__,
                )

    def list_events(
        self,
        *,
        limit: int = 100,
        outcome: str | None = None,
        upstream_client: str | None = None,
        request_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._primary.list_events(
            limit=limit,
            outcome=outcome,
            upstream_client=upstream_client,
            request_id=request_id,
        )

    def verify_integrity(self) -> dict[str, Any]:
        return self._primary.verify_integrity()


@dataclass(frozen=True)
class HttpAuditSink:
    """Sends tamper-evident audit records to a centralized audit endpoint."""

    url: str
    headers: dict[str, str] | None = None
    timeout_sec: float = 3.0

    def record(self, event: dict[str, Any]) -> None:
        payload = json.dumps(event, ensure_ascii=False, sort_keys=True).encode("utf-8")
        request = Request(
            self.url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                **(self.headers or {}),
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_sec) as response:
                status = getattr(response, "status", 200)
                if status >= 400:
                    raise RuntimeError(f"central audit sink returned HTTP {status}")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError("central audit sink write failed") from exc

    def list_events(
        self,
        *,
        limit: int = 100,
        outcome: str | None = None,
        upstream_client: str | None = None,
        request_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return []

    def verify_integrity(self) -> dict[str, Any]:
        return {
            "status": "external",
            "integrity_enabled": True,
            "total_records": 0,
            "verified_records": 0,
            "legacy_records": 0,
            "invalid_records": 0,
            "broken_links": 0,
            "first_event_hash": None,
            "last_event_hash": None,
        }


class JsonLinesAuditLog:
    """Append-only, single-instance audit log for external HTTP calls."""

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = 10 * 1024 * 1024,
        max_files: int = 5,
        integrity_enabled: bool = True,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be greater than or equal to 1")
        if max_files < 1:
            raise ValueError("max_files must be greater than or equal to 1")
        self.path = path
        self.max_bytes = max_bytes
        self.max_files = max_files
        self.integrity_enabled = integrity_enabled
        self._lock = Lock()

    def record(self, event: dict[str, Any]) -> None:
        self.record_and_return(event)

    def record_and_return(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            event_to_write = dict(event)
            if self.integrity_enabled:
                event_to_write["audit_previous_hash"] = self._last_audit_hash()
                event_to_write["audit_hash"] = _compute_audit_hash(event_to_write)
            rendered = json.dumps(event_to_write, ensure_ascii=False, sort_keys=True)
            self._rotate_if_needed(len(rendered.encode("utf-8")) + 1)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(rendered + "\n")
            return event_to_write

    def list_events(
        self,
        *,
        limit: int = 100,
        outcome: str | None = None,
        upstream_client: str | None = None,
        request_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            events = self._events_oldest_first()
        filtered = [
            event
            for event in events
            if event is not None
            and (outcome is None or event.get("outcome") == outcome)
            and (upstream_client is None or event.get("upstream_client") == upstream_client)
            and (request_id is None or event.get("request_id") == request_id)
        ]
        return filtered[-limit:][::-1]

    def verify_integrity(self) -> dict[str, Any]:
        with self._lock:
            events = self._events_oldest_first()
        total_records = len(events)
        verified_records = 0
        legacy_records = 0
        invalid_records = 0
        broken_links = 0
        previous_hash: str | None = None
        first_event_hash: str | None = None
        last_event_hash: str | None = None
        for event in events:
            event_hash = event.get("audit_hash")
            previous_event_hash = event.get("audit_previous_hash")
            if not isinstance(event_hash, str) or not isinstance(previous_event_hash, str):
                legacy_records += 1
                previous_hash = None
                continue
            expected_hash = _compute_audit_hash(event)
            if event_hash != expected_hash:
                invalid_records += 1
            else:
                verified_records += 1
            if previous_hash is not None and previous_event_hash != previous_hash:
                broken_links += 1
            previous_hash = event_hash
            if first_event_hash is None:
                first_event_hash = event_hash
            last_event_hash = event_hash
        if total_records == 0:
            status = "empty"
        elif invalid_records or broken_links:
            status = "failed"
        elif legacy_records and verified_records:
            status = "partial"
        elif legacy_records:
            status = "legacy"
        else:
            status = "passed"
        return {
            "status": status,
            "integrity_enabled": self.integrity_enabled,
            "total_records": total_records,
            "verified_records": verified_records,
            "legacy_records": legacy_records,
            "invalid_records": invalid_records,
            "broken_links": broken_links,
            "first_event_hash": first_event_hash,
            "last_event_hash": last_event_hash,
        }

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

    def _events_oldest_first(self) -> list[dict[str, Any]]:
        lines: list[str] = []
        for path in self._retained_paths_oldest_first():
            if path.exists():
                lines.extend(path.read_text(encoding="utf-8").splitlines())
        return [
            event
            for line in lines
            if line.strip() and (event := _parse_event(line)) is not None
        ]

    def _last_audit_hash(self) -> str:
        for event in reversed(self._events_oldest_first()):
            event_hash = event.get("audit_hash")
            if isinstance(event_hash, str):
                return event_hash
        return ""


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


def _compute_audit_hash(event: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in event.items()
        if key != "audit_hash"
    }
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(rendered.encode("utf-8")).hexdigest()
