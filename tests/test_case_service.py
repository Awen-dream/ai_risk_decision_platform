from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import create_app
from app import build_app_container, build_case_service
from core.models import AgentRequest
from services.case_service import FileCaseService, PostgresCaseService, SQLiteCaseService
from settings import AppConfig


class CaseServiceTests(unittest.TestCase):
    def test_build_case_service_returns_sqlite_store_for_sqlite_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = AppConfig(
                case_store_backend="sqlite",
                database_path=Path(tmp_dir) / "platform.db",
            )

            store = build_case_service(config)

            self.assertIsInstance(store, SQLiteCaseService)

    def test_build_case_service_returns_postgres_store_for_postgres_backend(self) -> None:
        config = AppConfig(
            case_store_backend="postgres",
            postgres_dsn="postgresql://risk:secret@db/risk",
        )

        with patch("services.case_service.PostgresDatabase.migrate"):
            store = build_case_service(config)

        self.assertIsInstance(store, PostgresCaseService)

    def test_build_case_service_returns_file_store_for_file_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = AppConfig(
                case_store_backend="file",
                case_store_path=Path(tmp_dir) / "cases.json",
            )

            store = build_case_service(config)

            self.assertIsInstance(store, FileCaseService)

    def test_file_case_store_persists_cases_across_container_rebuilds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = AppConfig(
                session_store_backend="file",
                session_store_path=Path(tmp_dir) / "sessions.json",
                case_store_backend="file",
                case_store_path=Path(tmp_dir) / "cases.json",
            )

            first_container = build_app_container(config)
            session_id, _ = first_container.runtime.execute(
                "copilot",
                AgentRequest(
                    query="请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                    context={"order_id": "O10001", "strategy_id": "STRAT-001", "entity_id": "U10001"},
                ),
            )
            session = first_container.runtime.get_session(session_id)
            assert session is not None
            created_case = first_container.case_service.create_case_from_session(session)

            rebuilt_container = build_app_container(config)
            loaded_case = rebuilt_container.case_service.get_case(created_case.case_id)

            self.assertIsNotNone(loaded_case)
            assert loaded_case is not None
            self.assertEqual(loaded_case.session_id, session_id)
            self.assertEqual(loaded_case.strategy_recommendation.strategy_id, "STRAT-001")
            self.assertEqual(loaded_case.evidence_panel["version"], "v1")
            self.assertGreater(loaded_case.evidence_panel["summary"]["evidence_count"], 0)
            self.assertIsNotNone(loaded_case.risk_decision)
            assert loaded_case.risk_decision is not None
            self.assertEqual(loaded_case.risk_decision.decision, "escalate_review")
            self.assertEqual(loaded_case.risk_decision.risk_level, "high")
            self.assertIsNotNone(loaded_case.risk_decision.action_plan)
            assert loaded_case.risk_decision.action_plan is not None
            self.assertEqual(
                loaded_case.risk_decision.action_plan.queue,
                "manual_review_queue",
            )
            self.assertEqual(loaded_case.risk_decision.action_plan.sla_hours, 4)
            self.assertEqual(loaded_case.risk_decision.action_plan.status, "queued")
            assert loaded_case.risk_decision.action_plan.due_at is not None
            created_at_dt = datetime.fromisoformat(
                loaded_case.created_at.replace("Z", "+00:00")
            )
            due_at_dt = datetime.fromisoformat(
                loaded_case.risk_decision.action_plan.due_at.replace("Z", "+00:00")
            )
            self.assertEqual(due_at_dt, created_at_dt + timedelta(hours=4))
            completed_case = rebuilt_container.case_service.update_case_status(
                created_case.case_id,
                "closed",
                note="复核完成",
                assigned_to="risk-reviewer-01",
                action_outcome="rejected_after_review",
            )
            assert completed_case is not None
            assert completed_case.risk_decision is not None
            assert completed_case.risk_decision.action_plan is not None
            self.assertEqual(
                completed_case.risk_decision.action_plan.status,
                "completed",
            )
            self.assertEqual(
                completed_case.risk_decision.action_plan.assigned_to,
                "risk-reviewer-01",
            )
            self.assertEqual(
                completed_case.risk_decision.action_plan.outcome,
                "rejected_after_review",
            )
            self.assertEqual(
                completed_case.risk_decision.action_plan.completed_at,
                completed_case.updated_at,
            )
            self.assertTrue(loaded_case.created_at.endswith("Z"))
            self.assertEqual(loaded_case.created_at, loaded_case.updated_at)

    def test_case_creation_marks_in_review_action_plan_in_progress(self) -> None:
        container = build_app_container(AppConfig())
        session_id, _ = container.runtime.execute(
            "copilot",
            AgentRequest(
                query="请分析这个订单为什么被判高风险",
                context={"order_id": "O10001"},
            ),
        )
        session = container.runtime.get_session(session_id)
        assert session is not None

        case = container.case_service.create_case_from_session(session)

        self.assertEqual(case.status, "in_review")
        self.assertEqual(case.evidence_panel["scope"], "copilot")
        self.assertIsNotNone(case.risk_decision)
        assert case.risk_decision is not None
        self.assertIsNotNone(case.risk_decision.action_plan)
        assert case.risk_decision.action_plan is not None
        self.assertEqual(case.risk_decision.action_plan.status, "in_progress")
        self.assertIsNotNone(case.risk_decision.action_plan.due_at)

    def test_root_cause_case_creation_builds_shadow_handoff_action_plan(self) -> None:
        container = build_app_container(AppConfig())
        session_id, _ = container.runtime.execute(
            "root_cause",
            AgentRequest(
                query="请分析巴西信用卡支付失败率升高的根因并给出排序",
                context={"country": "BR", "channel": "credit_card"},
            ),
        )
        session = container.runtime.get_session(session_id)
        assert session is not None

        case = container.case_service.create_case_from_session(session)

        self.assertEqual(case.status, "strategy_pending")
        self.assertEqual(case.intent, "root_cause_analysis")
        self.assertEqual(case.evidence_panel["scope"], "agent")
        self.assertIsNotNone(case.risk_decision)
        assert case.risk_decision is not None
        self.assertEqual(case.risk_decision.decision, "root_cause_handoff")
        self.assertEqual(
            case.risk_decision.recommended_action,
            "start_shadow_evaluation",
        )
        self.assertIn("shadow_evaluation", case.risk_decision.policy_controls)
        self.assertIsNotNone(case.risk_decision.action_plan)
        assert case.risk_decision.action_plan is not None
        self.assertEqual(case.risk_decision.action_plan.queue, "strategy_shadow_queue")
        self.assertEqual(case.risk_decision.action_plan.status, "queued")
        self.assertEqual(case.risk_decision.action_plan.sla_hours, 24)
        assert case.risk_decision.action_plan.due_at is not None
        created_at_dt = datetime.fromisoformat(case.created_at.replace("Z", "+00:00"))
        due_at_dt = datetime.fromisoformat(
            case.risk_decision.action_plan.due_at.replace("Z", "+00:00")
        )
        self.assertEqual(due_at_dt, created_at_dt + timedelta(hours=24))

    def test_file_case_store_survives_api_recreation_and_supports_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = AppConfig(
                session_store_backend="file",
                session_store_path=Path(tmp_dir) / "sessions.json",
                case_store_backend="file",
                case_store_path=Path(tmp_dir) / "cases.json",
            )

            first_client = TestClient(create_app(config))
            created = first_client.post("/sessions")
            session_id = created.json()["session_id"]
            first_client.post(
                "/agents/copilot",
                json={
                    "query": "请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                    "context": {"order_id": "O10001", "strategy_id": "STRAT-001", "entity_id": "U10001"},
                    "session_id": session_id,
                },
            )
            case_response = first_client.post(f"/cases/from-session/{session_id}")
            case_id = case_response.json()["case_id"]

            second_client = TestClient(create_app(config))
            loaded_case = second_client.get(f"/cases/{case_id}")
            filtered_cases = second_client.get(
                "/cases",
                params={"status": "strategy_pending", "source_agent": "copilot"},
            )

            self.assertEqual(loaded_case.status_code, 200)
            self.assertEqual(loaded_case.json()["case_id"], case_id)
            self.assertEqual(filtered_cases.status_code, 200)
            self.assertEqual(len(filtered_cases.json()), 1)
            self.assertEqual(filtered_cases.json()[0]["case_id"], case_id)

    def test_file_case_store_updates_timestamp_and_sort_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = AppConfig(
                session_store_backend="file",
                session_store_path=Path(tmp_dir) / "sessions.json",
                case_store_backend="file",
                case_store_path=Path(tmp_dir) / "cases.json",
            )

            container = build_app_container(config)
            first_session_id, _ = container.runtime.execute(
                "graph",
                AgentRequest(
                    query="请分析用户 U10001 是否属于团伙网络",
                    context={"user_id": "U10001"},
                ),
            )
            first_session = container.runtime.get_session(first_session_id)
            assert first_session is not None
            first_case = container.case_service.create_case_from_session(first_session)

            second_session_id, _ = container.runtime.execute(
                "copilot",
                AgentRequest(
                    query="请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                    context={"order_id": "O10001", "strategy_id": "STRAT-001", "entity_id": "U10001"},
                ),
            )
            second_session = container.runtime.get_session(second_session_id)
            assert second_session is not None
            second_case = container.case_service.create_case_from_session(second_session)

            updated_case = container.case_service.update_case_status(
                first_case.case_id,
                "in_review",
                note="重新处理",
            )

            assert updated_case is not None
            self.assertNotEqual(updated_case.updated_at, updated_case.created_at)
            listed_cases = container.case_service.list_cases()
            self.assertEqual(listed_cases[0].case_id, first_case.case_id)
            self.assertEqual(listed_cases[1].case_id, second_case.case_id)

    def test_file_case_store_supports_pagination_and_updated_at_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = AppConfig(
                session_store_backend="file",
                session_store_path=Path(tmp_dir) / "sessions.json",
                case_store_backend="file",
                case_store_path=Path(tmp_dir) / "cases.json",
            )

            container = build_app_container(config)
            first_session_id, _ = container.runtime.execute(
                "graph",
                AgentRequest(
                    query="请分析用户 U10001 是否属于团伙网络",
                    context={"user_id": "U10001"},
                ),
            )
            first_session = container.runtime.get_session(first_session_id)
            assert first_session is not None
            first_case = container.case_service.create_case_from_session(first_session)

            second_session_id, _ = container.runtime.execute(
                "copilot",
                AgentRequest(
                    query="请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                    context={"order_id": "O10001", "strategy_id": "STRAT-001", "entity_id": "U10001"},
                ),
            )
            second_session = container.runtime.get_session(second_session_id)
            assert second_session is not None
            second_case = container.case_service.create_case_from_session(second_session)
            updated_second_case = container.case_service.update_case_status(
                second_case.case_id,
                "closed",
                note="完成",
            )

            assert updated_second_case is not None
            paged_cases = container.case_service.list_cases(limit=1, offset=1)
            filtered_cases = container.case_service.list_cases(
                updated_after=updated_second_case.created_at,
            )

            self.assertEqual(len(paged_cases), 1)
            self.assertEqual(paged_cases[0].case_id, first_case.case_id)
            self.assertEqual(len(filtered_cases), 1)
            self.assertEqual(filtered_cases[0].case_id, second_case.case_id)
            self.assertEqual(
                container.case_service.count_cases(
                    updated_after=updated_second_case.created_at,
                ),
                1,
            )

    def test_sqlite_stores_share_database_and_survive_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "platform.db"
            config = AppConfig(
                session_store_backend="sqlite",
                case_store_backend="sqlite",
                database_path=database_path,
            )
            first_container = build_app_container(config)
            session_id, _ = first_container.runtime.execute(
                "copilot",
                AgentRequest(
                    query="请联合分析订单 O10001 和策略 STRAT-001",
                    context={
                        "order_id": "O10001",
                        "strategy_id": "STRAT-001",
                        "entity_id": "U10001",
                    },
                ),
            )
            session = first_container.runtime.get_session(session_id)
            assert session is not None
            created_case = first_container.case_service.create_case_from_session(session)

            rebuilt_container = build_app_container(config)
            loaded_session = rebuilt_container.runtime.get_session(session_id)
            loaded_case = rebuilt_container.case_service.get_case(created_case.case_id)

            self.assertIsNotNone(loaded_session)
            self.assertIsNotNone(loaded_case)
            assert loaded_case is not None
            self.assertEqual(loaded_case.session_id, session_id)
            self.assertEqual(
                rebuilt_container.case_service.count_cases(
                    status=created_case.status,
                    source_agent="copilot",
                ),
                1,
            )

    def test_sqlite_case_store_serializes_concurrent_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "platform.db"
            config = AppConfig(
                session_store_backend="sqlite",
                case_store_backend="sqlite",
                database_path=database_path,
            )
            container = build_app_container(config)
            session_id, _ = container.runtime.execute(
                "graph",
                AgentRequest(
                    query="请分析用户 U10001 是否属于团伙网络",
                    context={"entity_id": "U10001"},
                ),
            )
            session = container.runtime.get_session(session_id)
            assert session is not None
            created_case = container.case_service.create_case_from_session(session)

            def update_status(index: int) -> None:
                service = SQLiteCaseService(database_path)
                service.update_case_status(
                    created_case.case_id,
                    "in_review",
                    note=f"review-{index}",
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(update_status, range(20)))

            loaded_case = container.case_service.get_case(created_case.case_id)

            self.assertIsNotNone(loaded_case)
            assert loaded_case is not None
            self.assertEqual(len(loaded_case.history), 21)
            self.assertEqual(
                {item.summary for item in loaded_case.history[1:]},
                {f"review-{index}" for index in range(20)},
            )

    def test_sqlite_case_store_filters_by_action_plan_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "platform.db"
            config = AppConfig(
                session_store_backend="sqlite",
                case_store_backend="sqlite",
                database_path=database_path,
            )
            container = build_app_container(config)
            session_id, _ = container.runtime.execute(
                "copilot",
                AgentRequest(
                    query="请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                    context={
                        "order_id": "O10001",
                        "strategy_id": "STRAT-001",
                        "entity_id": "U10001",
                    },
                ),
            )
            session = container.runtime.get_session(session_id)
            assert session is not None
            created_case = container.case_service.create_case_from_session(session)
            updated_case = container.case_service.update_case_status(
                created_case.case_id,
                "strategy_pending",
                assigned_to="risk-reviewer-01",
            )

            assert updated_case is not None
            filtered = container.case_service.list_cases(
                action_queue="manual_review_queue",
                action_status="queued",
                assigned_to="risk-reviewer-01",
            )

            self.assertEqual([case.case_id for case in filtered], [created_case.case_id])
            self.assertEqual(
                container.case_service.count_cases(
                    action_queue="manual_review_queue",
                    action_status="queued",
                    assigned_to="risk-reviewer-01",
                ),
                1,
            )

    def test_sqlite_case_store_normalizes_timestamp_filter_to_utc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = AppConfig(
                session_store_backend="sqlite",
                case_store_backend="sqlite",
                database_path=Path(tmp_dir) / "platform.db",
            )
            container = build_app_container(config)
            session_id, _ = container.runtime.execute(
                "graph",
                AgentRequest(
                    query="请分析用户 U10001 是否属于团伙网络",
                    context={"entity_id": "U10001"},
                ),
            )
            session = container.runtime.get_session(session_id)
            assert session is not None
            created_case = container.case_service.create_case_from_session(session)
            equivalent_offset = datetime.fromisoformat(
                created_case.updated_at.replace("Z", "+00:00")
            ).astimezone(timezone(timedelta(hours=8))).isoformat()

            cases = container.case_service.list_cases(
                updated_after=equivalent_offset,
            )

            self.assertEqual([case.case_id for case in cases], [created_case.case_id])

    def test_sqlite_case_creation_is_idempotent_per_session_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = AppConfig(
                session_store_backend="sqlite",
                case_store_backend="sqlite",
                database_path=Path(tmp_dir) / "platform.db",
            )
            container = build_app_container(config)
            session_id, _ = container.runtime.execute(
                "graph",
                AgentRequest(
                    query="请分析用户 U10001 是否属于团伙网络",
                    context={"entity_id": "U10001"},
                ),
            )
            session = container.runtime.get_session(session_id)
            assert session is not None

            services = [
                SQLiteCaseService(config.database_path)
                for _ in range(8)
            ]
            with ThreadPoolExecutor(max_workers=8) as executor:
                cases = list(
                    executor.map(
                        lambda service: service.create_case_from_session(session),
                        services,
                    )
                )

            self.assertEqual(len({case.case_id for case in cases}), 1)
            self.assertEqual(container.case_service.count_cases(), 1)


if __name__ == "__main__":
    unittest.main()
