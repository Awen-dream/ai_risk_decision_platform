from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppConfig:
    knowledge_backend: str = "mock"
    tool_backend: str = "mock"
    knowledge_dir: Path = Path("data/knowledge")
    metric_snapshot_path: Path = Path("data/risk/metric_snapshots.json")
    case_record_path: Path = Path("data/risk/case_records.json")
    order_profile_path: Path = Path("data/risk/order_profiles.json")
    tool_http_base_url: str = "http://127.0.0.1:8090"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    risk_service_host: str = "127.0.0.1"
    risk_service_port: int = 8090

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            knowledge_backend=os.getenv("AI_RISK_KNOWLEDGE_BACKEND", "mock"),
            tool_backend=os.getenv("AI_RISK_TOOL_BACKEND", "mock"),
            knowledge_dir=Path(os.getenv("AI_RISK_KNOWLEDGE_DIR", "data/knowledge")),
            metric_snapshot_path=Path(
                os.getenv("AI_RISK_METRIC_SNAPSHOT_PATH", "data/risk/metric_snapshots.json")
            ),
            case_record_path=Path(
                os.getenv("AI_RISK_CASE_RECORD_PATH", "data/risk/case_records.json")
            ),
            order_profile_path=Path(
                os.getenv("AI_RISK_ORDER_PROFILE_PATH", "data/risk/order_profiles.json")
            ),
            tool_http_base_url=os.getenv(
                "AI_RISK_TOOL_HTTP_BASE_URL",
                "http://127.0.0.1:8090",
            ),
            api_host=os.getenv("AI_RISK_API_HOST", "127.0.0.1"),
            api_port=int(os.getenv("AI_RISK_API_PORT", "8000")),
            risk_service_host=os.getenv("AI_RISK_RISK_SERVICE_HOST", "127.0.0.1"),
            risk_service_port=int(os.getenv("AI_RISK_RISK_SERVICE_PORT", "8090")),
        )

    @classmethod
    def local_http_stack(cls) -> "AppConfig":
        return cls(
            knowledge_backend="file",
            tool_backend="http",
            knowledge_dir=Path("data/knowledge"),
            metric_snapshot_path=Path("data/risk/metric_snapshots.json"),
            case_record_path=Path("data/risk/case_records.json"),
            order_profile_path=Path("data/risk/order_profiles.json"),
            tool_http_base_url="http://127.0.0.1:8090",
            api_host="127.0.0.1",
            api_port=8000,
            risk_service_host="127.0.0.1",
            risk_service_port=8090,
        )
