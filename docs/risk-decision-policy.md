# Risk Decision Policy

The copilot agent emits a structured `risk_decision` artifact after it merges
investigation, strategy, and graph evidence. The built-in policy keeps high
graph risk and reject actions in manual review, sends strategy-only adjustments
to shadow evaluation, and monitors low-evidence metric anomalies.

Set `AI_RISK_DECISION_POLICY_PATH` to load a JSON policy file:

```bash
export AI_RISK_DECISION_POLICY_PATH=/etc/ai-risk/risk-decision-policy.json
```

Example:

```json
{
  "signals": {
    "high_graph_levels": ["high"],
    "medium_graph_levels": ["medium"],
    "reject_order_actions": ["reject"],
    "review_order_actions": ["manual_review"]
  },
  "evidence_strength": {
    "strong_min_confidence": 0.8,
    "strong_min_evidence_count": 2,
    "medium_min_confidence": 0.55
  },
  "outcomes": {
    "high_risk_review": {
      "decision": "escalate_review",
      "risk_level": "high",
      "recommended_action": "manual_review",
      "escalation_reason": "High-risk graph or reject signal requires review before hard action.",
      "policy_controls": ["manual_review_queue", "graph_network_review"]
    },
    "medium_risk_review": {
      "decision": "manual_review",
      "risk_level": "medium",
      "recommended_action": "manual_review",
      "escalation_reason": "Evidence reaches review threshold but is not enough for direct rejection.",
      "policy_controls": ["manual_review_queue"]
    },
    "strategy_shadow_adjustment": {
      "decision": "strategy_shadow_adjustment",
      "risk_level": "medium",
      "recommended_action": "shadow_evaluation",
      "escalation_reason": "Validate threshold changes in shadow evaluation before rollout.",
      "policy_controls": ["shadow_evaluation"]
    },
    "monitor": {
      "decision": "monitor",
      "risk_level": "low",
      "recommended_action": "monitor"
    }
  }
}
```

Use `GET /admin/runtime` to confirm `risk_decision_policy_source` is `builtin`
or `file` and, for file-backed policies, that `risk_decision_policy_path` points
to the expected policy.
