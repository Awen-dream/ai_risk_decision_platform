from __future__ import annotations

import unittest

from adapters.in_memory import (
    InMemoryCaseLookupAdapter,
    InMemoryKnowledgeSource,
    InMemoryMetricSnapshotAdapter,
    InMemoryOrderProfileAdapter,
)
from retrieval.knowledge_base import RetrievalService
from tools.registry import ToolRegistry


class AdapterTests(unittest.TestCase):
    def test_knowledge_source_loads_documents_into_retrieval(self) -> None:
        retrieval = RetrievalService()
        retrieval.add_source(InMemoryKnowledgeSource())

        documents = retrieval.search("营销套利", top_k=1)
        self.assertEqual(len(documents), 1)
        self.assertIn("营销套利", documents[0].title)

    def test_tool_registry_registers_adapters(self) -> None:
        registry = ToolRegistry()
        registry.register_adapter(InMemoryMetricSnapshotAdapter())
        registry.register_adapter(InMemoryCaseLookupAdapter())
        registry.register_adapter(InMemoryOrderProfileAdapter())

        self.assertEqual(
            registry.list_tools(),
            ["metric_snapshot", "case_lookup", "order_profile"],
        )
        metric_result = registry.execute(
            "metric_snapshot",
            country="BR",
            channel="credit_card",
            time_range="recent_24h",
        )
        order_result = registry.execute("order_profile", order_id="O10001")

        self.assertTrue(metric_result.success)
        self.assertEqual(metric_result.payload["country"], "BR")
        self.assertTrue(order_result.success)
        self.assertEqual(order_result.payload["order_id"], "O10001")


if __name__ == "__main__":
    unittest.main()
