"""GQ 质量门与 VALIDATION_ITERATION 预算联动的单元测试。"""
from scr.gates.gq_question import run_gq_node
from scr.runtime.budget import BudgetManager, BudgetType
from scr.schemas.question import (
    ProblemInterpretation,
    QuestionResult,
    ReusableSummary,
)


def _computation_error_result() -> QuestionResult:
    """结构完整但计算失败的结果：唯一失败项为可重试的 computation_error。"""
    return QuestionResult(
        question_id="Q1",
        status="validating",
        problem_interpretation=ProblemInterpretation(
            question_id="Q1",
            math_task="composite",
        ),
        decision_record={
            "selected_method": "问题驱动建模",
            "required_outputs": ["最优方案表"],
        },
        formulation={"description": "测试模型"},
        computation={"status": "error", "error": "generated code failed"},
        validation={"status": "recorded"},
        reusable_summary=ReusableSummary(
            question_id="Q1",
            verified_conclusions=["测试结论"],
        ),
        limitations=["测试限制"],
    )


def _failing_state(bm, retry_count=0):
    """构造一个计算失败（可重试类）的小问结果状态。"""
    return {
        "current_result": _computation_error_result(),
        "current_question_id": "Q1",
        "_solve_retry_count": retry_count,
        "budget_manager": bm,
    }


def test_validation_iteration_consumed_and_blocked_when_exhausted():
    bm = BudgetManager()  # VALIDATION_ITERATION 默认 2
    state = _failing_state(bm, retry_count=0)

    upd1 = run_gq_node(state)
    assert upd1["_gq_action"] == "retry"
    assert bm.get_record(BudgetType.VALIDATION_ITERATION).used == 1

    state["_solve_retry_count"] = upd1["_solve_retry_count"]
    upd2 = run_gq_node(state)
    assert upd2["_gq_action"] == "retry"
    assert bm.get_record(BudgetType.VALIDATION_ITERATION).used == 2

    state["_solve_retry_count"] = upd2["_solve_retry_count"]
    upd3 = run_gq_node(state)
    # 预算耗尽 → 强制 blocked，且不再超额消耗
    assert upd3["_gq_action"] == "blocked"
    assert bm.get_record(BudgetType.VALIDATION_ITERATION).used == 2
    assert state["current_result"].status == "blocked"


def test_node_degradation_blocked_not_retried():
    bm = BudgetManager()
    # 结果已被节点降级标记为 blocked
    res = QuestionResult(question_id="Q1", status="blocked", error_message="x")
    state = {
        "current_result": res,
        "current_question_id": "Q1",
        "_solve_retry_count": 0,
        "budget_manager": bm,
    }
    upd = run_gq_node(state)
    assert upd["_gq_action"] == "blocked"
    # 已 blocked 不应消耗验证迭代预算
    assert bm.get_record(BudgetType.VALIDATION_ITERATION).used == 0


def test_no_budget_falls_back_to_constant():
    # 无预算管理器：直接 blocked（不抛错）
    state = {
        "current_result": QuestionResult(question_id="Q1", status="validating"),
        "current_question_id": "Q1",
        "_solve_retry_count": 0,
        "budget_manager": None,
    }
    upd = run_gq_node(state)
    assert upd["_gq_action"] == "blocked"


def test_validation_iteration_override_via_question_limits():
    bm = BudgetManager()
    # 覆盖 Q1 的验证迭代上限为 1
    bm.set_question_limits("Q1", {BudgetType.VALIDATION_ITERATION: 1})
    state = _failing_state(bm, retry_count=0)
    upd1 = run_gq_node(state)
    assert upd1["_gq_action"] == "retry"
    # 第二次即耗尽（上限 1）
    state["_solve_retry_count"] = upd1["_solve_retry_count"]
    upd2 = run_gq_node(state)
    assert upd2["_gq_action"] == "blocked"


def test_structural_failure_blocks_without_budget_consumption():
    """结构性失败（流程装配字段缺失）直接 blocked，不消耗验证预算。"""
    bm = BudgetManager()
    state = {
        "current_result": QuestionResult(question_id="Q1", status="validating"),
        "current_question_id": "Q1",
        "_solve_retry_count": 0,
        "budget_manager": bm,
    }
    upd = run_gq_node(state)
    assert upd["_gq_action"] == "blocked"
    assert bm.get_record(BudgetType.VALIDATION_ITERATION).used == 0


def test_computation_error_consumes_validation_budget_and_returns_feedback():
    """执行失败也必须由 GQ 统一决定重试并提供修订反馈。"""
    bm = BudgetManager()
    result = _computation_error_result()
    update = run_gq_node({
        "current_result": result,
        "current_question_id": "Q1",
        "_solve_retry_count": 0,
        "budget_manager": bm,
    })

    assert update["_gq_action"] == "retry"
    assert bm.get_record(BudgetType.VALIDATION_ITERATION).used == 1
    assert "computation_error" in update["_gq_feedback"]
