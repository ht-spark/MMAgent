"""LangGraph 集成 smoke 测试（无 LLM）。"""
from pathlib import Path

import pandas as pd

from scr.math_modeling_agent.graph import build_graph, run_graph


def test_build_graph():
    """构建 LangGraph 主图不报错。"""
    app = build_graph(checkpoint=False)
    assert app is not None


def test_run_graph_no_llm(tmp_path):
    """无 LLM 时 LangGraph 端到端跑通。"""
    csv_path = tmp_path / "city.csv"
    pd.DataFrame({
        "城市": ["北京", "上海", "广州", "深圳"],
        "GDP(亿元)": [40269, 43215, 28232, 30664],
        "人口(万人)": [2189, 2487, 1881, 1768],
    }).to_csv(csv_path, index=False, encoding="utf-8")

    final_state = run_graph(
        problem_text="4 个城市经济综合评价",
        data_paths=str(csv_path),
        output_dir=str(tmp_path / "artifacts"),
        llm=None,
        search_provider=None,
        checkpoint=False,
    )

    # 验证最终状态
    assert final_state.get("workflow_status") in ("l6_completed", "l6_issues")
    final_dir = final_state.get("final_package_dir", "")
    assert final_dir
    assert Path(final_dir, "paper_final.md").exists()