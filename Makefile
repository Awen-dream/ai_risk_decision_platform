PYTHON ?= python3
UVICORN ?= $(PYTHON) -m uvicorn

.PHONY: test run-api run-risk-service run-local-stack run-api-http

test:
	$(PYTHON) -m unittest discover -v

run-api:
	$(UVICORN) api:fastapi_app --host 127.0.0.1 --port 8000 --reload

run-risk-service:
	$(UVICORN) risk_service:risk_service_app --host 127.0.0.1 --port 8090 --reload

run-api-http:
	AI_RISK_KNOWLEDGE_BACKEND=file \
	AI_RISK_TOOL_BACKEND=http \
	AI_RISK_TOOL_HTTP_BASE_URL=http://127.0.0.1:8090 \
	$(UVICORN) api:fastapi_app --host 127.0.0.1 --port 8000 --reload

run-local-stack:
	bash scripts/run_local_stack.sh
