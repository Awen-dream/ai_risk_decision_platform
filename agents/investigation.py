from __future__ import annotations

from agents.base import Agent
from core.models import AgentRequest, AgentResponse, Citation
from retrieval.knowledge_base import RetrievalService
from tools.registry import ToolRegistry


COUNTRY_ALIASES = {
    "巴西": "BR",
    "brazil": "BR",
    "巴西信用卡": "BR",
    "印尼": "ID",
    "indonesia": "ID",
    "美国": "US",
    "united states": "US",
}

CHANNEL_ALIASES = {
    "信用卡": "credit_card",
    "credit card": "credit_card",
    "钱包": "wallet",
    "wallet": "wallet",
}


class InvestigationAgent(Agent):
    """Risk investigation agent that orchestrates simple tool calls."""

    name = "investigation"

    def __init__(self, tools: ToolRegistry, retrieval: RetrievalService) -> None:
        self._tools = tools
        self._retrieval = retrieval

    def run(self, request: AgentRequest) -> AgentResponse:
        order_id = request.context.get("order_id")
        if order_id:
            return self._investigate_order(request, order_id)
        return self._investigate_metric(request)

    def _investigate_order(
        self, request: AgentRequest, order_id: str
    ) -> AgentResponse:
        response = AgentResponse(agent_name=self.name)
        order_trace = response.record_tool_trace(
            "order_profile",
            self._tools.execute("order_profile", order_id=order_id),
        )

        order = order_trace.payload
        docs = self._retrieval.search(
            f"{request.query} {' '.join(order['risk_labels'])}", top_k=2
        )
        response.citations.extend(
            Citation.from_document(doc, snippet_length=160) for doc in docs
        )
        response.summary = (
            f"订单 {order_id} 被判定为高风险，主要由 {', '.join(order['risk_labels'])} 驱动。"
        )
        response.findings = [
            f"命中规则：{', '.join(order['triggered_rules'])}",
            f"风险标签：{', '.join(order['risk_labels'])}",
            f"账号画像：国家 {order['country']}，支付渠道 {order['channel']}，近 7 天尝试下单 {order['recent_attempts']} 次",
        ]
        if order["recommended_action"] == "manual_review":
            response.findings.append("当前更适合转人工复核，而不是直接拒绝。")
        response.suggested_actions = [
            "复核最近 24 小时同设备/同支付工具订单",
            "结合相似 Case 判断是否属于误杀放大",
        ]
        response.confidence = 0.83
        return response

    def _investigate_metric(self, request: AgentRequest) -> AgentResponse:
        response = AgentResponse(agent_name=self.name)
        country = self._resolve_country(request)
        channel = self._resolve_channel(request)
        metric_trace = response.record_tool_trace(
            "metric_snapshot",
            self._tools.execute(
                "metric_snapshot",
                country=country,
                channel=channel,
                time_range=request.context.get("time_range", "recent_24h"),
            ),
        )
        metric = metric_trace.payload

        case_trace = response.record_tool_trace(
            "case_lookup",
            self._tools.execute("case_lookup", country=country, channel=channel),
        )
        cases = case_trace.payload

        docs = self._retrieval.search(request.query, top_k=2)
        response.citations.extend(
            Citation.from_document(doc, snippet_length=180) for doc in docs
        )

        response.summary = (
            f"{metric['country']} {metric['channel']} 的 {metric['metric_name']} 在 "
            f"{metric['anomaly_started_at']} 后出现明显上升，当前最可疑的触发因素是 "
            f"{metric['suspected_driver']}。"
        )
        response.findings = [
            f"异常开始时间：{metric['anomaly_started_at']}",
            f"当前指标：{metric['current_value']}，历史基线：{metric['baseline_value']}",
            f"近期变更：{metric['recent_change']}",
        ]
        if cases:
            response.findings.append(f"历史相似案例：{cases[0]['title']}")
        response.suggested_actions = [
            "优先复核近 24 小时策略变更和阈值调整",
            "按国家/渠道/卡组织进一步下钻影响范围",
        ]
        response.confidence = 0.79
        return response

    def _resolve_country(self, request: AgentRequest) -> str:
        if "country" in request.context:
            return str(request.context["country"]).upper()
        lowered = request.query.lower()
        for alias, value in COUNTRY_ALIASES.items():
            if alias in lowered or alias in request.query:
                return value
        return "BR"

    def _resolve_channel(self, request: AgentRequest) -> str:
        if "channel" in request.context:
            return str(request.context["channel"]).lower()
        lowered = request.query.lower()
        for alias, value in CHANNEL_ALIASES.items():
            if alias in lowered or alias in request.query:
                return value
        return "credit_card"
