from __future__ import annotations

from dataclasses import dataclass
import re

from agents.base import Agent
from agents.strategy_planner import (
    DEFAULT_SELECTED_REASONS,
    DEFAULT_UNSELECTED_REASONS,
    MAX_STRATEGY_TOOLS,
    REQUIRED_STRATEGY_TOOLS,
    STRATEGY_TOOL_CANDIDATES,
    RuleBasedStrategyPlanner,
    StrategyPlanCandidate,
    StrategyPlanner,
)
from core.models import (
    AgentRequest,
    AgentResponse,
    Citation,
    PlannerTraceStep,
    ToolResult,
    ToolTrace,
)
from retrieval.knowledge_base import RetrievalService
from tools.registry import ToolRegistry


STRATEGY_ID_PATTERN = re.compile(r"(STRAT-\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class ValidatedStrategyPlan:
    selected_tools: list[str]
    planner_trace: list[PlannerTraceStep]
    planner_backend: str
    fallback_used: bool
    validation_errors: list[str]
    candidate_tools: list[str]
    planner_error: str

    def to_artifact(self) -> dict[str, object]:
        return {
            "backend": self.planner_backend,
            "fallback_used": self.fallback_used,
            "validation_errors": list(self.validation_errors),
            "candidate_tools": list(self.candidate_tools),
            "planner_error": self.planner_error,
            "final_tools": list(self.selected_tools),
        }


class StrategyAgent(Agent):
    """Agent for strategy diagnosis with constrained tool selection."""

    name = "strategy"

    def __init__(
        self,
        tools: ToolRegistry,
        retrieval: RetrievalService,
        planner: StrategyPlanner | None = None,
    ) -> None:
        self._tools = tools
        self._retrieval = retrieval
        self._planner = planner or RuleBasedStrategyPlanner()
        self._fallback_planner = RuleBasedStrategyPlanner()

    def run(self, request: AgentRequest) -> AgentResponse:
        strategy_id = self._resolve_strategy_id(request)
        response = AgentResponse(agent_name=self.name)
        plan = self._validated_plan(request)
        response.intent = "strategy_tool_plan"
        response.plan_steps = list(plan.selected_tools)
        response.planner_trace = plan.planner_trace
        response.artifacts["strategy_plan"] = plan.to_artifact()

        traces = self._execute_strategy_plan(response, strategy_id, plan.selected_tools)
        return self._build_response(request, response, strategy_id, traces)

    def _validated_plan(self, request: AgentRequest) -> ValidatedStrategyPlan:
        candidate = self._planner.plan(request)
        errors: list[str] = []
        for tool_name in candidate.selected_tools:
            if tool_name not in STRATEGY_TOOL_CANDIDATES:
                errors.append(f"candidate selected unsupported tool: {tool_name}")
        selected_tools = self._normalize_selected_tools(candidate.selected_tools)
        for required_tool in REQUIRED_STRATEGY_TOOLS:
            if required_tool not in selected_tools:
                errors.append(f"candidate omitted required tool: {required_tool}")
                selected_tools.insert(0, required_tool)
                selected_tools = self._normalize_selected_tools(selected_tools)
        if len(selected_tools) > MAX_STRATEGY_TOOLS:
            errors.append(
                f"candidate exceeded max tool count: {len(selected_tools)} > {MAX_STRATEGY_TOOLS}"
            )
            selected_tools = selected_tools[:MAX_STRATEGY_TOOLS]
        if not selected_tools:
            errors.append("candidate produced no executable tools")
            return self._fallback_validated_plan(request, candidate, errors)
        return ValidatedStrategyPlan(
            selected_tools=selected_tools,
            planner_trace=self._build_planner_trace(
                selected_tools=selected_tools,
                tool_reasons=candidate.tool_reasons or {},
            ),
            planner_backend=candidate.planner_backend,
            fallback_used=False,
            validation_errors=errors,
            candidate_tools=list(candidate.selected_tools),
            planner_error=candidate.planner_error,
        )

    def _fallback_validated_plan(
        self,
        request: AgentRequest,
        candidate: StrategyPlanCandidate,
        errors: list[str],
    ) -> ValidatedStrategyPlan:
        fallback = self._fallback_planner.plan(request)
        selected_tools = self._normalize_selected_tools(fallback.selected_tools)
        return ValidatedStrategyPlan(
            selected_tools=selected_tools,
            planner_trace=self._build_planner_trace(
                selected_tools=selected_tools,
                tool_reasons=fallback.tool_reasons or {},
            ),
            planner_backend=fallback.planner_backend,
            fallback_used=True,
            validation_errors=errors,
            candidate_tools=list(candidate.selected_tools),
            planner_error=candidate.planner_error,
        )

    @staticmethod
    def _normalize_selected_tools(selected_tools: list[str]) -> list[str]:
        selected = {tool for tool in selected_tools if tool in STRATEGY_TOOL_CANDIDATES}
        return [tool for tool in STRATEGY_TOOL_CANDIDATES if tool in selected]

    @staticmethod
    def _build_planner_trace(
        *,
        selected_tools: list[str],
        tool_reasons: dict[str, str],
    ) -> list[PlannerTraceStep]:
        selected = set(selected_tools)
        traces: list[PlannerTraceStep] = []
        for tool_name in STRATEGY_TOOL_CANDIDATES:
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

    def _execute_strategy_plan(
        self,
        response: AgentResponse,
        strategy_id: str,
        selected_tools: list[str],
    ) -> dict[str, ToolTrace]:
        traces: dict[str, ToolTrace] = {}
        if "strategy_profile" in selected_tools:
            traces["strategy_profile"] = response.record_tool_trace(
                "strategy_profile",
                self._tools.execute("strategy_profile", strategy_id=strategy_id),
            )
        if "strategy_simulation" in selected_tools:
            traces["strategy_simulation"] = response.record_tool_trace(
                "strategy_simulation",
                self._tools.execute("strategy_simulation", strategy_id=strategy_id),
            )
        if "rule_explain" in selected_tools:
            traces["rule_explain"] = response.record_tool_trace(
                "rule_explain",
                self._tools.execute("rule_explain", strategy_id=strategy_id),
            )
        if "graph_relation" in selected_tools:
            entity_id = self._first_impacted_entity(traces.get("strategy_profile"))
            if entity_id:
                traces["graph_relation"] = response.record_tool_trace(
                    "graph_relation",
                    self._tools.execute("graph_relation", entity_id=entity_id),
                )
            else:
                traces["graph_relation"] = response.record_tool_trace(
                    "graph_relation",
                    ToolResult.degraded_result(
                        name="graph_relation",
                        payload={},
                        summary="未获取到重点影响实体",
                        error="strategy_profile did not provide top_impacted_entities",
                        error_type="missing_context",
                    ),
                )
        return traces

    def _build_response(
        self,
        request: AgentRequest,
        response: AgentResponse,
        strategy_id: str,
        traces: dict[str, ToolTrace],
    ) -> AgentResponse:
        profile_trace = traces.get("strategy_profile")
        simulation_trace = traces.get("strategy_simulation")
        rule_trace = traces.get("rule_explain")
        graph_trace = traces.get("graph_relation")
        profile = profile_trace.payload if self._trace_success(profile_trace) else None
        simulation = simulation_trace.payload if self._trace_success(simulation_trace) else None
        rule_explanation = rule_trace.payload if self._trace_success(rule_trace) else None
        graph_relation = graph_trace.payload if self._trace_success(graph_trace) else None
        impacted_entities = list(profile.get("top_impacted_entities", [])) if profile else []

        docs = self._retrieval.search(
            f"{request.query} strategy simulation graph relation fraud ring",
            top_k=2,
        )
        response.citations.extend(
            Citation.from_document(doc, snippet_length=180) for doc in docs
        )
        if profile:
            response.record_evidence(
                source="strategy_profile",
                source_type="tool",
                summary=f"策略 {strategy_id} 当前阈值 {profile['current_threshold']:.2f}。",
                payload=profile,
                confidence=0.77,
            )
        if simulation:
            response.record_evidence(
                source="strategy_simulation",
                source_type="tool",
                summary=f"仿真建议阈值调整到 {simulation['recommended_threshold']:.2f}。",
                payload=simulation,
                confidence=0.79,
            )
        if rule_explanation:
            response.record_evidence(
                source="rule_explain",
                source_type="tool",
                summary=rule_explanation["explanation"],
                payload=rule_explanation,
                confidence=0.75,
            )
        if graph_relation:
            response.record_evidence(
                source="graph_relation",
                source_type="tool",
                summary=f"重点实体图谱风险等级为 {graph_relation['risk_level']}。",
                payload=graph_relation,
                confidence=0.73,
            )

        if profile and simulation:
            response.summary = self._build_summary(strategy_id, profile, simulation, graph_relation)
            response.artifacts["strategy_recommendation"] = {
                "strategy_id": strategy_id,
                "current_threshold": profile["current_threshold"],
                "recommended_threshold": simulation["recommended_threshold"],
                "validation_window": "shadow evaluation",
                "rationale": (
                    f"基于仿真建议将阈值从 {profile['current_threshold']:.2f} "
                    f"调整到 {simulation['recommended_threshold']:.2f}"
                ),
            }
        elif profile:
            response.summary = (
                f"已获取策略 {strategy_id} 的当前画像，但尚未拿到仿真结果，"
                f"{self._tool_status_phrase(simulation_trace, '策略仿真')}。"
            )
        elif simulation:
            response.summary = (
                f"已获取策略 {strategy_id} 的仿真建议，但尚未拿到策略画像，"
                f"{self._tool_status_phrase(profile_trace, '策略画像')}。"
            )
        else:
            response.summary = (
                f"暂时无法完成策略 {strategy_id} 的完整分析，"
                f"{self._tool_status_phrase(profile_trace, '策略画像')}，"
                f"{self._tool_status_phrase(simulation_trace, '策略仿真')}。"
            )

        response.findings = []
        if profile:
            response.findings.extend(
                [
                    f"策略名称：{profile['name']}，状态：{profile['status']}",
                    f"命中率：{profile['hit_rate']}，风险捕获率：{profile['risk_capture_rate']}，误杀率：{profile['false_positive_rate']}",
                    f"当前问题：{profile['recent_issue']}",
                ]
            )
        elif profile_trace is not None:
            response.findings.append(self._tool_status_finding("策略画像", profile_trace))
        if simulation:
            response.findings.extend(
                [
                    f"仿真结果：拦截变化 {simulation['delta_intercepts']}，误杀变化 {simulation['delta_false_positives']}",
                    f"收益评估：风险下降 {simulation['estimated_risk_reduction']}，收入影响 {simulation['estimated_revenue_impact']}",
                ]
            )
        elif simulation_trace is not None:
            response.findings.append(self._tool_status_finding("策略仿真", simulation_trace))
        if rule_explanation:
            response.findings.extend(
                [
                    f"规则解释：{rule_explanation['explanation']}",
                    f"规则变更：{rule_explanation['recent_change']}",
                ]
            )
        elif rule_trace is not None:
            response.findings.append(self._tool_status_finding("规则解释", rule_trace))
        if impacted_entities:
            response.findings.append(f"重点影响实体：{', '.join(impacted_entities)}")
        if graph_relation:
            response.findings.extend(
                [
                    f"图谱风险：首个重点实体处于 {graph_relation['community_size']} 节点网络，风险等级 {graph_relation['risk_level']}",
                    f"团伙特征：共享设备 {', '.join(graph_relation['shared_devices']) or '无'}，共享 IP {', '.join(graph_relation['shared_ips']) or '无'}",
                    f"关键路径：{graph_relation['key_path']}",
                ]
            )
        elif graph_trace is not None:
            response.findings.append(self._tool_status_finding("图谱关系", graph_trace))

        response.suggested_actions = []
        if simulation:
            response.suggested_actions.append("先在 shadow evaluation 中验证推荐阈值")
        elif simulation_trace is not None:
            response.suggested_actions.append(self._tool_status_action("策略仿真", simulation_trace, strategy_id))
        if profile:
            response.suggested_actions.extend(
                [
                    "按国家/渠道分层观察通过率与误杀变化",
                    "如果人工投诉上升，补充相似策略和历史 Case 复核",
                ]
            )
        elif profile_trace is not None:
            response.suggested_actions.append(self._tool_status_action("策略画像", profile_trace, strategy_id))
        if graph_relation:
            response.suggested_actions.append("优先核查该策略是否正在集中命中同一团伙网络，并评估是否需要分层处置")
        elif graph_trace is not None:
            response.suggested_actions.append(
                self._tool_status_action(
                    "图谱关系",
                    graph_trace,
                    impacted_entities[0] if impacted_entities else strategy_id,
                )
            )

        if profile and simulation:
            response.confidence = 0.81 if graph_relation or graph_trace is None else 0.72
        elif profile or simulation:
            response.confidence = 0.52
        else:
            response.confidence = 0.2
        return response

    @staticmethod
    def _trace_success(trace: ToolTrace | None) -> bool:
        return trace is not None and trace.status == "success"

    @staticmethod
    def _first_impacted_entity(profile_trace: ToolTrace | None) -> str | None:
        if profile_trace is None or profile_trace.status != "success":
            return None
        impacted_entities = list(profile_trace.payload.get("top_impacted_entities", []))
        if not impacted_entities:
            return None
        return str(impacted_entities[0])

    @staticmethod
    def _build_summary(
        strategy_id: str,
        profile: dict,
        simulation: dict,
        graph_relation: dict | None,
    ) -> str:
        summary = (
            f"策略 {strategy_id} 当前阈值为 {profile['current_threshold']:.2f}，"
            f"建议参考仿真将阈值调整到 {simulation['recommended_threshold']:.2f}，"
            f"并先通过 shadow evaluation 验证。"
        )
        if graph_relation:
            summary += (
                f" 同时该策略已命中高关联关系网络，首个重点实体对应"
                f" {graph_relation['community_size']} 节点团伙，需结合图谱做分层判断。"
            )
        return summary

    @staticmethod
    def _resolve_strategy_id(request: AgentRequest) -> str:
        if "strategy_id" in request.context:
            return str(request.context["strategy_id"]).upper()
        match = STRATEGY_ID_PATTERN.search(request.query)
        if match:
            return match.group(1).upper()
        return "STRAT-001"

    @staticmethod
    def _tool_status_finding(label: str, trace: ToolTrace) -> str:
        if trace.status == "failed":
            return f"{label}：调用失败，原因 {trace.summary}"
        return f"{label}：{trace.summary}"

    @staticmethod
    def _tool_status_phrase(trace: ToolTrace | None, label: str) -> str:
        if trace is None:
            return f"未执行{label}"
        if trace.status == "failed":
            return f"{label}调用失败"
        return f"未获取到可用{label}"

    @staticmethod
    def _tool_status_action(label: str, trace: ToolTrace, identifier: str) -> str:
        if trace.status == "failed":
            return f"检查{label}上游服务状态与字段契约，确认 {identifier} 对应调用可恢复"
        return f"确认 {identifier} 对应的{label}数据是否已同步，必要时补齐记录后重试"
