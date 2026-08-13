"""论文统一模板单元测试。"""
from __future__ import annotations

import pytest

from scr.templates.paper_templates import (
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


# ---------------------------------------------------------------------------
# 统一模板完整性测试
# ---------------------------------------------------------------------------


class TestUnifiedTemplate:
    """验证统一模板的关键字段完整性。"""

    def test_basic_fields(self):
        """统一模板的基本字段应有效。"""
        t = UNIFIED_TEMPLATE
        assert isinstance(t, PaperTemplate)
        assert len(t.name) > 0
        assert len(t.fixed_sections) >= 5
        assert len(t.abstract_guide) > 20
        assert len(t.keyword_suggestions) >= 1
        assert len(t.writing_tips) >= 3

    def test_sections_valid(self):
        """公共骨架章节规格应有效。"""
        for spec in UNIFIED_TEMPLATE.fixed_sections:
            assert isinstance(spec, SectionSpec)
            assert len(spec.section_id) > 0
            assert len(spec.title) > 0
            assert len(spec.writing_guide) > 0
            assert spec.min_words > 0

    def test_has_required_sections(self):
        """公共骨架应包含问题重述和参考文献章节。"""
        titles = [s.title for s in UNIFIED_TEMPLATE.fixed_sections]
        assert any("重述" in t for t in titles)
        assert any("参考文献" in t for t in titles)


# ---------------------------------------------------------------------------
# 大纲构建测试
# ---------------------------------------------------------------------------


class TestBuildOutline:
    """测试按子问题数量动态生成大纲。"""

    @pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6])
    def test_outline_structure(self, n: int):
        """大纲 = 前 4 章公共骨架 + n 个问题章节 + 3 个收尾章节。"""
        outline = build_paper_outline(n)
        assert len(outline) == 4 + n + 3
        # 前 4 章为公共骨架
        assert outline[0].title == "问题重述"
        assert outline[3].title == "符号说明"
        # 问题章节连续编号
        for i in range(1, n + 1):
            spec = outline[3 + i]
            assert spec.section_id == str(4 + i)
            assert "问题" in spec.title
            assert "建模与求解" in spec.title
        # 收尾章节
        assert outline[-3].title == "模型评价与推广"
        assert outline[-2].title == "参考文献"
        assert outline[-1].title == "附录"

    def test_invalid_num_problems(self):
        """子问题数量小于 1 应抛异常。"""
        with pytest.raises(ValueError):
            build_paper_outline(0)

    def test_problem_section_invalid_index(self):
        """问题序号小于 1 应抛异常。"""
        with pytest.raises(ValueError):
            build_problem_section(0)

    def test_problem_section_chinese_titles(self):
        """问题章节标题应使用中文数字。"""
        assert build_problem_section(1).title == "问题一的建模与求解"
        assert build_problem_section(2).title == "问题二的建模与求解"

    def test_problem_section_custom_number(self):
        """可指定自定义章节编号。"""
        spec = build_problem_section(1, section_number=9)
        assert spec.section_id == "9"


# ---------------------------------------------------------------------------
# 兼容接口测试
# ---------------------------------------------------------------------------


class TestCompatFunctions:
    """测试兼容旧接口的函数。"""

    def test_get_template_ignores_type(self):
        """get_template 无论传什么都返回统一模板。"""
        assert get_template() is UNIFIED_TEMPLATE
        assert get_template("A") is UNIFIED_TEMPLATE
        assert get_template("c") is UNIFIED_TEMPLATE
        assert get_template("X") is UNIFIED_TEMPLATE
        assert get_template("") is UNIFIED_TEMPLATE

    def test_get_all_section_titles(self):
        """应返回公共骨架章节标题列表。"""
        titles = get_all_section_titles()
        assert len(titles) >= 5
        assert all(isinstance(t, str) and len(t) > 0 for t in titles)
        # 旧调用方式（带题型参数）也应可用
        assert get_all_section_titles("A") == titles

    def test_get_writing_guide_summary(self):
        """应返回非空的写作引导文本。"""
        summary = get_writing_guide_summary()
        assert len(summary) > 100
        assert get_writing_guide_summary("A") == summary


# ---------------------------------------------------------------------------
# LLM 提示词渲染测试
# ---------------------------------------------------------------------------


class TestRenderOutlinePrompt:
    """测试 render_outline_prompt 生成的 LLM 引导提示词。"""

    def test_prompt_contains_key_parts(self):
        """提示词应包含章节结构、摘要要求和写作要点。"""
        prompt = render_outline_prompt(3)
        assert "章节结构与写作要求" in prompt
        assert "摘要写作要求" in prompt
        assert "可选方法库" not in prompt
        assert "全局写作要点" in prompt
        assert "问题一的建模与求解" in prompt
        assert "问题三的建模与求解" in prompt
        assert "问题四" not in prompt  # 只有 3 个问题

    def test_prompt_scales_with_num_problems(self):
        """问题数量变化时提示词应相应伸缩。"""
        p2 = render_outline_prompt(2)
        p5 = render_outline_prompt(5)
        assert len(p5) > len(p2)
        assert "问题五的建模与求解" in p5
        assert "问题三" not in p2
