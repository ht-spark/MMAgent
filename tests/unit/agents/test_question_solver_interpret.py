"""Tests for neutral subproblem context construction."""
from __future__ import annotations

from scr.agents.question_solver import QuestionSolver
from scr.schemas.question import CurrentQuestionContext


def _context() -> CurrentQuestionContext:
    return CurrentQuestionContext(
        question_id="q1",
        question_text="求最优种植方案使总收益最大",
        objective="求最优种植方案使总收益最大",
        global_background="某农场共有 120 亩土地",
        global_constraints=["土地总量有限"],
        required_data=["data.csv"],
        inherited_summaries=[],
        budget_info={},
    )


def test_interpret_preserves_context_without_preclassification() -> None:
    """Interpretation must not invoke a prompt or infer a fixed task type."""
    interpretation = QuestionSolver(llm=None)._interpret_problem(_context())

    assert interpretation.question_id == "q1"
    assert interpretation.math_task == "composite"
    assert interpretation.math_task_description == "求最优种植方案使总收益最大"
    assert interpretation.constraints == ["土地总量有限"]
    assert interpretation.available_data == ["data.csv"]
    assert interpretation.decision_variables == []
    assert interpretation.result_form == ""
