from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app import build_app_container
from core.models import AgentRequest, AgentResponse
from settings import AppConfig


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


class PlannerTracePayload(BaseModel):
    step: str
    selected: bool
    reason: str


class AgentInvokeResponse(BaseModel):
    session_id: str
    agent_name: str
    summary: str
    intent: Optional[str] = None
    plan_steps: List[str] = Field(default_factory=list)
    planner_trace: List[PlannerTracePayload] = Field(default_factory=list)
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
    intent: Optional[str] = None
    plan_steps: List[str] = Field(default_factory=list)
    planner_trace: List[PlannerTracePayload] = Field(default_factory=list)
    confidence: float


class SessionResponse(BaseModel):
    session_id: str
    turns: List[SessionTurnPayload]


class KnowledgeReloadResponse(BaseModel):
    documents_loaded: int
    source_count: int
    total_documents: int


class RuntimeInfoResponse(BaseModel):
    knowledge_backend: str
    tool_backend: str
    knowledge_dir: str
    tool_http_base_url: str
    tool_http_auth_mode: str
    tool_http_metric_path: str
    tool_http_case_path: str
    tool_http_order_path_template: str
    tool_http_strategy_profile_path_template: str
    tool_http_strategy_simulation_path_template: str
    tool_http_graph_relation_path_template: str
    registered_agents: List[str]
    registered_tools: List[str]
    indexed_documents: int


def create_app(config: Optional[AppConfig] = None) -> FastAPI:
    container = build_app_container(config)
    runtime = container.runtime
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

    @fastapi_app.get("/admin/runtime", response_model=RuntimeInfoResponse)
    def runtime_info() -> RuntimeInfoResponse:
        return RuntimeInfoResponse(
            knowledge_backend=container.config.knowledge_backend,
            tool_backend=container.config.tool_backend,
            knowledge_dir=str(container.config.knowledge_dir),
            tool_http_base_url=container.config.tool_http_base_url,
            tool_http_auth_mode=container.config.tool_http_auth_mode,
            tool_http_metric_path=container.config.tool_http_metric_path,
            tool_http_case_path=container.config.tool_http_case_path,
            tool_http_order_path_template=container.config.tool_http_order_path_template,
            tool_http_strategy_profile_path_template=container.config.tool_http_strategy_profile_path_template,
            tool_http_strategy_simulation_path_template=container.config.tool_http_strategy_simulation_path_template,
            tool_http_graph_relation_path_template=container.config.tool_http_graph_relation_path_template,
            registered_agents=runtime.list_agents(),
            registered_tools=container.tools.list_tools(),
            indexed_documents=container.retrieval.document_count(),
        )

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

    @fastapi_app.post("/admin/knowledge/reload", response_model=KnowledgeReloadResponse)
    def reload_knowledge() -> KnowledgeReloadResponse:
        result = container.knowledge_sync_service.reload()
        return KnowledgeReloadResponse(
            documents_loaded=result.documents_loaded,
            source_count=result.source_count,
            total_documents=container.retrieval.document_count(),
        )

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
        intent=response.intent,
        plan_steps=response.plan_steps,
        planner_trace=[
            PlannerTracePayload(
                step=trace.step,
                selected=trace.selected,
                reason=trace.reason,
            )
            for trace in response.planner_trace
        ],
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
                intent=turn.intent,
                plan_steps=turn.plan_steps,
                planner_trace=[
                    PlannerTracePayload(
                        step=trace.step,
                        selected=trace.selected,
                        reason=trace.reason,
                    )
                    for trace in turn.planner_trace
                ],
                confidence=turn.confidence,
            )
            for turn in session.turns
        ],
    )


fastapi_app = create_app()
