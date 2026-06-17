from __future__ import annotations

import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

from services.audit import (
    CompositeAuditLog,
    HttpAuditSink,
    JsonLinesAuditLog,
    build_upstream_audit_event,
    redact_url,
)
from services.observability import bind_context


class _FakeAuditSinkResponse:
    status = 202

    def __enter__(self):
        return BytesIO(b"{}")

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FailingAuditMirror:
    def record(self, event: dict[str, object]) -> None:
        raise OSError("central audit unavailable")

    def list_events(self, **kwargs) -> list[dict[str, object]]:
        return []

    def verify_integrity(self) -> dict[str, object]:
        return {"status": "failed"}


class AuditTests(unittest.TestCase):
    def test_redact_url_removes_query_values_and_entity_ids(self) -> None:
        redacted = redact_url(
            "https://user:password@risk.example.com/v2/orders/O10001/profile"
            "?country=BR&token=secret#fragment"
        )

        self.assertIn("/v2/orders/[REDACTED]/profile", redacted)
        self.assertIn("country=%5BREDACTED%5D", redacted)
        self.assertIn("token=%5BREDACTED%5D", redacted)
        decoded = unquote(redacted)
        self.assertNotIn("O10001", decoded)
        self.assertNotIn("BR", decoded)
        self.assertNotIn("secret", decoded)
        self.assertNotIn("password", decoded)
        self.assertNotIn("user@", decoded)
        self.assertNotIn("fragment", decoded)

    def test_audit_event_preserves_correlation_without_header_values(self) -> None:
        with bind_context(
            request_id="req-123",
            trace_id="trace-456",
            session_id="session-789",
            agent_name="investigation",
        ):
            event = build_upstream_audit_event(
                upstream_client="HttpOrderProfileClient",
                method="GET",
                url="https://risk.example.com/orders/O10001",
                outcome="success",
                attempt=1,
                total_attempts=1,
                status_code=200,
                request_header_names=["Authorization", "X-Request-Id"],
            )

        rendered = json.dumps(event)
        self.assertEqual(event["request_id"], "req-123")
        self.assertEqual(event["agent_name"], "investigation")
        self.assertEqual(event["request_header_names"], ["Authorization", "X-Request-Id"])
        self.assertNotIn("O10001", rendered)
        self.assertNotIn("Bearer", rendered)

    def test_json_lines_audit_log_filters_newest_first_and_skips_partial_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "audit.jsonl"
            audit_log = JsonLinesAuditLog(path)
            audit_log.record({"event_id": "1", "outcome": "failed", "request_id": "req-1"})
            audit_log.record({"event_id": "2", "outcome": "success", "request_id": "req-2"})
            with path.open("a", encoding="utf-8") as handle:
                handle.write('{"event_id":')

            events = audit_log.list_events(outcome="success")

        self.assertEqual([event["event_id"] for event in events], ["2"])

    def test_json_lines_audit_log_adds_and_verifies_hash_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "audit.jsonl"
            audit_log = JsonLinesAuditLog(path)
            audit_log.record({"event_id": "1", "outcome": "success"})
            audit_log.record({"event_id": "2", "outcome": "success"})

            events = audit_log.list_events(limit=2)
            integrity = audit_log.verify_integrity()

        self.assertEqual(integrity["status"], "passed")
        self.assertEqual(integrity["verified_records"], 2)
        self.assertEqual(events[0]["event_id"], "2")
        self.assertEqual(events[0]["audit_previous_hash"], events[1]["audit_hash"])
        self.assertEqual(len(events[0]["audit_hash"]), 64)

    def test_json_lines_audit_log_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "audit.jsonl"
            audit_log = JsonLinesAuditLog(path)
            audit_log.record({"event_id": "1", "outcome": "success"})
            path.write_text(
                path.read_text(encoding="utf-8").replace('"success"', '"tampered"', 1),
                encoding="utf-8",
            )

            integrity = audit_log.verify_integrity()

        self.assertEqual(integrity["status"], "failed")
        self.assertEqual(integrity["invalid_records"], 1)

    def test_composite_audit_log_mirrors_hashed_event_to_http_sink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "audit.jsonl"
            audit_log = CompositeAuditLog(
                JsonLinesAuditLog(path),
                [
                    HttpAuditSink(
                        "https://audit.example.com/events",
                        headers={"Authorization": "Bearer central-secret"},
                    )
                ],
            )

            with patch("services.audit.urlopen", return_value=_FakeAuditSinkResponse()) as mocked:
                audit_log.record({"event_id": "1", "outcome": "success"})

            request = mocked.call_args[0][0]
            mirrored = json.loads(request.data.decode("utf-8"))
            local_event = audit_log.list_events()[0]

        self.assertEqual(mirrored["audit_hash"], local_event["audit_hash"])
        self.assertEqual(mirrored["audit_previous_hash"], "")
        self.assertEqual(request.headers["Authorization"], "Bearer central-secret")

    def test_composite_audit_log_keeps_local_record_when_mirror_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_log = CompositeAuditLog(
                JsonLinesAuditLog(Path(tmp_dir) / "audit.jsonl"),
                [_FailingAuditMirror()],
            )

            audit_log.record({"event_id": "1", "outcome": "success"})
            events = audit_log.list_events()

        self.assertEqual([event["event_id"] for event in events], ["1"])

    def test_json_lines_audit_log_rotates_and_queries_retained_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "audit.jsonl"
            audit_log = JsonLinesAuditLog(path, max_bytes=120, max_files=3)
            for index in range(5):
                audit_log.record(
                    {
                        "event_id": str(index),
                        "outcome": "success",
                        "request_id": "req",
                        "padding": "x" * 40,
                    }
                )

            events = audit_log.list_events(limit=5)

        self.assertLessEqual(len(events), 3)
        self.assertEqual(events[0]["event_id"], "4")
        self.assertTrue(any(event["event_id"] == "2" for event in events))


if __name__ == "__main__":
    unittest.main()
