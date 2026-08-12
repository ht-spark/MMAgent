"""Phase 0+1+2 端到端集成测试。

对应 plan.md Phase 2 验收：
  "系统可以使用 Stub 求解器跑完多个小问，并为每问生成合法的 QuestionResult。"

测试场景：
  1. 图构建无错误
  2. 无 LLM 端到端跑通（含数据画像、题目理解、逐问求解）
  3. 两问递进题中 Q2 能读取 Q1 的可复用结论
  4. 所有小问都被处理（validated 或 blocked）
  5. Q2 验证失败时不影响 Q1 的结果
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scr.math_modeling_agent.graph import build_graph, run_graph
from scr.math_modeling_agent.state import create_initial_state
from scr.schemas.context import ProjectContext, QuestionInfo
from scr.schemas.question import QuestionResult, ReusableSummary


# ---------------------------------------------------------------------------
# 图构建测试
# ---------------------------------------------------------------------------


def test_build_graph():
    """构建 LangGraph 主图不报错。"""
    app = build_graph(checkpoint=False)
    assert app is not None


def test_graph_places_budget_configuration_at_each_required_stage():
    """预算节点分别位于子任务求解前和全任务交付前。"""
    graph = build_graph(checkpoint=False).get_graph()
    assert "configure_question_budget" in graph.nodes
    assert "configure_delivery_budget" in graph.nodes

    edges = {(edge.source, edge.target) for edge in graph.edges}
    assert ("assemble_context", "configure_question_budget") in edges
    assert ("configure_question_budget", "solve_question") in edges
    assert ("configure_delivery_budget", "global_review") in edges


# ---------------------------------------------------------------------------
# 端到端测试
# ---------------------------------------------------------------------------


def test_run_graph_no_llm_two_questions(tmp_path):
    """无 LLM 时端到端跑通两问递进题。"""
    # 创建测试数据
    csv_path = tmp_path / "city.csv"
    pd.DataFrame({
        "城市": ["北京", "上海", "广州", "深圳"],
        "GDP(亿元)": [40269, 43215, 28232, 30664],
        "人口(万人)": [2189, 2487, 1881, 1768],
    }).to_csv(csv_path, index=False, encoding="utf-8")

    problem_text = """
某城市经济数据分析。请建立数学模型，研究下列问题：
问题1 对4个城市的经济进行综合评价，给出排名。
问题2 根据评价结果，预测未来发展趋势。
"""

    final_state = run_graph(
        problem_text=problem_text,
        data_paths=str(csv_path),
        output_dir=str(tmp_path / "artifacts"),
        llm=None,
        checkpoint=False,
    )

    # 验证工作流完成（Phase 6 交付后状态为 delivered）
    assert final_state.get("workflow_status") in ("delivered", "all_questions_done")
    dp = final_state.get("data_profile")
    assert dp is not None
    assert len(dp.files) > 0
    assert len(dp.tables) > 0

    # 验证题目理解
    pc = final_state.get("project_context")
    assert pc is not None
    assert len(pc.questions) >= 1

    # 验证小问求解结果
    question_results = final_state.get("question_results", {})
    assert len(question_results) > 0

    # 每个小问都应该被处理
    for q in pc.questions:
        qr = question_results.get(q.question_id)
        assert qr is not None, f"小问 {q.question_id} 未被处理"
        assert qr.status in ("validated", "blocked"), f"小问 {q.question_id} 状态异常: {qr.status}"

    print(f"\n[测试] 处理了 {len(question_results)} 个小问")
    for qid, qr in question_results.items():
        print(f"  {qid}: {qr.status}")


def test_run_graph_no_data(tmp_path):
    """无数据文件时也能跑通（只处理题目文本）。"""
    problem_text = """
某优化问题。请建立数学模型，研究下列问题：
问题1 给出最优种植方案。
"""

    final_state = run_graph(
        problem_text=problem_text,
        data_paths=[],
        output_dir=str(tmp_path / "artifacts"),
        llm=None,
        checkpoint=False,
    )

    assert final_state.get("workflow_status") in ("delivered", "all_questions_done")

    pc = final_state.get("project_context")
    assert pc is not None
    assert len(pc.questions) >= 1

    question_results = final_state.get("question_results", {})
    assert len(question_results) >= 1


def test_question_results_have_reusable_summary(tmp_path):
    """每个验证通过的小问都有 reusable_summary。"""
    csv_path = tmp_path / "data.csv"
    pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]}).to_csv(csv_path, index=False)

    problem_text = """
问题1 建立评价模型。
"""

    final_state = run_graph(
        problem_text=problem_text,
        data_paths=str(csv_path),
        output_dir=str(tmp_path / "artifacts"),
        llm=None,
        checkpoint=False,
    )

    question_results = final_state.get("question_results", {})
    for qid, qr in question_results.items():
        if qr.status == "validated":
            assert qr.reusable_summary is not None, f"小问 {qid} 缺少 reusable_summary"
            assert len(qr.reusable_summary.verified_conclusions) > 0


def test_question_results_have_interpretation(tmp_path):
    """每个小问都有 problem_interpretation。"""
    csv_path = tmp_path / "data.csv"
    pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]}).to_csv(csv_path, index=False)

    problem_text = """
问题1 优化种植方案。
"""

    final_state = run_graph(
        problem_text=problem_text,
        data_paths=str(csv_path),
        output_dir=str(tmp_path / "artifacts"),
        llm=None,
        checkpoint=False,
    )

    question_results = final_state.get("question_results", {})
    for qid, qr in question_results.items():
        assert qr.problem_interpretation is not None, f"小问 {qid} 缺少 problem_interpretation"
        assert qr.problem_interpretation.math_task != ""


def test_decision_log_recorded(tmp_path):
    """决策日志记录了小问处理。"""
    csv_path = tmp_path / "data.csv"
    pd.DataFrame({"x": [1, 2, 3]}).to_csv(csv_path, index=False)

    problem_text = "问题1 建立模型。"

    final_state = run_graph(
        problem_text=problem_text,
        data_paths=str(csv_path),
        output_dir=str(tmp_path / "artifacts"),
        llm=None,
        checkpoint=False,
    )

    dl = final_state.get("decision_log")
    assert dl is not None
    assert len(dl.entries) > 0


# ---------------------------------------------------------------------------
# 局部回退测试
# ---------------------------------------------------------------------------


def test_local_rollback_preserves_q1(tmp_path):
    """Q2 失败不影响 Q1 的结果（局部回退）。

    通过手动构造状态来验证：Q1 已验证，Q2 被阻塞。
    """
    from scr.workflow.question_loop import archive_result
    from scr.schemas.evidence import DecisionLog
    from scr.schemas.question import ProblemInterpretation

    # Q1 已验证
    q1_result = QuestionResult(
        question_id="q1",
        status="validated",
        problem_interpretation=ProblemInterpretation(
            question_id="q1",
            math_task="evaluation",
            result_form="评价排名表",
        ),
        reusable_summary=ReusableSummary(
            question_id="q1",
            verified_conclusions=["Q1结论"],
        ),
        limitations=["Q1限制"],
        findings={"summary": "Q1 求解完成"},
    )

    # Q2 被阻塞
    q2_result = QuestionResult(
        question_id="q2",
        status="blocked",
        error_message="GQ 验证失败",
        limitations=["Q2限制"],
    )

    # 先归档 Q1
    state_after_q1 = archive_result({
        "current_question_id": "q1",
        "current_result": q1_result,
        "question_results": {},
        "decision_log": DecisionLog(),
    })

    # 然后归档 Q2（blocked）
    state_after_q2 = archive_result({
        "current_question_id": "q2",
        "current_result": q2_result,
        "question_results": state_after_q1["question_results"],
        "decision_log": state_after_q1["decision_log"],
    })

    # Q1 结果不变
    results = state_after_q2["question_results"]
    assert results["q1"].status == "validated"
    assert results["q1"].findings["summary"] == "Q1 求解完成"
    assert results["q1"].reusable_summary.verified_conclusions == ["Q1结论"]

    # Q2 被阻塞
    assert results["q2"].status == "blocked"
    assert "GQ 验证失败" in results["q2"].error_message


# ---------------------------------------------------------------------------
# 上下文继承测试
# ---------------------------------------------------------------------------


def test_q2_inherits_q1_summary(tmp_path):
    """Q2 能继承 Q1 的可复用结论。"""
    from scr.workflow.question_loop import assemble_context
    from scr.schemas.question import ProblemInterpretation

    questions = [
        QuestionInfo(
            question_id="q1",
            original_text="问题1 建立评价",
            objective="建立评价",
            expected_output="排名表",
            depends_on=[],
        ),
        QuestionInfo(
            question_id="q2",
            original_text="问题2 预测趋势",
            objective="预测趋势",
            expected_output="预测值",
            depends_on=["q1"],
        ),
    ]

    q1_result = QuestionResult(
        question_id="q1",
        status="validated",
        problem_interpretation=ProblemInterpretation(
            question_id="q1",
            math_task="evaluation",
            result_form="评价排名表",
        ),
        reusable_summary=ReusableSummary(
            question_id="q1",
            verified_conclusions=["北京排名第一", "上海排名第二"],
            limitations=["样本量小"],
        ),
        limitations=["样本量小"],
    )

    pc = ProjectContext(
        run_id="test",
        problem_text="测试",
        background_summary="背景",
        constraints=[],
        questions=questions,
        question_dependencies={"q1": [], "q2": ["q1"]},
        question_data_map={"q1": [], "q2": []},
    )

    state = {
        "project_context": pc,
        "data_profile": None,
        "question_results": {"q1": q1_result},
        "current_question_id": "q2",
    }

    result = assemble_context(state)
    ctx = result["current_context"]

    # Q2 继承了 Q1 的可复用摘要
    assert len(ctx.inherited_summaries) == 1
    assert ctx.inherited_summaries[0]["question_id"] == "q1"
    assert "北京排名第一" in ctx.inherited_summaries[0]["verified_conclusions"]
