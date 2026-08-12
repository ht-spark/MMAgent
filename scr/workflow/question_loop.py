"""
协调子问题选择、上下文装配和结果归档的工作流节点。

职责：
  1. select_question — 根据依赖关系选择当前可执行的小问
  2. assemble_context — 装配 CurrentQuestionContext，选择性继承前问成果
  3. archive_result — 将当前小问结果归档到 question_results

状态流转：
  pending → solving → validating → validated
                                    ↘ blocked

设计要点：
  - 编排器只负责流程控制，不做数学推理
  - 选择性继承：只传递 reusable_summary，不传递完整历史推理
  - 局部回退：重做 Q2 不影响已验证的 Q1
"""
from __future__ import annotations

from ..runtime.logging import get_run_logger, log_step
from ..schemas.context import DataProfile, ProjectContext, QuestionInfo
from ..schemas.question import (
    CurrentQuestionContext,
    ProblemInterpretation,
    QuestionResult,
    ReusableSummary,
)
from ..schemas.evidence import DecisionLog


# ---------------------------------------------------------------------------
# 节点 1：select_question — 选择下一个小问
# ---------------------------------------------------------------------------


def select_question(state: dict) -> dict:
    """LangGraph 节点：选择下一个可执行的小问。

    根据依赖关系图，选择第一个满足以下条件的小问：
      - 状态为 pending
      - 所有依赖小问已 validated 或 blocked

    如果没有可执行的小问，则标记工作流完成。

    Args:
        state: 项目状态。

    Returns:
        状态更新字典，包含 current_question_id 和 workflow_status。
    """
    project_context: ProjectContext | None = state.get("project_context")
    if project_context is None:
        return {"workflow_status": "failed", "errors": [{"msg": "project_context missing in select_question"}]}

    question_results: dict[str, QuestionResult] = state.get("question_results", {})
    dependencies = project_context.question_dependencies

    next_qid = ""
    for q in project_context.questions:
        # 跳过已完成的小问
        existing = question_results.get(q.question_id)
        if existing is not None and existing.status in ("validated", "blocked"):
            continue

        # 检查依赖是否满足
        deps = dependencies.get(q.question_id, [])
        deps_met = all(
            _is_dependency_satisfied(dep, question_results)
            for dep in deps
        )
        if deps_met:
            next_qid = q.question_id
            break

    if not next_qid:
        # 没有可执行的小问了
        log_step(
            get_run_logger(),
            "workflow.select_question",
            "completed",
            detail="所有小问处理完毕",
        )
        return {
            "current_question_id": "",
            "workflow_status": "all_questions_done",
        }

    print(f"[question_loop] 选择小问: {next_qid}")

    # 进入新小问：重置强制型预算的"单问用量"（监控项 TIME/TOKEN 不重置）
    budget_manager = state.get("budget_manager")
    if budget_manager is not None:
        budget_manager.reset_for_new_question()

    log_step(
        get_run_logger(),
        "workflow.select_question",
        "completed",
        detail=f"选择下一个小问: {next_qid}",
    )

    return {
        "current_question_id": next_qid,
        "workflow_status": "solving",
        "_solve_retry_count": 0,
        "_gq_action": "",
        "_gq_feedback": "",
    }


def route_after_select(state: dict) -> str:
    """select_question 后的路由函数。

    Returns:
        "has_next" → 进入上下文装配
        "done" → 所有小问处理完毕
    """
    qid = state.get("current_question_id", "")
    if qid:
        return "has_next"
    return "done"


# ---------------------------------------------------------------------------
# 节点 2：assemble_context — 装配当前小问上下文
# ---------------------------------------------------------------------------


def assemble_context(state: dict) -> dict:
    """LangGraph 节点：装配 CurrentQuestionContext。

    装配内容：
      - 当前小问原文与目标
      - 相关的全局背景与约束
      - 所需数据及质量信息
      - 前置小问的 reusable_summary（选择性继承）
      - 当前项目的时间、算力与工具预算

    选择性继承规则：
      - 前问结论是本问的输入或约束 → 直接继承
      - 前问方法可作为基线 → 继承方法与局限
      - 前问数据处理能复用 → 继承处理后的数据及其口径
      - 与本问无关的中间推理 → 不传入

    Args:
        state: 项目状态。

    Returns:
        状态更新字典，包含 current_context。
    """
    project_context: ProjectContext | None = state.get("project_context")
    data_profile: DataProfile | None = state.get("data_profile")
    question_results: dict[str, QuestionResult] = state.get("question_results", {})
    current_qid = state.get("current_question_id", "")

    if not project_context or not current_qid:
        return {"errors": [{"msg": f"Cannot assemble context: qid={current_qid}"}]}

    # 找到当前小问信息
    question_info = _find_question(project_context, current_qid)
    if question_info is None:
        return {"errors": [{"msg": f"Question {current_qid} not found in project_context"}]}

    # 选择性继承：只从当前小问的依赖中提取 reusable_summary
    deps = project_context.question_dependencies.get(current_qid, [])
    inherited_summaries = _selective_inherit(deps, question_results)

    # 数据质量摘要
    data_quality_summary = _build_data_quality_summary(data_profile, question_info)

    # 预算信息
    budget_info = _build_budget_info(state)

    # 所需数据
    required_data = project_context.question_data_map.get(current_qid, question_info.required_data)

    current_context = CurrentQuestionContext(
        question_id=current_qid,
        question_text=question_info.original_text,
        objective=question_info.objective,
        global_background=project_context.background_summary,
        global_constraints=project_context.constraints,
        required_data=required_data,
        data_quality_summary=data_quality_summary,
        inherited_summaries=inherited_summaries,
        budget_info=budget_info,
    )

    print(f"[question_loop] 装配上下文: {current_qid}")
    inherited_count = len(inherited_summaries)
    if inherited_summaries:
        print(f"  → 继承 {inherited_count} 个前问摘要")
    if required_data:
        print(f"  → 所需数据: {required_data}")
    log_step(
        get_run_logger(),
        "workflow.assemble_context",
        "completed",
        question_id=current_qid,
        detail=(
            f"继承 {inherited_count} 个前问摘要"
            + (f"；所需数据: {required_data}" if required_data else "")
        ),
    )

    return {"current_context": current_context}


# ---------------------------------------------------------------------------
# 节点 3：archive_result — 归档小问结果
# ---------------------------------------------------------------------------


def archive_result(state: dict) -> dict:
    """LangGraph 节点：归档当前小问结果。

    将 current_result 写入 question_results 字典。
    验证通过的写入 validated，被阻塞的写入 blocked。
    归档后清理当前小问的可写状态（局部回退的基础）。

    Args:
        state: 项目状态。

    Returns:
        状态更新字典，包含更新后的 question_results 和清理后的 current_* 字段。
    """
    current_qid = state.get("current_question_id", "")
    current_result: QuestionResult | None = state.get("current_result")

    if not current_qid or current_result is None:
        return {"errors": [{"msg": f"Cannot archive: qid={current_qid}, result={current_result}"}]}

    # 获取已有的 question_results（需要深拷贝以触发 LangGraph 状态更新）
    question_results: dict[str, QuestionResult] = dict(state.get("question_results", {}))

    # 写入结果
    question_results[current_qid] = current_result
    print(f"[question_loop] 归档小问 {current_qid}: status={current_result.status}")
    log_step(
        get_run_logger(),
        "workflow.archive_result",
        "completed",
        question_id=current_qid,
        detail=f"归档小问结果，status={current_result.status}",
    )

    # 记录决策日志
    decision_log: DecisionLog | None = state.get("decision_log")
    if decision_log:
        if current_result.status == "validated":
            decision_log.log(
                decision_type="model_selection",
                description=f"小问 {current_qid} 验证通过",
                question_id=current_qid,
                reasoning=current_result.findings.get("summary", "") if current_result.findings else "",
            )
        elif current_result.status == "blocked":
            decision_log.log(
                decision_type="rollback",
                description=f"小问 {current_qid} 被阻塞: {current_result.error_message}",
                question_id=current_qid,
            )

    # 清理当前小问的可写状态（为下一问做准备）
    return {
        "question_results": question_results,
        "current_question_id": "",
        "current_context": None,
        "current_result": None,
        "_solve_retry_count": 0,
        "_gq_action": "",
        "_gq_feedback": "",
        "decision_log": decision_log,
    }


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _find_question(
    project_context: ProjectContext,
    question_id: str,
) -> QuestionInfo | None:
    """在 ProjectContext 中查找指定小问。"""
    for q in project_context.questions:
        if q.question_id == question_id:
            return q
    return None


def _is_dependency_satisfied(
    dep_id: str,
    question_results: dict[str, QuestionResult],
) -> bool:
    """检查依赖小问是否已完成（validated 或 blocked）。

    blocked 的小问也算"完成"，因为它的失败结论可能被后续小问参考。
    """
    result = question_results.get(dep_id)
    if result is None:
        return False
    return result.status in ("validated", "blocked")


def _selective_inherit(
    dependency_ids: list[str],
    question_results: dict[str, QuestionResult],
) -> list[dict]:
    """选择性继承前问的可复用摘要。

    只传递 reusable_summary，不传递：
      - 完整的推理历史
      - 失败的中间尝试
      - 冗长的原始文本

    Args:
        dependency_ids: 当前小问依赖的前问 ID 列表。
        question_results: 已完成的小问结果库。

    Returns:
        可复用摘要列表（每个元素是一个 dict，包含 question_id 和摘要内容）。
    """
    summaries: list[dict] = []
    for dep_id in dependency_ids:
        result = question_results.get(dep_id)
        if result is None or result.status != "validated":
            # 依赖未验证通过，不继承（但 blocked 的可以继承错误信息）
            if result and result.status == "blocked":
                summaries.append({
                    "question_id": dep_id,
                    "status": "blocked",
                    "error": result.error_message,
                    "note": "前问被阻塞，结果不可靠",
                })
            continue

        if result.reusable_summary is None:
            continue

        # 只提取 reusable_summary 的结构化内容
        summary = result.reusable_summary
        summaries.append({
            "question_id": dep_id,
            "status": "validated",
            "verified_conclusions": summary.verified_conclusions,
            "reusable_datasets": summary.reusable_datasets,
            "model_interface": summary.model_interface,
            "key_parameters": summary.key_parameters,
            "limitations": summary.limitations,
            "improvement_directions": summary.improvement_directions,
        })

    return summaries


def _build_data_quality_summary(
    data_profile: DataProfile | None,
    question_info: QuestionInfo,
) -> str:
    """为当前小问构建数据质量摘要。

    从全局 DataProfile 中提取与当前小问相关的数据质量信息。
    """
    if data_profile is None or not data_profile.files:
        return "无附件数据"

    parts: list[str] = []

    # 基本统计
    total_tables = len(data_profile.tables)
    total_rows = sum(t.n_rows for t in data_profile.tables)
    parts.append(f"共 {total_tables} 张表、{total_rows} 行数据")

    # 时间维度
    if data_profile.has_time_column:
        time_cols = [f.field_name for f in data_profile.fields if f.is_time_column]
        parts.append(f"时间列: {', '.join(time_cols[:5])}")
    else:
        parts.append("无时间维度列（不可使用时间序列模型）")

    # 样本量
    max_sample = data_profile.max_sample_size
    if max_sample > 0:
        if max_sample < 30:
            parts.append(f"最大样本量 {max_sample}（小样本，慎用高参数模型）")
        else:
            parts.append(f"最大样本量 {max_sample}")

    # 高严重度质量问题
    high_issues = [q for q in data_profile.quality_issues if q.severity == "high"]
    if high_issues:
        issue_msgs = [f"{q.target}({q.issue_type})" for q in high_issues[:3]]
        parts.append(f"高严重度问题: {', '.join(issue_msgs)}")

    return "; ".join(parts)


def _build_budget_info(state: dict) -> dict:
    """构建当前小问的预算信息。

    优先使用 state.budget_manager（run_graph 注入的全实例）；缺失时回退到
    默认预算（保证向后兼容，但不会跨小问累计）。
    """
    from ..runtime.budget import BudgetManager, BudgetType

    bm = state.get("budget_manager") or BudgetManager()
    qid = state.get("current_question_id", "")

    return {
        "validation_remaining": bm.remaining(BudgetType.VALIDATION_ITERATION, question_id=qid),
        "time_run_total": bm.get_total_usage().get(BudgetType.TIME, 0),
        "token_run_total": bm.get_total_usage().get(BudgetType.TOKEN, 0),
    }


# ---------------------------------------------------------------------------
# 节点 2.5：configure_question_budget — 子任务预算配置
# ---------------------------------------------------------------------------


def configure_question_budget(state: dict) -> dict:
    """LangGraph 节点：调用 budget_config_callback 收集用户对该问的预算覆盖。

    行为约定：
      - 若 state.budget_config_callback 为 None：跳过，沿用默认/之前的覆盖。
      - 若 callback 返回 dict[BudgetType, int]：调用 bm.set_question_limits(qid, ...)
        将其写入该问的临时覆盖。
      - 若 callback 返回 None 或抛错：跳过，不覆盖（默认配置生效）。

    典型回调：
      - CLI/Web 模式：允许覆盖 SEARCH / VALIDATION_ITERATION / CODE_REPAIR。

    Args:
        state: 项目状态。

    Returns:
        空 dict（覆盖直接写入 bm，无状态字段变更）。
    """
    callback = state.get("budget_config_callback")
    bm = state.get("budget_manager")
    qid = state.get("current_question_id", "")

    if callback is None or bm is None or not qid:
        return {}

    try:
        override = callback(state)
    except Exception as e:  # noqa: BLE001
        print(f"[budget] 用户预算回调异常，跳过覆盖: {e}")
        log_step(
            get_run_logger(),
            "workflow.configure_question_budget",
            "skipped",
            question_id=qid,
            detail=f"回调异常: {e}",
        )
        return {}

    if not override:
        return {}

    try:
        bm.set_question_limits(qid, override)
        print(
            f"[budget] 小问 {qid} 用户覆盖: "
            + ", ".join(f"{bt.value}={lim}" for bt, lim in override.items())
        )
        log_step(
            get_run_logger(),
            "workflow.configure_question_budget",
            "completed",
            question_id=qid,
            detail=f"用户覆盖: { {bt.value: lim for bt, lim in override.items()} }",
        )
    except Exception as e:  # noqa: BLE001
        print(f"[budget] 写入预算覆盖失败: {e}")

    return {}


def create_stub_result(
    question_id: str,
    interpretation: ProblemInterpretation | None = None,
) -> QuestionResult:
    """创建一个 stub QuestionResult（供测试和 Phase 2 骨架使用）。

    Args:
        question_id: 小问 ID。
        interpretation: 可选的问题理解。无则创建默认占位。

    Returns:
        一个 status="validating" 的 QuestionResult。
    """
    if interpretation is None:
        interpretation = ProblemInterpretation(
            question_id=question_id,
            math_task="composite",
            math_task_description="Stub 求解器占位理解",
            result_form="待 Phase 3+ 填充",
        )

    return QuestionResult(
        question_id=question_id,
        status="validating",
        problem_interpretation=interpretation,
        findings={"summary": "Stub 求解结果，待 Phase 3+ 替换"},
        reusable_summary=ReusableSummary(
            question_id=question_id,
            verified_conclusions=["Stub 结论（待替换）"],
            limitations=["当前为 Phase 2 骨架，无实际建模"],
        ),
        limitations=["Phase 2 stub，无实际计算"],
    )
