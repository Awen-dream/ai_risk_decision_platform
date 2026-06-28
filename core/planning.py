from __future__ import annotations

from core.models import (
    AgentIntermediateState,
    EvidenceGap,
    PlannerTraceStep,
    ToolSelectionReason,
    ToolTrace,
)


def build_tool_selection_reason(
    planner_trace: list[PlannerTraceStep],
) -> list[ToolSelectionReason]:
    return [
        ToolSelectionReason(
            tool=trace.step,
            selected=trace.selected,
            reason=trace.reason,
        )
        for trace in planner_trace
    ]


def build_tool_using_state(
    *,
    thought_summary: str,
    planner_trace: list[PlannerTraceStep],
    selected_steps: list[str],
    step_budget: int,
    planner_backend: str,
    fallback_used: bool,
    validation_errors: list[str],
    evidence_gap: list[EvidenceGap] | None = None,
) -> AgentIntermediateState:
    return AgentIntermediateState(
        thought_summary=thought_summary,
        tool_selection_reason=build_tool_selection_reason(planner_trace),
        evidence_gap=list(evidence_gap or []),
        step_budget=step_budget,
        selected_steps=list(selected_steps),
        planner_backend=planner_backend,
        fallback_used=fallback_used,
        validation_errors=list(validation_errors),
    )


def evidence_gaps_from_traces(
    traces: list[ToolTrace],
    *,
    label_by_tool: dict[str, str],
    next_action_by_tool: dict[str, str],
) -> list[EvidenceGap]:
    gaps: list[EvidenceGap] = []
    for trace in traces:
        if trace.status == "success":
            continue
        label = label_by_tool.get(trace.name, trace.name)
        gaps.append(
            EvidenceGap(
                gap=f"缺少可用的{label}证据：{trace.summary}",
                source=trace.name,
                severity="high" if trace.status == "failed" else "medium",
                next_action=next_action_by_tool.get(trace.name, f"补齐 {label} 数据后重试"),
                blocking=trace.status == "failed",
            )
        )
    return gaps
