from __future__ import annotations

from pathlib import Path
from typing import Iterable

from adapters.base import KnowledgeSource
from core.models import KnowledgeDocument


class DirectoryKnowledgeSource(KnowledgeSource):
    """Loads markdown knowledge documents from a directory."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def load(self) -> Iterable[KnowledgeDocument]:
        if not self._directory.exists():
            return []
        documents = []
        for path in sorted(self._directory.glob("*.md")):
            content = path.read_text(encoding="utf-8").strip()
            title, body = self._split_title_and_body(path.stem, content)
            doc_id = path.stem.upper().replace("-", "_")
            source_type = path.stem.split("-", 1)[0]
            documents.append(
                KnowledgeDocument(
                    doc_id=doc_id,
                    title=title,
                    source_type=source_type,
                    content=body,
                    tags=tuple(path.stem.split("-")),
                )
            )
        return documents

    @staticmethod
    def _split_title_and_body(fallback_title: str, content: str) -> tuple[str, str]:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if lines and lines[0].startswith("# "):
            return lines[0][2:].strip(), " ".join(lines[1:]).strip()
        return fallback_title.replace("-", " "), content

