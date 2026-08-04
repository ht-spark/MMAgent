"""论文核心章节 LLM 起草（P1-B3）单元测试。

覆盖：
  - 提供 LLM 时，"模型建立/结果解释"核心段落由 LLM 生成
  - 无 LLM 时回退确定性模板
"""
from __future__ import annotations

from pathlib import Path

from scr.agents.paper_writer import PaperWriter
from scr.schemas.context import ProjectContext, QuestionInfo
from scr.schemas.question import QuestionResult


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


class MockTextLLM:
    """只支持 invoke 返回文本的 Mock LLM（paper_writer 需要）。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def invoke(self, prompt: str) -> _Msg:
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return _Msg(self._responses[idx])


def _question_result(qid: str = "q1") -> QuestionResult:
    return QuestionResult(
        question_id=qid,
        status="validated",
        findings={
            "selected_method": "线性规划",
            "math_task": "optimization",
            "key_result": "最优目标值 10.0",
        },
        problem_interpretation=None,
        computation={
            "status": "success",
            "results": {"optimal_objective": 10.0, "optimal_solution": [5.0, 5.0]},
            "metrics": {},
        },
        decision_record={"selected_method": "线性规划"},
        assumptions=[{"id": "a1", "content": "测试假设", "rationale": "测试"}],
        formulation={
            "description": "线性规划模型",
            "objective_function": "max x1 + x2",
            "decision_variables": ["x1", "x2"],
            "constraints": ["x1 + x2 <= 10"],
            "parameters": {"cap": 10},
        },
        validation={"passed": True, "checks": []},
        limitations=["测试"],
    )


def _project_context() -> ProjectContext:
    return ProjectContext(
        run_id="test-run",
        problem_text="C题 资源优化问题",
        background_summary="在有限资源下最大化收益。",
        objectives=["求最优方案"],
        questions=[
            QuestionInfo(
                question_id="q1",
                original_text="问题一：建立优化模型",
                objective="求最优种植方案",
                question_type="optimization",
            ),
        ],
    )


def _state(tmp_path: Path) -> dict:
    return {
        "question_results": {"q1": _question_result()},
        "project_context": _project_context(),
        "data_profile": None,
        "output_dir": str(tmp_path),
    }


def test_write_uses_llm_for_core_sections(tmp_path):
    """提供 LLM 时，模型建立/结果解释段落由 LLM 起草。"""
    llm = MockTextLLM([
        "模型建立段：我们建立了线性规划模型，决策变量为 x1、x2，目标是最大化总收益。",
        "结果解释段：最优目标值为 10.0，方案满足全部约束。",
    ])
    writer = PaperWriter(llm=llm)
    paper = writer.write(_state(tmp_path), output_dir=str(tmp_path))

    full = paper.full_text
    assert "模型建立段" in full
    assert "结果解释段" in full
    assert llm.calls >= 2
    # 章节标题结构未被破坏
    assert "q1.3 模型建立" in full
    assert "q1.4 求解与结果" in full


def test_write_falls_back_to_template_without_llm(tmp_path):
    """无 LLM 时回退确定性模板，论文仍完整生成。"""
    writer = PaperWriter(llm=None)
    paper = writer.write(_state(tmp_path), output_dir=str(tmp_path))

    full = paper.full_text
    assert paper.title != ""
    assert "q1.3 模型建立" in full
    assert "q1.4 求解与结果" in full
    assert "模型建立段" not in full  # 未使用 LLM 文本
