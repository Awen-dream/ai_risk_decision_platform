from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import build_runtime, build_session_store
from core.models import AgentRequest
from core.session_store import FileSessionStore
from settings import AppConfig


class SessionStoreTests(unittest.TestCase):
    def test_build_session_store_returns_file_store_for_file_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = AppConfig(
                session_store_backend="file",
                session_store_path=Path(tmp_dir) / "sessions.json",
            )

            store = build_session_store(config)

            self.assertIsInstance(store, FileSessionStore)

    def test_file_session_store_persists_session_across_runtime_rebuilds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "sessions.json"
            config = AppConfig(
                session_store_backend="file",
                session_store_path=session_path,
            )

            first_runtime = build_runtime(config)
            session_id, _ = first_runtime.execute(
                "knowledge",
                AgentRequest(query="营销套利案件的标准排查 SOP 是什么？"),
            )

            rebuilt_runtime = build_runtime(config)
            session = rebuilt_runtime.get_session(session_id)

            self.assertIsNotNone(session)
            assert session is not None
            self.assertEqual(len(session.turns), 1)
            self.assertEqual(session.turns[0].agent_name, "knowledge")

    def test_file_session_store_appends_turns_to_existing_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "sessions.json"
            config = AppConfig(
                session_store_backend="file",
                session_store_path=session_path,
            )

            runtime = build_runtime(config)
            session_id, _ = runtime.execute(
                "knowledge",
                AgentRequest(query="营销套利案件的标准排查 SOP 是什么？"),
            )
            runtime.execute(
                "investigation",
                AgentRequest(query="为什么巴西信用卡支付失败率从昨晚开始突然升高？"),
                session_id=session_id,
            )

            rebuilt_runtime = build_runtime(config)
            session = rebuilt_runtime.get_session(session_id)

            self.assertIsNotNone(session)
            assert session is not None
            self.assertEqual(len(session.turns), 2)
            self.assertEqual(
                [turn.agent_name for turn in session.turns],
                ["knowledge", "investigation"],
            )

    def test_file_session_store_persists_strategy_artifacts_and_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "sessions.json"
            config = AppConfig(
                session_store_backend="file",
                session_store_path=session_path,
            )

            runtime = build_runtime(config)
            session_id, _ = runtime.execute(
                "strategy",
                AgentRequest(
                    query="请评估策略 STRAT-001 是否应该调整阈值",
                    context={"strategy_id": "STRAT-001"},
                ),
            )

            rebuilt_runtime = build_runtime(config)
            session = rebuilt_runtime.get_session(session_id)

            self.assertIsNotNone(session)
            assert session is not None
            self.assertEqual(session.turns[0].artifacts["strategy_recommendation"]["strategy_id"], "STRAT-001")
            self.assertIn("shadow evaluation", session.turns[0].suggested_actions[0])


if __name__ == "__main__":
    unittest.main()
