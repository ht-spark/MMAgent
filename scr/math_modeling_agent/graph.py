"""LangGraph 编排：主图组装。

对应 architecture.md §2 总体工作流和 plan.md 分阶段执行。

完整实现 Phase 0 ~ Phase 6：

  START → intake → context → G0 条件边
    G0 pass → select_question → (条件边)
      has_next → assemble_context → solve_question → validate_result → gq_check → (条件边)
        pass → archive_result → select_question (循环)
        retry → solve_question (重试)
        blocked → archive_result → select_question (循环)
      done → global_review → write_paper → review_paper → gf_check → (条件边)
        deliver → END
        revise → write_paper (修订)
    G0 retry → g0_retry → intake (重跑输入摄入)
    G0 human → END (人工介入)
"""
from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from ..agents.paper_writer import write_paper_node
from ..agents.question_solver import solve_question_node
from ..agents.result_validator import validate_result_node
from ..agents.reviewer import review_paper_node
from ..gates.gf_delivery import route_gf
from ..gates.g0_intake import route_g0
from ..gates.gq_question import route_after_gq, run_gq_node
from ..workflow.intake import run_intake
from ..workflow.project_context import run_context
from ..workflow.question_loop import (
    archive_result,
    assemble_context,
    route_after_select,
    select_question,
)
from .state import ProjectState, create_initial_state


# ---------------------------------------------------------------------------
# 节点函数
# ---------------------------------------------------------------------------


def _intake_node(state: ProjectState) -> dict:
    """intake 节点：输入摄入。"""
    print("[intake] 开始：数据画像...")
    result = run_intake(state)
    dp = result.get("data_profile")
    if dp:
        print(f"[intake] 完成：{len(dp.files)} 个文件、{len(dp.tables)} 张表、{len(dp.fields)} 个字段")
        for finding in dp.preliminary_findings:
            print(f"  → {finding}")
    return result


def _context_node(state: ProjectState) -> dict:
    """context 节点：全局上下文建立。"""
    print("[context] 开始：题目理解 + 小问拆分...")
    result = run_context(state)
    pc = result.get("project_context")
    if pc:
        print(f"[context] 完成：{len(pc.questions)} 个小问")
        for q in pc.questions:
            deps = pc.question_dependencies.get(q.question_id, [])
            print(f"  → {q.question_id}: {q.objective[:40]}... (deps={deps})")
    return result


def _g0_retry_node(state: ProjectState) -> dict:
    """G0 重试时递增计数器。"""
    retry_count = state.get("_g0_retry_count", 0)
    return {"_g0_retry_count": retry_count + 1}


def _select_question_node(state: ProjectState) -> dict:
    """select_question 节点：选择下一个可执行的小问。"""
    return select_question(state)


def _assemble_context_node(state: ProjectState) -> dict:
    """assemble_context 节点：装配当前小问上下文。"""
    return assemble_context(state)


def _solve_question_node(state: ProjectState) -> dict:
    """solve_question 节点：小问求解（含方法探索 + 建模计算）。"""
    return solve_question_node(state)


def _validate_result_node(state: ProjectState) -> dict:
    """validate_result 节点：题型验证（Phase 5）。"""
    return validate_result_node(state)


def _gq_check_node(state: ProjectState) -> dict:
    """gq_check 节点：GQ 小问结果质量门。"""
    return run_gq_node(state)


def _archive_result_node(state: ProjectState) -> dict:
    """archive_result 节点：归档小问结果。"""
    return archive_result(state)


def _global_review_node(state: ProjectState) -> dict:
    """global_review 节点：全题一致性审查（Phase 6 §6.1）。"""
    print("[global_review] 开始：全题一致性审查...")
    result = review_paper_node(state)
    report = result.get("review_report")
    if report:
        print(f"[global_review] 完成: status={report.overall_status}, "
              f"critical={report.critical_count}, major={report.major_count}")
    return result


def _write_paper_node(state: ProjectState) -> dict:
    """write_paper 节点：论文写作（Phase 6 §6.2）。"""
    print("[write_paper] 开始：论文写作...")
    result = write_paper_node(state)
    paper = result.get("paper_draft")
    if paper:
        print(f"[write_paper] 完成: {len(paper.sections)} 个章节, "
              f"全文 {len(paper.full_text)} 字符")
    return result


def _review_paper_node(state: ProjectState) -> dict:
    """review_paper 节点：论文审查（Phase 6 §6.1）。"""
    print("[review_paper] 开始：论文审查...")
    result = review_paper_node(state)
    report = result.get("review_report")
    if report:
        print(f"[review_paper] 完成: status={report.overall_status}, "
              f"critical={report.critical_count}, major={report.major_count}")
    return result


def _deliver_node(state: ProjectState) -> dict:
    """deliver 节点：最终交付。

    保存论文 Markdown、转换为 DOCX、保存审查报告。
    """
    import os
    import json

    output_dir = state.get("output_dir", "artifacts/unknown")
    os.makedirs(output_dir, exist_ok=True)
    print(f"[deliver] 最终交付完成，产物目录: {output_dir}")

    # 保存论文 Markdown
    paper = state.get("paper_draft")
    paper_path = ""
    if paper and paper.full_text:
        paper_path = os.path.join(output_dir, "paper.md")
        with open(paper_path, "w", encoding="utf-8") as f:
            f.write(paper.full_text)
        print(f"[deliver] 论文 Markdown 已保存: {paper_path}")

        # 转换为 DOCX
        try:
            from ..tools.md2docx import convert_paper_md_to_docx
            docx_path = convert_paper_md_to_docx(paper_path, output_dir)
            print(f"[deliver] 论文 DOCX 已保存: {docx_path}")
        except Exception as e:
            print(f"[deliver] DOCX 转换失败（不影响交付）: {e}")

    # 保存审查报告
    review = state.get("review_report")
    if review:
        review_path = os.path.join(output_dir, "review_report.json")
        with open(review_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "overall_status": review.overall_status,
                    "summary": review.summary,
                    "issues": [
                        {
                            "issue_id": i.issue_id,
                            "severity": i.severity,
                            "category": i.category,
                            "message": i.message,
                            "location": i.location,
                            "suggested_fix": i.suggested_fix,
                        }
                        for i in review.issues
                    ],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"[deliver] 审查报告已保存: {review_path}")

    return {"workflow_status": "delivered", "final_package_dir": output_dir}


def _gf_revise_node(state: ProjectState) -> dict:
    """GF 修订时递增计数器并传递审查反馈。"""
    retry_count = state.get("_gf_retry_count", 0)
    review_report = state.get("review_report")
    print(f"[GF] 开始第 {retry_count + 1} 次修订")

    # 如果有审查报告，打印待修复问题摘要
    if review_report and review_report.issues:
        critical_issues = [i for i in review_report.issues if i.severity == "critical"]
        major_issues = [i for i in review_report.issues if i.severity == "major"]
        print(f"[GF] 待修复: {len(critical_issues)} 个严重问题, {len(major_issues)} 个重要问题")
        for issue in (critical_issues + major_issues)[:5]:
            print(f"  → [{issue.severity}] {issue.category}: {issue.message[:80]}")

    return {
        "_gf_retry_count": retry_count + 1,
        # review_report 已经在 state 中，write_paper_node 会读取它
    }


# ---------------------------------------------------------------------------
# 主图构建
# ---------------------------------------------------------------------------


def build_graph(checkpoint: bool = True):
    """构建 LangGraph 主图。

    完整实现 Phase 0 ~ Phase 6：
      START → intake → context → G0
        G0 pass → select_question → has_next: assemble → solve → validate → GQ
                                                                   pass/blocked: archive → select_question
                                                                   retry: solve (重试)
                                done: global_review → write_paper → review_paper → GF
                                                                   deliver: END
                                                                   revise: write_paper
        G0 retry → g0_retry → intake
        G0 human → END

    Args:
        checkpoint: 是否启用 MemorySaver checkpoint（可 resume）。

    Returns:
        编译后的 LangGraph app。
    """
    builder = StateGraph(ProjectState)

    # Phase 1 节点
    builder.add_node("intake", _intake_node)
    builder.add_node("context", _context_node)
    builder.add_node("g0_retry", _g0_retry_node)

    # Phase 2-5 节点
    builder.add_node("select_question", _select_question_node)
    builder.add_node("assemble_context", _assemble_context_node)
    builder.add_node("solve_question", _solve_question_node)
    builder.add_node("validate_result", _validate_result_node)
    builder.add_node("gq_check", _gq_check_node)
    builder.add_node("archive_result", _archive_result_node)

    # Phase 6 节点
    builder.add_node("global_review", _global_review_node)
    builder.add_node("write_paper", _write_paper_node)
    builder.add_node("review_paper", _review_paper_node)
    builder.add_node("gf_revise", _gf_revise_node)
    builder.add_node("deliver", _deliver_node)

    # Phase 1 边
    builder.add_edge(START, "intake")
    builder.add_edge("intake", "context")

    # G0 条件边：context → pass: select_question / retry: g0_retry / human: END
    builder.add_conditional_edges(
        "context",
        route_g0,
        {"pass": "select_question", "retry": "g0_retry", "human": END},
    )

    # 重试后回到 intake
    builder.add_edge("g0_retry", "intake")

    # Phase 2-5 边：逐问闭环
    # select_question → has_next: assemble_context / done: global_review
    builder.add_conditional_edges(
        "select_question",
        route_after_select,
        {"has_next": "assemble_context", "done": "global_review"},
    )

    # assemble_context → solve_question → validate_result → gq_check
    builder.add_edge("assemble_context", "solve_question")
    builder.add_edge("solve_question", "validate_result")
    builder.add_edge("validate_result", "gq_check")

    # gq_check → pass: archive_result / retry: solve_question / blocked: archive_result
    builder.add_conditional_edges(
        "gq_check",
        route_after_gq,
        {"pass": "archive_result", "retry": "solve_question", "blocked": "archive_result"},
    )

    # archive_result → select_question (循环回去选下一问)
    builder.add_edge("archive_result", "select_question")

    # Phase 6 边：全题审查 + 论文写作 + 交付
    # global_review → write_paper → review_paper → gf_check
    builder.add_edge("global_review", "write_paper")
    builder.add_edge("write_paper", "review_paper")

    # gf_check → deliver / revise
    builder.add_conditional_edges(
        "review_paper",
        route_gf,
        {"deliver": "deliver", "revise": "gf_revise"},
    )

    # gf_revise → write_paper (修订后重新写作)
    builder.add_edge("gf_revise", "write_paper")

    # deliver → END
    builder.add_edge("deliver", END)

    if checkpoint:
        return builder.compile(checkpointer=MemorySaver())
    return builder.compile()


def run_graph(
    problem_text: str,
    data_paths: str | list[str],
    output_dir: str | None = None,
    llm: Any | None = None,
    search_provider: Any | None = None,
    checkpoint: bool = True,
) -> dict:
    """用 LangGraph 运行完整工作流。

    完整执行 Phase 0 ~ Phase 6：
      输入摄入 → 全局上下文 → G0 质量门 → 逐问求解闭环（含验证）
      → 全题审查 → 论文写作 → 论文审查 → 交付

    通过 G0 后，按依赖顺序逐问求解，每问经过建模计算、题型验证和 GQ 门后归档。
    所有小问处理完毕后，进行全题审查、论文写作和交付。

    Args:
        problem_text: 题目文本。
        data_paths: 数据文件路径（单个或列表，Excel 自动展开所有 sheet）。
        output_dir: 产物目录。
        llm: 可选 LLM 注入。
        search_provider: 可选搜索 Provider。
        checkpoint: 是否启用 checkpoint。

    Returns:
        最终 State。
    """
    import uuid

    if isinstance(data_paths, str):
        data_paths = [data_paths]

    run_id = uuid.uuid4().hex[:8]
    output_dir = output_dir or f"artifacts/{run_id}"

    app = build_graph(checkpoint=checkpoint)
    config = {"configurable": {"thread_id": run_id}}

    initial_state = create_initial_state(
        run_id=run_id,
        output_dir=output_dir,
        problem_text=problem_text,
        data_paths=data_paths,
        llm=llm,
        search_provider=search_provider,
    )

    final_state = app.invoke(initial_state, config=config)
    return dict(final_state)
