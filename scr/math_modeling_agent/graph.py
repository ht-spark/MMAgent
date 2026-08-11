"""
LangGraph 编排：主图组装。
"""
from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from ..runtime.logging import (
    get_run_logger,
    log_step,
    setup_run_logger,
)

from ..agents.paper_writer import write_paper_node
from ..agents.question_solver import solve_question_node
from ..agents.result_validator import validate_result_node
from ..agents.reviewer import review_paper_node
from ..gates.gf_delivery import route_gf
from ..gates.g0_intake import route_g0
from ..gates.gq_question import route_after_gq, run_gq_node
from ..runtime.budget import BudgetManager, BudgetType
from ..workflow.intake import run_intake
from ..workflow.project_context import run_context
from ..workflow.question_loop import (
    archive_result,
    assemble_context,
    configure_question_budget,
    route_after_select,
    select_question,
)
from .state import ProjectState, create_initial_state


# ---------------------------------------------------------------------------
# 节点日志装饰器
# ---------------------------------------------------------------------------

# 各运行的日志器（按 run_id 隔离，避免并发运行互相踩）
_run_loggers: dict[str, logging.Logger] = {}

# 各运行的进度回调（按 run_id 隔离，供 _logged_node 在节点开始时推送事件）
_run_progress_callbacks: dict[str, Callable[[dict], None]] = {}


def _get_logger(run_id: str | None = None) -> logging.Logger:
    """获取运行日志器。优先返回指定 run_id 的日志器，否则返回默认。"""
    if run_id and run_id in _run_loggers:
        return _run_loggers[run_id]
    return get_run_logger()


def _logged_node(name: str):
    """装饰 LangGraph 节点：记录开始/完成/失败日志（含耗时），并实时输出到控制台。

    日志写入 <output_dir>/run.log（JSON 结构化），
    控制台同时打印人类可读的实时进度。
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(state: ProjectState) -> dict:
            run_id = state.get("run_id")
            logger = _get_logger(run_id)
            question_id = state.get("current_question_id")
            t0 = time.monotonic()
            log_step(logger, f"node.{name}", "started", question_id=question_id)
            print(f"▶ [{name}] 开始", flush=True)

            # 节点开始时推送进度事件，让前端立即显示"XXX进行中"动画
            cb = _run_progress_callbacks.get(run_id)
            if cb is not None:
                try:
                    cb({
                        "type": "node_start",
                        "node": name,
                        "run_id": run_id,
                        "workflow_status": state.get("workflow_status"),
                        "current_question_id": question_id,
                        "timestamp": time.time(),
                    })
                except Exception:
                    pass

            try:
                result = fn(state)
                duration = time.monotonic() - t0
                log_step(
                    logger,
                    f"node.{name}",
                    "completed",
                    question_id=question_id,
                    duration=duration,
                )
                print(f"  ✔ [{name}] 完成（{duration:.1f}s）", flush=True)
                return result
            except Exception as e:
                duration = time.monotonic() - t0
                log_step(
                    logger,
                    f"node.{name}",
                    "failed",
                    question_id=question_id,
                    duration=duration,
                    error=str(e),
                )
                print(f"  ✗ [{name}] 失败: {e}", flush=True)
                # 系统性降级：节点异常不终止整题运行，记录错误并让流程继续
                return _degrade_node_failure(name, question_id, e)

        return wrapper

    return decorator


def _degrade_node_failure(
    node_name: str,
    question_id: str | None,
    error: Exception,
) -> dict:
    """
    节点异常的系统性降级。

    原则：任何节点抛错都不应终止整题运行。
      - ``solve_question`` 失败 → 构造 ``status="blocked"`` 的最小
        QuestionResult，复用 GQ 路由归档该小问并继续下一问
        （避免 archive 空结果导致 select_question 死循环）
      - 其他节点失败 → 仅记录错误，返回空更新，图继续

    Args:
        node_name: 节点名。
        question_id: 当前小问 ID。
        error: 捕获的异常。

    Returns:
        安全的状态更新字典。
    """
    err_entry = {"node": node_name, "msg": str(error)[:500]}
    print(f"  ⚠ [{node_name}] 异常已隔离，流程继续（错误已记录）", flush=True)

    if node_name == "solve_question":
        try:
            from ..schemas.question import QuestionResult

            blocked = QuestionResult(
                question_id=question_id or "",
                status="blocked",
                error_message=f"[{node_name}] {error}",
                findings={"summary": f"节点异常，小问被标记 blocked: {error}"},
                limitations=[f"{node_name} 异常: {error}"],
            )
        except Exception:
            # 极端情况：构造失败则仅记录错误（archive 会跳过，但不会崩溃）
            blocked = None
        return {
            "current_result": blocked,
            "_gq_action": "blocked",
            "errors": [err_entry],
        }

    # 其他节点：只记录错误，不覆盖任何状态
    return {"errors": [err_entry]}


def _print_state_update(node_name: str, update: dict) -> None:
    """实时打印节点返回的状态更新摘要（工作流状态变化）。"""
    # LangGraph 对返回空 dict {} 的节点会在 updates 流里发 None（表示无状态变更），
    # 此处统一归一化，避免 update.get(...) 对 None 崩溃。
    if not isinstance(update, dict):
        update = {}
    parts: list[str] = []
    for key in ("workflow_status", "current_question_id", "_gq_action"):
        value = update.get(key)
        if value:
            parts.append(f"{key}={value}")
    pc = update.get("project_context")
    if pc is not None and getattr(pc, "questions", None):
        parts.append(f"questions={len(pc.questions)}")
    qr = update.get("question_results")
    if qr is not None:
        parts.append(f"results={len(qr)}")
    detail = "  ".join(parts)
    suffix = f"：{detail}" if detail else ""
    print(f"  ◇ [{node_name}] 状态更新{suffix}", flush=True)


def _make_progress_event(node_name: str, update: dict) -> dict:
    """从节点状态更新中提取精简进度事件，供 Web 端轮询 / 推送。"""
    # 同 _print_state_update：LangGraph 可能对空更新发 None。
    if not isinstance(update, dict):
        update = {}
    results = update.get("question_results")
    results_count = len(results) if isinstance(results, dict) else None
    return {
        "type": "node",
        "node": node_name,
        "run_id": update.get("run_id"),
        "workflow_status": update.get("workflow_status"),
        "current_question_id": update.get("current_question_id"),
        "gq_action": update.get("_gq_action"),
        "results_count": results_count,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# 节点函数
# ---------------------------------------------------------------------------


@_logged_node("intake")
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


@_logged_node("context")
def _context_node(state: ProjectState) -> dict:
    """context 节点：全局上下文建立。"""
    print("[context] 开始：任务理解 + 小问拆分...")
    result = run_context(state)
    pc = result.get("project_context")
    if pc:
        print(f"[context] 完成：{len(pc.questions)} 个小问")
        for q in pc.questions:
            deps = pc.question_dependencies.get(q.question_id, [])
            print(f"  → {q.question_id}: {q.objective[:40]}... (deps={deps})")
    return result


@_logged_node("g0_retry")
def _g0_retry_node(state: ProjectState) -> dict:
    """G0 重试时消费 INTAKE_RETRY 预算。"""
    bm: BudgetManager | None = state.get("budget_manager")
    if bm is not None:
        ok = bm.consume(BudgetType.INTAKE_RETRY, amount=1)
        rem = bm.remaining(BudgetType.INTAKE_RETRY)
        print(f"[G0] 预算：INTAKE_RETRY 消耗 1 次，剩余 {rem}")
    retry_count = state.get("_g0_retry_count", 0)
    return {"_g0_retry_count": retry_count + 1}


@_logged_node("g0_clarification")
def _g0_clarification_node(state: ProjectState) -> dict:
    """G0 硬失败澄清节点：暂停等待用户选择终止或上传补充材料。"""
    cb = state.get("clarification_callback")
    if cb is None:
        # 无回调（CLI 模式）：直接终止
        print("[G0] 硬失败，无澄清回调，终止建模")
        return {"workflow_status": "failed", "_g0_clarification_action": "terminate"}

    # 获取 G0 失败项
    from ..gates.g0_intake import check_g0

    g0_result = check_g0(state)
    failed_checks = g0_result.failed_checks

    print(f"[G0] 硬失败，等待用户澄清: {failed_checks}")
    decision = cb({**state, "_g0_failed_checks": failed_checks})

    action = decision.get("action", "terminate") if decision else "terminate"
    if action == "terminate":
        print("[G0] 用户选择终止建模")
        return {"workflow_status": "failed", "_g0_clarification_action": "terminate"}

    # continue: 合并新数据路径
    new_paths = decision.get("new_data_paths", [])
    if new_paths:
        existing = list(state.get("data_paths", []))
        existing.extend(new_paths)
        print(f"[G0] 用户上传 {len(new_paths)} 个补充材料，重跑摄入")
        return {
            "data_paths": existing,
            "_g0_clarification_action": "continue",
        }
    return {"_g0_clarification_action": "continue"}


@_logged_node("select_question")
def _select_question_node(state: ProjectState) -> dict:
    """select_question 节点：选择下一个可执行的小问。"""
    return select_question(state)


@_logged_node("assemble_context")
def _assemble_context_node(state: ProjectState) -> dict:
    """assemble_context 节点：装配当前小问上下文。"""
    return assemble_context(state)


@_logged_node("configure_question_budget")
def _configure_question_budget_node(state: ProjectState) -> dict:
    """configure_question_budget 节点：调用回调让用户在该问覆盖预算上限。"""
    return configure_question_budget(state)


@_logged_node("solve_question")
def _solve_question_node(state: ProjectState) -> dict:
    """solve_question 节点：小问求解（含方法探索 + 建模计算）。"""
    return solve_question_node(state)


@_logged_node("validate_result")
def _validate_result_node(state: ProjectState) -> dict:
    """validate_result 节点：题型验证（Phase 5）。"""
    return validate_result_node(state)


@_logged_node("gq_check")
def _gq_check_node(state: ProjectState) -> dict:
    """gq_check 节点：GQ 小问结果质量门。"""
    return run_gq_node(state)


@_logged_node("archive_result")
def _archive_result_node(state: ProjectState) -> dict:
    """archive_result 节点：归档小问结果。"""
    return archive_result(state)


@_logged_node("global_review")
def _global_review_node(state: ProjectState) -> dict:
    """global_review 节点：全任务一致性审查（Phase 6 §6.1）。"""
    print("[global_review] 开始：全任务一致性审查...")
    result = review_paper_node(state)
    report = result.get("review_report")
    if report:
        print(f"[global_review] 完成: status={report.overall_status}, "
              f"critical={report.critical_count}, major={report.major_count}")
    return result


@_logged_node("write_paper")
def _write_paper_node(state: ProjectState) -> dict:
    """write_paper 节点：报告写作（Phase 6 §6.2）。"""
    print("[write_paper] 开始：报告写作...")
    result = write_paper_node(state)
    paper = result.get("paper_draft")
    if paper:
        print(f"[write_paper] 完成: {len(paper.sections)} 个章节, "
              f"全文 {len(paper.full_text)} 字符")
    return result


@_logged_node("review_paper")
def _review_paper_node(state: ProjectState) -> dict:
    """review_paper 节点：报告审查（Phase 6 §6.1）。"""
    print("[review_paper] 开始：报告审查...")
    result = review_paper_node(state)
    report = result.get("review_report")
    if report:
        print(f"[review_paper] 完成: status={report.overall_status}, "
              f"critical={report.critical_count}, major={report.major_count}")
    return result


@_logged_node("deliver")
def _deliver_node(state: ProjectState) -> dict:
    """deliver 节点：最终交付。

    保存报告 Markdown、转换为 DOCX、保存审查报告。
    """
    import os
    import json

    output_dir = state.get("output_dir", "artifacts/unknown")
    os.makedirs(output_dir, exist_ok=True)
    print(f"[deliver] 最终交付完成，产物目录: {output_dir}")

    # 保存报告 Markdown
    paper = state.get("paper_draft")
    paper_path = ""
    if paper and paper.full_text:
        paper_path = os.path.join(output_dir, "paper.md")
        with open(paper_path, "w", encoding="utf-8") as f:
            f.write(paper.full_text)
        print(f"[deliver] 报告 Markdown 已保存: {paper_path}")

        # 转换为 DOCX（优先 pandoc：LaTeX 公式转 Word 原生公式）
        try:
            from ..tools.md2docx import convert_paper_md_to_docx
            docx_path = convert_paper_md_to_docx(paper_path, output_dir)
            print(f"[deliver] 报告 DOCX 已保存: {docx_path}")
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


@_logged_node("gf_revise")
def _gf_revise_node(state: ProjectState) -> dict:
    """GF 修订时消费 PAPER_REVISION 预算并传递审查反馈。"""
    bm: BudgetManager | None = state.get("budget_manager")
    if bm is not None:
        ok = bm.consume(BudgetType.PAPER_REVISION, amount=1)
        rem = bm.remaining(BudgetType.PAPER_REVISION)
        print(f"[GF] 预算：PAPER_REVISION 消耗 1 次，剩余 {rem}")

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
    """
    构建 LangGraph 主图。
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
    builder.add_node("g0_clarification", _g0_clarification_node)

    # Phase 2-5 节点
    builder.add_node("select_question", _select_question_node)
    builder.add_node("assemble_context", _assemble_context_node)
    builder.add_node("configure_question_budget", _configure_question_budget_node)
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

    # G0 条件边：context → pass: select_question / retry: g0_retry / human: g0_clarification
    builder.add_conditional_edges(
        "context",
        route_g0,
        {"pass": "select_question", "retry": "g0_retry", "human": "g0_clarification"},
    )

    # 重试后回到 intake
    builder.add_edge("g0_retry", "intake")

    # G0 澄清：terminate → END / continue → intake（重跑摄入含补充材料）
    builder.add_conditional_edges(
        "g0_clarification",
        lambda state: "terminate" if state.get("_g0_clarification_action") == "terminate" else "continue",
        {"terminate": END, "continue": "intake"},
    )

    # Phase 2-5 边：逐问闭环
    # select_question → has_next: assemble_context / done: global_review
    builder.add_conditional_edges(
        "select_question",
        route_after_select,
        {"has_next": "assemble_context", "done": "global_review"},
    )

    # assemble_context → configure_question_budget → solve_question → validate_result → gq_check
    builder.add_edge("assemble_context", "configure_question_budget")
    builder.add_edge("configure_question_budget", "solve_question")
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

    # Phase 6 边：全任务审查 + 报告写作 + 交付
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
    log_level: int = logging.INFO,
    run_id: str | None = None,
    progress_callback: Callable[[dict], None] | None = None,
    console: bool = True,
    cancel_check: Callable[[], bool] | None = None,
    budget_manager: BudgetManager | None = None,
    budget_config_callback: Callable[[dict], dict | None] | None = None,
    clarification_callback: Callable[[dict], dict | None] | None = None,
) -> dict:
    """用 LangGraph 运行完整工作流。

    完整执行：
      输入摄入 → 全局上下文 → G0 质量门 → 逐问求解闭环（含验证）
      → 全任务审查 → 报告写作 → 报告审查 → 交付

    通过 G0 后，按依赖顺序逐问求解，每问经过建模计算、题型验证和 GQ 门后归档。
    所有小问处理完毕后，进行全任务审查、报告写作和交付。

    预算：
      - budget_manager：默认 None 时自动创建 BudgetManager（运行级单例）。
      - budget_config_callback：可选；签名 ``(state) -> dict[BudgetType, int] | None``。
        返回 None 或抛错视为沿用默认；返回 dict 时按该问临时覆盖预算上限。
        在每问 `assemble_context` 之后、`solve_question` 之前触发。

    Args:
        problem_text: 任务文本。
        data_paths: 数据文件路径（单个或列表，Excel 自动展开所有 sheet）。
        output_dir: 产物目录。
        llm: 可选 LLM 注入。
        search_provider: 可选搜索 Provider。
        checkpoint: 是否启用 checkpoint。
        log_level: 运行日志级别（写入 run.log，默认 INFO）。
        budget_manager: 预算管理器（None 时自动创建）。
        budget_config_callback: 用户预算覆盖回调（None 表示不暂停）。
        clarification_callback: G0 硬失败澄清回调（None 时直接终止）。

    Returns:
        最终 State。
    """
    import uuid

    if isinstance(data_paths, str):
        data_paths = [data_paths]

    run_id = run_id or uuid.uuid4().hex[:8]
    output_dir = output_dir or f"artifacts/{run_id}"

    # 默认预算管理器
    if budget_manager is None:
        budget_manager = BudgetManager()

    # 配置运行日志：run.log（JSON 结构化，实时追加）+ 控制台实时进度
    logger, log_path = setup_run_logger(
        run_id=run_id,
        log_dir=output_dir,
        level=log_level,
        console=console,
        console_level=logging.WARNING,
    )
    _run_loggers[run_id] = logger

    # 注册进度回调，供 _logged_node 在节点开始时推送 node_start 事件
    if progress_callback is not None:
        _run_progress_callbacks[run_id] = progress_callback

    print(f"▶ Run ID: {run_id}")
    print(f"▶ 输出目录: {output_dir}")
    if log_path:
        print(f"▶ 日志文件: {log_path}  （可用 Get-Content -Wait {log_path} 实时查看）")

    app = build_graph(checkpoint=False)
    config = {"configurable": {"thread_id": run_id}}

    initial_state = create_initial_state(
        run_id=run_id,
        output_dir=output_dir,
        problem_text=problem_text,
        data_paths=data_paths,
        llm=llm,
        search_provider=search_provider,
        budget_manager=budget_manager,
        budget_config_callback=budget_config_callback,
        clarification_callback=clarification_callback,
    )

    # 流式执行：每完成一个节点即实时输出其状态更新，便于实时查看进度
    final_state: dict | None = None
    for mode, chunk in app.stream(
        initial_state,
        config=config,
        stream_mode=["updates", "values"],
    ):
        if mode == "values":
            final_state = chunk
        else:
            # mode == "updates": chunk 是 {node_name: state_update}
            for node_name, update in chunk.items():
                _print_state_update(node_name, update)
                if progress_callback is not None:
                    try:
                        progress_callback(_make_progress_event(node_name, update))
                    except Exception:
                        pass
            # 中断检查点：每个节点完成后检查一次。run_graph 是同步阻塞调用，
            # 只能借节点边界自然退出；cancel_check 返回 True 即抛异常中断整个 stream。
            if cancel_check is not None and cancel_check():
                raise RuntimeError("Run cancelled by user")

    # 兜底：stream 未产出完整 values 时，从检查点读取最终状态
    if final_state is None:
        try:
            final_state = app.get_state(config).values
        except Exception:
            final_state = dict(initial_state)
    if progress_callback is not None:
        try:
            progress_callback(
                {
                    "type": "final",
                    "run_id": run_id,
                    "workflow_status": final_state.get("workflow_status"),
                }
            )
        except Exception:
            pass

    # 清理进度回调注册
    _run_progress_callbacks.pop(run_id, None)

    return dict(final_state)
