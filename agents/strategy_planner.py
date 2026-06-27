from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.models import AgentRequest


STRATEGY_TOOL_CANDIDATES = (
    "strategy_profile",
    "strategy_simulation",
    "graph_relation",
    "rule_explain",
)
REQUIRED_STRATEGY_TOOLS = (
    "strategy_profile",
    "strategy_simulation",
)
MAX_STRATEGY_TOOLS = 4
DEFAULT_SELECTED_REASONS = {
    "strategy_profile": "策略分析必须先获取当前策略画像、状态和近期问题。",
    "strategy_simulation": "通过仿真结果判断阈值调整方向及收益/误杀影响。",
    "graph_relation": "补充重点影响实体的关系网络，识别是否存在团伙集中命中。",
    "rule_explain": "补充规则解释和近期变更，判断问题是否来自策略逻辑变化。",
}
DEFAULT_UNSELECTED_REASONS = {
    "strategy_profile": "策略画像是策略分析的必选锚点。",
    "strategy_simulation": "策略仿真是阈值建议的必选锚点。",
    "graph_relation": "当前计划暂不补充重点实体关系网络。",
    "rule_explain": "当前计划暂不补充规则解释。",
}


@dataclass(frozen=True)
class StrategyPlanCandidate:
    selected_tools: list[str]
    plan_reason: str = ""
    tool_reasons: dict[str, str] | None = None
    planner_backend: str = "rule"
    planner_error: str = ""


class StrategyPlanner(ABC):
    name: str

    @abstractmethod
    def plan(self, request: AgentRequest) -> StrategyPlanCandidate:
        """Return a candidate tool-selection plan for strategy analysis."""


class RuleBasedStrategyPlanner(StrategyPlanner):
    name = "rule"

    def plan(self, request: AgentRequest) -> StrategyPlanCandidate:
        return StrategyPlanCandidate(
            selected_tools=list(STRATEGY_TOOL_CANDIDATES),
            plan_reason="默认策略分析同时执行画像、仿真、图谱和规则解释。",
            tool_reasons={
                tool: DEFAULT_SELECTED_REASONS[tool]
                for tool in STRATEGY_TOOL_CANDIDATES
            },
            planner_backend=self.name,
        )


class OpenAIStrategyPlanner(StrategyPlanner):
    """Structured-output tool selector for the strategy agent."""

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
        fallback_planner: StrategyPlanner | None = None,
        urlopen_impl: Callable[..., Any] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI strategy planner requires a non-empty API key")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec
        self._reasoning_effort = reasoning_effort
        self._max_output_tokens = max_output_tokens
        self._fallback_planner = fallback_planner or RuleBasedStrategyPlanner()
        self._urlopen = urlopen_impl or urlopen

    def plan(self, request: AgentRequest) -> StrategyPlanCandidate:
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
            return StrategyPlanCandidate(
                selected_tools=list(fallback.selected_tools),
                plan_reason=fallback.plan_reason,
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
            "You are a tool-selection component for a risk strategy agent. "
            "Select at most four tools from the allowed strategy tool list. "
            "strategy_profile and strategy_simulation are required anchors. "
            "Return only JSON matching the provided schema."
        )

    @staticmethod
    def _user_prompt(request: AgentRequest) -> str:
        context_json = json.dumps(request.context, ensure_ascii=False, sort_keys=True)
        return (
            "请为策略 Agent 生成受约束的工具计划。\n"
            f"query: {request.query}\n"
            f"context: {context_json}\n"
            "要求：\n"
            "1. selected_tools 最多 4 个。\n"
            "2. 工具只能从 strategy_profile, strategy_simulation, graph_relation, rule_explain 中选择。\n"
            "3. 必须包含 strategy_profile 和 strategy_simulation。\n"
            "4. graph_relation 依赖 strategy_profile 返回的 top_impacted_entities。\n"
            "5. tool_reasons 只给 selected_tools 里的工具填写理由。"
        )

    @staticmethod
    def _response_format() -> dict[str, Any]:
        return {
            "type": "json_schema",
            "name": "strategy_tool_plan",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "selected_tools": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": list(STRATEGY_TOOL_CANDIDATES),
                        },
                    },
                    "plan_reason": {"type": "string"},
                    "tool_reasons": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool": {
                                    "type": "string",
                                    "enum": list(STRATEGY_TOOL_CANDIDATES),
                                },
                                "reason": {"type": "string"},
                            },
                            "required": ["tool", "reason"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["selected_tools", "plan_reason", "tool_reasons"],
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
        raise ValueError("OpenAI strategy planner response did not contain output_text")

    @staticmethod
    def _candidate_from_payload(payload: dict[str, Any]) -> StrategyPlanCandidate:
        tool_reasons = {
            str(item["tool"]): str(item["reason"])
            for item in payload.get("tool_reasons", [])
            if isinstance(item, dict) and "tool" in item and "reason" in item
        }
        return StrategyPlanCandidate(
            selected_tools=[str(tool) for tool in payload["selected_tools"]],
            plan_reason=str(payload.get("plan_reason", "")),
            tool_reasons=tool_reasons,
            planner_backend="openai",
        )
