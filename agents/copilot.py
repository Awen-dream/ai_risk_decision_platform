from __future__ import annotations

from dataclasses import dataclass

from agents.base import Agent
from agents.copilot_planner import (
    CANONICAL_PLAN_STEPS,
    CopilotIntent,
    CopilotPlanCandidate,
    CopilotPlanStep,
    CopilotPlanner,
    RuleBasedCopilotPlanner,
)
from core.global_planning import (
    build_evidence_graph,
    build_global_plan,
    build_working_memory_snapshot,
)
from core.models import AgentRequest, AgentResponse, Citation, EvidenceRecord, PlannerTraceStep, ToolTrace
from services.risk_decision import RiskDecisionPolicy
from services.memory import LongTermMemoryProvider


DEFAULT_SELECTED_REASONS = {
    "调查": "所有风险问题都先从基础调查开始，统一定位对象、证据和影响范围。",
    "策略": "当前问题包含策略、阈值或仿真信号，需要补充策略效果分析。",
    "图谱": "当前问题包含实体关系、订单关联或团伙信号，需要补充关系网络分析。",
}
DEFAULT_UNSELECTED_REASONS = {
    "调查": "调查步骤为必选基础环节。",
    "策略": "当前问题缺少策略评估信号，暂不进入策略分析。",
    "图谱": "当前问题缺少团伙或关系网络信号，暂不进入图谱分析。",
}


@dataclass(frozen=True)
class ValidatedCopilotPlan:
    intent: CopilotIntent
    plan_steps: list[CopilotPlanStep]
    planner_trace: list[PlannerTraceStep]
    planner_backend: str
    fallback_used: bool
    validation_errors: list[str]
    candidate_intent: str
    candidate_steps: list[str]
    planner_error: str

    def to_artifact(self) -> dict[str, object]:
        return {
            "backend": self.planner_backend,
            "fallback_used": self.fallback_used,
            "validation_errors": list(self.validation_errors),
            "candidate_intent": self.candidate_intent,
            "candidate_steps": list(self.candidate_steps),
            "planner_error": self.planner_error,
            "final_intent": self.intent.value,
            "final_steps": [step.label for step in self.plan_steps],
        }


class CopilotAgent(Agent):
    """Workflow-style agent that composes investigation, strategy, and graph outputs."""

    name = "copilot"

    def __init__(
        self,
        investigation_agent: Agent,
        strategy_agent: Agent,
        graph_agent: Agent,
        risk_decision_policy: RiskDecisionPolicy | None = None,
        planner: CopilotPlanner | None = None,
        long_term_memory: LongTermMemoryProvider | None = None,
    ) -> None:
        self._investigation_agent = investigation_agent
        self._strategy_agent = strategy_agent
        self._graph_agent = graph_agent
        self._risk_decision_policy = risk_decision_policy or RiskDecisionPolicy.default()
        self._planner = planner or RuleBasedCopilotPlanner()
        self._fallback_planner = RuleBasedCopilotPlanner()
        self._long_term_memory = long_term_memory

    def run(self, request: AgentRequest) -> AgentResponse:
        response = AgentResponse(agent_name=self.name)
        validated_plan = self._validated_plan(request)
        response.intent = validated_plan.intent.value
        response.plan_steps = [step.label for step in validated_plan.plan_steps]
        response.planner_trace = validated_plan.planner_trace
        global_plan = build_global_plan(
            request=request,
            intent=validated_plan.intent.value,
            planner_trace=validated_plan.planner_trace,
            plan_steps=validated_plan.plan_steps,
            planner_backend=validated_plan.planner_backend,
            fallback_used=validated_plan.fallback_used,
            validation_errors=validated_plan.validation_errors,
        )

        child_responses: list[tuple[str, AgentResponse]] = []
        for step in validated_plan.plan_steps:
            if step.label == "调查":
                child_responses.append((step.label, self._investigation_agent.run(request)))
            elif step.label == "策略":
                child_responses.append((step.label, self._strategy_agent.run(request)))
            elif step.label == "图谱":
                child_responses.append((step.label, self._graph_agent.run(request)))

        response.summary = self._build_summary(validated_plan.intent, validated_plan.plan_steps, child_responses)
        response.findings = self._merge_findings(validated_plan.intent, validated_plan.plan_steps, child_responses)
        response.suggested_actions = self._merge_actions(child_responses)
        response.citations = self._merge_citations(child_responses)
        response.tool_traces = self._merge_tool_traces(child_responses)
        response.evidence = self._merge_evidence(child_responses)
        response.artifacts = self._merge_artifacts(child_responses)
        response.artifacts["planner"] = validated_plan.to_artifact()
        response.artifacts["global_plan"] = global_plan.to_artifact()
        response.confidence = round(
            sum(child.confidence for _, child in child_responses) / len(child_responses),
            2,
        )
        risk_decision = self._risk_decision_policy.evaluate(
            intent=validated_plan.intent.value,
            child_responses=child_responses,
            confidence=response.confidence,
        )
        response.artifacts["risk_decision"] = risk_decision
        long_term_memory_refs = (
            self._long_term_memory.retrieve(request)
            if self._long_term_memory is not None
            else []
        )
        response.artifacts["working_memory"] = build_working_memory_snapshot(
            request=request,
            child_responses=child_responses,
            long_term_memory_refs=long_term_memory_refs,
        )
        response.artifacts["evidence_graph"] = build_evidence_graph(
            request=request,
            global_plan=global_plan,
            child_responses=child_responses,
            risk_decision=risk_decision,
        )
        return response

    @staticmethod
    def _build_summary(
        intent: CopilotIntent,
        plan_steps: list[CopilotPlanStep],
        child_responses: list[tuple[str, AgentResponse]],
    ) -> str:
        planned_labels = " -> ".join(step.label for step in plan_steps)
        parts = [f"{label}结论：{child.summary}" for label, child in child_responses]
        return f"已完成联合分析，识别意图为 {intent.value}，执行计划为 {planned_labels}。 " + " ".join(parts)

    @staticmethod
    def _merge_findings(
        intent: CopilotIntent,
        plan_steps: list[CopilotPlanStep],
        child_responses: list[tuple[str, AgentResponse]],
    ) -> list[str]:
        findings = [f"[意图] {intent.value}"]
        findings.extend(f"[规划] {step.label}：{step.reason}" for step in plan_steps)
        for label, child in child_responses:
            findings.extend(f"[{label}] {finding}" for finding in child.findings)
        return findings

    @staticmethod
    def _merge_actions(child_responses: list[tuple[str, AgentResponse]]) -> list[str]:
        actions: list[str] = []
        seen: set[str] = set()
        for _, child in child_responses:
            for action in child.suggested_actions:
                if action not in seen:
                    seen.add(action)
                    actions.append(action)
        return actions

    @staticmethod
    def _merge_citations(child_responses: list[tuple[str, AgentResponse]]) -> list[Citation]:
        citations: list[Citation] = []
        seen: set[tuple[str, str]] = set()
        for _, child in child_responses:
            for citation in child.citations:
                key = (citation.doc_id, citation.snippet)
                if key not in seen:
                    seen.add(key)
                    citations.append(citation)
        return citations

    @staticmethod
    def _merge_tool_traces(child_responses: list[tuple[str, AgentResponse]]) -> list[ToolTrace]:
        traces: list[ToolTrace] = []
        for label, child in child_responses:
            traces.extend(
                ToolTrace(
                    name=f"{label.lower()}::{trace.name}",
                    status=trace.status,
                    summary=trace.summary,
                    payload=trace.payload,
                )
                for trace in child.tool_traces
            )
        return traces

    @staticmethod
    def _merge_evidence(child_responses: list[tuple[str, AgentResponse]]) -> list[EvidenceRecord]:
        evidence_records: list[EvidenceRecord] = []
        seen: set[tuple[str, str, str]] = set()
        for label, child in child_responses:
            for evidence in child.evidence:
                key = (label, evidence.source, evidence.summary)
                if key in seen:
                    continue
                seen.add(key)
                evidence_records.append(
                    EvidenceRecord(
                        source=f"{label.lower()}::{evidence.source}",
                        source_type=evidence.source_type,
                        summary=evidence.summary,
                        payload=evidence.payload,
                        confidence=evidence.confidence,
                        observed_at=evidence.observed_at,
                    )
                )
        return evidence_records

    @staticmethod
    def _merge_artifacts(child_responses: list[tuple[str, AgentResponse]]) -> dict[str, object]:
        artifacts: dict[str, object] = {}
        child_artifacts: dict[str, object] = {}
        for label, child in child_responses:
            artifacts.update(child.artifacts)
            child_artifacts[label] = dict(child.artifacts)
        artifacts["child_artifacts"] = child_artifacts
        return artifacts

    def _validated_plan(self, request: AgentRequest) -> ValidatedCopilotPlan:
        candidate = self._planner.plan(request)
        errors: list[str] = []

        try:
            intent = CopilotIntent(candidate.intent)
        except ValueError:
            errors.append(f"unknown intent: {candidate.intent}")
            return self._fallback_validated_plan(request, candidate, errors)

        selected_steps = self._normalize_selected_steps(candidate.selected_steps)
        if "调查" not in selected_steps:
            errors.append("candidate omitted required step: 调查")
            selected_steps.insert(0, "调查")
        if not selected_steps:
            errors.append("candidate produced no executable steps")
            return self._fallback_validated_plan(request, candidate, errors)

        plan_steps = [
            CopilotPlanStep(
                label=label,
                reason=candidate.step_reasons.get(label, DEFAULT_SELECTED_REASONS[label]),
            )
            for label in selected_steps
        ]
        return ValidatedCopilotPlan(
            intent=intent,
            plan_steps=plan_steps,
            planner_trace=self._build_planner_trace(selected_steps, candidate.step_reasons),
            planner_backend=candidate.planner_backend,
            fallback_used=False,
            validation_errors=errors,
            candidate_intent=candidate.intent,
            candidate_steps=list(candidate.selected_steps),
            planner_error=candidate.planner_error,
        )

    def _fallback_validated_plan(
        self,
        request: AgentRequest,
        candidate: CopilotPlanCandidate,
        errors: list[str],
    ) -> ValidatedCopilotPlan:
        fallback_candidate = self._fallback_planner.plan(request)
        selected_steps = self._normalize_selected_steps(fallback_candidate.selected_steps)
        plan_steps = [
            CopilotPlanStep(
                label=label,
                reason=fallback_candidate.step_reasons.get(label, DEFAULT_SELECTED_REASONS[label]),
            )
            for label in selected_steps
        ]
        return ValidatedCopilotPlan(
            intent=CopilotIntent(fallback_candidate.intent),
            plan_steps=plan_steps,
            planner_trace=self._build_planner_trace(selected_steps, fallback_candidate.step_reasons),
            planner_backend=fallback_candidate.planner_backend,
            fallback_used=True,
            validation_errors=errors,
            candidate_intent=candidate.intent,
            candidate_steps=list(candidate.selected_steps),
            planner_error=candidate.planner_error,
        )

    @staticmethod
    def _normalize_selected_steps(selected_steps: list[str]) -> list[str]:
        seen: set[str] = set()
        selected = {step for step in selected_steps if step in CANONICAL_PLAN_STEPS}
        normalized: list[str] = []
        for label in CANONICAL_PLAN_STEPS:
            if label in selected and label not in seen:
                seen.add(label)
                normalized.append(label)
        return normalized

    @staticmethod
    def _build_planner_trace(
        selected_steps: list[str],
        step_reasons: dict[str, str],
    ) -> list[PlannerTraceStep]:
        selected = set(selected_steps)
        planner_trace: list[PlannerTraceStep] = []
        for label in CANONICAL_PLAN_STEPS:
            planner_trace.append(
                PlannerTraceStep(
                    step=label,
                    selected=label in selected,
                    reason=step_reasons.get(
                        label,
                        DEFAULT_SELECTED_REASONS[label] if label in selected else DEFAULT_UNSELECTED_REASONS[label],
                    ),
                )
            )
        return planner_trace
