"""Pydantic 数据契约（无逻辑）。

所有节点先依赖 Schema 再实现。
"""
from __future__ import annotations

from .common import GateResult, NodeIssue, NodeStatus
from .problem import (
    CategoryCount,
    CategoricalStats,
    DataField,
    DataInventory,
    NumericStats,
    ProblemAnalysis,
    ProblemClassification,
    SubProblem,
    SubProblemList,
)
from .research import (
    EvidenceItem,
    EvidenceItemList,
    KnowledgeGap,
    KnowledgeGapList,
    SearchRequest,
    SearchRequestList,
    SourceRecord,
)

__all__ = [
    "CategoryCount",
    "CategoricalStats",
    "DataField",
    "DataInventory",
    "EvidenceItem",
    "EvidenceItemList",
    "GateResult",
    "KnowledgeGap",
    "KnowledgeGapList",
    "NodeIssue",
    "NodeStatus",
    "NumericStats",
    "ProblemAnalysis",
    "ProblemClassification",
    "SearchRequest",
    "SearchRequestList",
    "SourceRecord",
    "SubProblem",
    "SubProblemList",
]
