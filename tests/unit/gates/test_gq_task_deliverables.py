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


def test_gq_accepts_llm_contract_keys_for_optimization():
    """LLM 按提示词契约输出 solution/objective 也应通过 GQ 门（键名归一化）。"""
    result = _base_result({
        "status": "success",
        "results": {
            "solution": [1.0, 0.0],
            "objective": 3.5,
        },
        "metrics": {},
    })

    gate = check_gq({"current_result": result, "current_question_id": "q1"})

    assert gate.passed is True


def _stochastic_result(computation):
    return QuestionResult(
        question_id="q1",
        status="validating",
        problem_interpretation=ProblemInterpretation(
            question_id="q1",
            math_task="stochastic_optimization",
            math_task_description="不确定需求下的库存优化",
            result_form="鲁棒方案",
        ),
        decision_record={"selected_method": "随机规划", "canonical_method": "stochastic_programming"},
        assumptions=[{"description": "需求服从已知分布", "type": "model"}],
        formulation={
            "method_key": "stochastic_programming",
            "objective_function": "min E[cost]",
            "ir": {
                "variables": [{"symbol": "q"}],
                "objective": "min E[cost]",
            },
        },
        computation=computation,
        validation={"status": "passed", "checks": [{"passed": True}]},
        findings={"summary": "已完成"},
        reusable_summary=ReusableSummary(
            question_id="q1",
            verified_conclusions=["得到鲁棒订货量"],
        ),
        limitations=["仅对给定分布成立"],
    )


def test_gq_accepts_stochastic_risk_in_results_top_level():
    """LLM 提示词契约把 expected_objective 等风险指标放在 results 顶层，也应通过。"""
    result = _stochastic_result({
        "status": "success",
        "results": {
            "robust_solution": [10.0],
            "expected_objective": 55.0,
            "worst_case": 80.0,
        },
        "metrics": {},
    })

    gate = check_gq({"current_result": result, "current_question_id": "q1"})

    assert gate.passed is True
