"""报告与审查 Schema。

对应 architecture.md §6.2 报告写作和 §6.3 交付质量门。
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class PaperSection(BaseModel):
    """报告章节。"""
    section_id: str  # 如 "1", "6.1", "abstract"
    title: str
    content: str = ""
    question_id: str | None = None  # 关联的小问（如果有）
    figures: list[str] = Field(default_factory=list)  # 图文件路径
    tables: list[str] = Field(default_factory=list)  # 表文件路径
    formulas: list[str] = Field(default_factory=list)  # 公式列表
    order: int = 0  # 章节排序


class PaperDraft(BaseModel):
    """报告草稿。"""
    title: str = ""
    sections: list[PaperSection] = Field(default_factory=list)
    abstract: str = ""  # 最后生成
    references: list[str] = Field(default_factory=list)  # 引用列表
    full_text: str = ""  # 完整 Markdown 文本
    
    def get_section(self, section_id: str) -> PaperSection | None:
        """按 ID 获取章节。"""
        for s in self.sections:
            if s.section_id == section_id:
                return s
        return None
    
    def get_sections_by_question(self, question_id: str) -> list[PaperSection]:
        """按小问 ID 获取章节。"""
        return [s for s in self.sections if s.question_id == question_id]


class ReviewIssue(BaseModel):
    """审查问题。"""
    issue_id: str
    severity: Literal["critical", "major", "minor"]
    category: Literal[
        "coverage", "consistency", "traceability", "validation", "format", "citation",
    ]
    message: str
    location: str = ""  # 章节ID或小问ID
    suggested_fix: str = ""


class ReviewReport(BaseModel):
    """审查报告。"""
    issues: list[ReviewIssue] = Field(default_factory=list)
    overall_status: Literal["passed", "needs_revision", "failed"] = "needs_revision"
    summary: str = ""
    
    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "critical")
    
    @property
    def major_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "major")
    
    def add_issue(self, severity: str, category: str, message: str,
                  location: str = "", suggested_fix: str = "") -> None:
        """添加审查问题。"""
        issue_id = f"issue_{len(self.issues) + 1}"
        self.issues.append(ReviewIssue(
            issue_id=issue_id, severity=severity, category=category,
            message=message, location=location, suggested_fix=suggested_fix,
        ))
