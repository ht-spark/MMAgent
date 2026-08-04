"""结果键名归一化工具。

统一三套键名契约，避免"LLM 严格按提示词输出的合格结果被硬编码校验误杀"：
  - LLM 提示词契约（prompts/code_based_modeling.md）：`solution` / `objective` / `r2` ...
  - 预设方法契约（model_builder 确定性计算）：`optimal_solution` / `optimal_objective` / `r_squared` ...
  - 校验/门禁契约（model_builder._validate_task_results、gq_question、result_validator）

校验前调用 normalize 补齐同义键，使任意合法写法都能命中检查。
"""
from __future__ import annotations

from typing import Any

#: 同义键组：同组内的键视为等价，normalize 时互相补齐。
#: 注意：evaluation 的 weights/scores/ranking 是"任一输出形态"，语义不同，不归组。
_ALIAS_GROUPS: list[frozenset[str]] = [
    frozenset({"optimal_solution", "solution", "best_solution", "decision_solution"}),
    frozenset({"optimal_objective", "objective", "objective_value"}),
    frozenset({"r_squared", "r2"}),
]


def normalize_result_dict(value: Any) -> Any:
    """递归补齐同义键。

    返回新 dict（不修改原对象）；对非 dict 原样返回。
    补齐规则：同组内任一键存在，则为其余键写入相同值（递归作用于嵌套 dict）。
    """
    if not isinstance(value, dict):
        return value

    out: dict[str, Any] = {}
    for k, v in value.items():
        out[k] = normalize_result_dict(v) if isinstance(v, dict) else v

    for group in _ALIAS_GROUPS:
        present: dict[str, Any] = {k: out[k] for k in group if k in out}
        if present:
            first_value = next(iter(present.values()))
            for k in group:
                if k not in out:
                    out[k] = first_value

    return out


def normalize_computation(computation: dict) -> dict:
    """就地规范化 computation 字典（results/metrics/intermediate_values 补同义键）。

    幂等：对已规范化的字典再次调用无变化。
    """
    if not isinstance(computation, dict):
        return computation
    for sub_key in ("results", "metrics", "intermediate_values"):
        sub = computation.get(sub_key)
        if isinstance(sub, dict):
            normalized = normalize_result_dict(sub)
            computation[sub_key] = normalized
    return computation
