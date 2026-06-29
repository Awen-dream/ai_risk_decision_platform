from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from validation.signoff_manifest import build_signoff_manifest
from validation.signoff_evidence import validate_signoff_evidence


class SignoffEvidenceTests(unittest.TestCase):
    def test_valid_signoff_evidence_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir)
            _write_signoff_reports(report_dir)

            report = validate_signoff_evidence(
                report_dir,
                expected_risk_base_url="https://risk-staging.example.com",
                expected_agent_base_url="https://agent-staging.example.com",
            )

        self.assertEqual(report["status"], "passed")

    def test_postgres_skip_requires_explicit_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir)
            _write_signoff_reports(report_dir, postgres_status="skipped")

            rejected = validate_signoff_evidence(report_dir)
            accepted = validate_signoff_evidence(
                report_dir,
                allow_postgres_skipped=True,
            )

        self.assertEqual(rejected["status"], "failed")
        self.assertEqual(accepted["status"], "passed")

    def test_required_central_audit_evidence_must_be_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir)
            _write_signoff_reports(report_dir)

            report = validate_signoff_evidence(
                report_dir,
                require_central_audit=True,
            )

        self.assertEqual(report["status"], "failed")
        self.assertIn("central audit", _failed_details(report))

    def test_release_metadata_can_be_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir)
            _write_signoff_reports(report_dir)

            rejected = validate_signoff_evidence(
                report_dir,
                require_release_metadata=True,
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir)
            _write_signoff_reports(
                report_dir,
                release_metadata={
                    "environment": "staging",
                    "release_id": "risk-agent-2026.06.20",
                    "change_id": "CHG-12345",
                    "owner": "risk-platform",
                    "approver": "risk-ops",
                },
            )

            accepted = validate_signoff_evidence(
                report_dir,
                require_release_metadata=True,
            )

        self.assertEqual(rejected["status"], "failed")
        self.assertIn("release metadata", _failed_details(rejected))
        self.assertEqual(accepted["status"], "passed")

    def test_required_planner_eval_evidence_must_be_present_and_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir)
            _write_signoff_reports(report_dir)

            rejected = validate_signoff_evidence(
                report_dir,
                require_planner_eval=True,
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir)
            _write_signoff_reports(report_dir, include_planner_eval=True)

            accepted = validate_signoff_evidence(
                report_dir,
                require_planner_eval=True,
            )

        self.assertEqual(rejected["status"], "failed")
        self.assertIn("planner eval", _failed_details(rejected))
        self.assertEqual(accepted["status"], "passed")

    def test_planner_eval_evidence_rejects_v2_metric_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir)
            planner_eval = _planner_eval_report()
            planner_eval["summary"]["evidence_gap_accuracy"] = 0.5
            _write_signoff_reports(
                report_dir,
                include_planner_eval=True,
                planner_eval_report=planner_eval,
            )

            report = validate_signoff_evidence(
                report_dir,
                require_planner_eval=True,
            )

        self.assertEqual(report["status"], "failed")
        self.assertIn("evidence_gap_accuracy", _failed_details(report))

    def test_secret_like_values_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir)
            _write_signoff_reports(
                report_dir,
                extra_summary_inputs={
                    "postgres_dsn": "postgresql://risk:super-secret@db.internal/risk",
                },
            )

            report = validate_signoff_evidence(report_dir)

        self.assertEqual(report["status"], "failed")
        self.assertIn("secret", _failed_details(report))

    def test_manifest_detects_tampered_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir)
            _write_signoff_reports(report_dir)
            (report_dir / "readiness.json").write_text(
                json.dumps({"status": "passed", "summary": {"total": 0}}) + "\n",
                encoding="utf-8",
            )

            report = validate_signoff_evidence(report_dir)

        self.assertEqual(report["status"], "failed")
        self.assertIn("sha256 mismatch", _failed_details(report))


def _write_signoff_reports(
    report_dir: Path,
    *,
    postgres_status: str = "passed",
    central_audit_required: bool = False,
    include_central_audit_check: bool = False,
    extra_summary_inputs: dict[str, object] | None = None,
    release_metadata: dict[str, object] | None = None,
    include_planner_eval: bool = False,
    planner_eval_report: dict[str, object] | None = None,
) -> None:
    postgres_summary = _summary(total=0 if postgres_status == "skipped" else 4, status=postgres_status)
    preflight = _report(total=4)
    readiness = _report(total=7)
    staging_checks = [_check(f"staging.check.{index}") for index in range(17)]
    if include_central_audit_check:
        staging_checks.append(_check("central_audit.mirrored_events"))
    staging = _report(total=len(staging_checks), checks=staging_checks)
    inputs: dict[str, object] = {
        "risk_base_url": "https://risk-staging.example.com",
        "agent_base_url": "https://agent-staging.example.com",
        "postgres_required": postgres_status != "skipped",
        "central_audit_query_required": central_audit_required,
    }
    inputs.update(extra_summary_inputs or {})
    summary = {
        "status": "passed",
        "generated_at": "2026-06-18T00:00:00Z",
        "report_dir": str(report_dir),
        "inputs": inputs,
        "reports": {
            "signoff_preflight": {
                "status": "passed",
                "summary": preflight["summary"],
            },
            "postgres_smoke": {
                "status": postgres_status,
                "summary": postgres_summary,
            },
            "readiness": {
                "status": "passed",
                "summary": readiness["summary"],
            },
            "staging_validation": {
                "status": "passed",
                "summary": staging["summary"],
            },
        },
        "failed_reports": [],
    }
    if release_metadata is not None:
        summary["release"] = release_metadata
    manifest_files = None
    if include_planner_eval:
        _write_json(report_dir / "planner-eval.json", planner_eval_report or _planner_eval_report())
        manifest_files = (
            "signoff-preflight.json",
            "postgres-smoke.json",
            "readiness.json",
            "staging-validation.json",
            "signoff-summary.json",
            "planner-eval.json",
        )
    _write_json(report_dir / "signoff-preflight.json", preflight)
    _write_json(report_dir / "signoff-summary.json", summary)
    _write_json(
        report_dir / "postgres-smoke.json",
        {
            "status": postgres_status,
            "generated_at": "2026-06-18T00:00:00Z",
            "summary": postgres_summary,
            "checks": [] if postgres_status == "skipped" else [_check(f"postgres.check.{i}") for i in range(4)],
        },
    )
    _write_json(report_dir / "readiness.json", readiness)
    _write_json(report_dir / "staging-validation.json", staging)
    _write_json(
        report_dir / "signoff-manifest.json",
        build_signoff_manifest(report_dir, files=manifest_files)
        if manifest_files is not None
        else build_signoff_manifest(report_dir),
    )


def _report(
    *,
    total: int,
    checks: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    checks = checks or [_check(f"check.{index}") for index in range(total)]
    return {
        "status": "passed",
        "generated_at": "2026-06-18T00:00:00Z",
        "summary": _summary(total=total),
        "checks": checks,
    }


def _summary(*, total: int, status: str = "passed") -> dict[str, int]:
    passed = 0 if status == "skipped" else total
    return {"total": total, "passed": passed, "failed": 0}


def _check(name: str) -> dict[str, object]:
    return {
        "name": name,
        "status": "passed",
        "detail": "ok",
        "duration_ms": 0.0,
    }


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _planner_eval_report() -> dict[str, object]:
    return {
        "status": "passed",
        "generated_at": "2026-06-18T00:00:00Z",
        "summary": {
            "total": 7,
            "passed": 7,
            "failed": 0,
            "intermediate_state_coverage_rate": 1.0,
            "tool_reason_coverage_rate": 1.0,
            "evidence_gap_accuracy": 1.0,
        },
        "threshold_failures": [],
    }


def _failed_details(report: dict[str, object]) -> str:
    checks = report["checks"]
    assert isinstance(checks, list)
    return "\n".join(
        str(check["detail"])
        for check in checks
        if isinstance(check, dict) and check.get("status") == "failed"
    )


if __name__ == "__main__":
    unittest.main()
