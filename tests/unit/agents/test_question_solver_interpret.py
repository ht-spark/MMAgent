"""问题澄清 LLM 化（P1-B1）单元测试。

覆盖：
  - 有 LLM 时由 LLM 生成 ProblemInterpretation（决策变量/目标/约束/假设/结果形式）
  - 无 LLM 或调用失败时回退启发式
"""
from __future__ import annotations

import json

from scr.agents.question_solver import QuestionSolver
from scr.schemas.question import CurrentQuestionContext


class MockStructuredLLM:
    """支持 with_structured_output 的 Mock LLM：invoke 返回 schema 实例。"""

    def __init__(self, payload: str) -> None:
        self._payload = payload
        self._schema = None

    def with_structured_output(self, schema, method=None):
        self._schema = schema
        return self

    def invoke(self, prompt: str):
        assert self._schema is not None, "with_structured_output 未被调用"
        return self._schema.model_validate_json(self._payload)


def _context() -> CurrentQuestionContext:
    return CurrentQuestionContext(
        question_id="q1",
        question_text="求最优种植方案使总收益最大",
        objective="求最优种植方案使总收益最大",
        global_background="某农场共有 120 亩土地",
        global_constraints=["土地总量有限"],
        required_data=["data.csv"],
        data_quality_summary="1 张表、99 行",
        inherited_summaries=[],
        budget_info={},
    )


def _llm_payload() -> str:
    return json.dumps({
        "question_id": "q1",
        "math_task": "optimization",
        "math_task_description": "在种植成本与土地约束下最大化总收益",
        "decision_variables": ["x_i"],
        "objective_function": "max sum(p_i * x_i)",
        "constraints": ["sum(land_i * x_i) <= 120"],
        "evaluation_metrics": ["总收益"],
        "result_form": "最优种植方案表",
        "available_data": ["data.csv"],
        "missing_data": ["市场价格波动数据"],
        "necessary_assumptions": ["各作物价格保持稳定"],
        "acceptable_simplifications": ["忽略运输成本"],
        "relation_to_previous": "independent",
        "relation_description": "",
    })


def test_interpret_uses_llm_when_available():
    """有 LLM 时问题澄清由 LLM 生成（含决策变量/目标/约束/假设）。"""
    solver = QuestionSolver(llm=MockStructuredLLM(_llm_payload()))
    interp = solver._interpret_problem(_context())

    assert interp.question_id == "q1"
    assert interp.math_task == "optimization"
    assert interp.decision_variables == ["x_i"]
    assert interp.objective_function.startswith("max")
    assert "120" in interp.constraints[0]
    assert interp.necessary_assumptions == ["各作物价格保持稳定"]
    assert interp.result_form == "最优种植方案表"


def test_interpret_falls_back_to_heuristic_without_llm():
    """无 LLM 时回退启发式（决策变量等深度字段为空）。"""
    solver = QuestionSolver(llm=None)
    interp = solver._interpret_problem(_context())

    assert interp.question_id == "q1"
    assert interp.math_task == "optimization"  # 启发式关键词判断
    assert interp.decision_variables == []
    assert interp.objective_function == ""
    assert interp.result_form  # 启发式给出结果形式


def test_interpret_falls_back_on_llm_error():
    """LLM 返回非法 math_task 时回退启发式，不中断。"""

    class BadLLM(MockStructuredLLM):
        def invoke(self, prompt):
            # 非法 math_task，pydantic 校验失败
            return self._schema.model_validate_json(
                json.dumps({"question_id": "q1", "math_task": "not_a_task"})
            )

    solver = QuestionSolver(llm=BadLLM(_llm_payload()))
    interp = solver._interpret_problem(_context())

    assert interp.math_task == "optimization"  # 回退启发式
