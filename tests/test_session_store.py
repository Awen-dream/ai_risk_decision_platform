from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import build_runtime, build_session_store
from core.models import AgentRequest, AgentResponse
from core.session_store import FileSessionStore, SQLiteSessionStore
from services.observability import (
    get_gauges_snapshot,
    get_histograms_snapshot,
    get_metrics_snapshot,
)
from settings import AppConfig


class SessionStoreTests(unittest.TestCase):
    def test_build_session_store_returns_sqlite_store_for_sqlite_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = AppConfig(
                session_store_backend="sqlite",
                database_path=Path(tmp_dir) / "platform.db",
            )

            store = build_session_store(config)

            self.assertIsInstance(store, SQLiteSessionStore)

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

    def test_sqlite_session_store_persists_across_runtime_rebuilds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = AppConfig(
                session_store_backend="sqlite",
                database_path=Path(tmp_dir) / "platform.db",
            )

            runtime = build_runtime(config)
            session_id, _ = runtime.execute(
                "knowledge",
                AgentRequest(query="营销套利案件的标准排查 SOP 是什么？"),
            )

            rebuilt_runtime = build_runtime(config)
            session = rebuilt_runtime.get_session(session_id)

            self.assertIsNotNone(session)
            assert session is not None
            self.assertEqual(len(session.turns), 1)
            self.assertEqual(session.turns[0].agent_name, "knowledge")

    def test_sqlite_session_store_serializes_concurrent_appends(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SQLiteSessionStore(Path(tmp_dir) / "platform.db")
            session_id = store.create_session().session_id

            def append_turn(index: int) -> None:
                store.append_turn(
                    session_id,
                    AgentRequest(query=f"query-{index}"),
                    AgentResponse(agent_name="knowledge", summary=f"summary-{index}"),
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(append_turn, range(20)))

            session = store.get_session(session_id)

            self.assertIsNotNone(session)
            assert session is not None
            self.assertEqual(len(session.turns), 20)
            self.assertEqual(
                {turn.query for turn in session.turns},
                {f"query-{index}" for index in range(20)},
            )
            self.assertEqual(
                get_gauges_snapshot()["database.sqlite.transactions.active"],
                0.0,
            )
            self.assertGreaterEqual(
                get_metrics_snapshot()["database.sqlite.transactions.completed"],
                21,
            )
            self.assertIn(
                "database.sqlite.transaction.duration_seconds",
                get_histograms_snapshot(),
            )


if __name__ == "__main__":
    unittest.main()
