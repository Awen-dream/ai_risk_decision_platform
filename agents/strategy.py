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

        docs = self._retrieval.search(f"{request.query} strategy simulation", top_k=2)
        response.citations.extend(
            Citation.from_document(doc, snippet_length=180) for doc in docs
        )

        response.summary = (
            f"策略 {strategy_id} 当前阈值为 {profile['current_threshold']:.2f}，"
            f"建议参考仿真将阈值调整到 {simulation['recommended_threshold']:.2f}，"
            f"并先通过 shadow evaluation 验证。"
        )
        response.findings = [
            f"策略名称：{profile['name']}，状态：{profile['status']}",
            f"命中率：{profile['hit_rate']}，风险捕获率：{profile['risk_capture_rate']}，误杀率：{profile['false_positive_rate']}",
            f"当前问题：{profile['recent_issue']}",
            f"仿真结果：拦截变化 {simulation['delta_intercepts']}，误杀变化 {simulation['delta_false_positives']}",
            f"收益评估：风险下降 {simulation['estimated_risk_reduction']}，收入影响 {simulation['estimated_revenue_impact']}",
        ]
        response.suggested_actions = [
            "先在 shadow evaluation 中验证推荐阈值",
            "按国家/渠道分层观察通过率与误杀变化",
            "如果人工投诉上升，补充相似策略和历史 Case 复核",
        ]
        response.confidence = 0.81
        return response

    @staticmethod
    def _resolve_strategy_id(request: AgentRequest) -> str:
        if "strategy_id" in request.context:
            return str(request.context["strategy_id"]).upper()
        match = STRATEGY_ID_PATTERN.search(request.query)
        if match:
            return match.group(1).upper()
        return "STRAT-001"
