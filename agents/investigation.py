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
        graph_trace = response.record_tool_trace(
            "graph_relation",
            self._tools.execute("graph_relation", entity_id=order_id),
        )
        rule_trace = response.record_tool_trace(
            "rule_explain",
            self._tools.execute("rule_explain", order_id=order_id),
        )

        order = order_trace.payload if order_trace.status == "success" else None
        graph_relation = graph_trace.payload if graph_trace.status == "success" else None
        rule_explanation = rule_trace.payload if rule_trace.status == "success" else None
        search_terms = [request.query]
        if order:
            search_terms.extend(order.get("risk_labels", []))
        if graph_relation:
            search_terms.extend(["graph relation", "fraud ring", graph_relation.get("risk_reason", "")])
        docs = self._retrieval.search(
            " ".join(search_terms),
            top_k=2,
        )
        response.citations.extend(
            Citation.from_document(doc, snippet_length=160) for doc in docs
        )
        if order:
            response.record_evidence(
                source="order_profile",
                source_type="tool",
                summary=f"订单 {order_id} 命中 {len(order['triggered_rules'])} 条规则。",
                payload=order,
                confidence=0.78,
            )
        if graph_relation:
            response.record_evidence(
                source="graph_relation",
                source_type="tool",
                summary=f"订单 {order_id} 关联网络风险等级为 {graph_relation['risk_level']}。",
                payload=graph_relation,
                confidence=0.74,
            )
        if rule_explanation:
            response.record_evidence(
                source="rule_explain",
                source_type="tool",
                summary=rule_explanation["explanation"],
                payload=rule_explanation,
                confidence=0.8,
            )
        if order is None:
            response.summary = (
                f"暂时无法完成订单 {order_id} 的完整调查，"
                f"{self._tool_status_phrase(order_trace, '订单画像')}。"
            )
            response.findings = [
                self._tool_status_finding("订单画像", order_trace),
            ]
            if graph_relation:
                response.findings.extend(
                    [
                        f"图谱风险：订单 {order_id} 仍处于 {graph_relation['community_size']} 节点的关系网络中，风险等级 {graph_relation['risk_level']}",
                        f"关键路径：{graph_relation['key_path']}",
                    ]
                )
            else:
                response.findings.append(self._tool_status_finding("图谱关系", graph_trace))
            response.suggested_actions = [
                self._tool_status_action("订单画像", order_trace, order_id),
            ]
            if graph_relation:
                response.suggested_actions.append("优先根据现有图谱线索复核共享设备、共享 IP 和关联账号")
            else:
                response.suggested_actions.append(self._tool_status_action("图谱关系", graph_trace, order_id))
            response.confidence = 0.36 if graph_relation else 0.22
            return response

        if graph_relation:
            response.summary = (
                f"订单 {order_id} 被判定为高风险，主要由 {', '.join(order['risk_labels'])} 驱动，"
                f"并且已落入 {graph_relation['community_size']} 个节点的关系网络，存在"
                f" {graph_relation['risk_level']} 级别团伙风险。"
            )
        else:
            response.summary = (
                f"订单 {order_id} 被判定为高风险，主要由 {', '.join(order['risk_labels'])} 驱动。"
            )
        response.findings = [
            f"命中规则：{', '.join(order['triggered_rules'])}",
            f"风险标签：{', '.join(order['risk_labels'])}",
            f"账号画像：国家 {order['country']}，支付渠道 {order['channel']}，近 7 天尝试下单 {order['recent_attempts']} 次",
        ]
        if graph_relation:
            response.findings.extend(
                [
                    f"关系网络：关联账号 {', '.join(graph_relation['linked_accounts']) or '无'}，关联订单 {', '.join(graph_relation['linked_orders']) or '无'}",
                    f"图谱风险：共享设备 {', '.join(graph_relation['shared_devices']) or '无'}，共享 IP {', '.join(graph_relation['shared_ips']) or '无'}",
                    f"关键路径：{graph_relation['key_path']}",
                ]
            )
        else:
            response.findings.append(self._tool_status_finding("图谱关系", graph_trace))
        if rule_explanation:
            response.findings.extend(
                [
                    f"规则解释：{rule_explanation['explanation']}",
                    f"规则变更：{rule_explanation['recent_change']}",
                ]
            )
        else:
            response.findings.append(self._tool_status_finding("规则解释", rule_trace))
        if order["recommended_action"] == "manual_review":
            response.findings.append("当前更适合转人工复核，而不是直接拒绝。")
        response.suggested_actions = [
            "复核最近 24 小时同设备/同支付工具订单",
            "结合相似 Case 判断是否属于误杀放大",
        ]
        if graph_relation:
            response.suggested_actions.append("优先排查共享设备和共享 IP 上的关联账号是否存在批量操作")
        else:
            response.suggested_actions.append(self._tool_status_action("图谱关系", graph_trace, order_id))
        response.confidence = 0.83 if graph_relation else 0.7
        return response

    def _investigate_metric(self, request: AgentRequest) -> AgentResponse:
        response = AgentResponse(agent_name=self.name)
        country = self._resolve_country(request)
        channel = self._resolve_channel(request)
        time_range = str(request.context.get("time_range", "recent_24h"))
        metric_trace = response.record_tool_trace(
            "metric_snapshot",
            self._tools.execute(
                "metric_snapshot",
                country=country,
                channel=channel,
                time_range=time_range,
            ),
        )
        metric = metric_trace.payload if metric_trace.status == "success" else None

        case_trace = response.record_tool_trace(
            "case_lookup",
            self._tools.execute("case_lookup", country=country, channel=channel),
        )
        cases = case_trace.payload if case_trace.status == "success" else []
        dashboard_trace = response.record_tool_trace(
            "dashboard_snapshot",
            self._tools.execute(
                "dashboard_snapshot",
                dashboard_id="risk_overview",
                country=country,
                channel=channel,
                time_range=time_range,
            ),
        )
        dashboard = dashboard_trace.payload if dashboard_trace.status == "success" else None
        sql_trace = response.record_tool_trace(
            "sql_query",
            self._tools.execute(
                "sql_query",
                query_name="metric_breakdown",
                parameters={
                    "country": country,
                    "channel": channel,
                    "time_range": time_range,
                },
                limit=3,
            ),
        )
        sql_result = sql_trace.payload if sql_trace.status == "success" else None

        docs = self._retrieval.search(request.query, top_k=2)
        response.citations.extend(
            Citation.from_document(doc, snippet_length=180) for doc in docs
        )
        if metric:
            response.record_evidence(
                source="metric_snapshot",
                source_type="tool",
                summary=f"{metric['metric_name']} 当前值 {metric['current_value']}，基线 {metric['baseline_value']}。",
                payload=metric,
                confidence=0.76,
            )
        if dashboard:
            response.record_evidence(
                source="dashboard_snapshot",
                source_type="tool",
                summary=f"Dashboard 显示最大波动分层为 {dashboard['largest_segment']}。",
                payload=dashboard,
                confidence=0.72,
            )
        if sql_result:
            response.record_evidence(
                source="sql_query",
                source_type="tool",
                summary=f"SQL 分层返回 {sql_result['row_count']} 行，支持进一步下钻。",
                payload=sql_result,
                confidence=0.74,
            )

        response.findings = [f"时间窗口：{time_range}"]
        if metric:
            response.summary = (
                f"{metric['country']} {metric['channel']} 的 {metric['metric_name']} 在 "
                f"{metric['anomaly_started_at']} 后出现明显上升，当前最可疑的触发因素是 "
                f"{metric['suspected_driver']}。"
            )
            response.findings.extend(
                [
                    f"异常开始时间：{metric['anomaly_started_at']}",
                    f"当前指标：{metric['current_value']}，历史基线：{metric['baseline_value']}",
                    f"近期变更：{metric['recent_change']}",
                ]
            )
        else:
            response.summary = (
                f"暂时无法完成 {country} {channel} 在 {time_range} 的完整指标调查，"
                f"{self._tool_status_phrase(metric_trace, '指标快照')}。"
            )
            response.findings.append(self._tool_status_finding("指标快照", metric_trace))
        if dashboard:
            response.findings.append(
                f"看板下钻：最大波动分层 {dashboard['largest_segment']}，变化 {dashboard['largest_segment_change']}"
            )
        else:
            response.findings.append(self._tool_status_finding("Dashboard 快照", dashboard_trace))
        if sql_result and sql_result.get("rows"):
            top_row = sql_result["rows"][0]
            response.findings.append(
                f"SQL 分层：{top_row['segment']} 当前 {top_row['current_value']}，相对基线变化 {top_row['delta']}"
            )
        else:
            response.findings.append(self._tool_status_finding("SQL 查询", sql_trace))

        if cases:
            response.findings.append(f"历史相似案例：{cases[0]['title']}")
        else:
            response.findings.append(self._tool_status_finding("历史案例", case_trace))

        response.suggested_actions = []
        if metric:
            response.suggested_actions.extend(
                [
                    "优先复核近 24 小时策略变更和阈值调整",
                    "按国家/渠道/卡组织进一步下钻影响范围",
                ]
            )
        else:
            response.suggested_actions.append(self._tool_status_action("指标快照", metric_trace, f"{country}/{channel}/{time_range}"))
        if cases:
            response.suggested_actions.append("结合历史相似案例复核最近变更是否会放大误杀")
        else:
            response.suggested_actions.append(self._tool_status_action("历史案例", case_trace, f"{country}/{channel}"))

        if metric:
            response.confidence = 0.79 if cases else 0.68
        else:
            response.confidence = 0.3 if cases else 0.18
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
