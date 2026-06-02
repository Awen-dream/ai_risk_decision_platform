from __future__ import annotations

from dataclasses import dataclass
import re

from agents.base import Agent
from core.models import AgentRequest, AgentResponse, Citation, ToolTrace


STRATEGY_ID_PATTERN = re.compile(r"(STRAT-\d+)", re.IGNORECASE)
ENTITY_ID_PATTERN = re.compile(r"((?:U|O)\d{5})", re.IGNORECASE)


@dataclass
class CopilotPlanStep:
    label: str
    reason: str


class CopilotAgent(Agent):
    """Workflow-style agent that composes investigation, strategy, and graph outputs."""

    name = "copilot"

    def __init__(
        self,
        investigation_agent: Agent,
        strategy_agent: Agent,
        graph_agent: Agent,
    ) -> None:
        self._investigation_agent = investigation_agent
        self._strategy_agent = strategy_agent
        self._graph_agent = graph_agent

    def run(self, request: AgentRequest) -> AgentResponse:
        response = AgentResponse(agent_name=self.name)
        plan_steps = self._plan(request)

        child_responses: list[tuple[str, AgentResponse]] = []
        for step in plan_steps:
            if step.label == "调查":
                child_responses.append((step.label, self._investigation_agent.run(request)))
            elif step.label == "策略":
                child_responses.append((step.label, self._strategy_agent.run(request)))
            elif step.label == "图谱":
                child_responses.append((step.label, self._graph_agent.run(request)))

        response.summary = self._build_summary(plan_steps, child_responses)
        response.findings = self._merge_findings(plan_steps, child_responses)
        response.suggested_actions = self._merge_actions(child_responses)
        response.citations = self._merge_citations(child_responses)
        response.tool_traces = self._merge_tool_traces(child_responses)
        response.confidence = round(
            sum(child.confidence for _, child in child_responses) / len(child_responses),
            2,
        )
        return response

    @staticmethod
    def _build_summary(
        plan_steps: list[CopilotPlanStep],
        child_responses: list[tuple[str, AgentResponse]],
    ) -> str:
        planned_labels = " -> ".join(step.label for step in plan_steps)
        parts = [f"{label}结论：{child.summary}" for label, child in child_responses]
        return f"已完成联合分析，执行计划为 {planned_labels}。 " + " ".join(parts)

    @staticmethod
    def _merge_findings(
        plan_steps: list[CopilotPlanStep],
        child_responses: list[tuple[str, AgentResponse]],
    ) -> list[str]:
        findings = [f"[规划] {step.label}：{step.reason}" for step in plan_steps]
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
    def _should_include_strategy(request: AgentRequest) -> bool:
        if "strategy_id" in request.context:
            return True
        lowered = request.query.lower()
        if "策略" in request.query or "阈值" in request.query or "shadow evaluation" in lowered:
            return True
        return STRATEGY_ID_PATTERN.search(request.query) is not None

    @staticmethod
    def _should_include_graph(request: AgentRequest) -> bool:
        if any(key in request.context for key in ("entity_id", "user_id")):
            return True
        lowered = request.query.lower()
        if "团伙" in request.query or "关系网络" in request.query or "graph" in lowered:
            return True
        return ENTITY_ID_PATTERN.search(request.query) is not None and "order_id" not in request.context

    def _plan(self, request: AgentRequest) -> list[CopilotPlanStep]:
        steps = [
            CopilotPlanStep(
                label="调查",
                reason="先做基础风险调查，定位异常对象、核心证据和影响范围。",
            )
        ]
        if self._should_include_strategy(request):
            steps.append(
                CopilotPlanStep(
                    label="策略",
                    reason="问题包含策略或阈值信号，需要补充策略效果和仿真建议。",
                )
            )
        if self._should_include_graph(request):
            steps.append(
                CopilotPlanStep(
                    label="图谱",
                    reason="问题包含实体关系或团伙信号，需要补充关系网络和关键路径。",
                )
            )
        return steps
