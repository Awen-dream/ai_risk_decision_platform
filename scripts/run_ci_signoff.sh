#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

MAKE_BIN="${MAKE:-make}"
TIMESTAMP="$("$PYTHON_BIN" -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))")"
REPORT_ROOT="${AI_RISK_CI_SIGNOFF_REPORT_ROOT:-.data/reports}"
REPORT_DIR="${AI_RISK_CI_SIGNOFF_REPORT_DIR:-${REPORT_ROOT}/ci-signoff-${TIMESTAMP}}"

GIT_SHORT_SHA="$("$PYTHON_BIN" - <<'PY'
import subprocess

result = subprocess.run(
    ["git", "rev-parse", "--short", "HEAD"],
    check=False,
    capture_output=True,
    text=True,
    timeout=3,
)
print(result.stdout.strip() if result.returncode == 0 else "unknown")
PY
)"

RELEASE_ENVIRONMENT="${AI_RISK_SIGNOFF_ENVIRONMENT:-ci-local}"
RELEASE_ID="${AI_RISK_SIGNOFF_RELEASE_ID:-${AI_RISK_CI_SIGNOFF_RELEASE_ID:-ci-local-signoff-${TIMESTAMP}}}"
CHANGE_ID="${AI_RISK_SIGNOFF_CHANGE_ID:-${AI_RISK_CI_SIGNOFF_CHANGE_ID:-${GIT_SHORT_SHA}}}"
SIGNOFF_OWNER="${AI_RISK_SIGNOFF_OWNER:-${AI_RISK_CI_SIGNOFF_OWNER:-ci}}"
SIGNOFF_APPROVER="${AI_RISK_SIGNOFF_APPROVER:-${AI_RISK_CI_SIGNOFF_APPROVER:-ci}}"
CURRENT_GATE="setup"

cd "$ROOT_DIR"
mkdir -p "$REPORT_DIR"

write_failure_summary() {
  local exit_code="$1"
  if [[ -f "${REPORT_DIR}/ci-signoff-summary.json" ]]; then
    return
  fi
  "$PYTHON_BIN" - "$REPORT_DIR" "$RELEASE_ENVIRONMENT" "$RELEASE_ID" "$CHANGE_ID" "$SIGNOFF_OWNER" "$SIGNOFF_APPROVER" "$CURRENT_GATE" "$exit_code" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

report_dir = Path(sys.argv[1])
release = {
    "environment": sys.argv[2],
    "release_id": sys.argv[3],
    "change_id": sys.argv[4],
    "owner": sys.argv[5],
    "approver": sys.argv[6],
}
failed_gate = sys.argv[7]
exit_code = int(sys.argv[8])
summary = {
    "status": "failed",
    "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "report_dir": str(report_dir),
    "release": release,
    "failed_gate": failed_gate,
    "exit_code": exit_code,
    "gates": {
        "unit_tests": "unknown",
        "planner_eval": "unknown",
        "local_signoff": "unknown",
        "signoff_evidence": "unknown",
        "archive_verification": "unknown",
    },
    "artifacts": {
        "archive": str(report_dir / "signoff-archive.tar.gz"),
        "checksum": str(report_dir / "signoff-archive.sha256"),
        "planner_eval": str(report_dir / "planner-eval.json"),
        "ci_summary": str(report_dir / "ci-signoff-summary.json"),
    },
}
(report_dir / "ci-signoff-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY
}

on_error() {
  local exit_code="$?"
  write_failure_summary "$exit_code"
  exit "$exit_code"
}

trap on_error ERR

echo "==> unit-tests"
CURRENT_GATE="unit_tests"
"$PYTHON_BIN" -m unittest discover -v

echo "==> planner-eval"
CURRENT_GATE="planner_eval"
"$MAKE_BIN" validate-planner-eval PLANNER_EVAL_ARGS="--output ${REPORT_DIR}/planner-eval.json"

echo "==> local-signoff-with-release-metadata"
CURRENT_GATE="local_signoff"
AI_RISK_SIGNOFF_REQUIRE_RELEASE_METADATA=true \
AI_RISK_SIGNOFF_ENVIRONMENT="$RELEASE_ENVIRONMENT" \
AI_RISK_SIGNOFF_RELEASE_ID="$RELEASE_ID" \
AI_RISK_SIGNOFF_CHANGE_ID="$CHANGE_ID" \
AI_RISK_SIGNOFF_OWNER="$SIGNOFF_OWNER" \
AI_RISK_SIGNOFF_APPROVER="$SIGNOFF_APPROVER" \
AI_RISK_LOCAL_SIGNOFF_REPORT_DIR="$REPORT_DIR" \
  "$MAKE_BIN" signoff-local

echo "==> ci-signoff-summary"
CURRENT_GATE="ci_summary"
"$PYTHON_BIN" - "$REPORT_DIR" "$RELEASE_ENVIRONMENT" "$RELEASE_ID" "$CHANGE_ID" "$SIGNOFF_OWNER" "$SIGNOFF_APPROVER" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

report_dir = Path(sys.argv[1])
release = {
    "environment": sys.argv[2],
    "release_id": sys.argv[3],
    "change_id": sys.argv[4],
    "owner": sys.argv[5],
    "approver": sys.argv[6],
}

signoff_summary = json.loads((report_dir / "signoff-summary.json").read_text(encoding="utf-8"))
signoff_evidence = json.loads((report_dir / "signoff-evidence.json").read_text(encoding="utf-8"))
planner_eval = json.loads((report_dir / "planner-eval.json").read_text(encoding="utf-8"))
checksum_path = report_dir / "signoff-archive.sha256"
archive_path = report_dir / "signoff-archive.tar.gz"
archive_checksum = checksum_path.read_text(encoding="utf-8").split()[0]

summary = {
    "status": "passed",
    "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "report_dir": str(report_dir),
    "release": release,
    "gates": {
        "unit_tests": "passed",
        "planner_eval": planner_eval.get("status"),
        "local_signoff": signoff_summary.get("status"),
        "signoff_evidence": signoff_evidence.get("status"),
        "archive_verification": "passed",
    },
    "artifacts": {
        "archive": str(archive_path),
        "checksum": str(checksum_path),
        "archive_sha256": archive_checksum,
        "planner_eval": str(report_dir / "planner-eval.json"),
        "ci_summary": str(report_dir / "ci-signoff-summary.json"),
    },
}
(report_dir / "ci-signoff-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps(summary, ensure_ascii=False, indent=2))
PY
