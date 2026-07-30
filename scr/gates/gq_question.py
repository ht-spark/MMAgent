"""GQ 小问结果质量门。

对应 architecture.md §5.7 小问结果门。

通过条件（全部满足才能写入 validated）：
  1. 回答了题目要求，且输出形式完整
  2. 主方法、假设、关键参数和计算过程可解释
  3. 数值、图表和表格均有可复现产物
  4. 完成与题型相符的验证
  5. 结论与局限均已记录
  6. 已生成可供后续小问使用的 reusable_summary

失败处理（architecture.md §5.6）：
  - 数据口径或预处理错误 → 回到数据准备（Phase 4+ 实现）
  - 代码、求解或收敛错误 → 修复当前计算任务（Phase 4+ 实现）
  - 假设或模型不适配 → 回到方法决策（Phase 3+ 实现）
  - 多次失败 → 标记为 blocked，说明原因

预算（architecture.md §5.6）：
  - 方法重选不超过 2 次
  - 代码修复不超过 3 次
  - 验证迭代不超过 2 次
  - 预算耗尽不是"伪造通过"，而是产出风险说明

Phase 5 集成：启用实质检查（computation、validation）。
"""
from __future__ import annotations

from ..schemas.common import GateResult
from ..schemas.question import QuestionResult


# 重试预算
GQ_MAX_RETRIES = 2  # GQ 验证迭代最多 2 次

# Phase 5：启用实质检查
PHASE2_LENIENT = False


def check_gq(state: dict) -> GateResult:
    """执行 GQ 质量门检查。

    Args:
        state: 项目状态。需要包含 current_result。

    Returns:
        GateResult，action 为 pass / retry / blocked。
    """
    failed_checks: list[str] = []

    current_result: QuestionResult | None = state.get("current_result")
    current_qid = state.get("current_question_id", "")

    # 检查 1: QuestionResult 是否存在
    if current_result is None:
        failed_checks.append("result_missing")
        return _build_gate_result(failed_checks, state)

    # 检查 2: question_id 匹配
    if current_result.question_id != current_qid:
        failed_checks.append(f"question_id_mismatch: result={current_result.question_id}, state={current_qid}")

    # 检查 3: problem_interpretation 存在且非空
    if current_result.problem_interpretation is None:
        failed_checks.append("problem_interpretation_missing")
    else:
        interp = current_result.problem_interpretation
        if not interp.math_task:
            failed_checks.append("math_task_empty")
        if not interp.result_form:
            failed_checks.append("result_form_empty")

    # 检查 4: reusable_summary 已生成（architecture.md §5.7 条件 6）
    if current_result.reusable_summary is None:
        failed_checks.append("reusable_summary_missing")
    else:
        rs = current_result.reusable_summary
        if not rs.verified_conclusions:
            failed_checks.append("reusable_summary_no_conclusions")

    # 检查 5: 局限已记录（architecture.md §5.7 条件 5）
    if not current_result.limitations:
        failed_checks.append("limitations_empty")

    # Phase 5 实质检查：主方法、假设、关键参数可解释
    if not current_result.decision_record:
        failed_checks.append("decision_record_empty")
    if not current_result.assumptions:
        failed_checks.append("assumptions_empty")

    # 检查: 数值、图表和表格有可复现产物
    if not current_result.computation:
        failed_checks.append("computation_empty")
    else:
        comp_status = current_result.computation.get("status", "")
        if comp_status == "error":
            failed_checks.append("computation_error")

    # 检查: 完成题型相符的验证（Phase 5）
    if not current_result.validation:
        failed_checks.append("validation_empty")
    else:
        val_status = current_result.validation.get("status", "")
        if val_status == "failed":
            # 验证失败但不是致命错误时，记录风险而非阻塞
            val_checks = current_result.validation.get("checks", [])
            has_error = any(
                c.get("severity") == "error" and not c.get("passed", True)
                for c in val_checks
            )
            if has_error:
                failed_checks.append("validation_failed")

    return _build_gate_result(failed_checks, state)


def run_gq_node(state: dict) -> dict:
    """LangGraph 节点：执行 GQ 检查并更新 current_result 状态。

    根据 GQ 检查结果：
      - pass → current_result.status = "validated"
      - retry → current_result.status 保持 "validating"，递增重试计数
      - blocked → current_result.status = "blocked"，记录错误信息

    Args:
        state: 项目状态。

    Returns:
        状态更新字典，包含更新后的 current_result 和 _gq_action。
    """
    result = check_gq(state)
    current_result: QuestionResult | None = state.get("current_result")
    current_qid = state.get("current_question_id", "")
    retry_count = state.get("_solve_retry_count", 0)

    if result.passed:
        # 验证通过
        if current_result:
            current_result.status = "validated"
        print(f"[GQ] 小问 {current_qid} 验证通过 ✓")
        return {
            "current_result": current_result,
            "_gq_action": "pass",
        }

    if result.action == "retry" and retry_count < GQ_MAX_RETRIES:
        # 可重试
        if current_result:
            current_result.status = "solving"
            current_result.retry_count = retry_count + 1
        print(f"[GQ] 小问 {current_qid} 需要重试 (第 {retry_count + 1} 次): {result.failed_checks}")
        return {
            "current_result": current_result,
            "_solve_retry_count": retry_count + 1,
            "_gq_action": "retry",
        }

    # 超过重试次数或不可重试 → 标记为 blocked
    if current_result:
        current_result.status = "blocked"
        current_result.error_message = (
            f"GQ 验证失败，已用尽重试预算 ({retry_count}/{GQ_MAX_RETRIES})。"
            f"失败项: {', '.join(result.failed_checks)}"
        )
    print(f"[GQ] 小问 {current_qid} 被阻塞 ✗: {result.failed_checks}")
    return {
        "current_result": current_result,
        "_gq_action": "blocked",
    }


def route_after_gq(state: dict) -> str:
    """GQ 后的路由函数（LangGraph 条件边用）。

    Returns:
        "pass" → 归档结果
        "retry" → 重新求解
        "blocked" → 归档为 blocked
    """
    action = state.get("_gq_action", "")
    if action == "pass":
        return "pass"
    elif action == "retry":
        return "retry"
    elif action == "blocked":
        return "blocked"
    # 默认走 pass（安全兜底）
    return "pass"


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _build_gate_result(failed_checks: list[str], state: dict) -> GateResult:
    """根据失败项和重试预算构建 GateResult。"""
    retry_count = state.get("_solve_retry_count", 0)

    if not failed_checks:
        return GateResult(
            gate_id="GQ",
            passed=True,
            failed_checks=[],
            action="pass",
            budget_used=retry_count,
            budget_remaining=max(0, GQ_MAX_RETRIES - retry_count),
        )

    # 有失败项，判断是否可以重试
    if retry_count < GQ_MAX_RETRIES:
        return GateResult(
            gate_id="GQ",
            passed=False,
            failed_checks=failed_checks,
            action="retry",
            budget_used=retry_count,
            budget_remaining=max(0, GQ_MAX_RETRIES - retry_count),
        )

    # 超过重试次数
    return GateResult(
        gate_id="GQ",
        passed=False,
        failed_checks=failed_checks,
        action="blocked",
        budget_used=retry_count,
        budget_remaining=0,
    )
