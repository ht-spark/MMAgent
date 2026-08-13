from scr.tools.table_tools import generate_latex_formula


def test_formula_generation_does_not_invent_stochastic_template_formulas():
    formulation = {
        "math_task": "stochastic_optimization",
        "objective_function": "",
        "decision_variables": ["x_j"],
        "constraints": [],
    }

    formulas = generate_latex_formula(
        formulation,
        "q2",
        {"math_task": "stochastic_optimization", "alpha": 0.1},
    )

    assert formulas == []
