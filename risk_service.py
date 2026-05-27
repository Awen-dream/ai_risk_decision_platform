from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from clients.file import JsonCaseRecordClient, JsonMetricSnapshotSqlClient, JsonOrderProfileClient
from settings import AppConfig


class MetricSnapshotResponse(BaseModel):
    country: str
    channel: str
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


def create_risk_service_app(config: Optional[AppConfig] = None) -> FastAPI:
    config = config or AppConfig.from_env()
    metric_client = JsonMetricSnapshotSqlClient(config.metric_snapshot_path)
    case_client = JsonCaseRecordClient(config.case_record_path)
    order_client = JsonOrderProfileClient(config.order_profile_path)

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
    ) -> MetricSnapshotResponse:
        snapshot = metric_client.fetch_metric_snapshot(country=country, channel=channel)
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

    return fastapi_app


risk_service_app = create_risk_service_app()
