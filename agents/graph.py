from __future__ import annotations

from dataclasses import dataclass
import re

from agents.base import Agent
from agents.graph_planner import (
    DEFAULT_SELECTED_REASONS,
    DEFAULT_UNSELECTED_REASONS,
    GRAPH_TOOL_CANDIDATES,
    MAX_GRAPH_TOOLS,
    REQUIRED_GRAPH_TOOLS,
    GraphPlanCandidate,
    GraphPlanner,
    RuleBasedGraphPlanner,
)
from core.models import AgentRequest, AgentResponse, Citation, PlannerTraceStep, ToolTrace
from core.planning import build_tool_using_state, evidence_gaps_from_traces
from retrieval.knowledge_base import RetrievalService
from tools.registry import ToolRegistry


ENTITY_ID_PATTERN = re.compile(r"((?:U|O)\d{5})", re.IGNORECASE)


@dataclass(frozen=True)
class ValidatedGraphPlan:
    selected_tools: list[str]
    planner_trace: list[PlannerTraceStep]
    planner_backend: str
    fallback_used: bool
    validation_errors: list[str]
    candidate_tools: list[str]
    plan_reason: str
    planner_error: str

    def to_artifact(self) -> dict[str, object]:
        return {
            "backend": self.planner_backend,
            "fallback_used": self.fallback_used,
            "validation_errors": list(self.validation_errors),
            "candidate_tools": list(self.candidate_tools),
            "plan_reason": self.plan_reason,
            "planner_error": self.planner_error,
            "final_tools": list(self.selected_tools),
            "step_budget": MAX_GRAPH_TOOLS,
        }


class GraphAgent(Agent):
    """Agent for graph relation and community analysis."""

    name = "graph"

    def __init__(
        self,
        tools: ToolRegistry,
        retrieval: RetrievalService,
        planner: GraphPlanner | None = None,
    ) -> None:
        self._tools = tools
        self._retrieval = retrieval
        self._planner = planner or RuleBasedGraphPlanner()
        self._fallback_planner = RuleBasedGraphPlanner()

    def run(self, request: AgentRequest) -> AgentResponse:
        entity_id = self._resolve_entity_id(request)
        response = AgentResponse(agent_name=self.name)
        plan = self._validated_plan(request)
        response.intent = "graph_tool_plan"
        response.plan_steps = list(plan.selected_tools)
        response.planner_trace = plan.planner_trace
        response.artifacts["graph_plan"] = plan.to_artifact()

        traces = self._execute_graph_plan(response, entity_id, plan.selected_tools)
        self._attach_intermediate_state(response, plan, traces)
        relation_trace = traces.get("graph_relation")
        relation = relation_trace.payload if relation_trace.status == "success" else None

        docs = self._retrieval.search(f"{request.query} graph relation fraud ring", top_k=2)
        response.citations.extend(
            Citation.from_document(doc, snippet_length=180) for doc in docs
        )

        if relation:
            response.record_evidence(
                source="graph_relation",
                source_type="tool",
                summary=f"实体 {entity_id} 的关系网络风险等级为 {relation['risk_level']}。",
                payload=relation,
                confidence=0.8,
            )
            response.summary = (
                f"实体 {entity_id} 当前处于 {relation['community_size']} 个节点的关系网络中，"
                f"风险等级为 {relation['risk_level']}，主要风险原因是 {relation['risk_reason']}"
            )
            response.findings = [
                f"实体类型：{relation['entity_type']}，共享设备：{', '.join(relation['shared_devices']) or '无'}",
                f"共享 IP：{', '.join(relation['shared_ips']) or '无'}",
                f"关联账号：{', '.join(relation['linked_accounts']) or '无'}",
                f"关联订单：{', '.join(relation['linked_orders']) or '无'}",
                f"关键路径：{relation['key_path']}",
            ]
            response.suggested_actions = [
                "优先复核共享设备和共享 IP 上的关联账号",
                "结合历史相似 Case 判断是否属于团伙扩散",
                "如果网络继续扩大，建议补充图谱规则或升级人工审核",
            ]
            response.confidence = 0.8
            return response

        response.summary = (
            f"暂时无法完成实体 {entity_id} 的图谱分析，"
            f"{self._tool_status_phrase(relation_trace, '图谱关系')}。"
        )
        response.findings = [self._tool_status_finding("图谱关系", relation_trace)]
        response.suggested_actions = [
            self._tool_status_action("图谱关系", relation_trace, entity_id),
            "如需继续分析，可先结合历史案件或订单画像补充上下文",
        ]
        response.confidence = 0.18
        return response

    def _validated_plan(self, request: AgentRequest) -> ValidatedGraphPlan:
        candidate = self._planner.plan(request)
        errors: list[str] = []
        for tool_name in candidate.selected_tools:
            if tool_name not in GRAPH_TOOL_CANDIDATES:
                errors.append(f"candidate selected unsupported tool: {tool_name}")
        selected_tools = self._normalize_selected_tools(candidate.selected_tools)
        for required_tool in REQUIRED_GRAPH_TOOLS:
            if required_tool not in selected_tools:
                errors.append(f"candidate omitted required tool: {required_tool}")
                selected_tools.insert(0, required_tool)
                selected_tools = self._normalize_selected_tools(selected_tools)
        if len(selected_tools) > MAX_GRAPH_TOOLS:
            errors.append(f"candidate exceeded max tool count: {len(selected_tools)} > {MAX_GRAPH_TOOLS}")
            selected_tools = selected_tools[:MAX_GRAPH_TOOLS]
        if not selected_tools:
            errors.append("candidate produced no executable tools")
            return self._fallback_validated_plan(candidate, errors)
        return ValidatedGraphPlan(
            selected_tools=selected_tools,
            planner_trace=self._build_planner_trace(
                selected_tools=selected_tools,
                tool_reasons=candidate.tool_reasons or {},
            ),
            planner_backend=candidate.planner_backend,
            fallback_used=False,
            validation_errors=errors,
            candidate_tools=list(candidate.selected_tools),
            plan_reason=candidate.plan_reason,
            planner_error=candidate.planner_error,
        )

    def _fallback_validated_plan(
        self,
        candidate: GraphPlanCandidate,
        errors: list[str],
    ) -> ValidatedGraphPlan:
        fallback = self._fallback_planner.plan(AgentRequest(query="", context={}))
        selected_tools = self._normalize_selected_tools(fallback.selected_tools)
        return ValidatedGraphPlan(
            selected_tools=selected_tools,
            planner_trace=self._build_planner_trace(
                selected_tools=selected_tools,
                tool_reasons=fallback.tool_reasons or {},
            ),
            planner_backend=fallback.planner_backend,
            fallback_used=True,
            validation_errors=errors,
            candidate_tools=list(candidate.selected_tools),
            plan_reason=fallback.plan_reason,
            planner_error=candidate.planner_error,
        )

    @staticmethod
    def _normalize_selected_tools(selected_tools: list[str]) -> list[str]:
        selected = {tool for tool in selected_tools if tool in GRAPH_TOOL_CANDIDATES}
        return [tool for tool in GRAPH_TOOL_CANDIDATES if tool in selected]

    @staticmethod
    def _build_planner_trace(
        *,
        selected_tools: list[str],
        tool_reasons: dict[str, str],
    ) -> list[PlannerTraceStep]:
        selected = set(selected_tools)
        traces: list[PlannerTraceStep] = []
        for tool_name in GRAPH_TOOL_CANDIDATES:
            traces.append(
                PlannerTraceStep(
                    step=tool_name,
                    selected=tool_name in selected,
                    reason=tool_reasons.get(
                        tool_name,
                        DEFAULT_SELECTED_REASONS[tool_name]
                        if tool_name in selected
                        else DEFAULT_UNSELECTED_REASONS[tool_name],
                    ),
                )
            )
        return traces

    def _execute_graph_plan(
        self,
        response: AgentResponse,
        entity_id: str,
        selected_tools: list[str],
    ) -> dict[str, ToolTrace]:
        traces: dict[str, ToolTrace] = {}
        if "graph_relation" in selected_tools:
            traces["graph_relation"] = response.record_tool_trace(
                "graph_relation",
                self._tools.execute("graph_relation", entity_id=entity_id),
            )
        return traces

    @staticmethod
    def _attach_intermediate_state(
        response: AgentResponse,
        plan: ValidatedGraphPlan,
        traces: dict[str, ToolTrace],
    ) -> None:
        response.attach_intermediate_state(
            build_tool_using_state(
                thought_summary=(
                    plan.plan_reason
                    or f"围绕实体关系网络，在 {MAX_GRAPH_TOOLS} 步预算内选择图谱工具。"
                ),
                planner_trace=plan.planner_trace,
                selected_steps=plan.selected_tools,
                step_budget=MAX_GRAPH_TOOLS,
                planner_backend=plan.planner_backend,
                fallback_used=plan.fallback_used,
                validation_errors=plan.validation_errors,
                evidence_gap=evidence_gaps_from_traces(
                    list(traces.values()),
                    label_by_tool={"graph_relation": "关系图谱"},
                    next_action_by_tool={
                        "graph_relation": "确认实体关系图谱数据已同步后重试",
                    },
                ),
            )
        )

    @staticmethod
    def _resolve_entity_id(request: AgentRequest) -> str:
        if "entity_id" in request.context:
            return str(request.context["entity_id"]).upper()
        if "order_id" in request.context:
            return str(request.context["order_id"]).upper()
        if "user_id" in request.context:
            return str(request.context["user_id"]).upper()
        match = ENTITY_ID_PATTERN.search(request.query)
        if match:
            return match.group(1).upper()
        return "U10001"

    @staticmethod
    def _tool_status_finding(label: str, trace) -> str:
        if trace.status == "failed":
            return f"{label}：调用失败，原因 {trace.summary}"
        return f"{label}：{trace.summary}"

    @staticmethod
    def _tool_status_phrase(trace, label: str) -> str:
        if trace.status == "failed":
            return f"{label}调用失败"
        return f"未获取到可用{label}"

    @staticmethod
    def _tool_status_action(label: str, trace, identifier: str) -> str:
        if trace.status == "failed":
            return f"检查{label}上游服务状态与字段契约，确认 {identifier} 对应调用可恢复"
        return f"确认 {identifier} 对应的{label}数据是否已同步，必要时补齐记录后重试"
