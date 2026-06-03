from __future__ import annotations

from typing import List, Optional


def build_turn_title(agent_name: str) -> str:
    return {
        "knowledge": "知识问答",
        "investigation": "风险调查",
        "strategy": "策略分析",
        "graph": "图谱分析",
        "copilot": "联合分析",
    }.get(agent_name, "智能体执行")


def build_agent_group(agent_name: str) -> str:
    return {
        "knowledge": "knowledge",
        "investigation": "analysis",
        "strategy": "analysis",
        "graph": "analysis",
        "copilot": "workflow",
    }.get(agent_name, "analysis")


def build_expanded_sections(agent_name: str) -> List[str]:
    return {
        "knowledge": ["summary", "citations"],
        "investigation": ["summary", "findings", "tool_traces"],
        "strategy": ["summary", "findings", "tool_traces"],
        "graph": ["summary", "findings", "tool_traces"],
        "copilot": ["intent", "plan", "planner_trace", "findings", "actions"],
    }.get(agent_name, ["summary"])


def build_badge(agent_name: str, intent: Optional[str]) -> str:
    if agent_name == "copilot":
        return "workflow"
    if agent_name == "graph" or intent in {"fraud_ring", "order_case"}:
        return "risk-graph"
    if agent_name == "strategy" or intent in {"strategy_review", "composite"}:
        return "strategy"
    if agent_name == "knowledge":
        return "knowledge"
    return "analysis"


def build_severity(agent_name: str, intent: Optional[str]) -> str:
    if agent_name == "copilot" and intent == "composite":
        return "high"
    if agent_name == "graph" or intent == "fraud_ring":
        return "high"
    if agent_name == "strategy" or intent == "strategy_review":
        return "medium"
    if agent_name == "investigation" or intent == "order_case":
        return "medium"
    return "low"
