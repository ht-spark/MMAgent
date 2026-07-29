"""main.py 端到端 smoke 测试（无 LLM，使用占位数据）。"""
from pathlib import Path

import pandas as pd

from scr.math_modeling_agent.main import run


def test_end_to_end_no_llm(tmp_path):
    """无 LLM 时端到端 demo 应能跑通，产出 final_package。"""
    csv_path = tmp_path / "city.csv"
    pd.DataFrame({
        "城市": ["北京", "上海", "广州", "深圳"],
        "GDP(亿元)": [40269, 43215, 28232, 30664],
        "人口(万人)": [2189, 2487, 1881, 1768],
    }).to_csv(csv_path, index=False, encoding="utf-8")

    result = run(
        problem_text="对 4 个城市的经济指标进行综合评价",
        data_paths=csv_path,
        output_dir=tmp_path / "artifacts",
    )

    # 基础断言
    assert "run_id" in result
    assert result["workflow_status"] in ("l6_completed", "l6_issues")
    # 最终包目录存在
    final_dir = Path(result["final_package_dir"])
    assert final_dir.exists()
    assert (final_dir / "paper_final.md").exists()
    assert (final_dir / "review_report.json").exists()
    assert (final_dir / "submission_checklist.md").exists()