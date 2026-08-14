"""代码建模反馈传递与通用代码建模覆盖测试。"""
from __future__ import annotations

from pathlib import Path

def test_feedback_reaches_code_generation(sample_csv: Path, tmp_path: Path):
    """ModelBuilder.build(feedback=...) 的改进建议应进入代码生成 prompt。"""
    from tests.unit.agents.test_code_modeling import _context as _ctx
    from tests.unit.agents.test_code_modeling import (
        _decision,
        _interpretation as _interp,
        _model_design,
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

    code = ('import json\n'
            'print("__MODEL_RESULT__" + json.dumps('
            '{"solution": [1.0], "objective": 5.0, "metrics": {"n": 1}}))\n')
    # 分段接口：第一段输出模型设计 JSON，第二段输出求解代码
    llm = RecordingLLM([_model_design(), code])
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
