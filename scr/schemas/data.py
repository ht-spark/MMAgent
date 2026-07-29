"""数据处理 Schema（L3 内部）。

对应 plan.md Phase 1.6。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DataRequirement(BaseModel):
    """字段级数据需求（L3 plan_data 节点输出）。

    Attributes:
        name: 需求项名称（如 "GDP 字段"、"人口字段"）。
        field: 数据字段名。
        type: 期望数据类型。
        unit: 单位。
        source: 数据来源（附件 / 计算 / 外部）。
        missing_strategy: 缺失值处理策略（mean / median / drop / forward_fill）。
        preprocessing_method: 预处理方法描述。
        quality_risk: 质量风险等级（low / medium / high）。
    """

    name: str
    field: str
    type: Literal["int", "float", "str", "datetime", "bool", "category"]
    unit: str = ""
    source: str = "附件"
    missing_strategy: Literal["mean", "median", "drop", "forward_fill", "none"] = "none"
    preprocessing_method: str = ""
    quality_risk: Literal["low", "medium", "high"] = "low"


class DataRequirementList(BaseModel):
    """数据需求列表包装。"""

    requirements: list[DataRequirement] = Field(default_factory=list)


class PreprocessingStep(BaseModel):
    """单步预处理记录。"""

    operation: str  # "fillna", "drop_constant", "astype", "scale", ...
    target_column: str = ""
    parameters: dict = Field(default_factory=dict)


class PreprocessingReport(BaseModel):
    """预处理报告（L3 preprocess 节点输出）。

    Attributes:
        steps: 预处理步骤列表（原始数据不覆盖）。
        output_path: 清洗后数据路径。
        rows_before / rows_after: 处理前后行数。
        columns_after: 处理后列名列表。
    """

    steps: list[PreprocessingStep] = Field(default_factory=list)
    output_path: str = ""
    rows_before: int = Field(ge=0)
    rows_after: int = Field(ge=0)
    columns_after: list[str] = Field(default_factory=list)


class QualityIssue(BaseModel):
    """单条质量问题。"""

    kind: Literal["missing_rate", "constant_column", "outlier", "duplicate", "unit_risk", "high_correlation"]
    severity: Literal["low", "medium", "high"]
    message: str
    target: str = ""


class QualityReport(BaseModel):
    """数据质量报告（L3 quality_report 节点输出）。

    Attributes:
        row_count: 行数。
        column_count: 列数。
        missing_rates: 各字段缺失率（field → rate）。
        duplicate_rows: 重复行数。
        constant_columns: 常量列列表。
        issues: 问题列表。
        overall_score: 综合质量评分 [0, 1]。
    """

    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    missing_rates: dict[str, float] = Field(default_factory=dict)
    duplicate_rows: int = Field(ge=0)
    constant_columns: list[str] = Field(default_factory=list)
    issues: list[QualityIssue] = Field(default_factory=list)
    overall_score: float = Field(default=1.0, ge=0.0, le=1.0)