from __future__ import annotations

import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from api import create_app, fastapi_app
from settings import AppConfig


class AgentApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(fastapi_app)

    def test_healthz(self) -> None:
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_list_agents(self) -> None:
        response = self.client.get("/agents")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"agents": ["knowledge", "investigation"]})

    def test_create_and_get_session(self) -> None:
        created = self.client.post("/sessions")
        session_id = created.json()["session_id"]

        fetched = self.client.get(f"/sessions/{session_id}")
        self.assertEqual(created.status_code, 200)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["session_id"], session_id)
        self.assertEqual(fetched.json()["turns"], [])

    def test_invoke_knowledge_agent(self) -> None:
        response = self.client.post(
            "/agents/knowledge",
            json={"query": "营销套利案件的标准排查 SOP 是什么？"},
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["session_id"])
        self.assertEqual(payload["agent_name"], "knowledge")
        self.assertTrue(payload["citations"])

    def test_invoke_investigation_agent(self) -> None:
        created = self.client.post("/sessions")
        session_id = created.json()["session_id"]
        response = self.client.post(
            "/agents/investigation",
            json={
                "query": "请分析这个订单为什么被判高风险",
                "context": {"order_id": "O10001"},
                "session_id": session_id,
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["session_id"], session_id)
        self.assertEqual(payload["agent_name"], "investigation")
        self.assertTrue(any(trace["name"] == "order_profile" for trace in payload["tool_traces"]))

        fetched = self.client.get(f"/sessions/{session_id}")
        self.assertEqual(len(fetched.json()["turns"]), 1)

    def test_unknown_agent_returns_404(self) -> None:
        response = self.client.post(
            "/agents/unknown",
            json={"query": "test"},
        )

        self.assertEqual(response.status_code, 404)

    def test_get_unknown_session_returns_404(self) -> None:
        response = self.client.get("/sessions/missing-session")

        self.assertEqual(response.status_code, 404)

    def test_reload_knowledge_for_file_backend(self) -> None:
        app = create_app(
            AppConfig(
                knowledge_backend="file",
                tool_backend="file",
                knowledge_dir=Path("data/knowledge"),
                metric_snapshot_path=Path("data/risk/metric_snapshots.json"),
                case_record_path=Path("data/risk/case_records.json"),
                order_profile_path=Path("data/risk/order_profiles.json"),
            )
        )
        client = TestClient(app)

        response = client.post("/admin/knowledge/reload")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(payload["documents_loaded"], 4)
        self.assertEqual(payload["documents_loaded"], payload["total_documents"])

    def test_runtime_info_endpoint(self) -> None:
        app = create_app(
            AppConfig(
                knowledge_backend="file",
                tool_backend="file",
                knowledge_dir=Path("data/knowledge"),
                metric_snapshot_path=Path("data/risk/metric_snapshots.json"),
                case_record_path=Path("data/risk/case_records.json"),
                order_profile_path=Path("data/risk/order_profiles.json"),
            )
        )
        client = TestClient(app)

        response = client.get("/admin/runtime")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["knowledge_backend"], "file")
        self.assertEqual(payload["tool_backend"], "file")
        self.assertEqual(payload["registered_agents"], ["knowledge", "investigation"])
        self.assertEqual(payload["registered_tools"], ["metric_snapshot", "case_lookup", "order_profile"])


if __name__ == "__main__":
    unittest.main()
