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

from ..runtime.logging import get_run_logger, log_step
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

    # 终态短路：结果已被标记 blocked（如节点异常降级），直接保持 blocked，
    # 不重算其他字段（避免 solve 失败降级后又被 GQ 拉回 retry 浪费求解）
    if current_result.status == "blocked":
        return GateResult(
            gate_id="GQ",
            passed=False,
            failed_checks=["result_blocked"],
            action="blocked",
            budget_used=0,
            budget_remaining=GQ_MAX_RETRIES,
        )

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
        failed_checks.extend(_check_task_deliverables(current_result))

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
        log_step(
            get_run_logger(),
            "gate.gq",
            "passed",
            question_id=current_qid,
            detail="小问验证通过",
        )
        return {
            "current_result": current_result,
            "_gq_action": "pass",
        }

    # 未通过：按预算或常量决定重试 / 阻塞
    budget_manager = state.get("budget_manager")
    force_blocked = False

    if current_result is not None and current_result.status == "blocked":
        # 节点降级已标记 blocked（如 solve_question 异常），不再重试
        force_blocked = True
    elif budget_manager is not None:
        # 验证迭代预算（强制项，按小问计数）：每次未通过尝试消耗 1 次
        from ..runtime.budget import BudgetType

        ok = budget_manager.consume(
            BudgetType.VALIDATION_ITERATION, amount=1, question_id=current_qid
        )
        if ok:
            rem = budget_manager.remaining(
                BudgetType.VALIDATION_ITERATION, question_id=current_qid
            )
            print(f"[GQ] 预算：VALIDATION_ITERATION 消耗 1 次，剩余 {rem}")
        else:
            # 验证迭代预算耗尽 → 产出风险说明并阻塞（而非伪造通过）
            force_blocked = True
            print(f"[GQ] 预算：VALIDATION_ITERATION 已耗尽，强制 blocked")
    else:
        # 无预算：沿用 GQ_MAX_RETRIES 常量（默认回退路径）
        force_blocked = not (result.action == "retry" and retry_count < GQ_MAX_RETRIES)

    if not force_blocked:
        # 可重试
        if current_result:
            current_result.status = "solving"
            current_result.retry_count = retry_count + 1
        print(f"[GQ] 小问 {current_qid} 需要重试 (第 {retry_count + 1} 次): {result.failed_checks}")
        log_step(
            get_run_logger(),
            "gate.gq",
            "retry",
            question_id=current_qid,
            detail=(
                f"第 {retry_count + 1} 次重试: {result.failed_checks}"
            ),
        )
        return {
            "current_result": current_result,
            "_solve_retry_count": retry_count + 1,
            "_gq_action": "retry",
        }

    # 超过重试预算或不可重试 → 标记为 blocked
    if current_result:
        current_result.status = "blocked"
        current_result.error_message = (
            f"GQ 验证失败，已用尽验证迭代预算 ({retry_count}/{GQ_MAX_RETRIES})。"
            f"失败项: {', '.join(result.failed_checks)}"
        )
    print(f"[GQ] 小问 {current_qid} 被阻塞 ✗: {result.failed_checks}")
    log_step(
        get_run_logger(),
        "gate.gq",
        "blocked",
        question_id=current_qid,
        detail=f"小问被阻塞: {result.failed_checks}",
    )
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


def _check_task_deliverables(result: QuestionResult) -> list[str]:
    """Check task-specific minimum deliverables.

    This prevents descriptive statistics from being treated as a solved model.
    """
    interp = result.problem_interpretation
    if interp is None:
        return []

    task = interp.math_task
    computation = result.computation or {}
    status = computation.get("status", "")
    from ..tools.result_keys import normalize_computation

    computation = normalize_computation(dict(computation))
    results = computation.get("results", {}) or {}
    metrics = computation.get("metrics", {}) or {}
    intermediate = computation.get("intermediate_values", {}) or {}
    failures: list[str] = []

    if task in {
        "evaluation",
        "prediction",
        "optimization",
        "stochastic_optimization",
        "simulation",
    } and status == "generic_stats":
        failures.append(f"{task}_generic_stats_not_sufficient")

    if task == "evaluation":
        if not any(k in results for k in ("weights", "scores", "ranking", "relative_closeness")):
            failures.append("evaluation_outputs_missing")
    elif task == "prediction":
        has_predictions = any(k in results for k in ("predictions", "forecast", "fitted_values"))
        has_error_metric = any(k in metrics for k in ("r_squared", "rmse", "mse", "mae", "mape"))
        if not has_predictions or not has_error_metric:
            failures.append("prediction_outputs_missing")
    elif task == "optimization":
        has_solution = any(k in results for k in ("optimal_solution", "best_solution", "decision_solution"))
        has_objective = any(k in results for k in ("optimal_objective", "objective_value")) or "objective_value" in metrics
        if not has_solution or not has_objective:
            failures.append("optimization_solution_missing")
    elif task == "stochastic_optimization":
        has_scenario = (
            any(k in results for k in (
                "simulation",
                "scenario_solutions",
                "scenario_objectives",
                "robust_solution",
                "n_scenarios",
            ))
            or "scenario_objectives" in intermediate
        )
        # 风险指标同时查 results 顶层与 metrics（兼容 LLM 提示词契约的顶层输出）
        has_risk_metric = any(
            k in {**results, **metrics}
            for k in ("expected_objective", "objective_std", "worst_case", "cvar")
        )
        if not has_scenario or not has_risk_metric:
            failures.append("stochastic_outputs_missing")
    elif task == "simulation":
        has_simulation = "simulation" in results or "n_simulations" in metrics
        has_interval = (
            "confidence_interval" in results
            or "confidence_interval_90" in str(results)
            or "confidence_interval" in metrics
        )
        if not has_simulation or not has_interval:
            failures.append("simulation_outputs_missing")

    formulation = result.formulation or {}
    if task in {"optimization", "stochastic_optimization"}:
        ir = formulation.get("ir", {})
        if not ir or not ir.get("variables") or not ir.get("objective"):
            failures.append("formulation_ir_incomplete")

    return failures
