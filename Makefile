PYTHON ?= python3
UVICORN ?= $(PYTHON) -m uvicorn

.PHONY: test run-api run-risk-service run-local-stack run-api-http run-cli validate-staging validate-readiness validate-postgres validate-signoff-evidence signoff-staging signoff-local recovery-drill

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

validate-staging:
	$(PYTHON) -m validation.staging --risk-base-url $(RISK_BASE_URL) --agent-base-url $(AGENT_BASE_URL)

validate-readiness:
	$(PYTHON) -m validation.readiness --agent-base-url $(AGENT_BASE_URL)

validate-postgres:
	$(PYTHON) -m validation.postgres_smoke

validate-signoff-evidence:
	$(PYTHON) -m validation.signoff_evidence --report-dir $(REPORT_DIR) $(SIGNOFF_EVIDENCE_ARGS)

signoff-staging:
	bash scripts/run_real_staging_signoff.sh

signoff-local:
	bash scripts/run_local_signoff.sh

recovery-drill:
	bash scripts/run_recovery_drill.sh
