from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from typing import Any

from validation.staging import (
    ValidationRunner,
    _build_admin_headers,
    _validate_copilot,
    _central_recovery_audit_evidence_check,
    _validate_central_audit_events,
    _validate_fields,
    _validate_root_cause_handoff,
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


class SequencedAgentClient:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, dict[str, object]]] = []

    def post(self, path: str, payload: dict[str, object]) -> Any:
        self.requests.append((path, payload))
        return self.responses[path]

    def get(self, path: str) -> Any:
        return self.responses[path]


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
                "root_cause",
                "copilot",
            ],
            "registered_tools": [
                "metric_snapshot",
                "case_lookup",
                "order_profile",
                "strategy_profile",
                "strategy_simulation",
                "graph_relation",
                "sql_query",
                "dashboard_snapshot",
                "rule_explain",
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

    def test_root_cause_handoff_contract_validates_case_queue(self) -> None:
        client = SequencedAgentClient(
            {
                "/sessions": {"session_id": "session-1"},
                "/agents/root_cause": {
                    "agent_name": "root_cause",
                    "intent": "root_cause_analysis",
                    "artifacts": {
                        "root_cause_analysis": {"version": "v4a"},
                        "root_cause_quality": {"version": "v4c"},
                        "root_cause_readiness": {
                            "version": "v4d",
                            "status": "ready_for_handoff",
                        },
                    },
                },
                "/cases/from-session/session-1": {
                    "risk_decision": {
                        "decision": "root_cause_handoff",
                        "recommended_action": "start_shadow_evaluation",
                        "action_plan": {
                            "queue": "strategy_shadow_queue",
                            "status": "queued",
                            "due_at": "2026-07-01T00:00:00Z",
                        },
                    },
                },
            }
        )

        detail = _validate_root_cause_handoff(client)

        self.assertIn("strategy_shadow_queue", detail)
        self.assertEqual(client.requests[0], ("/sessions", {}))
        self.assertEqual(
            client.requests[1][1]["session_id"],
            "session-1",
        )

    def test_root_cause_handoff_contract_rejects_wrong_queue(self) -> None:
        client = SequencedAgentClient(
            {
                "/sessions": {"session_id": "session-1"},
                "/agents/root_cause": {
                    "agent_name": "root_cause",
                    "intent": "root_cause_analysis",
                    "artifacts": {
                        "root_cause_analysis": {"version": "v4a"},
                        "root_cause_quality": {"version": "v4c"},
                        "root_cause_readiness": {
                            "version": "v4d",
                            "status": "ready_for_handoff",
                        },
                    },
                },
                "/cases/from-session/session-1": {
                    "risk_decision": {
                        "decision": "root_cause_handoff",
                        "recommended_action": "start_shadow_evaluation",
                        "action_plan": {
                            "queue": "manual_review_queue",
                            "status": "queued",
                            "due_at": "2026-07-01T00:00:00Z",
                        },
                    },
                },
            }
        )

        with self.assertRaisesRegex(AssertionError, "unexpected root-cause queue"):
            _validate_root_cause_handoff(client)

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

    def test_central_audit_contract_requires_hashes_and_redaction(self) -> None:
        client = StubAgentClient(
            {
                "events": [
                    {
                        "event_id": "event-1",
                        "target_url": "https://risk.example.com/orders/{order_id}",
                        "outcome": "success",
                        "audit_previous_hash": "",
                        "audit_hash": "a" * 64,
                    }
                ]
            }
        )

        detail = _validate_central_audit_events(client)

        self.assertIn("tamper-evident", detail)

    def test_central_recovery_audit_requires_recovery_outcomes(self) -> None:
        client = StubAgentClient(
            {
                "events": [
                    {"upstream_client": "HttpMetricSnapshotClient", "outcome": "success"},
                    {"upstream_client": "HttpMetricSnapshotClient", "outcome": "http_error"},
                    {
                        "upstream_client": "HttpMetricSnapshotClient",
                        "outcome": "circuit_rejected",
                    },
                ]
            }
        )

        detail = _central_recovery_audit_evidence_check(client)

        self.assertIn("central audit sink captured", detail)

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
