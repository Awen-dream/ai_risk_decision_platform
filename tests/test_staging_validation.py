from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from typing import Any

from validation.staging import (
    ValidationRunner,
    _build_admin_headers,
    _validate_copilot,
    _validate_fields,
    _validate_runtime,
    _validate_upstream_audit,
    _validate_upstream_audit_integrity,
)


class StubAgentClient:
    def __init__(self, response: Any) -> None:
        self.response = response

    def post(self, path: str, payload: dict[str, object]) -> Any:
        return self.response

    def get(self, path: str) -> Any:
        return self.response


class StagingValidationTests(unittest.TestCase):
    def test_validation_runner_reports_failed_check(self) -> None:
        runner = ValidationRunner()

        runner.check("missing.field", lambda: _validate_fields({}, {"required"}, is_list=False))

        report = runner.report()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["summary"]["failed"], 1)
        self.assertIn("missing fields", report["checks"][0]["detail"])

    def test_runtime_contract_requires_exact_phase1_surface(self) -> None:
        payload = {
            "supported_capabilities": [
                "knowledge",
                "investigation",
                "strategy",
                "graph",
                "copilot",
            ],
            "registered_tools": [
                "metric_snapshot",
                "case_lookup",
                "order_profile",
                "strategy_profile",
                "strategy_simulation",
                "graph_relation",
            ],
            "readiness": {"status": "ready"},
        }

        detail = _validate_runtime(payload)

        self.assertIn("match", detail)

    def test_copilot_contract_validates_orchestration_surface(self) -> None:
        client = StubAgentClient(
            {
                "agent_name": "copilot",
                "intent": "composite",
                "plan_steps": ["调查", "策略", "图谱"],
                "planner_trace": [
                    {"step": "调查", "selected": True},
                    {"step": "策略", "selected": True},
                    {"step": "图谱", "selected": True},
                ],
                "tool_traces": [
                    {"name": "调查::order_profile", "status": "success", "summary": "ok"},
                    {"name": "策略::strategy_profile", "status": "success", "summary": "ok"},
                    {"name": "图谱::graph_relation", "status": "success", "summary": "ok"},
                ],
            }
        )

        detail = _validate_copilot(client, {"order_id": "O10001"})

        self.assertIn("completed", detail)

    def test_copilot_contract_rejects_missing_orchestration_branch(self) -> None:
        client = StubAgentClient(
            {
                "agent_name": "copilot",
                "intent": "composite",
                "plan_steps": ["调查", "策略", "图谱"],
                "planner_trace": [
                    {"step": "调查", "selected": True},
                    {"step": "策略", "selected": True},
                    {"step": "图谱", "selected": True},
                ],
                "tool_traces": [
                    {"name": "调查::order_profile", "status": "success", "summary": "ok"},
                    {"name": "策略::strategy_profile", "status": "success", "summary": "ok"},
                ],
            }
        )

        with self.assertRaisesRegex(AssertionError, "missing orchestrated tool traces"):
            _validate_copilot(client, {"order_id": "O10001"})

    def test_upstream_audit_contract_requires_redacted_records(self) -> None:
        client = StubAgentClient(
            [
                {
                    "event_id": "event-1",
                    "occurred_at": "2026-06-15T00:00:00Z",
                    "upstream_client": "HttpOrderProfileClient",
                    "target_url": "https://risk.example.com/orders/{order_id}",
                    "outcome": "success",
                    "request_header_names": ["Authorization"],
                }
            ]
        )

        detail = _validate_upstream_audit(client)

        self.assertIn("redacted records", detail)

    def test_upstream_audit_integrity_rejects_failed_status(self) -> None:
        client = StubAgentClient(
            {
                "status": "failed",
                "integrity_enabled": True,
                "verified_records": 1,
            }
        )

        with self.assertRaisesRegex(AssertionError, "integrity"):
            _validate_upstream_audit_integrity(client)

    def test_build_admin_headers_reads_token_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            token_path = Path(tmp_dir) / "admin-token"
            token_path.write_text("file-admin-secret\n", encoding="utf-8")

            headers = _build_admin_headers(
                "X-Admin-Token",
                "",
                str(token_path),
            )

        self.assertEqual(headers, {"X-Admin-Token": "file-admin-secret"})


if __name__ == "__main__":
    unittest.main()
