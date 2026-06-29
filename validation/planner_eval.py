from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import build_demo_runtime
from core.models import AgentRequest, AgentResponse


QUALITY_METRICS = (
    "intent_accuracy",
    "plan_step_accuracy",
    "tool_coverage_rate",
    "intermediate_state_coverage_rate",
    "tool_reason_coverage_rate",
    "evidence_gap_accuracy",
    "global_planning_coverage_rate",
    "no_fallback_rate",
    "no_validation_error_rate",
)


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
    expected_evidence_gap_sources: list[str] | None = None
    require_intermediate_state: bool = True
    require_global_planning: bool = False


@dataclass(frozen=True)
class PlannerEvalThresholds:
    min_intent_accuracy: float = 1.0
    min_plan_step_accuracy: float = 1.0
    min_tool_coverage_rate: float = 1.0
    min_intermediate_state_coverage_rate: float = 1.0
    min_tool_reason_coverage_rate: float = 1.0
    min_evidence_gap_accuracy: float = 1.0
    min_global_planning_coverage_rate: float = 1.0
    min_no_fallback_rate: float = 1.0
    min_no_validation_error_rate: float = 1.0


@dataclass
class PlannerEvalCaseResult:
    name: str
    agent_name: str
    status: str
    intent_matched: bool | None
    plan_steps_matched: bool
    tool_coverage_matched: bool
    intermediate_state_matched: bool
    tool_reason_coverage_matched: bool
    evidence_gap_matched: bool
    global_planning_matched: bool
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
    expected_evidence_gap_sources: list[str]
    actual_evidence_gap_sources: list[str]
    missing_evidence_gap_sources: list[str]
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
        require_intermediate_state=False,
        require_global_planning=True,
    ),
    PlannerEvalCase(
        name="copilot_metric_anomaly",
        agent_name="copilot",
        query="为什么巴西信用卡支付失败率从昨晚开始突然升高？",
        context={},
        expected_intent="metric_anomaly",
        expected_plan_steps=["调查"],
        expected_tool_trace_prefixes=["调查::"],
        require_intermediate_state=False,
        require_global_planning=True,
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
    PlannerEvalCase(
        name="graph_default",
        agent_name="graph",
        query="请分析用户 U10001 是否属于团伙网络",
        context={"entity_id": "U10001"},
        expected_intent="graph_tool_plan",
        expected_plan_steps=["graph_relation"],
        expected_tool_traces=["graph_relation"],
    ),
    PlannerEvalCase(
        name="graph_missing_relation_evidence_gap",
        agent_name="graph",
        query="请分析用户 MISSING 是否属于团伙网络",
        context={"entity_id": "MISSING"},
        expected_intent="graph_tool_plan",
        expected_plan_steps=["graph_relation"],
        expected_tool_traces=["graph_relation"],
        expected_evidence_gap_sources=["graph_relation"],
    ),
]


def run_planner_eval(
    cases: list[PlannerEvalCase] | None = None,
    thresholds: PlannerEvalThresholds | None = None,
    baseline_report: dict[str, Any] | None = None,
    max_allowed_regression: float = 0.0,
) -> dict[str, Any]:
    runtime = build_demo_runtime()
    eval_cases = cases or list(DEFAULT_EVAL_CASES)
    eval_thresholds = thresholds or PlannerEvalThresholds()
    results = [_run_case(runtime, case) for case in eval_cases]
    summary = _summarize_results(results)
    by_agent = _summarize_by_agent(results)
    by_backend = _summarize_by_backend(results)
    threshold_failures = _threshold_failures(summary, eval_thresholds)
    baseline_comparison = (
        _compare_baseline(
            summary,
            by_agent,
            by_backend,
            baseline_report,
            max_allowed_regression=max_allowed_regression,
        )
        if baseline_report is not None
        else None
    )
    baseline_failures = (
        baseline_comparison.get("failures", []) if baseline_comparison else []
    )
    report = {
        "status": (
            "passed"
            if summary["failed"] == 0 and not threshold_failures and not baseline_failures
            else "failed"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": summary,
        "by_agent": by_agent,
        "by_backend": by_backend,
        "thresholds": asdict(eval_thresholds),
        "threshold_failures": threshold_failures,
        "baseline_comparison": baseline_comparison,
        "cases": [asdict(result) for result in results],
    }
    return report


def load_eval_cases(path: Path) -> list[PlannerEvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        raw_cases = payload.get("cases")
    else:
        raw_cases = payload
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("planner eval cases file must contain a non-empty cases list")
    return [_case_from_payload(item, index) for index, item in enumerate(raw_cases)]


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
    actual_gap_sources = [gap.source for gap in response.evidence_gap]
    expected_tool_traces = list(case.expected_tool_traces or [])
    expected_prefixes = list(case.expected_tool_trace_prefixes or [])
    expected_gap_sources = list(case.expected_evidence_gap_sources or [])
    missing_tool_traces = [
        tool_name for tool_name in expected_tool_traces if tool_name not in actual_tool_traces
    ]
    missing_prefixes = [
        prefix
        for prefix in expected_prefixes
        if not any(tool_name.startswith(prefix) for tool_name in actual_tool_traces)
    ]
    missing_gap_sources = [
        source for source in expected_gap_sources if source not in actual_gap_sources
    ]
    intent_matched = (
        None if case.expected_intent is None else response.intent == case.expected_intent
    )
    plan_steps_matched = response.plan_steps == case.expected_plan_steps
    tool_coverage_matched = not missing_tool_traces and not missing_prefixes
    intermediate_state_matched = (
        True
        if not case.require_intermediate_state
        else bool(response.thought_summary and response.artifacts.get("tool_using_plan"))
    )
    selected_tool_reasons = {
        reason.tool for reason in response.tool_selection_reason if reason.selected
    }
    tool_reason_coverage_matched = (
        True
        if not case.require_intermediate_state
        else all(step in selected_tool_reasons for step in response.plan_steps)
    )
    evidence_gap_matched = (
        not missing_gap_sources
        and (
            bool(expected_gap_sources)
            or not actual_gap_sources
        )
    )
    global_planning_matched = (
        True
        if not case.require_global_planning
        else _has_global_planning_artifacts(response)
    )
    status = (
        "passed"
        if (
            intent_matched is not False
            and plan_steps_matched
            and tool_coverage_matched
            and intermediate_state_matched
            and tool_reason_coverage_matched
            and evidence_gap_matched
            and global_planning_matched
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
        intermediate_state_matched=intermediate_state_matched,
        tool_reason_coverage_matched=tool_reason_coverage_matched,
        evidence_gap_matched=evidence_gap_matched,
        global_planning_matched=global_planning_matched,
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
        expected_evidence_gap_sources=expected_gap_sources,
        actual_evidence_gap_sources=actual_gap_sources,
        missing_evidence_gap_sources=missing_gap_sources,
        planner_backend=planner_backend,
    )


def _has_global_planning_artifacts(response: AgentResponse) -> bool:
    global_plan = response.artifacts.get("global_plan")
    evidence_graph = response.artifacts.get("evidence_graph")
    working_memory = response.artifacts.get("working_memory")
    if not all(isinstance(item, dict) for item in (global_plan, evidence_graph, working_memory)):
        return False
    steps = global_plan.get("steps", [])  # type: ignore[union-attr]
    graph_summary = evidence_graph.get("summary", {})  # type: ignore[union-attr]
    return (
        global_plan.get("version") == "v3a"  # type: ignore[union-attr]
        and evidence_graph.get("version") == "v3a"  # type: ignore[union-attr]
        and working_memory.get("version") == "v3a"  # type: ignore[union-attr]
        and isinstance(steps, list)
        and len(steps) == len(response.plan_steps)
        and isinstance(graph_summary, dict)
        and int(graph_summary.get("node_count", 0) or 0) > 0
    )


def _planner_artifact(response: AgentResponse) -> dict[str, Any] | None:
    for artifact_name in (
        "planner",
        "tool_using_plan",
        "investigation_plan",
        "strategy_plan",
        "graph_plan",
    ):
        artifact = response.artifacts.get(artifact_name)
        if isinstance(artifact, dict):
            return artifact
    return None


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


def _summarize_results(results: list[PlannerEvalCaseResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(result.status == "passed" for result in results)
    intent_cases = [result for result in results if result.intent_matched is not None]
    intent_passed = sum(result.intent_matched is True for result in intent_cases)
    return {
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
        "intermediate_state_coverage_rate": _ratio(
            sum(result.intermediate_state_matched for result in results),
            total,
        ),
        "tool_reason_coverage_rate": _ratio(
            sum(result.tool_reason_coverage_matched for result in results),
            total,
        ),
        "evidence_gap_accuracy": _ratio(
            sum(result.evidence_gap_matched for result in results),
            total,
        ),
        "global_planning_coverage_rate": _ratio(
            sum(result.global_planning_matched for result in results),
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
    }


def _compare_baseline(
    summary: dict[str, Any],
    by_agent: dict[str, dict[str, Any]],
    by_backend: dict[str, dict[str, Any]],
    baseline_report: dict[str, Any],
    *,
    max_allowed_regression: float,
) -> dict[str, Any]:
    comparisons = {
        "summary": _compare_summary_metrics(
            summary,
            _baseline_mapping(baseline_report, "summary"),
        ),
        "by_agent": _compare_grouped_metrics(
            by_agent,
            _baseline_mapping(baseline_report, "by_agent"),
        ),
        "by_backend": _compare_grouped_metrics(
            by_backend,
            _baseline_mapping(baseline_report, "by_backend"),
        ),
    }
    failures: list[str] = []
    for scope, scoped_comparison in comparisons.items():
        failures.extend(
            _baseline_failures(
                scope,
                scoped_comparison,
                max_allowed_regression=max_allowed_regression,
            )
        )
    return {
        "max_allowed_regression": max_allowed_regression,
        **comparisons,
        "failures": failures,
    }


def _compare_summary_metrics(
    current_summary: dict[str, Any],
    baseline_summary: dict[str, Any],
) -> dict[str, dict[str, float]]:
    metrics: dict[str, dict[str, float]] = {}
    for metric_name in QUALITY_METRICS:
        current = float(current_summary.get(metric_name, 0.0))
        baseline = float(baseline_summary.get(metric_name, 0.0))
        delta = current - baseline
        regression = max(0.0, baseline - current)
        metrics[metric_name] = {
            "baseline": baseline,
            "current": current,
            "delta": delta,
            "regression": regression,
        }
    return metrics


def _compare_grouped_metrics(
    current_groups: dict[str, dict[str, Any]],
    baseline_groups: dict[str, Any],
) -> dict[str, dict[str, dict[str, float]]]:
    comparisons: dict[str, dict[str, dict[str, float]]] = {}
    for group_name, current_summary in sorted(current_groups.items()):
        baseline_summary = baseline_groups.get(group_name)
        if isinstance(baseline_summary, dict):
            comparisons[group_name] = _compare_summary_metrics(
                current_summary,
                baseline_summary,
            )
    return comparisons


def _baseline_failures(
    scope: str,
    comparison: dict[str, Any],
    *,
    max_allowed_regression: float,
) -> list[str]:
    failures: list[str] = []
    if scope == "summary":
        for metric_name, metric in comparison.items():
            regression = float(metric["regression"])
            if regression > max_allowed_regression:
                failures.append(
                    f"summary.{metric_name} regression={regression:.4f} > {max_allowed_regression:.4f}"
                )
        return failures
    for group_name, group_metrics in comparison.items():
        for metric_name, metric in group_metrics.items():
            regression = float(metric["regression"])
            if regression > max_allowed_regression:
                failures.append(
                    f"{scope}.{group_name}.{metric_name} regression={regression:.4f} > {max_allowed_regression:.4f}"
                )
    return failures


def _baseline_mapping(report: dict[str, Any], key: str) -> dict[str, Any]:
    payload = report.get(key)
    if not isinstance(payload, dict):
        if key == "summary":
            raise ValueError("baseline planner eval report must contain a summary object")
        return {}
    return payload


def _summarize_by_agent(results: list[PlannerEvalCaseResult]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[PlannerEvalCaseResult]] = {}
    for result in results:
        grouped.setdefault(result.agent_name, []).append(result)
    return {
        agent_name: _summarize_results(agent_results)
        for agent_name, agent_results in sorted(grouped.items())
    }


def _summarize_by_backend(results: list[PlannerEvalCaseResult]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[PlannerEvalCaseResult]] = {}
    for result in results:
        grouped.setdefault(result.planner_backend, []).append(result)
    return {
        backend: _summarize_results(backend_results)
        for backend, backend_results in sorted(grouped.items())
    }


def _case_from_payload(payload: Any, index: int) -> PlannerEvalCase:
    if not isinstance(payload, dict):
        raise ValueError(f"planner eval case at index {index} must be an object")
    required_fields = ("name", "agent_name", "query", "expected_plan_steps")
    missing = [field for field in required_fields if field not in payload]
    if missing:
        raise ValueError(f"planner eval case at index {index} missing fields: {missing}")
    context = payload.get("context", {})
    if not isinstance(context, dict):
        raise ValueError(f"planner eval case {payload['name']} context must be an object")
    return PlannerEvalCase(
        name=str(payload["name"]),
        agent_name=str(payload["agent_name"]),
        query=str(payload["query"]),
        context=dict(context),
        expected_intent=_optional_str(payload.get("expected_intent")),
        expected_plan_steps=_string_list(payload["expected_plan_steps"], "expected_plan_steps"),
        expected_tool_traces=_optional_string_list(
            payload.get("expected_tool_traces"),
            "expected_tool_traces",
        ),
        expected_tool_trace_prefixes=_optional_string_list(
            payload.get("expected_tool_trace_prefixes"),
            "expected_tool_trace_prefixes",
        ),
        expected_evidence_gap_sources=_optional_string_list(
            payload.get("expected_evidence_gap_sources"),
            "expected_evidence_gap_sources",
        ),
        require_intermediate_state=bool(payload.get("require_intermediate_state", True)),
        require_global_planning=bool(payload.get("require_global_planning", False)),
    )


def _threshold_failures(
    summary: dict[str, Any],
    thresholds: PlannerEvalThresholds,
) -> list[str]:
    checks = {
        "intent_accuracy": thresholds.min_intent_accuracy,
        "plan_step_accuracy": thresholds.min_plan_step_accuracy,
        "tool_coverage_rate": thresholds.min_tool_coverage_rate,
        "intermediate_state_coverage_rate": thresholds.min_intermediate_state_coverage_rate,
        "tool_reason_coverage_rate": thresholds.min_tool_reason_coverage_rate,
        "evidence_gap_accuracy": thresholds.min_evidence_gap_accuracy,
        "global_planning_coverage_rate": thresholds.min_global_planning_coverage_rate,
        "no_fallback_rate": thresholds.min_no_fallback_rate,
        "no_validation_error_rate": thresholds.min_no_validation_error_rate,
    }
    failures: list[str] = []
    for metric_name, minimum in checks.items():
        actual = float(summary.get(metric_name, 0.0))
        if actual < minimum:
            failures.append(f"{metric_name}={actual:.4f} < {minimum:.4f}")
    return failures


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_string_list(value: Any, field_name: str) -> list[str] | None:
    if value is None:
        return None
    return _string_list(value, field_name)


def _string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return [str(item) for item in value]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline planner golden-set evaluation.")
    parser.add_argument("--cases-file", help="Optional JSON golden-set cases file.")
    parser.add_argument("--min-intent-accuracy", type=float, default=1.0)
    parser.add_argument("--min-plan-step-accuracy", type=float, default=1.0)
    parser.add_argument("--min-tool-coverage-rate", type=float, default=1.0)
    parser.add_argument("--min-intermediate-state-coverage-rate", type=float, default=1.0)
    parser.add_argument("--min-tool-reason-coverage-rate", type=float, default=1.0)
    parser.add_argument("--min-evidence-gap-accuracy", type=float, default=1.0)
    parser.add_argument("--min-global-planning-coverage-rate", type=float, default=1.0)
    parser.add_argument("--min-no-fallback-rate", type=float, default=1.0)
    parser.add_argument("--min-no-validation-error-rate", type=float, default=1.0)
    parser.add_argument("--baseline-file", help="Optional previous planner eval report.")
    parser.add_argument("--max-allowed-regression", type=float, default=0.0)
    parser.add_argument("--output", help="Optional JSON report path.")
    args = parser.parse_args(argv)

    cases = load_eval_cases(Path(args.cases_file)) if args.cases_file else None
    baseline_report = (
        json.loads(Path(args.baseline_file).read_text(encoding="utf-8"))
        if args.baseline_file
        else None
    )
    thresholds = PlannerEvalThresholds(
        min_intent_accuracy=args.min_intent_accuracy,
        min_plan_step_accuracy=args.min_plan_step_accuracy,
        min_tool_coverage_rate=args.min_tool_coverage_rate,
        min_intermediate_state_coverage_rate=args.min_intermediate_state_coverage_rate,
        min_tool_reason_coverage_rate=args.min_tool_reason_coverage_rate,
        min_evidence_gap_accuracy=args.min_evidence_gap_accuracy,
        min_global_planning_coverage_rate=args.min_global_planning_coverage_rate,
        min_no_fallback_rate=args.min_no_fallback_rate,
        min_no_validation_error_rate=args.min_no_validation_error_rate,
    )
    report = run_planner_eval(
        cases=cases,
        thresholds=thresholds,
        baseline_report=baseline_report,
        max_allowed_regression=args.max_allowed_regression,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
