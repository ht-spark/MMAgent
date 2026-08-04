"""反思循环（P2-C1）与 code_based 题型扩展（P2-C2）单元测试。

覆盖：
  - _self_review：pass / revise / 无 LLM 三种情形
  - ModelBuilder.build(feedback=...) 的反馈传递到代码生成 prompt
  - CODE_BASED_TASKS 已覆盖 classification/clustering/composite
"""
from __future__ import annotations

import json
from pathlib import Path

from scr.agents.code_modeler import CODE_BASED_TASKS
from scr.agents.question_solver import QuestionSolver
from scr.schemas.question import CurrentQuestionContext, ProblemInterpretation


class MockStructuredLLM:
    """支持 with_structured_output 的 Mock LLM。"""

    def __init__(self, payload) -> None:
        self._payload = payload
        self._schema = None

    def with_structured_output(self, schema, method=None):
        self._schema = schema
        return self

    def invoke(self, prompt: str):
        assert self._schema is not None
        return self._schema.model_validate_json(self._payload)


def _context() -> CurrentQuestionContext:
    return CurrentQuestionContext(
        question_id="q1",
        question_text="求最优种植方案使总收益最大",
        objective="求最优种植方案使总收益最大",
        global_background="",
        global_constraints=[],
        required_data=["data.csv"],
        data_quality_summary="",
        inherited_summaries=[],
        budget_info={},
    )


def _interpretation() -> ProblemInterpretation:
    return ProblemInterpretation(
        question_id="q1",
        math_task="optimization",
        math_task_description="求最优种植方案使总收益最大",
        decision_variables=["x_i"],
        objective_function="max sum(p_i*x_i)",
        constraints=["sum(x_i)<=120"],
    )


def _model_output(status: str = "success") -> dict:
    return {
        "computation": {
            "status": status,
            "results": {"optimal_solution": [5.0], "optimal_objective": 10.0},
            "metrics": {"objective_value": 10.0},
        }
    }


def test_self_review_pass():
    payload = json.dumps({
        "verdict": "pass",
        "review": "结果正确回答了题目，目标值 10.0 与约束相符。",
        "suggestions": "",
    })
    solver = QuestionSolver(llm=MockStructuredLLM(payload))
    review = solver._self_review(_context(), _interpretation(), _model_output())
    assert review is not None
    assert review["verdict"] == "pass"
    assert "回答了题目" in review["review"]


def test_self_review_revise():
    payload = json.dumps({
        "verdict": "revise",
        "review": "结果未覆盖所有约束。",
        "suggestions": "补充土地约束并重新求解",
    })
    solver = QuestionSolver(llm=MockStructuredLLM(payload))
    review = solver._self_review(_context(), _interpretation(), _model_output())
    assert review is not None
    assert review["verdict"] == "revise"
    assert review["suggestions"] == "补充土地约束并重新求解"


def test_self_review_skipped_without_llm():
    solver = QuestionSolver(llm=None)
    assert solver._self_review(_context(), _interpretation(), _model_output()) is None


def test_feedback_reaches_code_generation(sample_csv: Path, tmp_path: Path):
    """ModelBuilder.build(feedback=...) 的改进建议应进入代码生成 prompt。"""
    from tests.unit.agents.test_code_modeling import _context as _ctx
    from tests.unit.agents.test_code_modeling import (
        _decision,
        _interpretation as _interp,
        _model_json,
    )
    from tests.unit.agents.test_code_modeling import MockLLM as BaseMockLLM
    from scr.agents.model_builder import ModelBuilder
    from scr.workflow.intake import run_intake

    class RecordingLLM(BaseMockLLM):
        def __init__(self, responses):
            super().__init__(responses)
            self.prompts: list[str] = []

        def invoke(self, prompt: str):
            self.prompts.append(prompt)
            return super().invoke(prompt)

    llm = RecordingLLM([_model_json("import json\n"
                                     'print("__MODEL_RESULT__" + json.dumps({"solution": [1.0], "objective": 5.0}))\n')])
    dp = run_intake(
        {"data_paths": [str(sample_csv)], "output_dir": str(tmp_path / "art")}
    )["data_profile"]

    builder = ModelBuilder(llm=llm)
    comp = builder.build(
        _ctx(), _interp(), _decision(), dp,
        output_dir=str(tmp_path / "out"),
        feedback="请补充约束敏感性分析",
    )["computation"]

    assert comp["status"] == "success"
    assert any("约束敏感性分析" in p for p in llm.prompts), "反馈未传递到代码生成 prompt"


def test_code_based_tasks_extended():
    """code_based 建模覆盖更多题型（P2-C2）。"""
    for task in ("classification", "clustering", "composite"):
        assert task in CODE_BASED_TASKS
