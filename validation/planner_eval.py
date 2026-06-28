from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import build_demo_runtime
from core.models import AgentRequest, AgentResponse


@dataclass(frozen=True)
class PlannerEvalCase:
    name: str
    agent_name: str
    query: str
    context: dict[str, Any]
    expected_plan_steps: list[str]
    expected_intent: str | None = None
    expected_tool_traces: list[str] | None = None
    expected_tool_trace_prefixes: list[str] | None = None


@dataclass
class PlannerEvalCaseResult:
    name: str
    agent_name: str
    status: str
    intent_matched: bool | None
    plan_steps_matched: bool
    tool_coverage_matched: bool
    fallback_used: bool
    validation_error_count: int
    expected_intent: str | None
    actual_intent: str | None
    expected_plan_steps: list[str]
    actual_plan_steps: list[str]
    expected_tool_traces: list[str]
    actual_tool_traces: list[str]
    missing_tool_traces: list[str]
    missing_tool_trace_prefixes: list[str]
    planner_backend: str


DEFAULT_EVAL_CASES = [
    PlannerEvalCase(
        name="copilot_composite_order_strategy_graph",
        agent_name="copilot",
        query="请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
        context={
            "order_id": "O10001",
            "strategy_id": "STRAT-001",
            "entity_id": "U10001",
        },
        expected_intent="composite",
        expected_plan_steps=["调查", "策略", "图谱"],
        expected_tool_trace_prefixes=["调查::", "策略::", "图谱::"],
    ),
    PlannerEvalCase(
        name="copilot_metric_anomaly",
        agent_name="copilot",
        query="为什么巴西信用卡支付失败率从昨晚开始突然升高？",
        context={},
        expected_intent="metric_anomaly",
        expected_plan_steps=["调查"],
        expected_tool_trace_prefixes=["调查::"],
    ),
    PlannerEvalCase(
        name="investigation_metric_default",
        agent_name="investigation",
        query="为什么巴西信用卡支付失败率从昨晚开始突然升高？",
        context={"country": "BR", "channel": "credit_card"},
        expected_intent="metric_investigation",
        expected_plan_steps=["metric_snapshot", "case_lookup", "dashboard_snapshot"],
        expected_tool_traces=["metric_snapshot", "case_lookup", "dashboard_snapshot"],
    ),
    PlannerEvalCase(
        name="investigation_order_default",
        agent_name="investigation",
        query="请分析这个订单为什么被判高风险",
        context={"order_id": "O10001"},
        expected_intent="order_investigation",
        expected_plan_steps=["order_profile", "graph_relation", "rule_explain"],
        expected_tool_traces=["order_profile", "graph_relation", "rule_explain"],
    ),
    PlannerEvalCase(
        name="strategy_default",
        agent_name="strategy",
        query="请评估策略 STRAT-001 是否应该调整阈值",
        context={"strategy_id": "STRAT-001"},
        expected_intent="strategy_tool_plan",
        expected_plan_steps=[
            "strategy_profile",
            "strategy_simulation",
            "graph_relation",
            "rule_explain",
        ],
        expected_tool_traces=[
            "strategy_profile",
            "strategy_simulation",
            "graph_relation",
            "rule_explain",
        ],
    ),
]


def run_planner_eval(
    cases: list[PlannerEvalCase] | None = None,
) -> dict[str, Any]:
    runtime = build_demo_runtime()
    eval_cases = cases or list(DEFAULT_EVAL_CASES)
    results = [_run_case(runtime, case) for case in eval_cases]
    total = len(results)
    passed = sum(result.status == "passed" for result in results)
    intent_cases = [result for result in results if result.intent_matched is not None]
    intent_passed = sum(result.intent_matched is True for result in intent_cases)
    report = {
        "status": "passed" if passed == total else "failed",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "intent_accuracy": _ratio(intent_passed, len(intent_cases)),
            "plan_step_accuracy": _ratio(
                sum(result.plan_steps_matched for result in results),
                total,
            ),
            "tool_coverage_rate": _ratio(
                sum(result.tool_coverage_matched for result in results),
                total,
            ),
            "no_fallback_rate": _ratio(
                sum(not result.fallback_used for result in results),
                total,
            ),
            "no_validation_error_rate": _ratio(
                sum(result.validation_error_count == 0 for result in results),
                total,
            ),
        },
        "cases": [asdict(result) for result in results],
    }
    return report


def _run_case(runtime, case: PlannerEvalCase) -> PlannerEvalCaseResult:
    _, response = runtime.execute(
        case.agent_name,
        AgentRequest(query=case.query, context=dict(case.context)),
    )
    artifact = _planner_artifact(response)
    validation_errors = artifact.get("validation_errors", []) if artifact else []
    validation_error_count = len(validation_errors) if isinstance(validation_errors, list) else 0
    fallback_used = bool(artifact.get("fallback_used")) if artifact else False
    planner_backend = str(artifact.get("backend") or "unknown") if artifact else "none"
    actual_tool_traces = [trace.name for trace in response.tool_traces]
    expected_tool_traces = list(case.expected_tool_traces or [])
    expected_prefixes = list(case.expected_tool_trace_prefixes or [])
    missing_tool_traces = [
        tool_name for tool_name in expected_tool_traces if tool_name not in actual_tool_traces
    ]
    missing_prefixes = [
        prefix
        for prefix in expected_prefixes
        if not any(tool_name.startswith(prefix) for tool_name in actual_tool_traces)
    ]
    intent_matched = (
        None if case.expected_intent is None else response.intent == case.expected_intent
    )
    plan_steps_matched = response.plan_steps == case.expected_plan_steps
    tool_coverage_matched = not missing_tool_traces and not missing_prefixes
    status = (
        "passed"
        if (
            intent_matched is not False
            and plan_steps_matched
            and tool_coverage_matched
            and not fallback_used
            and validation_error_count == 0
        )
        else "failed"
    )
    return PlannerEvalCaseResult(
        name=case.name,
        agent_name=case.agent_name,
        status=status,
        intent_matched=intent_matched,
        plan_steps_matched=plan_steps_matched,
        tool_coverage_matched=tool_coverage_matched,
        fallback_used=fallback_used,
        validation_error_count=validation_error_count,
        expected_intent=case.expected_intent,
        actual_intent=response.intent,
        expected_plan_steps=list(case.expected_plan_steps),
        actual_plan_steps=list(response.plan_steps),
        expected_tool_traces=expected_tool_traces,
        actual_tool_traces=actual_tool_traces,
        missing_tool_traces=missing_tool_traces,
        missing_tool_trace_prefixes=missing_prefixes,
        planner_backend=planner_backend,
    )


def _planner_artifact(response: AgentResponse) -> dict[str, Any] | None:
    for artifact_name in ("planner", "investigation_plan", "strategy_plan"):
        artifact = response.artifacts.get(artifact_name)
        if isinstance(artifact, dict):
            return artifact
    return None


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline planner golden-set evaluation.")
    parser.add_argument("--output", help="Optional JSON report path.")
    args = parser.parse_args(argv)

    report = run_planner_eval()
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
