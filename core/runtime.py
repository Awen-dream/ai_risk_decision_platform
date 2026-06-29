from __future__ import annotations

import time

from agents.base import Agent
from core.models import AgentRequest, AgentResponse
from core.session_store import InMemorySessionStore, SessionStore
from services.observability import bind_context, emit_event, increment_counter, set_gauge


class AgentRuntime:
    """Simple runtime for registering and executing agents by name."""

    def __init__(self, session_store: SessionStore | None = None) -> None:
        self._agents: dict[str, Agent] = {}
        self._session_store = session_store or InMemorySessionStore()

    def register_agent(self, agent: Agent) -> None:
        self._agents[agent.name] = agent

    def list_agents(self) -> list[str]:
        return list(self._agents)

    def execute(
        self,
        agent_name: str,
        request: AgentRequest,
        session_id: str | None = None,
    ) -> tuple[str, AgentResponse]:
        if agent_name not in self._agents:
            raise KeyError(f"Unknown agent: {agent_name}")
        session = self._session_store.ensure_session(session_id)
        with bind_context(session_id=session.session_id, agent_name=agent_name):
            started_at = time.perf_counter()
            emit_event(
                "agent_execution_started",
                provided_session_id=bool(session_id),
            )
            try:
                response = self._agents[agent_name].run(request)
                session = self._session_store.append_turn(
                    session.session_id,
                    request,
                    response,
                )
            except Exception as exc:
                emit_event(
                    "agent_execution_failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    duration_seconds=time.perf_counter() - started_at,
                )
                raise
            emit_event(
                "agent_execution_completed",
                confidence=response.confidence,
                tool_trace_count=len(response.tool_traces),
                duration_seconds=time.perf_counter() - started_at,
            )
            self._record_response_metrics(agent_name, response)
        return session.session_id, response

    def create_session(self) -> str:
        session_id = self._session_store.create_session().session_id
        with bind_context(session_id=session_id):
            emit_event("session_created")
        return session_id

    def get_session(self, session_id: str):
        return self._session_store.get_session(session_id)

    @staticmethod
    def _record_response_metrics(agent_name: str, response: AgentResponse) -> None:
        planner_artifact = AgentRuntime._planner_artifact(response)
        if planner_artifact is not None:
            backend = str(planner_artifact.get("backend") or "unknown")
            validation_errors = planner_artifact.get("validation_errors") or []
            validation_error_count = (
                len(validation_errors) if isinstance(validation_errors, list) else 0
            )
            increment_counter("agent.planner.plans.total")
            increment_counter(f"agent.planner.plans.by_agent.{agent_name}")
            increment_counter(f"agent.planner.plans.by_backend.{backend}")
            increment_counter("agent.planner.selected_steps.total", len(response.plan_steps))
            increment_counter(
                f"agent.planner.selected_steps.by_agent.{agent_name}",
                len(response.plan_steps),
            )
            if planner_artifact.get("fallback_used"):
                increment_counter("agent.planner.fallbacks.total")
                increment_counter(f"agent.planner.fallbacks.by_agent.{agent_name}")
            if validation_error_count:
                increment_counter("agent.planner.validation_errors.total", validation_error_count)
                increment_counter(
                    f"agent.planner.validation_errors.by_agent.{agent_name}",
                    validation_error_count,
                )
            set_gauge(
                f"agent.planner.last_selected_step_count.by_agent.{agent_name}",
                float(len(response.plan_steps)),
            )
            set_gauge(
                f"agent.planner.last_validation_error_count.by_agent.{agent_name}",
                float(validation_error_count),
            )

        if (
            response.thought_summary
            or response.tool_selection_reason
            or response.evidence_gap
            or response.artifacts.get("tool_using_plan")
        ):
            increment_counter("agent.intermediate_states.total")
            increment_counter(f"agent.intermediate_states.by_agent.{agent_name}")
            increment_counter(
                "agent.intermediate_states.tool_reasons.total",
                len(response.tool_selection_reason),
            )
            increment_counter(
                f"agent.intermediate_states.tool_reasons.by_agent.{agent_name}",
                len(response.tool_selection_reason),
            )
            if response.evidence_gap:
                increment_counter("agent.intermediate_states.evidence_gaps.total", len(response.evidence_gap))
                increment_counter(
                    f"agent.intermediate_states.evidence_gaps.by_agent.{agent_name}",
                    len(response.evidence_gap),
                )
            set_gauge(
                f"agent.intermediate_states.last_tool_reason_count.by_agent.{agent_name}",
                float(len(response.tool_selection_reason)),
            )
            set_gauge(
                f"agent.intermediate_states.last_evidence_gap_count.by_agent.{agent_name}",
                float(len(response.evidence_gap)),
            )

        global_plan = response.artifacts.get("global_plan")
        evidence_graph = response.artifacts.get("evidence_graph")
        if isinstance(global_plan, dict):
            steps = global_plan.get("steps") or []
            step_count = len(steps) if isinstance(steps, list) else 0
            increment_counter("agent.global_plans.total")
            increment_counter(f"agent.global_plans.by_agent.{agent_name}")
            increment_counter("agent.global_plans.steps.total", step_count)
            set_gauge(
                f"agent.global_plans.last_step_count.by_agent.{agent_name}",
                float(step_count),
            )
        if isinstance(evidence_graph, dict):
            summary = evidence_graph.get("summary") if isinstance(evidence_graph.get("summary"), dict) else {}
            evidence_gap_count = int(summary.get("evidence_gap_count", 0) or 0)
            evidence_count = int(summary.get("evidence_count", 0) or 0)
            increment_counter("agent.evidence_graphs.total")
            increment_counter(f"agent.evidence_graphs.by_agent.{agent_name}")
            increment_counter("agent.evidence_graphs.evidence_nodes.total", evidence_count)
            if evidence_gap_count:
                increment_counter("agent.evidence_graphs.evidence_gap_nodes.total", evidence_gap_count)
            set_gauge(
                f"agent.evidence_graphs.last_evidence_count.by_agent.{agent_name}",
                float(evidence_count),
            )
            set_gauge(
                f"agent.evidence_graphs.last_evidence_gap_count.by_agent.{agent_name}",
                float(evidence_gap_count),
            )

        if response.tool_traces:
            increment_counter("agent.tools.executions.total", len(response.tool_traces))
            increment_counter(
                f"agent.tools.executions.by_agent.{agent_name}",
                len(response.tool_traces),
            )
            for trace in response.tool_traces:
                status = trace.status or "unknown"
                increment_counter(f"agent.tools.executions.by_status.{status}")
                increment_counter(
                    f"agent.tools.executions.by_agent.{agent_name}.by_status.{status}"
                )
            set_gauge(
                f"agent.tools.last_trace_count.by_agent.{agent_name}",
                float(len(response.tool_traces)),
            )

    @staticmethod
    def _planner_artifact(response: AgentResponse) -> dict | None:
        for artifact_name in (
            "planner",
            "tool_using_plan",
            "investigation_plan",
            "strategy_plan",
            "graph_plan",
        ):
            artifact = response.artifacts.get(artifact_name)
            if isinstance(artifact, dict):
                return artifact
        return None
