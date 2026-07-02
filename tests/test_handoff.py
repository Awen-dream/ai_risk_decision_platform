from __future__ import annotations

import unittest

from app import build_app_container, build_handoff_publisher_service
from core.models import AgentRequest
from services.handoff import CaseHandoffPublisherService
from settings import AppConfig


class HandoffPublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        container = build_app_container(AppConfig())
        self.case_service = container.case_service
        self.audit_log = container.audit_log
        self.runtime = container.runtime
        self.service: CaseHandoffPublisherService = build_handoff_publisher_service(
            case_service=self.case_service,
            audit_log=self.audit_log,
        )

    def test_publish_selects_ticket_and_webhook_and_audit_only_publishers(self) -> None:
        session_id, _ = self.runtime.execute(
            "root_cause",
            AgentRequest(
                query="请分析巴西信用卡支付失败率升高的根因并给出排序",
                context={"country": "BR", "channel": "credit_card"},
            ),
        )
        session = self.runtime.get_session(session_id)
        assert session is not None
        case = self.case_service.create_case_from_session(session)

        ticket_result = self.service.publish_case_handoff(
            case.case_id,
            destination_type="ticket",
            destination_key="shadow-exp-1",
            note="推送到工单系统",
            published_at="2026-07-02T00:00:00Z",
        )
        webhook_result = self.service.publish_case_handoff(
            case.case_id,
            destination_type="webhook",
            destination_key="ops-sync",
            note="推送到 webhook",
            published_at="2026-07-02T00:05:00Z",
        )
        audit_only_result = self.service.publish_case_handoff(
            case.case_id,
            destination_type="audit-only",
            destination_key="local-archive",
            note="仅审计归档",
            published_at="2026-07-02T00:10:00Z",
        )

        assert ticket_result is not None
        assert webhook_result is not None
        assert audit_only_result is not None
        self.assertEqual(ticket_result.receipt.publisher_type, "ticket")
        self.assertEqual(
            ticket_result.receipt.target_ref,
            "ticket://risk-ops/shadow-exp-1",
        )
        self.assertEqual(webhook_result.receipt.publisher_type, "webhook")
        self.assertEqual(
            webhook_result.receipt.target_ref,
            "https://handoff.local/webhooks/ops-sync",
        )
        self.assertEqual(audit_only_result.receipt.publisher_type, "audit-only")
        self.assertEqual(
            audit_only_result.receipt.target_ref,
            "audit://local-archive",
        )
        self.assertEqual(
            audit_only_result.audit_event["destination_type"],
            "audit-only",
        )
        self.assertEqual(
            audit_only_result.audit_event["publisher_type"],
            "audit-only",
        )

    def test_publish_rejects_unknown_destination_type(self) -> None:
        session_id, _ = self.runtime.execute(
            "graph",
            AgentRequest(
                query="请分析用户 U10001 是否属于团伙网络",
                context={"user_id": "U10001"},
            ),
        )
        session = self.runtime.get_session(session_id)
        assert session is not None
        case = self.case_service.create_case_from_session(session)

        with self.assertRaises(ValueError):
            self.service.publish_case_handoff(
                case.case_id,
                destination_type="unknown",
                destination_key="x",
                note=None,
                published_at="2026-07-02T01:00:00Z",
            )


if __name__ == "__main__":
    unittest.main()
