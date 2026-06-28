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

Use this offline gate before changing planner prompts, rule planners, or tool
contracts. Runtime quality remains covered by `/admin/metrics`, Prometheus
alerts, and the readiness gate.

`make ci-signoff` runs the same gate automatically after unit tests and writes
`planner-eval.json` into the CI report directory.
