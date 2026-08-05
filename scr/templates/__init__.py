"""论文模板包。

提供数学建模竞赛论文的统一模板（不分题型），供 PaperWriter 参考：
公共骨架章节 + 按子问题数量动态生成的问题章节。
"""
from .paper_templates import (
    METHOD_LIBRARY,
    UNIFIED_TEMPLATE,
    PaperTemplate,
    SectionSpec,
    build_paper_outline,
    build_problem_section,
    get_all_section_titles,
    get_template,
    get_writing_guide_summary,
    render_outline_prompt,
)

__all__ = [
    "METHOD_LIBRARY",
    "UNIFIED_TEMPLATE",
    "PaperTemplate",
    "SectionSpec",
    "build_paper_outline",
    "build_problem_section",
    "get_all_section_titles",
    "get_template",
    "get_writing_guide_summary",
    "render_outline_prompt",
]
