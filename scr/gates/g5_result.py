"""G5 结果门 — L4 出口校验。

对应 architecture.md §4 G5：
  数据问题 → L3（仅该子问题，其他缓存保留）
  模型不适配 → L2（仅该子问题）
  代码/收敛问题 → 局部修复环
  通过 → fan-in barrier

预算机制：max_budget = 3（局部修复环），超限 escalate。
"""
from __future__ import annotations

from typing import Any

from ..schemas.common import GateResult


class G5ResultGate:
    """L4 结果门。

    校验：
      1. execution_result.success == True
      2. 关键数值（numeric_outputs）非空
      3. 失败原因可分类（data / model / code）

    路由策略：
      - success 且有数值 → pass
      - 失败原因 = code → retry（局部修复）
      - 失败原因 = data → escalate (L3)
      - 失败原因 = model → escalate (L2)
      - 预算耗尽 → human
    """

    gate_id = "G5"
    max_budget = 3

    def evaluate(self, state: dict[str, Any]) -> GateResult:
        execution: dict[str, Any] | None = state.get("execution_result")

        if execution is None:
            return GateResult(
                gate_id=self.gate_id,
                passed=False,
                failed_checks=["execution_result_missing"],
                action="retry",
                budget_used=1,
                budget_remaining=self.max_budget - 1,
            )

        failed_checks: list[str] = []
        success = bool(execution.get("success", False))
        numeric_outputs = execution.get("numeric_outputs", {})
        failure_reason = execution.get("failure_reason", "")  # "code" | "data" | "model"

        if not success:
            failed_checks.append(f"execution_failed: {failure_reason or 'unknown'}")

        if not numeric_outputs:
            failed_checks.append("numeric_outputs_empty")

        passed = len(failed_checks) == 0

        budget_used = int(state.get("_g5_budget_used", 0)) + (0 if passed else 1)
        budget_remaining = max(0, self.max_budget - budget_used)

        if passed:
            action = "pass"
        elif budget_remaining == 0:
            action = "human"
        elif failure_reason == "code":
            action = "retry"  # 局部修复
        elif failure_reason == "data":
            action = "escalate"  # 回 L3
        elif failure_reason == "model":
            action = "escalate"  # 回 L2
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