#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

TIMESTAMP="$("$PYTHON_BIN" -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))")"
REPORT_DIR="${AI_RISK_SIGNOFF_REPORT_DIR:-.data/reports/staging-signoff-${TIMESTAMP}}"
RISK_BASE_URL="${AI_RISK_SIGNOFF_RISK_BASE_URL:-${RISK_BASE_URL:-}}"
AGENT_BASE_URL="${AI_RISK_SIGNOFF_AGENT_BASE_URL:-${AGENT_BASE_URL:-}}"
ADMIN_HEADER="${AI_RISK_ADMIN_AUTH_HEADER:-X-Admin-Token}"
ADMIN_TOKEN_FILE="${AI_RISK_ADMIN_AUTH_TOKEN_FILE:-}"
POSTGRES_DSN_FILE="${AI_RISK_POSTGRES_DSN_FILE:-}"
CENTRAL_AUDIT_BASE_URL="${AI_RISK_SIGNOFF_CENTRAL_AUDIT_BASE_URL:-${AI_RISK_AUDIT_CENTRAL_QUERY_URL:-}}"
CENTRAL_AUDIT_HEADER="${AI_RISK_AUDIT_CENTRAL_AUTH_HEADER:-Authorization}"
CENTRAL_AUDIT_TOKEN_FILE="${AI_RISK_AUDIT_CENTRAL_AUTH_TOKEN_FILE:-}"
REQUIRE_POSTGRES="${AI_RISK_SIGNOFF_REQUIRE_POSTGRES:-true}"
REQUIRE_CENTRAL_AUDIT="${AI_RISK_SIGNOFF_REQUIRE_CENTRAL_AUDIT:-false}"
SIGNOFF_FAILED=0

require_value() {
  local name="$1"
  local value="$2"
  if [[ -z "$value" ]]; then
    echo "Missing required value: ${name}" >&2
    exit 2
  fi
}

run_step() {
  local name="$1"
  shift
  echo "==> ${name}"
  set +e
  "$@"
  local exit_code=$?
  set -e
  if [[ "$exit_code" -ne 0 ]]; then
    echo "Step failed: ${name} (exit ${exit_code})" >&2
    SIGNOFF_FAILED=1
  fi
}

cd "$ROOT_DIR"
mkdir -p "$REPORT_DIR"

require_value "RISK_BASE_URL or AI_RISK_SIGNOFF_RISK_BASE_URL" "$RISK_BASE_URL"
require_value "AGENT_BASE_URL or AI_RISK_SIGNOFF_AGENT_BASE_URL" "$AGENT_BASE_URL"
require_value "AI_RISK_ADMIN_AUTH_TOKEN_FILE" "$ADMIN_TOKEN_FILE"

PREFLIGHT_ARGS=(
  "--risk-base-url" "$RISK_BASE_URL"
  "--agent-base-url" "$AGENT_BASE_URL"
  "--admin-token-file" "$ADMIN_TOKEN_FILE"
  "--output" "${REPORT_DIR}/signoff-preflight.json"
)
if [[ -n "$POSTGRES_DSN_FILE" ]]; then
  PREFLIGHT_ARGS+=("--postgres-dsn-file" "$POSTGRES_DSN_FILE")
fi
if [[ "$REQUIRE_POSTGRES" == "true" ]]; then
  PREFLIGHT_ARGS+=("--postgres-required")
fi
if [[ -n "$CENTRAL_AUDIT_BASE_URL" ]]; then
  PREFLIGHT_ARGS+=("--central-audit-base-url" "$CENTRAL_AUDIT_BASE_URL")
fi
if [[ -n "$CENTRAL_AUDIT_TOKEN_FILE" ]]; then
  PREFLIGHT_ARGS+=("--central-audit-token-file" "$CENTRAL_AUDIT_TOKEN_FILE")
fi
if [[ "$REQUIRE_CENTRAL_AUDIT" == "true" ]]; then
  PREFLIGHT_ARGS+=("--central-audit-required")
fi

run_step "signoff-preflight" \
  "$PYTHON_BIN" -m validation.signoff_preflight "${PREFLIGHT_ARGS[@]}"

POSTGRES_ARGS=("--output" "${REPORT_DIR}/postgres-smoke.json")
if [[ -n "$POSTGRES_DSN_FILE" ]]; then
  POSTGRES_ARGS=("--dsn-file" "$POSTGRES_DSN_FILE" "${POSTGRES_ARGS[@]}")
elif [[ "$REQUIRE_POSTGRES" == "true" ]]; then
  echo "Missing value: AI_RISK_POSTGRES_DSN_FILE; continuing to produce failed signoff evidence" >&2
else
  POSTGRES_ARGS=("--skip-if-unconfigured" "${POSTGRES_ARGS[@]}")
fi

STAGING_ARGS=(
  "--risk-base-url" "$RISK_BASE_URL"
  "--agent-base-url" "$AGENT_BASE_URL"
  "--agent-admin-header" "$ADMIN_HEADER"
  "--agent-admin-token-file" "$ADMIN_TOKEN_FILE"
  "--output" "${REPORT_DIR}/staging-validation.json"
)
if [[ -n "$CENTRAL_AUDIT_BASE_URL" ]]; then
  STAGING_ARGS+=("--central-audit-base-url" "$CENTRAL_AUDIT_BASE_URL")
  STAGING_ARGS+=("--central-audit-header" "$CENTRAL_AUDIT_HEADER")
  if [[ -n "$CENTRAL_AUDIT_TOKEN_FILE" ]]; then
    STAGING_ARGS+=("--central-audit-token-file" "$CENTRAL_AUDIT_TOKEN_FILE")
  fi
elif [[ "$REQUIRE_CENTRAL_AUDIT" == "true" ]]; then
  echo "Missing value: AI_RISK_SIGNOFF_CENTRAL_AUDIT_BASE_URL; continuing to produce failed signoff evidence" >&2
fi

run_step "postgres-smoke" \
  "$PYTHON_BIN" -m validation.postgres_smoke "${POSTGRES_ARGS[@]}"

run_step "readiness" \
  "$PYTHON_BIN" -m validation.readiness \
    --agent-base-url "$AGENT_BASE_URL" \
    --admin-header "$ADMIN_HEADER" \
    --admin-token-file "$ADMIN_TOKEN_FILE" \
    --output "${REPORT_DIR}/readiness.json"

run_step "staging-contract" \
  "$PYTHON_BIN" -m validation.staging "${STAGING_ARGS[@]}"

run_step "signoff-summary" \
  "$PYTHON_BIN" - "$REPORT_DIR" "$RISK_BASE_URL" "$AGENT_BASE_URL" "$REQUIRE_POSTGRES" "$REQUIRE_CENTRAL_AUDIT" "$SIGNOFF_FAILED" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

report_dir = Path(sys.argv[1])
risk_base_url = sys.argv[2]
agent_base_url = sys.argv[3]
require_postgres = sys.argv[4] == "true"
require_central_audit = sys.argv[5] == "true"
command_failed = sys.argv[6] != "0"

reports = {}
for name, filename in (
    ("signoff_preflight", "signoff-preflight.json"),
    ("postgres_smoke", "postgres-smoke.json"),
    ("readiness", "readiness.json"),
    ("staging_validation", "staging-validation.json"),
):
    path = report_dir / filename
    if path.exists():
        reports[name] = json.loads(path.read_text(encoding="utf-8"))
    else:
        reports[name] = {"status": "missing", "checks": []}

accepted_statuses = {"passed"}
if not require_postgres:
    accepted_statuses.add("skipped")

failed_reports = [
    name
    for name, report in reports.items()
    if report.get("status") not in accepted_statuses
]
status = "passed" if not command_failed and not failed_reports else "failed"
summary = {
    "status": status,
    "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "report_dir": str(report_dir),
    "inputs": {
        "risk_base_url": risk_base_url,
        "agent_base_url": agent_base_url,
        "postgres_required": require_postgres,
        "central_audit_query_required": require_central_audit,
    },
    "reports": {
        name: {
            "status": report.get("status", "missing"),
            "summary": report.get("summary", {}),
        }
        for name, report in reports.items()
    },
    "failed_reports": failed_reports,
}
(report_dir / "signoff-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps(summary, ensure_ascii=False, indent=2))
raise SystemExit(0 if status == "passed" else 1)
PY

run_step "signoff-manifest" \
  "$PYTHON_BIN" -m validation.signoff_manifest \
    --report-dir "$REPORT_DIR" \
    --output "${REPORT_DIR}/signoff-manifest.json"

EVIDENCE_ARGS=(
  "--report-dir" "$REPORT_DIR"
  "--expected-risk-base-url" "$RISK_BASE_URL"
  "--expected-agent-base-url" "$AGENT_BASE_URL"
  "--output" "${REPORT_DIR}/signoff-evidence.json"
)
if [[ "$REQUIRE_POSTGRES" != "true" ]]; then
  EVIDENCE_ARGS+=("--allow-postgres-skipped")
fi
if [[ "$REQUIRE_CENTRAL_AUDIT" == "true" ]]; then
  EVIDENCE_ARGS+=("--require-central-audit")
fi

run_step "signoff-evidence" \
  "$PYTHON_BIN" -m validation.signoff_evidence "${EVIDENCE_ARGS[@]}"

run_step "signoff-archive" \
  "$PYTHON_BIN" -m validation.signoff_archive \
    --report-dir "$REPORT_DIR" \
    --output "${REPORT_DIR}/signoff-archive.tar.gz" \
    --checksum-output "${REPORT_DIR}/signoff-archive.sha256"

run_step "verify-signoff-archive" \
  "$PYTHON_BIN" -m validation.signoff_archive \
    --verify \
    --report-dir "$REPORT_DIR" \
    --archive "${REPORT_DIR}/signoff-archive.tar.gz" \
    --checksum "${REPORT_DIR}/signoff-archive.sha256"

exit "$SIGNOFF_FAILED"
