"""L6 审查与交付 smoke 测试。"""
from pathlib import Path

import pandas as pd

from scr.layers.l6_review import L6ReviewSubgraph
from scr.schemas.problem import ProblemAnalysis
from scr.schemas.result import ExecutionResult


def test_review_and_final_package(tmp_path):
    # 模拟已有产物
    csv_path = tmp_path / "data.csv"
    pd.DataFrame({"x": [1, 2, 3]}).to_csv(csv_path, index=False)
    paper_path = tmp_path / "paper.md"
    paper_path.write_text(
        "# 城市经济评价\n\n## 1. 问题重述\n\n## 8. 模型检验\n\n## 4. 符号说明\n",
        encoding="utf-8",
    )

    analysis = ProblemAnalysis(
        research_subject="城市经济评价",
        background="背景",
        explicit_questions=["问题一：评价"],
        constraints=[],
        expected_outputs=["排名"],
        keywords=[],
    )
    execution = ExecutionResult(success=True, runtime_seconds=1.0)

    subgraph = L6ReviewSubgraph(output_dir=tmp_path)
    result = subgraph.run(
        problem_analysis=analysis,
        execution_result=execution,
        paper_text=paper_path.read_text(encoding="utf-8"),
        paper_path=str(paper_path),
        artifacts={"data": str(csv_path)},
    )

    # 调试输出
    print("\nREVIEW REPORT:", result["review_report"])
    assert Path(result["submission_checklist_path"]).exists()
    assert Path(result["final_package_dir"], "paper_final.md").exists()
    assert result["workflow_status"] == "l6_completed"