# Planner Evaluation

V2/V3/V4 planner evaluation is an offline golden-set gate for copilot,
investigation, strategy, graph, root-cause routing quality, V3 global-planning
artifacts, and V4 root-cause hypothesis quality. It runs fully locally against
the demo runtime and does not call external LLM or tool services.

Run the default golden set:

```bash
make validate-planner-eval
```

Write a JSON report:

```bash
make validate-planner-eval \
  PLANNER_EVAL_ARGS="--output .data/reports/planner-eval.json"
```

Run a custom golden set:

```bash
make validate-planner-eval \
  PLANNER_EVAL_ARGS="--cases-file config/planner-eval/golden-cases.example.json"
```

Relax or tighten gates explicitly:

```bash
make validate-planner-eval \
  PLANNER_EVAL_ARGS="--min-plan-step-accuracy 0.98 --min-tool-coverage-rate 1.0"
```

Gate V2 intermediate-state quality explicitly:

```bash
make validate-planner-eval \
  PLANNER_EVAL_ARGS="--min-intermediate-state-coverage-rate 1.0 --min-tool-reason-coverage-rate 1.0 --min-evidence-gap-accuracy 1.0"
```

Gate V3 global-planning artifacts explicitly:

```bash
make validate-planner-eval \
  PLANNER_EVAL_ARGS="--min-global-planning-coverage-rate 1.0"
```

Compare against a previous report and fail on any quality regression:

```bash
make validate-planner-eval \
  PLANNER_EVAL_ARGS="--baseline-file .data/reports/previous-planner-eval.json"
```

Allow a small regression tolerance:

```bash
make validate-planner-eval \
  PLANNER_EVAL_ARGS="--baseline-file .data/reports/previous-planner-eval.json --max-allowed-regression 0.01"
```

The default suite checks:

- `copilot` composite routing for order + strategy + graph analysis.
- `copilot` metric-anomaly routing for plain metric questions.
- `copilot` V3 global-plan, evidence-graph, and working-memory artifacts.
- `copilot` V4b root-cause routing for why/root-cause questions.
- `investigation` metric tool selection.
- `investigation` order tool selection.
- `strategy` tool selection for profile, simulation, graph, and rule evidence.
- `root_cause` V4a hypothesis ranking across metric, dashboard, SQL, and rule
  evidence.
- `graph` tool selection for graph relation evidence.
- `graph` missing-data behavior that must surface an `evidence_gap`.

The report includes:

- `intent_accuracy`: expected intent match rate.
- `plan_step_accuracy`: exact plan-step match rate.
- `tool_coverage_rate`: expected tool trace coverage.
- `intermediate_state_coverage_rate`: share of cases with required
  `thought_summary` and `tool_using_plan` state.
- `tool_reason_coverage_rate`: share of cases where every selected tool has an
  auditable `tool_selection_reason`.
- `evidence_gap_accuracy`: share of cases whose actual evidence-gap sources
  match the expected missing-evidence contract.
- `global_planning_coverage_rate`: share of cases that require and produce V3
  `global_plan`, `evidence_graph`, `working_memory`, and
  `global_plan_quality` artifacts, plus the V3f `execution_readiness`
  execution-governance gate.
- `root_cause_quality_rate`: share of cases that either do not require
  root-cause quality or produce V4c `root_cause_quality` with
  `overall_score >= 0.75` and V4d `root_cause_readiness`.
  V4e reuses that readiness artifact when creating workflow cases, mapping
  ready/review/blocked outcomes into auditable action queues.
- `no_fallback_rate`: share of cases that did not use rule fallback.
- `no_validation_error_rate`: share of cases with no candidate-plan repair.
- `by_agent`: the same quality summary grouped by agent.
- `by_backend`: the same quality summary grouped by planner backend.
- `thresholds`: configured minimum rates for the current run.
- `threshold_failures`: any metrics below the configured thresholds.
- `baseline_comparison`: metric deltas versus a previous report when
  `--baseline-file` is provided. It compares overall summary metrics, agent
  groups, and backend groups.

Custom cases use this JSON shape:

```json
{
  "cases": [
    {
      "name": "copilot_composite_order_strategy_graph",
      "agent_name": "copilot",
      "query": "请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
      "context": {"order_id": "O10001", "strategy_id": "STRAT-001", "entity_id": "U10001"},
      "expected_intent": "composite",
      "expected_plan_steps": ["调查", "策略", "图谱"],
      "expected_tool_trace_prefixes": ["调查::", "策略::", "图谱::"],
      "require_intermediate_state": false,
      "require_global_planning": true
    },
    {
      "name": "copilot_root_cause_metric",
      "agent_name": "copilot",
      "query": "为什么巴西信用卡支付失败率从昨晚开始突然升高？请给出根因排序",
      "context": {"country": "BR", "channel": "credit_card"},
      "expected_intent": "root_cause_analysis",
      "expected_plan_steps": ["调查", "根因"],
      "expected_tool_trace_prefixes": ["调查::", "根因::"],
      "require_intermediate_state": false,
      "require_global_planning": true
    },
    {
      "name": "investigation_metric_default",
      "agent_name": "investigation",
      "query": "为什么巴西信用卡支付失败率从昨晚开始突然升高？",
      "context": {"country": "BR", "channel": "credit_card"},
      "expected_intent": "metric_investigation",
      "expected_plan_steps": ["metric_snapshot", "case_lookup", "dashboard_snapshot"],
      "expected_tool_traces": ["metric_snapshot", "case_lookup", "dashboard_snapshot"],
      "expected_evidence_gap_sources": []
    },
    {
      "name": "graph_missing_relation_evidence_gap",
      "agent_name": "graph",
      "query": "请分析用户 MISSING 是否属于团伙网络",
      "context": {"entity_id": "MISSING"},
      "expected_intent": "graph_tool_plan",
      "expected_plan_steps": ["graph_relation"],
      "expected_tool_traces": ["graph_relation"],
      "expected_evidence_gap_sources": ["graph_relation"]
    }
  ]
}
```

Set `"require_intermediate_state": false` for orchestration-only cases such as
`copilot` when the case is testing high-level routing rather than V2
tool-using agent internals.
Set `"require_global_planning": true` for copilot cases that must produce the
V3 global-planning artifact set. Required quality artifacts include
`global_plan_quality.version == "v3d"`, `overall_score >= 0.75`, and
`execution_readiness.version == "v3f"` with a valid `ready`,
`requires_review`, or `blocked` status.

For multi-turn copilot sessions, the runtime injects short-term session memory
into the execution request. The stored user turn context remains unchanged, but
the V3 `working_memory.session_memory_refs` artifact can cite recent turn
summaries, intents, evidence sources, and open evidence-gap sources.
When workflow cases exist, copilot also retrieves lightweight long-term case
memory into `working_memory.long_term_memory_refs`, including case ID, summary,
intent, severity, risk level, and recommended action.

Use this offline gate before changing planner prompts, rule planners, or tool
contracts. Runtime quality remains covered by `/admin/metrics`, Prometheus
alerts, and the readiness gate.

`make ci-signoff` runs the same gate automatically after unit tests and writes
`planner-eval.json` into the CI report directory.

CI signoff can also compare against a previous planner eval report:

```bash
AI_RISK_PLANNER_EVAL_BASELINE_FILE=.data/reports/previous/planner-eval.json \
AI_RISK_PLANNER_EVAL_MAX_ALLOWED_REGRESSION=0.01 \
make ci-signoff
```
