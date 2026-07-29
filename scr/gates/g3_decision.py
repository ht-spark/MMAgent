"""G3 决策门 — L2 出口校验。

对应 architecture.md §4 G3：
  Critic 裁决 insufficient_evidence → L1
  Critic 裁决 weak_candidates → 重生成
  Critic 裁决 passed → H1 人工确认

预算机制：max_budget = 3。
"""
from __future__ import annotations

from typing import Any

from ..schemas.common import GateResult
from ..schemas.model import ModelCriticReport


class G3DecisionGate:
    """L2 决策门。

    根据 ModelCriticReport.overall_judgment 决定路由：
      - passed → action="pass"（可进入 H1 人工确认）
      - insufficient_evidence → action="escalate"（回 L1）
      - weak_candidates → action="retry"（重新生成候选）
    """

    gate_id = "G3"
    max_budget = 3

    def evaluate(self, state: dict[str, Any]) -> GateResult:
        critic: ModelCriticReport | None = state.get("model_critic_report")

        failed_checks: list[str] = []

        if critic is None:
            failed_checks.append("critic_report_missing")
            judgment = None
        else:
            judgment = critic.overall_judgment

        # 决策路由
        if not failed_checks:
            if judgment == "passed":
                action = "pass"
            elif judgment == "insufficient_evidence":
                action = "escalate"
                failed_checks.append("insufficient_evidence")
            elif judgment == "weak_candidates":
                action = "retry"
                failed_checks.append("weak_candidates")
            else:
                action = "human"
                failed_checks.append("unknown_judgment")

        passed = action == "pass"

        budget_used = int(state.get("_g3_budget_used", 0)) + (0 if passed else 1)
        budget_remaining = max(0, self.max_budget - budget_used)

        # 当 action 是 escalate 时，如果 budget 耗尽仍 escalate（architecture.md §5.2）
        # 当 action 是 retry 时，按预算重试
        if action == "retry" and budget_used >= self.max_budget:
            action = "human"

        return GateResult(
            gate_id=self.gate_id,
            passed=passed,
            failed_checks=failed_checks,
            action=action,
            budget_used=budget_used,
            budget_remaining=budget_remaining,
        )