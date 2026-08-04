"""题目驱动建模（CodeModeler + ModelBuilder 集成）单元测试。

覆盖：
  - CodeModeler 响应解析（纯 JSON / markdown 代码块 / 杂文本）
  - CodeModeler 错误分支（解析失败、缺 solution_code）
  - ModelBuilder 题目驱动成功路径 / 修复循环 / 回退 / 无 LLM
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scr.agents.code_modeler import CodeModeler, CodeModelingError
from scr.agents.model_builder import ModelBuilder
from scr.schemas.question import CurrentQuestionContext, ProblemInterpretation


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


class MockLLM:
    """按顺序返回预设响应；用完返回最后一个。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def invoke(self, prompt: str) -> _Msg:
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return _Msg(self._responses[idx])


GOOD_CODE = (
    "import json\n"
    'result = {"solution": [5.0, 5.0], "objective": 10.0, '
    '"metrics": {"n_vars": 2}}\n'
    'print("__MODEL_RESULT__" + json.dumps(result))\n'
)

BAD_CODE = (
    "import json\n"
    'print("__MODEL_RESULT__" + json.dumps({"x": 1/0}))\n'
)


def _model_json(code: str) -> str:
    return json.dumps({
        "model_name": "测试LP",
        "model_summary": "max 收益",
        "math_task": "optimization",
        "variables": [{"symbol": "x", "meaning": "分配量", "domain": "continuous"}],
        "objective": "max: sum(c_i*x_i)",
        "constraints": ["sum(x)<=cap"],
        "key_parameters": {"cap": 10},
        "solution_code": code,
    })


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
        math_task_description="测试",
        result_form="最优方案表",
    )


def _decision() -> dict:
    return {"selected_method": "线性规划", "canonical_method": "linear_programming"}


class TestCodeModeler:
    def test_parse_plain_json(self):
        modeler = CodeModeler(MockLLM([_model_json(GOOD_CODE)]))
        m = modeler.generate_model("小问", "optimization")
        assert m["model_name"] == "测试LP"
        assert "solution_code" in m

    def test_parse_markdown_fenced(self):
        payload = f"```json\n{_model_json(GOOD_CODE)}\n```"
        modeler = CodeModeler(MockLLM([payload]))
        m = modeler.generate_model("小问", "optimization")
        assert m["math_task"] == "optimization"

    def test_parse_with_surrounding_text(self):
        payload = f"好的，以下是模型：\n{_model_json(GOOD_CODE)}\n以上。"
        modeler = CodeModeler(MockLLM([payload]))
        m = modeler.generate_model("小问", "optimization")
        assert m["model_name"] == "测试LP"

    def test_unparseable_raises(self):
        modeler = CodeModeler(MockLLM(["这不是 JSON 内容"]))
        with pytest.raises(CodeModelingError, match="无法从 LLM 响应中解析"):
            modeler.generate_model("小问", "optimization")

    def test_missing_solution_code_raises(self):
        payload = json.dumps({"model_name": "无代码"})
        modeler = CodeModeler(MockLLM([payload]))
        with pytest.raises(CodeModelingError, match="solution_code"):
            modeler.generate_model("小问", "optimization")


class TestModelBuilderCodeBased:
    def _build(self, llm, data_profile):
        builder = ModelBuilder(llm=llm)
        return builder.build(
            _context(), _interpretation(), _decision(), data_profile
        )["computation"]

    def test_code_based_success(self, sample_csv: Path, tmp_path: Path):
        from scr.workflow.intake import run_intake

        dp = run_intake(
            {"data_paths": [str(sample_csv)], "output_dir": str(tmp_path / "art")}
        )["data_profile"]
        comp = self._build(MockLLM([_model_json(GOOD_CODE)]), dp)
        assert comp["status"] == "success"
        assert comp["method_key"] == "code_based"
        assert "solution" in comp["results"]

    def test_repair_loop(self, sample_csv: Path, tmp_path: Path):
        from scr.workflow.intake import run_intake

        dp = run_intake(
            {"data_paths": [str(sample_csv)], "output_dir": str(tmp_path / "art")}
        )["data_profile"]
        comp = self._build(
            MockLLM([_model_json(BAD_CODE), _model_json(GOOD_CODE)]), dp
        )
        assert comp["status"] == "success"
        assert comp["method_key"] == "code_based"
        assert comp["intermediate_values"]["generation_attempts"] == 2

    def test_fallback_after_all_failures(self, sample_csv: Path, tmp_path: Path):
        from scr.workflow.intake import run_intake

        dp = run_intake(
            {"data_paths": [str(sample_csv)], "output_dir": str(tmp_path / "art")}
        )["data_profile"]
        comp = self._build(
            MockLLM([_model_json(BAD_CODE), _model_json(BAD_CODE)]), dp
        )
        assert comp["status"] == "success"  # 回退预设方法
        assert comp["method_key"] != "code_based"

    def test_no_llm_uses_preset(self, sample_csv: Path, tmp_path: Path):
        from scr.workflow.intake import run_intake

        dp = run_intake(
            {"data_paths": [str(sample_csv)], "output_dir": str(tmp_path / "art")}
        )["data_profile"]
        comp = self._build(None, dp)
        assert comp["status"] == "success"
        assert comp["method_key"] != "code_based"
