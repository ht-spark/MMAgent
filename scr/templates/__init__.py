"""论文模板包。

提供数学建模竞赛 A-F 题的论文模板，供 PaperWriter 参考。
"""
from .paper_templates import (
    PaperTemplate,
    SectionSpec,
    get_template,
    get_template_by_problem_text,
    get_all_section_titles,
    get_writing_guide_summary,
    ALL_TEMPLATES,
)

__all__ = [
    "PaperTemplate",
    "SectionSpec",
    "get_template",
    "get_template_by_problem_text",
    "get_all_section_titles",
    "get_writing_guide_summary",
    "ALL_TEMPLATES",
]
