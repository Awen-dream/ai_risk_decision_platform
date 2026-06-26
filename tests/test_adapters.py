from __future__ import annotations

import unittest

from adapters.in_memory import (
    InMemoryCaseLookupAdapter,
    InMemoryDashboardSnapshotAdapter,
    InMemoryKnowledgeSource,
    InMemoryMetricSnapshotAdapter,
    InMemoryOrderProfileAdapter,
    InMemoryRuleExplainAdapter,
    InMemorySqlQueryAdapter,
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
        registry.register_adapter(InMemorySqlQueryAdapter())
        registry.register_adapter(InMemoryDashboardSnapshotAdapter())
        registry.register_adapter(InMemoryRuleExplainAdapter())

        self.assertEqual(
            registry.list_tools(),
            [
                "metric_snapshot",
                "case_lookup",
                "order_profile",
                "sql_query",
                "dashboard_snapshot",
                "rule_explain",
            ],
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

    def test_tool_registry_returns_failed_result_for_handler_exception(self) -> None:
        registry = ToolRegistry()

        def exploding_handler(**kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError(f"boom: {kwargs['order_id']}")

        registry.register("order_profile", exploding_handler)

        result = registry.execute("order_profile", order_id="O99999")

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_type, "RuntimeError")
        self.assertIn("boom: O99999", result.error or "")

    def test_metric_snapshot_adapter_marks_invalid_payload_as_failed(self) -> None:
        class BrokenMetricProvider:
            def get_snapshot(self, country: str, channel: str, time_range: str):  # type: ignore[no-untyped-def]
                return {"country": country, "channel": channel}

        adapter = InMemoryMetricSnapshotAdapter(provider=BrokenMetricProvider())

        result = adapter.invoke(country="BR", channel="credit_card", time_range="recent_24h")

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_type, "invalid_payload")
        self.assertIn("metric_name", result.error or "")

    def test_case_lookup_adapter_marks_invalid_payload_as_failed(self) -> None:
        class BrokenCaseProvider:
            def get_cases(self, country: str, channel: str):  # type: ignore[no-untyped-def]
                return [{"case_id": "BR-1"}]

        adapter = InMemoryCaseLookupAdapter(provider=BrokenCaseProvider())

        result = adapter.invoke(country="BR", channel="credit_card")

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_type, "invalid_payload")
        self.assertIn("title", result.error or "")

    def test_phase1_adapters_return_expected_payloads(self) -> None:
        sql_result = InMemorySqlQueryAdapter().invoke(
            query_name="metric_breakdown",
            parameters={"country": "BR", "channel": "credit_card", "time_range": "recent_24h"},
            limit=2,
        )
        dashboard_result = InMemoryDashboardSnapshotAdapter().invoke(
            dashboard_id="risk_overview",
            country="BR",
            channel="credit_card",
            time_range="recent_24h",
        )
        rule_result = InMemoryRuleExplainAdapter().invoke(order_id="O10001")

        self.assertTrue(sql_result.success)
        self.assertEqual(sql_result.payload["row_count"], 2)
        self.assertTrue(dashboard_result.success)
        self.assertEqual(dashboard_result.payload["largest_segment"], "shared_device")
        self.assertTrue(rule_result.success)
        self.assertEqual(rule_result.payload["subject_id"], "O10001")


if __name__ == "__main__":
    unittest.main()
