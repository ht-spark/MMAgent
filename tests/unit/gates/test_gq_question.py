"""GQ 小问结果质量门单元测试。

对应 plan.md Phase 2 测试要求和 architecture.md §5.7。
"""
from __future__ import annotations

from scr.runtime.budget import BudgetManager
from scr.schemas.question import (
    ProblemInterpretation,
    QuestionResult,
    ReusableSummary,
)
from scr.gates.gq_question import (
    check_gq,
    run_gq_node,
    route_after_gq,
)


# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------


def _make_valid_result(qid: str = "q1") -> QuestionResult:
    """创建结构完整的 QuestionResult（应通过 GQ）。"""
    return QuestionResult(
        question_id=qid,
        status="validating",
        problem_interpretation=ProblemInterpretation(
            question_id=qid,
            math_task="optimization",
            result_form="最优方案表",
        ),
        decision_record={
            "selected_method": "问题驱动建模",
            "required_outputs": ["最优方案表", "目标值"],
        },
        assumptions=[{"description": "测试假设", "type": "model"}],
        formulation={
            "description": "测试模型",
            "decision_variables": ["x"],
            "objective_function": "max Z",
            "constraints": ["x >= 0"],
        },
        computation={
            "status": "success",
            "results": {"solution": [1.0], "objective": 1.0},
            "metrics": {},
        },
        validation={"status": "passed", "checks": [{"passed": True}]},
        reusable_summary=ReusableSummary(
            question_id=qid,
            verified_conclusions=["测试结论"],
        ),
        limitations=["测试限制"],
    )


def _make_state(
    result: QuestionResult | None,
    qid: str = "q1",
    retry_count: int = 0,
    budget_manager=None,
) -> dict:
    """创建测试用状态。"""
    return {
        "current_question_id": qid,
        "current_result": result,
        "_solve_retry_count": retry_count,
        "budget_manager": budget_manager,
    }


# ---------------------------------------------------------------------------
# check_gq 测试
# ---------------------------------------------------------------------------


class TestCheckGQ:
    """GQ 检查逻辑测试。"""

    def test_pass_with_complete_result(self):
        """结构完整的结果应通过 GQ。"""
        state = _make_state(_make_valid_result())
        result = check_gq(state)
        assert result.passed is True
        assert result.action == "pass"
        assert len(result.failed_checks) == 0

    def test_fail_when_result_missing(self):
        """结果缺失时 GQ 失败。"""
        state = _make_state(None)
        result = check_gq(state)
        assert result.passed is False
        assert "result_missing" in result.failed_checks

    def test_fail_when_interpretation_missing(self):
        """问题理解缺失时 GQ 失败。"""
        result = _make_valid_result()
        result.problem_interpretation = None
        state = _make_state(result)
        gq = check_gq(state)
        assert gq.passed is False
        assert "problem_interpretation_missing" in gq.failed_checks

    def test_fail_when_reusable_summary_missing(self):
        """可复用摘要缺失时 GQ 失败。"""
        result = _make_valid_result()
        result.reusable_summary = None
        state = _make_state(result)
        gq = check_gq(state)
        assert gq.passed is False
        assert "reusable_summary_missing" in gq.failed_checks

    def test_fail_when_limitations_empty(self):
        """局限为空时 GQ 失败。"""
        result = _make_valid_result()
        result.limitations = []
        state = _make_state(result)
        gq = check_gq(state)
        assert gq.passed is False
        assert "limitations_empty" in gq.failed_checks

    def test_fail_when_question_id_mismatch(self):
        """question_id 不匹配时 GQ 失败。"""
        result = _make_valid_result("q1")
        state = _make_state(result, qid="q2")
        gq = check_gq(state)
        assert gq.passed is False
        assert any("question_id_mismatch" in c for c in gq.failed_checks)


# ---------------------------------------------------------------------------
# run_gq_node 测试
# ---------------------------------------------------------------------------


class TestRunGQNode:
    """GQ 节点执行测试。"""

    def test_pass_updates_status(self):
        """通过时更新状态为 validated。"""
        state = _make_state(_make_valid_result())
        result = run_gq_node(state)
        assert result["_gq_action"] == "pass"
        assert result["current_result"].status == "validated"

    def test_retry_when_incomplete(self):
        """结构不完整时触发重试。"""
        result = _make_valid_result()
        result.reusable_summary = None  # 缺少摘要
        state = _make_state(result, retry_count=0, budget_manager=BudgetManager())
        gq_result = run_gq_node(state)
        assert gq_result["_gq_action"] == "retry"
        assert gq_result["_solve_retry_count"] == 1
        assert gq_result["current_result"].status == "solving"

    def test_block_without_budget_manager(self):
        """无预算管理器时直接 blocked。"""
        result = _make_valid_result()
        result.reusable_summary = None  # 缺少摘要，永远过不了
        state = _make_state(result)
        gq_result = run_gq_node(state)
        assert gq_result["_gq_action"] == "blocked"
        assert gq_result["current_result"].status == "blocked"
        assert "GQ 验证失败" in gq_result["current_result"].error_message

    def test_block_records_failed_checks(self):
        """blocked 时记录失败项。"""
        result = _make_valid_result()
        result.reusable_summary = None
        state = _make_state(result)
        gq_result = run_gq_node(state)
        assert "reusable_summary_missing" in gq_result["current_result"].error_message


# ---------------------------------------------------------------------------
# route_after_gq 测试
# ---------------------------------------------------------------------------


class TestRouteAfterGQ:
    """GQ 路由函数测试。"""

    def test_route_pass(self):
        """pass 动作正确路由。"""
        assert route_after_gq({"_gq_action": "pass"}) == "pass"

    def test_route_retry(self):
        """retry 动作正确路由。"""
        assert route_after_gq({"_gq_action": "retry"}) == "retry"

    def test_route_blocked(self):
        """blocked 动作正确路由。"""
        assert route_after_gq({"_gq_action": "blocked"}) == "blocked"

    def test_route_default(self):
        """无动作时默认路由到 pass。"""
        assert route_after_gq({}) == "pass"


class TestGQBlockedShortCircuit:
    """系统性加固：status=blocked 的结果直接判定 blocked，不重算字段。"""

    def test_blocked_result_short_circuits(self):
        from scr.schemas.question import QuestionResult

        br = QuestionResult(question_id="q1", status="blocked", error_message="x")
        result = check_gq({"current_result": br, "current_question_id": "q1"})
        assert result.action == "blocked"
        assert result.failed_checks == ["result_blocked"]
