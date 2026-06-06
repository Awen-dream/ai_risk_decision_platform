from __future__ import annotations

from uuid import uuid4
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app import build_app_container
from core.models import AgentRequest, AgentResponse
from services.observability import (
    REQUEST_ID_HEADER,
    TRACE_ID_HEADER,
    bind_context,
    emit_event,
)
from services.presentation import (
    build_session_turn_view,
    build_timeline_items,
)
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
    title: str
    status: str
    agent_group: str
    badge: str
    severity: str
    expanded_sections: List[str] = Field(default_factory=list)
    intent: Optional[str] = None
    plan_steps: List[str] = Field(default_factory=list)
    planner_trace: List[PlannerTracePayload] = Field(default_factory=list)
    confidence: float


class TimelineItemPayload(BaseModel):
    turn_index: int
    agent_name: str
    title: str
    status: str
    agent_group: str
    badge: str
    severity: str
    summary: str
    intent: Optional[str] = None
    plan_steps: List[str] = Field(default_factory=list)
    expanded_sections: List[str] = Field(default_factory=list)


class SessionResponse(BaseModel):
    session_id: str
    turns: List[SessionTurnPayload]
    timeline: List[TimelineItemPayload] = Field(default_factory=list)


class KnowledgeReloadResponse(BaseModel):
    documents_loaded: int
    source_count: int
    total_documents: int


class CapabilityContractPayload(BaseModel):
    name: str
    description: str
    knowledge_required: bool
    required_tools: List[str] = Field(default_factory=list)
    composed_agents: List[str] = Field(default_factory=list)


class QueryParamContractPayload(BaseModel):
    country_env_var: Optional[str] = None
    country_name: Optional[str] = None
    channel_env_var: Optional[str] = None
    channel_name: Optional[str] = None


class HttpEndpointContractPayload(BaseModel):
    tool_name: str
    path_env_var: str
    path: str
    supports_capabilities: List[str] = Field(default_factory=list)
    query_params: QueryParamContractPayload = Field(
        default_factory=QueryParamContractPayload
    )


class RuntimeInfoResponse(BaseModel):
    knowledge_backend: str
    tool_backend: str
    session_store_backend: str
    session_store_path: str
    knowledge_dir: str
    tool_http_base_url: str
    tool_http_timeout_sec: float
    tool_http_auth_mode: str
    tool_http_auth_header: str
    tool_http_metric_path: str
    tool_http_case_path: str
    tool_http_order_path_template: str
    tool_http_strategy_profile_path_template: str
    tool_http_strategy_simulation_path_template: str
    tool_http_graph_relation_path_template: str
    tool_http_country_param: str
    tool_http_channel_param: str
    registered_agents: List[str]
    registered_tools: List[str]
    supported_capabilities: List[str]
    capability_contract: List[CapabilityContractPayload]
    http_endpoint_contract: List[HttpEndpointContractPayload]
    indexed_documents: int


def create_app(config: Optional[AppConfig] = None) -> FastAPI:
    container = build_app_container(config)
    runtime = container.runtime
    fastapi_app = FastAPI(
        title="AI Risk Decision Platform API",
        version="0.1.0",
        description="Minimal agent-platform API for risk knowledge and investigation workflows.",
    )

    @fastapi_app.middleware("http")
    async def observability_middleware(request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        trace_id = request.headers.get(TRACE_ID_HEADER) or request_id
        with bind_context(
            request_id=request_id,
            trace_id=trace_id,
            http_method=request.method,
            http_path=request.url.path,
        ):
            emit_event("http_request_started")
            try:
                response = await call_next(request)
            except Exception as exc:
                emit_event(
                    "http_request_failed",
                    status_code=500,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                raise
            response.headers[REQUEST_ID_HEADER] = request_id
            response.headers[TRACE_ID_HEADER] = trace_id
            emit_event("http_request_completed", status_code=response.status_code)
            return response

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
            session_store_backend=container.config.session_store_backend,
            session_store_path=str(container.config.session_store_path),
            knowledge_dir=str(container.config.knowledge_dir),
            tool_http_base_url=container.config.tool_http_base_url,
            tool_http_timeout_sec=container.config.tool_http_timeout_sec,
            tool_http_auth_mode=container.config.tool_http_auth_mode,
            tool_http_auth_header=container.config.tool_http_auth_header,
            tool_http_metric_path=container.config.tool_http_metric_path,
            tool_http_case_path=container.config.tool_http_case_path,
            tool_http_order_path_template=container.config.tool_http_order_path_template,
            tool_http_strategy_profile_path_template=container.config.tool_http_strategy_profile_path_template,
            tool_http_strategy_simulation_path_template=container.config.tool_http_strategy_simulation_path_template,
            tool_http_graph_relation_path_template=container.config.tool_http_graph_relation_path_template,
            tool_http_country_param=container.config.tool_http_country_param,
            tool_http_channel_param=container.config.tool_http_channel_param,
            registered_agents=runtime.list_agents(),
            registered_tools=container.tools.list_tools(),
            supported_capabilities=container.config.supported_agent_capabilities(),
            capability_contract=[
                CapabilityContractPayload(**item)
                for item in container.config.capability_contract()
            ],
            http_endpoint_contract=[
                HttpEndpointContractPayload(**item)
                for item in container.config.http_endpoint_contract()
            ],
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
        emit_event(
            "agent_request_received",
            requested_agent=agent_name,
            has_session_id=bool(payload.session_id),
        )
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
            emit_event(
                "agent_request_failed",
                requested_agent=agent_name,
                error_type="KeyError",
                error=str(exc),
            )
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        emit_event(
            "agent_request_completed",
            requested_agent=agent_name,
            session_id=session_id,
        )
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
    turn_views = [build_session_turn_view(turn) for turn in session.turns]
    turns = [
        SessionTurnPayload(
            agent_name=turn.agent_name,
            query=turn.query,
            context=turn.context,
            summary=turn.summary,
            title=turn.title,
            status=turn.status,
            agent_group=turn.agent_group,
            badge=turn.badge,
            severity=turn.severity,
            expanded_sections=turn.expanded_sections,
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
        for turn in turn_views
    ]
    timeline_views = build_timeline_items(turn_views)
    return SessionResponse(
        session_id=session.session_id,
        turns=turns,
        timeline=[
            TimelineItemPayload(
                turn_index=turn.turn_index,
                agent_name=turn.agent_name,
                title=turn.title,
                status=turn.status,
                agent_group=turn.agent_group,
                badge=turn.badge,
                severity=turn.severity,
                summary=turn.summary,
                intent=turn.intent,
                plan_steps=turn.plan_steps,
                expanded_sections=turn.expanded_sections,
            )
            for turn in timeline_views
        ],
    )


fastapi_app = create_app()
