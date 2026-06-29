from __future__ import annotations

from core.models import SessionRecord


def build_session_memory_context(
    session: SessionRecord,
    *,
    max_turns: int = 3,
) -> dict[str, object]:
    turns = session.turns[-max_turns:]
    return {
        "scope": "short_term_session",
        "turn_count": len(turns),
        "turns": [
            {
                "turn_index": len(session.turns) - len(turns) + index + 1,
                "agent_name": turn.agent_name,
                "intent": turn.intent,
                "summary": turn.summary,
                "confidence": turn.confidence,
                "plan_steps": list(turn.plan_steps),
                "evidence_sources": [evidence.source for evidence in turn.evidence],
                "open_evidence_gap_sources": [gap.source for gap in turn.evidence_gap],
            }
            for index, turn in enumerate(turns)
        ],
    }


def public_context_keys(context: dict[str, object]) -> list[str]:
    return sorted(key for key in context if not key.startswith("_"))
