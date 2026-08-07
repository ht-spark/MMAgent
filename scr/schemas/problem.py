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
    """数值型字段的统计摘要。

    覆盖分布特征（分布特征·单变量）：
      - 集中趋势：mean / median
      - 离散程度：std / iqr（四分位距）
      - 形态：skewness（偏态）/ kurtosis（峰态）
      - 质量：outlier_count / outlier_rate（IQR 法离群点）
    """

    min: float
    max: float
    mean: float
    std: float = Field(ge=0.0)
    median: float
    q1: float | None = None
    q3: float | None = None
    iqr: float | None = None
    skewness: float | None = None
    kurtosis: float | None = None
    outlier_count: int = Field(default=0, ge=0)
    outlier_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("outlier_rate")
    @classmethod
    def _round_outlier_rate(cls, v: float) -> float:
        return round(v, 4)


class CategoryCount(BaseModel):
    """分类字段的频次项。"""

    value: str
    count: int = Field(ge=0)


class CategoricalStats(BaseModel):
    """分类型字段的统计摘要。

    覆盖分布特征与目标变量特殊性：
      - top_values：频次最高的类别（分布集中/离散）
      - max_category_share：最大类别占比（不平衡检测，目标变量特殊性）
    """

    top_values: list[CategoryCount] = Field(default_factory=list, max_length=10)
    max_category_share: float | None = None

    @field_validator("max_category_share")
    @classmethod
    def _round_share(cls, v: float | None) -> float | None:
        if v is None:
            return None
        return round(v, 4)


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
        is_candidate_key: 是否候选主键（唯一且无缺失，粒度/关联键线索）。
        is_spatial: 是否为空间坐标列（经纬度等）。
        numeric_parseable_rate: 字符列中可解析为数值的比例（编码一致性，
            None 表示非字符列；0<rate<1 表示类型混合风险）。
        numeric_stats: 数值型统计（dtype 为 int/float 时填充，含偏度/峰度/离群）。
        categorical_stats: 分类型统计（dtype 为 str/category/bool 时填充，含不平衡度）。
    """

    name: str
    dtype: Literal["int", "float", "str", "datetime", "bool", "category"]
    missing_count: int = Field(ge=0)
    missing_rate: float = Field(ge=0.0, le=1.0)
    unique_count: int = Field(ge=0)
    sample_values: list[str] = Field(default_factory=list, max_length=5)
    unit_hint: str | None = None
    is_time_column: bool = False
    is_candidate_key: bool = False
    is_spatial: bool = False
    numeric_parseable_rate: float | None = None
    numeric_stats: NumericStats | None = None
    categorical_stats: CategoricalStats | None = None

    @field_validator("missing_rate")
    @classmethod
    def _round_rate(cls, v: float) -> float:
        return round(v, 4)

    @field_validator("numeric_parseable_rate")
    @classmethod
    def _round_parseable(cls, v: float | None) -> float | None:
        if v is None:
            return None
        return round(v, 4)


class CorrelatedPair(BaseModel):
    """高相关数值列对（分布特征·多变量 / 共线性风险）。"""

    col_a: str
    col_b: str
    correlation: float = Field(ge=-1.0, le=1.0)

    @field_validator("correlation")
    @classmethod
    def _round_corr(cls, v: float) -> float:
        return round(v, 4)


class DataInventory(BaseModel):
    """附件数据文件的确定性画像。

    产物路径：``artifacts/<run_id>/reports/data_inventory.json``

    覆盖数据画像 6 大维度（file_tools 确定性生成，不依赖 LLM）：
      1. 数据基本面 — file_size / n_rows / n_cols / dtype / candidate_keys / 时空覆盖
      2. 数据质量 — overall_missing_rate / duplicate_rows / 字段离群与类型混合
      3. 分布特征 — 字段 skewness / kurtosis / correlated_pairs（共线性）
      4. 业务语义 — unit_hint / max_category_share（目标不平衡）/ sample_rows
      5. 时空结构 — time_min/max/time_unique_count / spatial_columns
      6. 建模假设预判 — modeling_constraints（模型可用性硬约束）

    Attributes:
        file_name: 文件名（含扩展名）。
        file_path: 文件绝对路径。
        file_type: 文件格式。
        file_size: 文件大小（字节）。
        n_rows: 行数（样本量），用于 L2 硬过滤。
        n_cols: 列数。
        fields: 每个字段的画像列表。
        overall_missing_rate: 全表缺失率 [0, 1]。
        duplicate_rows: 完全重复的行数。
        duplicate_rate: 重复行比例 [0, 1]。
        candidate_keys: 候选主键列（唯一且无缺失）。
        sample_rows: 前 5 行样例（值转为字符串，控制体积）。
        has_time_column: 是否存在时间维度列。
        time_columns: 时间列名列表。
        time_min / time_max: 时间覆盖范围（首列时间字段）。
        time_unique_count: 时间点数量（粒度线索）。
        spatial_columns: 空间坐标列名列表。
        correlated_pairs: |r|≥阈值 的高相关数值列对。
        numeric_columns: 数值列名列表。
        categorical_columns: 分类列名列表。
        modeling_constraints: 建模假设预判（确定性规则生成）。
        sample_size: 样本量（= n_rows），冗余字段便于硬过滤直接引用。
    """

    file_name: str
    file_path: str
    file_type: Literal["csv", "excel", "json", "mat"]
    file_size: int = Field(default=0, ge=0)
    n_rows: int = Field(ge=0)
    n_cols: int = Field(ge=0)
    fields: list[DataField] = Field(default_factory=list)
    overall_missing_rate: float = Field(ge=0.0, le=1.0)
    duplicate_rows: int = Field(default=0, ge=0)
    duplicate_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    candidate_keys: list[str] = Field(default_factory=list)
    sample_rows: list[dict] = Field(default_factory=list, max_length=5)
    has_time_column: bool = False
    time_columns: list[str] = Field(default_factory=list)
    time_min: str | None = None
    time_max: str | None = None
    time_unique_count: int = Field(default=0, ge=0)
    spatial_columns: list[str] = Field(default_factory=list)
    correlated_pairs: list[CorrelatedPair] = Field(default_factory=list)
    numeric_columns: list[str] = Field(default_factory=list)
    categorical_columns: list[str] = Field(default_factory=list)
    modeling_constraints: list[str] = Field(default_factory=list)
    sample_size: int = Field(ge=0)

    @field_validator("overall_missing_rate")
    @classmethod
    def _round_rate(cls, v: float) -> float:
        return round(v, 4)

    @field_validator("duplicate_rate")
    @classmethod
    def _round_duplicate_rate(cls, v: float) -> float:
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
    """任务理解结果（L0 understand 节点输出）。

    对应 architecture.md §4 L0：
      提取研究对象、背景、显式小问、约束、预期输出、关键词。
      禁止推荐模型或开始求解。

    Attributes:
        research_subject: 研究对象（如 "城市经济综合评价"）。
        background: 任务背景描述。
        explicit_questions: 任务明确要求回答的所有小问。
        constraints: 任务中的约束条件。
        expected_outputs: 任务期望的输出形式（如 "排名表"、"预测值"）。
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
