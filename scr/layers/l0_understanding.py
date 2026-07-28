"""L0 摄入与理解子图。

对应 architecture.md §2 与 §4 L0：
  ingest → data_inventory → understand → decompose → classify → G1

实现要点：
  - 当前为函数式 orchestrator，可被 LangGraph 子图包装（plan.md Phase 2.4）
  - 节点只返回 State 部分更新（architecture.md §3.2 状态铁律 1）
  - 原始 DataFrame 不进 State，只存 DataInventory 画像（铁律 2）
  - G1 失败时按预算重试 understand/decompose/classify
"""
from __future__ import annotations

from pathlib import Path

from ..agents.problem_analyst import ProblemAnalyst
from ..gates.g1_understanding import G1UnderstandingGate
from ..schemas.common import GateResult
from ..schemas.problem import (
    DataInventory,
    ProblemAnalysis,
    ProblemClassification,
    SubProblem,
)
from ..tools.file_tools import generate_data_inventory


class L0UnderstandingSubgraph:
    """L0 摄入与理解子图。

    串联：
      data_inventory（确定性工具）→
      understand / decompose / classify（LLM Agent）→
      G1 理解门

    Args:
        llm: 可选 LLM 客户端（注入用于测试）。
        max_attempts: 最大重试次数（G1 失败时），默认 3（首次 + 2 次重试）。
    """

    def __init__(self, llm=None, max_attempts: int = 3) -> None:
        self.analyst = ProblemAnalyst(llm=llm)
        self.gate = G1UnderstandingGate()
        self.max_attempts = max(1, max_attempts)

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------

    def run(
        self,
        problem_text: str,
        data_files: list[str | Path] | None = None,
    ) -> dict:
        """执行 L0 完整流程。

        Args:
            problem_text: 题目全文。
            data_files: 可选的附件路径列表。

        Returns:
            包含以下字段的 State 部分更新 dict：
              - data_inventories: list[DataInventory]
              - problem_analysis: ProblemAnalysis | None
              - subproblems: list[SubProblem]
              - problem_classification: ProblemClassification | None
              - gate_result: GateResult | None
              - workflow_status: str ("l0_completed" | "l0_failed")
        """
        # 1. data_inventory（确定性，不依赖 LLM）
        data_inventories = self._ingest_data(data_files or [])

        # 2-4. understand → decompose → classify + G1（带重试）
        problem_analysis: ProblemAnalysis | None = None
        subproblems: list[SubProblem] = []
        problem_classification: ProblemClassification | None = None
        gate_result: GateResult | None = None

        primary_inventory = data_inventories[0] if data_inventories else None

        for attempt in range(1, self.max_attempts + 1):
            try:
                problem_analysis = self.analyst.understand(
                    problem_text, primary_inventory
                )
                subproblems = self.analyst.decompose(problem_analysis)
                problem_classification = self.analyst.classify(
                    problem_analysis, subproblems
                )
            except Exception as e:
                # LLM 调用失败 → 记录，下一轮重试
                problem_analysis = None
                subproblems = []
                problem_classification = None
                continue

            state = {
                "problem_analysis": problem_analysis,
                "subproblems": subproblems,
                "problem_classification": problem_classification,
                "_g1_budget_used": attempt - 1,
            }
            gate_result = self.gate.evaluate(state)

            if gate_result.passed:
                break

        # 决定 workflow_status
        if gate_result is None or not gate_result.passed:
            status = "l0_failed"
        else:
            status = "l0_completed"

        return {
            "data_inventories": data_inventories,
            "problem_analysis": problem_analysis,
            "subproblems": subproblems,
            "problem_classification": problem_classification,
            "gate_result": gate_result,
            "workflow_status": status,
        }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _ingest_data(
        self, data_files: list[str | Path]
    ) -> list[DataInventory]:
        """对每个数据文件生成画像；失败的文件被跳过不抛异常。"""
        inventories: list[DataInventory] = []
        for path in data_files:
            try:
                inv = generate_data_inventory(path)
                inventories.append(inv)
            except (FileNotFoundError, ValueError):
                # 跳过不可读文件，继续处理其他文件
                continue
        return inventories