from __future__ import annotations

import re

from agents.base import Agent
from core.models import AgentRequest, AgentResponse, Citation
from retrieval.knowledge_base import RetrievalService
from tools.registry import ToolRegistry


STRATEGY_ID_PATTERN = re.compile(r"(STRAT-\d+)", re.IGNORECASE)


class StrategyAgent(Agent):
    """Agent for strategy diagnosis, recommendation, and simulation summary."""

    name = "strategy"

    def __init__(self, tools: ToolRegistry, retrieval: RetrievalService) -> None:
        self._tools = tools
        self._retrieval = retrieval

    def run(self, request: AgentRequest) -> AgentResponse:
        strategy_id = self._resolve_strategy_id(request)
        response = AgentResponse(agent_name=self.name)

        profile_trace = response.record_tool_trace(
            "strategy_profile",
            self._tools.execute("strategy_profile", strategy_id=strategy_id),
        )
        simulation_trace = response.record_tool_trace(
            "strategy_simulation",
            self._tools.execute("strategy_simulation", strategy_id=strategy_id),
        )
        profile = profile_trace.payload
        simulation = simulation_trace.payload
        impacted_entities = list(profile.get("top_impacted_entities", []))
        graph_relation = None
        if impacted_entities:
            graph_trace = response.record_tool_trace(
                "graph_relation",
                self._tools.execute("graph_relation", entity_id=impacted_entities[0]),
            )
            if graph_trace.status == "success":
                graph_relation = graph_trace.payload

        docs = self._retrieval.search(
            f"{request.query} strategy simulation graph relation fraud ring",
            top_k=2,
        )
        response.citations.extend(
            Citation.from_document(doc, snippet_length=180) for doc in docs
        )

        response.summary = self._build_summary(strategy_id, profile, simulation, graph_relation)
        response.findings = [
            f"策略名称：{profile['name']}，状态：{profile['status']}",
            f"命中率：{profile['hit_rate']}，风险捕获率：{profile['risk_capture_rate']}，误杀率：{profile['false_positive_rate']}",
            f"当前问题：{profile['recent_issue']}",
            f"仿真结果：拦截变化 {simulation['delta_intercepts']}，误杀变化 {simulation['delta_false_positives']}",
            f"收益评估：风险下降 {simulation['estimated_risk_reduction']}，收入影响 {simulation['estimated_revenue_impact']}",
        ]
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
        response.suggested_actions = [
            "先在 shadow evaluation 中验证推荐阈值",
            "按国家/渠道分层观察通过率与误杀变化",
            "如果人工投诉上升，补充相似策略和历史 Case 复核",
        ]
        if graph_relation:
            response.suggested_actions.append("优先核查该策略是否正在集中命中同一团伙网络，并评估是否需要分层处置")
        response.confidence = 0.81
        return response

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
