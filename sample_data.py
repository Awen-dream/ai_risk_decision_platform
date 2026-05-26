from __future__ import annotations

from core.models import KnowledgeDocument, ToolResult


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


def build_metric_snapshots():
    snapshots = {
        ("BR", "credit_card"): {
            "country": "BR",
            "channel": "credit_card",
            "metric_name": "payment_failure_rate",
            "anomaly_started_at": "2026-05-20 22:00",
            "current_value": "12.4%",
            "baseline_value": "5.1%",
            "recent_change": "新支付风控阈值于 2026-05-20 21:40 上线",
            "suspected_driver": "阈值过严导致正常用户挑战和拒绝增加",
        },
        ("ID", "wallet"): {
            "country": "ID",
            "channel": "wallet",
            "metric_name": "payment_pass_rate",
            "anomaly_started_at": "2026-05-21 09:10",
            "current_value": "81.3%",
            "baseline_value": "89.6%",
            "recent_change": "钱包通道风险路由规则更新",
            "suspected_driver": "新路由规则放大了挑战比例",
        },
        ("US", "credit_card"): {
            "country": "US",
            "channel": "credit_card",
            "metric_name": "chargeback_rate",
            "anomaly_started_at": "2026-05-18 00:00",
            "current_value": "1.9%",
            "baseline_value": "1.1%",
            "recent_change": "风控策略未变更，需优先排查渠道和外部流量结构",
            "suspected_driver": "高风险流量结构变化",
        },
    }

    def execute(country: str, channel: str, time_range: str) -> ToolResult:
        key = (country.upper(), channel.lower())
        payload = snapshots.get(key)
        if payload is None:
            return ToolResult(
                name="metric_snapshot",
                payload={},
                summary="未找到对应指标快照",
                success=False,
                error=f"No snapshot for {country}/{channel} in {time_range}",
            )
        return ToolResult(
            name="metric_snapshot",
            payload=payload,
            summary=f"已返回 {payload['country']} {payload['channel']} 的指标快照",
        )

    return execute


def build_case_records():
    records = {
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

    def execute(country: str, channel: str) -> ToolResult:
        payload = records.get((country.upper(), channel.lower()), [])
        return ToolResult(
            name="case_lookup",
            payload=payload,
            summary=f"返回 {len(payload)} 条历史相似案例",
        )

    return execute


def build_order_profiles():
    orders = {
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

    def execute(order_id: str) -> ToolResult:
        payload = orders.get(order_id)
        if payload is None:
            return ToolResult(
                name="order_profile",
                payload={},
                summary="未找到订单画像",
                success=False,
                error=f"Unknown order: {order_id}",
            )
        return ToolResult(
            name="order_profile",
            payload=payload,
            summary=f"已返回订单 {order_id} 的风险画像",
        )

    return execute
