#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

TIMESTAMP="$("$PYTHON_BIN" -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))")"
API_HOST="${AI_RISK_LOCAL_SIGNOFF_API_HOST:-127.0.0.1}"
API_PORT="${AI_RISK_LOCAL_SIGNOFF_API_PORT:-18180}"
RISK_HOST="${AI_RISK_LOCAL_SIGNOFF_RISK_HOST:-127.0.0.1}"
RISK_PORT="${AI_RISK_LOCAL_SIGNOFF_RISK_PORT:-18190}"
AUDIT_SINK_HOST="${AI_RISK_LOCAL_SIGNOFF_AUDIT_SINK_HOST:-127.0.0.1}"
AUDIT_SINK_PORT="${AI_RISK_LOCAL_SIGNOFF_AUDIT_SINK_PORT:-18191}"
REPORT_DIR="${AI_RISK_LOCAL_SIGNOFF_REPORT_DIR:-.data/reports/local-signoff-${TIMESTAMP}}"
DATABASE_PATH="${AI_RISK_LOCAL_SIGNOFF_DATABASE_PATH:-.data/local-signoff.db}"
AUDIT_PATH="${AI_RISK_LOCAL_SIGNOFF_AUDIT_PATH:-.data/local-signoff-audit-$$.jsonl}"
ADMIN_TOKEN_PATH="${AI_RISK_LOCAL_SIGNOFF_ADMIN_TOKEN_PATH:-.data/local-signoff-admin-token-$$}"
ADMIN_TOKEN="${AI_RISK_LOCAL_SIGNOFF_ADMIN_TOKEN:-local-signoff-admin-token}"
CENTRAL_AUDIT_TOKEN_PATH="${AI_RISK_LOCAL_SIGNOFF_CENTRAL_AUDIT_TOKEN_PATH:-.data/local-signoff-central-audit-token-$$}"
CENTRAL_AUDIT_TOKEN="${AI_RISK_LOCAL_SIGNOFF_CENTRAL_AUDIT_TOKEN:-local-signoff-central-audit-token}"

cleanup() {
  if [[ -n "${API_PID:-}" ]]; then
    kill "$API_PID" >/dev/null 2>&1 || true
    wait "$API_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "${RISK_PID:-}" ]]; then
    kill "$RISK_PID" >/dev/null 2>&1 || true
    wait "$RISK_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "${AUDIT_SINK_PID:-}" ]]; then
    kill "$AUDIT_SINK_PID" >/dev/null 2>&1 || true
    wait "$AUDIT_SINK_PID" >/dev/null 2>&1 || true
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
mkdir -p .data "$REPORT_DIR" "$(dirname "$DATABASE_PATH")" "$(dirname "$AUDIT_PATH")" "$(dirname "$ADMIN_TOKEN_PATH")" "$(dirname "$CENTRAL_AUDIT_TOKEN_PATH")"
printf "%s\n" "$ADMIN_TOKEN" >"$ADMIN_TOKEN_PATH"
printf "%s\n" "$CENTRAL_AUDIT_TOKEN" >"$CENTRAL_AUDIT_TOKEN_PATH"
ensure_port_available "$RISK_HOST" "$RISK_PORT"
ensure_port_available "$API_HOST" "$API_PORT"
ensure_port_available "$AUDIT_SINK_HOST" "$AUDIT_SINK_PORT"

"$PYTHON_BIN" -m uvicorn risk_service:risk_service_app \
  --host "$RISK_HOST" --port "$RISK_PORT" >.data/local-signoff-risk.log 2>&1 &
RISK_PID=$!

AI_RISK_AUDIT_SINK_AUTH_HEADER=X-Audit-Token \
AI_RISK_AUDIT_SINK_AUTH_TOKEN="$CENTRAL_AUDIT_TOKEN" \
  "$PYTHON_BIN" -m uvicorn audit_sink_service:audit_sink_app \
  --host "$AUDIT_SINK_HOST" --port "$AUDIT_SINK_PORT" >.data/local-signoff-audit-sink.log 2>&1 &
AUDIT_SINK_PID=$!

AI_RISK_KNOWLEDGE_BACKEND=file \
AI_RISK_TOOL_BACKEND=http \
AI_RISK_TOOL_HTTP_BASE_URL="http://${RISK_HOST}:${RISK_PORT}" \
AI_RISK_SESSION_STORE_BACKEND=sqlite \
AI_RISK_CASE_STORE_BACKEND=sqlite \
AI_RISK_DATABASE_PATH="$DATABASE_PATH" \
AI_RISK_TOOL_HTTP_AUDIT_ENABLED=true \
AI_RISK_TOOL_HTTP_AUDIT_PATH="$AUDIT_PATH" \
AI_RISK_AUDIT_CENTRAL_ENABLED=true \
AI_RISK_AUDIT_CENTRAL_URL="http://${AUDIT_SINK_HOST}:${AUDIT_SINK_PORT}/audit-events" \
AI_RISK_AUDIT_CENTRAL_TIMEOUT_SEC=3 \
AI_RISK_AUDIT_CENTRAL_AUTH_HEADER=X-Audit-Token \
AI_RISK_AUDIT_CENTRAL_AUTH_TOKEN_FILE="$CENTRAL_AUDIT_TOKEN_PATH" \
AI_RISK_ADMIN_AUTH_ENABLED=true \
AI_RISK_ADMIN_AUTH_TOKEN_FILE="$ADMIN_TOKEN_PATH" \
  "$PYTHON_BIN" -m uvicorn api:fastapi_app \
  --host "$API_HOST" --port "$API_PORT" >.data/local-signoff-api.log 2>&1 &
API_PID=$!

wait_for_health "http://${RISK_HOST}:${RISK_PORT}/healthz"
wait_for_health "http://${AUDIT_SINK_HOST}:${AUDIT_SINK_PORT}/healthz"
wait_for_health "http://${API_HOST}:${API_PORT}/healthz"

RISK_BASE_URL="http://${RISK_HOST}:${RISK_PORT}" \
AGENT_BASE_URL="http://${API_HOST}:${API_PORT}" \
AI_RISK_ADMIN_AUTH_TOKEN_FILE="$ADMIN_TOKEN_PATH" \
AI_RISK_SIGNOFF_REQUIRE_POSTGRES=false \
AI_RISK_SIGNOFF_REQUIRE_CENTRAL_AUDIT=true \
AI_RISK_SIGNOFF_CENTRAL_AUDIT_BASE_URL="http://${AUDIT_SINK_HOST}:${AUDIT_SINK_PORT}" \
AI_RISK_AUDIT_CENTRAL_AUTH_HEADER=X-Audit-Token \
AI_RISK_AUDIT_CENTRAL_AUTH_TOKEN_FILE="$CENTRAL_AUDIT_TOKEN_PATH" \
AI_RISK_SIGNOFF_REPORT_DIR="$REPORT_DIR" \
  bash scripts/run_real_staging_signoff.sh
