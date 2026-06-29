from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.memory import public_context_keys
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
    long_term_memory_refs: list[dict[str, Any]] | None = None,
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
        "context_keys": public_context_keys(request.context),
        "entities": _extract_entities(request.context),
        "session_memory_refs": _session_memory_refs(request.context),
        "long_term_memory_refs": list(long_term_memory_refs or []),
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


def evaluate_global_plan_quality(
    *,
    global_plan: GlobalPlan,
    evidence_graph: dict[str, Any],
    working_memory: dict[str, Any],
    child_responses: list[tuple[str, AgentResponse]],
) -> dict[str, Any]:
    evidence_summary = evidence_graph.get("summary", {})
    evidence_count = int(evidence_summary.get("evidence_count", 0) or 0)
    evidence_gap_count = int(evidence_summary.get("evidence_gap_count", 0) or 0)
    step_count = len(global_plan.steps)
    covered_steps = {
        label
        for label, child in child_responses
        if child.tool_traces or child.evidence or child.findings
    }
    expected_steps = {step.label for step in global_plan.steps}
    coverage_score = _ratio(len(covered_steps & expected_steps), max(1, step_count))
    evidence_score = min(1.0, evidence_count / max(1, step_count))
    gap_penalty = min(0.6, evidence_gap_count * 0.2)
    gap_score = max(0.0, 1.0 - gap_penalty)
    memory_refs = (
        len(working_memory.get("session_memory_refs", []) or [])
        + len(working_memory.get("long_term_memory_refs", []) or [])
    )
    memory_score = 1.0 if memory_refs else 0.5
    audit_score = _audit_score(global_plan, evidence_graph, working_memory)
    overall_score = round(
        (
            coverage_score * 0.30
            + evidence_score * 0.30
            + gap_score * 0.20
            + memory_score * 0.10
            + audit_score * 0.10
        ),
        3,
    )
    blocking_gaps = [
        gap
        for gap in working_memory.get("open_evidence_gaps", []) or []
        if isinstance(gap, dict) and gap.get("blocking")
    ]
    recommended_next_steps: list[str] = []
    if blocking_gaps:
        recommended_next_steps.append("优先补齐 blocking evidence gaps 后再收敛结论。")
    if evidence_score < 1.0:
        recommended_next_steps.append("补充每个全局步骤的至少一条可引用证据。")
    if not memory_refs:
        recommended_next_steps.append("如为持续案件，建议关联 session 或历史 case memory。")
    if not recommended_next_steps:
        recommended_next_steps.append("当前全局计划证据链可进入人工复核或策略动作。")
    return {
        "version": "v3d",
        "overall_score": overall_score,
        "status": "passed" if overall_score >= 0.75 and not blocking_gaps else "needs_attention",
        "scores": {
            "plan_coverage": round(coverage_score, 3),
            "evidence_sufficiency": round(evidence_score, 3),
            "evidence_gap_control": round(gap_score, 3),
            "memory_utilization": round(memory_score, 3),
            "auditability": round(audit_score, 3),
        },
        "diagnostics": {
            "step_count": step_count,
            "covered_step_count": len(covered_steps & expected_steps),
            "evidence_count": evidence_count,
            "evidence_gap_count": evidence_gap_count,
            "memory_ref_count": memory_refs,
            "blocking_gap_count": len(blocking_gaps),
        },
        "recommended_next_steps": recommended_next_steps,
    }


def _audit_score(
    global_plan: GlobalPlan,
    evidence_graph: dict[str, Any],
    working_memory: dict[str, Any],
) -> float:
    checks = [
        bool(global_plan.steps),
        all(step.reason for step in global_plan.steps),
        bool(evidence_graph.get("nodes")),
        bool(evidence_graph.get("edges")),
        working_memory.get("version") == "v3a",
    ]
    return _ratio(sum(checks), len(checks))


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return numerator / denominator


def _extract_entities(context: dict[str, Any]) -> dict[str, str]:
    entity_keys = ("order_id", "strategy_id", "entity_id", "user_id", "country", "channel")
    return {
        key: str(context[key])
        for key in entity_keys
        if key in context and context[key] is not None
    }


def _session_memory_refs(context: dict[str, Any]) -> list[dict[str, Any]]:
    memory = context.get("_session_memory")
    if not isinstance(memory, dict):
        return []
    turns = memory.get("turns", [])
    if not isinstance(turns, list):
        return []
    refs: list[dict[str, Any]] = []
    for item in turns:
        if not isinstance(item, dict):
            continue
        refs.append(
            {
                "turn_index": item.get("turn_index"),
                "agent_name": item.get("agent_name"),
                "intent": item.get("intent"),
                "summary": item.get("summary"),
                "confidence": item.get("confidence"),
                "evidence_sources": list(item.get("evidence_sources", []))
                if isinstance(item.get("evidence_sources"), list)
                else [],
                "open_evidence_gap_sources": list(item.get("open_evidence_gap_sources", []))
                if isinstance(item.get("open_evidence_gap_sources"), list)
                else [],
            }
        )
    return refs
