from __future__ import annotations

from dataclasses import dataclass

from agents.base import Agent
from agents.investigation_planner import (
    DEFAULT_SELECTED_REASONS,
    DEFAULT_UNSELECTED_REASONS,
    InvestigationPlanCandidate,
    InvestigationPlanner,
    MAX_TOOLS_BY_MODE,
    REQUIRED_TOOL_BY_MODE,
    RuleBasedInvestigationPlanner,
    TOOL_CANDIDATES_BY_MODE,
)
from core.models import AgentRequest, AgentResponse, Citation, PlannerTraceStep, ToolTrace
from core.planning import build_tool_using_state, evidence_gaps_from_traces
from retrieval.knowledge_base import RetrievalService
from services.evidence import build_evidence_panel
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


@dataclass(frozen=True)
class ValidatedInvestigationPlan:
    mode: str
    selected_tools: list[str]
    planner_trace: list[PlannerTraceStep]
    planner_backend: str
    fallback_used: bool
    validation_errors: list[str]
    candidate_mode: str
    candidate_tools: list[str]
    plan_reason: str
    planner_error: str

    def to_artifact(self) -> dict[str, object]:
        return {
            "backend": self.planner_backend,
            "fallback_used": self.fallback_used,
            "validation_errors": list(self.validation_errors),
            "candidate_mode": self.candidate_mode,
            "candidate_tools": list(self.candidate_tools),
            "plan_reason": self.plan_reason,
            "planner_error": self.planner_error,
            "final_mode": self.mode,
            "final_tools": list(self.selected_tools),
            "step_budget": MAX_TOOLS_BY_MODE[self.mode],
        }


class InvestigationAgent(Agent):
    """Risk investigation agent with constrained tool selection."""

    name = "investigation"

    def __init__(
        self,
        tools: ToolRegistry,
        retrieval: RetrievalService,
        planner: InvestigationPlanner | None = None,
    ) -> None:
        self._tools = tools
        self._retrieval = retrieval
        self._planner = planner or RuleBasedInvestigationPlanner()
        self._fallback_planner = RuleBasedInvestigationPlanner()

    def run(self, request: AgentRequest) -> AgentResponse:
        response = AgentResponse(agent_name=self.name)
        plan = self._validated_plan(request)
        response.intent = "order_investigation" if plan.mode == "order" else "metric_investigation"
        response.plan_steps = list(plan.selected_tools)
        response.planner_trace = plan.planner_trace
        response.artifacts["investigation_plan"] = plan.to_artifact()

        if plan.mode == "order":
            order_id = self._resolve_order_id(request)
            traces = self._execute_order_plan(response, order_id, plan.selected_tools)
            self._attach_intermediate_state(response, plan, traces)
            return self._build_order_response(request, response, order_id, traces)

        country = self._resolve_country(request)
        channel = self._resolve_channel(request)
        time_range = str(request.context.get("time_range", "recent_24h"))
        traces = self._execute_metric_plan(
            response,
            country=country,
            channel=channel,
            time_range=time_range,
            selected_tools=plan.selected_tools,
        )
        self._attach_intermediate_state(response, plan, traces)
        return self._build_metric_response(
            request,
            response,
            country=country,
            channel=channel,
            time_range=time_range,
            traces=traces,
        )

    def _validated_plan(self, request: AgentRequest) -> ValidatedInvestigationPlan:
        candidate = self._planner.plan(request)
        errors: list[str] = []
        if candidate.mode not in TOOL_CANDIDATES_BY_MODE:
            errors.append(f"unknown investigation mode: {candidate.mode}")
            return self._fallback_validated_plan(request, candidate, errors)

        allowed_tools = TOOL_CANDIDATES_BY_MODE[candidate.mode]
        selected_tools = self._normalize_selected_tools(candidate.selected_tools, allowed_tools)
        required_tool = REQUIRED_TOOL_BY_MODE[candidate.mode]
        if required_tool not in selected_tools:
            errors.append(f"candidate omitted required tool: {required_tool}")
            selected_tools.insert(0, required_tool)
            selected_tools = self._normalize_selected_tools(selected_tools, allowed_tools)
        max_tools = MAX_TOOLS_BY_MODE[candidate.mode]
        if len(selected_tools) > max_tools:
            errors.append(f"candidate exceeded max tool count: {len(selected_tools)} > {max_tools}")
            selected_tools = selected_tools[:max_tools]
        if not selected_tools:
            errors.append("candidate produced no executable tools")
            return self._fallback_validated_plan(request, candidate, errors)
        return ValidatedInvestigationPlan(
            mode=candidate.mode,
            selected_tools=selected_tools,
            planner_trace=self._build_planner_trace(
                allowed_tools=allowed_tools,
                selected_tools=selected_tools,
                tool_reasons=candidate.tool_reasons or {},
            ),
            planner_backend=candidate.planner_backend,
            fallback_used=False,
            validation_errors=errors,
            candidate_mode=candidate.mode,
            candidate_tools=list(candidate.selected_tools),
            plan_reason=candidate.mode_reason,
            planner_error=candidate.planner_error,
        )

    def _fallback_validated_plan(
        self,
        request: AgentRequest,
        candidate: InvestigationPlanCandidate,
        errors: list[str],
    ) -> ValidatedInvestigationPlan:
        fallback = self._fallback_planner.plan(request)
        allowed_tools = TOOL_CANDIDATES_BY_MODE[fallback.mode]
        selected_tools = self._normalize_selected_tools(fallback.selected_tools, allowed_tools)
        return ValidatedInvestigationPlan(
            mode=fallback.mode,
            selected_tools=selected_tools,
            planner_trace=self._build_planner_trace(
                allowed_tools=allowed_tools,
                selected_tools=selected_tools,
                tool_reasons=fallback.tool_reasons or {},
            ),
            planner_backend=fallback.planner_backend,
            fallback_used=True,
            validation_errors=errors,
            candidate_mode=candidate.mode,
            candidate_tools=list(candidate.selected_tools),
            plan_reason=fallback.mode_reason,
            planner_error=candidate.planner_error,
        )

    @staticmethod
    def _attach_intermediate_state(
        response: AgentResponse,
        plan: ValidatedInvestigationPlan,
        traces: dict[str, ToolTrace],
    ) -> None:
        labels = {
            "metric_snapshot": "指标快照",
            "case_lookup": "历史案例",
            "dashboard_snapshot": "看板快照",
            "sql_query": "SQL 下钻",
            "order_profile": "订单画像",
            "graph_relation": "关系图谱",
            "rule_explain": "规则解释",
        }
        next_actions = {
            "metric_snapshot": "检查指标服务或缩小 country/channel/time_range 后重试",
            "case_lookup": "补充历史 case 索引后复查相似案例",
            "dashboard_snapshot": "确认看板分层数据同步完成后重试",
            "sql_query": "确认 SQL 结果集或查询名配置后重试",
            "order_profile": "确认订单画像数据已同步后重试",
            "graph_relation": "确认实体关系图谱数据已同步后重试",
            "rule_explain": "确认规则解释服务可用并补齐 rule/order 上下文",
        }
        response.attach_intermediate_state(
            build_tool_using_state(
                thought_summary=(
                    plan.plan_reason
                    or f"按 {plan.mode} 调查模式在 {MAX_TOOLS_BY_MODE[plan.mode]} 步预算内选择工具。"
                ),
                planner_trace=plan.planner_trace,
                selected_steps=plan.selected_tools,
                step_budget=MAX_TOOLS_BY_MODE[plan.mode],
                planner_backend=plan.planner_backend,
                fallback_used=plan.fallback_used,
                validation_errors=plan.validation_errors,
                evidence_gap=evidence_gaps_from_traces(
                    list(traces.values()),
                    label_by_tool=labels,
                    next_action_by_tool=next_actions,
                ),
            )
        )

    @staticmethod
    def _normalize_selected_tools(selected_tools: list[str], allowed_tools: tuple[str, ...]) -> list[str]:
        selected = {tool for tool in selected_tools if tool in allowed_tools}
        return [tool for tool in allowed_tools if tool in selected]

    @staticmethod
    def _build_planner_trace(
        *,
        allowed_tools: tuple[str, ...],
        selected_tools: list[str],
        tool_reasons: dict[str, str],
    ) -> list[PlannerTraceStep]:
        selected = set(selected_tools)
        traces: list[PlannerTraceStep] = []
        for tool_name in allowed_tools:
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

    def _execute_order_plan(
        self,
        response: AgentResponse,
        order_id: str,
        selected_tools: list[str],
    ) -> dict[str, ToolTrace]:
        traces: dict[str, ToolTrace] = {}
        if "order_profile" in selected_tools:
            traces["order_profile"] = response.record_tool_trace(
                "order_profile",
                self._tools.execute("order_profile", order_id=order_id),
            )
        if "graph_relation" in selected_tools:
            traces["graph_relation"] = response.record_tool_trace(
                "graph_relation",
                self._tools.execute("graph_relation", entity_id=order_id),
            )
        if "rule_explain" in selected_tools:
            traces["rule_explain"] = response.record_tool_trace(
                "rule_explain",
                self._tools.execute("rule_explain", order_id=order_id),
            )
        return traces

    def _execute_metric_plan(
        self,
        response: AgentResponse,
        *,
        country: str,
        channel: str,
        time_range: str,
        selected_tools: list[str],
    ) -> dict[str, ToolTrace]:
        traces: dict[str, ToolTrace] = {}
        if "metric_snapshot" in selected_tools:
            traces["metric_snapshot"] = response.record_tool_trace(
                "metric_snapshot",
                self._tools.execute(
                    "metric_snapshot",
                    country=country,
                    channel=channel,
                    time_range=time_range,
                ),
            )
        if "case_lookup" in selected_tools:
            traces["case_lookup"] = response.record_tool_trace(
                "case_lookup",
                self._tools.execute("case_lookup", country=country, channel=channel),
            )
        if "dashboard_snapshot" in selected_tools:
            traces["dashboard_snapshot"] = response.record_tool_trace(
                "dashboard_snapshot",
                self._tools.execute(
                    "dashboard_snapshot",
                    dashboard_id="risk_overview",
                    country=country,
                    channel=channel,
                    time_range=time_range,
                ),
            )
        if "sql_query" in selected_tools:
            traces["sql_query"] = response.record_tool_trace(
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
        return traces

    def _build_order_response(
        self,
        request: AgentRequest,
        response: AgentResponse,
        order_id: str,
        traces: dict[str, ToolTrace],
    ) -> AgentResponse:
        order_trace = traces.get("order_profile")
        graph_trace = traces.get("graph_relation")
        rule_trace = traces.get("rule_explain")
        order = order_trace.payload if order_trace and order_trace.status == "success" else None
        graph_relation = graph_trace.payload if graph_trace and graph_trace.status == "success" else None
        rule_explanation = rule_trace.payload if rule_trace and rule_trace.status == "success" else None

        search_terms = [request.query]
        if order:
            search_terms.extend(order.get("risk_labels", []))
        if graph_relation:
            search_terms.extend(["graph relation", "fraud ring", graph_relation.get("risk_reason", "")])
        self._attach_retrieval_citations(response, " ".join(search_terms), snippet_length=160, top_k=2)

        if order:
            response.record_tool_evidence(
                tool_name="order_profile",
                summary=f"订单 {order_id} 命中 {len(order['triggered_rules'])} 条规则。",
                payload=order,
                confidence=0.78,
                source_label="订单画像",
                tags=["order", order_id, "profile"],
            )
        if graph_relation:
            response.record_tool_evidence(
                tool_name="graph_relation",
                summary=f"订单 {order_id} 关联网络风险等级为 {graph_relation['risk_level']}。",
                payload=graph_relation,
                confidence=0.74,
                source_label="关系图谱",
                tags=["order", order_id, "graph"],
            )
        if rule_explanation:
            response.record_tool_evidence(
                tool_name="rule_explain",
                summary=rule_explanation["explanation"],
                payload=rule_explanation,
                confidence=0.8,
                source_label="规则解释",
                tags=["order", order_id, "rule"],
            )

        if order is None:
            response.summary = (
                f"暂时无法完成订单 {order_id} 的完整调查，"
                f"{self._tool_status_phrase(order_trace, '订单画像')}。"
            )
            response.findings = [self._tool_status_finding("订单画像", order_trace)]
            if graph_relation:
                response.findings.extend(
                    [
                        f"图谱风险：订单 {order_id} 仍处于 {graph_relation['community_size']} 节点的关系网络中，风险等级 {graph_relation['risk_level']}",
                        f"关键路径：{graph_relation['key_path']}",
                    ]
                )
            elif graph_trace is not None:
                response.findings.append(self._tool_status_finding("图谱关系", graph_trace))
            if rule_explanation:
                response.findings.append(f"规则解释：{rule_explanation['explanation']}")
            elif rule_trace is not None:
                response.findings.append(self._tool_status_finding("规则解释", rule_trace))
            response.suggested_actions = [self._tool_status_action("订单画像", order_trace, order_id)]
            if graph_relation:
                response.suggested_actions.append("优先根据现有图谱线索复核共享设备、共享 IP 和关联账号")
            elif graph_trace is not None:
                response.suggested_actions.append(self._tool_status_action("图谱关系", graph_trace, order_id))
            if rule_trace is not None and rule_explanation is None:
                response.suggested_actions.append(self._tool_status_action("规则解释", rule_trace, order_id))
            response.confidence = 0.36 if graph_relation else 0.22
            response.artifacts["evidence_panel"] = build_evidence_panel(response)
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
        elif graph_trace is not None:
            response.findings.append(self._tool_status_finding("图谱关系", graph_trace))
        if rule_explanation:
            response.findings.extend(
                [
                    f"规则解释：{rule_explanation['explanation']}",
                    f"规则变更：{rule_explanation['recent_change']}",
                ]
            )
        elif rule_trace is not None:
            response.findings.append(self._tool_status_finding("规则解释", rule_trace))
        if order["recommended_action"] == "manual_review":
            response.findings.append("当前更适合转人工复核，而不是直接拒绝。")
        response.suggested_actions = [
            "复核最近 24 小时同设备/同支付工具订单",
            "结合相似 Case 判断是否属于误杀放大",
        ]
        if graph_relation:
            response.suggested_actions.append("优先排查共享设备和共享 IP 上的关联账号是否存在批量操作")
        elif graph_trace is not None:
            response.suggested_actions.append(self._tool_status_action("图谱关系", graph_trace, order_id))
        if rule_trace is not None and rule_explanation is None:
            response.suggested_actions.append(self._tool_status_action("规则解释", rule_trace, order_id))
        response.confidence = 0.83 if graph_relation else 0.7
        response.artifacts["evidence_panel"] = build_evidence_panel(response)
        return response

    def _build_metric_response(
        self,
        request: AgentRequest,
        response: AgentResponse,
        *,
        country: str,
        channel: str,
        time_range: str,
        traces: dict[str, ToolTrace],
    ) -> AgentResponse:
        metric_trace = traces.get("metric_snapshot")
        case_trace = traces.get("case_lookup")
        dashboard_trace = traces.get("dashboard_snapshot")
        sql_trace = traces.get("sql_query")
        metric = metric_trace.payload if metric_trace and metric_trace.status == "success" else None
        cases = case_trace.payload if case_trace and case_trace.status == "success" else []
        dashboard = dashboard_trace.payload if dashboard_trace and dashboard_trace.status == "success" else None
        sql_result = sql_trace.payload if sql_trace and sql_trace.status == "success" else None

        self._attach_retrieval_citations(response, request.query, snippet_length=180, top_k=2)
        if metric:
            response.record_tool_evidence(
                tool_name="metric_snapshot",
                summary=f"{metric['metric_name']} 当前值 {metric['current_value']}，基线 {metric['baseline_value']}。",
                payload=metric,
                confidence=0.76,
                source_label="指标快照",
                tags=["metric", country, channel, metric["metric_name"]],
            )
        if dashboard:
            response.record_tool_evidence(
                tool_name="dashboard_snapshot",
                summary=f"Dashboard 显示最大波动分层为 {dashboard['largest_segment']}。",
                payload=dashboard,
                confidence=0.72,
                source_label="Dashboard 快照",
                tags=["dashboard", country, channel],
            )
        if sql_result:
            response.record_tool_evidence(
                tool_name="sql_query",
                summary=f"SQL 分层返回 {sql_result['row_count']} 行，支持进一步下钻。",
                payload=sql_result,
                confidence=0.74,
                source_label="SQL 下钻",
                tags=["sql", country, channel, str(sql_result.get('query_name', 'metric_breakdown'))],
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
        elif dashboard_trace is not None:
            response.findings.append(self._tool_status_finding("Dashboard 快照", dashboard_trace))

        if sql_result and sql_result.get("rows"):
            top_row = sql_result["rows"][0]
            response.findings.append(
                f"SQL 分层：{top_row['segment']} 当前 {top_row['current_value']}，相对基线变化 {top_row['delta']}"
            )
        elif sql_trace is not None:
            response.findings.append(self._tool_status_finding("SQL 查询", sql_trace))

        if cases:
            response.findings.append(f"历史相似案例：{cases[0]['title']}")
        elif case_trace is not None:
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
            response.suggested_actions.append(
                self._tool_status_action("指标快照", metric_trace, f"{country}/{channel}/{time_range}")
            )
        if cases:
            response.suggested_actions.append("结合历史相似案例复核最近变更是否会放大误杀")
        elif case_trace is not None:
            response.suggested_actions.append(self._tool_status_action("历史案例", case_trace, f"{country}/{channel}"))
        if dashboard_trace is not None and dashboard is None:
            response.suggested_actions.append(
                self._tool_status_action("Dashboard 快照", dashboard_trace, f"{country}/{channel}/{time_range}")
            )
        if sql_trace is not None and not (sql_result and sql_result.get("rows")):
            response.suggested_actions.append(
                self._tool_status_action("SQL 查询", sql_trace, f"{country}/{channel}/{time_range}")
            )

        confidence = 0.18
        if metric:
            confidence = 0.68
            if cases:
                confidence += 0.11
            if dashboard or sql_result:
                confidence += 0.04
        elif cases:
            confidence = 0.3
        response.confidence = min(confidence, 0.83)
        response.artifacts["evidence_panel"] = build_evidence_panel(response)
        return response

    def _attach_retrieval_citations(
        self,
        response: AgentResponse,
        query: str,
        *,
        snippet_length: int,
        top_k: int,
    ) -> None:
        docs = self._retrieval.search(query, top_k=top_k)
        response.citations.extend(
            Citation.from_document(doc, snippet_length=snippet_length) for doc in docs
        )

    def _resolve_order_id(self, request: AgentRequest) -> str:
        return str(request.context.get("order_id", "O10001")).upper()

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
    def _tool_status_finding(label: str, trace: ToolTrace | None) -> str:
        if trace is None:
            return f"{label}：未执行"
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
    def _tool_status_action(label: str, trace: ToolTrace | None, identifier: str) -> str:
        if trace is None:
            return f"补充执行{label}，确认 {identifier} 对应证据是否需要进一步采集"
        if trace.status == "failed":
            return f"检查{label}上游服务状态与字段契约，确认 {identifier} 对应调用可恢复"
        return f"确认 {identifier} 对应的{label}数据是否已同步，必要时补齐记录后重试"
