from __future__ import annotations

from typing import Any, Dict, List, Tuple

from core.models import KnowledgeDocument


def build_knowledge_documents() -> list[KnowledgeDocument]:
    return [
        KnowledgeDocument(
            doc_id="SOP-001",
            title="支付失败率异常排查 SOP",
            source_type="sop",
            tags=("payment", "anomaly", "investigation"),
            content=(
                "支付失败率异常排查需要先确认异常开始时间，再按国家、渠道、卡组织拆分。"
                "之后检查近 24 小时策略阈值、支付通道、验证码触发率和人工审核量变化，"
                "最后回看历史相似案例并形成下一步动作建议。"
            ),
        ),
        KnowledgeDocument(
            doc_id="CASE-112",
            title="巴西信用卡失败率波动复盘",
            source_type="case",
            tags=("brazil", "credit_card", "payment"),
            content=(
                "2025 年 Q4 巴西信用卡失败率曾因新阈值上线后误杀放大而上升。"
                "当时通过回退阈值、补充卡组织分层策略和人工抽样复核恢复了通过率。"
            ),
        ),
        KnowledgeDocument(
            doc_id="SOP-010",
            title="营销套利案件排查 SOP",
            source_type="sop",
            tags=("marketing", "abuse", "case"),
            content=(
                "营销套利排查需要核对账户画像、设备/IP 复用、优惠领取路径、支付工具重叠和历史套利标签。"
                "对可疑样本需要补看活动参与链路和同设备多账号关系。"
            ),
        ),
        KnowledgeDocument(
            doc_id="FAQ-007",
            title="Shadow Evaluation 为什么重要",
            source_type="faq",
            tags=("strategy", "simulation"),
            content=(
                "Shadow Evaluation 用于在不影响线上真实决策的前提下验证新策略收益与误杀影响。"
                "它适合在策略上线前做风险收益平衡分析。"
            ),
        ),
    ]


def build_metric_snapshots() -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    return {
        ("BR", "credit_card", "recent_24h"): {
            "country": "BR",
            "channel": "credit_card",
            "time_range": "recent_24h",
            "metric_name": "payment_failure_rate",
            "anomaly_started_at": "2026-05-20 22:00",
            "current_value": "12.4%",
            "baseline_value": "5.1%",
            "recent_change": "新支付风控阈值于 2026-05-20 21:40 上线",
            "suspected_driver": "阈值过严导致正常用户挑战和拒绝增加",
        },
        ("BR", "credit_card", "recent_7d"): {
            "country": "BR",
            "channel": "credit_card",
            "time_range": "recent_7d",
            "metric_name": "payment_failure_rate",
            "anomaly_started_at": "2026-05-18 08:00",
            "current_value": "9.8%",
            "baseline_value": "5.0%",
            "recent_change": "过去 7 天内失败率持续抬升，5 月 20 日晚间阈值调整后进一步放大",
            "suspected_driver": "阈值偏严叠加部分卡组织通过率下滑",
        },
        ("ID", "wallet", "recent_24h"): {
            "country": "ID",
            "channel": "wallet",
            "time_range": "recent_24h",
            "metric_name": "payment_pass_rate",
            "anomaly_started_at": "2026-05-21 09:10",
            "current_value": "81.3%",
            "baseline_value": "89.6%",
            "recent_change": "钱包通道风险路由规则更新",
            "suspected_driver": "新路由规则放大了挑战比例",
        },
        ("US", "credit_card", "recent_24h"): {
            "country": "US",
            "channel": "credit_card",
            "time_range": "recent_24h",
            "metric_name": "chargeback_rate",
            "anomaly_started_at": "2026-05-18 00:00",
            "current_value": "1.9%",
            "baseline_value": "1.1%",
            "recent_change": "风控策略未变更，需优先排查渠道和外部流量结构",
            "suspected_driver": "高风险流量结构变化",
        },
    }


def build_case_records() -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    return {
        ("BR", "credit_card"): [
            {
                "case_id": "BR-2025-112",
                "title": "巴西信用卡失败率因阈值过严而放大",
            }
        ],
        ("ID", "wallet"): [
            {
                "case_id": "ID-2026-021",
                "title": "印尼钱包路由更新导致挑战率上升",
            }
        ],
    }


def build_order_profiles() -> Dict[str, Dict[str, Any]]:
    return {
        "O10001": {
            "order_id": "O10001",
            "country": "BR",
            "channel": "credit_card",
            "recent_attempts": 4,
            "triggered_rules": ["device_velocity_spike", "high_risk_bin"],
            "risk_labels": ["device_risk", "payment_risk"],
            "recommended_action": "manual_review",
        },
        "O20001": {
            "order_id": "O20001",
            "country": "US",
            "channel": "credit_card",
            "recent_attempts": 1,
            "triggered_rules": ["chargeback_history"],
            "risk_labels": ["account_risk"],
            "recommended_action": "reject",
        },
    }


def build_strategy_profiles() -> Dict[str, Dict[str, Any]]:
    return {
        "STRAT-001": {
            "strategy_id": "STRAT-001",
            "name": "Brazil Credit Card Velocity Guard",
            "country": "BR",
            "channel": "credit_card",
            "status": "active",
            "current_threshold": 0.70,
            "hit_rate": "8.4%",
            "risk_capture_rate": "67%",
            "false_positive_rate": "2.1%",
            "recent_issue": "通过率下降且误杀投诉上升",
            "top_impacted_entities": ["O10001", "U10001"],
        },
        "STRAT-002": {
            "strategy_id": "STRAT-002",
            "name": "Indonesia Wallet Routing Control",
            "country": "ID",
            "channel": "wallet",
            "status": "active",
            "current_threshold": 0.64,
            "hit_rate": "6.1%",
            "risk_capture_rate": "58%",
            "false_positive_rate": "1.4%",
            "recent_issue": "挑战率波动放大，需重新评估阈值",
            "top_impacted_entities": ["U10001"],
        },
    }


def build_strategy_simulations() -> Dict[str, Dict[str, Any]]:
    return {
        "STRAT-001": {
            "strategy_id": "STRAT-001",
            "recommended_threshold": 0.66,
            "delta_intercepts": "+4.2%",
            "delta_false_positives": "+0.5%",
            "estimated_risk_reduction": "8.7%",
            "estimated_revenue_impact": "-0.9%",
            "simulation_window": "recent_14d",
            "recommendation_reason": "当前阈值偏严，适合小幅下调后先做 shadow evaluation。",
        },
        "STRAT-002": {
            "strategy_id": "STRAT-002",
            "recommended_threshold": 0.60,
            "delta_intercepts": "+3.1%",
            "delta_false_positives": "+0.3%",
            "estimated_risk_reduction": "5.4%",
            "estimated_revenue_impact": "-0.4%",
            "simulation_window": "recent_14d",
            "recommendation_reason": "通过率波动较大，建议小步调整并结合国家分层观察。",
        },
    }


def build_graph_relations() -> Dict[str, Dict[str, Any]]:
    return {
        "U10001": {
            "entity_id": "U10001",
            "entity_type": "user",
            "risk_level": "high",
            "shared_devices": ["D-778", "D-901"],
            "shared_ips": ["203.0.113.18"],
            "linked_accounts": ["U10002", "U10421", "U10987"],
            "linked_orders": ["O10001", "O10019"],
            "community_size": 5,
            "key_path": "U10001 -> D-778 -> U10002 -> IP:203.0.113.18 -> U10421",
            "risk_reason": "多账号共享设备与 IP，存在明显团伙联动特征。",
        },
        "O10001": {
            "entity_id": "O10001",
            "entity_type": "order",
            "risk_level": "medium",
            "shared_devices": ["D-778"],
            "shared_ips": ["203.0.113.18"],
            "linked_accounts": ["U10001", "U10002"],
            "linked_orders": ["O10019", "O10021"],
            "community_size": 4,
            "key_path": "O10001 -> U10001 -> D-778 -> U10002 -> O10019",
            "risk_reason": "订单关联账号和设备网络密集，疑似同一操作群体。",
        },
    }
