from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


SUPPORTED_AGENT_CAPABILITIES = (
    "knowledge",
    "investigation",
    "strategy",
    "graph",
    "copilot",
)


CAPABILITY_DESCRIPTIONS = {
    "knowledge": "知识检索与 SOP/FAQ 问答能力。",
    "investigation": "基于指标、案例和订单画像的风险调查能力。",
    "strategy": "基于策略画像、仿真和图谱线索的策略分析能力。",
    "graph": "基于关系网络数据的团伙与关联分析能力。",
    "copilot": "编排 investigation、strategy、graph 的联合分析能力。",
}


CAPABILITY_REQUIRED_TOOLS = {
    "knowledge": (),
    "investigation": ("metric_snapshot", "case_lookup", "order_profile"),
    "strategy": ("strategy_profile", "strategy_simulation", "graph_relation"),
    "graph": ("graph_relation",),
    "copilot": (
        "metric_snapshot",
        "case_lookup",
        "order_profile",
        "strategy_profile",
        "strategy_simulation",
        "graph_relation",
    ),
}


CAPABILITY_COMPOSED_AGENTS = {
    "knowledge": (),
    "investigation": (),
    "strategy": (),
    "graph": (),
    "copilot": ("investigation", "strategy", "graph"),
}


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
    tool_http_retry_attempts: int = 2
    tool_http_retry_backoff_sec: float = 0.1
    tool_http_circuit_breaker_failure_threshold: int = 5
    tool_http_circuit_breaker_reset_sec: float = 30.0
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
    session_store_backend: str = "memory"
    session_store_path: Path = Path(".data/sessions.json")
    case_store_backend: str = "memory"
    case_store_path: Path = Path(".data/cases.json")
    database_path: Path = Path(".data/platform.db")
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
            tool_http_retry_attempts=int(
                os.getenv("AI_RISK_TOOL_HTTP_RETRY_ATTEMPTS", "2")
            ),
            tool_http_retry_backoff_sec=float(
                os.getenv("AI_RISK_TOOL_HTTP_RETRY_BACKOFF_SEC", "0.1")
            ),
            tool_http_circuit_breaker_failure_threshold=int(
                os.getenv(
                    "AI_RISK_TOOL_HTTP_CIRCUIT_BREAKER_FAILURE_THRESHOLD",
                    "5",
                )
            ),
            tool_http_circuit_breaker_reset_sec=float(
                os.getenv("AI_RISK_TOOL_HTTP_CIRCUIT_BREAKER_RESET_SEC", "30.0")
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
            session_store_backend=os.getenv(
                "AI_RISK_SESSION_STORE_BACKEND",
                "memory",
            ),
            session_store_path=Path(
                os.getenv("AI_RISK_SESSION_STORE_PATH", ".data/sessions.json")
            ),
            case_store_backend=os.getenv(
                "AI_RISK_CASE_STORE_BACKEND",
                "memory",
            ),
            case_store_path=Path(
                os.getenv("AI_RISK_CASE_STORE_PATH", ".data/cases.json")
            ),
            database_path=Path(
                os.getenv("AI_RISK_DATABASE_PATH", ".data/platform.db")
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
            tool_http_retry_attempts=2,
            tool_http_retry_backoff_sec=0.1,
            tool_http_circuit_breaker_failure_threshold=5,
            tool_http_circuit_breaker_reset_sec=30.0,
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
            session_store_backend="memory",
            session_store_path=Path(".data/sessions.json"),
            case_store_backend="memory",
            case_store_path=Path(".data/cases.json"),
            database_path=Path(".data/platform.db"),
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

    def supported_agent_capabilities(self) -> list[str]:
        return list(SUPPORTED_AGENT_CAPABILITIES)

    def capability_contract(self) -> list[Dict[str, Any]]:
        contract: list[Dict[str, Any]] = []
        for capability in SUPPORTED_AGENT_CAPABILITIES:
            contract.append(
                {
                    "name": capability,
                    "description": CAPABILITY_DESCRIPTIONS[capability],
                    "knowledge_required": capability in {"knowledge", "investigation", "strategy", "graph"},
                    "required_tools": list(CAPABILITY_REQUIRED_TOOLS[capability]),
                    "composed_agents": list(CAPABILITY_COMPOSED_AGENTS[capability]),
                }
            )
        return contract

    def http_endpoint_contract(self) -> list[Dict[str, Any]]:
        return [
            {
                "tool_name": "metric_snapshot",
                "path_env_var": "AI_RISK_TOOL_HTTP_METRIC_PATH",
                "path": self.tool_http_metric_path,
                "supports_capabilities": ["investigation", "copilot"],
                "query_params": {
                    "country_env_var": "AI_RISK_TOOL_HTTP_COUNTRY_PARAM",
                    "country_name": self.tool_http_country_param,
                    "channel_env_var": "AI_RISK_TOOL_HTTP_CHANNEL_PARAM",
                    "channel_name": self.tool_http_channel_param,
                },
            },
            {
                "tool_name": "case_lookup",
                "path_env_var": "AI_RISK_TOOL_HTTP_CASE_PATH",
                "path": self.tool_http_case_path,
                "supports_capabilities": ["investigation", "copilot"],
                "query_params": {
                    "country_env_var": "AI_RISK_TOOL_HTTP_COUNTRY_PARAM",
                    "country_name": self.tool_http_country_param,
                    "channel_env_var": "AI_RISK_TOOL_HTTP_CHANNEL_PARAM",
                    "channel_name": self.tool_http_channel_param,
                },
            },
            {
                "tool_name": "order_profile",
                "path_env_var": "AI_RISK_TOOL_HTTP_ORDER_PATH_TEMPLATE",
                "path": self.tool_http_order_path_template,
                "supports_capabilities": ["investigation", "copilot"],
                "query_params": {},
            },
            {
                "tool_name": "strategy_profile",
                "path_env_var": "AI_RISK_TOOL_HTTP_STRATEGY_PROFILE_PATH_TEMPLATE",
                "path": self.tool_http_strategy_profile_path_template,
                "supports_capabilities": ["strategy", "copilot"],
                "query_params": {},
            },
            {
                "tool_name": "strategy_simulation",
                "path_env_var": "AI_RISK_TOOL_HTTP_STRATEGY_SIMULATION_PATH_TEMPLATE",
                "path": self.tool_http_strategy_simulation_path_template,
                "supports_capabilities": ["strategy", "copilot"],
                "query_params": {},
            },
            {
                "tool_name": "graph_relation",
                "path_env_var": "AI_RISK_TOOL_HTTP_GRAPH_RELATION_PATH_TEMPLATE",
                "path": self.tool_http_graph_relation_path_template,
                "supports_capabilities": ["strategy", "graph", "copilot"],
                "query_params": {},
            },
        ]
