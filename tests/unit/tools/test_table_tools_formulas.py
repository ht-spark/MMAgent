from scr.tools.table_tools import generate_latex_formula


def test_stochastic_formula_generation_escapes_latex_braces_in_f_strings():
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

    chance_constraints = [
        formula for _, formula in formulas if r"g_i(\mathbf{x}" in formula
    ]
    assert chance_constraints
    assert r"\mathbf{x}" in chance_constraints[0]
    assert r"\boldsymbol{\xi}" in chance_constraints[0]
