from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

from services.audit import (
    JsonLinesAuditLog,
    build_upstream_audit_event,
    redact_url,
)
from services.observability import bind_context


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


if __name__ == "__main__":
    unittest.main()
