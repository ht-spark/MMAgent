"""判定报告和审查结果是否满足最终交付条件。

最终通过条件：
  - 任务覆盖完整
  - 图文表公式齐备
  - 引用可追溯
  - 所有数值可复现
  - 格式符合竞赛模板
  - 审查问题已关闭或显式接受风险

本门在报告写作和审查之后执行，判定是否可以交付最终产物。

通过条件（本模块实现）：
  1. review_report 存在
  2. 无 critical 审查问题
  3. review_status != "failed"
  4. paper_draft 存在且 full_text 非空

失败处理：
  - 不通过 → 返回 "revise"，回退到报告写作或审查修复
  - 通过 → 返回 "deliver"，进入最终交付
  - 超过修订预算 → 强制交付，记录风险

预算：通过 BudgetManager 的 PAPER_REVISION 类型管理修订上限，
不内置额外常量。
"""
from __future__ import annotations

from ..runtime.budget import BudgetManager, BudgetType
from ..runtime.logging import get_run_logger, log_step
from ..schemas.common import GateResult
from ..schemas.paper import PaperDraft, ReviewReport


def _get_budget_info(state: dict) -> tuple[int, int, bool]:
    """从 BudgetManager 获取 GF 预算信息。

    Returns:
        (budget_used, budget_remaining, can_retry)
    """
    bm: BudgetManager | None = state.get("budget_manager")
    if bm is None:
        return 0, 0, False
    record = bm.get_record(BudgetType.PAPER_REVISION)
    if record is None:
        return 0, 0, False
    return record.used, record.remaining, bm.check(BudgetType.PAPER_REVISION)


def check_gf(state: dict) -> GateResult:
    """执行 GF 交付质量门检查。

    Args:
        state: 项目状态。需要包含 review_report 和 paper_draft。

    Returns:
        GateResult，passed=True 时可交付，否则需要修订。
    """
    failed_checks: list[str] = []
    budget_used, budget_remaining, can_retry = _get_budget_info(state)

    review_report: ReviewReport | None = state.get("review_report")
    paper_draft: PaperDraft | None = state.get("paper_draft")

    # 检查 1: 审查报告是否存在
    if review_report is None:
        failed_checks.append("review_report_missing")
    else:
        # 检查 2: 无 critical 审查问题
        if review_report.critical_count > 0:
            failed_checks.append(
                f"critical_issues_unclosed:{review_report.critical_count}"
            )

        # 检查 3: 审查状态不为 failed
        if review_report.overall_status == "failed":
            failed_checks.append("review_status_failed")

    # 检查 4: 报告草稿是否存在
    if paper_draft is None:
        failed_checks.append("paper_draft_missing")
    else:
        # 检查 5: 报告完整文本非空
        if not paper_draft.full_text.strip():
            failed_checks.append("paper_full_text_empty")

        # 检查 6: 报告有章节
        if not paper_draft.sections:
            failed_checks.append("paper_sections_empty")

        # 检查 7: 报告有摘要
        if not paper_draft.abstract.strip():
            failed_checks.append("paper_abstract_empty")

    passed = len(failed_checks) == 0

    # 修订预算耗尽时强制交付（产出风险说明）
    if not passed and not can_retry:
        print(f"[GF] 修订预算耗尽 (used={budget_used})，强制交付并记录风险")
        print(f"[GF] 未解决问题: {failed_checks}")
        return GateResult(
            gate_id="GF",
            passed=True,
            failed_checks=failed_checks,
            action="pass",
            budget_used=budget_used,
            budget_remaining=0,
        )

    if passed:
        print("[GF] 交付质量门通过，可以交付")
    else:
        print(f"[GF] 交付质量门未通过 (used={budget_used}, remaining={budget_remaining}): {failed_checks}")

    return GateResult(
        gate_id="GF",
        passed=passed,
        failed_checks=failed_checks,
        action="pass" if passed else "retry",
        budget_used=budget_used,
        budget_remaining=budget_remaining,
    )


def route_gf(state: dict) -> str:
    """GF 路由函数（LangGraph 条件边用）。

    Args:
        state: 项目状态。

    Returns:
        "deliver" → 进入最终交付
        "revise"  → 回退到报告写作或审查修复
    """
    result = check_gf(state)
    log_step(
        get_run_logger(),
        "gate.gf",
        "completed",
        detail=(
            f"action={result.action}, "
            f"failed_checks={result.failed_checks or '无'}, "
            f"budget_used={result.budget_used}, remaining={result.budget_remaining}"
        ),
    )
    if result.passed:
        return "deliver"
    return "revise"
