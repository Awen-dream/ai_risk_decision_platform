from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from clients.file import (
    JsonCaseRecordClient,
    JsonGraphRelationClient,
    JsonMetricSnapshotSqlClient,
    JsonOrderProfileClient,
    JsonStrategyProfileClient,
    JsonStrategySimulationClient,
)
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


def create_risk_service_app(config: Optional[AppConfig] = None) -> FastAPI:
    config = config or AppConfig.from_env()
    metric_client = JsonMetricSnapshotSqlClient(config.metric_snapshot_path)
    case_client = JsonCaseRecordClient(config.case_record_path)
    order_client = JsonOrderProfileClient(config.order_profile_path)
    strategy_client = JsonStrategyProfileClient(config.strategy_profile_path)
    simulation_client = JsonStrategySimulationClient(config.strategy_simulation_path)
    graph_client = JsonGraphRelationClient(config.graph_relation_path)

    fastapi_app = FastAPI(
        title="AI Risk Mock Service",
        version="0.1.0",
        description="Mock risk data service for local HTTP backend integration.",
    )

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

    return fastapi_app


risk_service_app = create_risk_service_app()
