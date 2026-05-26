from __future__ import annotations

from agents.base import Agent
from core.models import AgentRequest, AgentResponse, Citation
from retrieval.knowledge_base import RetrievalService


class KnowledgeAgent(Agent):
    """Agent for SOP, FAQ, and case retrieval."""

    name = "knowledge"

    def __init__(self, retrieval: RetrievalService) -> None:
        self._retrieval = retrieval

    def run(self, request: AgentRequest) -> AgentResponse:
        docs = self._retrieval.search(request.query, top_k=3)
        response = AgentResponse(agent_name=self.name)
        if not docs:
            response.summary = "未检索到可用知识，请补充更多上下文后重试。"
            response.confidence = 0.2
            return response

        response.citations = [
            Citation.from_document(doc, snippet_length=200) for doc in docs
        ]
        response.summary = docs[0].summary
        response.findings = [doc.title for doc in docs]
        response.suggested_actions = [
            "优先查看第一条引用文档的完整 SOP",
            "如果需要案件化分析，可切换到 Investigation Agent 继续追问",
        ]
        response.confidence = min(0.95, 0.55 + len(docs) * 0.1)
        return response
