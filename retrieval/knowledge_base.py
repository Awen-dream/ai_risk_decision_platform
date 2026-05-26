from __future__ import annotations

import re
from dataclasses import dataclass

from core.models import KnowledgeDocument


TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+")


@dataclass
class SearchHit:
    document: KnowledgeDocument
    score: int


class RetrievalService:
    """Very small in-memory retrieval service for demo and test usage."""

    def __init__(self) -> None:
        self._documents: list[KnowledgeDocument] = []

    def add_documents(self, documents: list[KnowledgeDocument]) -> None:
        self._documents.extend(documents)

    def search(self, query: str, top_k: int = 3) -> list[KnowledgeDocument]:
        query_terms = self._tokenize(query)
        hits: list[SearchHit] = []
        for document in self._documents:
            haystack = " ".join((document.title, document.content, " ".join(document.tags)))
            content_terms = self._tokenize(haystack)
            score = 0
            for term in query_terms:
                if term in content_terms:
                    score += 3
                    continue
                if any(term in candidate or candidate in term for candidate in content_terms):
                    score += 1
            if query.lower() in haystack.lower():
                score += 5
            if score > 0:
                hits.append(SearchHit(document=document, score=score))
        hits.sort(key=lambda hit: (-hit.score, hit.document.doc_id))
        return [hit.document for hit in hits[:top_k]]

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        tokens: set[str] = set()
        for token in TOKEN_PATTERN.findall(text):
            lowered = token.lower()
            tokens.add(lowered)
            if len(token) >= 4 and any("\u4e00" <= char <= "\u9fff" for char in token):
                for index in range(len(token) - 1):
                    tokens.add(token[index : index + 2].lower())
        return tokens
