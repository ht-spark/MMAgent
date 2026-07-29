"""七层子图：每文件一子图 + 关联 Gate。

对应 plan.md §2.1 / Phase 2。
"""
from __future__ import annotations

from .l0_understanding import L0UnderstandingSubgraph
from .l1_research import FakeSearchProvider, L1ResearchSubgraph, SearchHit
from .l3_data import L3DataSubgraph
from .l4_solve import L4SolveSubgraph
from .l5_writing import L5WritingSubgraph
from .l6_review import L6ReviewSubgraph

__all__ = [
    "FakeSearchProvider",
    "L0UnderstandingSubgraph",
    "L1ResearchSubgraph",
    "L3DataSubgraph",
    "L4SolveSubgraph",
    "L5WritingSubgraph",
    "L6ReviewSubgraph",
    "SearchHit",
]