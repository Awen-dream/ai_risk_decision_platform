from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


@dataclass
class AppConfig:
    knowledge_backend: str = "mock"
    tool_backend: str = "mock"
    knowledge_dir: Path = Path("data/knowledge")
    metric_snapshot_path: Path = Path("data/risk/metric_snapshots.json")
    case_record_path: Path = Path("data/risk/case_records.json")
    order_profile_path: Path = Path("data/risk/order_profiles.json")
    strategy_profile_path: Path = Path("data/risk/strategy_profiles.json")
    strategy_simulation_path: Path = Path("data/risk/strategy_simulations.json")
    graph_relation_path: Path = Path("data/risk/graph_relations.json")
    tool_http_base_url: str = "http://127.0.0.1:8090"
    tool_http_timeout_sec: float = 5.0
    tool_http_auth_mode: str = "none"
    tool_http_auth_token: str = ""
    tool_http_auth_header: str = "Authorization"
    tool_http_metric_path: str = "/metric-snapshots"
    tool_http_case_path: str = "/case-records"
    tool_http_order_path_template: str = "/order-profiles/{order_id}"
    tool_http_strategy_profile_path_template: str = "/strategy-profiles/{strategy_id}"
    tool_http_strategy_simulation_path_template: str = "/strategy-simulations/{strategy_id}"
    tool_http_graph_relation_path_template: str = "/graph-relations/{entity_id}"
    tool_http_country_param: str = "country"
    tool_http_channel_param: str = "channel"
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
            strategy_profile_path=Path(
                os.getenv("AI_RISK_STRATEGY_PROFILE_PATH", "data/risk/strategy_profiles.json")
            ),
            strategy_simulation_path=Path(
                os.getenv(
                    "AI_RISK_STRATEGY_SIMULATION_PATH",
                    "data/risk/strategy_simulations.json",
                )
            ),
            graph_relation_path=Path(
                os.getenv("AI_RISK_GRAPH_RELATION_PATH", "data/risk/graph_relations.json")
            ),
            tool_http_base_url=os.getenv(
                "AI_RISK_TOOL_HTTP_BASE_URL",
                "http://127.0.0.1:8090",
            ),
            tool_http_timeout_sec=float(
                os.getenv("AI_RISK_TOOL_HTTP_TIMEOUT_SEC", "5.0")
            ),
            tool_http_auth_mode=os.getenv("AI_RISK_TOOL_HTTP_AUTH_MODE", "none"),
            tool_http_auth_token=os.getenv("AI_RISK_TOOL_HTTP_AUTH_TOKEN", ""),
            tool_http_auth_header=os.getenv(
                "AI_RISK_TOOL_HTTP_AUTH_HEADER",
                "Authorization",
            ),
            tool_http_metric_path=os.getenv(
                "AI_RISK_TOOL_HTTP_METRIC_PATH",
                "/metric-snapshots",
            ),
            tool_http_case_path=os.getenv(
                "AI_RISK_TOOL_HTTP_CASE_PATH",
                "/case-records",
            ),
            tool_http_order_path_template=os.getenv(
                "AI_RISK_TOOL_HTTP_ORDER_PATH_TEMPLATE",
                "/order-profiles/{order_id}",
            ),
            tool_http_strategy_profile_path_template=os.getenv(
                "AI_RISK_TOOL_HTTP_STRATEGY_PROFILE_PATH_TEMPLATE",
                "/strategy-profiles/{strategy_id}",
            ),
            tool_http_strategy_simulation_path_template=os.getenv(
                "AI_RISK_TOOL_HTTP_STRATEGY_SIMULATION_PATH_TEMPLATE",
                "/strategy-simulations/{strategy_id}",
            ),
            tool_http_graph_relation_path_template=os.getenv(
                "AI_RISK_TOOL_HTTP_GRAPH_RELATION_PATH_TEMPLATE",
                "/graph-relations/{entity_id}",
            ),
            tool_http_country_param=os.getenv(
                "AI_RISK_TOOL_HTTP_COUNTRY_PARAM",
                "country",
            ),
            tool_http_channel_param=os.getenv(
                "AI_RISK_TOOL_HTTP_CHANNEL_PARAM",
                "channel",
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
            strategy_profile_path=Path("data/risk/strategy_profiles.json"),
            strategy_simulation_path=Path("data/risk/strategy_simulations.json"),
            graph_relation_path=Path("data/risk/graph_relations.json"),
            tool_http_base_url="http://127.0.0.1:8090",
            tool_http_timeout_sec=5.0,
            tool_http_auth_mode="none",
            tool_http_auth_token="",
            tool_http_auth_header="Authorization",
            tool_http_metric_path="/metric-snapshots",
            tool_http_case_path="/case-records",
            tool_http_order_path_template="/order-profiles/{order_id}",
            tool_http_strategy_profile_path_template="/strategy-profiles/{strategy_id}",
            tool_http_strategy_simulation_path_template="/strategy-simulations/{strategy_id}",
            tool_http_graph_relation_path_template="/graph-relations/{entity_id}",
            tool_http_country_param="country",
            tool_http_channel_param="channel",
            api_host="127.0.0.1",
            api_port=8000,
            risk_service_host="127.0.0.1",
            risk_service_port=8090,
        )

    def tool_http_headers(self) -> Dict[str, str]:
        if self.tool_http_auth_mode == "bearer" and self.tool_http_auth_token:
            return {self.tool_http_auth_header: f"Bearer {self.tool_http_auth_token}"}
        if self.tool_http_auth_mode == "api_key" and self.tool_http_auth_token:
            return {self.tool_http_auth_header: self.tool_http_auth_token}
        return {}
