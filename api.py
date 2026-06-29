from __future__ import annotations

import time
from secrets import compare_digest
from uuid import uuid4
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app import build_app_container
from core.models import (
    AgentRequest,
    AgentResponse,
    EvidenceGap,
    EvidenceRecord,
    RiskActionPlanRecord,
    RiskDecisionRecord,
    StrategyRecommendationRecord,
    WorkflowCase,
    WorkflowCaseHistoryEntry,
)
from persistence.postgres import PostgresDatabase
from persistence.sqlite import SQLiteDatabase
from services.case_service import ALLOWED_CASE_STATUSES, is_risk_action_plan_overdue
from services.observability import (
    REQUEST_ID_HEADER,
    TRACE_ID_HEADER,
    bind_context,
    emit_event,
    get_gauges_snapshot,
    get_histograms_snapshot,
    get_metrics_snapshot,
    render_prometheus,
    set_gauge,
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


class EvidencePayload(BaseModel):
    source: str
    source_type: str
    summary: str
    payload: Any
    confidence: float
    observed_at: Optional[str] = None


class PlannerTracePayload(BaseModel):
    step: str
    selected: bool
    reason: str


class ToolSelectionReasonPayload(BaseModel):
    tool: str
    selected: bool
    reason: str


class EvidenceGapPayload(BaseModel):
    gap: str
    source: str
    severity: str = "medium"
    next_action: str = ""
    blocking: bool = False


class AgentInvokeResponse(BaseModel):
    session_id: str
    agent_name: str
    summary: str
    intent: Optional[str] = None
    thought_summary: str = ""
    plan_steps: List[str] = Field(default_factory=list)
    planner_trace: List[PlannerTracePayload] = Field(default_factory=list)
    tool_selection_reason: List[ToolSelectionReasonPayload] = Field(default_factory=list)
    evidence_gap: List[EvidenceGapPayload] = Field(default_factory=list)
    findings: List[str]
    suggested_actions: List[str]
    citations: List[CitationPayload]
    tool_traces: List[ToolTracePayload]
    evidence: List[EvidencePayload] = Field(default_factory=list)
    confidence: float
    artifacts: Dict[str, Any] = Field(default_factory=dict)


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
    thought_summary: str = ""
    plan_steps: List[str] = Field(default_factory=list)
    planner_trace: List[PlannerTracePayload] = Field(default_factory=list)
    tool_selection_reason: List[ToolSelectionReasonPayload] = Field(default_factory=list)
    evidence_gap: List[EvidenceGapPayload] = Field(default_factory=list)
    confidence: float
    evidence: List[EvidencePayload] = Field(default_factory=list)
    artifacts: Dict[str, Any] = Field(default_factory=dict)


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
    planner_backend: str
    planner_source: str
    investigation_backend: str
    investigation_source: str
    strategy_backend: str
    strategy_source: str
    graph_backend: str
    graph_source: str
    planner_openai_base_url: str
    planner_openai_model: str
    planner_openai_timeout_sec: float
    planner_openai_reasoning_effort: str
    planner_openai_max_output_tokens: int
    planner_openai_api_key_source: str
    investigation_openai_base_url: str
    investigation_openai_model: str
    investigation_openai_timeout_sec: float
    investigation_openai_reasoning_effort: str
    investigation_openai_max_output_tokens: int
    investigation_openai_api_key_source: str
    strategy_openai_base_url: str
    strategy_openai_model: str
    strategy_openai_timeout_sec: float
    strategy_openai_reasoning_effort: str
    strategy_openai_max_output_tokens: int
    strategy_openai_api_key_source: str
    graph_openai_base_url: str
    graph_openai_model: str
    graph_openai_timeout_sec: float
    graph_openai_reasoning_effort: str
    graph_openai_max_output_tokens: int
    graph_openai_api_key_source: str
    session_store_backend: str
    session_store_path: str
    case_store_backend: str
    case_store_path: str
    database_path: str
    postgres_dsn_configured: bool
    postgres_dsn_source: str
    knowledge_dir: str
    tool_http_base_url: str
    tool_http_timeout_sec: float
    tool_http_retry_attempts: int
    tool_http_retry_backoff_sec: float
    tool_http_circuit_breaker_failure_threshold: int
    tool_http_circuit_breaker_reset_sec: float
    tool_http_auth_mode: str
    tool_http_auth_header: str
    tool_http_auth_token_source: str
    tool_http_audit_enabled: bool
    tool_http_audit_path: str
    tool_http_audit_max_bytes: int
    tool_http_audit_max_files: int
    tool_http_audit_integrity_enabled: bool
    audit_central_enabled: bool
    audit_central_url_configured: bool
    audit_central_timeout_sec: float
    audit_central_auth_header: str
    audit_central_auth_token_source: str
    risk_decision_policy_source: str
    risk_decision_policy_path: Optional[str] = None
    admin_auth_enabled: bool
    admin_auth_header: str
    admin_auth_token_source: str
    admin_auth_configured: bool
    tool_http_metric_path: str
    tool_http_case_path: str
    tool_http_order_path_template: str
    tool_http_strategy_profile_path_template: str
    tool_http_strategy_simulation_path_template: str
    tool_http_graph_relation_path_template: str
    tool_http_sql_query_path_template: str
    tool_http_dashboard_snapshot_path_template: str
    tool_http_rule_explain_path: str
    tool_http_country_param: str
    tool_http_channel_param: str
    registered_agents: List[str]
    registered_tools: List[str]
    supported_capabilities: List[str]
    capability_contract: List[CapabilityContractPayload]
    http_endpoint_contract: List[HttpEndpointContractPayload]
    observability: Dict[str, Any]
    readiness: Dict[str, Any]
    indexed_documents: int


class RuntimeMetricsResponse(BaseModel):
    counters: Dict[str, int] = Field(default_factory=dict)
    gauges: Dict[str, float] = Field(default_factory=dict)
    histograms: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class SqlQueryToolRequest(BaseModel):
    query_name: str = Field(..., min_length=1)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=50, ge=1, le=500)


class DashboardSnapshotToolRequest(BaseModel):
    dashboard_id: str = Field(default="risk_overview", min_length=1)
    country: str = Field(..., min_length=2)
    channel: str = Field(..., min_length=2)
    time_range: str = Field(default="recent_24h", min_length=1)


class RuleExplainToolRequest(BaseModel):
    rule_id: Optional[str] = None
    order_id: Optional[str] = None
    strategy_id: Optional[str] = None


class ToolExecutionResponse(BaseModel):
    tool_name: str
    status: str
    summary: str
    payload: Any


class UpstreamAuditEventPayload(BaseModel):
    event_id: str
    occurred_at: str
    event_type: str
    upstream_client: str
    method: str
    target_url: str
    outcome: str
    status_code: Optional[int] = None
    attempt: Optional[int] = None
    total_attempts: Optional[int] = None
    duration_ms: Optional[float] = None
    error_type: Optional[str] = None
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    agent_name: Optional[str] = None
    request_header_names: List[str] = Field(default_factory=list)
    audit_previous_hash: Optional[str] = None
    audit_hash: Optional[str] = None


class AuditIntegrityResponse(BaseModel):
    status: str
    integrity_enabled: bool
    total_records: int
    verified_records: int
    legacy_records: int
    invalid_records: int
    broken_links: int
    first_event_hash: Optional[str] = None
    last_event_hash: Optional[str] = None


class StrategyRecommendationPayload(BaseModel):
    strategy_id: str
    current_threshold: float
    recommended_threshold: float
    validation_window: str
    rationale: str


class RiskActionPlanPayload(BaseModel):
    queue: str
    priority: str
    sla_hours: int
    owner_role: str
    next_actions: List[str] = Field(default_factory=list)
    status: str = "queued"
    due_at: Optional[str] = None
    assigned_to: Optional[str] = None
    completed_at: Optional[str] = None
    outcome: Optional[str] = None
    is_overdue: bool = False


class RiskDecisionPayload(BaseModel):
    decision: str
    risk_level: str
    recommended_action: str
    evidence_strength: str
    confidence: float
    rationale: str
    escalation_reason: Optional[str] = None
    evidence: List[str] = Field(default_factory=list)
    policy_controls: List[str] = Field(default_factory=list)
    action_plan: Optional[RiskActionPlanPayload] = None


class CaseHistoryPayload(BaseModel):
    event_type: str
    status: str
    summary: str


class WorkflowCasePayload(BaseModel):
    case_id: str
    session_id: str
    turn_index: int
    title: str
    summary: str
    status: str
    severity: str
    source_agent: str
    intent: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    suggested_actions: List[str] = Field(default_factory=list)
    strategy_recommendation: Optional[StrategyRecommendationPayload] = None
    risk_decision: Optional[RiskDecisionPayload] = None
    history: List[CaseHistoryPayload] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ActionQueueSummaryPayload(BaseModel):
    queue: str
    total_cases: int
    overdue_cases: int
    high_priority_cases: int
    statuses: Dict[str, int] = Field(default_factory=dict)
    priorities: Dict[str, int] = Field(default_factory=dict)
    assignees: List[str] = Field(default_factory=list)
    oldest_due_at: Optional[str] = None
    next_due_at: Optional[str] = None
    highest_priority: Optional[str] = None


class ActionQueueAssignRequest(BaseModel):
    assigned_to: str = Field(..., min_length=1)
    case_ids: List[str] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=100)
    action_status: Optional[str] = None
    action_overdue: Optional[bool] = None
    note: Optional[str] = None


class ActionQueueAssignResponse(BaseModel):
    queue: str
    assigned_to: str
    updated_count: int
    cases: List[WorkflowCasePayload] = Field(default_factory=list)


class CaseStatusUpdateRequest(BaseModel):
    status: str = Field(..., min_length=1)
    note: Optional[str] = None
    assigned_to: Optional[str] = None
    action_outcome: Optional[str] = None


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
        started_at = time.perf_counter()
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        trace_id = request.headers.get(TRACE_ID_HEADER) or request_id
        with bind_context(
            request_id=request_id,
            trace_id=trace_id,
            http_method=request.method,
            http_path=request.url.path,
        ):
            emit_event("http_request_started")
            if _requires_admin_auth(request.url.path) and not _is_admin_authorized(
                request,
                container.config,
            ):
                emit_event(
                    "admin_request_unauthorized",
                    admin_path=request.url.path,
                    admin_auth_enabled=container.config.admin_auth_enabled,
                    admin_auth_configured=bool(container.config.admin_auth_token),
                )
                response = JSONResponse(
                    status_code=401,
                    content={"detail": "Admin authentication required"},
                )
                response.headers[REQUEST_ID_HEADER] = request_id
                response.headers[TRACE_ID_HEADER] = trace_id
                emit_event(
                    "http_request_completed",
                    status_code=401,
                    duration_seconds=time.perf_counter() - started_at,
                )
                return response
            try:
                response = await call_next(request)
            except Exception as exc:
                emit_event(
                    "http_request_failed",
                    status_code=500,
                    error_type=type(exc).__name__,
                    error=str(exc),
                    duration_seconds=time.perf_counter() - started_at,
                )
                raise
            response.headers[REQUEST_ID_HEADER] = request_id
            response.headers[TRACE_ID_HEADER] = trace_id
            emit_event(
                "http_request_completed",
                status_code=response.status_code,
                duration_seconds=time.perf_counter() - started_at,
            )
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
            planner_backend=container.config.planner_backend,
            planner_source=container.config.planner_source(),
            investigation_backend=container.config.investigation_backend,
            investigation_source=container.config.investigation_source(),
            strategy_backend=container.config.strategy_backend,
            strategy_source=container.config.strategy_source(),
            graph_backend=container.config.graph_backend,
            graph_source=container.config.graph_source(),
            planner_openai_base_url=container.config.planner_openai_base_url,
            planner_openai_model=container.config.planner_openai_model,
            planner_openai_timeout_sec=container.config.planner_openai_timeout_sec,
            planner_openai_reasoning_effort=container.config.planner_openai_reasoning_effort,
            planner_openai_max_output_tokens=container.config.planner_openai_max_output_tokens,
            planner_openai_api_key_source=container.config.planner_openai_api_key_source(),
            investigation_openai_base_url=container.config.investigation_openai_base_url,
            investigation_openai_model=container.config.investigation_openai_model,
            investigation_openai_timeout_sec=container.config.investigation_openai_timeout_sec,
            investigation_openai_reasoning_effort=container.config.investigation_openai_reasoning_effort,
            investigation_openai_max_output_tokens=container.config.investigation_openai_max_output_tokens,
            investigation_openai_api_key_source=container.config.investigation_openai_api_key_source(),
            strategy_openai_base_url=container.config.strategy_openai_base_url,
            strategy_openai_model=container.config.strategy_openai_model,
            strategy_openai_timeout_sec=container.config.strategy_openai_timeout_sec,
            strategy_openai_reasoning_effort=container.config.strategy_openai_reasoning_effort,
            strategy_openai_max_output_tokens=container.config.strategy_openai_max_output_tokens,
            strategy_openai_api_key_source=container.config.strategy_openai_api_key_source(),
            graph_openai_base_url=container.config.graph_openai_base_url,
            graph_openai_model=container.config.graph_openai_model,
            graph_openai_timeout_sec=container.config.graph_openai_timeout_sec,
            graph_openai_reasoning_effort=container.config.graph_openai_reasoning_effort,
            graph_openai_max_output_tokens=container.config.graph_openai_max_output_tokens,
            graph_openai_api_key_source=container.config.graph_openai_api_key_source(),
            session_store_backend=container.config.session_store_backend,
            session_store_path=str(container.config.session_store_path),
            case_store_backend=container.config.case_store_backend,
            case_store_path=str(container.config.case_store_path),
            database_path=str(container.config.database_path),
            postgres_dsn_configured=bool(container.config.postgres_dsn),
            postgres_dsn_source=container.config.postgres_dsn_source(),
            knowledge_dir=str(container.config.knowledge_dir),
            tool_http_base_url=container.config.tool_http_base_url,
            tool_http_timeout_sec=container.config.tool_http_timeout_sec,
            tool_http_retry_attempts=container.config.tool_http_retry_attempts,
            tool_http_retry_backoff_sec=container.config.tool_http_retry_backoff_sec,
            tool_http_circuit_breaker_failure_threshold=(
                container.config.tool_http_circuit_breaker_failure_threshold
            ),
            tool_http_circuit_breaker_reset_sec=(
                container.config.tool_http_circuit_breaker_reset_sec
            ),
            tool_http_auth_mode=container.config.tool_http_auth_mode,
            tool_http_auth_header=container.config.tool_http_auth_header,
            tool_http_auth_token_source=container.config.tool_http_auth_token_source(),
            tool_http_audit_enabled=container.config.tool_http_audit_enabled,
            tool_http_audit_path=str(container.config.tool_http_audit_path),
            tool_http_audit_max_bytes=container.config.tool_http_audit_max_bytes,
            tool_http_audit_max_files=container.config.tool_http_audit_max_files,
            tool_http_audit_integrity_enabled=(
                container.config.tool_http_audit_integrity_enabled
            ),
            audit_central_enabled=container.config.audit_central_enabled,
            audit_central_url_configured=bool(container.config.audit_central_url),
            audit_central_timeout_sec=container.config.audit_central_timeout_sec,
            audit_central_auth_header=container.config.audit_central_auth_header,
            audit_central_auth_token_source=(
                container.config.audit_central_auth_token_source()
            ),
            risk_decision_policy_source=container.config.risk_decision_policy_source(),
            risk_decision_policy_path=(
                str(container.config.risk_decision_policy_path)
                if container.config.risk_decision_policy_path is not None
                else None
            ),
            admin_auth_enabled=container.config.admin_auth_enabled,
            admin_auth_header=container.config.admin_auth_header,
            admin_auth_token_source=container.config.admin_auth_token_source(),
            admin_auth_configured=bool(container.config.admin_auth_token),
            tool_http_metric_path=container.config.tool_http_metric_path,
            tool_http_case_path=container.config.tool_http_case_path,
            tool_http_order_path_template=container.config.tool_http_order_path_template,
            tool_http_strategy_profile_path_template=container.config.tool_http_strategy_profile_path_template,
            tool_http_strategy_simulation_path_template=container.config.tool_http_strategy_simulation_path_template,
            tool_http_graph_relation_path_template=container.config.tool_http_graph_relation_path_template,
            tool_http_sql_query_path_template=container.config.tool_http_sql_query_path_template,
            tool_http_dashboard_snapshot_path_template=container.config.tool_http_dashboard_snapshot_path_template,
            tool_http_rule_explain_path=container.config.tool_http_rule_explain_path,
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
            observability={
                "json_metrics_path": "/admin/metrics",
                "prometheus_metrics_path": "/metrics",
                "upstream_audit_path": "/admin/audit-events",
                "upstream_audit_integrity_path": "/admin/audit-integrity",
                "duration_histograms": [
                    "http.request.duration_seconds",
                    "agent.execution.duration_seconds",
                    "upstream.http.request.duration_seconds",
                    "database.sqlite.transaction.duration_seconds",
                ],
                "planner_quality_counters": [
                    "agent.planner.plans.total",
                    "agent.planner.fallbacks.total",
                    "agent.planner.validation_errors.total",
                    "agent.tools.executions.total",
                    "agent.intermediate_states.total",
                    "agent.intermediate_states.evidence_gaps.total",
                    "agent.global_plans.total",
                    "agent.evidence_graphs.total",
                    "agent.memory.snapshots.total",
                    "agent.memory.session_refs.total",
                    "agent.memory.long_term_refs.total",
                    "agent.global_plan_quality.evaluations.total",
                    "agent.global_plan_quality.needs_attention.total",
                    "agent.execution_readiness.evaluations.total",
                ],
                "slo_baseline": "docs/observability-slo.md",
            },
            readiness=_build_runtime_readiness(container),
            indexed_documents=container.retrieval.document_count(),
        )

    @fastapi_app.get("/admin/metrics", response_model=RuntimeMetricsResponse)
    def runtime_metrics() -> RuntimeMetricsResponse:
        case_gauges = _build_case_gauges(container)
        return RuntimeMetricsResponse(
            counters=get_metrics_snapshot(),
            gauges={**get_gauges_snapshot(), **case_gauges},
            histograms=get_histograms_snapshot(),
        )

    @fastapi_app.get("/metrics", response_class=PlainTextResponse)
    def prometheus_metrics() -> PlainTextResponse:
        return PlainTextResponse(
            render_prometheus(extra_gauges=_build_case_gauges(container)),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @fastapi_app.get("/admin/audit-events", response_model=List[UpstreamAuditEventPayload])
    def upstream_audit_events(
        outcome: Optional[str] = None,
        upstream_client: Optional[str] = None,
        request_id: Optional[str] = None,
        limit: int = Query(default=100, ge=1, le=200),
    ) -> List[UpstreamAuditEventPayload]:
        return [
            UpstreamAuditEventPayload(**event)
            for event in container.audit_log.list_events(
                limit=limit,
                outcome=outcome,
                upstream_client=upstream_client,
                request_id=request_id,
            )
        ]

    @fastapi_app.get("/admin/audit-integrity", response_model=AuditIntegrityResponse)
    def upstream_audit_integrity() -> AuditIntegrityResponse:
        return AuditIntegrityResponse(**container.audit_log.verify_integrity())

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

    @fastapi_app.get("/cases", response_model=List[WorkflowCasePayload])
    def list_cases(
        response: Response,
        status: Optional[str] = None,
        source_agent: Optional[str] = None,
        intent: Optional[str] = None,
        session_id: Optional[str] = None,
        severity: Optional[str] = None,
        action_queue: Optional[str] = None,
        action_status: Optional[str] = None,
        assigned_to: Optional[str] = None,
        action_overdue: Optional[bool] = None,
        updated_after: Optional[str] = None,
        updated_before: Optional[str] = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: Optional[int] = Query(default=None, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> List[WorkflowCasePayload]:
        try:
            total = container.case_service.count_cases(
                status=status,
                source_agent=source_agent,
                intent=intent,
                session_id=session_id,
                severity=severity,
                action_queue=action_queue,
                action_status=action_status,
                assigned_to=assigned_to,
                action_overdue=action_overdue,
                updated_after=updated_after,
                updated_before=updated_before,
            )
            cases = container.case_service.list_cases(
                status=status,
                source_agent=source_agent,
                intent=intent,
                session_id=session_id,
                severity=severity,
                action_queue=action_queue,
                action_status=action_status,
                assigned_to=assigned_to,
                action_overdue=action_overdue,
                updated_after=updated_after,
                updated_before=updated_before,
                sort_by=sort_by,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response.headers["X-Total-Count"] = str(total)
        response.headers["X-Has-More"] = str(offset + len(cases) < total).lower()
        response.headers["X-Offset"] = str(offset)
        if limit is not None:
            response.headers["X-Limit"] = str(limit)
        return [_to_case_payload(case) for case in cases]

    @fastapi_app.get("/cases/action-queues", response_model=List[ActionQueueSummaryPayload])
    def list_action_queues(
        status: Optional[str] = None,
        source_agent: Optional[str] = None,
        intent: Optional[str] = None,
        session_id: Optional[str] = None,
        severity: Optional[str] = None,
        action_status: Optional[str] = None,
        assigned_to: Optional[str] = None,
        action_overdue: Optional[bool] = None,
        updated_after: Optional[str] = None,
        updated_before: Optional[str] = None,
    ) -> List[ActionQueueSummaryPayload]:
        try:
            cases = container.case_service.list_cases(
                status=status,
                source_agent=source_agent,
                intent=intent,
                session_id=session_id,
                severity=severity,
                action_status=action_status,
                assigned_to=assigned_to,
                action_overdue=action_overdue,
                updated_after=updated_after,
                updated_before=updated_before,
                sort_by="updated_at",
                sort_order="desc",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _build_action_queue_summaries(cases)

    @fastapi_app.get(
        "/cases/action-queues/{queue}/cases",
        response_model=List[WorkflowCasePayload],
    )
    def list_action_queue_cases(
        queue: str,
        action_status: Optional[str] = None,
        assigned_to: Optional[str] = None,
        action_overdue: Optional[bool] = None,
        include_completed: bool = False,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> List[WorkflowCasePayload]:
        cases = container.case_service.list_cases(
            action_queue=queue,
            action_status=action_status,
            assigned_to=assigned_to,
            action_overdue=action_overdue,
        )
        selected_cases = _select_action_queue_cases(
            cases,
            include_completed=include_completed,
            limit=limit,
        )
        return [_to_case_payload(case) for case in selected_cases]

    @fastapi_app.post(
        "/cases/action-queues/{queue}/assign",
        response_model=ActionQueueAssignResponse,
    )
    def assign_action_queue_cases(
        queue: str,
        payload: ActionQueueAssignRequest,
    ) -> ActionQueueAssignResponse:
        cases = container.case_service.list_cases(
            action_queue=queue,
            action_status=payload.action_status,
            action_overdue=payload.action_overdue,
        )
        if payload.case_ids:
            requested_case_ids = set(payload.case_ids)
            cases = [case for case in cases if case.case_id in requested_case_ids]
            missing_case_ids = requested_case_ids.difference(case.case_id for case in cases)
            if missing_case_ids:
                raise HTTPException(
                    status_code=404,
                    detail=f"Cases not found in queue {queue}: {sorted(missing_case_ids)}",
                )
        selected_cases = _select_action_queue_cases(
            cases,
            include_completed=False,
            limit=payload.limit,
        )
        updated_cases: list[WorkflowCase] = []
        for case in selected_cases:
            updated = container.case_service.update_case_status(
                case.case_id,
                case.status,
                note=payload.note or f"Action queue {queue} assigned to {payload.assigned_to}.",
                assigned_to=payload.assigned_to,
            )
            if updated is not None:
                updated_cases.append(updated)
        emit_event(
            "case_action_queue_assigned",
            action_queue=queue,
            assigned_to=payload.assigned_to,
            updated_count=len(updated_cases),
        )
        return ActionQueueAssignResponse(
            queue=queue,
            assigned_to=payload.assigned_to,
            updated_count=len(updated_cases),
            cases=[_to_case_payload(case) for case in updated_cases],
        )

    @fastapi_app.get("/cases/{case_id}", response_model=WorkflowCasePayload)
    def get_case(case_id: str) -> WorkflowCasePayload:
        case = container.case_service.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        return _to_case_payload(case)

    @fastapi_app.post("/cases/from-session/{session_id}", response_model=WorkflowCasePayload)
    def create_case_from_session(session_id: str, turn_index: Optional[int] = None) -> WorkflowCasePayload:
        session = runtime.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        try:
            case = container.case_service.create_case_from_session(session, turn_index=turn_index)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except IndexError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        emit_event(
            "case_created",
            case_id=case.case_id,
            session_id=session_id,
            turn_index=case.turn_index,
            case_status=case.status,
        )
        return _to_case_payload(case)

    @fastapi_app.patch("/cases/{case_id}", response_model=WorkflowCasePayload)
    def update_case_status(case_id: str, payload: CaseStatusUpdateRequest) -> WorkflowCasePayload:
        if payload.status not in ALLOWED_CASE_STATUSES:
            raise HTTPException(status_code=400, detail="Unsupported case status")
        case = container.case_service.update_case_status(
            case_id,
            status=payload.status,
            note=payload.note,
            assigned_to=payload.assigned_to,
            action_outcome=payload.action_outcome,
        )
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        emit_event("case_status_updated", case_id=case.case_id, case_status=case.status)
        return _to_case_payload(case)

    @fastapi_app.post("/admin/knowledge/reload", response_model=KnowledgeReloadResponse)
    def reload_knowledge() -> KnowledgeReloadResponse:
        result = container.knowledge_sync_service.reload()
        return KnowledgeReloadResponse(
            documents_loaded=result.documents_loaded,
            source_count=result.source_count,
            total_documents=container.retrieval.document_count(),
        )

    @fastapi_app.post("/tools/sql/query", response_model=ToolExecutionResponse)
    def sql_query_tool(payload: SqlQueryToolRequest) -> ToolExecutionResponse:
        result = container.tools.execute(
            "sql_query",
            query_name=payload.query_name,
            parameters=payload.parameters,
            limit=payload.limit,
        )
        return ToolExecutionResponse(
            tool_name=result.name,
            status=result.status,
            summary=result.summary,
            payload=result.payload,
        )

    @fastapi_app.post("/tools/dashboard/snapshot", response_model=ToolExecutionResponse)
    def dashboard_snapshot_tool(
        payload: DashboardSnapshotToolRequest,
    ) -> ToolExecutionResponse:
        result = container.tools.execute(
            "dashboard_snapshot",
            dashboard_id=payload.dashboard_id,
            country=payload.country,
            channel=payload.channel,
            time_range=payload.time_range,
        )
        return ToolExecutionResponse(
            tool_name=result.name,
            status=result.status,
            summary=result.summary,
            payload=result.payload,
        )

    @fastapi_app.post("/tools/rules/explain", response_model=ToolExecutionResponse)
    def rule_explain_tool(payload: RuleExplainToolRequest) -> ToolExecutionResponse:
        result = container.tools.execute(
            "rule_explain",
            rule_id=payload.rule_id,
            order_id=payload.order_id,
            strategy_id=payload.strategy_id,
        )
        return ToolExecutionResponse(
            tool_name=result.name,
            status=result.status,
            summary=result.summary,
            payload=result.payload,
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


def _requires_admin_auth(path: str) -> bool:
    return path.startswith("/admin/") or path == "/metrics"


def _is_admin_authorized(request: Request, config: AppConfig) -> bool:
    if not config.admin_auth_enabled:
        return True
    expected = config.admin_auth_token
    if not expected:
        return False
    provided = request.headers.get(config.admin_auth_header)
    if provided is None:
        return False
    return compare_digest(provided, expected)


def _to_response_model(session_id: str, response: AgentResponse) -> AgentInvokeResponse:
    return AgentInvokeResponse(
        session_id=session_id,
        agent_name=response.agent_name,
        summary=response.summary,
        intent=response.intent,
        thought_summary=response.thought_summary,
        plan_steps=response.plan_steps,
        planner_trace=[
            PlannerTracePayload(
                step=trace.step,
                selected=trace.selected,
                reason=trace.reason,
            )
            for trace in response.planner_trace
        ],
        tool_selection_reason=[
            ToolSelectionReasonPayload(
                tool=reason.tool,
                selected=reason.selected,
                reason=reason.reason,
            )
            for reason in response.tool_selection_reason
        ],
        evidence_gap=[_to_evidence_gap_payload(gap) for gap in response.evidence_gap],
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
        evidence=[_to_evidence_payload(evidence) for evidence in response.evidence],
        confidence=response.confidence,
        artifacts=response.artifacts,
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
            thought_summary=turn.thought_summary,
            plan_steps=turn.plan_steps,
            planner_trace=[
                PlannerTracePayload(
                    step=trace.step,
                    selected=trace.selected,
                    reason=trace.reason,
                )
                for trace in turn.planner_trace
            ],
            tool_selection_reason=[
                ToolSelectionReasonPayload(
                    tool=reason.tool,
                    selected=reason.selected,
                    reason=reason.reason,
                )
                for reason in turn.tool_selection_reason
            ],
            evidence_gap=[_to_evidence_gap_payload(gap) for gap in turn.evidence_gap],
            confidence=turn.confidence,
            evidence=[_to_evidence_payload(evidence) for evidence in turn.evidence],
            artifacts=turn.artifacts,
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


def _to_evidence_payload(evidence: EvidenceRecord) -> EvidencePayload:
    return EvidencePayload(
        source=evidence.source,
        source_type=evidence.source_type,
        summary=evidence.summary,
        payload=evidence.payload,
        confidence=evidence.confidence,
        observed_at=evidence.observed_at,
    )


def _to_evidence_gap_payload(gap: EvidenceGap) -> EvidenceGapPayload:
    return EvidenceGapPayload(
        gap=gap.gap,
        source=gap.source,
        severity=gap.severity,
        next_action=gap.next_action,
        blocking=gap.blocking,
    )


def _build_runtime_readiness(container) -> Dict[str, Any]:
    registered_agents = set(container.runtime.list_agents())
    expected_agents = set(container.config.supported_agent_capabilities())
    registered_tools = set(container.tools.list_tools())
    required_tools = {
        tool_name
        for capability in container.config.capability_contract()
        for tool_name in capability["required_tools"]
    }
    sqlite_enabled = _database_backend_enabled(container, "sqlite")
    postgres_enabled = _database_backend_enabled(container, "postgres")
    database_ready = True
    if sqlite_enabled:
        database_ready = SQLiteDatabase(container.config.database_path).is_ready()
    if postgres_enabled:
        database_ready = (
            bool(container.config.postgres_dsn)
            and PostgresDatabase(container.config.postgres_dsn).is_ready()
        )
    set_gauge("runtime.readiness.database", 1.0 if database_ready else 0.0)
    session_store_ready = _store_ready(
        container.config.session_store_backend,
        container.config.session_store_path,
        database_ready,
    )
    case_store_ready = _store_ready(
        container.config.case_store_backend,
        container.config.case_store_path,
        database_ready,
    )
    session_store_path = _store_path(
        container.config,
        container.config.session_store_backend,
        container.config.session_store_path,
    )
    case_store_path = _store_path(
        container.config,
        container.config.case_store_backend,
        container.config.case_store_path,
    )
    checks = [
        {
            "name": "knowledge_index",
            "status": "ready" if container.retrieval.document_count() > 0 else "degraded",
            "detail": f"indexed_documents={container.retrieval.document_count()}",
        },
        {
            "name": "agent_registry",
            "status": "ready" if expected_agents.issubset(registered_agents) else "degraded",
            "detail": f"registered={sorted(registered_agents)}",
        },
        {
            "name": "tool_registry",
            "status": "ready" if required_tools.issubset(registered_tools) else "degraded",
            "detail": f"registered={sorted(registered_tools)}",
        },
        {
            "name": "session_store",
            "status": "ready" if session_store_ready else "degraded",
            "detail": (
                f"backend={container.config.session_store_backend}, "
                f"path={session_store_path}"
            ),
        },
        {
            "name": "case_store",
            "status": "ready" if case_store_ready else "degraded",
            "detail": (
                f"backend={container.config.case_store_backend}, "
                f"path={case_store_path}"
            ),
        },
    ]
    overall_status = "ready" if all(item["status"] == "ready" for item in checks) else "degraded"
    return {"status": overall_status, "checks": checks}


def _store_ready(backend: str, file_path, database_ready: bool) -> bool:
    if backend in {"sqlite", "postgres"}:
        return database_ready
    if backend == "file":
        return file_path.parent.exists()
    return True


def _store_path(config: AppConfig, backend: str, file_path) -> str:
    if backend == "sqlite":
        return str(config.database_path)
    if backend == "postgres":
        return "<postgres-dsn-configured>" if config.postgres_dsn else "<postgres-dsn-missing>"
    return str(file_path)


def _database_backend_enabled(container, backend: str) -> bool:
    return (
        container.config.session_store_backend == backend
        or container.config.case_store_backend == backend
    )


def _to_case_payload(case: WorkflowCase) -> WorkflowCasePayload:
    return WorkflowCasePayload(
        case_id=case.case_id,
        session_id=case.session_id,
        turn_index=case.turn_index,
        title=case.title,
        summary=case.summary,
        status=case.status,
        severity=case.severity,
        source_agent=case.source_agent,
        intent=case.intent,
        context=case.context,
        suggested_actions=case.suggested_actions,
        strategy_recommendation=_to_strategy_recommendation_payload(
            case.strategy_recommendation
        ),
        risk_decision=_to_risk_decision_payload(case.risk_decision),
        history=[_to_case_history_payload(item) for item in case.history],
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def _to_strategy_recommendation_payload(
    recommendation: StrategyRecommendationRecord | None,
) -> StrategyRecommendationPayload | None:
    if recommendation is None:
        return None
    return StrategyRecommendationPayload(
        strategy_id=recommendation.strategy_id,
        current_threshold=recommendation.current_threshold,
        recommended_threshold=recommendation.recommended_threshold,
        validation_window=recommendation.validation_window,
        rationale=recommendation.rationale,
    )


def _to_risk_decision_payload(
    decision: RiskDecisionRecord | None,
) -> RiskDecisionPayload | None:
    if decision is None:
        return None
    return RiskDecisionPayload(
        decision=decision.decision,
        risk_level=decision.risk_level,
        recommended_action=decision.recommended_action,
        evidence_strength=decision.evidence_strength,
        confidence=decision.confidence,
        rationale=decision.rationale,
        escalation_reason=decision.escalation_reason,
        evidence=list(decision.evidence),
        policy_controls=list(decision.policy_controls),
        action_plan=_to_risk_action_plan_payload(decision.action_plan),
    )


def _to_risk_action_plan_payload(
    action_plan: RiskActionPlanRecord | None,
) -> RiskActionPlanPayload | None:
    if action_plan is None:
        return None
    return RiskActionPlanPayload(
        queue=action_plan.queue,
        priority=action_plan.priority,
        sla_hours=action_plan.sla_hours,
        owner_role=action_plan.owner_role,
        next_actions=list(action_plan.next_actions),
        status=action_plan.status,
        due_at=action_plan.due_at,
        assigned_to=action_plan.assigned_to,
        completed_at=action_plan.completed_at,
        outcome=action_plan.outcome,
        is_overdue=is_risk_action_plan_overdue(action_plan),
    )


def _to_case_history_payload(entry: WorkflowCaseHistoryEntry) -> CaseHistoryPayload:
    return CaseHistoryPayload(
        event_type=entry.event_type,
        status=entry.status,
        summary=entry.summary,
    )


def _build_action_queue_summaries(
    cases: list[WorkflowCase],
) -> List[ActionQueueSummaryPayload]:
    summaries: dict[str, dict[str, Any]] = {}
    for case in cases:
        if case.risk_decision is None or case.risk_decision.action_plan is None:
            continue
        action_plan = case.risk_decision.action_plan
        summary = summaries.setdefault(
            action_plan.queue,
            {
                "queue": action_plan.queue,
                "total_cases": 0,
                "overdue_cases": 0,
                "high_priority_cases": 0,
                "statuses": {},
                "priorities": {},
                "assignees": set(),
                "oldest_due_at": None,
                "next_due_at": None,
                "highest_priority": None,
            },
        )
        summary["total_cases"] += 1
        if is_risk_action_plan_overdue(action_plan):
            summary["overdue_cases"] += 1
        if action_plan.priority == "high":
            summary["high_priority_cases"] += 1
        summary["statuses"][action_plan.status] = (
            summary["statuses"].get(action_plan.status, 0) + 1
        )
        summary["priorities"][action_plan.priority] = (
            summary["priorities"].get(action_plan.priority, 0) + 1
        )
        if action_plan.assigned_to:
            summary["assignees"].add(action_plan.assigned_to)
        if action_plan.due_at is not None:
            if summary["oldest_due_at"] is None or action_plan.due_at < summary["oldest_due_at"]:
                summary["oldest_due_at"] = action_plan.due_at
            if action_plan.status != "completed" and (
                summary["next_due_at"] is None or action_plan.due_at < summary["next_due_at"]
            ):
                summary["next_due_at"] = action_plan.due_at
        if _priority_rank(action_plan.priority) > _priority_rank(summary["highest_priority"]):
            summary["highest_priority"] = action_plan.priority

    return [
        ActionQueueSummaryPayload(
            queue=str(summary["queue"]),
            total_cases=int(summary["total_cases"]),
            overdue_cases=int(summary["overdue_cases"]),
            high_priority_cases=int(summary["high_priority_cases"]),
            statuses=dict(sorted(summary["statuses"].items())),
            priorities=dict(sorted(summary["priorities"].items())),
            assignees=sorted(summary["assignees"]),
            oldest_due_at=summary["oldest_due_at"],
            next_due_at=summary["next_due_at"],
            highest_priority=summary["highest_priority"],
        )
        for summary in sorted(
            summaries.values(),
            key=lambda item: (
                -int(item["overdue_cases"]),
                str(item["next_due_at"] or item["oldest_due_at"] or ""),
                str(item["queue"]),
            ),
        )
    ]


def _select_action_queue_cases(
    cases: list[WorkflowCase],
    *,
    include_completed: bool,
    limit: int,
) -> list[WorkflowCase]:
    filtered = [
        case
        for case in cases
        if _case_action_plan(case) is not None
        and (include_completed or _case_action_plan(case).status != "completed")
    ]
    return sorted(filtered, key=_action_queue_case_sort_key)[:limit]


def _action_queue_case_sort_key(case: WorkflowCase) -> tuple[object, ...]:
    action_plan = _case_action_plan(case)
    if action_plan is None:
        return (1, 0, "9999-12-31T23:59:59Z", case.updated_at, case.case_id)
    return (
        0 if is_risk_action_plan_overdue(action_plan) else 1,
        -_priority_rank(action_plan.priority),
        action_plan.due_at or "9999-12-31T23:59:59Z",
        case.updated_at,
        case.case_id,
    )


def _case_action_plan(case: WorkflowCase) -> RiskActionPlanRecord | None:
    if case.risk_decision is None:
        return None
    return case.risk_decision.action_plan


def _priority_rank(priority: str | None) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(priority or "", 0)


def _build_case_gauges(container) -> Dict[str, int]:
    cases = container.case_service.list_cases(sort_by="updated_at", sort_order="desc")
    gauges: Dict[str, int] = {"cases.total": len(cases)}
    for status in ALLOWED_CASE_STATUSES:
        gauges[f"cases.status.{status}"] = 0
    for severity in ("high", "medium", "low"):
        gauges[f"cases.severity.{severity}"] = 0
    gauges["cases.action_plan.total"] = 0
    gauges["cases.action_plan.overdue"] = 0
    for action_status in ("queued", "in_progress", "completed"):
        gauges[f"cases.action_plan.status.{action_status}"] = 0
    for case in cases:
        gauges[f"cases.status.{case.status}"] = gauges.get(
            f"cases.status.{case.status}",
            0,
        ) + 1
        gauges[f"cases.severity.{case.severity}"] = gauges.get(
            f"cases.severity.{case.severity}",
            0,
        ) + 1
        if case.risk_decision is None or case.risk_decision.action_plan is None:
            continue
        action_plan = case.risk_decision.action_plan
        gauges["cases.action_plan.total"] += 1
        gauges[f"cases.action_plan.status.{action_plan.status}"] = gauges.get(
            f"cases.action_plan.status.{action_plan.status}",
            0,
        ) + 1
        gauges[f"cases.action_plan.queue.{action_plan.queue}"] = gauges.get(
            f"cases.action_plan.queue.{action_plan.queue}",
            0,
        ) + 1
        if is_risk_action_plan_overdue(action_plan):
            gauges["cases.action_plan.overdue"] += 1
            gauges[f"cases.action_plan.queue.{action_plan.queue}.overdue"] = gauges.get(
                f"cases.action_plan.queue.{action_plan.queue}.overdue",
                0,
            ) + 1
    return dict(sorted(gauges.items()))


fastapi_app = create_app()
