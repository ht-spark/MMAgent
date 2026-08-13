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
from scr.tools.md2docx import convert_paper_md_to_docx


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
        self.last_prompt = prompt
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


def test_llm_core_sections_receive_writing_guide(tmp_path):
    """报告写作总纲应注入 LLM 写作提示词。"""
    llm = MockTextLLM([
        "模型建立段：基于题目约束建立模型。",
        "结果解释段：仅依据给定结果进行分析。",
    ])

    PaperWriter(llm=llm).write(_state(tmp_path), output_dir=str(tmp_path))

    assert "数学建模竞赛论文主笔与技术编辑" in llm.last_prompt
    assert "不得编造" in llm.last_prompt


def test_write_falls_back_to_template_without_llm(tmp_path):
    """无 LLM 时回退确定性模板，论文仍完整生成。"""
    writer = PaperWriter(llm=None)
    paper = writer.write(_state(tmp_path), output_dir=str(tmp_path))

    full = paper.full_text
    assert paper.title != ""
    assert "q1.3 模型建立" in full
    assert "q1.4 求解与结果" in full
    assert "模型建立段" not in full  # 未使用 LLM 文本


def test_write_tolerates_list_shaped_computation_fields(tmp_path):
    """求解器异常返回列表时，报告写作仍应完成，保证后续 DOCX 可交付。"""
    result = _question_result()
    result.computation["results"] = ["unexpected result"]
    result.computation["metrics"] = ["unexpected metric"]
    result.formulation["parameters"] = ["unexpected parameter"]

    paper = PaperWriter().write(
        {
            "question_results": {"q1": result},
            "project_context": _project_context(),
            "data_profile": None,
            "output_dir": str(tmp_path),
        },
        output_dir=str(tmp_path),
    )

    assert paper.full_text
    assert "q1.4 求解与结果" in paper.full_text

    markdown_path = tmp_path / "paper.md"
    markdown_path.write_text(paper.full_text, encoding="utf-8")
    docx_path = Path(convert_paper_md_to_docx(markdown_path))
    assert docx_path.is_file()


def test_write_tolerates_vector_metrics(tmp_path):
    """仿真指标为向量时，报告写作不应因数值格式化中断。"""
    result = _question_result()
    result.findings["math_task"] = "simulation"
    result.findings["selected_method"] = "随机游走模型"
    result.computation["results"] = {"simulation": {"time": [0, 1, 2]}}
    result.computation["metrics"] = {
        "n_simulations": 100,
        "mean": [0.0, 1.25, 2.5],
        "std": [0.0, 0.1, 0.2],
        "ci_lower": [0.0, 1.0, 2.0],
        "ci_upper": [0.0, 1.5, 3.0],
    }

    paper = PaperWriter().write(
        {
            "question_results": {"q1": result},
            "project_context": _project_context(),
            "data_profile": None,
            "output_dir": str(tmp_path),
        },
        output_dir=str(tmp_path),
    )

    assert paper.full_text
    assert "[0.0000, 1.2500, 2.5000]" in paper.full_text


def test_llm_receives_compact_result_material(tmp_path):
    """LLM 写作输入应是选择性摘要，而不是原始大数组。"""
    llm = MockTextLLM([
        "模型建立段：建立仿真模型。",
        "结果解释段：仿真轨迹随时间变化，关键指标已由摘要给出。",
    ])
    result = _question_result()
    result.findings["math_task"] = "simulation"
    result.findings["selected_method"] = "随机游走模型"
    result.computation["results"] = {
        "simulation": {
            "time": list(range(20)),
            "x": [i * 2 for i in range(20)],
        }
    }
    result.computation["metrics"] = {
        "mean": [i * 0.5 for i in range(20)],
    }

    PaperWriter(llm=llm).write(
        {
            "question_results": {"q1": result},
            "project_context": _project_context(),
            "data_profile": None,
            "output_dir": str(tmp_path),
        },
        output_dir=str(tmp_path),
    )

    assert "20项，首值=0.0000，末值=19.0000" in llm.last_prompt
    assert "0, 1, 2, 3, 4, 5, 6, 7, 8, 9" not in llm.last_prompt
