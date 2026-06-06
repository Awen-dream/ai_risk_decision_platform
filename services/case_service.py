from __future__ import annotations

from uuid import uuid4

from core.models import (
    SessionRecord,
    StrategyRecommendationRecord,
    WorkflowCase,
    WorkflowCaseHistoryEntry,
)
from services.presentation import build_severity, build_turn_title


ALLOWED_CASE_STATUSES = {"open", "in_review", "strategy_pending", "closed"}


class InMemoryCaseService:
    """Stores workflow cases in memory for lightweight review and follow-up."""

    def __init__(self) -> None:
        self._cases: dict[str, WorkflowCase] = {}

    def create_case_from_session(
        self,
        session: SessionRecord,
        turn_index: int | None = None,
    ) -> WorkflowCase:
        if not session.turns:
            raise ValueError("Session has no turns")
        resolved_turn_index = turn_index or len(session.turns)
        if resolved_turn_index < 1 or resolved_turn_index > len(session.turns):
            raise IndexError("Turn index out of range")
        turn = session.turns[resolved_turn_index - 1]
        recommendation = _extract_strategy_recommendation(turn.artifacts)
        status = _initial_status(turn.agent_name, turn.intent, recommendation)
        case = WorkflowCase(
            case_id=f"CASE-{uuid4().hex[:8].upper()}",
            session_id=session.session_id,
            turn_index=resolved_turn_index,
            title=build_turn_title(turn.agent_name),
            summary=turn.summary,
            status=status,
            severity=build_severity(turn.agent_name, turn.intent),
            source_agent=turn.agent_name,
            intent=turn.intent,
            context=dict(turn.context),
            suggested_actions=list(turn.suggested_actions),
            strategy_recommendation=recommendation,
            history=[
                WorkflowCaseHistoryEntry(
                    event_type="case_created",
                    status=status,
                    summary=f"基于 session {session.session_id} 的第 {resolved_turn_index} 个 turn 创建 case。",
                )
            ],
        )
        self._cases[case.case_id] = case
        return case

    def get_case(self, case_id: str) -> WorkflowCase | None:
        return self._cases.get(case_id)

    def list_cases(self) -> list[WorkflowCase]:
        return list(self._cases.values())

    def update_case_status(
        self,
        case_id: str,
        status: str,
        note: str | None = None,
    ) -> WorkflowCase | None:
        if status not in ALLOWED_CASE_STATUSES:
            raise ValueError(f"Unsupported case status: {status}")
        case = self._cases.get(case_id)
        if case is None:
            return None
        case.status = status
        case.history.append(
            WorkflowCaseHistoryEntry(
                event_type="status_updated",
                status=status,
                summary=note or f"Case 状态更新为 {status}。",
            )
        )
        return case


def _extract_strategy_recommendation(
    artifacts: dict[str, object],
) -> StrategyRecommendationRecord | None:
    payload = artifacts.get("strategy_recommendation")
    if not isinstance(payload, dict):
        return None
    return StrategyRecommendationRecord(
        strategy_id=str(payload["strategy_id"]),
        current_threshold=float(payload["current_threshold"]),
        recommended_threshold=float(payload["recommended_threshold"]),
        validation_window=str(payload["validation_window"]),
        rationale=str(payload["rationale"]),
    )


def _initial_status(
    agent_name: str,
    intent: str | None,
    recommendation: StrategyRecommendationRecord | None,
) -> str:
    if recommendation is not None:
        return "strategy_pending"
    if agent_name == "copilot" or intent in {"fraud_ring", "order_case", "composite"}:
        return "in_review"
    return "open"
