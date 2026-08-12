"""请求 / 响应数据契约。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    """每请求可选的 LLM 配置；缺省字段回退到服务端环境变量。"""

    provider: str | None = Field(
        None, description="openai | deepseek | custom | None(自动)"
    )
    api_key: str | None = Field(None, description="API Key（服务端不持久化明文到日志）")
    base_url: str | None = Field(None, description="自定义 API 基地址")
    model: str | None = Field(None, description="模型名")


class RunSummary(BaseModel):
    """运行摘要（用于列表与详情）。"""

    run_id: str
    status: str
    created_at: str
    updated_at: str
    workflow_status: str | None = None
    current_question_id: str | None = None
    results_count: int | None = None
    paper_title: str | None = None
    review_status: str | None = None
    error: str | None = None
    problem_preview: str | None = None
    task_name: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "RunSummary":
        return cls(
            run_id=row["run_id"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            workflow_status=row.get("workflow_status"),
            current_question_id=row.get("current_question_id"),
            results_count=row.get("results_count"),
            paper_title=row.get("paper_title"),
            review_status=row.get("review_status"),
            error=row.get("error"),
            problem_preview=row.get("problem_preview"),
            task_name=row.get("task_name"),
        )


class RunDetail(RunSummary):
    """运行详情：在摘要基础上附加最新进度事件与产物清单。"""

    progress: list[dict] | None = None
    artifacts: list[str] | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "RunDetail":
        summary = RunSummary.from_row(row)
        return cls(
            **summary.model_dump(),
            progress=row.get("progress") or [],
            artifacts=row.get("artifacts") or [],
        )


class CreateRunResponse(BaseModel):
    """提交任务后的返回。"""

    run_id: str
    status: str
    output_dir: str


class BudgetConfirmBody(BaseModel):
    """用户在弹窗中确认预算的请求体（初始任务级或每问级）。"""

    question_id: str | None = Field(None, description="对应的小问 id（初始预算为空）")
    use_defaults: bool = Field(False, description="True=沿用默认预算，不覆盖")
    limits: dict[str, int] | None = Field(
        None,
        description='预算覆盖，键为当前阶段允许的预算类型，值为正整数上限',
    )
