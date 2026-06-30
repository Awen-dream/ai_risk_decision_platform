from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.base import Agent
from core.models import AgentRequest, AgentResponse, Citation, PlannerTraceStep, ToolTrace
from core.planning import build_tool_using_state, evidence_gaps_from_traces
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

ROOT_CAUSE_STEPS = [
    "metric_snapshot",
    "dashboard_snapshot",
    "sql_query",
    "rule_explain",
]


@dataclass(frozen=True)
class RootCausePlan:
    selected_tools: list[str]
    planner_trace: list[PlannerTraceStep]
    planner_backend: str = "rule"
    fallback_used: bool = False
    validation_errors: list[str] | None = None

    def to_artifact(self) -> dict[str, Any]:
        return {
            "backend": self.planner_backend,
            "fallback_used": self.fallback_used,
            "validation_errors": list(self.validation_errors or []),
            "final_intent": "root_cause_analysis",
            "final_tools": list(self.selected_tools),
            "step_budget": 4,
        }


class RootCauseAgent(Agent):
    """V4a root-cause agent that verifies and ranks explicit hypotheses."""

    name = "root_cause"

    def __init__(self, tools: ToolRegistry, retrieval: RetrievalService) -> None:
        self._tools = tools
        self._retrieval = retrieval

    def run(self, request: AgentRequest) -> AgentResponse:
        response = AgentResponse(agent_name=self.name)
        plan = self._build_plan()
        response.intent = "root_cause_analysis"
        response.plan_steps = list(plan.selected_tools)
        response.planner_trace = plan.planner_trace
        response.artifacts["root_cause_plan"] = plan.to_artifact()

        country = self._resolve_country(request)
        channel = self._resolve_channel(request)
        time_range = str(request.context.get("time_range", "recent_24h"))
        traces = self._execute_plan(
            response,
            request=request,
            country=country,
            channel=channel,
            time_range=time_range,
        )
        self._attach_intermediate_state(response, plan, traces)
        self._attach_citations(response, request.query)
        analysis = self._build_analysis(
            country=country,
            channel=channel,
            time_range=time_range,
            traces=traces,
        )
        response.artifacts["root_cause_analysis"] = analysis
        self._attach_evidence(response, traces)
        self._attach_findings_and_actions(response, analysis)
        response.confidence = float(analysis["top_root_cause"]["confidence"])
        response.summary = (
            f"根因分析完成，Top1 根因为 {analysis['top_root_cause']['label']}，"
            f"置信度 {response.confidence:.2f}。"
        )
        return response

    @staticmethod
    def _build_plan() -> RootCausePlan:
        reasons = {
            "metric_snapshot": "先确认异常指标、开始时间和上游初判驱动。",
            "dashboard_snapshot": "用看板分层定位波动最大的业务切面。",
            "sql_query": "用 SQL 分层明细验证波动是否集中在特定 segment。",
            "rule_explain": "核对规则或策略近期变更，验证是否与异常时间重合。",
        }
        return RootCausePlan(
            selected_tools=list(ROOT_CAUSE_STEPS),
            planner_trace=[
                PlannerTraceStep(step=tool, selected=True, reason=reasons[tool])
                for tool in ROOT_CAUSE_STEPS
            ],
        )

    def _execute_plan(
        self,
        response: AgentResponse,
        *,
        request: AgentRequest,
        country: str,
        channel: str,
        time_range: str,
    ) -> dict[str, ToolTrace]:
        traces: dict[str, ToolTrace] = {}
        traces["metric_snapshot"] = response.record_tool_trace(
            "metric_snapshot",
            self._tools.execute(
                "metric_snapshot",
                country=country,
                channel=channel,
                time_range=time_range,
            ),
        )
        traces["dashboard_snapshot"] = response.record_tool_trace(
            "dashboard_snapshot",
            self._tools.execute(
                "dashboard_snapshot",
                dashboard_id=str(request.context.get("dashboard_id", "risk_overview")),
                country=country,
                channel=channel,
                time_range=time_range,
            ),
        )
        traces["sql_query"] = response.record_tool_trace(
            "sql_query",
            self._tools.execute(
                "sql_query",
                query_name=str(request.context.get("query_name", "metric_breakdown")),
                parameters={
                    "country": country,
                    "channel": channel,
                    "time_range": time_range,
                },
                limit=int(request.context.get("limit", 20)),
            ),
        )
        traces["rule_explain"] = response.record_tool_trace(
            "rule_explain",
            self._tools.execute(
                "rule_explain",
                rule_id=request.context.get("rule_id", "device_velocity_spike"),
                strategy_id=request.context.get("strategy_id"),
                order_id=request.context.get("order_id"),
            ),
        )
        return traces

    @staticmethod
    def _attach_intermediate_state(
        response: AgentResponse,
        plan: RootCausePlan,
        traces: dict[str, ToolTrace],
    ) -> None:
        labels = {
            "metric_snapshot": "指标快照",
            "dashboard_snapshot": "看板快照",
            "sql_query": "SQL 分层",
            "rule_explain": "规则解释",
        }
        next_actions = {
            "metric_snapshot": "补齐异常指标快照后重新生成根因候选",
            "dashboard_snapshot": "确认看板分层数据同步完成后重试",
            "sql_query": "确认 SQL 分层查询配置和参数后重试",
            "rule_explain": "补齐规则 ID、策略 ID 或订单 ID 后复核规则变更",
        }
        response.attach_intermediate_state(
            build_tool_using_state(
                thought_summary="在 4 步预算内验证指标、看板、SQL 分层和规则变更，形成根因排序。",
                planner_trace=plan.planner_trace,
                selected_steps=plan.selected_tools,
                step_budget=4,
                planner_backend=plan.planner_backend,
                fallback_used=plan.fallback_used,
                validation_errors=plan.validation_errors or [],
                evidence_gap=evidence_gaps_from_traces(
                    list(traces.values()),
                    label_by_tool=labels,
                    next_action_by_tool=next_actions,
                ),
            )
        )

    def _attach_citations(self, response: AgentResponse, query: str) -> None:
        for document in self._retrieval.search(query, top_k=2):
            response.citations.append(Citation.from_document(document, snippet_length=180))

    @staticmethod
    def _attach_evidence(
        response: AgentResponse,
        traces: dict[str, ToolTrace],
    ) -> None:
        confidence_by_tool = {
            "metric_snapshot": 0.76,
            "dashboard_snapshot": 0.72,
            "sql_query": 0.78,
            "rule_explain": 0.82,
        }
        for name, trace in traces.items():
            if trace.status != "success":
                continue
            response.record_evidence(
                source=name,
                source_type="tool",
                summary=trace.summary,
                payload=trace.payload,
                confidence=confidence_by_tool.get(name, 0.7),
            )

    @staticmethod
    def _build_analysis(
        *,
        country: str,
        channel: str,
        time_range: str,
        traces: dict[str, ToolTrace],
    ) -> dict[str, Any]:
        metric = _successful_payload(traces.get("metric_snapshot"))
        dashboard = _successful_payload(traces.get("dashboard_snapshot"))
        sql_result = _successful_payload(traces.get("sql_query"))
        rule = _successful_payload(traces.get("rule_explain"))
        top_segment = _top_sql_segment(sql_result)
        metric_driver = str(metric.get("suspected_driver", "")) if metric else ""
        recent_change = str(metric.get("recent_change", "")) if metric else ""
        rule_change = str(rule.get("recent_change", "")) if rule else ""
        largest_segment = str(dashboard.get("largest_segment", "")) if dashboard else ""

        hypotheses = [
            {
                "id": "strategy_threshold_change",
                "label": "策略阈值或规则变更导致正常流量被过度拦截",
                "rank": 1,
                "confidence": _bounded_confidence(
                    0.54
                    + (0.16 if recent_change else 0)
                    + (0.14 if rule_change else 0)
                    + (0.08 if "阈值" in metric_driver or "threshold" in metric_driver.lower() else 0)
                ),
                "status": "supported",
                "supporting_evidence": _present(
                    [
                        _evidence_ref("metric_snapshot", recent_change),
                        _evidence_ref("rule_explain", rule_change),
                        _evidence_ref("metric_snapshot", metric_driver),
                    ]
                ),
                "counter_evidence": _present(
                    [
                        _counter_ref(
                            "sql_query",
                            "SQL 分层显示波动集中在特定 segment，可能不是纯规则阈值问题。",
                            bool(top_segment),
                        )
                    ]
                ),
                "verification_steps": [
                    "回放变更前后样本，比较命中率、拒绝率和人工复核量。",
                    "对 device_velocity_spike 做 shadow evaluation，验证回调阈值后的误杀变化。",
                ],
            },
            {
                "id": "segment_concentration",
                "label": "异常集中在特定分层或设备风险 segment",
                "rank": 2,
                "confidence": _bounded_confidence(
                    0.44
                    + (0.16 if largest_segment else 0)
                    + (0.16 if top_segment else 0)
                    + (0.08 if top_segment and top_segment == largest_segment else 0)
                ),
                "status": "supported" if top_segment or largest_segment else "needs_more_evidence",
                "supporting_evidence": _present(
                    [
                        _evidence_ref("dashboard_snapshot", f"最大波动分层 {largest_segment}"),
                        _evidence_ref("sql_query", f"Top SQL segment {top_segment}"),
                    ]
                ),
                "counter_evidence": _present(
                    [
                        _counter_ref(
                            "rule_explain",
                            "规则变更时间与指标异常时间更接近，segment 集中可能是结果而非根因。",
                            bool(rule_change),
                        )
                    ]
                ),
                "verification_steps": [
                    "按卡组织、设备风险标签和 issuer 继续拆分 SQL 明细。",
                    "抽样比对最大波动 segment 的拒绝原因和命中规则。",
                ],
            },
            {
                "id": "external_traffic_shift",
                "label": "外部流量结构或渠道质量变化放大风险指标",
                "rank": 3,
                "confidence": _bounded_confidence(0.36 + (0.08 if metric else 0)),
                "status": "needs_more_evidence",
                "supporting_evidence": _present(
                    [_evidence_ref("metric_snapshot", "指标异常需要继续排查外部流量结构。")]
                ),
                "counter_evidence": _present(
                    [
                        _counter_ref(
                            "rule_explain",
                            "已有规则近期变更证据，优先级低于策略阈值假设。",
                            bool(rule_change),
                        ),
                        _counter_ref(
                            "dashboard_snapshot",
                            "看板显示波动集中在内部可解释 segment。",
                            bool(largest_segment),
                        ),
                    ]
                ),
                "verification_steps": [
                    "拉取渠道侧成功率、发卡行响应码和外部流量来源变化。",
                    "比较异常窗口内新老用户、卡组织和 issuer 的流量占比。",
                ],
            },
        ]
        hypotheses.sort(key=lambda item: float(item["confidence"]), reverse=True)
        for index, item in enumerate(hypotheses, start=1):
            item["rank"] = index
        top_root_cause = hypotheses[0]
        return {
            "version": "v4a",
            "scope": {
                "country": country,
                "channel": channel,
                "time_range": time_range,
            },
            "top_root_cause": {
                "id": top_root_cause["id"],
                "label": top_root_cause["label"],
                "confidence": top_root_cause["confidence"],
            },
            "hypotheses": hypotheses,
            "evidence_matrix": _evidence_matrix(hypotheses),
            "next_verification_steps": list(top_root_cause["verification_steps"]),
        }

    @staticmethod
    def _attach_findings_and_actions(
        response: AgentResponse,
        analysis: dict[str, Any],
    ) -> None:
        response.findings = [
            f"[根因排序] #{item['rank']} {item['label']}，置信度 {item['confidence']}"
            for item in analysis["hypotheses"]
        ]
        response.suggested_actions = list(analysis["next_verification_steps"])

    @staticmethod
    def _resolve_country(request: AgentRequest) -> str:
        if "country" in request.context:
            return str(request.context["country"])
        lowered = request.query.lower()
        for alias, value in COUNTRY_ALIASES.items():
            if alias.lower() in lowered:
                return value
        return "BR"

    @staticmethod
    def _resolve_channel(request: AgentRequest) -> str:
        if "channel" in request.context:
            return str(request.context["channel"])
        lowered = request.query.lower()
        for alias, value in CHANNEL_ALIASES.items():
            if alias.lower() in lowered:
                return value
        return "credit_card"


def _successful_payload(trace: ToolTrace | None) -> dict[str, Any] | None:
    if trace is None or trace.status != "success" or not isinstance(trace.payload, dict):
        return None
    return trace.payload


def _top_sql_segment(sql_result: dict[str, Any] | None) -> str:
    if not sql_result:
        return ""
    rows = sql_result.get("rows", [])
    if not isinstance(rows, list) or not rows:
        return ""
    first = rows[0]
    if not isinstance(first, dict):
        return ""
    return str(first.get("segment", ""))


def _bounded_confidence(value: float) -> float:
    return round(max(0.0, min(0.95, value)), 2)


def _evidence_ref(source: str, summary: str) -> dict[str, str] | None:
    if not summary:
        return None
    return {"source": source, "summary": summary}


def _counter_ref(source: str, summary: str, enabled: bool) -> dict[str, str] | None:
    if not enabled:
        return None
    return {"source": source, "summary": summary}


def _present(items: list[dict[str, str] | None]) -> list[dict[str, str]]:
    return [item for item in items if item is not None]


def _evidence_matrix(hypotheses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for hypothesis in hypotheses:
        hypothesis_id = str(hypothesis["id"])
        for item in hypothesis.get("supporting_evidence", []):
            source = str(item.get("source", "unknown"))
            rows.setdefault(source, {"source": source, "supports": [], "counters": []})
            rows[source]["supports"].append(hypothesis_id)
        for item in hypothesis.get("counter_evidence", []):
            source = str(item.get("source", "unknown"))
            rows.setdefault(source, {"source": source, "supports": [], "counters": []})
            rows[source]["counters"].append(hypothesis_id)
    return list(rows.values())
