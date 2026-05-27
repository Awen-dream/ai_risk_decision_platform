from __future__ import annotations

from typing import Any, Iterable

from adapters.base import KnowledgeSource, ToolAdapter
from core.models import KnowledgeDocument, ToolResult
from sample_data import (
    build_case_records,
    build_knowledge_documents,
    build_metric_snapshots,
    build_order_profiles,
)


class InMemoryKnowledgeSource(KnowledgeSource):
    """Knowledge source backed by local demo documents."""

    def load(self) -> Iterable[KnowledgeDocument]:
        return build_knowledge_documents()


class InMemoryMetricSnapshotAdapter(ToolAdapter):
    name = "metric_snapshot"

    def __init__(self) -> None:
        self._records = build_metric_snapshots()

    def invoke(self, **kwargs: Any) -> ToolResult:
        return self._records(
            country=str(kwargs["country"]),
            channel=str(kwargs["channel"]),
            time_range=str(kwargs["time_range"]),
        )


class InMemoryCaseLookupAdapter(ToolAdapter):
    name = "case_lookup"

    def __init__(self) -> None:
        self._records = build_case_records()

    def invoke(self, **kwargs: Any) -> ToolResult:
        return self._records(
            country=str(kwargs["country"]),
            channel=str(kwargs["channel"]),
        )


class InMemoryOrderProfileAdapter(ToolAdapter):
    name = "order_profile"

    def __init__(self) -> None:
        self._records = build_order_profiles()

    def invoke(self, **kwargs: Any) -> ToolResult:
        return self._records(order_id=str(kwargs["order_id"]))

