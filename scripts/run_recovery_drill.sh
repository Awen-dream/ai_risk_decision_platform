#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

API_HOST="${AI_RISK_DRILL_API_HOST:-127.0.0.1}"
API_PORT="${AI_RISK_DRILL_API_PORT:-18080}"
RISK_HOST="${AI_RISK_DRILL_RISK_HOST:-127.0.0.1}"
RISK_PORT="${AI_RISK_DRILL_RISK_PORT:-18090}"
REPORT_PATH="${AI_RISK_DRILL_REPORT_PATH:-.data/reports/recovery-drill.json}"
DATABASE_PATH="${AI_RISK_DRILL_DATABASE_PATH:-.data/recovery-drill.db}"
AUDIT_PATH="${AI_RISK_DRILL_AUDIT_PATH:-.data/recovery-drill-audit-$$.jsonl}"
ADMIN_TOKEN_PATH="${AI_RISK_DRILL_ADMIN_TOKEN_PATH:-.data/recovery-drill-admin-token-$$}"
ADMIN_TOKEN="${AI_RISK_DRILL_ADMIN_TOKEN:-recovery-drill-admin-token}"

cleanup() {
  if [[ -n "${API_PID:-}" ]]; then
    kill "$API_PID" >/dev/null 2>&1 || true
    wait "$API_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "${RISK_PID:-}" ]]; then
    kill "$RISK_PID" >/dev/null 2>&1 || true
    wait "$RISK_PID" >/dev/null 2>&1 || true
  fi
}

ensure_port_available() {
  local host="$1"
  local port="$2"
  if "$PYTHON_BIN" -c "import socket; s = socket.socket(); s.settimeout(0.2); raise SystemExit(0 if s.connect_ex(('$host', $port)) != 0 else 1)"; then
    return 0
  fi
  echo "Refusing to run: ${host}:${port} is already in use" >&2
  return 1
}

wait_for_health() {
  local url="$1"
  local attempts=50
  while (( attempts > 0 )); do
    if "$PYTHON_BIN" -c "from urllib.request import urlopen; urlopen('$url', timeout=1).read()" >/dev/null 2>&1; then
      return 0
    fi
    attempts=$((attempts - 1))
    sleep 0.1
  done
  echo "Timed out waiting for $url" >&2
  return 1
}

trap cleanup EXIT INT TERM
cd "$ROOT_DIR"
mkdir -p .data "$(dirname "$REPORT_PATH")" "$(dirname "$DATABASE_PATH")" "$(dirname "$ADMIN_TOKEN_PATH")"
printf "%s\n" "$ADMIN_TOKEN" >"$ADMIN_TOKEN_PATH"
ensure_port_available "$RISK_HOST" "$RISK_PORT"
ensure_port_available "$API_HOST" "$API_PORT"

AI_RISK_RISK_SERVICE_FAULT_INJECTION_ENABLED=true \
  "$PYTHON_BIN" -m uvicorn risk_service:risk_service_app \
  --host "$RISK_HOST" --port "$RISK_PORT" >.data/recovery-drill-risk.log 2>&1 &
RISK_PID=$!

AI_RISK_KNOWLEDGE_BACKEND=file \
AI_RISK_TOOL_BACKEND=http \
AI_RISK_TOOL_HTTP_BASE_URL="http://${RISK_HOST}:${RISK_PORT}" \
AI_RISK_TOOL_HTTP_RETRY_ATTEMPTS=2 \
AI_RISK_TOOL_HTTP_RETRY_BACKOFF_SEC=0 \
AI_RISK_TOOL_HTTP_CIRCUIT_BREAKER_FAILURE_THRESHOLD=2 \
AI_RISK_TOOL_HTTP_CIRCUIT_BREAKER_RESET_SEC=0.2 \
AI_RISK_SESSION_STORE_BACKEND=sqlite \
AI_RISK_CASE_STORE_BACKEND=sqlite \
AI_RISK_DATABASE_PATH="$DATABASE_PATH" \
AI_RISK_TOOL_HTTP_AUDIT_ENABLED=true \
AI_RISK_TOOL_HTTP_AUDIT_PATH="$AUDIT_PATH" \
AI_RISK_ADMIN_AUTH_ENABLED=true \
AI_RISK_ADMIN_AUTH_TOKEN_FILE="$ADMIN_TOKEN_PATH" \
  "$PYTHON_BIN" -m uvicorn api:fastapi_app \
  --host "$API_HOST" --port "$API_PORT" >.data/recovery-drill-api.log 2>&1 &
API_PID=$!

wait_for_health "http://${RISK_HOST}:${RISK_PORT}/healthz"
wait_for_health "http://${API_HOST}:${API_PORT}/healthz"

"$PYTHON_BIN" -m validation.readiness \
  --agent-base-url "http://${API_HOST}:${API_PORT}" \
  --admin-token-file "$ADMIN_TOKEN_PATH" \
  --output .data/reports/readiness-drill.json

"$PYTHON_BIN" -m validation.staging \
  --risk-base-url "http://${RISK_HOST}:${RISK_PORT}" \
  --agent-base-url "http://${API_HOST}:${API_PORT}" \
  --agent-admin-token-file "$ADMIN_TOKEN_PATH" \
  --fault-drill \
  --reset-wait-sec 0.5 \
  --output "$REPORT_PATH"
