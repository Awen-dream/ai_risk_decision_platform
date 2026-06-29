from __future__ import annotations

import re
from typing import Any

from core.models import SessionRecord


TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+")


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


def tokenize_memory_text(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in TOKEN_PATTERN.findall(text):
        lowered = token.lower()
        tokens.add(lowered)
        if len(token) >= 4 and any("\u4e00" <= char <= "\u9fff" for char in token):
            for index in range(len(token) - 1):
                tokens.add(token[index : index + 2].lower())
    return tokens


def memory_query_text(query: str, context: dict[str, Any]) -> str:
    public_items = {
        key: value
        for key, value in context.items()
        if not key.startswith("_") and value is not None
    }
    context_text = " ".join(f"{key}:{value}" for key, value in sorted(public_items.items()))
    return f"{query} {context_text}".strip()
