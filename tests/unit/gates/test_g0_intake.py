"""G0 输入质量门单元测试。

覆盖 fallback 标记识别和软失败降级逻辑。
"""
from __future__ import annotations

from scr.gates.g0_intake import G0_HARD_FAILURES, check_g0
from scr.runtime.budget import BudgetManager, BudgetType
from scr.schemas.context import ProjectContext, QuestionInfo


# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------


def _make_fallback_question(qid: str = "q1") -> QuestionInfo:
    """创建 fallback 标记的问题。"""
    return QuestionInfo(
        question_id=qid,
        original_text=f"问题{qid} 综合建模",
        objective=f"问题{qid} 综合建模",
        expected_output="计算结果与分析",
        is_fallback=True,
    )


def _make_normal_question(qid: str = "q1") -> QuestionInfo:
    """创建正常（LLM 生成）的问题。"""
    return QuestionInfo(
        question_id=qid,
        original_text=f"问题{qid} 建立评价体系",
        objective=f"问题{qid} 建立评价体系",
        expected_output="指标体系与权重",
        is_fallback=False,
    )


def _make_state(
    questions: list[QuestionInfo],
    *,
    budget_manager=None,
) -> dict:
    """创建测试用状态。"""
    project_context = ProjectContext(
        run_id="test",
        problem_text="测试任务文本",
        questions=questions,
        question_dependencies={q.question_id: q.depends_on for q in questions},
    )
    return {
        "project_context": project_context,
        "data_profile": None,
        "budget_manager": budget_manager,
    }


# ---------------------------------------------------------------------------
# 测试：fallback 标记识别
# ---------------------------------------------------------------------------


class TestG0FallbackDetection:
    """G0 对 fallback 生成问题的识别。"""

    def test_fallback_questions_add_soft_failure_check(self):
        """fallback 问题触发 decomposition_fallback_used 检查项。"""
        state = _make_state([_make_fallback_question()])
        result = check_g0(state)

        assert "decomposition_fallback_used" in result.failed_checks

    def test_normal_questions_do_not_trigger_fallback_check(self):
        """正常 LLM 生成的问题不触发 fallback 检查。"""
        state = _make_state([_make_normal_question()])
        result = check_g0(state)

        assert "decomposition_fallback_used" not in result.failed_checks
        assert result.passed is True
        assert result.action == "pass"

    def test_mixed_fallback_and_normal_triggers_check(self):
        """混合问题中只要有 fallback 就触发检查。"""
        state = _make_state([
            _make_normal_question("q1"),
            _make_fallback_question("q2"),
        ])
        result = check_g0(state)

        assert "decomposition_fallback_used" in result.failed_checks


# ---------------------------------------------------------------------------
# 测试：软失败降级处理
# ---------------------------------------------------------------------------


class TestG0FallbackDegradedPass:
    """G0 fallback 软失败的降级行为。"""

    def test_fallback_is_not_hard_failure(self):
        """decomposition_fallback_used 不在硬失败集合中。"""
        assert "decomposition_fallback_used" not in G0_HARD_FAILURES

    def test_fallback_budget_exhausted_degraded_pass(self):
        """预算耗尽时 fallback 软失败降级通过。"""
        state = _make_state([_make_fallback_question()])
        result = check_g0(state)

        assert result.passed is True
        assert result.action == "pass"
        assert "decomposition_fallback_used" in result.failed_checks

    def test_fallback_with_hard_failure_goes_human(self):
        """fallback 软失败 + 硬失败时走人工介入。"""
        q = _make_fallback_question()
        q.objective = ""  # 触发 objective_empty（软失败）
        # 添加一个硬失败：清空 problem_text
        state = _make_state([q])
        state["project_context"].problem_text = ""
        result = check_g0(state)

        assert result.passed is False
        assert result.action == "human"
        assert "problem_text_empty" in result.failed_checks
        assert "decomposition_fallback_used" in result.failed_checks

    def test_fallback_with_budget_remaining_triggers_retry(self):
        """有剩余预算时 fallback 软失败触发重试。"""
        bm = BudgetManager(run_limits={BudgetType.INTAKE_RETRY: 3})
        state = _make_state([_make_fallback_question()], budget_manager=bm)
        result = check_g0(state)

        assert result.passed is False
        assert result.action == "retry"
        assert "decomposition_fallback_used" in result.failed_checks
