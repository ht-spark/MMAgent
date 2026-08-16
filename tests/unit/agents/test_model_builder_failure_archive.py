"""失败尝试归档测试：computation error 时代码与错误应落盘，便于追溯。

对应 run 549171fc 的排查问题：blocked 小问的求解代码和错误只在控制台
打印，artifacts/questions/<qid>/ 仅在成功时创建，导致根因不可追溯。
"""
from __future__ import annotations

import json

from scr.agents import code_modeler as cm
from scr.agents.model_builder import ModelBuilder
from scr.schemas.question import CurrentQuestionContext


class _FakeModeler:
    """替身 CodeModeler：返回固定模型与可执行但校验不过的代码。"""

    def __init__(self, llm) -> None:  # noqa: ANN001 - 与被替身签名一致
        pass

    def generate_model(self, **kwargs) -> dict:
        return {"model_name": "测试模型"}

    def generate_code(self, model_json, question_text="", data_summary="", feedback="") -> str:
        return "print('__MODEL_RESULT__' + '{}')"


def _context() -> CurrentQuestionContext:
    return CurrentQuestionContext(
        question_id="q1",
        question_text="求最优方案",
        objective="求最优方案",
        global_background="",
        global_constraints=[],
        required_data=[],
        inherited_summaries=[],
        budget_info={},
    )


def test_failed_attempt_persists_code_and_error(monkeypatch, tmp_path) -> None:
    """最终失败（不再重试）时应归档 solution.py 与含错误的 result.json。"""
    monkeypatch.setattr(cm, "CodeModeler", _FakeModeler)
    builder = ModelBuilder(llm=object(), budget_manager=None)  # 无预算 → 失败后不重试

    computation = builder._execute_code_based(
        "LLM 问题驱动建模",
        "composite",
        {"data_matrix": None},
        {},
        _context(),
        output_dir=str(tmp_path),
    )

    assert computation["status"] == "error"
    q_dir = tmp_path / "questions" / "q1"
    assert (q_dir / "solution.py").exists()
    result_json = json.loads((q_dir / "result.json").read_text(encoding="utf-8"))
    assert result_json["status"] == "error"
    assert result_json["results"].get("error")
