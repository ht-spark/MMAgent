"""论文模板（A-F 题）单元测试。"""
from __future__ import annotations

import pytest

from scr.templates.paper_templates import (
    PaperTemplate,
    SectionSpec,
    TEMPLATE_A,
    TEMPLATE_B,
    TEMPLATE_C,
    TEMPLATE_D,
    TEMPLATE_E,
    TEMPLATE_F,
    ALL_TEMPLATES,
    get_template,
    get_template_by_problem_text,
    get_all_section_titles,
    get_writing_guide_summary,
)


# ---------------------------------------------------------------------------
# 模板完整性测试
# ---------------------------------------------------------------------------


class TestTemplateCompleteness:
    """验证每个模板的关键字段完整性。"""

    @pytest.mark.parametrize(
        "template,key",
        [
            (TEMPLATE_A, "A"),
            (TEMPLATE_B, "B"),
            (TEMPLATE_C, "C"),
            (TEMPLATE_D, "D"),
            (TEMPLATE_E, "E"),
            (TEMPLATE_F, "F"),
        ],
    )
    def test_template_registered(self, template: PaperTemplate, key: str):
        """每个模板都应注册在 ALL_TEMPLATES 中。"""
        assert ALL_TEMPLATES[key] is template

    @pytest.mark.parametrize("template", ALL_TEMPLATES.values())
    def test_basic_fields(self, template: PaperTemplate):
        """每个模板的基本字段都应有效。"""
        assert template.problem_type in "ABCDEF"
        assert len(template.problem_type_name) > 0
        assert len(template.category) > 0
        assert len(template.example_title) > 0
        assert len(template.sections) >= 5
        assert len(template.abstract_guide) > 20
        assert len(template.keyword_suggestions) >= 3
        assert len(template.method_preferences) >= 3
        assert len(template.writing_tips) >= 3

    @pytest.mark.parametrize("template", ALL_TEMPLATES.values())
    def test_sections_valid(self, template: PaperTemplate):
        """每个模板的章节规格应有效。"""
        for spec in template.sections:
            assert isinstance(spec, SectionSpec)
            assert len(spec.section_id) > 0
            assert len(spec.title) > 0
            assert len(spec.writing_guide) > 0
            assert spec.min_words > 0

    @pytest.mark.parametrize("template", ALL_TEMPLATES.values())
    def test_has_required_sections(self, template: PaperTemplate):
        """每个模板都应包含问题重述和参考文献章节。"""
        titles = [s.title for s in template.sections]
        # 至少有一个章节标题包含"重述"或"简介"
        assert any("重述" in t or "简介" in t for t in titles), (
            f"{template.problem_type_name} 缺少问题重述章节"
        )
        # 至少有一个章节标题包含"参考文献"
        assert any("参考文献" in t for t in titles), (
            f"{template.problem_type_name} 缺少参考文献章节"
        )


# ---------------------------------------------------------------------------
# get_template 测试
# ---------------------------------------------------------------------------


class TestGetTemplate:
    """测试 get_template 函数。"""

    @pytest.mark.parametrize(
        "problem_type,expected",
        [
            ("A", TEMPLATE_A),
            ("B", TEMPLATE_B),
            ("C", TEMPLATE_C),
            ("D", TEMPLATE_D),
            ("E", TEMPLATE_E),
            ("F", TEMPLATE_F),
            ("a", TEMPLATE_A),
            ("b", TEMPLATE_B),
            ("c", TEMPLATE_C),
            (" A ", TEMPLATE_A),
            (" a ", TEMPLATE_A),  # 去空格后大写 a -> A
        ],
    )
    def test_get_template(self, problem_type: str, expected: PaperTemplate):
        """get_template 应返回正确的模板。"""
        result = get_template(problem_type)
        assert result is expected

    def test_invalid_type_returns_default(self):
        """无效题型应返回默认模板（C题）。"""
        result = get_template("X")
        assert result is TEMPLATE_C

    def test_empty_type_returns_default(self):
        """空字符串应返回默认模板。"""
        assert get_template("") is TEMPLATE_C


# ---------------------------------------------------------------------------
# get_template_by_problem_text 测试
# ---------------------------------------------------------------------------


class TestGetTemplateByProblemText:
    """测试基于关键词的题型推断。"""

    def test_detect_a(self):
        """检测 A 题关键词。"""
        text = "本题要求建立WLAN信道接入的马尔科夫链仿真器"
        result = get_template_by_problem_text(text)
        assert result.problem_type == "A"

    def test_detect_b(self):
        """检测 B 题关键词。"""
        text = "方形件排样优化与切割下料问题"
        result = get_template_by_problem_text(text)
        assert result.problem_type == "B"

    def test_detect_c(self):
        """检测 C 题关键词。"""
        text = "大规模创新类竞赛评审方案与评价指标体系"
        result = get_template_by_problem_text(text)
        assert result.problem_type == "C"

    def test_detect_d(self):
        """检测 D 题关键词。"""
        text = "碳排放时序预测与双碳路径规划"
        result = get_template_by_problem_text(text)
        assert result.problem_type == "D"

    def test_detect_e(self):
        """检测 E 题关键词。"""
        text = "草原放牧策略与生态微分方程模型"
        result = get_template_by_problem_text(text)
        assert result.problem_type == "E"

    def test_detect_f(self):
        """检测 F 题关键词。"""
        text = "疫情期间生活物资物流选址与路径优化"
        result = get_template_by_problem_text(text)
        assert result.problem_type == "F"

    def test_no_match_returns_default(self):
        """无匹配关键词时返回 C 题模板。"""
        text = "这是一个普通的文本，没有特定关键词"
        result = get_template_by_problem_text(text)
        assert result is TEMPLATE_C

    def test_empty_text_returns_default(self):
        """空文本返回 C 题模板。"""
        result = get_template_by_problem_text("")
        assert result is TEMPLATE_C


# ---------------------------------------------------------------------------
# 辅助函数测试
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    """测试辅助函数。"""

    @pytest.mark.parametrize("problem_type", list("ABCDEF"))
    def test_get_all_section_titles(self, problem_type: str):
        """get_all_section_titles 应返回非空标题列表。"""
        titles = get_all_section_titles(problem_type)
        assert len(titles) >= 5
        assert all(isinstance(t, str) and len(t) > 0 for t in titles)

    @pytest.mark.parametrize("problem_type", list("ABCDEF"))
    def test_get_writing_guide_summary(self, problem_type: str):
        """get_writing_guide_summary 应返回包含关键信息的摘要。"""
        summary = get_writing_guide_summary(problem_type)
        assert "章节结构" in summary
        assert "写作要点" in summary
        assert "常用方法" in summary
        assert "摘要指导" in summary
        assert len(summary) > 100
