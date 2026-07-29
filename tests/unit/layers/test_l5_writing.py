"""L5 写作子图 smoke 测试。"""
import pytest

from scr.layers.l5_writing import L5WritingSubgraph
from scr.schemas.problem import ProblemAnalysis, SubProblem
from scr.schemas.result import ExecutionResult


def test_paper_generation_smoke(tmp_path):
    analysis = ProblemAnalysis(
        research_subject="城市经济评价",
        background="5 城市数据",
        explicit_questions=["问题一：评价"],
        constraints=[],
        expected_outputs=["排名"],
        keywords=[],
    )
    subproblems = [SubProblem(
        id="q1", task="评价", input_requirements=["GDP"],
        expected_outputs=[], dependencies=[], parallelizable=True,
    )]
    execution = ExecutionResult(
        success=True,
        numeric_outputs={"weights_sum": 1.0, "max_score": 0.8},
        runtime_seconds=0.5,
    )

    subgraph = L5WritingSubgraph(output_dir=tmp_path)
    result = subgraph.run(analysis, subproblems, execution, "熵权法")

    assert result["workflow_status"] == "l5_completed"
    assert (tmp_path / "paper_draft.md").exists()
    assert "问题重述" in result["paper_text"]
    assert "熵权法" in result["paper_text"]
    assert result["section_completeness_passed"] is True