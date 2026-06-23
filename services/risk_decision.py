from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.models import AgentResponse


@dataclass(frozen=True)
class DecisionOutcome:
    decision: str
    risk_level: str
    recommended_action: str
    escalation_reason: str | None = None
    policy_controls: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "DecisionOutcome":
        return cls(
            decision=str(payload["decision"]),
            risk_level=str(payload["risk_level"]),
            recommended_action=str(payload["recommended_action"]),
            escalation_reason=(
                str(payload["escalation_reason"])
                if payload.get("escalation_reason") is not None
                else None
            ),
            policy_controls=tuple(str(item) for item in payload.get("policy_controls", [])),
        )


@dataclass(frozen=True)
class DecisionActionPlan:
    queue: str
    priority: str
    sla_hours: int
    owner_role: str
    next_actions: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "DecisionActionPlan":
        return cls(
            queue=str(payload["queue"]),
            priority=str(payload["priority"]),
            sla_hours=int(payload["sla_hours"]),
            owner_role=str(payload["owner_role"]),
            next_actions=tuple(str(item) for item in payload.get("next_actions", [])),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "queue": self.queue,
            "priority": self.priority,
            "sla_hours": self.sla_hours,
            "owner_role": self.owner_role,
            "next_actions": list(self.next_actions),
        }


@dataclass(frozen=True)
class EvidenceStrengthPolicy:
    strong_min_confidence: float = 0.75
    strong_min_evidence_count: int = 2
    medium_min_confidence: float = 0.5

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "EvidenceStrengthPolicy":
        return cls(
            strong_min_confidence=float(payload.get("strong_min_confidence", 0.75)),
            strong_min_evidence_count=int(payload.get("strong_min_evidence_count", 2)),
            medium_min_confidence=float(payload.get("medium_min_confidence", 0.5)),
        )

    def classify(self, *, confidence: float, evidence_count: int) -> str:
        if confidence >= self.strong_min_confidence and evidence_count >= self.strong_min_evidence_count:
            return "strong"
        if confidence >= self.medium_min_confidence and evidence_count > 0:
            return "medium"
        return "weak"


@dataclass(frozen=True)
class RiskDecisionPolicy:
    high_graph_levels: tuple[str, ...] = ("high",)
    medium_graph_levels: tuple[str, ...] = ("medium",)
    reject_order_actions: tuple[str, ...] = ("reject",)
    review_order_actions: tuple[str, ...] = ("manual_review",)
    evidence_strength: EvidenceStrengthPolicy = field(default_factory=EvidenceStrengthPolicy)
    outcomes: dict[str, DecisionOutcome] = field(default_factory=dict)
    action_plans: dict[str, DecisionActionPlan] = field(default_factory=dict)

    @classmethod
    def default(cls) -> "RiskDecisionPolicy":
        return cls(outcomes=_default_outcomes(), action_plans=_default_action_plans())

    @classmethod
    def from_file(cls, path: Path) -> "RiskDecisionPolicy":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("risk decision policy must be a JSON object")
        return cls.from_mapping(payload)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "RiskDecisionPolicy":
        signals = payload.get("signals", {})
        if not isinstance(signals, dict):
            raise ValueError("risk decision policy signals must be an object")
        evidence_strength_payload = payload.get("evidence_strength", {})
        if not isinstance(evidence_strength_payload, dict):
            raise ValueError("risk decision policy evidence_strength must be an object")
        outcomes_payload = payload.get("outcomes", {})
        if not isinstance(outcomes_payload, dict):
            raise ValueError("risk decision policy outcomes must be an object")
        action_plans_payload = payload.get("action_plans", {})
        if not isinstance(action_plans_payload, dict):
            raise ValueError("risk decision policy action_plans must be an object")
        outcomes = _default_outcomes()
        for name, outcome_payload in outcomes_payload.items():
            if not isinstance(outcome_payload, dict):
                raise ValueError(f"risk decision outcome must be an object: {name}")
            outcomes[str(name)] = DecisionOutcome.from_mapping(outcome_payload)
        action_plans = _default_action_plans()
        for name, action_plan_payload in action_plans_payload.items():
            if not isinstance(action_plan_payload, dict):
                raise ValueError(f"risk decision action plan must be an object: {name}")
            action_plans[str(name)] = DecisionActionPlan.from_mapping(action_plan_payload)
        return cls(
            high_graph_levels=_normalized_tuple(signals.get("high_graph_levels", ("high",))),
            medium_graph_levels=_normalized_tuple(signals.get("medium_graph_levels", ("medium",))),
            reject_order_actions=_normalized_tuple(signals.get("reject_order_actions", ("reject",))),
            review_order_actions=_normalized_tuple(signals.get("review_order_actions", ("manual_review",))),
            evidence_strength=EvidenceStrengthPolicy.from_mapping(evidence_strength_payload),
            outcomes=outcomes,
            action_plans=action_plans,
        )

    def evaluate(
        self,
        *,
        intent: str,
        child_responses: list[tuple[str, AgentResponse]],
        confidence: float,
    ) -> dict[str, object]:
        payloads = self._successful_payloads(child_responses)
        order = payloads.get("order_profile")
        graph = payloads.get("graph_relation")
        simulation = payloads.get("strategy_simulation")

        evidence = _build_evidence(order=order, graph=graph, simulation=simulation)
        has_strategy = any(label == "策略" for label, _ in child_responses)
        has_graph = any(label == "图谱" for label, _ in child_responses)
        outcome_key = self._select_outcome_key(
            intent=intent,
            order=order,
            graph=graph,
            has_strategy=has_strategy,
        )
        outcome = self.outcomes[outcome_key]
        evidence_strength = self.evidence_strength.classify(
            confidence=confidence,
            evidence_count=len(evidence),
        )
        rationale = "；".join(evidence) if evidence else "当前证据不足，建议补充上游画像和历史案例后再决策。"
        action_plan = self._action_plan_for(outcome)
        return {
            "decision": outcome.decision,
            "risk_level": outcome.risk_level,
            "recommended_action": outcome.recommended_action,
            "evidence_strength": evidence_strength,
            "confidence": confidence,
            "rationale": rationale,
            "escalation_reason": outcome.escalation_reason,
            "evidence": evidence,
            "policy_controls": self._policy_controls(outcome, has_strategy=has_strategy, has_graph=has_graph),
            "action_plan": action_plan.to_payload(),
        }

    @staticmethod
    def _successful_payloads(child_responses: list[tuple[str, AgentResponse]]) -> dict[str, Any]:
        return {
            trace.name: trace.payload
            for _, child in child_responses
            for trace in child.tool_traces
            if trace.status == "success"
        }

    def _select_outcome_key(
        self,
        *,
        intent: str,
        order: Any,
        graph: Any,
        has_strategy: bool,
    ) -> str:
        graph_level = _normalized_value(graph.get("risk_level", "")) if isinstance(graph, dict) else ""
        order_action = _normalized_value(order.get("recommended_action", "")) if isinstance(order, dict) else ""
        if graph_level in self.high_graph_levels or order_action in self.reject_order_actions:
            return "high_risk_review"
        if graph_level in self.medium_graph_levels or order_action in self.review_order_actions:
            return "medium_risk_review"
        if has_strategy:
            return "strategy_shadow_adjustment"
        if intent == "metric_anomaly":
            return "monitor"
        return "monitor"

    @staticmethod
    def _policy_controls(
        outcome: DecisionOutcome,
        *,
        has_strategy: bool,
        has_graph: bool,
    ) -> list[str]:
        controls = list(outcome.policy_controls)
        if has_strategy and "shadow_evaluation" not in controls:
            controls.append("shadow_evaluation")
        if has_graph and "graph_network_review" not in controls:
            controls.append("graph_network_review")
        if outcome.recommended_action == "manual_review" and "manual_review_queue" not in controls:
            controls.append("manual_review_queue")
        return controls

    def _action_plan_for(self, outcome: DecisionOutcome) -> DecisionActionPlan:
        return (
            self.action_plans.get(outcome.decision)
            or self.action_plans.get(outcome.recommended_action)
            or self.action_plans["monitor"]
        )


def _default_outcomes() -> dict[str, DecisionOutcome]:
    return {
        "high_risk_review": DecisionOutcome(
            decision="escalate_review",
            risk_level="high",
            recommended_action="manual_review",
            escalation_reason="存在高风险订单或高风险关系网络，需要人工复核后再执行强处置。",
            policy_controls=("manual_review_queue",),
        ),
        "medium_risk_review": DecisionOutcome(
            decision="manual_review",
            risk_level="medium",
            recommended_action="manual_review",
            escalation_reason="风险证据达到人工复核门槛，但暂不建议直接拒绝。",
            policy_controls=("manual_review_queue",),
        ),
        "strategy_shadow_adjustment": DecisionOutcome(
            decision="strategy_shadow_adjustment",
            risk_level="medium",
            recommended_action="shadow_evaluation",
            escalation_reason="策略调整需要先进入 shadow evaluation，避免误杀扩散。",
            policy_controls=("shadow_evaluation",),
        ),
        "monitor": DecisionOutcome(
            decision="monitor",
            risk_level="low",
            recommended_action="monitor",
        ),
    }


def _default_action_plans() -> dict[str, DecisionActionPlan]:
    return {
        "escalate_review": DecisionActionPlan(
            queue="manual_review_queue",
            priority="high",
            sla_hours=4,
            owner_role="risk_reviewer",
            next_actions=(
                "复核订单画像、图谱关系和历史案例证据",
                "确认是否执行拒绝、放行或补充验证",
            ),
        ),
        "manual_review": DecisionActionPlan(
            queue="manual_review_queue",
            priority="medium",
            sla_hours=12,
            owner_role="risk_reviewer",
            next_actions=(
                "复核核心风险证据和业务影响范围",
                "补充验证后确认放行、拦截或继续观察",
            ),
        ),
        "strategy_shadow_adjustment": DecisionActionPlan(
            queue="strategy_shadow_queue",
            priority="medium",
            sla_hours=24,
            owner_role="strategy_owner",
            next_actions=(
                "创建 shadow evaluation 实验并绑定推荐阈值",
                "监控通过率、误杀率和风险捕获率",
            ),
        ),
        "shadow_evaluation": DecisionActionPlan(
            queue="strategy_shadow_queue",
            priority="medium",
            sla_hours=24,
            owner_role="strategy_owner",
            next_actions=(
                "创建 shadow evaluation 实验并绑定推荐阈值",
                "监控通过率、误杀率和风险捕获率",
            ),
        ),
        "monitor": DecisionActionPlan(
            queue="risk_monitoring_queue",
            priority="low",
            sla_hours=72,
            owner_role="risk_ops",
            next_actions=(
                "持续监控核心指标和异常扩散",
                "证据增强或指标恶化时升级复核",
            ),
        ),
    }


def _build_evidence(*, order: Any, graph: Any, simulation: Any) -> list[str]:
    evidence: list[str] = []
    if isinstance(order, dict):
        evidence.append(
            "订单命中规则 "
            f"{', '.join(order.get('triggered_rules', [])) or '无'}，"
            f"建议动作 {order.get('recommended_action', 'unknown')}"
        )
    if isinstance(graph, dict):
        evidence.append(
            f"图谱风险 {graph.get('risk_level', 'unknown')}，"
            f"社区规模 {graph.get('community_size', 'unknown')}"
        )
    if isinstance(simulation, dict):
        evidence.append(
            "策略仿真建议阈值 "
            f"{simulation.get('recommended_threshold')}，"
            f"预计风险下降 {simulation.get('estimated_risk_reduction')}"
        )
    return evidence


def _normalized_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (_normalized_value(value),)
    return tuple(_normalized_value(item) for item in value)


def _normalized_value(value: Any) -> str:
    return str(value).strip().lower()
