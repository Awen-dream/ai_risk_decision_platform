from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from adapters.base import KnowledgeSource
from core.models import KnowledgeDocument
from retrieval.knowledge_base import RetrievalService


@dataclass
class KnowledgeSyncResult:
    documents_loaded: int
    source_count: int


class KnowledgeSyncService:
    """Reloads retrieval documents from configured knowledge sources."""

    def __init__(
        self,
        retrieval: RetrievalService,
        sources: Iterable[KnowledgeSource],
    ) -> None:
        self._retrieval = retrieval
        self._sources: List[KnowledgeSource] = list(sources)

    def reload(self) -> KnowledgeSyncResult:
        documents: List[KnowledgeDocument] = []
        for source in self._sources:
            documents.extend(list(source.load()))
        self._retrieval.replace_documents(documents)
        return KnowledgeSyncResult(
            documents_loaded=len(documents),
            source_count=len(self._sources),
        )
