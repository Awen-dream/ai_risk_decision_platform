from unittest import TestCase

from core.models import PlannerTraceStep, SessionTurn
from services.presentation import build_session_turn_view, build_timeline_items


class PresentationTests(TestCase):
    def test_build_session_turn_view_for_copilot(self) -> None:
        turn = SessionTurn(
            agent_name="copilot",
            query="请综合分析这个订单和策略影响",
            context={"order_id": "O10001", "strategy_id": "STRAT-001"},
            summary="已完成联合分析",
            confidence=0.91,
            intent="composite",
            plan_steps=["调查", "策略", "图谱"],
            planner_trace=[
                PlannerTraceStep(step="调查", selected=True, reason="命中订单线索"),
                PlannerTraceStep(step="策略", selected=True, reason="包含策略标识"),
                PlannerTraceStep(step="图谱", selected=True, reason="需要关系网络补充"),
            ],
        )

        view = build_session_turn_view(turn)

        self.assertEqual("联合分析", view.title)
        self.assertEqual("workflow", view.agent_group)
        self.assertEqual("workflow", view.badge)
        self.assertEqual("high", view.severity)
        self.assertEqual(
            ["intent", "plan", "decision", "planner_trace", "findings", "actions"],
            view.expanded_sections,
        )
        self.assertEqual(["调查", "策略", "图谱"], view.plan_steps)
        self.assertEqual("调查", view.planner_trace[0].step)

    def test_build_timeline_items_preserves_display_metadata(self) -> None:
        investigation_view = build_session_turn_view(
            SessionTurn(
                agent_name="investigation",
                query="分析高风险订单",
                context={"order_id": "O10001"},
                summary="订单命中设备风险",
                confidence=0.82,
                intent="order_case",
            )
        )
        knowledge_view = build_session_turn_view(
            SessionTurn(
                agent_name="knowledge",
                query="营销套利 SOP 是什么",
                context={},
                summary="已返回 SOP 摘要",
                confidence=0.77,
            )
        )

        timeline = build_timeline_items([investigation_view, knowledge_view])

        self.assertEqual(2, len(timeline))
        self.assertEqual(1, timeline[0].turn_index)
        self.assertEqual("risk-graph", timeline[0].badge)
        self.assertEqual("medium", timeline[0].severity)
        self.assertEqual(2, timeline[1].turn_index)
        self.assertEqual("knowledge", timeline[1].agent_group)
        self.assertEqual("knowledge", timeline[1].badge)
        self.assertEqual("low", timeline[1].severity)
