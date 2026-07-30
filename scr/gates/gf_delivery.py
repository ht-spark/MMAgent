"""GF 交付质量门（architecture.md §6.3）。

对应 architecture.md §6.3 交付质量门 GF。

最终通过条件：
  - 题目覆盖完整
  - 图文表公式齐备
  - 引用可追溯
  - 所有数值可复现
  - 格式符合竞赛模板
  - 审查问题已关闭或显式接受风险

本门在论文写作和审查之后执行，判定是否可以交付最终产物。

通过条件（本模块实现）：
  1. review_report 存在
  2. 无 critical 审查问题
  3. review_status != "failed"
  4. paper_draft 存在且 full_text 非空

失败处理：
  - 不通过 → 返回 "revise"，回退到论文写作或审查修复
  - 通过 → 返回 "deliver"，进入最终交付
  - 超过修订预算（2次） → 强制交付，记录风险
"""
from __future__ import annotations

from ..schemas.common import GateResult
from ..schemas.paper import PaperDraft, ReviewReport

# GF 修订预算
GF_MAX_RETRIES = 2


def check_gf(state: dict) -> GateResult:
    """执行 GF 交付质量门检查。

    Args:
        state: 项目状态。需要包含 review_report 和 paper_draft。

    Returns:
        GateResult，passed=True 时可交付，否则需要修订。
    """
    failed_checks: list[str] = []
    retry_count = state.get("_gf_retry_count", 0)

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

    # 检查 4: 论文草稿是否存在
    if paper_draft is None:
        failed_checks.append("paper_draft_missing")
    else:
        # 检查 5: 论文完整文本非空
        if not paper_draft.full_text.strip():
            failed_checks.append("paper_full_text_empty")

        # 检查 6: 论文有章节
        if not paper_draft.sections:
            failed_checks.append("paper_sections_empty")

        # 检查 7: 论文有摘要
        if not paper_draft.abstract.strip():
            failed_checks.append("paper_abstract_empty")

    passed = len(failed_checks) == 0

    # 超过修订预算时强制交付（产出风险说明）
    if not passed and retry_count >= GF_MAX_RETRIES:
        print(f"[GF] 修订预算耗尽 ({retry_count}/{GF_MAX_RETRIES})，强制交付并记录风险")
        print(f"[GF] 未解决问题: {failed_checks}")
        return GateResult(
            gate_id="GF",
            passed=True,
            failed_checks=failed_checks,
            action="pass",
            budget_used=retry_count,
            budget_remaining=0,
        )

    if passed:
        print("[GF] 交付质量门通过，可以交付")
    else:
        print(f"[GF] 交付质量门未通过 (retry={retry_count}/{GF_MAX_RETRIES}): {failed_checks}")

    return GateResult(
        gate_id="GF",
        passed=passed,
        failed_checks=failed_checks,
        action="pass" if passed else "retry",
        budget_used=retry_count,
        budget_remaining=max(0, GF_MAX_RETRIES - retry_count),
    )


def route_gf(state: dict) -> str:
    """GF 路由函数（LangGraph 条件边用）。

    Args:
        state: 项目状态。

    Returns:
        "deliver" → 进入最终交付
        "revise"  → 回退到论文写作或审查修复
    """
    result = check_gf(state)
    if result.passed:
        return "deliver"
    return "revise"
