from __future__ import annotations

import unittest
from pathlib import Path

from app import build_knowledge_sources, build_runtime, build_tool_adapters
from core.models import AgentRequest
from retrieval.file_source import DirectoryKnowledgeSource
from settings import AppConfig


class FileBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = AppConfig(
            knowledge_backend="file",
            tool_backend="file",
            knowledge_dir=Path("data/knowledge"),
            metric_snapshot_path=Path("data/risk/metric_snapshots.json"),
            case_record_path=Path("data/risk/case_records.json"),
            order_profile_path=Path("data/risk/order_profiles.json"),
            strategy_profile_path=Path("data/risk/strategy_profiles.json"),
            strategy_simulation_path=Path("data/risk/strategy_simulations.json"),
            graph_relation_path=Path("data/risk/graph_relations.json"),
        )

    def test_directory_knowledge_source_loads_markdown_documents(self) -> None:
        source = DirectoryKnowledgeSource(self.config.knowledge_dir)

        documents = list(source.load())

        self.assertGreaterEqual(len(documents), 4)
        self.assertTrue(any("营销套利" in document.title for document in documents))

    def test_build_runtime_supports_file_backends(self) -> None:
        runtime = build_runtime(self.config)

        session_id, response = runtime.execute(
            "knowledge",
            AgentRequest(query="营销套利案件的标准排查 SOP 是什么？"),
        )

        self.assertTrue(session_id)
        self.assertIn("营销套利", response.summary)

    def test_build_tool_adapters_uses_file_backends(self) -> None:
        adapters = build_tool_adapters(self.config)

        self.assertEqual(len(adapters), 6)
        result = adapters[0].invoke(
            country="BR",
            channel="credit_card",
            time_range="recent_24h",
        )
        self.assertTrue(result.success)
        self.assertEqual(result.payload["country"], "BR")
        strategy_result = adapters[3].invoke(strategy_id="STRAT-001")
        self.assertTrue(strategy_result.success)
        self.assertEqual(strategy_result.payload["strategy_id"], "STRAT-001")
        graph_result = adapters[5].invoke(entity_id="U10001")
        self.assertTrue(graph_result.success)
        self.assertEqual(graph_result.payload["entity_type"], "user")

    def test_build_knowledge_sources_uses_file_backend(self) -> None:
        sources = build_knowledge_sources(self.config)

        self.assertEqual(len(sources), 1)
        self.assertIsInstance(sources[0], DirectoryKnowledgeSource)


if __name__ == "__main__":
    unittest.main()
