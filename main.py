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

    knowledge_response = runtime.execute(
        "knowledge",
        AgentRequest(query="营销套利案件的标准排查 SOP 是什么？"),
    )
    render_response("Knowledge Agent Demo", knowledge_response)

    investigation_response = runtime.execute(
        "investigation",
        AgentRequest(query="为什么巴西信用卡支付失败率从昨晚开始突然升高？"),
    )
    render_response("Investigation Agent Demo", investigation_response)

    print("\nAPI server hint:")
    print("  uvicorn api:fastapi_app --reload")
