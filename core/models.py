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
class EvidenceRecord:
    source: str
    source_type: str
    summary: str
    payload: Any
    confidence: float = 0.0
    observed_at: str | None = None


@dataclass
class PlannerTraceStep:
    step: str
    selected: bool
    reason: str


@dataclass
class ToolSelectionReason:
    tool: str
    selected: bool
    reason: str


@dataclass
class EvidenceGap:
    gap: str
    source: str
    severity: str = "medium"
    next_action: str = ""
    blocking: bool = False


@dataclass
class AgentIntermediateState:
    thought_summary: str = ""
    tool_selection_reason: list[ToolSelectionReason] = field(default_factory=list)
    evidence_gap: list[EvidenceGap] = field(default_factory=list)
    step_budget: int = 0
    selected_steps: list[str] = field(default_factory=list)
    planner_backend: str = ""
    fallback_used: bool = False
    validation_errors: list[str] = field(default_factory=list)

    def to_artifact(self) -> dict[str, Any]:
        return {
            "thought_summary": self.thought_summary,
            "tool_selection_reason": [
                {
                    "tool": reason.tool,
                    "selected": reason.selected,
                    "reason": reason.reason,
                }
                for reason in self.tool_selection_reason
            ],
            "evidence_gap": [
                {
                    "gap": gap.gap,
                    "source": gap.source,
                    "severity": gap.severity,
                    "next_action": gap.next_action,
                    "blocking": gap.blocking,
                }
                for gap in self.evidence_gap
            ],
            "step_budget": self.step_budget,
            "selected_steps": list(self.selected_steps),
            "backend": self.planner_backend,
            "planner_backend": self.planner_backend,
            "fallback_used": self.fallback_used,
            "validation_errors": list(self.validation_errors),
        }


@dataclass
class AgentResponse:
    agent_name: str
    summary: str = ""
    intent: str | None = None
    thought_summary: str = ""
    plan_steps: list[str] = field(default_factory=list)
    planner_trace: list[PlannerTraceStep] = field(default_factory=list)
    tool_selection_reason: list[ToolSelectionReason] = field(default_factory=list)
    evidence_gap: list[EvidenceGap] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    tool_traces: list[ToolTrace] = field(default_factory=list)
    evidence: list[EvidenceRecord] = field(default_factory=list)
    confidence: float = 0.0
    artifacts: dict[str, Any] = field(default_factory=dict)

    def attach_intermediate_state(self, state: AgentIntermediateState) -> None:
        self.thought_summary = state.thought_summary
        self.tool_selection_reason = list(state.tool_selection_reason)
        self.evidence_gap = list(state.evidence_gap)
        self.artifacts["tool_using_plan"] = state.to_artifact()

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

    def record_evidence(
        self,
        *,
        source: str,
        source_type: str,
        summary: str,
        payload: Any,
        confidence: float = 0.0,
        observed_at: str | None = None,
    ) -> EvidenceRecord:
        evidence = EvidenceRecord(
            source=source,
            source_type=source_type,
            summary=summary,
            payload=payload,
            confidence=confidence,
            observed_at=observed_at,
        )
        self.evidence.append(evidence)
        return evidence


@dataclass
class SessionTurn:
    agent_name: str
    query: str
    context: dict[str, Any]
    summary: str
    confidence: float = 0.0
    intent: str | None = None
    thought_summary: str = ""
    plan_steps: list[str] = field(default_factory=list)
    planner_trace: list[PlannerTraceStep] = field(default_factory=list)
    tool_selection_reason: list[ToolSelectionReason] = field(default_factory=list)
    evidence_gap: list[EvidenceGap] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    evidence: list[EvidenceRecord] = field(default_factory=list)
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
class RiskActionPlanRecord:
    queue: str
    priority: str
    sla_hours: int
    owner_role: str
    next_actions: list[str] = field(default_factory=list)
    status: str = "queued"
    due_at: str | None = None
    assigned_to: str | None = None
    completed_at: str | None = None
    outcome: str | None = None


@dataclass
class RiskDecisionRecord:
    decision: str
    risk_level: str
    recommended_action: str
    evidence_strength: str
    confidence: float
    rationale: str
    escalation_reason: str | None = None
    evidence: list[str] = field(default_factory=list)
    policy_controls: list[str] = field(default_factory=list)
    action_plan: RiskActionPlanRecord | None = None


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
    risk_decision: RiskDecisionRecord | None = None
    history: list[WorkflowCaseHistoryEntry] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
