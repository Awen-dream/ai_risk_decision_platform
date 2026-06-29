from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.memory import memory_query_text, tokenize_memory_text
from core.models import AgentRequest, WorkflowCase
from services.case_service import CaseService


class LongTermMemoryProvider(Protocol):
    def retrieve(self, request: AgentRequest, *, limit: int = 3) -> list[dict[str, object]]:
        """Return auditable long-term memory references for a request."""


@dataclass(frozen=True)
class CaseMemoryProvider:
    case_service: CaseService
    candidate_limit: int = 50

    def retrieve(self, request: AgentRequest, *, limit: int = 3) -> list[dict[str, object]]:
        query_terms = tokenize_memory_text(memory_query_text(request.query, request.context))
        if not query_terms:
            return []
        cases = self.case_service.list_cases(limit=self.candidate_limit)
        scored = [
            (self._score_case(case, query_terms), case)
            for case in cases
        ]
        scored = [(score, case) for score, case in scored if score > 0]
        scored.sort(key=lambda item: (-item[0], item[1].updated_at, item[1].case_id))
        return [
            self._case_ref(case, score)
            for score, case in scored[:limit]
        ]

    @staticmethod
    def _score_case(case: WorkflowCase, query_terms: set[str]) -> int:
        haystack = " ".join(
            str(value)
            for value in (
                case.case_id,
                case.title,
                case.summary,
                case.status,
                case.severity,
                case.source_agent,
                case.intent,
                case.risk_decision.risk_level if case.risk_decision else "",
                case.risk_decision.recommended_action if case.risk_decision else "",
            )
        )
        case_terms = tokenize_memory_text(haystack)
        score = 0
        for term in query_terms:
            if term in case_terms:
                score += 3
                continue
            if any(term in candidate or candidate in term for candidate in case_terms):
                score += 1
        return score

    @staticmethod
    def _case_ref(case: WorkflowCase, score: int) -> dict[str, object]:
        return {
            "memory_type": "workflow_case",
            "case_id": case.case_id,
            "title": case.title,
            "summary": case.summary,
            "status": case.status,
            "severity": case.severity,
            "source_agent": case.source_agent,
            "intent": case.intent,
            "risk_level": case.risk_decision.risk_level if case.risk_decision else None,
            "recommended_action": (
                case.risk_decision.recommended_action if case.risk_decision else None
            ),
            "score": score,
            "updated_at": case.updated_at,
        }
