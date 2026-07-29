"""Gate 门控评估器（程序化，可独立单测）。

对应 architecture.md §5 和 plan.md §1：
  - 集中式路由表
  - 作用域回退规则
  - 预算判定
"""
from __future__ import annotations

from .base import Gate
from .g1_understanding import G1UnderstandingGate
from .g2_coverage import G2CoverageGate
from .g3_decision import G3DecisionGate
from .g4_data import G4DataGate
from .g5_result import G5ResultGate

__all__ = [
    "G1UnderstandingGate",
    "G2CoverageGate",
    "G3DecisionGate",
    "G4DataGate",
    "G5ResultGate",
    "Gate",
]