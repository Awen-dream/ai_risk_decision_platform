from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from api import create_app
from app import build_app_container, build_case_service
from core.models import AgentRequest
from services.case_service import FileCaseService
from settings import AppConfig


class CaseServiceTests(unittest.TestCase):
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
            self.assertTrue(loaded_case.created_at.endswith("Z"))
            self.assertEqual(loaded_case.created_at, loaded_case.updated_at)

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


if __name__ == "__main__":
    unittest.main()
