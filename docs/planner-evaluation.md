# Planner Evaluation

V2 planner evaluation is an offline golden-set gate for copilot,
investigation, and strategy routing quality. It runs fully locally against the
demo runtime and does not call external LLM or tool services.

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

The default suite checks:

- `copilot` composite routing for order + strategy + graph analysis.
- `copilot` metric-anomaly routing for plain metric questions.
- `investigation` metric tool selection.
- `investigation` order tool selection.
- `strategy` tool selection for profile, simulation, graph, and rule evidence.

The report includes:

- `intent_accuracy`: expected intent match rate.
- `plan_step_accuracy`: exact plan-step match rate.
- `tool_coverage_rate`: expected tool trace coverage.
- `no_fallback_rate`: share of cases that did not use rule fallback.
- `no_validation_error_rate`: share of cases with no candidate-plan repair.
- `by_agent`: the same quality summary grouped by agent.
- `by_backend`: the same quality summary grouped by planner backend.
- `thresholds`: configured minimum rates for the current run.
- `threshold_failures`: any metrics below the configured thresholds.

Custom cases use this JSON shape:

```json
{
  "cases": [
    {
      "name": "investigation_metric_default",
      "agent_name": "investigation",
      "query": "为什么巴西信用卡支付失败率从昨晚开始突然升高？",
      "context": {"country": "BR", "channel": "credit_card"},
      "expected_intent": "metric_investigation",
      "expected_plan_steps": ["metric_snapshot", "case_lookup", "dashboard_snapshot"],
      "expected_tool_traces": ["metric_snapshot", "case_lookup", "dashboard_snapshot"]
    }
  ]
}
```

Use this offline gate before changing planner prompts, rule planners, or tool
contracts. Runtime quality remains covered by `/admin/metrics`, Prometheus
alerts, and the readiness gate.

`make ci-signoff` runs the same gate automatically after unit tests and writes
`planner-eval.json` into the CI report directory.
