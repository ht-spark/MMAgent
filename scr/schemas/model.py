"""定义候选模型、评分和模型审查结果的数据结构。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# 候选模型
# ---------------------------------------------------------------------------


class ModelCandidate(BaseModel):
    """候选模型（对应 L2 generate_candidates 节点输出）。

    每个候选含所需数据、假设、输出、验证方法、支持证据 ID、
    优点、局限、实现风险、淘汰条件。

    Attributes:
        id: 候选标识符。
        name: 模型名称（如 "熵权法"）。
        family: 模型家族（如 "客观赋权法"、"线性回归"）。
        required_data: 所需数据字段。
        assumptions: 核心假设。
        output_description: 输出描述。
        validation_method: 验证方法。
        supporting_evidence_ids: 支持证据 ID 列表（引用 EvidenceItem.source_id）。
        pros: 优点列表。
        cons: 局限列表。
        elimination_conditions: 淘汰条件列表。
    """

    id: str
    name: str
    family: str
    required_data: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    output_description: str = ""
    validation_method: str = ""
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    elimination_conditions: list[str] = Field(default_factory=list)


class ModelCandidateList(BaseModel):
    """候选模型列表包装。"""

    candidates: list[ModelCandidate] = Field(min_length=1)


# ---------------------------------------------------------------------------
# 评分（LLM 给单项，代码算总分）
# ---------------------------------------------------------------------------


# 评分权重（与 architecture.md §4 L2 一致）
SCORE_WEIGHTS: dict[str, float] = {
    "problem_fit": 0.25,
    "data_fit": 0.20,
    "assumption_validity": 0.15,
    "validation_feasibility": 0.15,
    "interpretability": 0.10,
    "implementation_feasibility": 0.10,
    "innovation": 0.05,
}


class ModelScore(BaseModel):
    """模型评分（最终结果，含代码计算的 total_score）。

    Attributes:
        candidate_id: 候选模型 ID。
        problem_fit / data_fit / assumption_validity / validation_feasibility /
        interpretability / implementation_feasibility / innovation: 各单项分（0–1）。
        total_score: 总分（由代码按 SCORE_WEIGHTS 加权计算）。
        reasoning: 整体评分理由。
    """

    candidate_id: str
    problem_fit: float = Field(ge=0.0, le=1.0)
    data_fit: float = Field(ge=0.0, le=1.0)
    assumption_validity: float = Field(ge=0.0, le=1.0)
    validation_feasibility: float = Field(ge=0.0, le=1.0)
    interpretability: float = Field(ge=0.0, le=1.0)
    implementation_feasibility: float = Field(ge=0.0, le=1.0)
    innovation: float = Field(ge=0.0, le=1.0)
    total_score: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""

    @field_validator("problem_fit", "data_fit", "assumption_validity",
                     "validation_feasibility", "interpretability",
                     "implementation_feasibility", "innovation", "total_score")
    @classmethod
    def _round(cls, v: float) -> float:
        return round(v, 4)


def compute_total_score(
    problem_fit: float,
    data_fit: float,
    assumption_validity: float,
    validation_feasibility: float,
    interpretability: float,
    implementation_feasibility: float,
    innovation: float,
) -> float:
    """按 SCORE_WEIGHTS 加权计算总分（与 architecture.md §4 L2 一致）。"""
    total = (
        SCORE_WEIGHTS["problem_fit"] * problem_fit
        + SCORE_WEIGHTS["data_fit"] * data_fit
        + SCORE_WEIGHTS["assumption_validity"] * assumption_validity
        + SCORE_WEIGHTS["validation_feasibility"] * validation_feasibility
        + SCORE_WEIGHTS["interpretability"] * interpretability
        + SCORE_WEIGHTS["implementation_feasibility"] * implementation_feasibility
        + SCORE_WEIGHTS["innovation"] * innovation
    )
    return round(total, 4)


# ---------------------------------------------------------------------------
# Critic 报告
# ---------------------------------------------------------------------------


class ModelCriticReport(BaseModel):
    """Critic 审查报告（对应 L2 criticize 节点输出）。

    Attributes:
        overall_judgment: 整体裁决。
        checks: 各检查项的结果（check_name → 备注）。
        suggested_action: 建议动作（如 "approve"、"replace_model"、"more_research"）。
        reasoning: 整体理由。
    """

    overall_judgment: Literal["passed", "insufficient_evidence", "weak_candidates"]
    checks: dict[str, str] = Field(default_factory=dict)
    suggested_action: str = ""
    reasoning: str = ""
