"""定义跨智能体和质量门共享的基础数据类型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GateResult(BaseModel):
    """Gate 判定结果（对应 architecture.md §5.1）。

    Attributes:
        gate_id: Gate 标识符（如 "G1"、"G2"）。
        passed: 是否通过。
        failed_checks: 失败项列表（如 ["explicit_questions_empty"]）。
        action: 后续动作（pass / retry / escalate / blocked / human）。
        budget_used: 本 Gate 已用预算次数。
        budget_remaining: 剩余预算次数。
    """

    gate_id: str
    passed: bool
    failed_checks: list[str] = Field(default_factory=list)
    action: Literal["pass", "retry", "escalate", "blocked", "human"]
    budget_used: int = Field(ge=0)
    budget_remaining: int = Field(ge=0)


class NodeStatus(BaseModel):
    """节点执行状态。"""

    node_name: str
    status: Literal["pending", "running", "completed", "failed"]
    error: str | None = None


class NodeIssue(BaseModel):
    """节点产生的 Issue（供 Gate 收集）。

    对应 plan.md Phase 1.1。
    """

    category: str
    severity: Literal["critical", "major", "minor"]
    message: str
    location: str | None = None
