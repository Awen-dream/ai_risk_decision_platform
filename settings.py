from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str) -> Optional[Path]:
    value = os.getenv(name)
    if not value:
        return None
    return Path(value)


def _load_secret(value: str, file_path: Optional[Path]) -> str:
    if file_path is None:
        return value
    return file_path.read_text(encoding="utf-8").strip()


SUPPORTED_AGENT_CAPABILITIES = (
    "knowledge",
    "investigation",
    "strategy",
    "graph",
    "root_cause",
    "copilot",
)


CAPABILITY_DESCRIPTIONS = {
    "knowledge": "知识检索与 SOP/FAQ 问答能力。",
    "investigation": "基于指标、案例和订单画像的风险调查能力。",
    "strategy": "基于策略画像、仿真和图谱线索的策略分析能力。",
    "graph": "基于关系网络数据的团伙与关联分析能力。",
    "root_cause": "基于指标、看板、SQL 和规则解释的显式根因候选验证与排序能力。",
    "copilot": "编排 investigation、strategy、graph 的联合分析能力。",
}


CAPABILITY_REQUIRED_TOOLS = {
    "knowledge": (),
    "investigation": (
        "metric_snapshot",
        "case_lookup",
        "order_profile",
        "sql_query",
        "dashboard_snapshot",
        "rule_explain",
    ),
    "strategy": (
        "strategy_profile",
        "strategy_simulation",
        "graph_relation",
        "rule_explain",
    ),
    "graph": ("graph_relation",),
    "root_cause": (
        "metric_snapshot",
        "dashboard_snapshot",
        "sql_query",
        "rule_explain",
    ),
    "copilot": (
        "metric_snapshot",
        "case_lookup",
        "order_profile",
        "strategy_profile",
        "strategy_simulation",
        "graph_relation",
        "sql_query",
        "dashboard_snapshot",
        "rule_explain",
    ),
}


CAPABILITY_COMPOSED_AGENTS = {
    "knowledge": (),
    "investigation": (),
    "strategy": (),
    "graph": (),
    "root_cause": (),
    "copilot": ("investigation", "strategy", "graph"),
}


@dataclass
class AppConfig:
    knowledge_backend: str = "mock"
    tool_backend: str = "mock"
    planner_backend: str = "rule"
    planner_openai_base_url: str = "https://api.openai.com/v1"
    planner_openai_model: str = "gpt-4o-mini"
    planner_openai_timeout_sec: float = 10.0
    planner_openai_reasoning_effort: str = "low"
    planner_openai_max_output_tokens: int = 400
    planner_openai_api_key: str = ""
    planner_openai_api_key_file: Optional[Path] = None
    investigation_backend: str = "rule"
    investigation_openai_base_url: str = "https://api.openai.com/v1"
    investigation_openai_model: str = "gpt-4o-mini"
    investigation_openai_timeout_sec: float = 10.0
    investigation_openai_reasoning_effort: str = "low"
    investigation_openai_max_output_tokens: int = 400
    investigation_openai_api_key: str = ""
    investigation_openai_api_key_file: Optional[Path] = None
    strategy_backend: str = "rule"
    strategy_openai_base_url: str = "https://api.openai.com/v1"
    strategy_openai_model: str = "gpt-4o-mini"
    strategy_openai_timeout_sec: float = 10.0
    strategy_openai_reasoning_effort: str = "low"
    strategy_openai_max_output_tokens: int = 400
    strategy_openai_api_key: str = ""
    strategy_openai_api_key_file: Optional[Path] = None
    graph_backend: str = "rule"
    graph_openai_base_url: str = "https://api.openai.com/v1"
    graph_openai_model: str = "gpt-4o-mini"
    graph_openai_timeout_sec: float = 10.0
    graph_openai_reasoning_effort: str = "low"
    graph_openai_max_output_tokens: int = 300
    graph_openai_api_key: str = ""
    graph_openai_api_key_file: Optional[Path] = None
    knowledge_dir: Path = Path("data/knowledge")
    metric_snapshot_path: Path = Path("data/risk/metric_snapshots.json")
    case_record_path: Path = Path("data/risk/case_records.json")
    order_profile_path: Path = Path("data/risk/order_profiles.json")
    strategy_profile_path: Path = Path("data/risk/strategy_profiles.json")
    strategy_simulation_path: Path = Path("data/risk/strategy_simulations.json")
    graph_relation_path: Path = Path("data/risk/graph_relations.json")
    sql_query_result_path: Path = Path("data/risk/sql_query_results.json")
    dashboard_snapshot_path: Path = Path("data/risk/dashboard_snapshots.json")
    rule_explanation_path: Path = Path("data/risk/rule_explanations.json")
    tool_http_base_url: str = "http://127.0.0.1:8090"
    tool_http_timeout_sec: float = 5.0
    tool_http_retry_attempts: int = 2
    tool_http_retry_backoff_sec: float = 0.1
    tool_http_circuit_breaker_failure_threshold: int = 5
    tool_http_circuit_breaker_reset_sec: float = 30.0
    tool_http_auth_mode: str = "none"
    tool_http_auth_token: str = ""
    tool_http_auth_token_file: Optional[Path] = None
    tool_http_auth_header: str = "Authorization"
    tool_http_audit_enabled: bool = True
    tool_http_audit_path: Path = Path(".data/upstream-audit.jsonl")
    tool_http_audit_max_bytes: int = 10 * 1024 * 1024
    tool_http_audit_max_files: int = 5
    tool_http_audit_integrity_enabled: bool = True
    audit_central_enabled: bool = False
    audit_central_url: str = ""
    audit_central_timeout_sec: float = 3.0
    audit_central_auth_header: str = "Authorization"
    audit_central_auth_token: str = ""
    audit_central_auth_token_file: Optional[Path] = None
    handoff_ticket_base_url: str = "https://handoff.local/tickets"
    handoff_ticket_path: str = "/projects/{project_key}/cases"
    handoff_ticket_project_key: str = "risk-ops"
    handoff_ticket_auth_header: str = "Authorization"
    handoff_ticket_auth_token: str = ""
    handoff_ticket_auth_token_file: Optional[Path] = None
    handoff_webhook_base_url: str = "https://handoff.local/webhooks"
    handoff_webhook_auth_header: str = "Authorization"
    handoff_webhook_auth_token: str = ""
    handoff_webhook_auth_token_file: Optional[Path] = None
    handoff_publish_timeout_sec: float = 5.0
    handoff_publish_retry_attempts: int = 1
    handoff_publish_retry_backoff_sec: float = 0.1
    handoff_ticket_max_attempts: int = 3
    handoff_ticket_retry_cooldown_sec: float = 0.0
    handoff_webhook_max_attempts: int = 3
    handoff_webhook_retry_cooldown_sec: float = 0.0
    handoff_retry_sweep_limit: int = 50
    tool_http_metric_path: str = "/metric-snapshots"
    tool_http_case_path: str = "/case-records"
    tool_http_order_path_template: str = "/order-profiles/{order_id}"
    tool_http_strategy_profile_path_template: str = "/strategy-profiles/{strategy_id}"
    tool_http_strategy_simulation_path_template: str = "/strategy-simulations/{strategy_id}"
    tool_http_graph_relation_path_template: str = "/graph-relations/{entity_id}"
    tool_http_sql_query_path_template: str = "/sql-queries/{query_name}"
    tool_http_dashboard_snapshot_path_template: str = "/dashboard-snapshots/{dashboard_id}"
    tool_http_rule_explain_path: str = "/rule-explanations"
    tool_http_country_param: str = "country"
    tool_http_channel_param: str = "channel"
    session_store_backend: str = "memory"
    session_store_path: Path = Path(".data/sessions.json")
    case_store_backend: str = "memory"
    case_store_path: Path = Path(".data/cases.json")
    database_path: Path = Path(".data/platform.db")
    postgres_dsn: str = ""
    postgres_dsn_file: Optional[Path] = None
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    risk_service_host: str = "127.0.0.1"
    risk_service_port: int = 8090
    risk_service_fault_injection_enabled: bool = False
    risk_decision_policy_path: Optional[Path] = None
    admin_auth_enabled: bool = False
    admin_auth_header: str = "X-Admin-Token"
    admin_auth_token: str = ""
    admin_auth_token_file: Optional[Path] = None

    @classmethod
    def from_env(cls) -> "AppConfig":
        tool_http_auth_token_file = _env_path("AI_RISK_TOOL_HTTP_AUTH_TOKEN_FILE")
        admin_auth_token_file = _env_path("AI_RISK_ADMIN_AUTH_TOKEN_FILE")
        audit_central_auth_token_file = _env_path("AI_RISK_AUDIT_CENTRAL_AUTH_TOKEN_FILE")
        handoff_ticket_auth_token_file = _env_path("AI_RISK_HANDOFF_TICKET_AUTH_TOKEN_FILE")
        handoff_webhook_auth_token_file = _env_path("AI_RISK_HANDOFF_WEBHOOK_AUTH_TOKEN_FILE")
        postgres_dsn_file = _env_path("AI_RISK_POSTGRES_DSN_FILE")
        planner_openai_api_key_file = _env_path("AI_RISK_PLANNER_OPENAI_API_KEY_FILE")
        investigation_openai_api_key_file = _env_path("AI_RISK_INVESTIGATION_OPENAI_API_KEY_FILE")
        strategy_openai_api_key_file = _env_path("AI_RISK_STRATEGY_OPENAI_API_KEY_FILE")
        graph_openai_api_key_file = _env_path("AI_RISK_GRAPH_OPENAI_API_KEY_FILE")
        return cls(
            knowledge_backend=os.getenv("AI_RISK_KNOWLEDGE_BACKEND", "mock"),
            tool_backend=os.getenv("AI_RISK_TOOL_BACKEND", "mock"),
            planner_backend=os.getenv("AI_RISK_PLANNER_BACKEND", "rule"),
            planner_openai_base_url=os.getenv(
                "AI_RISK_PLANNER_OPENAI_BASE_URL",
                "https://api.openai.com/v1",
            ),
            planner_openai_model=os.getenv(
                "AI_RISK_PLANNER_OPENAI_MODEL",
                "gpt-4o-mini",
            ),
            planner_openai_timeout_sec=float(
                os.getenv("AI_RISK_PLANNER_OPENAI_TIMEOUT_SEC", "10.0")
            ),
            planner_openai_reasoning_effort=os.getenv(
                "AI_RISK_PLANNER_OPENAI_REASONING_EFFORT",
                "low",
            ),
            planner_openai_max_output_tokens=int(
                os.getenv("AI_RISK_PLANNER_OPENAI_MAX_OUTPUT_TOKENS", "400")
            ),
            planner_openai_api_key=_load_secret(
                os.getenv("AI_RISK_PLANNER_OPENAI_API_KEY", ""),
                planner_openai_api_key_file,
            ),
            planner_openai_api_key_file=planner_openai_api_key_file,
            investigation_backend=os.getenv("AI_RISK_INVESTIGATION_BACKEND", "rule"),
            investigation_openai_base_url=os.getenv(
                "AI_RISK_INVESTIGATION_OPENAI_BASE_URL",
                "https://api.openai.com/v1",
            ),
            investigation_openai_model=os.getenv(
                "AI_RISK_INVESTIGATION_OPENAI_MODEL",
                "gpt-4o-mini",
            ),
            investigation_openai_timeout_sec=float(
                os.getenv("AI_RISK_INVESTIGATION_OPENAI_TIMEOUT_SEC", "10.0")
            ),
            investigation_openai_reasoning_effort=os.getenv(
                "AI_RISK_INVESTIGATION_OPENAI_REASONING_EFFORT",
                "low",
            ),
            investigation_openai_max_output_tokens=int(
                os.getenv("AI_RISK_INVESTIGATION_OPENAI_MAX_OUTPUT_TOKENS", "400")
            ),
            investigation_openai_api_key=_load_secret(
                os.getenv("AI_RISK_INVESTIGATION_OPENAI_API_KEY", ""),
                investigation_openai_api_key_file,
            ),
            investigation_openai_api_key_file=investigation_openai_api_key_file,
            strategy_backend=os.getenv("AI_RISK_STRATEGY_BACKEND", "rule"),
            strategy_openai_base_url=os.getenv(
                "AI_RISK_STRATEGY_OPENAI_BASE_URL",
                "https://api.openai.com/v1",
            ),
            strategy_openai_model=os.getenv(
                "AI_RISK_STRATEGY_OPENAI_MODEL",
                "gpt-4o-mini",
            ),
            strategy_openai_timeout_sec=float(
                os.getenv("AI_RISK_STRATEGY_OPENAI_TIMEOUT_SEC", "10.0")
            ),
            strategy_openai_reasoning_effort=os.getenv(
                "AI_RISK_STRATEGY_OPENAI_REASONING_EFFORT",
                "low",
            ),
            strategy_openai_max_output_tokens=int(
                os.getenv("AI_RISK_STRATEGY_OPENAI_MAX_OUTPUT_TOKENS", "400")
            ),
            strategy_openai_api_key=_load_secret(
                os.getenv("AI_RISK_STRATEGY_OPENAI_API_KEY", ""),
                strategy_openai_api_key_file,
            ),
            strategy_openai_api_key_file=strategy_openai_api_key_file,
            graph_backend=os.getenv("AI_RISK_GRAPH_BACKEND", "rule"),
            graph_openai_base_url=os.getenv(
                "AI_RISK_GRAPH_OPENAI_BASE_URL",
                "https://api.openai.com/v1",
            ),
            graph_openai_model=os.getenv(
                "AI_RISK_GRAPH_OPENAI_MODEL",
                "gpt-4o-mini",
            ),
            graph_openai_timeout_sec=float(
                os.getenv("AI_RISK_GRAPH_OPENAI_TIMEOUT_SEC", "10.0")
            ),
            graph_openai_reasoning_effort=os.getenv(
                "AI_RISK_GRAPH_OPENAI_REASONING_EFFORT",
                "low",
            ),
            graph_openai_max_output_tokens=int(
                os.getenv("AI_RISK_GRAPH_OPENAI_MAX_OUTPUT_TOKENS", "300")
            ),
            graph_openai_api_key=_load_secret(
                os.getenv("AI_RISK_GRAPH_OPENAI_API_KEY", ""),
                graph_openai_api_key_file,
            ),
            graph_openai_api_key_file=graph_openai_api_key_file,
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
            sql_query_result_path=Path(
                os.getenv("AI_RISK_SQL_QUERY_RESULT_PATH", "data/risk/sql_query_results.json")
            ),
            dashboard_snapshot_path=Path(
                os.getenv("AI_RISK_DASHBOARD_SNAPSHOT_PATH", "data/risk/dashboard_snapshots.json")
            ),
            rule_explanation_path=Path(
                os.getenv("AI_RISK_RULE_EXPLANATION_PATH", "data/risk/rule_explanations.json")
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
            tool_http_auth_token=_load_secret(
                os.getenv("AI_RISK_TOOL_HTTP_AUTH_TOKEN", ""),
                tool_http_auth_token_file,
            ),
            tool_http_auth_token_file=tool_http_auth_token_file,
            tool_http_auth_header=os.getenv(
                "AI_RISK_TOOL_HTTP_AUTH_HEADER",
                "Authorization",
            ),
            tool_http_audit_enabled=_env_bool(
                "AI_RISK_TOOL_HTTP_AUDIT_ENABLED",
                True,
            ),
            tool_http_audit_path=Path(
                os.getenv(
                    "AI_RISK_TOOL_HTTP_AUDIT_PATH",
                    ".data/upstream-audit.jsonl",
                )
            ),
            tool_http_audit_max_bytes=int(
                os.getenv("AI_RISK_TOOL_HTTP_AUDIT_MAX_BYTES", str(10 * 1024 * 1024))
            ),
            tool_http_audit_max_files=int(
                os.getenv("AI_RISK_TOOL_HTTP_AUDIT_MAX_FILES", "5")
            ),
            tool_http_audit_integrity_enabled=_env_bool(
                "AI_RISK_TOOL_HTTP_AUDIT_INTEGRITY_ENABLED",
                True,
            ),
            audit_central_enabled=_env_bool("AI_RISK_AUDIT_CENTRAL_ENABLED", False),
            audit_central_url=os.getenv("AI_RISK_AUDIT_CENTRAL_URL", ""),
            audit_central_timeout_sec=float(
                os.getenv("AI_RISK_AUDIT_CENTRAL_TIMEOUT_SEC", "3.0")
            ),
            audit_central_auth_header=os.getenv(
                "AI_RISK_AUDIT_CENTRAL_AUTH_HEADER",
                "Authorization",
            ),
            audit_central_auth_token=_load_secret(
                os.getenv("AI_RISK_AUDIT_CENTRAL_AUTH_TOKEN", ""),
                audit_central_auth_token_file,
            ),
            audit_central_auth_token_file=audit_central_auth_token_file,
            handoff_ticket_base_url=os.getenv(
                "AI_RISK_HANDOFF_TICKET_BASE_URL",
                "https://handoff.local/tickets",
            ),
            handoff_ticket_path=os.getenv(
                "AI_RISK_HANDOFF_TICKET_PATH",
                "/projects/{project_key}/cases",
            ),
            handoff_ticket_project_key=os.getenv(
                "AI_RISK_HANDOFF_TICKET_PROJECT_KEY",
                "risk-ops",
            ),
            handoff_ticket_auth_header=os.getenv(
                "AI_RISK_HANDOFF_TICKET_AUTH_HEADER",
                "Authorization",
            ),
            handoff_ticket_auth_token=_load_secret(
                os.getenv("AI_RISK_HANDOFF_TICKET_AUTH_TOKEN", ""),
                handoff_ticket_auth_token_file,
            ),
            handoff_ticket_auth_token_file=handoff_ticket_auth_token_file,
            handoff_webhook_base_url=os.getenv(
                "AI_RISK_HANDOFF_WEBHOOK_BASE_URL",
                "https://handoff.local/webhooks",
            ),
            handoff_webhook_auth_header=os.getenv(
                "AI_RISK_HANDOFF_WEBHOOK_AUTH_HEADER",
                "Authorization",
            ),
            handoff_webhook_auth_token=_load_secret(
                os.getenv("AI_RISK_HANDOFF_WEBHOOK_AUTH_TOKEN", ""),
                handoff_webhook_auth_token_file,
            ),
            handoff_webhook_auth_token_file=handoff_webhook_auth_token_file,
            handoff_publish_timeout_sec=float(
                os.getenv("AI_RISK_HANDOFF_PUBLISH_TIMEOUT_SEC", "5.0")
            ),
            handoff_publish_retry_attempts=int(
                os.getenv("AI_RISK_HANDOFF_PUBLISH_RETRY_ATTEMPTS", "1")
            ),
            handoff_publish_retry_backoff_sec=float(
                os.getenv("AI_RISK_HANDOFF_PUBLISH_RETRY_BACKOFF_SEC", "0.1")
            ),
            handoff_ticket_max_attempts=int(
                os.getenv("AI_RISK_HANDOFF_TICKET_MAX_ATTEMPTS", "3")
            ),
            handoff_ticket_retry_cooldown_sec=float(
                os.getenv("AI_RISK_HANDOFF_TICKET_RETRY_COOLDOWN_SEC", "0.0")
            ),
            handoff_webhook_max_attempts=int(
                os.getenv("AI_RISK_HANDOFF_WEBHOOK_MAX_ATTEMPTS", "3")
            ),
            handoff_webhook_retry_cooldown_sec=float(
                os.getenv("AI_RISK_HANDOFF_WEBHOOK_RETRY_COOLDOWN_SEC", "0.0")
            ),
            handoff_retry_sweep_limit=int(
                os.getenv("AI_RISK_HANDOFF_RETRY_SWEEP_LIMIT", "50")
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
            tool_http_sql_query_path_template=os.getenv(
                "AI_RISK_TOOL_HTTP_SQL_QUERY_PATH_TEMPLATE",
                "/sql-queries/{query_name}",
            ),
            tool_http_dashboard_snapshot_path_template=os.getenv(
                "AI_RISK_TOOL_HTTP_DASHBOARD_SNAPSHOT_PATH_TEMPLATE",
                "/dashboard-snapshots/{dashboard_id}",
            ),
            tool_http_rule_explain_path=os.getenv(
                "AI_RISK_TOOL_HTTP_RULE_EXPLAIN_PATH",
                "/rule-explanations",
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
            postgres_dsn=_load_secret(
                os.getenv("AI_RISK_POSTGRES_DSN", ""),
                postgres_dsn_file,
            ),
            postgres_dsn_file=postgres_dsn_file,
            api_host=os.getenv("AI_RISK_API_HOST", "127.0.0.1"),
            api_port=int(os.getenv("AI_RISK_API_PORT", "8000")),
            risk_service_host=os.getenv("AI_RISK_RISK_SERVICE_HOST", "127.0.0.1"),
            risk_service_port=int(os.getenv("AI_RISK_RISK_SERVICE_PORT", "8090")),
            risk_service_fault_injection_enabled=_env_bool(
                "AI_RISK_RISK_SERVICE_FAULT_INJECTION_ENABLED",
                False,
            ),
            risk_decision_policy_path=_env_path("AI_RISK_DECISION_POLICY_PATH"),
            admin_auth_enabled=_env_bool("AI_RISK_ADMIN_AUTH_ENABLED", False),
            admin_auth_header=os.getenv("AI_RISK_ADMIN_AUTH_HEADER", "X-Admin-Token"),
            admin_auth_token=_load_secret(
                os.getenv("AI_RISK_ADMIN_AUTH_TOKEN", ""),
                admin_auth_token_file,
            ),
            admin_auth_token_file=admin_auth_token_file,
        )

    @classmethod
    def local_http_stack(cls) -> "AppConfig":
        return cls(
            knowledge_backend="file",
            tool_backend="http",
            planner_backend="rule",
            planner_openai_base_url="https://api.openai.com/v1",
            planner_openai_model="gpt-4o-mini",
            planner_openai_timeout_sec=10.0,
            planner_openai_reasoning_effort="low",
            planner_openai_max_output_tokens=400,
            planner_openai_api_key="",
            planner_openai_api_key_file=None,
            investigation_backend="rule",
            investigation_openai_base_url="https://api.openai.com/v1",
            investigation_openai_model="gpt-4o-mini",
            investigation_openai_timeout_sec=10.0,
            investigation_openai_reasoning_effort="low",
            investigation_openai_max_output_tokens=400,
            investigation_openai_api_key="",
            investigation_openai_api_key_file=None,
            strategy_backend="rule",
            strategy_openai_base_url="https://api.openai.com/v1",
            strategy_openai_model="gpt-4o-mini",
            strategy_openai_timeout_sec=10.0,
            strategy_openai_reasoning_effort="low",
            strategy_openai_max_output_tokens=400,
            strategy_openai_api_key="",
            strategy_openai_api_key_file=None,
            graph_backend="rule",
            graph_openai_base_url="https://api.openai.com/v1",
            graph_openai_model="gpt-4o-mini",
            graph_openai_timeout_sec=10.0,
            graph_openai_reasoning_effort="low",
            graph_openai_max_output_tokens=300,
            graph_openai_api_key="",
            graph_openai_api_key_file=None,
            knowledge_dir=Path("data/knowledge"),
            metric_snapshot_path=Path("data/risk/metric_snapshots.json"),
            case_record_path=Path("data/risk/case_records.json"),
            order_profile_path=Path("data/risk/order_profiles.json"),
            strategy_profile_path=Path("data/risk/strategy_profiles.json"),
            strategy_simulation_path=Path("data/risk/strategy_simulations.json"),
            graph_relation_path=Path("data/risk/graph_relations.json"),
            sql_query_result_path=Path("data/risk/sql_query_results.json"),
            dashboard_snapshot_path=Path("data/risk/dashboard_snapshots.json"),
            rule_explanation_path=Path("data/risk/rule_explanations.json"),
            tool_http_base_url="http://127.0.0.1:8090",
            tool_http_timeout_sec=5.0,
            tool_http_retry_attempts=2,
            tool_http_retry_backoff_sec=0.1,
            tool_http_circuit_breaker_failure_threshold=5,
            tool_http_circuit_breaker_reset_sec=30.0,
            tool_http_auth_mode="none",
            tool_http_auth_token="",
            tool_http_auth_token_file=None,
            tool_http_auth_header="Authorization",
            tool_http_audit_enabled=True,
            tool_http_audit_path=Path(".data/upstream-audit.jsonl"),
            tool_http_audit_max_bytes=10 * 1024 * 1024,
            tool_http_audit_max_files=5,
            tool_http_audit_integrity_enabled=True,
            audit_central_enabled=False,
            audit_central_url="",
            audit_central_timeout_sec=3.0,
            audit_central_auth_header="Authorization",
            audit_central_auth_token="",
            audit_central_auth_token_file=None,
            handoff_ticket_base_url="https://handoff.local/tickets",
            handoff_ticket_path="/projects/{project_key}/cases",
            handoff_ticket_project_key="risk-ops",
            handoff_ticket_auth_header="Authorization",
            handoff_ticket_auth_token="",
            handoff_ticket_auth_token_file=None,
            handoff_webhook_base_url="https://handoff.local/webhooks",
            handoff_webhook_auth_header="Authorization",
            handoff_webhook_auth_token="",
            handoff_webhook_auth_token_file=None,
            handoff_publish_timeout_sec=5.0,
            handoff_publish_retry_attempts=1,
            handoff_publish_retry_backoff_sec=0.1,
            handoff_ticket_max_attempts=3,
            handoff_ticket_retry_cooldown_sec=0.0,
            handoff_webhook_max_attempts=3,
            handoff_webhook_retry_cooldown_sec=0.0,
            handoff_retry_sweep_limit=50,
            tool_http_metric_path="/metric-snapshots",
            tool_http_case_path="/case-records",
            tool_http_order_path_template="/order-profiles/{order_id}",
            tool_http_strategy_profile_path_template="/strategy-profiles/{strategy_id}",
            tool_http_strategy_simulation_path_template="/strategy-simulations/{strategy_id}",
            tool_http_graph_relation_path_template="/graph-relations/{entity_id}",
            tool_http_sql_query_path_template="/sql-queries/{query_name}",
            tool_http_dashboard_snapshot_path_template="/dashboard-snapshots/{dashboard_id}",
            tool_http_rule_explain_path="/rule-explanations",
            tool_http_country_param="country",
            tool_http_channel_param="channel",
            session_store_backend="memory",
            session_store_path=Path(".data/sessions.json"),
            case_store_backend="memory",
            case_store_path=Path(".data/cases.json"),
            database_path=Path(".data/platform.db"),
            postgres_dsn="",
            postgres_dsn_file=None,
            api_host="127.0.0.1",
            api_port=8000,
            risk_service_host="127.0.0.1",
            risk_service_port=8090,
            risk_service_fault_injection_enabled=False,
            risk_decision_policy_path=None,
            admin_auth_enabled=False,
            admin_auth_header="X-Admin-Token",
            admin_auth_token="",
            admin_auth_token_file=None,
        )

    def tool_http_headers(self) -> Dict[str, str]:
        if self.tool_http_auth_mode == "bearer" and self.tool_http_auth_token:
            return {self.tool_http_auth_header: f"Bearer {self.tool_http_auth_token}"}
        if self.tool_http_auth_mode == "api_key" and self.tool_http_auth_token:
            return {self.tool_http_auth_header: self.tool_http_auth_token}
        return {}

    def tool_http_auth_token_source(self) -> str:
        if self.tool_http_auth_token_file is not None:
            return "file"
        if self.tool_http_auth_token:
            return "env"
        return "none"

    def admin_auth_token_source(self) -> str:
        if self.admin_auth_token_file is not None:
            return "file"
        if self.admin_auth_token:
            return "env"
        return "none"

    def audit_central_headers(self) -> Dict[str, str]:
        if not self.audit_central_auth_token:
            return {}
        return {self.audit_central_auth_header: self.audit_central_auth_token}

    def audit_central_auth_token_source(self) -> str:
        if self.audit_central_auth_token_file is not None:
            return "file"
        if self.audit_central_auth_token:
            return "env"
        return "none"

    def handoff_ticket_headers(self) -> Dict[str, str]:
        if not self.handoff_ticket_auth_token:
            return {}
        return {self.handoff_ticket_auth_header: self.handoff_ticket_auth_token}

    def handoff_ticket_auth_token_source(self) -> str:
        if self.handoff_ticket_auth_token_file is not None:
            return "file"
        if self.handoff_ticket_auth_token:
            return "env"
        return "none"

    def handoff_webhook_headers(self) -> Dict[str, str]:
        if not self.handoff_webhook_auth_token:
            return {}
        return {self.handoff_webhook_auth_header: self.handoff_webhook_auth_token}

    def handoff_webhook_auth_token_source(self) -> str:
        if self.handoff_webhook_auth_token_file is not None:
            return "file"
        if self.handoff_webhook_auth_token:
            return "env"
        return "none"

    def postgres_dsn_source(self) -> str:
        if self.postgres_dsn_file is not None:
            return "file"
        if self.postgres_dsn:
            return "env"
        return "none"

    def risk_decision_policy_source(self) -> str:
        if self.risk_decision_policy_path is not None:
            return "file"
        return "builtin"

    def planner_source(self) -> str:
        return self.planner_backend

    def planner_openai_api_key_source(self) -> str:
        if self.planner_openai_api_key_file is not None:
            return "file"
        if self.planner_openai_api_key:
            return "env"
        return "none"

    def investigation_source(self) -> str:
        return self.investigation_backend

    def investigation_openai_api_key_source(self) -> str:
        if self.investigation_openai_api_key_file is not None:
            return "file"
        if self.investigation_openai_api_key:
            return "env"
        return "none"

    def strategy_source(self) -> str:
        return self.strategy_backend

    def strategy_openai_api_key_source(self) -> str:
        if self.strategy_openai_api_key_file is not None:
            return "file"
        if self.strategy_openai_api_key:
            return "env"
        return "none"

    def graph_source(self) -> str:
        return self.graph_backend

    def graph_openai_api_key_source(self) -> str:
        if self.graph_openai_api_key_file is not None:
            return "file"
        if self.graph_openai_api_key:
            return "env"
        return "none"

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
            {
                "tool_name": "sql_query",
                "path_env_var": "AI_RISK_TOOL_HTTP_SQL_QUERY_PATH_TEMPLATE",
                "path": self.tool_http_sql_query_path_template,
                "supports_capabilities": ["investigation", "copilot"],
                "query_params": {
                    "country_env_var": "AI_RISK_TOOL_HTTP_COUNTRY_PARAM",
                    "country_name": self.tool_http_country_param,
                    "channel_env_var": "AI_RISK_TOOL_HTTP_CHANNEL_PARAM",
                    "channel_name": self.tool_http_channel_param,
                },
            },
            {
                "tool_name": "dashboard_snapshot",
                "path_env_var": "AI_RISK_TOOL_HTTP_DASHBOARD_SNAPSHOT_PATH_TEMPLATE",
                "path": self.tool_http_dashboard_snapshot_path_template,
                "supports_capabilities": ["investigation", "copilot"],
                "query_params": {
                    "country_env_var": "AI_RISK_TOOL_HTTP_COUNTRY_PARAM",
                    "country_name": self.tool_http_country_param,
                    "channel_env_var": "AI_RISK_TOOL_HTTP_CHANNEL_PARAM",
                    "channel_name": self.tool_http_channel_param,
                },
            },
            {
                "tool_name": "rule_explain",
                "path_env_var": "AI_RISK_TOOL_HTTP_RULE_EXPLAIN_PATH",
                "path": self.tool_http_rule_explain_path,
                "supports_capabilities": ["investigation", "strategy", "copilot"],
                "query_params": {},
            },
        ]
