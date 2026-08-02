from scr.gates.gq_question import check_gq
from scr.schemas.question import ProblemInterpretation, QuestionResult, ReusableSummary


def _base_result(computation):
    return QuestionResult(
        question_id="q1",
        status="validating",
        problem_interpretation=ProblemInterpretation(
            question_id="q1",
            math_task="optimization",
            math_task_description="资源优化",
            result_form="最优方案",
        ),
        decision_record={"selected_method": "线性规划", "canonical_method": "linear_programming"},
        assumptions=[{"description": "参数已知", "type": "model"}],
        formulation={
            "method_key": "linear_programming",
            "objective_function": "max Z",
            "decision_variables": ["x_j"],
            "ir": {
                "variables": [{"symbol": "x_j"}],
                "objective": "max Z",
            },
        },
        computation=computation,
        validation={"status": "passed", "checks": [{"passed": True}]},
        findings={"summary": "已完成"},
        reusable_summary=ReusableSummary(
            question_id="q1",
            verified_conclusions=["得到一个可行方案"],
        ),
        limitations=["仅在当前参数下成立"],
    )


def test_gq_rejects_generic_stats_for_optimization_task():
    result = _base_result({
        "status": "generic_stats",
        "results": {"data_summary": {"mean": [1.0]}},
        "metrics": {"n_samples": 10},
    })

    gate = check_gq({"current_result": result, "current_question_id": "q1"})

    assert gate.passed is False
    assert "optimization_generic_stats_not_sufficient" in gate.failed_checks


def test_gq_accepts_optimization_with_solution_and_objective():
    result = _base_result({
        "status": "success",
        "results": {
            "optimal_solution": [1.0, 0.0],
            "optimal_objective": 3.5,
        },
        "metrics": {"objective_value": 3.5},
    })

    gate = check_gq({"current_result": result, "current_question_id": "q1"})

    assert gate.passed is True
