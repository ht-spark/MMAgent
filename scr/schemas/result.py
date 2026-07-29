"""求解结果 Schema（L4 内部）。

对应 plan.md Phase 1.7。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExecutionResult(BaseModel):
    """执行结果（L4 execute 节点输出）。

    Attributes:
        success: 是否成功。
        numeric_outputs: 关键数值输出（指标名 → 值）。
        output_files: 输出文件路径列表（图表、结果表）。
        error_message: 错误信息（成功时为空）。
        failure_reason: 失败原因分类（code / data / model）。
        runtime_seconds: 运行时长。
    """

    success: bool
    numeric_outputs: dict[str, float] = Field(default_factory=dict)
    output_files: list[str] = Field(default_factory=list)
    error_message: str = ""
    failure_reason: Literal["", "code", "data", "model"] = ""
    runtime_seconds: float = Field(ge=0.0, default=0.0)


class SubProblemExecution(BaseModel):
    """单子问题执行结果（按子问题分域）。"""

    subproblem_id: str
    candidate_id: str
    result: ExecutionResult
    repair_count: int = Field(ge=0)


class ResultAnalysis(BaseModel):
    """结果分析（L4 analyze 节点输出，demo 简化版）。

    Attributes:
        summary: 一句话总结。
        key_findings: 关键发现列表。
    """

    subproblem_id: str
    summary: str
    key_findings: list[str] = Field(default_factory=list)