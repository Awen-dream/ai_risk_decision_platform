from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from validation.planner_eval import PlannerEvalCase, main, run_planner_eval


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
        self.assertFalse(report["cases"][0]["plan_steps_matched"])
        self.assertEqual(
            report["cases"][0]["actual_plan_steps"],
            ["metric_snapshot", "case_lookup", "dashboard_snapshot"],
        )

    def test_planner_eval_cli_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "planner-eval.json"

            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = main(["--output", str(output_path)])

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "passed")

    def test_makefile_exposes_planner_eval_target(self) -> None:
        payload = Path("Makefile").read_text(encoding="utf-8")

        self.assertIn("validate-planner-eval:", payload)
        self.assertIn("$(PYTHON) -m validation.planner_eval", payload)


if __name__ == "__main__":
    unittest.main()
