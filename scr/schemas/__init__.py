"""Pydantic 数据契约（无逻辑）。

所有节点先依赖 Schema 再实现。
"""
from __future__ import annotations

from .common import GateResult, NodeIssue, NodeStatus
from .data import (
    DataRequirement,
    DataRequirementList,
    PreprocessingReport,
    PreprocessingStep,
    QualityIssue,
    QualityReport,
)
from .model import (
    ModelCandidate,
    ModelCandidateList,
    ModelCriticReport,
    ModelScore,
    SCORE_WEIGHTS,
    compute_total_score,
)
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
from .result import ExecutionResult, ResultAnalysis, SubProblemExecution

__all__ = [
    "CategoryCount",
    "CategoricalStats",
    "DataField",
    "DataInventory",
    "DataRequirement",
    "DataRequirementList",
    "EvidenceItem",
    "EvidenceItemList",
    "ExecutionResult",
    "GateResult",
    "KnowledgeGap",
    "KnowledgeGapList",
    "ModelCandidate",
    "ModelCandidateList",
    "ModelCriticReport",
    "ModelScore",
    "NodeIssue",
    "NodeStatus",
    "NumericStats",
    "PreprocessingReport",
    "PreprocessingStep",
    "ProblemAnalysis",
    "ProblemClassification",
    "QualityIssue",
    "QualityReport",
    "ResultAnalysis",
    "SCORE_WEIGHTS",
    "SearchRequest",
    "SearchRequestList",
    "SourceRecord",
    "SubProblem",
    "SubProblemExecution",
    "SubProblemList",
    "compute_total_score",
]
