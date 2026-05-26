from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentRequest:
    query: str
    context: dict[str, Any] = field(default_factory=dict)
    user_role: str = "risk_analyst"


@dataclass
class KnowledgeDocument:
    doc_id: str
    title: str
    source_type: str
    content: str
    tags: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        return self.content.split("。", 1)[0].strip() + "。"


@dataclass
class Citation:
    doc_id: str
    title: str
    source_type: str
    snippet: str

    @classmethod
    def from_document(cls, document: KnowledgeDocument, snippet_length: int) -> "Citation":
        snippet = document.content[:snippet_length].strip()
        return cls(
            doc_id=document.doc_id,
            title=document.title,
            source_type=document.source_type,
            snippet=snippet,
        )


@dataclass
class ToolResult:
    name: str
    payload: Any
    summary: str
    success: bool = True
    error: str | None = None


@dataclass
class ToolTrace:
    name: str
    status: str
    summary: str
    payload: Any


@dataclass
class AgentResponse:
    agent_name: str
    summary: str = ""
    findings: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    tool_traces: list[ToolTrace] = field(default_factory=list)
    confidence: float = 0.0

    def record_tool_trace(self, name: str, result: ToolResult) -> ToolTrace:
        status = "success" if result.success else "failed"
        trace = ToolTrace(
            name=name,
            status=status,
            summary=result.summary if result.success else result.error or "unknown error",
            payload=result.payload,
        )
        self.tool_traces.append(trace)
        return trace


@dataclass
class SessionTurn:
    agent_name: str
    query: str
    context: dict[str, Any]
    summary: str
    confidence: float


@dataclass
class SessionRecord:
    session_id: str
    turns: list[SessionTurn] = field(default_factory=list)
