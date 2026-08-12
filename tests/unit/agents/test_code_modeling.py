"""题目驱动建模（CodeModeler 分段 + ModelBuilder 集成）单元测试。

覆盖：
  - CodeModeler 模型设计解析（纯 JSON / markdown 代码块 / 杂文本）
  - CodeModeler 代码生成解析（```python 块 / 纯文本 / 空响应）
  - LLM 超时 → LLMTimeoutError（上层据此"超时即回退"）
  - ModelBuilder 分段成功路径 / 修复循环 / 全部失败回退 / 无 LLM
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from scr.agents.code_modeler import (
    CodeModeler,
    CodeModelingError,
    LLMTimeoutError,
)
from scr.agents.model_builder import ModelBuilder
from scr.runtime.budget import BudgetManager, BudgetType
from scr.schemas.question import CurrentQuestionContext, ProblemInterpretation


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


class MockLLM:
    """按顺序返回预设响应；用完返回最后一个。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.prompts: list[str] = []

    def invoke(self, prompt: str) -> _Msg:
        self.prompts.append(prompt)
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return _Msg(self._responses[idx])


class SlowLLM:
    """模拟 LLM 调用耗时（用于超时测试）。"""

    def __init__(self, delay: float) -> None:
        self._delay = delay

    def invoke(self, prompt: str) -> _Msg:
        time.sleep(self._delay)
        return _Msg("{}")


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


def _model_design() -> str:
    """第一段输出：数学模型 JSON（不含代码）。"""
    return json.dumps({
        "model_name": "测试LP",
        "model_summary": "max 收益",
        "math_task": "optimization",
        "variables": [{"symbol": "x", "meaning": "分配量", "domain": "continuous"}],
        "objective": "max: sum(c_i*x_i)",
        "constraints": ["sum(x)<=cap"],
        "key_parameters": {"cap": 10},
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


class TestCodeModelerModelDesign:
    def test_parse_plain_json(self):
        modeler = CodeModeler(MockLLM([_model_design()]))
        m = modeler.generate_model("小问", "optimization")
        assert m["model_name"] == "测试LP"
        assert "solution_code" not in m  # 第一段不生成代码

    def test_parse_markdown_fenced(self):
        payload = f"```json\n{_model_design()}\n```"
        m = CodeModeler(MockLLM([payload])).generate_model("小问", "optimization")
        assert m["math_task"] == "optimization"

    def test_parse_with_surrounding_text(self):
        payload = f"好的，以下是模型：\n{_model_design()}\n以上。"
        m = CodeModeler(MockLLM([payload])).generate_model("小问", "optimization")
        assert m["model_name"] == "测试LP"

    def test_unparseable_raises(self):
        modeler = CodeModeler(MockLLM(["这不是 JSON 内容"]))
        with pytest.raises(CodeModelingError, match="无法从 LLM 响应中解析"):
            modeler.generate_model("小问", "optimization")


class TestCodeModelerCodeGeneration:
    def test_generate_code_plain(self):
        modeler = CodeModeler(MockLLM([GOOD_CODE]))
        code = modeler.generate_code(json.loads(_model_design()))
        assert "__MODEL_RESULT__" in code
        assert "json" in code

    def test_generate_code_fenced(self):
        payload = f"```python\n{GOOD_CODE}\n```"
        code = CodeModeler(MockLLM([payload])).generate_code(json.loads(_model_design()))
        assert "__MODEL_RESULT__" in code

    def test_empty_response_raises(self):
        modeler = CodeModeler(MockLLM(["   \n  "]))
        with pytest.raises(CodeModelingError, match="响应为空"):
            modeler.generate_code(json.loads(_model_design()))


class TestLLMTimeout:
    def test_timeout_raises_llm_timeout_error(self):
        modeler = CodeModeler(SlowLLM(delay=5))
        with pytest.raises(LLMTimeoutError, match="超时"):
            modeler._invoke("prompt", timeout=1)

    def test_timeout_is_subclass_of_modeling_error(self):
        assert issubclass(LLMTimeoutError, CodeModelingError)


class TestModelBuilderCodeBased:
    def _build(self, llm, data_profile):
        builder = ModelBuilder(llm=llm)
        return builder.build(
            _context(), _interpretation(), _decision(), data_profile
        )["computation"]

    def _responses_ok(self) -> list[str]:
        """成功路径：模型设计 → 好代码。"""
        return [_model_design(), GOOD_CODE]

    def test_code_based_success(self, sample_csv: Path, tmp_path: Path):
        from scr.workflow.intake import run_intake

        dp = run_intake(
            {"data_paths": [str(sample_csv)], "output_dir": str(tmp_path / "art")}
        )["data_profile"]
        comp = self._build(MockLLM(self._responses_ok()), dp)
        assert comp["status"] == "success"
        assert comp["method_key"] == "code_based"
        assert "solution" in comp["results"]

    def test_failed_attempt_is_returned_for_gq_retry(self, sample_csv: Path, tmp_path: Path):
        from scr.workflow.intake import run_intake

        dp = run_intake(
            {"data_paths": [str(sample_csv)], "output_dir": str(tmp_path / "art")}
        )["data_profile"]
        comp = self._build(MockLLM([_model_design(), BAD_CODE]), dp)
        assert comp["status"] == "error"

    def test_code_failure_retries_with_code_repair_budget(self, sample_csv: Path, tmp_path: Path):
        from scr.workflow.intake import run_intake

        dp = run_intake(
            {"data_paths": [str(sample_csv)], "output_dir": str(tmp_path / "art")}
        )["data_profile"]
        budget_manager = BudgetManager(
            run_limits={BudgetType.CODE_REPAIR: 1}
        )
        builder = ModelBuilder(
            llm=MockLLM([_model_design(), BAD_CODE, _model_design(), GOOD_CODE]),
            budget_manager=budget_manager,
        )

        comp = builder.build(_context(), _interpretation(), _decision(), dp)["computation"]

        assert comp["status"] == "success"
        assert budget_manager.get_record(BudgetType.CODE_REPAIR).used == 1

    def test_llm_failure_does_not_fallback_to_preset_method(self, sample_csv: Path, tmp_path: Path):
        from scr.workflow.intake import run_intake

        dp = run_intake(
            {"data_paths": [str(sample_csv)], "output_dir": str(tmp_path / "art")}
        )["data_profile"]
        comp = self._build(
            MockLLM([_model_design(), BAD_CODE, _model_design(), BAD_CODE]), dp
        )
        assert comp["status"] == "error"
        assert "失败" in comp["error"] or comp["error"]

    def test_no_llm_does_not_use_preset_method(self, sample_csv: Path, tmp_path: Path):
        from scr.workflow.intake import run_intake

        dp = run_intake(
            {"data_paths": [str(sample_csv)], "output_dir": str(tmp_path / "art")}
        )["data_profile"]
        comp = self._build(None, dp)
        assert comp["status"] == "error"
        assert "LLM" in comp["error"]

    def test_model_design_receives_complete_problem_context_without_candidates(self):
        llm = MockLLM([_model_design(), GOOD_CODE])
        builder = ModelBuilder(llm=llm)
        context = CurrentQuestionContext(
            question_id="q1",
            question_text="计算烟幕对导弹视线的有效遮蔽时长",
            objective="建立运动学几何模型并求遮蔽时间",
            global_background="导弹、无人机、干扰弹和烟幕云团在三维空间中运动",
            global_constraints=["烟幕球半径10m", "起爆后20s有效", "忽略空气阻力"],
        )
        interpretation = ProblemInterpretation(
            question_id="q1",
            math_task="simulation",
            math_task_description="确定性运动学几何问题",
            constraints=["导弹到目标线段与烟幕球相交"],
            necessary_assumptions=["无人机和导弹匀速直线运动"],
            result_form="有效遮蔽时间区间和总时长",
        )
        decision = {"selected_method": "LLM 问题驱动建模"}

        builder.build(context, interpretation, decision, data_profile=None)

        prompt = llm.prompts[0]
        assert "烟幕球半径10m" in prompt
        assert "不预选候选方法" in prompt
