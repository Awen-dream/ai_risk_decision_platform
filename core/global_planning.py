from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import AgentRequest, AgentResponse


STEP_AGENT_BY_LABEL = {
    "调查": "investigation",
    "策略": "strategy",
    "图谱": "graph",
}
EXPECTED_OUTPUTS_BY_LABEL = {
    "调查": ["risk_scope", "primary_evidence", "investigation_findings"],
    "策略": ["strategy_profile", "simulation_guidance", "rule_or_graph_context"],
    "图谱": ["relation_network", "community_risk", "key_path"],
}


@dataclass(frozen=True)
class GlobalPlanStep:
    step_id: str
    label: str
    agent_name: str
    reason: str
    depends_on: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GlobalPlan:
    version: str
    objective: str
    intent: str
    steps: list[GlobalPlanStep]
    constraints: dict[str, Any]
    audit_contract: dict[str, Any]

    def to_artifact(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "objective": self.objective,
            "intent": self.intent,
            "steps": [
                {
                    "step_id": step.step_id,
                    "label": step.label,
                    "agent_name": step.agent_name,
                    "reason": step.reason,
                    "depends_on": list(step.depends_on),
                    "expected_outputs": list(step.expected_outputs),
                }
                for step in self.steps
            ],
            "constraints": dict(self.constraints),
            "audit_contract": dict(self.audit_contract),
        }


def build_global_plan(
    *,
    request: AgentRequest,
    intent: str,
    planner_trace,
    plan_steps,
    planner_backend: str,
    fallback_used: bool,
    validation_errors: list[str],
) -> GlobalPlan:
    selected_reasons = {trace.step: trace.reason for trace in planner_trace if trace.selected}
    steps: list[GlobalPlanStep] = []
    previous_step_id = ""
    for index, step in enumerate(plan_steps, start=1):
        step_id = f"global_step_{index}"
        steps.append(
            GlobalPlanStep(
                step_id=step_id,
                label=step.label,
                agent_name=STEP_AGENT_BY_LABEL.get(step.label, "unknown"),
                reason=selected_reasons.get(step.label, step.reason),
                depends_on=[previous_step_id] if previous_step_id else [],
                expected_outputs=list(EXPECTED_OUTPUTS_BY_LABEL.get(step.label, ())),
            )
        )
        previous_step_id = step_id

    return GlobalPlan(
        version="v3a",
        objective=request.query,
        intent=intent,
        steps=steps,
        constraints={
            "max_global_steps": 3,
            "selected_step_count": len(steps),
            "planner_backend": planner_backend,
            "fallback_used": fallback_used,
            "validation_error_count": len(validation_errors),
            "requires_investigation_anchor": True,
        },
        audit_contract={
            "requires_step_reason": True,
            "requires_child_tool_trace": True,
            "requires_evidence_graph": True,
            "requires_working_memory_snapshot": True,
        },
    )


def build_working_memory_snapshot(
    *,
    request: AgentRequest,
    child_responses: list[tuple[str, AgentResponse]],
) -> dict[str, Any]:
    open_gaps = []
    for label, child in child_responses:
        for gap in child.evidence_gap:
            open_gaps.append(
                {
                    "step": label,
                    "source": gap.source,
                    "gap": gap.gap,
                    "severity": gap.severity,
                    "blocking": gap.blocking,
                    "next_action": gap.next_action,
                }
            )
    citation_refs = []
    seen_citations: set[str] = set()
    for label, child in child_responses:
        for citation in child.citations:
            key = f"{label}:{citation.doc_id}"
            if key in seen_citations:
                continue
            seen_citations.add(key)
            citation_refs.append(
                {
                    "step": label,
                    "doc_id": citation.doc_id,
                    "title": citation.title,
                    "source_type": citation.source_type,
                }
            )
    return {
        "version": "v3a",
        "scope": "short_term",
        "query": request.query,
        "context_keys": sorted(request.context),
        "entities": _extract_entities(request.context),
        "child_summaries": [
            {
                "step": label,
                "agent_name": child.agent_name,
                "summary": child.summary,
                "confidence": child.confidence,
            }
            for label, child in child_responses
        ],
        "open_evidence_gaps": open_gaps,
        "retrieved_memory_refs": citation_refs,
    }


def build_evidence_graph(
    *,
    request: AgentRequest,
    global_plan: GlobalPlan,
    child_responses: list[tuple[str, AgentResponse]],
    risk_decision: dict[str, Any],
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {
            "id": "objective",
            "type": "objective",
            "label": request.query,
        }
    ]
    edges: list[dict[str, str]] = []
    step_id_by_label = {step.label: step.step_id for step in global_plan.steps}
    for step in global_plan.steps:
        nodes.append(
            {
                "id": step.step_id,
                "type": "plan_step",
                "label": step.label,
                "agent_name": step.agent_name,
            }
        )
        edges.append({"source": "objective", "target": step.step_id, "relation": "decomposes_to"})
        for dependency in step.depends_on:
            edges.append({"source": dependency, "target": step.step_id, "relation": "precedes"})

    evidence_index = 0
    gap_index = 0
    for label, child in child_responses:
        step_id = step_id_by_label.get(label, "objective")
        for evidence in child.evidence:
            evidence_index += 1
            evidence_id = f"evidence_{evidence_index}"
            nodes.append(
                {
                    "id": evidence_id,
                    "type": "evidence",
                    "label": evidence.summary,
                    "source": evidence.source,
                    "confidence": evidence.confidence,
                }
            )
            edges.append({"source": step_id, "target": evidence_id, "relation": "produces"})
        for gap in child.evidence_gap:
            gap_index += 1
            gap_id = f"gap_{gap_index}"
            nodes.append(
                {
                    "id": gap_id,
                    "type": "evidence_gap",
                    "label": gap.gap,
                    "source": gap.source,
                    "severity": gap.severity,
                    "blocking": gap.blocking,
                }
            )
            edges.append({"source": step_id, "target": gap_id, "relation": "has_gap"})

    nodes.append(
        {
            "id": "risk_decision",
            "type": "decision",
            "label": str(risk_decision.get("decision", "unknown")),
            "risk_level": risk_decision.get("risk_level"),
            "recommended_action": risk_decision.get("recommended_action"),
        }
    )
    for node in nodes:
        if node["type"] == "evidence":
            edges.append({"source": node["id"], "target": "risk_decision", "relation": "supports"})
        if node["type"] == "evidence_gap":
            edges.append({"source": node["id"], "target": "risk_decision", "relation": "limits"})

    return {
        "version": "v3a",
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "evidence_count": evidence_index,
            "evidence_gap_count": gap_index,
        },
    }


def _extract_entities(context: dict[str, Any]) -> dict[str, str]:
    entity_keys = ("order_id", "strategy_id", "entity_id", "user_id", "country", "channel")
    return {
        key: str(context[key])
        for key in entity_keys
        if key in context and context[key] is not None
    }
