from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import json
import re
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.models import AgentRequest


STRATEGY_ID_PATTERN = re.compile(r"(STRAT-\d+)", re.IGNORECASE)
ENTITY_ID_PATTERN = re.compile(r"((?:U|O)\d{5})", re.IGNORECASE)
CANONICAL_PLAN_STEPS = ("调查", "策略", "图谱")


class CopilotIntent(str, Enum):
    METRIC_ANOMALY = "metric_anomaly"
    ORDER_CASE = "order_case"
    STRATEGY_REVIEW = "strategy_review"
    FRAUD_RING = "fraud_ring"
    COMPOSITE = "composite"


@dataclass(frozen=True)
class CopilotPlanStep:
    label: str
    reason: str


@dataclass(frozen=True)
class CopilotPlanCandidate:
    intent: str
    selected_steps: list[str]
    intent_reason: str = ""
    step_reasons: dict[str, str] = field(default_factory=dict)
    planner_backend: str = "rule"
    planner_error: str = ""


class CopilotPlanner(ABC):
    name: str

    @abstractmethod
    def plan(self, request: AgentRequest) -> CopilotPlanCandidate:
        """Return a candidate intent and plan for the request."""


class RuleBasedCopilotPlanner(CopilotPlanner):
    """Deterministic planner used as the default and validation fallback."""

    name = "rule"

    def plan(self, request: AgentRequest) -> CopilotPlanCandidate:
        intent = self._classify_intent(request)
        return CopilotPlanCandidate(
            intent=intent.value,
            selected_steps=[step.label for step in self._plan(intent)],
            intent_reason=self._intent_reason(request, intent),
            step_reasons={
                "调查": "先做基础风险调查，定位异常对象、核心证据和影响范围。",
                "策略": "问题包含策略或阈值信号，需要补充策略效果和仿真建议。",
                "图谱": "问题包含实体关系或团伙信号，需要补充关系网络和关键路径。",
            },
            planner_backend=self.name,
        )

    @staticmethod
    def _plan(intent: CopilotIntent) -> list[CopilotPlanStep]:
        steps = [
            CopilotPlanStep(
                label="调查",
                reason="先做基础风险调查，定位异常对象、核心证据和影响范围。",
            )
        ]
        if intent in (CopilotIntent.STRATEGY_REVIEW, CopilotIntent.COMPOSITE):
            steps.append(
                CopilotPlanStep(
                    label="策略",
                    reason="问题包含策略或阈值信号，需要补充策略效果和仿真建议。",
                )
            )
        if intent in (CopilotIntent.FRAUD_RING, CopilotIntent.ORDER_CASE, CopilotIntent.COMPOSITE):
            steps.append(
                CopilotPlanStep(
                    label="图谱",
                    reason="问题包含实体关系或团伙信号，需要补充关系网络和关键路径。",
                )
            )
        return steps

    @staticmethod
    def _intent_reason(request: AgentRequest, intent: CopilotIntent) -> str:
        if intent == CopilotIntent.COMPOSITE:
            return "同时命中策略与图谱信号，需要联合分析。"
        if intent == CopilotIntent.STRATEGY_REVIEW:
            return "问题包含策略、阈值或 shadow evaluation 信号。"
        if intent == CopilotIntent.ORDER_CASE:
            return "问题包含订单实体，并且需要补充图谱关联。"
        if intent == CopilotIntent.FRAUD_RING:
            return "问题包含图谱、团伙或关系网络信号。"
        return "问题以指标异常为主，先进入基础调查。"

    @staticmethod
    def _should_include_strategy(request: AgentRequest) -> bool:
        if "strategy_id" in request.context:
            return True
        lowered = request.query.lower()
        if "策略" in request.query or "阈值" in request.query or "shadow evaluation" in lowered:
            return True
        return STRATEGY_ID_PATTERN.search(request.query) is not None

    @staticmethod
    def _should_include_graph(request: AgentRequest) -> bool:
        if any(key in request.context for key in ("entity_id", "user_id", "order_id")):
            return True
        lowered = request.query.lower()
        if "团伙" in request.query or "关系网络" in request.query or "graph" in lowered:
            return True
        return ENTITY_ID_PATTERN.search(request.query) is not None

    def _classify_intent(self, request: AgentRequest) -> CopilotIntent:
        has_strategy = self._should_include_strategy(request)
        has_graph = self._should_include_graph(request)
        has_order = "order_id" in request.context or (
            ENTITY_ID_PATTERN.search(request.query) is not None and "订单" in request.query
        )
        if has_strategy and has_graph:
            return CopilotIntent.COMPOSITE
        if has_strategy:
            return CopilotIntent.STRATEGY_REVIEW
        if has_graph:
            if has_order:
                return CopilotIntent.ORDER_CASE
            return CopilotIntent.FRAUD_RING
        return CopilotIntent.METRIC_ANOMALY


class OpenAICopilotPlanner(CopilotPlanner):
    """Structured-output planner backed by the OpenAI Responses API."""

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
        fallback_planner: CopilotPlanner | None = None,
        urlopen_impl: Callable[..., Any] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI planner requires a non-empty API key")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec
        self._reasoning_effort = reasoning_effort
        self._max_output_tokens = max_output_tokens
        self._fallback_planner = fallback_planner or RuleBasedCopilotPlanner()
        self._urlopen = urlopen_impl or urlopen

    def plan(self, request: AgentRequest) -> CopilotPlanCandidate:
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
            return CopilotPlanCandidate(
                intent=fallback.intent,
                selected_steps=list(fallback.selected_steps),
                intent_reason=fallback.intent_reason,
                step_reasons=dict(fallback.step_reasons),
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
                        {
                            "type": "input_text",
                            "text": self._user_prompt(request),
                        }
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
            "You are a planning component for a risk copilot. "
            "Classify the request into one of the supported intents and select execution steps "
            "from the fixed set: 调查, 策略, 图谱. "
            "调查 is always required. "
            "Return only JSON that matches the provided schema."
        )

    @staticmethod
    def _user_prompt(request: AgentRequest) -> str:
        context_json = json.dumps(request.context, ensure_ascii=False, sort_keys=True)
        return (
            "请基于以下风险问题生成候选计划。\n"
            f"query: {request.query}\n"
            f"context: {context_json}\n"
            "要求：\n"
            "1. intent 只能是 metric_anomaly, order_case, strategy_review, fraud_ring, composite。\n"
            "2. selected_steps 只能从 调查, 策略, 图谱 中选择，且必须包含 调查。\n"
            "3. step_reasons 只给 selected_steps 里的步骤填写理由。\n"
            "4. 如果同时出现策略和图谱信号，优先用 composite。"
        )

    @staticmethod
    def _response_format() -> dict[str, Any]:
        return {
            "type": "json_schema",
            "name": "copilot_plan",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "enum": [intent.value for intent in CopilotIntent],
                    },
                    "selected_steps": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": list(CANONICAL_PLAN_STEPS),
                        },
                    },
                    "intent_reason": {"type": "string"},
                    "step_reasons": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step": {
                                    "type": "string",
                                    "enum": list(CANONICAL_PLAN_STEPS),
                                },
                                "reason": {"type": "string"},
                            },
                            "required": ["step", "reason"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["intent", "selected_steps", "intent_reason", "step_reasons"],
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
        raise ValueError("OpenAI planner response did not contain output_text")

    @staticmethod
    def _candidate_from_payload(payload: dict[str, Any]) -> CopilotPlanCandidate:
        step_reasons = {
            str(item["step"]): str(item["reason"])
            for item in payload.get("step_reasons", [])
            if isinstance(item, dict) and "step" in item and "reason" in item
        }
        return CopilotPlanCandidate(
            intent=str(payload["intent"]),
            selected_steps=[str(step) for step in payload["selected_steps"]],
            intent_reason=str(payload.get("intent_reason", "")),
            step_reasons=step_reasons,
            planner_backend="openai",
        )
