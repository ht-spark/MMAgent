from scr.agents.model_builder import ModelBuilder
from scr.schemas.question import CurrentQuestionContext, ProblemInterpretation


def test_model_builder_attaches_generic_formulation_ir():
    builder = ModelBuilder()
    context = CurrentQuestionContext(
        question_id="q1",
        question_text="给出最优方案",
        objective="优化资源配置",
    )
    interpretation = ProblemInterpretation(
        question_id="q1",
        math_task="optimization",
        math_task_description="优化问题",
        result_form="最优方案",
    )

    formulation = builder._build_formulation(
        "线性规划",
        "optimization",
        interpretation,
        context,
        "linear_programming",
    )

    assert formulation["method_key"] == "linear_programming"
    assert formulation["ir"]["method_key"] == "linear_programming"
    assert formulation["ir"]["variables"]
    assert formulation["ir"]["objective"]
    assert formulation["ir"]["required_outputs"]
