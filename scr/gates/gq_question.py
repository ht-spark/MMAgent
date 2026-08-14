"""检查单个子问题的结果是否可归档并供后续任务使用。

通过条件（全部满足才能写入 validated）：
  1. 回答了任务要求，且输出形式完整
  2. 主方法、假设、关键参数和计算过程可解释
  3. 数值、图表和表格均有可复现产物
  4. 完成与题型相符的验证
  5. 结论与局限均已记录
  6. 已生成可供后续小问使用的 reusable_summary

失败处理：
  - 数据口径或预处理错误 → 回到数据准备
  - 代码、求解或收敛错误 → 修复当前计算任务
  - 假设或模型不适配 → 回到方法决策
  - 多次失败 → 标记为 blocked，说明原因

预算：通过 BudgetManager 的 VALIDATION_ITERATION 类型管理重试上限，
不内置额外常量。预算耗尽不是"伪造通过"，而是产出风险说明。

"""
from __future__ import annotations

import json

from ..runtime.budget import BudgetManager, BudgetType
from ..runtime.logging import get_run_logger, log_step
from ..schemas.common import GateResult
from ..schemas.question import QuestionResult


def _get_budget_info(state: dict, question_id: str = "") -> tuple[int, int, bool]:
    """从 BudgetManager 获取 GQ 预算信息。

    Returns:
        (budget_used, budget_remaining, can_retry)
    """
    bm: BudgetManager | None = state.get("budget_manager")
    if bm is None:
        return 0, 0, False
    record = bm.get_record(BudgetType.VALIDATION_ITERATION)
    if record is None:
        return 0, 0, False
    qid = question_id or None
    return (
        record.used,
        bm.remaining(BudgetType.VALIDATION_ITERATION, question_id=qid),
        bm.check(BudgetType.VALIDATION_ITERATION, question_id=qid),
    )


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
        b_used, b_rem, _ = _get_budget_info(state, current_qid)
        return GateResult(
            gate_id="GQ",
            passed=False,
            failed_checks=["result_blocked"],
            action="blocked",
            budget_used=b_used,
            budget_remaining=b_rem,
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

    # Phase 5 实质检查：建模与结果依据可追溯。
    # 假设是否需要显式列出由具体题面和验证结果决定，不能把空列表作为通用失败条件。
    if not current_result.decision_record:
        failed_checks.append("decision_record_empty")

    # 检查: 数值、图表和表格有可复现产物
    if not current_result.computation:
        failed_checks.append("computation_empty")
    else:
        comp_status = current_result.computation.get("status", "")
        if comp_status == "error":
            failed_checks.append("computation_error")
        failed_checks.extend(_check_task_deliverables(current_result))

    # 验证节点只记录计算证据与风险；GQ 自己基于题目契约和原始结果决定是否归档。
    if not current_result.validation:
        failed_checks.append("validation_empty")

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

    # 节点显式标记 blocked 时不可重试；其他 GQ 失败均消耗验证迭代预算后重试。
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
        # 无 BudgetManager 时直接阻塞
        force_blocked = True

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
            "_gq_feedback": "GQ 未通过：" + "; ".join(result.failed_checks),
        }

    # 超过重试预算或不可重试 → 标记为 blocked
    if current_result:
        current_result.status = "blocked"
        _, b_rem, _ = _get_budget_info(state, current_qid)
        current_result.error_message = (
            f"GQ 验证失败，验证迭代预算已耗尽 (剩余 {b_rem})。"
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
    """根据失败项和 BudgetManager 预算构建 GateResult。"""
    question_id = state.get("current_question_id", "")
    budget_used, budget_remaining, can_retry = _get_budget_info(state, question_id)

    if not failed_checks:
        return GateResult(
            gate_id="GQ",
            passed=True,
            failed_checks=[],
            action="pass",
            budget_used=budget_used,
            budget_remaining=budget_remaining,
        )

    # 有失败项，判断是否可以重试
    if can_retry:
        return GateResult(
            gate_id="GQ",
            passed=False,
            failed_checks=failed_checks,
            action="retry",
            budget_used=budget_used,
            budget_remaining=budget_remaining,
        )

    # 预算耗尽
    return GateResult(
        gate_id="GQ",
        passed=False,
        failed_checks=failed_checks,
        action="blocked",
        budget_used=budget_used,
        budget_remaining=0,
    )


def _check_task_deliverables(result: QuestionResult) -> list[str]:
    """Check question-specific deliverables without task-type hard coding.

    GQ only checks whether the current result satisfies the question contract
    implied by result_form / required_outputs / formulation. The coarse
    math_task label is not used to require fixed output keys.
    """
    computation = result.computation or {}
    status = computation.get("status", "")
    from ..tools.result_keys import normalize_computation

    computation = normalize_computation(dict(computation))
    results = computation.get("results", {}) or {}
    metrics = computation.get("metrics", {}) or {}
    intermediate = computation.get("intermediate_values", {}) or {}
    failures: list[str] = []

    if not results and not metrics and not intermediate:
        failures.append("computation_outputs_missing")

    if status == "generic_stats" and not _contract_allows_generic_stats(result):
        failures.append("generic_stats_not_sufficient")

    missing_outputs = _missing_contract_outputs(
        result=result,
        results=results,
        metrics=metrics,
        intermediate=intermediate,
    )
    if missing_outputs:
        failures.append(
            "contract_outputs_missing:" + ", ".join(missing_outputs[:3])
        )

    if not _has_model_formulation(result):
        failures.append("model_formulation_missing")

    return failures


def _contract_allows_generic_stats(result: QuestionResult) -> bool:
    """Return True only when the question explicitly asks for statistics."""
    interp = result.problem_interpretation
    text = " ".join([
        interp.result_form if interp else "",
        interp.math_task_description if interp else "",
        result.findings.get("summary", "") if result.findings else "",
    ]).lower()
    return any(
        kw in text
        for kw in ("描述统计", "统计摘要", "数据概览", "数据画像", "exploratory", "descriptive")
    )


def _collect_contract_outputs(result: QuestionResult) -> list[str]:
    """Collect required outputs from the available question contract fields."""
    outputs: list[str] = []
    interp = result.problem_interpretation
    if interp and interp.result_form:
        outputs.append(interp.result_form)

    formulation = result.formulation or {}
    for key in ("required_outputs", "outputs", "deliverables"):
        value = formulation.get(key)
        if isinstance(value, list):
            outputs.extend(str(v) for v in value if str(v).strip())
        elif value:
            outputs.append(str(value))

    decision = result.decision_record or {}
    for key in ("required_outputs", "outputs", "deliverables"):
        value = decision.get(key)
        if isinstance(value, list):
            outputs.extend(str(v) for v in value if str(v).strip())
        elif value:
            outputs.append(str(value))

    selected = decision.get("selected_details", {})
    if isinstance(selected, dict):
        value = selected.get("required_outputs")
        if isinstance(value, list):
            outputs.extend(str(v) for v in value if str(v).strip())

    seen: set[str] = set()
    unique: list[str] = []
    for item in outputs:
        item = item.strip()
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _missing_contract_outputs(
    result: QuestionResult,
    results: dict,
    metrics: dict,
    intermediate: dict,
) -> list[str]:
    """Return contract outputs not evidenced by computation/findings/formulation."""
    required = _collect_contract_outputs(result)
    if not required:
        return []

    output_keys = {
        str(k).lower()
        for container in (results, metrics, intermediate)
        for k in container.keys()
    }
    evidence_text = _json_text({
        "results": results,
        "metrics": metrics,
        "intermediate": intermediate,
        "findings": result.findings,
        "formulation": result.formulation,
        "tables": result.tables,
        "figures": result.figures,
    })

    missing = [
        item for item in required
        if not _contract_item_satisfied(item, output_keys, evidence_text)
    ]
    return missing


def _contract_item_satisfied(
    item: str,
    output_keys: set[str],
    evidence_text: str,
) -> bool:
    """Heuristic semantic match for contract item evidence."""
    text = item.lower()
    if text in evidence_text:
        return True
    compact = text.replace(" ", "_")
    if compact in output_keys:
        return True

    groups = [
        (
            ("solution", "decision", "方案", "策略", "安排", "分配", "取值", "计划"),
            ("solution", "optimal_solution", "decision_solution", "assignment", "allocation", "schedule", "plan", "strategy"),
        ),
        (
            ("objective", "profit", "cost", "revenue", "收益", "利润", "成本", "目标", "效益"),
            ("objective", "optimal_objective", "objective_value", "profit", "cost", "revenue", "benefit"),
        ),
        (
            ("constraint", "feasible", "约束", "可行", "满足", "校验", "验证"),
            ("constraint_check", "constraint_satisfaction", "feasibility", "validation", "checks"),
        ),
        (
            ("prediction", "forecast", "预测"),
            ("predictions", "forecast", "fitted_values"),
        ),
        (
            ("ranking", "score", "评价", "排序", "得分"),
            ("ranking", "scores", "weights", "relative_closeness"),
        ),
        (
            ("simulation", "scenario", "仿真", "模拟", "情景", "场景"),
            ("simulation", "scenario_solutions", "scenario_objectives", "n_scenarios"),
        ),
    ]
    for triggers, aliases in groups:
        if any(token in text for token in triggers):
            return any(alias in output_keys or alias in evidence_text for alias in aliases)
    return any(part and part in evidence_text for part in text.replace("/", " ").split())


def _has_model_formulation(result: QuestionResult) -> bool:
    """Check that some problem-specific model description exists."""
    formulation = result.formulation or {}
    if not formulation:
        return False
    ir = formulation.get("ir", {})
    fields = [
        formulation.get("description", ""),
        formulation.get("model_summary", ""),
        formulation.get("objective", ""),
        formulation.get("objective_function", ""),
        formulation.get("decision_variables", []),
        formulation.get("constraints", []),
        ir.get("variables", []) if isinstance(ir, dict) else [],
        ir.get("objective", "") if isinstance(ir, dict) else "",
        ir.get("constraints", []) if isinstance(ir, dict) else [],
    ]
    return any(bool(v) for v in fields)


def _json_text(value: object) -> str:
    """Serialize evidence to lowercase text for lightweight matching."""
    try:
        return json.dumps(value, ensure_ascii=False, default=str).lower()
    except TypeError:
        return str(value).lower()
