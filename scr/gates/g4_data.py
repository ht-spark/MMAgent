"""G4 数据门 — L3 出口校验。

对应 architecture.md §4 G4：
  字段齐备率、缺失率阈值、正负向指标配置。
  失败区分"可预处理修复"（回 preprocess）与"本质不足"（回 L2 / 人工）。

预算机制：max_budget = 3。
"""
from __future__ import annotations

from typing import Any

from ..schemas.common import GateResult
from ..schemas.data import DataRequirement, QualityReport


class G4DataGate:
    """L3 数据门。

    校验三项：
      1. 字段齐备率：每条 DataRequirement.field 都在 QualityReport 中存在
      2. 缺失率：每字段 ≤ 阈值（默认 0.5）
      3. 整体质量评分 ≥ 阈值（默认 0.5）

    失败时：
      - 字段齐备率 < 1.0 → action="retry"（回 preprocess 修复）
      - 缺失率超阈值 → action="retry"（回 preprocess）
      - 整体评分过低 → action="escalate"（回 L2 换模型）
      - 预算耗尽 → action="human"
    """

    gate_id = "G4"
    max_budget = 3

    # 阈值（demo 可调）
    MAX_MISSING_RATE = 0.5
    MIN_OVERALL_SCORE = 0.5

    def evaluate(self, state: dict[str, Any]) -> GateResult:
        requirements: list[DataRequirement] = state.get("data_requirements") or []
        quality: QualityReport | None = state.get("quality_report")

        failed_checks: list[str] = []

        if quality is None:
            failed_checks.append("quality_report_missing")
            return GateResult(
                gate_id=self.gate_id,
                passed=False,
                failed_checks=failed_checks,
                action="retry",
                budget_used=1,
                budget_remaining=self.max_budget - 1,
            )

        # 1. 字段齐备率
        required_fields = {r.field for r in requirements}
        present_fields = set(quality.missing_rates.keys())
        if required_fields:
            missing_fields = required_fields - present_fields
            if missing_fields:
                failed_checks.append(
                    f"fields_missing: {sorted(missing_fields)}"
                )

        # 2. 缺失率
        high_missing = [
            f for f, r in quality.missing_rates.items()
            if r > self.MAX_MISSING_RATE
        ]
        if high_missing:
            failed_checks.append(
                f"high_missing_rate (> {self.MAX_MISSING_RATE}): {high_missing}"
            )

        # 3. 整体质量评分
        if quality.overall_score < self.MIN_OVERALL_SCORE:
            failed_checks.append(
                f"overall_score < {self.MIN_OVERALL_SCORE}"
            )

        passed = len(failed_checks) == 0

        budget_used = int(state.get("_g4_budget_used", 0)) + (0 if passed else 1)
        budget_remaining = max(0, self.max_budget - budget_used)

        if passed:
            action = "pass"
        elif quality.overall_score < 0.3 or budget_remaining == 0:
            # 评分极低或预算耗尽 → escalate/human
            action = "human" if budget_remaining == 0 else "escalate"
        else:
            action = "retry"

        return GateResult(
            gate_id=self.gate_id,
            passed=passed,
            failed_checks=failed_checks,
            action=action,
            budget_used=budget_used,
            budget_remaining=budget_remaining,
        )