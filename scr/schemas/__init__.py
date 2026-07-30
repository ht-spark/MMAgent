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
from .context import (
    DataProfile,
    DataProfileIssue,
    FieldProfile,
    FileRecord,
    ProjectContext,
    QuestionInfo,
    TableProfile,
    TableRelationship,
)
from .question import (
    CurrentQuestionContext,
    ProblemInterpretation,
    QuestionResult,
    ReusableSummary,
)
from .evidence import (
    ArtifactRecord,
    ArtifactRegistry,
    DecisionLog,
    DecisionLogEntry,
    EvidenceCatalog,
    RunLedger,
    RunLedgerEntry,
)
from .paper import (
    PaperDraft,
    PaperSection,
    ReviewIssue,
    ReviewReport,
)

__all__ = [
    "ArtifactRecord",
    "ArtifactRegistry",
    "CategoryCount",
    "CategoricalStats",
    "CurrentQuestionContext",
    "DataField",
    "DataInventory",
    "DataProfile",
    "DataProfileIssue",
    "DataRequirement",
    "DataRequirementList",
    "DecisionLog",
    "DecisionLogEntry",
    "EvidenceCatalog",
    "EvidenceItem",
    "EvidenceItemList",
    "ExecutionResult",
    "FieldProfile",
    "FileRecord",
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
    "PaperDraft",
    "PaperSection",
    "PreprocessingReport",
    "PreprocessingStep",
    "ProblemAnalysis",
    "ProblemClassification",
    "ProblemInterpretation",
    "ProjectContext",
    "QualityIssue",
    "QualityReport",
    "QuestionInfo",
    "QuestionResult",
    "ResultAnalysis",
    "ReviewIssue",
    "ReviewReport",
    "ReusableSummary",
    "RunLedger",
    "RunLedgerEntry",
    "SCORE_WEIGHTS",
    "SearchRequest",
    "SearchRequestList",
    "SourceRecord",
    "SubProblem",
    "SubProblemExecution",
    "SubProblemList",
    "TableProfile",
    "TableRelationship",
    "compute_total_score",
]
