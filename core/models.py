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
    status: str = "success"
    error: str | None = None
    error_type: str | None = None

    @property
    def success(self) -> bool:
        return self.status == "success"

    @property
    def degraded(self) -> bool:
        return self.status == "degraded"

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    @classmethod
    def success_result(cls, name: str, payload: Any, summary: str) -> "ToolResult":
        return cls(name=name, payload=payload, summary=summary, status="success")

    @classmethod
    def degraded_result(
        cls,
        name: str,
        payload: Any,
        summary: str,
        *,
        error: str | None = None,
        error_type: str | None = None,
    ) -> "ToolResult":
        return cls(
            name=name,
            payload=payload,
            summary=summary,
            status="degraded",
            error=error,
            error_type=error_type,
        )

    @classmethod
    def failed_result(
        cls,
        name: str,
        payload: Any,
        summary: str,
        *,
        error: str | None = None,
        error_type: str | None = None,
    ) -> "ToolResult":
        return cls(
            name=name,
            payload=payload,
            summary=summary,
            status="failed",
            error=error,
            error_type=error_type,
        )


@dataclass
class ToolTrace:
    name: str
    status: str
    summary: str
    payload: Any


@dataclass
class PlannerTraceStep:
    step: str
    selected: bool
    reason: str


@dataclass
class AgentResponse:
    agent_name: str
    summary: str = ""
    intent: str | None = None
    plan_steps: list[str] = field(default_factory=list)
    planner_trace: list[PlannerTraceStep] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    tool_traces: list[ToolTrace] = field(default_factory=list)
    confidence: float = 0.0
    artifacts: dict[str, Any] = field(default_factory=dict)

    def record_tool_trace(self, name: str, result: ToolResult) -> ToolTrace:
        summary = result.summary
        if result.failed:
            summary = result.error or result.summary or "unknown error"
        trace = ToolTrace(
            name=name,
            status=result.status,
            summary=summary,
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
    confidence: float = 0.0
    intent: str | None = None
    plan_steps: list[str] = field(default_factory=list)
    planner_trace: list[PlannerTraceStep] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionRecord:
    session_id: str
    turns: list[SessionTurn] = field(default_factory=list)


@dataclass
class StrategyRecommendationRecord:
    strategy_id: str
    current_threshold: float
    recommended_threshold: float
    validation_window: str
    rationale: str


@dataclass
class WorkflowCaseHistoryEntry:
    event_type: str
    status: str
    summary: str


@dataclass
class WorkflowCase:
    case_id: str
    session_id: str
    turn_index: int
    title: str
    summary: str
    status: str
    severity: str
    source_agent: str
    intent: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    suggested_actions: list[str] = field(default_factory=list)
    strategy_recommendation: StrategyRecommendationRecord | None = None
    history: list[WorkflowCaseHistoryEntry] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
