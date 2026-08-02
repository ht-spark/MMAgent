"""Canonical method registry for generic mathematical modeling tasks."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalMethod:
    key: str
    display_name: str
    family: str
    task: str
    required_outputs: tuple[str, ...]
    validation_requirements: tuple[str, ...]


CANONICAL_METHODS: dict[str, CanonicalMethod] = {
    "entropy_weight": CanonicalMethod(
        "entropy_weight", "熵权法", "客观赋权法", "evaluation",
        ("indicator_weights", "scores_or_ranking"),
        ("weight_sum_check", "sensitivity_analysis"),
    ),
    "topsis": CanonicalMethod(
        "topsis", "TOPSIS", "多属性决策", "evaluation",
        ("normalized_matrix", "ideal_distances", "ranking"),
        ("weight_sensitivity", "ranking_stability"),
    ),
    "ahp": CanonicalMethod(
        "ahp", "层次分析法 AHP", "主观赋权法", "evaluation",
        ("weights", "consistency_ratio"),
        ("consistency_check",),
    ),
    "linear_regression": CanonicalMethod(
        "linear_regression", "线性回归", "线性模型", "prediction",
        ("coefficients", "predictions", "error_metrics"),
        ("residual_analysis", "error_metrics"),
    ),
    "arima": CanonicalMethod(
        "arima", "时间序列 ARIMA", "时间序列模型", "prediction",
        ("forecast", "model_order", "error_metrics"),
        ("residual_whiteness", "forecast_error"),
    ),
    "gm11": CanonicalMethod(
        "gm11", "灰色预测 GM(1,1)", "灰色系统理论", "prediction",
        ("fitted_values", "forecast", "error_metrics"),
        ("posterior_error_check",),
    ),
    "linear_programming": CanonicalMethod(
        "linear_programming", "线性规划", "数学规划", "optimization",
        ("decision_solution", "objective_value", "constraint_check"),
        ("objective_recompute", "constraint_feasibility", "sensitivity_analysis"),
    ),
    "integer_programming": CanonicalMethod(
        "integer_programming", "整数规划", "数学规划", "optimization",
        ("decision_solution", "objective_value", "integrality_check", "constraint_check"),
        ("objective_recompute", "constraint_feasibility", "integrality_check"),
    ),
    "heuristic_optimization": CanonicalMethod(
        "heuristic_optimization", "启发式优化算法", "启发式算法", "optimization",
        ("best_solution", "objective_value", "convergence_trace"),
        ("multi_run_stability", "constraint_feasibility"),
    ),
    "stochastic_programming": CanonicalMethod(
        "stochastic_programming", "随机规划", "随机优化", "stochastic_optimization",
        ("scenario_solutions", "expected_objective", "risk_metrics"),
        ("scenario_sensitivity", "baseline_comparison"),
    ),
    "robust_optimization": CanonicalMethod(
        "robust_optimization", "鲁棒优化", "鲁棒优化", "stochastic_optimization",
        ("robust_solution", "worst_case_objective", "robustness_metrics"),
        ("uncertainty_set_sensitivity", "baseline_comparison"),
    ),
    "monte_carlo_optimization": CanonicalMethod(
        "monte_carlo_optimization", "蒙特卡洛场景优化", "随机优化", "stochastic_optimization",
        ("scenario_statistics", "recommended_solution", "risk_metrics"),
        ("simulation_seed_check", "confidence_interval"),
    ),
    "chance_constrained_programming": CanonicalMethod(
        "chance_constrained_programming", "机会约束规划", "随机优化", "stochastic_optimization",
        ("decision_solution", "violation_probability", "objective_value"),
        ("chance_constraint_check", "scenario_sensitivity"),
    ),
    "monte_carlo_simulation": CanonicalMethod(
        "monte_carlo_simulation", "蒙特卡洛模拟", "仿真模型", "simulation",
        ("simulation_summary", "confidence_interval", "distribution_assumptions"),
        ("seed_reproducibility", "sample_size_sensitivity"),
    ),
}


DEFAULT_METHOD_BY_TASK = {
    "evaluation": "topsis",
    "prediction": "linear_regression",
    "optimization": "linear_programming",
    "stochastic_optimization": "stochastic_programming",
    "simulation": "monte_carlo_simulation",
}


_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("entropy_weight", ("熵权", "entropy")),
    ("topsis", ("topsis", "理想解")),
    ("ahp", ("ahp", "层次分析")),
    ("linear_regression", ("线性回归", "regression", "least squares")),
    ("arima", ("arima", "时间序列")),
    ("gm11", ("gm(1,1)", "gm11", "灰色预测")),
    ("integer_programming", ("整数规划", "integer programming", "0-1", "binary")),
    ("linear_programming", ("线性规划", "linear programming", "lp")),
    ("heuristic_optimization", ("遗传", "粒子群", "模拟退火", "heuristic", "genetic", "pso")),
    ("chance_constrained_programming", ("机会约束", "chance constrained")),
    ("robust_optimization", ("鲁棒", "robust")),
    ("monte_carlo_optimization", ("蒙特卡洛+优化", "场景优化", "monte carlo optimization")),
    ("stochastic_programming", ("随机规划", "stochastic programming")),
    ("monte_carlo_simulation", ("蒙特卡洛", "monte carlo", "simulation", "仿真", "模拟")),
]


def canonicalize_method(
    name: str,
    family: str = "",
    math_task: str = "",
) -> CanonicalMethod | None:
    """Map a loose method label to a canonical modeling method."""
    text = f"{name} {family} {math_task}".lower()
    for key, keywords in _KEYWORDS:
        if any(keyword.lower() in text for keyword in keywords):
            return CANONICAL_METHODS[key]

    default_key = DEFAULT_METHOD_BY_TASK.get(math_task)
    if default_key:
        return CANONICAL_METHODS[default_key]
    return None


def annotate_candidate(candidate: dict, math_task: str) -> dict:
    """Attach canonical method metadata to a method candidate in-place."""
    spec = canonicalize_method(
        str(candidate.get("name", "")),
        str(candidate.get("family", "")),
        math_task,
    )
    if spec is None:
        candidate["canonical_method"] = ""
        candidate["is_actionable"] = False
        return candidate

    original_name = str(candidate.get("name", ""))
    candidate["canonical_method"] = spec.key
    candidate["canonical_family"] = spec.family
    candidate["required_outputs"] = list(spec.required_outputs)
    candidate["validation_requirements"] = list(spec.validation_requirements)
    candidate["is_actionable"] = True

    if _looks_like_web_fragment(original_name):
        candidate["raw_name"] = original_name
        candidate["name"] = spec.display_name
        candidate["family"] = spec.family

    return candidate


def _looks_like_web_fragment(name: str) -> bool:
    if not name:
        return True
    generic_words = ("进行", "建立", "请", "的结果", "作比较", "问题", "本文", "方法")
    if any(word in name for word in generic_words) and not any(
        method.display_name in name for method in CANONICAL_METHODS.values()
    ):
        return True
    return len(name) > 28
