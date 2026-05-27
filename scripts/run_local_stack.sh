#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

if [[ -f "$ROOT_DIR/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.local"
  set +a
elif [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

API_HOST="${AI_RISK_API_HOST:-127.0.0.1}"
API_PORT="${AI_RISK_API_PORT:-8000}"
RISK_HOST="${AI_RISK_RISK_SERVICE_HOST:-127.0.0.1}"
RISK_PORT="${AI_RISK_RISK_SERVICE_PORT:-8090}"

cleanup() {
  if [[ -n "${RISK_PID:-}" ]]; then
    kill "$RISK_PID" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

cd "$ROOT_DIR"

echo "Starting mock risk service on ${RISK_HOST}:${RISK_PORT} ..."
"$PYTHON_BIN" -m uvicorn risk_service:risk_service_app --host "$RISK_HOST" --port "$RISK_PORT" --reload &
RISK_PID=$!

sleep 1

echo "Starting agent API on ${API_HOST}:${API_PORT} with HTTP backend ..."
export AI_RISK_KNOWLEDGE_BACKEND="${AI_RISK_KNOWLEDGE_BACKEND:-file}"
export AI_RISK_TOOL_BACKEND="${AI_RISK_TOOL_BACKEND:-http}"
export AI_RISK_TOOL_HTTP_BASE_URL="${AI_RISK_TOOL_HTTP_BASE_URL:-http://${RISK_HOST}:${RISK_PORT}}"

exec "$PYTHON_BIN" -m uvicorn api:fastapi_app --host "$API_HOST" --port "$API_PORT" --reload
