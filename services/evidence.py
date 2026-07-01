from __future__ import annotations

from collections import Counter
from typing import Any

from core.models import AgentResponse, SessionTurn


def build_evidence_panel(
    response: AgentResponse,
    *,
    scope: str = "agent",
) -> dict[str, Any]:
    evidence_by_type = Counter(item.evidence_type for item in response.evidence)
    evidence_by_source_type = Counter(item.source_type for item in response.evidence)
    tool_status_counts = Counter(trace.status for trace in response.tool_traces)

    items = [
        {
            "evidence_id": item.evidence_id,
            "evidence_type": item.evidence_type,
            "source": item.source,
            "source_label": item.source_label,
            "source_type": item.source_type,
            "source_agent": item.source_agent,
            "source_tool": item.source_tool,
            "summary": item.summary,
            "payload": item.payload,
            "confidence": item.confidence,
            "status": item.status,
            "tags": list(item.tags),
            "observed_at": item.observed_at,
        }
        for item in sorted(
            response.evidence,
            key=lambda value: (value.confidence, value.observed_at or ""),
            reverse=True,
        )
    ]

    gaps = [
        {
            "source": gap.source,
            "gap": gap.gap,
            "severity": gap.severity,
            "blocking": gap.blocking,
            "next_action": gap.next_action,
        }
        for gap in response.evidence_gap
    ]

    citations = [
        {
            "doc_id": citation.doc_id,
            "title": citation.title,
            "source_type": citation.source_type,
            "snippet": citation.snippet,
        }
        for citation in response.citations
    ]

    tool_traces = [
        {
            "name": trace.name,
            "status": trace.status,
            "summary": trace.summary,
        }
        for trace in response.tool_traces
    ]

    return {
        "version": "v1",
        "scope": scope,
        "summary": {
            "evidence_count": len(items),
            "evidence_gap_count": len(gaps),
            "citation_count": len(citations),
            "tool_trace_count": len(tool_traces),
            "failed_tool_count": tool_status_counts.get("failed", 0),
            "degraded_tool_count": tool_status_counts.get("degraded", 0),
            "evidence_by_type": dict(evidence_by_type),
            "evidence_by_source_type": dict(evidence_by_source_type),
            "top_sources": [item["source_label"] for item in items[:3]],
        },
        "items": items,
        "gaps": gaps,
        "citations": citations,
        "tool_traces": tool_traces,
    }


def build_child_evidence_panels(
    child_responses: list[tuple[str, AgentResponse]],
) -> dict[str, dict[str, Any]]:
    return {
        label: build_evidence_panel(child, scope=f"child:{child.agent_name}")
        for label, child in child_responses
    }


def build_session_turn_evidence_panel(
    turn: SessionTurn,
    *,
    scope: str = "session_turn",
) -> dict[str, Any]:
    evidence_by_type = Counter(item.evidence_type for item in turn.evidence)
    evidence_by_source_type = Counter(item.source_type for item in turn.evidence)

    items = [
        {
            "evidence_id": item.evidence_id,
            "evidence_type": item.evidence_type,
            "source": item.source,
            "source_label": item.source_label,
            "source_type": item.source_type,
            "source_agent": item.source_agent,
            "source_tool": item.source_tool,
            "summary": item.summary,
            "payload": item.payload,
            "confidence": item.confidence,
            "status": item.status,
            "tags": list(item.tags),
            "observed_at": item.observed_at,
        }
        for item in sorted(
            turn.evidence,
            key=lambda value: (value.confidence, value.observed_at or ""),
            reverse=True,
        )
    ]

    gaps = [
        {
            "source": gap.source,
            "gap": gap.gap,
            "severity": gap.severity,
            "blocking": gap.blocking,
            "next_action": gap.next_action,
        }
        for gap in turn.evidence_gap
    ]

    return {
        "version": "v1",
        "scope": scope,
        "summary": {
            "evidence_count": len(items),
            "evidence_gap_count": len(gaps),
            "citation_count": 0,
            "tool_trace_count": 0,
            "failed_tool_count": 0,
            "degraded_tool_count": 0,
            "evidence_by_type": dict(evidence_by_type),
            "evidence_by_source_type": dict(evidence_by_source_type),
            "top_sources": [item["source_label"] for item in items[:3]],
        },
        "items": items,
        "gaps": gaps,
        "citations": [],
        "tool_traces": [],
    }
