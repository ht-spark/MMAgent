"""Gate 门控评估器（程序化，可独立单测）。

对应 architecture.md §5 和 plan.md §1：
  - 集中式路由表
  - 作用域回退规则
  - 预算判定
"""
from __future__ import annotations

from .base import Gate
from .g1_understanding import G1UnderstandingGate

__all__ = ["Gate", "G1UnderstandingGate"]