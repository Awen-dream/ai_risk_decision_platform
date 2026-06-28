from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from core.models import EvidenceGap, EvidenceRecord, PlannerTraceStep, SessionTurn, ToolSelectionReason


@dataclass
class SessionTurnView:
    agent_name: str
    query: str
    context: dict[str, Any]
    summary: str
    title: str
    status: str
    agent_group: str
    badge: str
    severity: str
    expanded_sections: list[str] = field(default_factory=list)
    intent: Optional[str] = None
    thought_summary: str = ""
    plan_steps: list[str] = field(default_factory=list)
    planner_trace: list[PlannerTraceStep] = field(default_factory=list)
    tool_selection_reason: list[ToolSelectionReason] = field(default_factory=list)
    evidence_gap: list[EvidenceGap] = field(default_factory=list)
    confidence: float = 0.0
    evidence: list[EvidenceRecord] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass
class TimelineItemView:
    turn_index: int
    agent_name: str
    title: str
    status: str
    agent_group: str
    badge: str
    severity: str
    summary: str
    intent: Optional[str] = None
    plan_steps: list[str] = field(default_factory=list)
    expanded_sections: list[str] = field(default_factory=list)


def build_turn_title(agent_name: str) -> str:
    return {
        "knowledge": "知识问答",
        "investigation": "风险调查",
        "strategy": "策略分析",
        "graph": "图谱分析",
        "copilot": "联合分析",
    }.get(agent_name, "智能体执行")


def build_agent_group(agent_name: str) -> str:
    return {
        "knowledge": "knowledge",
        "investigation": "analysis",
        "strategy": "analysis",
        "graph": "analysis",
        "copilot": "workflow",
    }.get(agent_name, "analysis")


def build_expanded_sections(agent_name: str) -> list[str]:
    return {
        "knowledge": ["summary", "citations"],
        "investigation": ["summary", "findings", "tool_traces"],
        "strategy": ["summary", "findings", "tool_traces"],
        "graph": ["summary", "findings", "tool_traces"],
        "copilot": ["intent", "plan", "decision", "planner_trace", "findings", "actions"],
    }.get(agent_name, ["summary"])


def build_badge(agent_name: str, intent: Optional[str]) -> str:
    if agent_name == "copilot":
        return "workflow"
    if agent_name == "graph" or intent in {"fraud_ring", "order_case"}:
        return "risk-graph"
    if agent_name == "strategy" or intent in {"strategy_review", "composite"}:
        return "strategy"
    if agent_name == "knowledge":
        return "knowledge"
    return "analysis"


def build_severity(agent_name: str, intent: Optional[str]) -> str:
    if agent_name == "copilot" and intent == "composite":
        return "high"
    if agent_name == "graph" or intent == "fraud_ring":
        return "high"
    if agent_name == "strategy" or intent == "strategy_review":
        return "medium"
    if agent_name == "investigation" or intent == "order_case":
        return "medium"
    return "low"


def build_session_turn_view(turn: SessionTurn) -> SessionTurnView:
    return SessionTurnView(
        agent_name=turn.agent_name,
        query=turn.query,
        context=turn.context,
        summary=turn.summary,
        title=build_turn_title(turn.agent_name),
        status="completed",
        agent_group=build_agent_group(turn.agent_name),
        badge=build_badge(turn.agent_name, turn.intent),
        severity=build_severity(turn.agent_name, turn.intent),
        expanded_sections=build_expanded_sections(turn.agent_name),
        intent=turn.intent,
        thought_summary=turn.thought_summary,
        plan_steps=list(turn.plan_steps),
        planner_trace=[
            PlannerTraceStep(
                step=trace.step,
                selected=trace.selected,
                reason=trace.reason,
            )
            for trace in turn.planner_trace
        ],
        tool_selection_reason=[
            ToolSelectionReason(
                tool=reason.tool,
                selected=reason.selected,
                reason=reason.reason,
            )
            for reason in turn.tool_selection_reason
        ],
        evidence_gap=[
            EvidenceGap(
                gap=gap.gap,
                source=gap.source,
                severity=gap.severity,
                next_action=gap.next_action,
                blocking=gap.blocking,
            )
            for gap in turn.evidence_gap
        ],
        confidence=turn.confidence,
        evidence=[
            EvidenceRecord(
                source=evidence.source,
                source_type=evidence.source_type,
                summary=evidence.summary,
                payload=evidence.payload,
                confidence=evidence.confidence,
                observed_at=evidence.observed_at,
            )
            for evidence in turn.evidence
        ],
        artifacts=dict(turn.artifacts),
    )


def build_timeline_items(turns: list[SessionTurnView]) -> list[TimelineItemView]:
    return [
        TimelineItemView(
            turn_index=index,
            agent_name=turn.agent_name,
            title=turn.title,
            status=turn.status,
            agent_group=turn.agent_group,
            badge=turn.badge,
            severity=turn.severity,
            summary=turn.summary,
            intent=turn.intent,
            plan_steps=list(turn.plan_steps),
            expanded_sections=list(turn.expanded_sections),
        )
        for index, turn in enumerate(turns, start=1)
    ]
