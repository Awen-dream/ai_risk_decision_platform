from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app import build_demo_runtime
from core.models import AgentRequest, AgentResponse


class AgentInvokeRequest(BaseModel):
    query: str = Field(..., min_length=1, description="User query for the agent")
    session_id: Optional[str] = Field(
        default=None,
        description="Optional existing session ID for multi-turn interaction",
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional structured context such as country, channel, order_id",
    )
    user_role: str = Field(default="risk_analyst")


class CitationPayload(BaseModel):
    doc_id: str
    title: str
    source_type: str
    snippet: str


class ToolTracePayload(BaseModel):
    name: str
    status: str
    summary: str


class AgentInvokeResponse(BaseModel):
    session_id: str
    agent_name: str
    summary: str
    findings: List[str]
    suggested_actions: List[str]
    citations: List[CitationPayload]
    tool_traces: List[ToolTracePayload]
    confidence: float


class SessionTurnPayload(BaseModel):
    agent_name: str
    query: str
    context: Dict[str, Any]
    summary: str
    confidence: float


class SessionResponse(BaseModel):
    session_id: str
    turns: List[SessionTurnPayload]


def create_app() -> FastAPI:
    runtime = build_demo_runtime()
    fastapi_app = FastAPI(
        title="AI Risk Decision Platform API",
        version="0.1.0",
        description="Minimal agent-platform API for risk knowledge and investigation workflows.",
    )

    @fastapi_app.get("/healthz")
    def healthz() -> Dict[str, str]:
        return {"status": "ok"}

    @fastapi_app.get("/agents")
    def list_agents() -> Dict[str, List[str]]:
        return {"agents": runtime.list_agents()}

    @fastapi_app.post("/sessions", response_model=SessionResponse)
    def create_session() -> SessionResponse:
        session_id = runtime.create_session()
        session = runtime.get_session(session_id)
        return _to_session_response(session)

    @fastapi_app.get("/sessions/{session_id}", response_model=SessionResponse)
    def get_session(session_id: str) -> SessionResponse:
        session = runtime.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return _to_session_response(session)

    @fastapi_app.post("/agents/{agent_name}", response_model=AgentInvokeResponse)
    def invoke_agent(agent_name: str, payload: AgentInvokeRequest) -> AgentInvokeResponse:
        try:
            session_id, response = runtime.execute(
                agent_name,
                AgentRequest(
                    query=payload.query,
                    context=payload.context,
                    user_role=payload.user_role,
                ),
                session_id=payload.session_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _to_response_model(session_id, response)

    return fastapi_app


def _to_response_model(session_id: str, response: AgentResponse) -> AgentInvokeResponse:
    return AgentInvokeResponse(
        session_id=session_id,
        agent_name=response.agent_name,
        summary=response.summary,
        findings=response.findings,
        suggested_actions=response.suggested_actions,
        citations=[
            CitationPayload(
                doc_id=citation.doc_id,
                title=citation.title,
                source_type=citation.source_type,
                snippet=citation.snippet,
            )
            for citation in response.citations
        ],
        tool_traces=[
            ToolTracePayload(
                name=trace.name,
                status=trace.status,
                summary=trace.summary,
            )
            for trace in response.tool_traces
        ],
        confidence=response.confidence,
    )


def _to_session_response(session) -> SessionResponse:
    return SessionResponse(
        session_id=session.session_id,
        turns=[
            SessionTurnPayload(
                agent_name=turn.agent_name,
                query=turn.query,
                context=turn.context,
                summary=turn.summary,
                confidence=turn.confidence,
            )
            for turn in session.turns
        ],
    )


fastapi_app = create_app()
