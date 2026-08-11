"""Project context fallback decomposition tests."""
from __future__ import annotations

from scr.schemas.problem import ProblemAnalysis
from scr.workflow.project_context import _create_fallback_subproblems


def test_fallback_subproblems_keep_dependency_only_when_question_refers_back():
    analysis = ProblemAnalysis(
        research_subject="生产调度优化",
        background="根据订单、设备和交付时间制定生产计划。",
        explicit_questions=[
            "问题一 建立生产能力评价体系，识别瓶颈工序",
            "问题二 在问题一的基础上优化生产排程并降低延期成本",
            "问题三 分析订单需求波动下方案的稳定性",
        ],
        constraints=["设备能力有限", "订单必须按期交付"],
        expected_outputs=[],
        keywords=["生产调度", "产能", "延期成本"],
    )

    subproblems = _create_fallback_subproblems(analysis)

    assert [sp.id for sp in subproblems] == ["q1", "q2", "q3"]
    assert subproblems[0].dependencies == []
    assert subproblems[1].dependencies == ["q1"]
    assert subproblems[2].dependencies == []
    assert all(sp.expected_outputs for sp in subproblems)
    assert all(sp.is_fallback for sp in subproblems)
