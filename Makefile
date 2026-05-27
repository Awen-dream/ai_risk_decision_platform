PYTHON ?= python3
UVICORN ?= $(PYTHON) -m uvicorn

.PHONY: test run-api run-risk-service run-local-stack run-api-http run-cli

test:
	$(PYTHON) -m unittest discover -v

run-api:
	$(UVICORN) api:fastapi_app --host 127.0.0.1 --port 8000 --reload

run-risk-service:
	$(UVICORN) risk_service:risk_service_app --host 127.0.0.1 --port 8090 --reload

run-api-http:
	bash scripts/run_api_http_backend.sh

run-local-stack:
	bash scripts/run_local_stack.sh

run-cli:
	$(PYTHON) cli.py --help
