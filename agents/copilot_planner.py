from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import re

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
