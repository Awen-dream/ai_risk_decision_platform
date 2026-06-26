from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.models import AgentRequest


METRIC_TOOL_CANDIDATES = (
    "metric_snapshot",
    "case_lookup",
    "dashboard_snapshot",
    "sql_query",
)
ORDER_TOOL_CANDIDATES = (
    "order_profile",
    "graph_relation",
    "rule_explain",
)
TOOL_CANDIDATES_BY_MODE = {
    "metric": METRIC_TOOL_CANDIDATES,
    "order": ORDER_TOOL_CANDIDATES,
}
REQUIRED_TOOL_BY_MODE = {
    "metric": "metric_snapshot",
    "order": "order_profile",
}
MAX_TOOLS_BY_MODE = {
    "metric": 3,
    "order": 3,
}
DEFAULT_SELECTED_REASONS = {
    "metric_snapshot": "先确认核心指标是否真的异常，以及异常开始时间和疑似驱动因素。",
    "case_lookup": "补充历史相似案例，帮助判断是新问题还是已知模式复现。",
    "dashboard_snapshot": "通过看板快照快速定位波动最大的分层或业务切面。",
    "sql_query": "需要更细的分层明细时，用 SQL 结果做进一步下钻。",
    "order_profile": "订单调查必须先获取订单画像和命中规则。",
    "graph_relation": "补充订单或实体的关联网络，判断是否存在团伙迹象。",
    "rule_explain": "补充规则解释和近期规则变更，帮助判断误杀还是有效拦截。",
}
DEFAULT_UNSELECTED_REASONS = {
    "metric_snapshot": "指标异常调查必须优先确认核心指标快照。",
    "case_lookup": "当前计划优先使用实时工具，暂不补充历史案例。",
    "dashboard_snapshot": "当前计划不需要看板级分层快照。",
    "sql_query": "当前计划不需要 SQL 明细下钻。",
    "order_profile": "订单调查必须优先确认订单画像。",
    "graph_relation": "当前计划暂不补充关系网络。",
    "rule_explain": "当前计划暂不补充规则解释。",
}


@dataclass(frozen=True)
class InvestigationPlanCandidate:
    mode: str
    selected_tools: list[str]
    mode_reason: str = ""
    tool_reasons: dict[str, str] | None = None
    planner_backend: str = "rule"
    planner_error: str = ""


class InvestigationPlanner(ABC):
    name: str

    @abstractmethod
    def plan(self, request: AgentRequest) -> InvestigationPlanCandidate:
        """Return a candidate tool-selection plan for investigation."""


class RuleBasedInvestigationPlanner(InvestigationPlanner):
    name = "rule"

    def plan(self, request: AgentRequest) -> InvestigationPlanCandidate:
        mode = "order" if request.context.get("order_id") else "metric"
        if mode == "order":
            return InvestigationPlanCandidate(
                mode=mode,
                selected_tools=["order_profile", "graph_relation", "rule_explain"],
                mode_reason="请求包含 order_id，优先按订单调查路径执行。",
                tool_reasons={
                    "order_profile": DEFAULT_SELECTED_REASONS["order_profile"],
                    "graph_relation": DEFAULT_SELECTED_REASONS["graph_relation"],
                    "rule_explain": DEFAULT_SELECTED_REASONS["rule_explain"],
                },
                planner_backend=self.name,
            )
        return InvestigationPlanCandidate(
            mode=mode,
            selected_tools=["metric_snapshot", "case_lookup", "dashboard_snapshot"],
            mode_reason="请求以指标异常为主，先确认指标、历史案例和看板下钻。",
            tool_reasons={
                "metric_snapshot": DEFAULT_SELECTED_REASONS["metric_snapshot"],
                "case_lookup": DEFAULT_SELECTED_REASONS["case_lookup"],
                "dashboard_snapshot": DEFAULT_SELECTED_REASONS["dashboard_snapshot"],
            },
            planner_backend=self.name,
        )


class OpenAIInvestigationPlanner(InvestigationPlanner):
    """Structured-output tool selector for the investigation agent."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_sec: float = 10.0,
        reasoning_effort: str = "low",
        max_output_tokens: int = 400,
        fallback_planner: InvestigationPlanner | None = None,
        urlopen_impl: Callable[..., Any] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI investigation planner requires a non-empty API key")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec
        self._reasoning_effort = reasoning_effort
        self._max_output_tokens = max_output_tokens
        self._fallback_planner = fallback_planner or RuleBasedInvestigationPlanner()
        self._urlopen = urlopen_impl or urlopen

    def plan(self, request: AgentRequest) -> InvestigationPlanCandidate:
        try:
            payload = self._post_response(request)
            candidate_payload = json.loads(self._extract_output_text(payload))
            return self._candidate_from_payload(candidate_payload)
        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            fallback = self._fallback_planner.plan(request)
            return InvestigationPlanCandidate(
                mode=fallback.mode,
                selected_tools=list(fallback.selected_tools),
                mode_reason=fallback.mode_reason,
                tool_reasons=dict(fallback.tool_reasons or {}),
                planner_backend="openai_fallback_rule",
                planner_error=f"{type(exc).__name__}: {exc}",
            )

    def _post_response(self, request: AgentRequest) -> dict[str, Any]:
        body = {
            "model": self._model,
            "instructions": self._instructions(),
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": self._user_prompt(request)},
                    ],
                }
            ],
            "text": {"format": self._response_format()},
            "max_output_tokens": self._max_output_tokens,
            "store": False,
        }
        if self._reasoning_effort:
            body["reasoning"] = {"effort": self._reasoning_effort}
        request_obj = Request(
            f"{self._base_url}/responses",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with self._urlopen(request_obj, timeout=self._timeout_sec) as response:
            return json.load(response)

    @staticmethod
    def _instructions() -> str:
        return (
            "You are a tool-selection component for a risk investigation agent. "
            "Select at most three tools from the allowed investigation tool list. "
            "If the request contains an order context, mode must be order and order_profile is required. "
            "Otherwise mode must be metric and metric_snapshot is required. "
            "Return only JSON matching the provided schema."
        )

    @staticmethod
    def _user_prompt(request: AgentRequest) -> str:
        context_json = json.dumps(request.context, ensure_ascii=False, sort_keys=True)
        return (
            "请为调查 Agent 生成受约束的工具计划。\n"
            f"query: {request.query}\n"
            f"context: {context_json}\n"
            "要求：\n"
            "1. mode 只能是 metric 或 order。\n"
            "2. selected_tools 最多 3 个。\n"
            "3. mode=metric 时工具只能从 metric_snapshot, case_lookup, dashboard_snapshot, sql_query 中选择，且必须包含 metric_snapshot。\n"
            "4. mode=order 时工具只能从 order_profile, graph_relation, rule_explain 中选择，且必须包含 order_profile。\n"
            "5. tool_reasons 只给 selected_tools 里的工具填写理由。"
        )

    @staticmethod
    def _response_format() -> dict[str, Any]:
        return {
            "type": "json_schema",
            "name": "investigation_tool_plan",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["metric", "order"],
                    },
                    "selected_tools": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": list(METRIC_TOOL_CANDIDATES + ORDER_TOOL_CANDIDATES),
                        },
                    },
                    "mode_reason": {"type": "string"},
                    "tool_reasons": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool": {
                                    "type": "string",
                                    "enum": list(METRIC_TOOL_CANDIDATES + ORDER_TOOL_CANDIDATES),
                                },
                                "reason": {"type": "string"},
                            },
                            "required": ["tool", "reason"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["mode", "selected_tools", "mode_reason", "tool_reasons"],
                "additionalProperties": False,
            },
        }

    @staticmethod
    def _extract_output_text(payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text
        for item in payload.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and str(content.get("text", "")).strip():
                    return str(content["text"])
        raise ValueError("OpenAI investigation planner response did not contain output_text")

    @staticmethod
    def _candidate_from_payload(payload: dict[str, Any]) -> InvestigationPlanCandidate:
        tool_reasons = {
            str(item["tool"]): str(item["reason"])
            for item in payload.get("tool_reasons", [])
            if isinstance(item, dict) and "tool" in item and "reason" in item
        }
        return InvestigationPlanCandidate(
            mode=str(payload["mode"]),
            selected_tools=[str(tool) for tool in payload["selected_tools"]],
            mode_reason=str(payload.get("mode_reason", "")),
            tool_reasons=tool_reasons,
            planner_backend="openai",
        )
