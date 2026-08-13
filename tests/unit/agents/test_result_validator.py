"""ResultValidator evidence-recording regression tests."""
from scr.agents.result_validator import ResultValidator
from scr.schemas.question import QuestionResult


def _result(math_task: str, status: str = "success") -> QuestionResult:
    return QuestionResult(
        question_id="q1",
        status="validating",
        findings={"math_task": math_task},
        computation={
            "status": status,
            "results": {"duration": 0.5},
            "metrics": {"duration_seconds": 0.5},
        },
        formulation={"description": "specific model"},
        assumptions=[{"content": "fixed condition"}],
    )


def test_validator_uses_same_evidence_checks_for_all_task_labels():
    """Task labels must not select different legacy validation strategies."""
    validator = ResultValidator()
    optimization = validator.validate(_result("optimization"))
    simulation = validator.validate(_result("simulation"))

    assert optimization["math_task"] == ""
    assert simulation["math_task"] == ""
    assert [check["name"] for check in optimization["checks"]] == [
        check["name"] for check in simulation["checks"]
    ]


def test_validator_records_missing_evidence_as_warning_not_gate_failure():
    """Evidence gaps are reported for GQ; this agent does not block a task."""
    result = _result("prediction", status="error")
    report = ResultValidator().validate(result)

    assert report["status"] == "warning"
    assert report["summary"]["errors"] == 0
    assert any("计算状态" in risk for risk in report["risks"])
