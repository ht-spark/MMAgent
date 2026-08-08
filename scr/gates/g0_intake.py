"""检查任务输入是否足以开始可靠建模。

通过条件：
  - 任务小问已完整提取
  - 附件均已读取或明确标记为不可读
  - 每问有目标与预期输出
  - 依赖关系无环
  - 关键数据缺口已记录

失败处理：
  - 只重跑任务解析或数据读取
  - 若文件损坏、题干缺页或关键语义无法消除，则进入 need_clarification
  - 不应伪造假设继续求解

预算：通过 BudgetManager 的 INTAKE_RETRY 类型管理重试上限，
不内置额外常量。
"""
from __future__ import annotations

from ..runtime.budget import BudgetManager, BudgetType
from ..runtime.logging import get_run_logger, log_step
from ..schemas.common import GateResult
from ..schemas.context import DataProfile, ProjectContext


# 硬失败项：即使重试耗尽也不能降级通过（必须人工介入）
G0_HARD_FAILURES = {
    "project_context_missing",
    "questions_empty",
    "dependency_cycle_detected",
    "problem_text_empty",
}


def _get_budget_info(state: dict) -> tuple[int, int, bool]:
    """从 BudgetManager 获取 G0 预算信息。

    Returns:
        (budget_used, budget_remaining, can_retry)
    """
    bm: BudgetManager | None = state.get("budget_manager")
    if bm is None:
        return 0, 0, False
    record = bm.get_record(BudgetType.INTAKE_RETRY)
    if record is None:
        return 0, 0, False
    return record.used, record.remaining, bm.check(BudgetType.INTAKE_RETRY)


def check_g0(state: dict) -> GateResult:
    """执行 G0 质量门检查。

    Args:
        state: 项目状态。需要包含 project_context 和 data_profile。

    Returns:
        GateResult，passed=True 时可进入逐问求解，否则需要重试或人工介入。
    """
    failed_checks: list[str] = []

    project_context: ProjectContext | None = state.get("project_context")
    data_profile: DataProfile | None = state.get("data_profile")

    # 检查 1: ProjectContext 是否存在且有小问
    if project_context is None:
        failed_checks.append("project_context_missing")
    elif not project_context.questions:
        failed_checks.append("questions_empty")

    # 检查 2: 每问是否有目标和预期输出
    if project_context and project_context.questions:
        for q in project_context.questions:
            if not q.objective:
                failed_checks.append(f"{q.question_id}_objective_empty")
            if not q.expected_output:
                failed_checks.append(f"{q.question_id}_expected_output_empty")

    # 检查 3: 依赖关系无环
    if project_context and project_context.question_dependencies:
        if _has_cycle(project_context.question_dependencies):
            failed_checks.append("dependency_cycle_detected")

    # 检查 4: 附件均已读取或明确标记为不可读
    if data_profile and data_profile.files:
        for f in data_profile.files:
            if f.read_status not in ("success", "failed", "skipped"):
                failed_checks.append(f"file_{f.file_name}_unknown_status")
            # 读取失败的文件需要记录
            if f.read_status == "failed" and not f.error_message:
                failed_checks.append(f"file_{f.file_name}_error_missing")

    # 检查 5: 任务文本非空
    if project_context and not project_context.problem_text.strip():
        failed_checks.append("problem_text_empty")

    # 从 BudgetManager 获取预算信息
    budget_used, budget_remaining, can_retry = _get_budget_info(state)

    if not failed_checks:
        return GateResult(
            gate_id="G0",
            passed=True,
            failed_checks=[],
            action="pass",
            budget_used=budget_used,
            budget_remaining=budget_remaining,
        )

    # 检查是否只有软失败（可降级通过）
    has_hard_failure = any(c in G0_HARD_FAILURES for c in failed_checks)

    # 有失败项，判断是否还可以重试
    if can_retry:
        return GateResult(
            gate_id="G0",
            passed=False,
            failed_checks=failed_checks,
            action="retry",
            budget_used=budget_used,
            budget_remaining=budget_remaining,
        )

    # 重试耗尽
    if has_hard_failure:
        # 硬失败：必须人工介入
        return GateResult(
            gate_id="G0",
            passed=False,
            failed_checks=failed_checks,
            action="human",
            budget_used=budget_used,
            budget_remaining=0,
        )

    # 只有软失败（如 expected_output_empty）：降级通过，记录风险
    print(f"[G0] 预算耗尽，软失败降级通过: {failed_checks}")
    return GateResult(
        gate_id="G0",
        passed=True,
        failed_checks=failed_checks,
        action="pass",
        budget_used=budget_used,
        budget_remaining=0,
    )


def route_g0(state: dict) -> str:
    """G0 路由函数（LangGraph 条件边用）。

    Returns:
        "pass" → 进入逐问求解
        "retry" → 重跑输入摄入和上下文建立
        "human" → 人工介入
    """
    result = check_g0(state)
    log_step(
        get_run_logger(),
        "gate.g0",
        "completed",
        detail=(
            f"action={result.action}, "
            f"failed_checks={result.failed_checks or '无'}"
        ),
    )
    return result.action


def _has_cycle(dependencies: dict[str, list[str]]) -> bool:
    """检查依赖图是否有环（DFS）。

    Args:
        dependencies: {question_id: [dep_id, ...]}

    Returns:
        True 如果存在环。
    """
    # 三色标记法：0=未访问, 1=正在访问, 2=已完成
    color: dict[str, int] = {node: 0 for node in dependencies}

    def dfs(node: str) -> bool:
        if color.get(node, 0) == 1:
            return True  # 发现环
        if color.get(node, 0) == 2:
            return False  # 已完成，无环

        color[node] = 1  # 标记为正在访问
        for dep in dependencies.get(node, []):
            if dep in color:  # 只检查图中的节点
                if dfs(dep):
                    return True
        color[node] = 2  # 标记为已完成
        return False

    for node in dependencies:
        if color[node] == 0:
            if dfs(node):
                return True

    return False
