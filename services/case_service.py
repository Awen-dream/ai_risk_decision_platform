from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from core.models import (
    SessionRecord,
    StrategyRecommendationRecord,
    WorkflowCase,
    WorkflowCaseHistoryEntry,
)
from services.presentation import build_severity, build_turn_title


ALLOWED_CASE_STATUSES = {"open", "in_review", "strategy_pending", "closed"}


class CaseService(ABC):
    @abstractmethod
    def create_case_from_session(
        self,
        session: SessionRecord,
        turn_index: int | None = None,
    ) -> WorkflowCase:
        """Create a workflow case from one session turn."""

    @abstractmethod
    def get_case(self, case_id: str) -> WorkflowCase | None:
        """Return one case by id if present."""

    @abstractmethod
    def list_cases(
        self,
        *,
        status: str | None = None,
        source_agent: str | None = None,
        intent: str | None = None,
        session_id: str | None = None,
        severity: str | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[WorkflowCase]:
        """List cases with optional filters."""

    @abstractmethod
    def update_case_status(
        self,
        case_id: str,
        status: str,
        note: str | None = None,
    ) -> WorkflowCase | None:
        """Update case status and append history."""


class InMemoryCaseService(CaseService):
    """Stores workflow cases in memory for lightweight review and follow-up."""

    def __init__(self) -> None:
        self._cases: dict[str, WorkflowCase] = {}

    def create_case_from_session(
        self,
        session: SessionRecord,
        turn_index: int | None = None,
    ) -> WorkflowCase:
        case = _build_case_from_session(session, turn_index=turn_index)
        self._cases[case.case_id] = case
        return case

    def get_case(self, case_id: str) -> WorkflowCase | None:
        return self._cases.get(case_id)

    def list_cases(
        self,
        *,
        status: str | None = None,
        source_agent: str | None = None,
        intent: str | None = None,
        session_id: str | None = None,
        severity: str | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[WorkflowCase]:
        return _filter_cases(
            self._cases.values(),
            status=status,
            source_agent=source_agent,
            intent=intent,
            session_id=session_id,
            severity=severity,
            updated_after=updated_after,
            updated_before=updated_before,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

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
        _append_case_status_update(case, status, note)
        return case


class FileCaseService(CaseService):
    """Stores workflow cases in a local JSON file for lightweight persistence."""

    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

    def create_case_from_session(
        self,
        session: SessionRecord,
        turn_index: int | None = None,
    ) -> WorkflowCase:
        cases = self._load_cases()
        case = _build_case_from_session(session, turn_index=turn_index)
        cases[case.case_id] = case
        self._save_cases(cases)
        return case

    def get_case(self, case_id: str) -> WorkflowCase | None:
        return self._load_cases().get(case_id)

    def list_cases(
        self,
        *,
        status: str | None = None,
        source_agent: str | None = None,
        intent: str | None = None,
        session_id: str | None = None,
        severity: str | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[WorkflowCase]:
        return _filter_cases(
            self._load_cases().values(),
            status=status,
            source_agent=source_agent,
            intent=intent,
            session_id=session_id,
            severity=severity,
            updated_after=updated_after,
            updated_before=updated_before,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    def update_case_status(
        self,
        case_id: str,
        status: str,
        note: str | None = None,
    ) -> WorkflowCase | None:
        if status not in ALLOWED_CASE_STATUSES:
            raise ValueError(f"Unsupported case status: {status}")
        cases = self._load_cases()
        case = cases.get(case_id)
        if case is None:
            return None
        _append_case_status_update(case, status, note)
        self._save_cases(cases)
        return case

    def _load_cases(self) -> dict[str, WorkflowCase]:
        if not self._file_path.exists():
            return {}
        payload = json.loads(self._file_path.read_text(encoding="utf-8"))
        cases: dict[str, WorkflowCase] = {}
        for item in payload.get("cases", []):
            case = _deserialize_case(item)
            cases[case.case_id] = case
        return cases

    def _save_cases(self, cases: dict[str, WorkflowCase]) -> None:
        payload = {
            "cases": [_serialize_case(case) for case in cases.values()],
        }
        self._file_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _build_case_from_session(
    session: SessionRecord,
    *,
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
    timestamp = _current_timestamp()
    return WorkflowCase(
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
        created_at=timestamp,
        updated_at=timestamp,
    )


def _filter_cases(
    cases,
    *,
    status: str | None = None,
    source_agent: str | None = None,
    intent: str | None = None,
    session_id: str | None = None,
    severity: str | None = None,
    updated_after: str | None = None,
    updated_before: str | None = None,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
    limit: int | None = None,
    offset: int = 0,
) -> list[WorkflowCase]:
    filtered = list(cases)
    if status is not None:
        filtered = [case for case in filtered if case.status == status]
    if source_agent is not None:
        filtered = [case for case in filtered if case.source_agent == source_agent]
    if intent is not None:
        filtered = [case for case in filtered if case.intent == intent]
    if session_id is not None:
        filtered = [case for case in filtered if case.session_id == session_id]
    if severity is not None:
        filtered = [case for case in filtered if case.severity == severity]
    if updated_after is not None:
        updated_after_dt = _parse_timestamp(updated_after)
        filtered = [
            case
            for case in filtered
            if case.updated_at and _parse_timestamp(case.updated_at) >= updated_after_dt
        ]
    if updated_before is not None:
        updated_before_dt = _parse_timestamp(updated_before)
        filtered = [
            case
            for case in filtered
            if case.updated_at and _parse_timestamp(case.updated_at) <= updated_before_dt
        ]
    filtered.sort(
        key=lambda case: _case_sort_key(case, sort_by),
        reverse=sort_order.lower() != "asc",
    )
    if offset:
        filtered = filtered[offset:]
    if limit is not None:
        filtered = filtered[:limit]
    return filtered


def _append_case_status_update(
    case: WorkflowCase,
    status: str,
    note: str | None,
) -> None:
    case.status = status
    case.updated_at = _current_timestamp()
    case.history.append(
        WorkflowCaseHistoryEntry(
            event_type="status_updated",
            status=status,
            summary=note or f"Case 状态更新为 {status}。",
        )
    )


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


def _serialize_case(case: WorkflowCase) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "session_id": case.session_id,
        "turn_index": case.turn_index,
        "title": case.title,
        "summary": case.summary,
        "status": case.status,
        "severity": case.severity,
        "source_agent": case.source_agent,
        "intent": case.intent,
        "context": case.context,
        "suggested_actions": case.suggested_actions,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "strategy_recommendation": (
            {
                "strategy_id": case.strategy_recommendation.strategy_id,
                "current_threshold": case.strategy_recommendation.current_threshold,
                "recommended_threshold": case.strategy_recommendation.recommended_threshold,
                "validation_window": case.strategy_recommendation.validation_window,
                "rationale": case.strategy_recommendation.rationale,
            }
            if case.strategy_recommendation is not None
            else None
        ),
        "history": [
            {
                "event_type": item.event_type,
                "status": item.status,
                "summary": item.summary,
            }
            for item in case.history
        ],
    }


def _deserialize_case(payload: dict[str, object]) -> WorkflowCase:
    item = dict(payload)
    recommendation_payload = item.get("strategy_recommendation")
    if isinstance(recommendation_payload, dict):
        recommendation = StrategyRecommendationRecord(
            strategy_id=str(recommendation_payload["strategy_id"]),
            current_threshold=float(recommendation_payload["current_threshold"]),
            recommended_threshold=float(recommendation_payload["recommended_threshold"]),
            validation_window=str(recommendation_payload["validation_window"]),
            rationale=str(recommendation_payload["rationale"]),
        )
    else:
        recommendation = None
    history = [
        WorkflowCaseHistoryEntry(
            event_type=str(entry["event_type"]),
            status=str(entry["status"]),
            summary=str(entry["summary"]),
        )
        for entry in item.get("history", [])
    ]
    return WorkflowCase(
        case_id=str(item["case_id"]),
        session_id=str(item["session_id"]),
        turn_index=int(item["turn_index"]),
        title=str(item["title"]),
        summary=str(item["summary"]),
        status=str(item["status"]),
        severity=str(item["severity"]),
        source_agent=str(item["source_agent"]),
        intent=str(item["intent"]) if item.get("intent") is not None else None,
        context=dict(item.get("context", {})),
        suggested_actions=list(item.get("suggested_actions", [])),
        strategy_recommendation=recommendation,
        history=history,
        created_at=str(item.get("created_at", "")),
        updated_at=str(item.get("updated_at", "")),
    )


def _case_sort_key(case: WorkflowCase, sort_by: str) -> str:
    if sort_by == "created_at":
        return case.created_at
    if sort_by == "status":
        return case.status
    if sort_by == "severity":
        return case.severity
    return case.updated_at


def _current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
    )


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
