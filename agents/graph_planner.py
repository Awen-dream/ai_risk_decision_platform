from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.models import AgentRequest


GRAPH_TOOL_CANDIDATES = ("graph_relation",)
REQUIRED_GRAPH_TOOLS = ("graph_relation",)
MAX_GRAPH_TOOLS = 1
DEFAULT_SELECTED_REASONS = {
    "graph_relation": "图谱分析必须先获取实体关系网络，确认共享设备、共享 IP、关联账号和关键路径。",
}
DEFAULT_UNSELECTED_REASONS = {
    "graph_relation": "图谱分析当前只有 graph_relation 作为必选锚点。",
}


@dataclass(frozen=True)
class GraphPlanCandidate:
    selected_tools: list[str]
    plan_reason: str = ""
    tool_reasons: dict[str, str] | None = None
    planner_backend: str = "rule"
    planner_error: str = ""


class GraphPlanner(ABC):
    name: str

    @abstractmethod
    def plan(self, request: AgentRequest) -> GraphPlanCandidate:
        """Return a candidate tool-selection plan for graph analysis."""


class RuleBasedGraphPlanner(GraphPlanner):
    name = "rule"

    def plan(self, request: AgentRequest) -> GraphPlanCandidate:
        return GraphPlanCandidate(
            selected_tools=["graph_relation"],
            plan_reason="默认图谱分析以实体关系网络作为必选证据锚点。",
            tool_reasons={
                "graph_relation": DEFAULT_SELECTED_REASONS["graph_relation"],
            },
            planner_backend=self.name,
        )


class OpenAIGraphPlanner(GraphPlanner):
    """Structured-output tool selector for the graph agent."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_sec: float = 10.0,
        reasoning_effort: str = "low",
        max_output_tokens: int = 300,
        fallback_planner: GraphPlanner | None = None,
        urlopen_impl: Callable[..., Any] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI graph planner requires a non-empty API key")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec
        self._reasoning_effort = reasoning_effort
        self._max_output_tokens = max_output_tokens
        self._fallback_planner = fallback_planner or RuleBasedGraphPlanner()
        self._urlopen = urlopen_impl or urlopen

    def plan(self, request: AgentRequest) -> GraphPlanCandidate:
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
            return GraphPlanCandidate(
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
            "You are a tool-selection component for a graph-risk agent. "
            "Select at most one graph tool. graph_relation is the required evidence anchor. "
            "Return only JSON matching the provided schema."
        )

    @staticmethod
    def _user_prompt(request: AgentRequest) -> str:
        context_json = json.dumps(request.context, ensure_ascii=False, sort_keys=True)
        return (
            "请为图谱 Agent 生成受约束的工具计划。\n"
            f"query: {request.query}\n"
            f"context: {context_json}\n"
            "要求：\n"
            "1. selected_tools 最多 1 个。\n"
            "2. 工具只能从 graph_relation 中选择。\n"
            "3. 必须包含 graph_relation。\n"
            "4. tool_reasons 只给 selected_tools 里的工具填写理由。"
        )

    @staticmethod
    def _response_format() -> dict[str, Any]:
        return {
            "type": "json_schema",
            "name": "graph_tool_plan",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "selected_tools": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": list(GRAPH_TOOL_CANDIDATES),
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
                                    "enum": list(GRAPH_TOOL_CANDIDATES),
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
        raise ValueError("OpenAI graph planner response did not contain output_text")

    @staticmethod
    def _candidate_from_payload(payload: dict[str, Any]) -> GraphPlanCandidate:
        tool_reasons = {
            str(item["tool"]): str(item["reason"])
            for item in payload.get("tool_reasons", [])
            if isinstance(item, dict) and "tool" in item and "reason" in item
        }
        return GraphPlanCandidate(
            selected_tools=[str(tool) for tool in payload["selected_tools"]],
            plan_reason=str(payload.get("plan_reason", "")),
            tool_reasons=tool_reasons,
            planner_backend="openai",
        )
