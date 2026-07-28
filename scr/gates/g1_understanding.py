"""G1 理解门 — L0 出口校验。

对应 architecture.md §4 G1：
  所有显式小问已提取；
  子问题依赖无环（DAG 校验）；
  每个子问题有主类型。

  任一失败 → 重跑该节点（≤2 次）→ 人工。

对应 plan.md Phase 3.4：gates/g1_understanding.py。
"""
from __future__ import annotations

from typing import Any

from ..schemas.common import GateResult
from ..schemas.problem import (
    ProblemAnalysis,
    ProblemClassification,
    SubProblem,
)


def _is_dag(subproblems: list[SubProblem]) -> bool:
    """校验子问题依赖是否构成 DAG（无环）。

    使用 DFS + 三色标记：
      WHITE(0) = 未访问
      GRAY(1)  = 正在访问（递归栈中）
      BLACK(2) = 已访问完毕

    遇到 GRAY 节点说明有环。
    """
    if not subproblems:
        return True

    nodes = {sp.id for sp in subproblems}
    edges: dict[str, list[str]] = {}
    for sp in subproblems:
        # 只保留指向存在节点的依赖
        edges[sp.id] = [d for d in sp.dependencies if d in nodes]

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}

    def dfs(node: str) -> bool:
        if color[node] == GRAY:
            return False  # 发现环
        if color[node] == BLACK:
            return True
        color[node] = GRAY
        for neighbor in edges[node]:
            if not dfs(neighbor):
                return False
        color[node] = BLACK
        return True

    return all(dfs(n) for n in nodes)


class G1UnderstandingGate:
    """L0 理解门。

    校验三项：
      1. 小问完整：ProblemAnalysis.explicit_questions 非空且至少 1 个
      2. 依赖无环：SubProblem.dependencies 构成 DAG
      3. 主类型齐备：ProblemClassification.primary_type 已设定

    budget 用尽 → action="human"；否则 → action="retry"。
    """

    gate_id = "G1"
    max_budget = 2

    def evaluate(self, state: dict[str, Any]) -> GateResult:
        analysis: ProblemAnalysis | None = state.get("problem_analysis")
        subproblems: list[SubProblem] = state.get("subproblems") or []
        classification: ProblemClassification | None = state.get(
            "problem_classification"
        )

        failed_checks: list[str] = []

        # 1. 小问完整
        if analysis is None:
            failed_checks.append("problem_analysis_missing")
        elif not analysis.explicit_questions:
            failed_checks.append("explicit_questions_empty")

        # 2. 依赖无环
        if not subproblems:
            failed_checks.append("subproblems_empty")
        elif not _is_dag(subproblems):
            failed_checks.append("subproblem_dependencies_have_cycle")

        # 3. 主类型齐备
        if classification is None:
            failed_checks.append("problem_classification_missing")
        elif not classification.primary_type:
            failed_checks.append("primary_type_missing")

        passed = len(failed_checks) == 0

        # 预算读取：state 中可携带 _g1_budget_used
        budget_used = int(state.get("_g1_budget_used", 0)) + (0 if passed else 1)
        budget_remaining = max(0, self.max_budget - budget_used)

        if passed:
            action = "pass"
        elif budget_used <= self.max_budget:
            action = "retry"
        else:
            action = "human"

        return GateResult(
            gate_id=self.gate_id,
            passed=passed,
            failed_checks=failed_checks,
            action=action,
            budget_used=budget_used,
            budget_remaining=budget_remaining,
        )