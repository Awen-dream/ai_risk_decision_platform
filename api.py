from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app import build_demo_runtime
from core.models import AgentRequest, AgentResponse


class AgentInvokeRequest(BaseModel):
    query: str = Field(..., min_length=1, description="User query for the agent")
    context: dict[str, object] = Field(
        default_factory=dict,
        description="Optional structured context such as country, channel, order_id",
    )
    user_role: str = Field(default="risk_analyst")


class CitationPayload(BaseModel):
    doc_id: str
    title: str
    source_type: str
    snippet: str


class ToolTracePayload(BaseModel):
    name: str
    status: str
    summary: str


class AgentInvokeResponse(BaseModel):
    agent_name: str
    summary: str
    findings: list[str]
    suggested_actions: list[str]
    citations: list[CitationPayload]
    tool_traces: list[ToolTracePayload]
    confidence: float


def create_app() -> FastAPI:
    runtime = build_demo_runtime()
    fastapi_app = FastAPI(
        title="AI Risk Decision Platform API",
        version="0.1.0",
        description="Minimal agent-platform API for risk knowledge and investigation workflows.",
    )

    @fastapi_app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @fastapi_app.get("/agents")
    def list_agents() -> dict[str, list[str]]:
        return {"agents": ["knowledge", "investigation"]}

    @fastapi_app.post("/agents/{agent_name}", response_model=AgentInvokeResponse)
    def invoke_agent(agent_name: str, payload: AgentInvokeRequest) -> AgentInvokeResponse:
        try:
            response = runtime.execute(
                agent_name,
                AgentRequest(
                    query=payload.query,
                    context=payload.context,
                    user_role=payload.user_role,
                ),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _to_response_model(response)

    return fastapi_app


def _to_response_model(response: AgentResponse) -> AgentInvokeResponse:
    return AgentInvokeResponse(
        agent_name=response.agent_name,
        summary=response.summary,
        findings=response.findings,
        suggested_actions=response.suggested_actions,
        citations=[
            CitationPayload(
                doc_id=citation.doc_id,
                title=citation.title,
                source_type=citation.source_type,
                snippet=citation.snippet,
            )
            for citation in response.citations
        ],
        tool_traces=[
            ToolTracePayload(
                name=trace.name,
                status=trace.status,
                summary=trace.summary,
            )
            for trace in response.tool_traces
        ],
        confidence=response.confidence,
    )


fastapi_app = create_app()
