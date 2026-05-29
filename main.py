from __future__ import annotations

from app import build_demo_runtime
from core.models import AgentRequest


def render_response(title: str, response) -> None:
    print(f"\n=== {title} ===")
    print(f"Agent: {response.agent_name}")
    print(f"Summary: {response.summary}")
    print("Findings:")
    for finding in response.findings:
        print(f"  - {finding}")
    print("Suggested actions:")
    for action in response.suggested_actions:
        print(f"  - {action}")
    print("Citations:")
    for citation in response.citations:
        print(f"  - [{citation.source_type}] {citation.title}: {citation.snippet}")
    print("Tool traces:")
    for trace in response.tool_traces:
        print(f"  - {trace.name} ({trace.status}): {trace.summary}")


if __name__ == "__main__":
    runtime = build_demo_runtime()

    session_id, knowledge_response = runtime.execute(
        "knowledge",
        AgentRequest(query="营销套利案件的标准排查 SOP 是什么？"),
    )
    render_response("Knowledge Agent Demo", knowledge_response)

    _, investigation_response = runtime.execute(
        "investigation",
        AgentRequest(query="为什么巴西信用卡支付失败率从昨晚开始突然升高？"),
        session_id=session_id,
    )
    render_response("Investigation Agent Demo", investigation_response)

    _, strategy_response = runtime.execute(
        "strategy",
        AgentRequest(
            query="请评估策略 STRAT-001 是否应该调整阈值",
            context={"strategy_id": "STRAT-001"},
        ),
        session_id=session_id,
    )
    render_response("Strategy Agent Demo", strategy_response)

    _, graph_response = runtime.execute(
        "graph",
        AgentRequest(
            query="请分析用户 U10001 是否属于团伙网络",
            context={"entity_id": "U10001"},
        ),
        session_id=session_id,
    )
    render_response("Graph Agent Demo", graph_response)
    print(f"\nShared session ID: {session_id}")

    print("\nAPI server hint:")
    print("  uvicorn api:fastapi_app --reload")
    print("  uvicorn risk_service:risk_service_app --port 8090 --reload")
