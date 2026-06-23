from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.models import AgentResponse, ToolTrace
from services.risk_decision import RiskDecisionPolicy


class RiskDecisionPolicyTests(unittest.TestCase):
    def test_default_policy_escalates_high_graph_risk(self) -> None:
        child = AgentResponse(
            agent_name="graph",
            tool_traces=[
                ToolTrace(
                    name="graph_relation",
                    status="success",
                    summary="graph",
                    payload={"risk_level": "high", "community_size": 5},
                )
            ],
        )

        decision = RiskDecisionPolicy.default().evaluate(
            intent="fraud_ring",
            child_responses=[("图谱", child)],
            confidence=0.82,
        )

        self.assertEqual(decision["decision"], "escalate_review")
        self.assertEqual(decision["risk_level"], "high")
        self.assertIn("graph_network_review", decision["policy_controls"])
        self.assertEqual(decision["action_plan"]["queue"], "manual_review_queue")
        self.assertEqual(decision["action_plan"]["priority"], "high")
        self.assertEqual(decision["action_plan"]["sla_hours"], 4)

    def test_custom_policy_overrides_signals_and_outcomes(self) -> None:
        policy = RiskDecisionPolicy.from_mapping(
            {
                "signals": {
                    "high_graph_levels": ["medium"],
                },
                "outcomes": {
                    "high_risk_review": {
                        "decision": "queue_l2_review",
                        "risk_level": "high",
                        "recommended_action": "manual_review",
                        "escalation_reason": "中风险图谱在当前业务线需要二线复核。",
                        "policy_controls": ["l2_review_queue"],
                    }
                },
                "action_plans": {
                    "queue_l2_review": {
                        "queue": "l2_review_queue",
                        "priority": "high",
                        "sla_hours": 2,
                        "owner_role": "l2_risk_reviewer",
                        "next_actions": ["二线复核图谱证据", "确认强处置方案"],
                    }
                },
            }
        )
        child = AgentResponse(
            agent_name="graph",
            tool_traces=[
                ToolTrace(
                    name="graph_relation",
                    status="success",
                    summary="graph",
                    payload={"risk_level": "medium", "community_size": 4},
                )
            ],
        )

        decision = policy.evaluate(
            intent="order_case",
            child_responses=[("图谱", child)],
            confidence=0.8,
        )

        self.assertEqual(decision["decision"], "queue_l2_review")
        self.assertEqual(decision["risk_level"], "high")
        self.assertIn("l2_review_queue", decision["policy_controls"])
        self.assertEqual(decision["action_plan"]["queue"], "l2_review_queue")
        self.assertEqual(decision["action_plan"]["sla_hours"], 2)
        self.assertEqual(decision["action_plan"]["owner_role"], "l2_risk_reviewer")

    def test_policy_loads_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            policy_path = Path(tmp_dir) / "risk-decision-policy.json"
            policy_path.write_text(
                json.dumps(
                    {
                        "evidence_strength": {
                            "strong_min_confidence": 0.9,
                            "strong_min_evidence_count": 3,
                        }
                    }
                ),
                encoding="utf-8",
            )

            policy = RiskDecisionPolicy.from_file(policy_path)

        self.assertEqual(policy.evidence_strength.strong_min_confidence, 0.9)
        self.assertEqual(policy.evidence_strength.strong_min_evidence_count, 3)


if __name__ == "__main__":
    unittest.main()
