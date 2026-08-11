"""定义任务上下文、子问题信息和数据画像的数据结构。"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field

from .problem import CorrelatedPair


class QuestionInfo(BaseModel):
    """单个小问信息（ProjectContext.questions 列表项）。
    
    每个 question 至少包含：编号、原题文本、预期输出、题型、输入数据、前置问题和完成状态。
    """
    question_id: str
    original_text: str
    objective: str = ""
    expected_output: str = ""
    question_type: str = ""  # evaluation/prediction/optimization/classification/simulation/mechanism/composite
    required_data: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    status: Literal["pending", "solving", "validated", "blocked"] = "pending"
    is_fallback: bool = False


class ProjectContext(BaseModel):
    """项目全局上下文。
    
    在读题阶段生成，后续只允许补充澄清，不应被单题求解器随意改写。
    """
    run_id: str
    problem_text: str
    competition_requirements: dict[str, str] = Field(default_factory=dict)
    background_summary: str = ""
    objectives: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    terminology: dict[str, str] = Field(default_factory=dict)
    questions: list[QuestionInfo] = Field(default_factory=list)
    question_dependencies: dict[str, list[str]] = Field(default_factory=dict)
    question_data_map: dict[str, list[str]] = Field(default_factory=dict)


class FileRecord(BaseModel):
    """文件记录（DataProfile.files 列表项）。"""
    file_name: str
    file_path: str
    file_type: str  # csv/excel/json/markdown/text/pdf/docx
    file_size: int = Field(ge=0)
    read_status: Literal["success", "failed", "skipped"] = "success"
    error_message: str = ""


class TableProfile(BaseModel):
    """表画像（DataProfile.tables 列表项）。

    覆盖数据画像 6 大维度中的表级信息：
      - 基本面：n_rows / n_cols / field_names / sample_rows（样例）
      - 质量：duplicate_rows / duplicate_rate
      - 分布（多变量）：correlated_pairs（共线性）
      - 粒度：candidate_keys
      - 时空：time_coverage / spatial_columns
    """

    source_file: str
    sheet_name: str = ""  # CSV 为空，Excel 为 sheet 名
    n_rows: int = Field(ge=0)
    n_cols: int = Field(ge=0)
    field_names: list[str] = Field(default_factory=list)
    sample_rows: list[dict] = Field(default_factory=list, max_length=5)
    duplicate_rows: int = Field(default=0, ge=0)
    duplicate_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    candidate_keys: list[str] = Field(default_factory=list)
    correlated_pairs: list[CorrelatedPair] = Field(default_factory=list)
    time_coverage: str = ""  # 如 "2023-01 ~ 2023-05 (5 个时间点)"
    spatial_columns: list[str] = Field(default_factory=list)


class FieldProfile(BaseModel):
    """字段画像（DataProfile.fields 列表项）。

    覆盖数据画像 6 大维度（由 file_tools 确定性统计转换而来）：
      - 基本面：dtype / is_candidate_key / is_spatial
      - 质量：missing_count / missing_rate / outlier_rate / numeric_parseable_rate
      - 分布：skewness / kurtosis / value_range
      - 语义：unit_hint / max_category_share（目标不平衡）
      - 时空：is_time_column
    """

    source_file: str
    sheet_name: str = ""
    field_name: str
    dtype: str  # int/float/str/datetime/bool/category
    unit_hint: str | None = None
    missing_count: int = Field(default=0, ge=0)
    missing_rate: float = Field(ge=0.0, le=1.0)
    unique_count: int = Field(ge=0)
    value_range: str = ""  # "min~max" 或 "top3 values"
    is_time_column: bool = False
    is_candidate_key: bool = False
    is_spatial: bool = False
    skewness: float | None = None
    kurtosis: float | None = None
    outlier_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    max_category_share: float | None = None
    numeric_parseable_rate: float | None = None


class TableRelationship(BaseModel):
    """表间关联候选（DataProfile.relationships 列表项）。"""
    left_table: str
    left_field: str
    right_table: str
    right_field: str
    confidence: float = Field(ge=0.0, le=1.0)


class DataProfileIssue(BaseModel):
    """数据质量问题（DataProfile.quality_issues 列表项）。"""
    source_file: str
    sheet_name: str = ""
    issue_type: str  # missing_rate/constant_column/outlier/duplicate/unit_risk/high_correlation
    severity: Literal["low", "medium", "high"] = "low"
    message: str
    target: str = ""  # 字段名或表名


class DataProfile(BaseModel):
    """数据画像（architecture.md §3.2）。

    数据画像必须由确定性工具生成。Excel 读取需要覆盖每个工作簿、每个 Sheet。
    数据画像的作用是约束方法选择。

    6 大维度覆盖：
      1. 基本面 — files / tables（规模、粒度、时空覆盖）
      2. 质量 — quality_issues（缺失/重复/异常/编码一致性）
      3. 分布 — fields（偏态/峰态）+ tables.correlated_pairs（共线性）
      4. 语义 — fields（单位、不平衡度）
      5. 时空 — fields.is_time_column / tables.time_coverage / spatial_columns
      6. 建模假设预判 — modeling_constraints（模型可用性硬约束）
    """
    files: list[FileRecord] = Field(default_factory=list)
    tables: list[TableProfile] = Field(default_factory=list)
    fields: list[FieldProfile] = Field(default_factory=list)
    relationships: list[TableRelationship] = Field(default_factory=list)
    quality_issues: list[DataProfileIssue] = Field(default_factory=list)
    preliminary_findings: list[str] = Field(default_factory=list)
    modeling_constraints: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    
    @property
    def has_time_column(self) -> bool:
        """是否存在时间维度列。"""
        return any(f.is_time_column for f in self.fields)
    
    @property
    def max_sample_size(self) -> int:
        """最大表样本量。"""
        return max((t.n_rows for t in self.tables), default=0)
