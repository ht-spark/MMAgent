"""Gate 协议。

对应 architecture.md §5.1：
  evaluate(state) -> GateResult
  每个 Gate 是程序化校验器，可独立单测，不依赖 LLM。
"""
from __future__ import annotations

from typing import Any, Protocol

from ..schemas.common import GateResult


class Gate(Protocol):
    """Gate 协议：所有 Gate 需实现 evaluate。

    Attributes:
        gate_id: Gate 标识符（如 "G1"、"G2"）。
        max_budget: 最大预算次数（默认 2）。
    """

    gate_id: str
    max_budget: int

    def evaluate(self, state: dict[str, Any]) -> GateResult:
        """根据当前 State 判定 Gate 结果。

        Args:
            state: 当前 workflow 状态（dict，可访问任意已构建产物）。

        Returns:
            GateResult 对象。
        """
        ...