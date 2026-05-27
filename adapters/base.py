from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable

from core.models import KnowledgeDocument, ToolResult


class KnowledgeSource(ABC):
    """Source of knowledge documents for retrieval indexing."""

    @abstractmethod
    def load(self) -> Iterable[KnowledgeDocument]:
        """Return the documents that should be indexed."""


class ToolAdapter(ABC):
    """Adapter interface for runtime tool invocation."""

    name: str

    @abstractmethod
    def invoke(self, **kwargs: Any) -> ToolResult:
        """Execute the adapter and return a structured tool result."""

