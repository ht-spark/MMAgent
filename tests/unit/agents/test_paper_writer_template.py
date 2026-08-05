"""PaperWriter 论文模板集成单元测试（统一模板版本）。"""
from __future__ import annotations

from typing import Any

import pytest

from scr.agents.paper_writer import PaperWriter
from scr.schemas.context import ProjectContext, QuestionInfo
from scr.schemas.question import QuestionResult
from scr.templates.paper_templates import (
    UNIFIED_TEMPLATE,
    PaperTemplate,
    get_template,
)


# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------


def _make_question_result(
    qid: str,
    method: str = "线性规划",
    task: str = "optimization",
    key_result: str = "最优解已找到",
) -> QuestionResult:
    """创建测试用 QuestionResult。"""
    return QuestionResult(
        question_id=qid,
        status="validated",
        findings={
            "selected_method": method,
            "math_task": task,
            "key_result": key_result,
        },
        computation={
            "results": {"optimal_objective": 12345.6789},
            "metrics": {},
        },
        assumptions=[{"id": "a1", "content": "测试假设", "rationale": "测试"}],
        formulation={"objective": "max x1 + x2"},
        validation={"passed": True, "checks": []},
    )


def _make_project_context(
    problem_text: str = "某数学建模竞赛题目",
    background: str = "本题涉及评审方案设计与评价指标体系构建。",
) -> ProjectContext:
    """创建测试用 ProjectContext。"""
    return ProjectContext(
        run_id="test-run",
        problem_text=problem_text,
        background_summary=background,
        objectives=["建立评价模型", "求解最优方案"],
        questions=[
            QuestionInfo(
                question_id="q1",
                original_text="问题一：建立评价模型",
                objective="建立综合评价模型",
                question_type="evaluation",
            ),
            QuestionInfo(
                question_id="q2",
                original_text="问题二：求解最优方案",
                objective="求解最优评审方案",
                question_type="optimization",
            ),
        ],
    )


@pytest.fixture
def writer() -> PaperWriter:
    """创建 PaperWriter 实例。"""
    return PaperWriter()


@pytest.fixture
def validated_results() -> dict[str, QuestionResult]:
    """创建已验证的 QuestionResult 字典。"""
    return {
        "q1": _make_question_result("q1", "层次分析法", "evaluation", "排名结果"),
        "q2": _make_question_result("q2", "NSGA-II", "optimization", "Pareto最优解"),
    }


# ---------------------------------------------------------------------------
# _select_template 测试
# ---------------------------------------------------------------------------


class TestSelectTemplate:
    """测试模板加载逻辑（统一模板，不分题型）。"""

    @pytest.mark.parametrize(
        "problem_text",
        [
            "A题 WLAN网络信道接入机制建模",
            "B题 方形件排布优化",
            "C题 大规模创新类竞赛评审方案",
            "D题 碳排放时序分析",
            "E题 草原放牧策略研究",
            "F题 COVID-19疫情期间物资管理",
            "任意不带题型标识的题目文本",
        ],
    )
    def test_always_returns_unified_template(
        self,
        writer: PaperWriter,
        problem_text: str,
    ):
        """无论题目内容如何，都应返回统一模板。"""
        ctx = _make_project_context(problem_text)
        template = writer._select_template(ctx)
        assert template is UNIFIED_TEMPLATE

    def test_select_no_context(self, writer: PaperWriter):
        """项目上下文为 None 时同样返回统一模板。"""
        template = writer._select_template(None)
        assert template is UNIFIED_TEMPLATE

    def test_select_empty_text(self, writer: PaperWriter):
        """问题文本为空时同样返回统一模板。"""
        ctx = _make_project_context("")
        template = writer._select_template(ctx)
        assert template is UNIFIED_TEMPLATE

    def test_select_stores_template(self, writer: PaperWriter):
        """加载的模板应存储在实例属性中。"""
        ctx = _make_project_context("某题目")
        writer._select_template(ctx)
        assert writer._template is not None
        assert writer._template is UNIFIED_TEMPLATE


# ---------------------------------------------------------------------------
# _build_outline 测试
# ---------------------------------------------------------------------------


class TestBuildOutline:
    """测试大纲构建与模板集成。"""

    def test_outline_has_seven_main_sections(
        self,
        writer: PaperWriter,
        validated_results: dict[str, QuestionResult],
    ):
        """大纲应包含 7 个主章节 + 2 个问题子章节 = 9 个章节。"""
        writer._template = get_template()
        sections = writer._build_outline(validated_results)
        # 主章节 1-7 + 子章节 4.1, 4.2
        main_sections = [s for s in sections if "." not in s.section_id]
        assert len(main_sections) == 7
        assert len(sections) == 9

    def test_outline_section_ids(
        self,
        writer: PaperWriter,
        validated_results: dict[str, QuestionResult],
    ):
        """章节 ID 应按 1-7 + 4.1, 4.2 格式排列。"""
        writer._template = get_template()
        sections = writer._build_outline(validated_results)
        ids = [s.section_id for s in sections]
        assert "1" in ids
        assert "2" in ids
        assert "3" in ids
        assert "4" in ids
        assert "4.1" in ids
        assert "4.2" in ids
        assert "5" in ids
        assert "6" in ids
        assert "7" in ids

    def test_outline_uses_generic_titles(
        self,
        writer: PaperWriter,
        validated_results: dict[str, QuestionResult],
    ):
        """大纲标题应使用通用标题，不含领域特定内容。"""
        writer._template = get_template()
        sections = writer._build_outline(validated_results)
        section_1 = next(s for s in sections if s.section_id == "1")
        assert "重述" in section_1.title
        titles = [s.title for s in sections]
        for title in titles:
            assert "交叉分发" not in title
            assert "评审方案" not in title

    def test_outline_question_sections(
        self,
        writer: PaperWriter,
        validated_results: dict[str, QuestionResult],
    ):
        """问题子章节应正确关联 question_id。"""
        writer._template = get_template()
        sections = writer._build_outline(validated_results)
        q_sections = [s for s in sections if s.question_id is not None]
        assert len(q_sections) == 2
        assert q_sections[0].question_id == "q1"
        assert q_sections[1].question_id == "q2"

    def test_match_template_title(self):
        """测试 _match_template_title 始终返回默认标题（不泄露模板标题）。"""
        template = get_template()
        title = PaperWriter._match_template_title(
            template, ["重述"], "默认标题"
        )
        assert title == "默认标题"

    def test_match_template_title_no_match(self):
        """测试 _match_template_title 未匹配时返回默认值。"""
        template = get_template()
        title = PaperWriter._match_template_title(
            template, ["不存在的关键词"], "默认标题"
        )
        assert title == "默认标题"

    def test_get_question_section_title(self):
        """测试 _get_question_section_title 静态方法。"""
        template = get_template()
        title = PaperWriter._get_question_section_title(template, 1, "q1")
        assert "一" in title or "问题" in title

    def test_get_question_section_title_fallback(self):
        """测试超出中文数字范围的问题标题回退。"""
        template = get_template()
        # 第 11 个问题超出中文数字映射范围，应回退到 qid 格式
        title = PaperWriter._get_question_section_title(template, 11, "q11")
        assert title == "问题 q11"
        # 第 5 个问题应使用中文数字"问题五"
        title5 = PaperWriter._get_question_section_title(template, 5, "q5")
        assert title5 == "问题五"


# ---------------------------------------------------------------------------
# _write_abstract 测试
# ---------------------------------------------------------------------------


class TestWriteAbstract:
    """测试摘要生成与模板集成。"""

    def test_abstract_no_hardcoded_crop(
        self,
        writer: PaperWriter,
        validated_results: dict[str, QuestionResult],
    ):
        """摘要不应包含硬编码的"农作物"相关文本。"""
        writer._template = get_template()
        sections = writer._build_outline(validated_results)
        abstract = writer._write_abstract(validated_results, sections)
        assert "农作物" not in abstract
        assert "华北山区" not in abstract
        assert "种植策略" not in abstract

    def test_abstract_contains_problem_count(
        self,
        writer: PaperWriter,
        validated_results: dict[str, QuestionResult],
    ):
        """摘要应包含子问题数量。"""
        writer._template = get_template()
        sections = writer._build_outline(validated_results)
        abstract = writer._write_abstract(validated_results, sections)
        assert "2 个子问题" in abstract

    def test_abstract_contains_keywords(
        self,
        writer: PaperWriter,
        validated_results: dict[str, QuestionResult],
    ):
        """摘要应包含关键词。"""
        writer._template = get_template()
        sections = writer._build_outline(validated_results)
        abstract = writer._write_abstract(validated_results, sections)
        assert "**关键词**" in abstract

    def test_abstract_includes_actual_keywords(
        self,
        writer: PaperWriter,
        validated_results: dict[str, QuestionResult],
    ):
        """摘要关键词应来自各问实际采用的方法。"""
        writer._template = get_template()
        sections = writer._build_outline(validated_results)
        abstract = writer._write_abstract(validated_results, sections)
        # 关键词来自 question_results 的实际方法
        assert "NSGA-II" in abstract or "层次分析法" in abstract

    def test_abstract_methods_from_results_only(
        self,
        writer: PaperWriter,
        validated_results: dict[str, QuestionResult],
    ):
        """摘要方法论只应包含各问实际方法，不掺入模板推荐方法。"""
        writer._template = get_template()
        sections = writer._build_outline(validated_results)
        abstract = writer._write_abstract(validated_results, sections)
        # 统一模板不再提供 method_preferences，未实际使用的方法不应出现
        assert "蒙特卡洛模拟" not in abstract
        assert "马尔科夫链模型" not in abstract

    def test_abstract_template_independent(
        self,
        writer: PaperWriter,
        validated_results: dict[str, QuestionResult],
    ):
        """统一模板下，相同的求解结果应生成相同的摘要。"""
        writer._template = get_template()
        sections = writer._build_outline(validated_results)
        abstract1 = writer._write_abstract(validated_results, sections)
        abstract2 = writer._write_abstract(validated_results, sections)
        assert abstract1 == abstract2

    def test_get_category_description(self):
        """测试 _get_category_description 静态方法。"""
        template = get_template()
        desc = PaperWriter._get_category_description(template)
        assert len(desc) > 0
        assert "问题" in desc


# ---------------------------------------------------------------------------
# 端到端 write 测试
# ---------------------------------------------------------------------------


class TestWriteIntegration:
    """测试 write 方法的模板集成。"""

    def test_write_includes_blocked_placeholder(self, writer: PaperWriter, tmp_path):
        """blocked 小问应在论文中生成占位章节而非整节消失。"""
        from scr.schemas.question import QuestionResult

        q1 = _make_question_result("q1", "层次分析法", "evaluation", "排名结果")
        q2 = QuestionResult(
            question_id="q2",
            status="blocked",
            error_message="GQ 验证失败，已用尽重试预算 (2/2)。失败项: prediction_outputs_missing",
            limitations=["未完成"],
            findings={"math_task": "prediction"},
        )

        state = {
            "question_results": {"q1": q1, "q2": q2},
            "project_context": _make_project_context(),
            "data_profile": None,
            "output_dir": str(tmp_path),
        }
        paper = writer.write(state, output_dir=str(tmp_path))

        # 大纲中包含 q2 章节（question_id 匹配），且标题带"未完成"
        q2_sections = paper.get_sections_by_question("q2")
        assert q2_sections, "blocked 小问缺少占位章节"
        assert "未完成" in q2_sections[0].title

        # 内容说明阻塞原因
        content = "\n".join(s.content for s in q2_sections)
        assert "阻塞" in content
        assert "prediction_outputs_missing" in content

        # full_text 包含占位章节标题
        assert "（未完成）" in paper.full_text

    def test_write_uses_unified_template(self, writer: PaperWriter, tmp_path):
        """无论题目类型如何，完整论文生成都使用统一模板。"""
        ctx = _make_project_context(
            "A题 WLAN网络信道接入机制建模\n本题要求建立马尔科夫链仿真器"
        )
        state = {
            "question_results": {
                "q1": _make_question_result("q1", "马尔科夫链模型", "simulation"),
            },
            "project_context": ctx,
            "data_profile": None,
        }
        paper = writer.write(state, output_dir=str(tmp_path))

        assert paper.title != ""
        assert len(paper.sections) > 0
        assert paper.abstract != ""
        assert writer._template is not None
        assert writer._template is UNIFIED_TEMPLATE

    def test_write_prediction_problem(self, writer: PaperWriter, tmp_path):
        """预测类题目同样使用统一模板完成生成。"""
        ctx = _make_project_context(
            "D题 碳排放时序分析与双碳路径规划\n本题要求进行碳排放预测"
        )
        state = {
            "question_results": {
                "q1": _make_question_result("q1", "时间序列ARIMA", "prediction"),
            },
            "project_context": ctx,
            "data_profile": None,
        }
        paper = writer.write(state, output_dir=str(tmp_path))

        assert writer._template is not None
        assert writer._template is UNIFIED_TEMPLATE
        assert "农作物" not in paper.abstract
