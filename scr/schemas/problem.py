"""数据画像相关的 Pydantic Schema。

对应 architecture.md §3.1 中的 data_inventory 和 plan.md Phase 1 中的
DataInventory / DataField。

这些 Schema 是 L2 硬过滤的关键输入：
  - 无时间列 → 淘汰 ARIMA
  - 样本量 < 30 → 淘汰机器学习类候选
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class NumericStats(BaseModel):
    """数值型字段的统计摘要。"""

    min: float
    max: float
    mean: float
    std: float = Field(ge=0.0)
    median: float


class CategoryCount(BaseModel):
    """分类字段的频次项。"""

    value: str
    count: int = Field(ge=0)


class CategoricalStats(BaseModel):
    """分类型字段的统计摘要。"""

    top_values: list[CategoryCount] = Field(default_factory=list, max_length=10)


class DataField(BaseModel):
    """单个数据字段的确定性画像。

    Attributes:
        name: 字段名。
        dtype: 推断的数据类型。
        missing_count: 缺失值数量。
        missing_rate: 缺失率 [0, 1]。
        unique_count: 唯一值数量。
        sample_values: 前 5 个非缺失样例值（字符串形式）。
        unit_hint: 从字段名推断的单位线索（如 "重量"、"百分比"），无则 None。
        is_time_column: 是否为时间维度列。
        numeric_stats: 数值型统计（dtype 为 int/float 时填充）。
        categorical_stats: 分类型统计（dtype 为 str/category/bool 时填充）。
    """

    name: str
    dtype: Literal["int", "float", "str", "datetime", "bool", "category"]
    missing_count: int = Field(ge=0)
    missing_rate: float = Field(ge=0.0, le=1.0)
    unique_count: int = Field(ge=0)
    sample_values: list[str] = Field(default_factory=list, max_length=5)
    unit_hint: str | None = None
    is_time_column: bool = False
    numeric_stats: NumericStats | None = None
    categorical_stats: CategoricalStats | None = None

    @field_validator("missing_rate")
    @classmethod
    def _round_rate(cls, v: float) -> float:
        return round(v, 4)


class DataInventory(BaseModel):
    """附件数据文件的确定性画像。

    产物路径：``artifacts/<run_id>/reports/data_inventory.json``

    Attributes:
        file_name: 文件名（含扩展名）。
        file_path: 文件绝对路径。
        file_type: 文件格式。
        n_rows: 行数（样本量），用于 L2 硬过滤。
        n_cols: 列数。
        fields: 每个字段的画像列表。
        overall_missing_rate: 全表缺失率 [0, 1]。
        has_time_column: 是否存在时间维度列。
        time_columns: 时间列名列表。
        numeric_columns: 数值列名列表。
        categorical_columns: 分类列名列表。
        sample_size: 样本量（= n_rows），冗余字段便于硬过滤直接引用。
    """

    file_name: str
    file_path: str
    file_type: Literal["csv", "excel", "json"]
    n_rows: int = Field(ge=0)
    n_cols: int = Field(ge=0)
    fields: list[DataField] = Field(default_factory=list)
    overall_missing_rate: float = Field(ge=0.0, le=1.0)
    has_time_column: bool = False
    time_columns: list[str] = Field(default_factory=list)
    numeric_columns: list[str] = Field(default_factory=list)
    categorical_columns: list[str] = Field(default_factory=list)
    sample_size: int = Field(ge=0)

    @field_validator("overall_missing_rate")
    @classmethod
    def _round_rate(cls, v: float) -> float:
        return round(v, 4)

    @field_validator("sample_size")
    @classmethod
    def _sample_size_matches_rows(cls, v: int, info) -> int:
        n_rows = info.data.get("n_rows")
        if n_rows is not None and v != n_rows:
            raise ValueError(f"sample_size ({v}) must equal n_rows ({n_rows})")
        return v


# ---------------------------------------------------------------------------
# L0 understand / decompose / classify
# ---------------------------------------------------------------------------


class ProblemAnalysis(BaseModel):
    """题目理解结果（L0 understand 节点输出）。

    对应 architecture.md §4 L0：
      提取研究对象、背景、显式小问、约束、预期输出、关键词。
      禁止推荐模型或开始求解。

    Attributes:
        research_subject: 研究对象（如 "城市经济综合评价"）。
        background: 题目背景描述。
        explicit_questions: 题目明确要求回答的所有小问。
        constraints: 题目中的约束条件。
        expected_outputs: 题目期望的输出形式（如 "排名表"、"预测值"）。
        keywords: 用于后续 L1 检索的关键术语。
    """

    research_subject: str
    background: str
    explicit_questions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class SubProblem(BaseModel):
    """子问题（L0 decompose 节点输出）。

    对应 architecture.md §3.1 SubProblem 与 §4 L0 decompose：
      每个子问题含 id、task、input_requirements、expected_outputs、
      dependencies、parallelizable。

    Attributes:
        id: 子问题标识符（如 "q1"、"q2"）。
        task: 具体任务描述。
        input_requirements: 所需输入数据描述。
        expected_outputs: 预期输出描述。
        dependencies: 依赖的其他子问题 id 列表（无依赖为空）。
        parallelizable: 是否可与其他子问题并行求解。
    """

    id: str
    task: str
    input_requirements: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    parallelizable: bool = True

    @staticmethod
    def _normalize_to_list(value: object) -> list[str]:
        """将字符串自动包装为列表，兼容 LLM 返回字符串而非数组的情况。"""
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [value]
        return []

    @field_validator("expected_outputs", mode="before")
    @classmethod
    def _wrap_expected_outputs(cls, v: object) -> list[str]:
        return cls._normalize_to_list(v)

    @field_validator("input_requirements", mode="before")
    @classmethod
    def _wrap_input_requirements(cls, v: object) -> list[str]:
        return cls._normalize_to_list(v)

    @field_validator("dependencies", mode="before")
    @classmethod
    def _wrap_dependencies(cls, v: object) -> list[str]:
        return cls._normalize_to_list(v)


class SubProblemList(BaseModel):
    """子问题列表包装，用于 LLM 结构化输出。"""

    subproblems: list[SubProblem] = Field(min_length=1)


class ProblemClassification(BaseModel):
    """题型分类（L0 classify 节点输出）。

    对应 architecture.md §4 L0 classify：
      判定主类型（evaluation / prediction / optimization / classification /
      simulation / mechanism / composite），允许一主多次。

    Attributes:
        primary_type: 主题型。
        secondary_types: 次题型列表（可为空）。
        reasoning: 分类理由。
    """

    primary_type: Literal[
        "evaluation",
        "prediction",
        "optimization",
        "classification",
        "simulation",
        "mechanism",
        "composite",
    ]
    secondary_types: list[str] = Field(default_factory=list)
    reasoning: str
