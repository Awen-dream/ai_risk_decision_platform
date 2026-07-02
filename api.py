from __future__ import annotations

import time
from datetime import datetime, timezone
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
    WorkflowCaseHandoffDeliveryEntry,
    WorkflowCaseHistoryEntry,
    WorkflowCaseOperationEntry,
)
from persistence.postgres import PostgresDatabase
from persistence.sqlite import SQLiteDatabase
from services.handoff import HandoffPublishError, HandoffRetryDecision
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
    evidence_id: str
    evidence_type: str
    source: str
    source_type: str
    source_label: str
    source_agent: Optional[str] = None
    source_tool: Optional[str] = None
    summary: str
    payload: Any
    confidence: float
    status: str = "active"
    tags: List[str] = Field(default_factory=list)
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
    case_id: Optional[str] = None
    handoff_export_id: Optional[str] = None
    handoff_schema_version: Optional[str] = None
    destination_type: Optional[str] = None
    destination_key: Optional[str] = None
    publisher_type: Optional[str] = None
    target_ref: Optional[str] = None
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


class CaseOperationPayload(BaseModel):
    operation_id: str
    operation_type: str
    actor: str
    status_before: Optional[str] = None
    status_after: str
    summary: str
    created_at: str
    assigned_to: Optional[str] = None
    action_outcome: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HandoffDeliveryPayload(BaseModel):
    delivery_id: str
    export_id: str
    destination_type: str
    destination_key: str
    publisher_type: str
    target_ref: str
    status: str
    summary: str
    created_at: str
    published_at: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    retry_eligible: bool = False
    retry_reason: Optional[str] = None
    retry_after: Optional[str] = None
    attempt_count: int = 0
    max_attempts: int = 0
    remaining_attempts: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


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
    evidence_panel: Dict[str, Any] = Field(default_factory=dict)
    handoff_artifact: Dict[str, Any] = Field(default_factory=dict)
    strategy_recommendation: Optional[StrategyRecommendationPayload] = None
    risk_decision: Optional[RiskDecisionPayload] = None
    history: List[CaseHistoryPayload] = Field(default_factory=list)
    operation_log: List[CaseOperationPayload] = Field(default_factory=list)
    handoff_deliveries: List[HandoffDeliveryPayload] = Field(default_factory=list)
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


class WorkbenchBacklogSummaryPayload(BaseModel):
    total_cases: int
    open_cases: int
    overdue_cases: int
    unassigned_cases: int
    high_severity_cases: int
    evidence_covered_cases: int
    status_counts: Dict[str, int] = Field(default_factory=dict)
    severity_counts: Dict[str, int] = Field(default_factory=dict)
    source_agent_counts: Dict[str, int] = Field(default_factory=dict)


class AnalystWorkbenchPayload(BaseModel):
    generated_at: str
    backlog: WorkbenchBacklogSummaryPayload
    action_queues: List[ActionQueueSummaryPayload] = Field(default_factory=list)
    attention_cases: List[WorkflowCasePayload] = Field(default_factory=list)
    recent_cases: List[WorkflowCasePayload] = Field(default_factory=list)
    focus_areas: List[str] = Field(default_factory=list)


class WorkbenchActionPayload(BaseModel):
    action_key: str
    label: str
    description: str
    action_type: str
    target_status: Optional[str] = None
    recommended: bool = False


class CaseWorkbenchPayload(BaseModel):
    generated_at: str
    case: WorkflowCasePayload
    handoff_artifact: Dict[str, Any] = Field(default_factory=dict)
    evidence_summary: Dict[str, Any] = Field(default_factory=dict)
    evidence_gaps: List[EvidenceGapPayload] = Field(default_factory=list)
    citations: List[CitationPayload] = Field(default_factory=list)
    tool_traces: List[ToolTracePayload] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    available_actions: List[WorkbenchActionPayload] = Field(default_factory=list)
    recent_history: List[CaseHistoryPayload] = Field(default_factory=list)
    recent_operations: List[CaseOperationPayload] = Field(default_factory=list)


class HandoffDestinationPayload(BaseModel):
    destination_type: str
    destination_key: str


class HandoffExportPayload(BaseModel):
    export_id: str
    schema_version: str
    exported_at: str
    destination: HandoffDestinationPayload
    case: WorkflowCasePayload
    handoff_artifact: Dict[str, Any] = Field(default_factory=dict)
    operation_log: List[CaseOperationPayload] = Field(default_factory=list)


class HandoffPublishRequest(BaseModel):
    destination_type: str = Field(..., min_length=1)
    destination_key: str = Field(..., min_length=1)
    note: Optional[str] = None


class HandoffPublishResponse(BaseModel):
    receipt_id: str
    status: str
    published_at: str
    audit_event_id: str
    publisher_type: str
    target_ref: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    destination: HandoffDestinationPayload
    export: HandoffExportPayload


class HandoffDeliveryListResponse(BaseModel):
    generated_at: str
    total_count: int
    failed_count: int
    deliveries: List[HandoffDeliveryPayload] = Field(default_factory=list)


class HandoffRetryRequest(BaseModel):
    note: Optional[str] = None


class HandoffRetryBatchRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)
    case_id: Optional[str] = None
    destination_type: Optional[str] = None
    publisher_type: Optional[str] = None
    note: Optional[str] = None


class HandoffRetryBatchResponse(BaseModel):
    generated_at: str
    requested_count: int
    success_count: int
    failed_count: int
    skipped_count: int
    results: List[HandoffPublishResponse] = Field(default_factory=list)
    failures: List[Dict[str, Any]] = Field(default_factory=list)
    skipped: List[Dict[str, Any]] = Field(default_factory=list)


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


class WorkbenchCaseNoteRequest(BaseModel):
    note: str = Field(..., min_length=1)
    assigned_to: Optional[str] = None


class WorkbenchCaseAssignRequest(BaseModel):
    assigned_to: str = Field(..., min_length=1)
    note: Optional[str] = None


class WorkbenchCaseActionRequest(BaseModel):
    action_key: str = Field(..., min_length=1)
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
                    "agent.root_cause.analyses.total",
                    "agent.root_cause_quality.evaluations.total",
                    "agent.root_cause_quality.needs_attention.total",
                    "agent.root_cause_readiness.evaluations.total",
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
        return [_to_case_payload(case, container) for case in cases]

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

    @fastapi_app.get("/analyst-workbench", response_model=AnalystWorkbenchPayload)
    def get_analyst_workbench(
        attention_limit: int = Query(default=5, ge=1, le=20),
        recent_limit: int = Query(default=5, ge=1, le=20),
    ) -> AnalystWorkbenchPayload:
        cases = container.case_service.list_cases(sort_by="updated_at", sort_order="desc")
        action_queue_summaries = _build_action_queue_summaries(cases)
        attention_cases = _select_action_queue_cases(
            cases,
            include_completed=False,
            limit=attention_limit,
        )
        recent_cases = cases[:recent_limit]
        return AnalystWorkbenchPayload(
            generated_at=_utc_now_iso(),
            backlog=_build_workbench_backlog_summary(cases),
            action_queues=action_queue_summaries,
            attention_cases=[_to_case_payload(case, container) for case in attention_cases],
            recent_cases=[_to_case_payload(case, container) for case in recent_cases],
            focus_areas=_build_workbench_focus_areas(cases, action_queue_summaries),
        )

    @fastapi_app.get("/analyst-workbench/cases/{case_id}", response_model=CaseWorkbenchPayload)
    def get_case_workbench(case_id: str) -> CaseWorkbenchPayload:
        case = container.case_service.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        return _build_case_workbench_payload(container, case)

    @fastapi_app.post(
        "/analyst-workbench/cases/{case_id}/notes",
        response_model=CaseWorkbenchPayload,
    )
    def append_case_workbench_note(
        case_id: str,
        payload: WorkbenchCaseNoteRequest,
    ) -> CaseWorkbenchPayload:
        case = container.case_service.append_case_note(
            case_id,
            payload.note,
            assigned_to=payload.assigned_to,
        )
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        emit_event("case_note_added", case_id=case.case_id, case_status=case.status)
        return _build_case_workbench_payload(container, case)

    @fastapi_app.post(
        "/analyst-workbench/cases/{case_id}/assign",
        response_model=CaseWorkbenchPayload,
    )
    def assign_case_workbench_owner(
        case_id: str,
        payload: WorkbenchCaseAssignRequest,
    ) -> CaseWorkbenchPayload:
        case = container.case_service.append_case_note(
            case_id,
            payload.note or f"案件已分派给 {payload.assigned_to}。",
            assigned_to=payload.assigned_to,
        )
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        emit_event(
            "case_workbench_assigned",
            case_id=case.case_id,
            assigned_to=payload.assigned_to,
            case_status=case.status,
        )
        return _build_case_workbench_payload(container, case)

    @fastapi_app.post(
        "/analyst-workbench/cases/{case_id}/actions",
        response_model=CaseWorkbenchPayload,
    )
    def execute_case_workbench_action(
        case_id: str,
        payload: WorkbenchCaseActionRequest,
    ) -> CaseWorkbenchPayload:
        case = container.case_service.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        supported_actions = {
            action.action_key: action
            for action in _build_case_workbench_actions(case)
        }
        if payload.action_key not in supported_actions:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported workbench action: {payload.action_key}",
            )
        updated_case = _execute_case_workbench_action(
            container.case_service,
            case,
            payload,
        )
        if updated_case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        emit_event(
            "case_workbench_action_executed",
            case_id=updated_case.case_id,
            action_key=payload.action_key,
            case_status=updated_case.status,
        )
        return _build_case_workbench_payload(container, updated_case)

    @fastapi_app.get(
        "/analyst-workbench/cases/{case_id}/handoff-export",
        response_model=HandoffExportPayload,
    )
    def export_case_handoff(
        case_id: str,
        destination_type: str = Query(default="generic", min_length=1),
        destination_key: str = Query(default="default", min_length=1),
    ) -> HandoffExportPayload:
        export_payload = container.handoff_publisher_service.export_case_handoff(
            case_id,
            destination_type=destination_type,
            destination_key=destination_key,
            exported_at=_utc_now_iso(),
        )
        if export_payload is None:
            raise HTTPException(status_code=404, detail="Case not found")
        return _to_handoff_export_payload(container, export_payload)

    @fastapi_app.post(
        "/analyst-workbench/cases/{case_id}/handoff-publish",
        response_model=HandoffPublishResponse,
    )
    def publish_case_handoff(
        case_id: str,
        payload: HandoffPublishRequest,
    ) -> HandoffPublishResponse:
        try:
            result = container.handoff_publisher_service.publish_case_handoff(
                case_id,
                destination_type=payload.destination_type,
                destination_key=payload.destination_key,
                note=payload.note,
                published_at=_utc_now_iso(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except HandoffPublishError as exc:
            result = exc.result
            emit_event(
                "case_handoff_publish_failed",
                case_id=case_id,
                destination_type=payload.destination_type,
                destination_key=payload.destination_key,
                publisher_type=result.receipt.publisher_type,
                error_type=result.receipt.error_type,
                audit_event_id=result.audit_event["event_id"],
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Failed to publish case handoff",
                    "receipt_id": result.receipt.receipt_id,
                    "status": result.receipt.status,
                    "published_at": result.receipt.published_at,
                    "audit_event_id": str(result.audit_event["event_id"]),
                    "publisher_type": result.receipt.publisher_type,
                    "target_ref": result.receipt.target_ref,
                    "error_type": result.receipt.error_type,
                    "error_message": result.receipt.error_message,
                    "metadata": result.receipt.metadata,
                    "destination": {
                        "destination_type": result.export.destination.destination_type,
                        "destination_key": result.export.destination.destination_key,
                    },
                },
            ) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="Case not found")
        emit_event(
            "case_handoff_published",
            case_id=result.case.case_id,
            destination_type=payload.destination_type,
            destination_key=payload.destination_key,
            audit_event_id=result.audit_event["event_id"],
        )
        return _to_handoff_publish_response(container, result)

    @fastapi_app.get(
        "/analyst-workbench/cases/{case_id}/handoff-deliveries",
        response_model=HandoffDeliveryListResponse,
    )
    def get_case_handoff_deliveries(case_id: str) -> HandoffDeliveryListResponse:
        case = container.case_service.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        return _build_handoff_delivery_list_response(
            container,
            [(case, item) for item in case.handoff_deliveries],
        )

    @fastapi_app.post(
        "/analyst-workbench/cases/{case_id}/handoff-deliveries/{delivery_id}/retry",
        response_model=HandoffPublishResponse,
    )
    def retry_case_handoff_delivery(
        case_id: str,
        delivery_id: str,
        payload: HandoffRetryRequest,
    ) -> HandoffPublishResponse:
        case = container.case_service.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        delivery = _find_case_handoff_delivery(case, delivery_id)
        if delivery is None:
            raise HTTPException(status_code=404, detail="Handoff delivery not found")
        decision = container.handoff_publisher_service.evaluate_delivery_retry(
            case,
            delivery,
            evaluated_at=_utc_now_iso(),
        )
        if not decision.eligible:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Handoff delivery is not retryable",
                    "delivery_id": delivery.delivery_id,
                    "retry_reason": decision.reason,
                    "retry_after": decision.retry_after,
                    "attempt_count": decision.attempt_count,
                    "max_attempts": decision.max_attempts,
                    "remaining_attempts": decision.remaining_attempts,
                },
            )
        emit_event(
            "case_handoff_retry_requested",
            case_id=case_id,
            delivery_id=delivery.delivery_id,
            destination_type=delivery.destination_type,
            destination_key=delivery.destination_key,
            publisher_type=delivery.publisher_type,
        )
        try:
            result = container.handoff_publisher_service.publish_case_handoff(
                case_id,
                destination_type=delivery.destination_type,
                destination_key=delivery.destination_key,
                note=payload.note or f"重试投递 {delivery.delivery_id}",
                published_at=_utc_now_iso(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except HandoffPublishError as exc:
            result = exc.result
            emit_event(
                "case_handoff_retry_failed",
                case_id=case_id,
                delivery_id=delivery.delivery_id,
                destination_type=delivery.destination_type,
                destination_key=delivery.destination_key,
                publisher_type=result.receipt.publisher_type,
                error_type=result.receipt.error_type,
                audit_event_id=result.audit_event["event_id"],
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Failed to retry case handoff",
                    "delivery_id": delivery.delivery_id,
                    "receipt_id": result.receipt.receipt_id,
                    "status": result.receipt.status,
                    "published_at": result.receipt.published_at,
                    "audit_event_id": str(result.audit_event["event_id"]),
                    "publisher_type": result.receipt.publisher_type,
                    "target_ref": result.receipt.target_ref,
                    "error_type": result.receipt.error_type,
                    "error_message": result.receipt.error_message,
                    "metadata": result.receipt.metadata,
                    "destination": {
                        "destination_type": result.export.destination.destination_type,
                        "destination_key": result.export.destination.destination_key,
                    },
                },
            ) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="Case not found")
        emit_event(
            "case_handoff_retry_completed",
            case_id=result.case.case_id,
            delivery_id=delivery.delivery_id,
            destination_type=delivery.destination_type,
            destination_key=delivery.destination_key,
            publisher_type=result.receipt.publisher_type,
            audit_event_id=result.audit_event["event_id"],
        )
        return _to_handoff_publish_response(container, result)

    @fastapi_app.get(
        "/analyst-workbench/handoff-deliveries",
        response_model=HandoffDeliveryListResponse,
    )
    def list_handoff_deliveries(
        case_id: Optional[str] = None,
        status: Optional[str] = None,
        destination_type: Optional[str] = None,
        publisher_type: Optional[str] = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> HandoffDeliveryListResponse:
        deliveries = _list_handoff_deliveries(
            container.case_service.list_cases(limit=None),
            case_id=case_id,
            status=status,
            destination_type=destination_type,
            publisher_type=publisher_type,
            limit=limit,
        )
        return _build_handoff_delivery_list_response(container, deliveries)

    @fastapi_app.get(
        "/analyst-workbench/handoff-dead-letter",
        response_model=HandoffDeliveryListResponse,
    )
    def list_handoff_dead_letter(
        case_id: Optional[str] = None,
        destination_type: Optional[str] = None,
        publisher_type: Optional[str] = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> HandoffDeliveryListResponse:
        deliveries = _list_handoff_deliveries(
            container.case_service.list_cases(limit=None),
            case_id=case_id,
            status="failed",
            destination_type=destination_type,
            publisher_type=publisher_type,
            limit=limit,
        )
        return _build_handoff_delivery_list_response(container, deliveries)

    @fastapi_app.post(
        "/analyst-workbench/handoff-dead-letter/retry",
        response_model=HandoffRetryBatchResponse,
    )
    def retry_handoff_dead_letter(
        payload: HandoffRetryBatchRequest,
    ) -> HandoffRetryBatchResponse:
        deliveries = container.handoff_publisher_service.list_retry_candidates(
            container.case_service.list_cases(limit=None),
            evaluated_at=_utc_now_iso(),
            case_id=payload.case_id,
            destination_type=payload.destination_type,
            publisher_type=payload.publisher_type,
            limit=min(payload.limit, container.config.handoff_retry_sweep_limit),
        )
        results: list[HandoffPublishResponse] = []
        failures: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for owner_case, delivery, decision in deliveries:
            if not decision.eligible:
                emit_event(
                    "case_handoff_retry_skipped",
                    case_id=owner_case.case_id,
                    delivery_id=delivery.delivery_id,
                    destination_type=delivery.destination_type,
                    destination_key=delivery.destination_key,
                    publisher_type=delivery.publisher_type,
                    retry_reason=decision.reason,
                )
                skipped.append(
                    {
                        "delivery_id": delivery.delivery_id,
                        "case_id": owner_case.case_id,
                        "retry_reason": decision.reason,
                        "retry_after": decision.retry_after,
                        "attempt_count": decision.attempt_count,
                        "max_attempts": decision.max_attempts,
                        "remaining_attempts": decision.remaining_attempts,
                    }
                )
                continue
            retry_note = payload.note or f"批量重试投递 {delivery.delivery_id}"
            emit_event(
                "case_handoff_retry_requested",
                case_id=owner_case.case_id,
                delivery_id=delivery.delivery_id,
                destination_type=delivery.destination_type,
                destination_key=delivery.destination_key,
                publisher_type=delivery.publisher_type,
            )
            try:
                result = container.handoff_publisher_service.publish_case_handoff(
                    owner_case.case_id,
                    destination_type=delivery.destination_type,
                    destination_key=delivery.destination_key,
                    note=retry_note,
                    published_at=_utc_now_iso(),
                )
            except ValueError as exc:
                failures.append(
                    {
                        "delivery_id": delivery.delivery_id,
                        "message": str(exc),
                    }
                )
                continue
            except HandoffPublishError as exc:
                result = exc.result
                emit_event(
                    "case_handoff_retry_failed",
                    case_id=result.case.case_id,
                    delivery_id=delivery.delivery_id,
                    destination_type=delivery.destination_type,
                    destination_key=delivery.destination_key,
                    publisher_type=result.receipt.publisher_type,
                    error_type=result.receipt.error_type,
                    audit_event_id=result.audit_event["event_id"],
                )
                failures.append(
                    {
                        "delivery_id": delivery.delivery_id,
                        "case_id": result.case.case_id,
                        "message": result.receipt.error_message,
                        "publisher_type": result.receipt.publisher_type,
                        "target_ref": result.receipt.target_ref,
                        "error_type": result.receipt.error_type,
                    }
                )
                continue
            if result is None:
                failures.append(
                    {
                        "delivery_id": delivery.delivery_id,
                        "message": "Case not found",
                    }
                )
                continue
            emit_event(
                "case_handoff_retry_completed",
                case_id=result.case.case_id,
                delivery_id=delivery.delivery_id,
                destination_type=delivery.destination_type,
                destination_key=delivery.destination_key,
                publisher_type=result.receipt.publisher_type,
                audit_event_id=result.audit_event["event_id"],
            )
            results.append(_to_handoff_publish_response(container, result))
        return HandoffRetryBatchResponse(
            generated_at=_utc_now_iso(),
            requested_count=len(deliveries),
            success_count=len(results),
            failed_count=len(failures),
            skipped_count=len(skipped),
            results=results,
            failures=failures,
            skipped=skipped,
        )

    @fastapi_app.post(
        "/analyst-workbench/handoff-dead-letter/sweep",
        response_model=HandoffRetryBatchResponse,
    )
    def sweep_handoff_dead_letter(
        payload: HandoffRetryBatchRequest,
    ) -> HandoffRetryBatchResponse:
        return retry_handoff_dead_letter(payload)

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
        return [_to_case_payload(case, container) for case in selected_cases]

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
            cases=[_to_case_payload(case, container) for case in updated_cases],
        )

    @fastapi_app.get("/cases/{case_id}", response_model=WorkflowCasePayload)
    def get_case(case_id: str) -> WorkflowCasePayload:
        case = container.case_service.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        return _to_case_payload(case, container)

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
        return _to_case_payload(case, container)

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
        return _to_case_payload(case, container)

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
        evidence_id=evidence.evidence_id,
        evidence_type=evidence.evidence_type,
        source=evidence.source,
        source_type=evidence.source_type,
        source_label=evidence.source_label,
        source_agent=evidence.source_agent,
        source_tool=evidence.source_tool,
        summary=evidence.summary,
        payload=evidence.payload,
        confidence=evidence.confidence,
        status=evidence.status,
        tags=list(evidence.tags),
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


def _to_case_payload(
    case: WorkflowCase,
    container=None,
) -> WorkflowCasePayload:
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
        evidence_panel=case.evidence_panel,
        handoff_artifact=case.handoff_artifact,
        strategy_recommendation=_to_strategy_recommendation_payload(
            case.strategy_recommendation
        ),
        risk_decision=_to_risk_decision_payload(case.risk_decision),
        history=[_to_case_history_payload(item) for item in case.history],
        operation_log=[_to_case_operation_payload(item) for item in case.operation_log],
        handoff_deliveries=[
            _to_handoff_delivery_payload(container, case, item)
            if container is not None
            else HandoffDeliveryPayload(
                delivery_id=item.delivery_id,
                export_id=item.export_id,
                destination_type=item.destination_type,
                destination_key=item.destination_key,
                publisher_type=item.publisher_type,
                target_ref=item.target_ref,
                status=item.status,
                summary=item.summary,
                created_at=item.created_at,
                published_at=item.published_at,
                error_type=item.error_type,
                error_message=item.error_message,
                metadata=dict(item.metadata),
            )
            for item in case.handoff_deliveries
        ],
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def _to_handoff_delivery_payload(
    container,
    case: WorkflowCase,
    delivery: WorkflowCaseHandoffDeliveryEntry,
) -> HandoffDeliveryPayload:
    decision = container.handoff_publisher_service.evaluate_delivery_retry(
        case,
        delivery,
        evaluated_at=_utc_now_iso(),
    )
    return HandoffDeliveryPayload(
        delivery_id=delivery.delivery_id,
        export_id=delivery.export_id,
        destination_type=delivery.destination_type,
        destination_key=delivery.destination_key,
        publisher_type=delivery.publisher_type,
        target_ref=delivery.target_ref,
        status=delivery.status,
        summary=delivery.summary,
        created_at=delivery.created_at,
        published_at=delivery.published_at,
        error_type=delivery.error_type,
        error_message=delivery.error_message,
        retry_eligible=decision.eligible,
        retry_reason=decision.reason,
        retry_after=decision.retry_after,
        attempt_count=decision.attempt_count,
        max_attempts=decision.max_attempts,
        remaining_attempts=decision.remaining_attempts,
        metadata=dict(delivery.metadata),
    )


def _build_handoff_delivery_list_response(
    container,
    deliveries: list[tuple[WorkflowCase, WorkflowCaseHandoffDeliveryEntry]],
) -> HandoffDeliveryListResponse:
    failed_count = sum(1 for _, item in deliveries if item.status != "published")
    return HandoffDeliveryListResponse(
        generated_at=_utc_now_iso(),
        total_count=len(deliveries),
        failed_count=failed_count,
        deliveries=[
            _to_handoff_delivery_payload(container, case, item)
            for case, item in deliveries
        ],
    )


def _to_handoff_publish_response(container, result) -> HandoffPublishResponse:
    return HandoffPublishResponse(
        receipt_id=result.receipt.receipt_id,
        status=result.receipt.status,
        published_at=result.receipt.published_at,
        audit_event_id=str(result.audit_event["event_id"]),
        publisher_type=result.receipt.publisher_type,
        target_ref=result.receipt.target_ref,
        metadata=result.receipt.metadata,
        destination=HandoffDestinationPayload(
            destination_type=result.export.destination.destination_type,
            destination_key=result.export.destination.destination_key,
        ),
        export=_to_handoff_export_payload(container, result.export),
    )


def _list_handoff_deliveries(
    cases: list[WorkflowCase],
    *,
    case_id: str | None = None,
    status: str | None = None,
    destination_type: str | None = None,
    publisher_type: str | None = None,
    limit: int = 100,
) -> list[tuple[WorkflowCase, WorkflowCaseHandoffDeliveryEntry]]:
    deliveries: list[tuple[WorkflowCase, WorkflowCaseHandoffDeliveryEntry]] = []
    for case in cases:
        if case_id is not None and case.case_id != case_id:
            continue
        for delivery in case.handoff_deliveries:
            if status is not None and delivery.status != status:
                continue
            if (
                destination_type is not None
                and delivery.destination_type != destination_type
            ):
                continue
            if publisher_type is not None and delivery.publisher_type != publisher_type:
                continue
            deliveries.append((case, delivery))
    deliveries.sort(key=lambda item: item[1].created_at, reverse=True)
    return deliveries[:limit]


def _find_case_handoff_delivery(
    case: WorkflowCase,
    delivery_id: str,
) -> WorkflowCaseHandoffDeliveryEntry | None:
    for delivery in case.handoff_deliveries:
        if delivery.delivery_id == delivery_id:
            return delivery
    return None


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


def _to_case_operation_payload(entry: WorkflowCaseOperationEntry) -> CaseOperationPayload:
    return CaseOperationPayload(
        operation_id=entry.operation_id,
        operation_type=entry.operation_type,
        actor=entry.actor,
        status_before=entry.status_before,
        status_after=entry.status_after,
        summary=entry.summary,
        created_at=entry.created_at,
        assigned_to=entry.assigned_to,
        action_outcome=entry.action_outcome,
        metadata=entry.metadata,
    )


def _build_case_workbench_payload(container, case: WorkflowCase) -> CaseWorkbenchPayload:
    evidence_panel = case.evidence_panel or {}
    return CaseWorkbenchPayload(
        generated_at=_utc_now_iso(),
        case=_to_case_payload(case, container),
        handoff_artifact=case.handoff_artifact,
        evidence_summary=dict(evidence_panel.get("summary", {})),
        evidence_gaps=[
            _evidence_gap_payload_from_mapping(item)
            for item in evidence_panel.get("gaps", [])
            if isinstance(item, dict)
        ],
        citations=[
            _citation_payload_from_mapping(item)
            for item in evidence_panel.get("citations", [])
            if isinstance(item, dict)
        ],
        tool_traces=[
            _tool_trace_payload_from_mapping(item)
            for item in evidence_panel.get("tool_traces", [])
            if isinstance(item, dict)
        ],
        recommended_actions=_build_case_workbench_recommended_actions(case, evidence_panel),
        available_actions=_build_case_workbench_actions(case),
        recent_history=[_to_case_history_payload(item) for item in case.history[-5:]],
        recent_operations=[
            _to_case_operation_payload(item) for item in case.operation_log[-5:]
        ],
    )


def _to_handoff_export_payload(container, export) -> HandoffExportPayload:
    return HandoffExportPayload(
        export_id=export.export_id,
        schema_version=export.schema_version,
        exported_at=export.exported_at,
        destination=HandoffDestinationPayload(
            destination_type=export.destination.destination_type,
            destination_key=export.destination.destination_key,
        ),
        case=_to_case_payload(export.case, container),
        handoff_artifact=export.handoff_artifact,
        operation_log=[_to_case_operation_payload(item) for item in export.operation_log],
    )


def _evidence_gap_payload_from_mapping(item: dict[str, Any]) -> EvidenceGapPayload:
    return EvidenceGapPayload(
        gap=str(item.get("gap", "")),
        source=str(item.get("source", "")),
        severity=str(item.get("severity", "medium")),
        next_action=str(item.get("next_action", "")),
        blocking=bool(item.get("blocking", False)),
    )


def _citation_payload_from_mapping(item: dict[str, Any]) -> CitationPayload:
    return CitationPayload(
        doc_id=str(item.get("doc_id", "")),
        title=str(item.get("title", "")),
        source_type=str(item.get("source_type", "")),
        snippet=str(item.get("snippet", "")),
    )


def _tool_trace_payload_from_mapping(item: dict[str, Any]) -> ToolTracePayload:
    return ToolTracePayload(
        name=str(item.get("name", "")),
        status=str(item.get("status", "")),
        summary=str(item.get("summary", "")),
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


def _build_workbench_backlog_summary(
    cases: list[WorkflowCase],
) -> WorkbenchBacklogSummaryPayload:
    status_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    source_agent_counts: dict[str, int] = {}
    open_cases = 0
    overdue_cases = 0
    unassigned_cases = 0
    high_severity_cases = 0
    evidence_covered_cases = 0
    for case in cases:
        status_counts[case.status] = status_counts.get(case.status, 0) + 1
        severity_counts[case.severity] = severity_counts.get(case.severity, 0) + 1
        source_agent_counts[case.source_agent] = source_agent_counts.get(case.source_agent, 0) + 1
        if case.status != "closed":
            open_cases += 1
        if case.severity == "high":
            high_severity_cases += 1
        if case.evidence_panel.get("summary", {}).get("evidence_count", 0) > 0:
            evidence_covered_cases += 1
        action_plan = _case_action_plan(case)
        if action_plan is not None:
            if is_risk_action_plan_overdue(action_plan):
                overdue_cases += 1
            if not action_plan.assigned_to and action_plan.status != "completed":
                unassigned_cases += 1
    return WorkbenchBacklogSummaryPayload(
        total_cases=len(cases),
        open_cases=open_cases,
        overdue_cases=overdue_cases,
        unassigned_cases=unassigned_cases,
        high_severity_cases=high_severity_cases,
        evidence_covered_cases=evidence_covered_cases,
        status_counts=dict(sorted(status_counts.items())),
        severity_counts=dict(sorted(severity_counts.items())),
        source_agent_counts=dict(sorted(source_agent_counts.items())),
    )


def _build_workbench_focus_areas(
    cases: list[WorkflowCase],
    queue_summaries: list[ActionQueueSummaryPayload],
) -> list[str]:
    if not cases:
        return ["当前没有待处理案件，工作台处于空闲状态。"]
    focus_areas: list[str] = []
    overdue_cases = sum(summary.overdue_cases for summary in queue_summaries)
    if overdue_cases:
        focus_areas.append(
            f"当前有 {overdue_cases} 个案件已超 SLA，建议优先处理逾期队列。"
        )
    unassigned_cases = sum(
        1
        for case in cases
        if (action_plan := _case_action_plan(case)) is not None
        and action_plan.status != "completed"
        and not action_plan.assigned_to
    )
    if unassigned_cases:
        focus_areas.append(
            f"当前有 {unassigned_cases} 个案件尚未分派，建议尽快完成责任人分配。"
        )
    high_severity_cases = sum(1 for case in cases if case.severity == "high")
    if high_severity_cases:
        focus_areas.append(
            f"高优先级风险案件共有 {high_severity_cases} 个，建议先看高危案件。"
        )
    evidence_gap_cases = sum(
        1
        for case in cases
        if case.evidence_panel.get("summary", {}).get("evidence_gap_count", 0) > 0
    )
    if evidence_gap_cases:
        focus_areas.append(
            f"有 {evidence_gap_cases} 个案件存在证据缺口，建议补齐调查链路后再推进处置。"
        )
    return focus_areas or ["案件证据和处置状态正常，可按最近更新时间推进处理。"]


def _build_case_workbench_recommended_actions(
    case: WorkflowCase,
    evidence_panel: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    for item in case.suggested_actions:
        if item and item not in actions:
            actions.append(item)
    action_plan = _case_action_plan(case)
    if action_plan is not None:
        for item in action_plan.next_actions:
            if item and item not in actions:
                actions.append(item)
        if not action_plan.assigned_to:
            assignment_hint = f"将案件分派给 {action_plan.owner_role}"
            if assignment_hint not in actions:
                actions.append(assignment_hint)
    for gap in evidence_panel.get("gaps", []):
        if not isinstance(gap, dict):
            continue
        next_action = str(gap.get("next_action", "")).strip()
        if next_action and next_action not in actions:
            actions.append(next_action)
    return actions


def _build_case_workbench_actions(case: WorkflowCase) -> list[WorkbenchActionPayload]:
    actions: list[WorkbenchActionPayload] = [
        WorkbenchActionPayload(
            action_key="add_note",
            label="添加备注",
            description="记录运营跟进、沟通结果或补充上下文。",
            action_type="note",
            recommended=True,
        )
    ]
    action_plan = _case_action_plan(case)
    if action_plan is not None:
        actions.append(
            WorkbenchActionPayload(
                action_key="assign_owner",
                label="分派负责人" if not action_plan.assigned_to else "重新分派",
                description=f"将案件分派给 {action_plan.owner_role} 角色处理。",
                action_type="assign",
                recommended=not action_plan.assigned_to,
            )
        )
    evidence_gap_count = case.evidence_panel.get("summary", {}).get("evidence_gap_count", 0)
    if evidence_gap_count and case.status != "closed":
        actions.append(
            WorkbenchActionPayload(
                action_key="request_more_evidence",
                label="补充证据",
                description="发起补证跟进，推动补齐缺失调查信息。",
                action_type="follow_up",
                recommended=True,
            )
        )
    if case.status in {"open", "strategy_pending"}:
        actions.append(
            WorkbenchActionPayload(
                action_key="start_review",
                label="开始复核",
                description="将案件切换到人工复核处理中。",
                action_type="status_update",
                target_status="in_review",
                recommended=True,
            )
        )
    if case.status != "closed":
        actions.append(
            WorkbenchActionPayload(
                action_key="close_case",
                label="关闭案件",
                description="完成处置后关闭案件并结束 action plan。",
                action_type="status_update",
                target_status="closed",
            )
        )
    else:
        actions.append(
            WorkbenchActionPayload(
                action_key="reopen_case",
                label="重新打开",
                description="需要追加调查时重新进入人工复核。",
                action_type="status_update",
                target_status="in_review",
            )
        )
    return actions


def _execute_case_workbench_action(
    case_service,
    case: WorkflowCase,
    payload: WorkbenchCaseActionRequest,
) -> WorkflowCase | None:
    if payload.action_key == "add_note":
        note = payload.note or "已添加运营备注。"
        return case_service.append_case_note(
            case.case_id,
            note,
            assigned_to=payload.assigned_to,
        )
    if payload.action_key == "assign_owner":
        if not payload.assigned_to:
            raise HTTPException(status_code=400, detail="assigned_to is required")
        return case_service.append_case_note(
            case.case_id,
            payload.note or f"案件已分派给 {payload.assigned_to}。",
            assigned_to=payload.assigned_to,
        )
    if payload.action_key == "request_more_evidence":
        return case_service.append_case_note(
            case.case_id,
            payload.note or "已发起补证请求，等待补充调查信息。",
            assigned_to=payload.assigned_to,
        )
    target_status = {
        "start_review": "in_review",
        "close_case": "closed",
        "reopen_case": "in_review",
    }.get(payload.action_key)
    if target_status is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported workbench action: {payload.action_key}",
        )
    default_note = {
        "start_review": "案件已进入人工复核。",
        "close_case": "案件已关闭。",
        "reopen_case": "案件已重新打开并进入人工复核。",
    }[payload.action_key]
    return case_service.update_case_status(
        case.case_id,
        target_status,
        note=payload.note or default_note,
        assigned_to=payload.assigned_to,
        action_outcome=payload.action_outcome,
    )


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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_case_gauges(container) -> Dict[str, int]:
    cases = container.case_service.list_cases(sort_by="updated_at", sort_order="desc")
    gauges: Dict[str, int] = {"cases.total": len(cases)}
    evaluated_at = _utc_now_iso()
    for status in ALLOWED_CASE_STATUSES:
        gauges[f"cases.status.{status}"] = 0
    for severity in ("high", "medium", "low"):
        gauges[f"cases.severity.{severity}"] = 0
    gauges["cases.action_plan.total"] = 0
    gauges["cases.action_plan.overdue"] = 0
    gauges["cases.handoff.deliveries.total"] = 0
    gauges["cases.handoff.deliveries.failed"] = 0
    gauges["cases.handoff.dead_letter_cases"] = 0
    gauges["cases.handoff.deliveries.retryable"] = 0
    gauges["cases.handoff.deliveries.cooldown_blocked"] = 0
    gauges["cases.handoff.deliveries.limit_blocked"] = 0
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
        gauges["cases.handoff.deliveries.total"] += len(case.handoff_deliveries)
        failed_deliveries = [item for item in case.handoff_deliveries if item.status != "published"]
        gauges["cases.handoff.deliveries.failed"] += len(failed_deliveries)
        if failed_deliveries:
            gauges["cases.handoff.dead_letter_cases"] += 1
        for delivery in case.handoff_deliveries:
            decision = container.handoff_publisher_service.evaluate_delivery_retry(
                case,
                delivery,
                evaluated_at=evaluated_at,
            )
            gauges[f"cases.handoff.deliveries.status.{delivery.status}"] = gauges.get(
                f"cases.handoff.deliveries.status.{delivery.status}",
                0,
            ) + 1
            gauges[
                f"cases.handoff.deliveries.destination.{delivery.destination_type}"
            ] = gauges.get(
                f"cases.handoff.deliveries.destination.{delivery.destination_type}",
                0,
            ) + 1
            gauges[
                f"cases.handoff.deliveries.publisher.{delivery.publisher_type}"
            ] = gauges.get(
                f"cases.handoff.deliveries.publisher.{delivery.publisher_type}",
                0,
            ) + 1
            if delivery.status != "published":
                if decision.eligible:
                    gauges["cases.handoff.deliveries.retryable"] += 1
                elif decision.reason == "retry_cooldown_active":
                    gauges["cases.handoff.deliveries.cooldown_blocked"] += 1
                elif decision.reason == "retry_attempt_limit_reached":
                    gauges["cases.handoff.deliveries.limit_blocked"] += 1
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
