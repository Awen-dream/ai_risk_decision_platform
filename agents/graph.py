from __future__ import annotations

import re

from agents.base import Agent
from core.models import AgentRequest, AgentResponse, Citation
from retrieval.knowledge_base import RetrievalService
from tools.registry import ToolRegistry


ENTITY_ID_PATTERN = re.compile(r"((?:U|O)\d{5})", re.IGNORECASE)


class GraphAgent(Agent):
    """Agent for graph relation and community analysis."""

    name = "graph"

    def __init__(self, tools: ToolRegistry, retrieval: RetrievalService) -> None:
        self._tools = tools
        self._retrieval = retrieval

    def run(self, request: AgentRequest) -> AgentResponse:
        entity_id = self._resolve_entity_id(request)
        response = AgentResponse(agent_name=self.name)

        relation_trace = response.record_tool_trace(
            "graph_relation",
            self._tools.execute("graph_relation", entity_id=entity_id),
        )
        relation = relation_trace.payload if relation_trace.status == "success" else None

        docs = self._retrieval.search(f"{request.query} graph relation fraud ring", top_k=2)
        response.citations.extend(
            Citation.from_document(doc, snippet_length=180) for doc in docs
        )

        if relation:
            response.record_evidence(
                source="graph_relation",
                source_type="tool",
                summary=f"实体 {entity_id} 的关系网络风险等级为 {relation['risk_level']}。",
                payload=relation,
                confidence=0.8,
            )
            response.summary = (
                f"实体 {entity_id} 当前处于 {relation['community_size']} 个节点的关系网络中，"
                f"风险等级为 {relation['risk_level']}，主要风险原因是 {relation['risk_reason']}"
            )
            response.findings = [
                f"实体类型：{relation['entity_type']}，共享设备：{', '.join(relation['shared_devices']) or '无'}",
                f"共享 IP：{', '.join(relation['shared_ips']) or '无'}",
                f"关联账号：{', '.join(relation['linked_accounts']) or '无'}",
                f"关联订单：{', '.join(relation['linked_orders']) or '无'}",
                f"关键路径：{relation['key_path']}",
            ]
            response.suggested_actions = [
                "优先复核共享设备和共享 IP 上的关联账号",
                "结合历史相似 Case 判断是否属于团伙扩散",
                "如果网络继续扩大，建议补充图谱规则或升级人工审核",
            ]
            response.confidence = 0.8
            return response

        response.summary = (
            f"暂时无法完成实体 {entity_id} 的图谱分析，"
            f"{self._tool_status_phrase(relation_trace, '图谱关系')}。"
        )
        response.findings = [self._tool_status_finding("图谱关系", relation_trace)]
        response.suggested_actions = [
            self._tool_status_action("图谱关系", relation_trace, entity_id),
            "如需继续分析，可先结合历史案件或订单画像补充上下文",
        ]
        response.confidence = 0.18
        return response

    @staticmethod
    def _resolve_entity_id(request: AgentRequest) -> str:
        if "entity_id" in request.context:
            return str(request.context["entity_id"]).upper()
        if "order_id" in request.context:
            return str(request.context["order_id"]).upper()
        if "user_id" in request.context:
            return str(request.context["user_id"]).upper()
        match = ENTITY_ID_PATTERN.search(request.query)
        if match:
            return match.group(1).upper()
        return "U10001"

    @staticmethod
    def _tool_status_finding(label: str, trace) -> str:
        if trace.status == "failed":
            return f"{label}：调用失败，原因 {trace.summary}"
        return f"{label}：{trace.summary}"

    @staticmethod
    def _tool_status_phrase(trace, label: str) -> str:
        if trace.status == "failed":
            return f"{label}调用失败"
        return f"未获取到可用{label}"

    @staticmethod
    def _tool_status_action(label: str, trace, identifier: str) -> str:
        if trace.status == "failed":
            return f"检查{label}上游服务状态与字段契约，确认 {identifier} 对应调用可恢复"
        return f"确认 {identifier} 对应的{label}数据是否已同步，必要时补齐记录后重试"
