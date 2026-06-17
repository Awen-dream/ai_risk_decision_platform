from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from audit_sink_service import create_audit_sink_app


class AuditSinkServiceTests(unittest.TestCase):
    def test_audit_sink_requires_token_and_lists_events_newest_first(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AI_RISK_AUDIT_SINK_AUTH_HEADER": "X-Audit-Token",
                "AI_RISK_AUDIT_SINK_AUTH_TOKEN": "sink-secret",
            },
        ):
            client = TestClient(create_audit_sink_app())

        unauthorized = client.post("/audit-events", json={"event_id": "1"})
        accepted_one = client.post(
            "/audit-events",
            headers={"X-Audit-Token": "sink-secret"},
            json={"event_id": "1", "audit_hash": "a" * 64},
        )
        accepted_two = client.post(
            "/audit-events",
            headers={"X-Audit-Token": "sink-secret"},
            json={"event_id": "2", "audit_hash": "b" * 64},
        )
        listed = client.get("/admin/events", headers={"X-Audit-Token": "sink-secret"})

        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(accepted_one.status_code, 200)
        self.assertEqual(accepted_two.status_code, 200)
        self.assertEqual(
            [event["event_id"] for event in listed.json()["events"]],
            ["2", "1"],
        )
        self.assertIn("central_received_at", listed.json()["events"][0])


if __name__ == "__main__":
    unittest.main()
