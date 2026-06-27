from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from clients.file import (
    JsonCaseRecordClient,
    JsonDashboardSnapshotClient,
    JsonGraphRelationClient,
    JsonMetricSnapshotSqlClient,
    JsonOrderProfileClient,
    JsonRuleExplainClient,
    JsonSqlQueryClient,
    JsonStrategyProfileClient,
    JsonStrategySimulationClient,
)
from services.fault_injection import FaultController, FaultRule
from settings import AppConfig


class MetricSnapshotResponse(BaseModel):
    country: str
    channel: str
    time_range: str
    metric_name: str
    anomaly_started_at: str
    current_value: str
    baseline_value: str
    recent_change: str
    suspected_driver: str


class CaseRecordResponse(BaseModel):
    case_id: str
    country: str
    channel: str
    title: str


class OrderProfileResponse(BaseModel):
    order_id: str
    country: str
    channel: str
    recent_attempts: int
    triggered_rules: List[str]
    risk_labels: List[str]
    recommended_action: str


class StrategyProfileResponse(BaseModel):
    strategy_id: str
    name: str
    country: str
    channel: str
    status: str
    current_threshold: float
    hit_rate: str
    risk_capture_rate: str
    false_positive_rate: str
    recent_issue: str
    top_impacted_entities: List[str]


class StrategySimulationResponse(BaseModel):
    strategy_id: str
    recommended_threshold: float
    delta_intercepts: str
    delta_false_positives: str
    estimated_risk_reduction: str
    estimated_revenue_impact: str
    simulation_window: str
    recommendation_reason: str


class GraphRelationResponse(BaseModel):
    entity_id: str
    entity_type: str
    risk_level: str
    shared_devices: List[str]
    shared_ips: List[str]
    linked_accounts: List[str]
    linked_orders: List[str]
    community_size: int
    key_path: str
    risk_reason: str


class SqlQueryRowResponse(BaseModel):
    segment: str
    current_value: str
    baseline_value: str
    delta: str


class SqlQueryResponse(BaseModel):
    query_name: str
    country: str
    channel: str
    time_range: str
    description: str
    columns: List[str]
    rows: List[SqlQueryRowResponse]
    row_count: int
    limit: int


class DashboardSnapshotResponse(BaseModel):
    dashboard_id: str
    title: str
    country: str
    channel: str
    time_range: str
    metric_name: str
    current_value: str
    baseline_value: str
    trend: str
    largest_segment: str
    largest_segment_change: str
    recommended_drilldowns: List[str]


class RuleHitResponse(BaseModel):
    rule_id: str
    rule_name: str
    feature: str
    operator: str
    threshold: Union[str, int, float]
    actual_value: Union[str, int, float]


class RuleExplanationResponse(BaseModel):
    subject_id: str
    subject_type: str
    strategy_id: str
    decision: str
    explanation: str
    recent_change: str
    owner: str
    hit_rules: List[RuleHitResponse]


class FaultRuleRequest(BaseModel):
    target_path: str = Field(..., min_length=1)
    status_code: int = Field(default=503, ge=400, le=599)
    remaining: int = Field(default=1, ge=1, le=1000)
    delay_sec: float = Field(default=0.0, ge=0.0, le=30.0)


def create_risk_service_app(config: Optional[AppConfig] = None) -> FastAPI:
    config = config or AppConfig.from_env()
    metric_client = JsonMetricSnapshotSqlClient(config.metric_snapshot_path)
    case_client = JsonCaseRecordClient(config.case_record_path)
    order_client = JsonOrderProfileClient(config.order_profile_path)
    strategy_client = JsonStrategyProfileClient(config.strategy_profile_path)
    simulation_client = JsonStrategySimulationClient(config.strategy_simulation_path)
    graph_client = JsonGraphRelationClient(config.graph_relation_path)
    sql_query_client = JsonSqlQueryClient(config.sql_query_result_path)
    dashboard_client = JsonDashboardSnapshotClient(config.dashboard_snapshot_path)
    rule_explain_client = JsonRuleExplainClient(config.rule_explanation_path)
    fault_controller = FaultController()

    fastapi_app = FastAPI(
        title="AI Risk Mock Service",
        version="0.1.0",
        description="Mock risk data service for local HTTP backend integration.",
    )

    if config.risk_service_fault_injection_enabled:
        @fastapi_app.middleware("http")
        async def fault_injection_middleware(request: Request, call_next):
            rule = fault_controller.consume(request.url.path)
            if rule is None:
                return await call_next(request)
            if rule.delay_sec:
                await asyncio.sleep(rule.delay_sec)
            return JSONResponse(
                status_code=rule.status_code,
                content={
                    "detail": "Injected fault for recovery drill",
                    "target_path": rule.target_path,
                    "remaining": rule.remaining,
                },
                headers={"X-Fault-Injected": "true"},
            )

        @fastapi_app.get("/admin/faults")
        def list_faults() -> Dict[str, Any]:
            return {"faults": fault_controller.snapshot()}

        @fastapi_app.post("/admin/faults")
        def configure_fault(payload: FaultRuleRequest) -> Dict[str, Any]:
            if not payload.target_path.startswith("/"):
                raise HTTPException(status_code=400, detail="target_path must start with /")
            if payload.target_path.startswith("/admin/faults"):
                raise HTTPException(status_code=400, detail="cannot fault the control endpoint")
            rule = fault_controller.configure(
                FaultRule(
                    target_path=payload.target_path,
                    status_code=payload.status_code,
                    remaining=payload.remaining,
                    delay_sec=payload.delay_sec,
                )
            )
            return {"fault": rule.__dict__}

        @fastapi_app.delete("/admin/faults")
        def clear_faults() -> Dict[str, str]:
            fault_controller.clear()
            return {"status": "cleared"}

    @fastapi_app.get("/healthz")
    def healthz() -> Dict[str, str]:
        return {"status": "ok"}

    @fastapi_app.get("/metric-snapshots", response_model=MetricSnapshotResponse)
    def get_metric_snapshot(
        country: str = Query(..., min_length=2),
        channel: str = Query(..., min_length=2),
        time_range: str = Query("recent_24h", min_length=3),
    ) -> MetricSnapshotResponse:
        snapshot = metric_client.fetch_metric_snapshot(
            country=country,
            channel=channel,
            time_range=time_range,
        )
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Metric snapshot not found")
        return MetricSnapshotResponse(**snapshot)

    @fastapi_app.get("/case-records", response_model=List[CaseRecordResponse])
    def get_case_records(
        country: str = Query(..., min_length=2),
        channel: str = Query(..., min_length=2),
    ) -> List[CaseRecordResponse]:
        records = case_client.fetch_case_records(country=country, channel=channel)
        if not records:
            raise HTTPException(status_code=404, detail="Case records not found")
        return [CaseRecordResponse(**record) for record in records]

    @fastapi_app.get("/order-profiles/{order_id}", response_model=OrderProfileResponse)
    def get_order_profile(order_id: str) -> OrderProfileResponse:
        profile = order_client.fetch_order_profile(order_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Order profile not found")
        return OrderProfileResponse(**profile)

    @fastapi_app.get("/strategy-profiles/{strategy_id}", response_model=StrategyProfileResponse)
    def get_strategy_profile(strategy_id: str) -> StrategyProfileResponse:
        profile = strategy_client.fetch_strategy_profile(strategy_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Strategy profile not found")
        return StrategyProfileResponse(**profile)

    @fastapi_app.get(
        "/strategy-simulations/{strategy_id}",
        response_model=StrategySimulationResponse,
    )
    def get_strategy_simulation(strategy_id: str) -> StrategySimulationResponse:
        simulation = simulation_client.fetch_strategy_simulation(strategy_id)
        if simulation is None:
            raise HTTPException(status_code=404, detail="Strategy simulation not found")
        return StrategySimulationResponse(**simulation)

    @fastapi_app.get("/graph-relations/{entity_id}", response_model=GraphRelationResponse)
    def get_graph_relation(entity_id: str) -> GraphRelationResponse:
        relation = graph_client.fetch_graph_relation(entity_id.upper())
        if relation is None:
            raise HTTPException(status_code=404, detail="Graph relation not found")
        return GraphRelationResponse(**relation)

    @fastapi_app.get("/sql-queries/{query_name}", response_model=SqlQueryResponse)
    def get_sql_query(
        query_name: str,
        country: str = Query(..., min_length=2),
        channel: str = Query(..., min_length=2),
        time_range: str = Query("recent_24h", min_length=3),
        limit: int = Query(50, ge=1, le=500),
    ) -> SqlQueryResponse:
        result = sql_query_client.fetch_sql_query(
            query_name=query_name,
            parameters={
                "country": country.upper(),
                "channel": channel.lower(),
                "time_range": time_range,
            },
            limit=limit,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="SQL query result not found")
        return SqlQueryResponse(**result)

    @fastapi_app.get(
        "/dashboard-snapshots/{dashboard_id}",
        response_model=DashboardSnapshotResponse,
    )
    def get_dashboard_snapshot(
        dashboard_id: str,
        country: str = Query(..., min_length=2),
        channel: str = Query(..., min_length=2),
        time_range: str = Query("recent_24h", min_length=3),
    ) -> DashboardSnapshotResponse:
        snapshot = dashboard_client.fetch_dashboard_snapshot(
            dashboard_id=dashboard_id,
            country=country.upper(),
            channel=channel.lower(),
            time_range=time_range,
        )
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Dashboard snapshot not found")
        return DashboardSnapshotResponse(**snapshot)

    @fastapi_app.get("/rule-explanations", response_model=RuleExplanationResponse)
    def get_rule_explanation(
        rule_id: Optional[str] = Query(None),
        order_id: Optional[str] = Query(None),
        strategy_id: Optional[str] = Query(None),
    ) -> RuleExplanationResponse:
        if not any((rule_id, order_id, strategy_id)):
            raise HTTPException(
                status_code=400,
                detail="rule_id, order_id, or strategy_id is required",
            )
        explanation = rule_explain_client.fetch_rule_explanation(
            rule_id=rule_id,
            order_id=order_id,
            strategy_id=strategy_id,
        )
        if explanation is None:
            raise HTTPException(status_code=404, detail="Rule explanation not found")
        return RuleExplanationResponse(**explanation)

    return fastapi_app


risk_service_app = create_risk_service_app()
