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
        )

