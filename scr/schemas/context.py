"""项目全局上下文与数据画像 Schema。

对应 architecture.md §3.1 ProjectContext 和 §3.2 DataProfile。
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


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


class ProjectContext(BaseModel):
    """项目全局上下文（architecture.md §3.1）。
    
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
    """表画像（DataProfile.tables 列表项）。"""
    source_file: str
    sheet_name: str = ""  # CSV 为空，Excel 为 sheet 名
    n_rows: int = Field(ge=0)
    n_cols: int = Field(ge=0)
    field_names: list[str] = Field(default_factory=list)
    sample_rows: list[dict] = Field(default_factory=list, max_length=5)


class FieldProfile(BaseModel):
    """字段画像（DataProfile.fields 列表项）。"""
    source_file: str
    sheet_name: str = ""
    field_name: str
    dtype: str  # int/float/str/datetime/bool/category
    unit_hint: str | None = None
    missing_rate: float = Field(ge=0.0, le=1.0)
    unique_count: int = Field(ge=0)
    value_range: str = ""  # "min~max" 或 "top3 values"
    is_time_column: bool = False


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
    """
    files: list[FileRecord] = Field(default_factory=list)
    tables: list[TableProfile] = Field(default_factory=list)
    fields: list[FieldProfile] = Field(default_factory=list)
    relationships: list[TableRelationship] = Field(default_factory=list)
    quality_issues: list[DataProfileIssue] = Field(default_factory=list)
    preliminary_findings: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    
    @property
    def has_time_column(self) -> bool:
        """是否存在时间维度列。"""
        return any(f.is_time_column for f in self.fields)
    
    @property
    def max_sample_size(self) -> int:
        """最大表样本量。"""
        return max((t.n_rows for t in self.tables), default=0)
