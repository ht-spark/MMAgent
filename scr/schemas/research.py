"""定义知识缺口、检索请求和证据条目的数据结构。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# 知识缺口
# ---------------------------------------------------------------------------


KnowledgeGapType = Literal[
    "domain_definition",      # 领域定义
    "mechanism",              # 机理/原理
    "standard",               # 标准/规范
    "data_source",            # 数据来源
    "model_precedent",        # 模型先例
    "parameter_range",        # 参数范围
    "evaluation_metric",      # 评价指标
    "validation_method",      # 验证方法
    "constraint",             # 约束条件
    "implementation",         # 实现细节
]


class KnowledgeGap(BaseModel):
    """知识缺口（对应 L1 gaps 节点输出）。

    Attributes:
        gap_type: 缺口类型。
        description: 缺口描述（任务在哪些方面需要补充知识）。
        priority: 优先级（high/medium/low）。
        related_subproblems: 关联的子问题 id 列表。
    """

    gap_type: KnowledgeGapType
    description: str
    priority: Literal["high", "medium", "low"]
    related_subproblems: list[str] = Field(default_factory=list)


class KnowledgeGapList(BaseModel):
    """知识缺口列表包装。"""

    gaps: list[KnowledgeGap] = Field(min_length=1)


# ---------------------------------------------------------------------------
# 搜索查询
# ---------------------------------------------------------------------------


SourcePreference = Literal[
    "academic_paper",      # 学术报告
    "official_standard",   # 官方标准
    "government_data",     # 政府数据
    "research_report",     # 研究报告
    "industry_report",     # 行业报告
    "any",                 # 不限
]


class SearchRequest(BaseModel):
    """搜索请求（对应 L1 queries 节点输出）。

    Attributes:
        query: 查询文本。
        purpose: 搜索目的（为什么查这个）。
        language: 查询语言。
        source_preference: 偏好来源类型。
        target_gap_type: 针对的缺口类型。
    """

    query: str
    purpose: str
    language: Literal["zh", "en"]
    source_preference: SourcePreference = "any"
    target_gap_type: KnowledgeGapType


class SearchRequestList(BaseModel):
    """搜索请求列表包装。"""

    queries: list[SearchRequest] = Field(min_length=1)


# ---------------------------------------------------------------------------
# 来源与证据
# ---------------------------------------------------------------------------


SourceLevel = Literal["S", "A", "B", "C", "D"]


class SourceRecord(BaseModel):
    """来源记录（评级后的标准化结果）。

    Attributes:
        source_id: 来源唯一标识（用于 EvidenceItem 引用）。
        url: 标准化后的 URL。
        title: 文章/页面标题。
        level: 来源分级（S 政府/标准 / A 同行评审 / B 高校研究机构 /
              C 官方文档 / D 博客论坛）。
        score: 评分（确定性公式计算，LLM 只提供单项输入）。
        year: 发布年份（可空）。
    """

    source_id: str
    url: str
    title: str
    level: SourceLevel
    score: float = Field(ge=0.0, le=1.0)
    year: int | None = None

    @field_validator("score")
    @classmethod
    def _round_score(cls, v: float) -> float:
        return round(v, 4)


class EvidenceItem(BaseModel):
    """证据项（对应 L1 extract_evidence 节点输出）。

    一个证据项支撑一个 claim，必记来源与局限性，区分事实与推断。

    Attributes:
        claim: 证据声明（这个证据支持的具体陈述）。
        source_id: 引用的来源 ID（对应 SourceRecord.source_id）。
        source_url: 来源 URL（冗余，便于检索）。
        fact_or_inference: 事实还是推断。
        limitations: 局限性描述。
        confidence: 置信度（0–1）。
    """

    claim: str
    source_id: str
    source_url: str | None = None
    fact_or_inference: Literal["fact", "inference"]
    limitations: str = ""
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("confidence")
    @classmethod
    def _round_confidence(cls, v: float) -> float:
        return round(v, 4)


class EvidenceItemList(BaseModel):
    """证据项列表包装。"""

    items: list[EvidenceItem] = Field(min_length=1)
