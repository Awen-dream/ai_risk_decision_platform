# Risk Decision Policy

The copilot agent emits a structured `risk_decision` artifact after it merges
investigation, strategy, and graph evidence. The built-in policy keeps high
graph risk and reject actions in manual review, sends strategy-only adjustments
to shadow evaluation, and monitors low-evidence metric anomalies. Each decision
also carries an executable action plan with the target queue, priority, SLA,
owner role, and next actions.

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
  },
  "action_plans": {
    "escalate_review": {
      "queue": "manual_review_queue",
      "priority": "high",
      "sla_hours": 4,
      "owner_role": "risk_reviewer",
      "next_actions": [
        "Review order profile, graph relations, and historical case evidence.",
        "Confirm reject, approve, or additional verification action."
      ]
    },
    "manual_review": {
      "queue": "manual_review_queue",
      "priority": "medium",
      "sla_hours": 12,
      "owner_role": "risk_reviewer",
      "next_actions": [
        "Review core risk evidence and business impact.",
        "Confirm approve, intercept, or continue monitoring decision."
      ]
    },
    "strategy_shadow_adjustment": {
      "queue": "strategy_shadow_queue",
      "priority": "medium",
      "sla_hours": 24,
      "owner_role": "strategy_owner",
      "next_actions": [
        "Create a shadow evaluation experiment with the recommended threshold.",
        "Monitor approval rate, false positives, and risk capture rate."
      ]
    },
    "monitor": {
      "queue": "risk_monitoring_queue",
      "priority": "low",
      "sla_hours": 72,
      "owner_role": "risk_ops",
      "next_actions": [
        "Monitor core metrics and anomaly spread.",
        "Escalate to review if evidence strengthens or metrics deteriorate."
      ]
    }
  }
}
```

Use `GET /admin/runtime` to confirm `risk_decision_policy_source` is `builtin`
or `file` and, for file-backed policies, that `risk_decision_policy_path` points
to the expected policy.
