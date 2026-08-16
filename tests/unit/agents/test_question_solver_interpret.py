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


def test_solve_backfills_interpretation_from_model_output() -> None:
    """solve() 应将 LLM 建模产物回填到问题理解的空缺字段（LLM-only 来源）。"""

    class _StubBuilder:
        def build(self, context, interpretation, decision_record,
                  data_profile=None, output_dir=None, feedback=""):
            return {
                "formulation": {"method": "LLM 问题驱动建模", "description": "测试模型"},
                "data_preparation": {},
                "computation": {
                    "status": "success",
                    "results": {"solution": [1.0]},
                    "metrics": {"objective": 1.0},
                    "intermediate_values": {
                        "variables": [{"symbol": "x", "meaning": "种植面积", "domain": "continuous"}],
                        "objective": "max Z",
                        "constraints": [],
                    },
                },
                "figures": [],
                "tables": [],
            }

    solver = QuestionSolver(llm=None)
    solver._builder = _StubBuilder()
    result = solver.solve(_context())

    interp = result.problem_interpretation
    assert interp.decision_variables == [
        {"symbol": "x", "meaning": "种植面积", "domain": "continuous"}
    ]
    assert interp.objective_function == "max Z"
