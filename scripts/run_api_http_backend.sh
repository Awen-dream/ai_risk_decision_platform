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

export AI_RISK_KNOWLEDGE_BACKEND="${AI_RISK_KNOWLEDGE_BACKEND:-file}"
export AI_RISK_TOOL_BACKEND="${AI_RISK_TOOL_BACKEND:-http}"
export AI_RISK_TOOL_HTTP_BASE_URL="${AI_RISK_TOOL_HTTP_BASE_URL:-http://127.0.0.1:8090}"
export AI_RISK_API_HOST="${AI_RISK_API_HOST:-127.0.0.1}"
export AI_RISK_API_PORT="${AI_RISK_API_PORT:-8000}"

cd "$ROOT_DIR"
exec "$PYTHON_BIN" -m uvicorn api:fastapi_app --host "$AI_RISK_API_HOST" --port "$AI_RISK_API_PORT" --reload
