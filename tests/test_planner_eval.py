from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from validation.planner_eval import (
    PlannerEvalCase,
    PlannerEvalThresholds,
    load_eval_cases,
    main,
    run_planner_eval,
)


class PlannerEvalTests(unittest.TestCase):
    def test_default_planner_eval_passes_all_golden_cases(self) -> None:
        report = run_planner_eval()

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["summary"]["total"], 5)
        self.assertEqual(report["summary"]["passed"], 5)
        self.assertEqual(report["summary"]["intent_accuracy"], 1.0)
        self.assertEqual(report["summary"]["plan_step_accuracy"], 1.0)
        self.assertEqual(report["summary"]["tool_coverage_rate"], 1.0)
        self.assertEqual(report["summary"]["no_fallback_rate"], 1.0)
        self.assertEqual(report["summary"]["no_validation_error_rate"], 1.0)
        self.assertEqual(report["by_agent"]["copilot"]["total"], 2)
        self.assertEqual(report["by_agent"]["investigation"]["total"], 2)
        self.assertEqual(report["by_agent"]["strategy"]["total"], 1)
        self.assertEqual(report["by_backend"]["rule"]["total"], 5)
        self.assertEqual(report["threshold_failures"], [])

    def test_planner_eval_reports_failed_golden_case(self) -> None:
        report = run_planner_eval(
            [
                PlannerEvalCase(
                    name="wrong_expected_plan",
                    agent_name="investigation",
                    query="为什么巴西信用卡支付失败率从昨晚开始突然升高？",
                    context={"country": "BR", "channel": "credit_card"},
                    expected_intent="metric_investigation",
                    expected_plan_steps=["sql_query"],
                    expected_tool_traces=["metric_snapshot"],
                )
            ]
        )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["summary"]["plan_step_accuracy"], 0.0)
        self.assertEqual(report["by_agent"]["investigation"]["failed"], 1)
        self.assertEqual(report["by_backend"]["rule"]["failed"], 1)
        self.assertFalse(report["cases"][0]["plan_steps_matched"])
        self.assertEqual(
            report["cases"][0]["actual_plan_steps"],
            ["metric_snapshot", "case_lookup", "dashboard_snapshot"],
        )

    def test_planner_eval_fails_when_threshold_is_not_met(self) -> None:
        report = run_planner_eval(
            [
                PlannerEvalCase(
                    name="wrong_expected_plan",
                    agent_name="investigation",
                    query="为什么巴西信用卡支付失败率从昨晚开始突然升高？",
                    context={"country": "BR", "channel": "credit_card"},
                    expected_intent="metric_investigation",
                    expected_plan_steps=["sql_query"],
                    expected_tool_traces=["metric_snapshot"],
                )
            ],
            thresholds=PlannerEvalThresholds(min_plan_step_accuracy=0.5),
        )

        self.assertEqual(report["status"], "failed")
        self.assertIn("plan_step_accuracy=0.0000 < 0.5000", report["threshold_failures"])

    def test_planner_eval_loads_cases_from_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cases_path = Path(tmp_dir) / "planner-cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "name": "metric_case",
                                "agent_name": "investigation",
                                "query": "为什么巴西信用卡支付失败率从昨晚开始突然升高？",
                                "context": {"country": "BR", "channel": "credit_card"},
                                "expected_intent": "metric_investigation",
                                "expected_plan_steps": [
                                    "metric_snapshot",
                                    "case_lookup",
                                    "dashboard_snapshot",
                                ],
                                "expected_tool_traces": [
                                    "metric_snapshot",
                                    "case_lookup",
                                    "dashboard_snapshot",
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            cases = load_eval_cases(cases_path)
            report = run_planner_eval(cases)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].name, "metric_case")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["summary"]["total"], 1)

    def test_planner_eval_rejects_empty_cases_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cases_path = Path(tmp_dir) / "planner-cases.json"
            cases_path.write_text(json.dumps({"cases": []}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "non-empty cases list"):
                load_eval_cases(cases_path)

    def test_planner_eval_cli_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "planner-eval.json"

            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = main(["--output", str(output_path)])

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "passed")

    def test_planner_eval_cli_supports_cases_file_and_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cases_path = Path(tmp_dir) / "planner-cases.json"
            output_path = Path(tmp_dir) / "planner-eval.json"
            cases_path.write_text(
                json.dumps(
                    [
                        {
                            "name": "strategy_case",
                            "agent_name": "strategy",
                            "query": "请评估策略 STRAT-001 是否应该调整阈值",
                            "context": {"strategy_id": "STRAT-001"},
                            "expected_intent": "strategy_tool_plan",
                            "expected_plan_steps": [
                                "strategy_profile",
                                "strategy_simulation",
                                "graph_relation",
                                "rule_explain",
                            ],
                            "expected_tool_traces": [
                                "strategy_profile",
                                "strategy_simulation",
                                "graph_relation",
                                "rule_explain",
                            ],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--cases-file",
                        str(cases_path),
                        "--min-plan-step-accuracy",
                        "1.0",
                        "--output",
                        str(output_path),
                    ]
                )

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["summary"]["total"], 1)
        self.assertEqual(payload["thresholds"]["min_plan_step_accuracy"], 1.0)

    def test_makefile_exposes_planner_eval_target(self) -> None:
        payload = Path("Makefile").read_text(encoding="utf-8")

        self.assertIn("validate-planner-eval:", payload)
        self.assertIn("$(PYTHON) -m validation.planner_eval", payload)


if __name__ == "__main__":
    unittest.main()
