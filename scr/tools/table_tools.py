"""表格格式化工具 — 从计算结果生成规范的 Markdown 表格。

确定性工具，不依赖 LLM。

功能：
  1. 格式化优化结果表（决策变量取值、约束满足情况）
  2. 格式化验证报告表（检查项、通过/失败、详情）
  3. 格式化数据摘要表（统计量、缺失率）
  4. 格式化指标对比表（多问横向对比）
  5. 生成 LaTeX 公式字符串
"""
from __future__ import annotations

from typing import Any

import numpy as np

__all__ = [
    "format_solution_table",
    "format_metrics_table",
    "format_validation_table",
    "format_data_summary_table",
    "format_comparison_table",
    "format_assumptions_table",
    "format_symbols_table",
    "generate_latex_formula",
    "generate_all_tables",
]


def _fmt_num(v: Any, decimals: int = 4) -> str:
    """格式化数值。"""
    if isinstance(v, float):
        if np.isfinite(v):
            return f"{v:.{decimals}f}"
        return "N/A"
    if isinstance(v, (list, np.ndarray)):
        arr = np.array(v, dtype=float)
        if len(arr) <= 5:
            return ", ".join(f"{x:.2f}" for x in arr)
        return f"[{', '.join(f'{x:.2f}' for x in arr[:5])}, ...]"
    return str(v)


# ---------------------------------------------------------------------------
# 1. 优化结果表
# ---------------------------------------------------------------------------


def format_solution_table(
    computation: dict[str, Any],
    qid: str,
    feature_names: list[str] | None = None,
    max_rows: int = 15,
) -> str:
    """格式化优化求解结果为 Markdown 表格。

    当变量数超过 max_rows 时，仅展示非零变量，零变量汇总显示。

    Args:
        computation: 计算结果。
        qid: 小问 ID。
        feature_names: 变量名列表（可选）。
        max_rows: 最大展示行数（不含表头和汇总行）。

    Returns:
        Markdown 表格字符串。
    """
    results = computation.get("results", {})
    solution = results.get("optimal_solution", [])
    objective = results.get("optimal_objective", None)

    if not solution:
        return f"（问题 {qid} 无求解结果）"

    lines: list[str] = []
    lines.append("| 序号 | 变量名 | 最优取值 | 是否非零 |")
    lines.append("|------|--------|----------|----------|")

    # 分离非零和零变量
    nonzero_items = []
    zero_items = []
    for i, val in enumerate(solution):
        name = feature_names[i] if feature_names and i < len(feature_names) else f"x_{i+1}"
        if abs(val) > 0.01:
            nonzero_items.append((i + 1, name, val, "是"))
        else:
            zero_items.append((i + 1, name, val, "否"))

    # 展示非零变量
    for seq, name, val, nz in nonzero_items[:max_rows]:
        lines.append(f"| {seq} | {name} | {_fmt_num(val)} | {nz} |")

    # 如果非零变量太多，截断
    if len(nonzero_items) > max_rows:
        lines.append(f"| ... | 另有 {len(nonzero_items) - max_rows} 个非零变量省略 | ... | ... |")

    # 汇总零变量
    if zero_items:
        lines.append(f"| - | （另有 {len(zero_items)} 个零变量） | 0.0000 | 否 |")

    # 汇总行
    total = sum(abs(v) for v in solution)
    n_nonzero = len(nonzero_items)
    lines.append(f"| **合计** | — | **{_fmt_num(total)}** | **{n_nonzero} 个非零** |")

    if objective is not None:
        lines.append("")
        lines.append(f"**最优目标值**：{_fmt_num(objective)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. 指标表
# ---------------------------------------------------------------------------


def format_metrics_table(
    computation: dict[str, Any],
    qid: str,
) -> str:
    """格式化关键指标为 Markdown 表格。"""
    metrics = computation.get("metrics", {})

    if not metrics:
        return f"（问题 {qid} 无指标数据）"

    lines: list[str] = []
    lines.append("| 指标名称 | 数值 | 说明 |")
    lines.append("|----------|------|------|")

    metric_labels = {
        "n_samples": ("样本数", "参与计算的数据行数"),
        "n_features": ("特征数", "参与计算的数值列数"),
        "objective_value": ("目标值", "优化目标函数值"),
        "optimal_objective": ("最优目标值", "优化目标函数最优值"),
        "total_allocation": ("总分配量", "所有决策变量之和"),
        "capacity_utilization": ("容量利用率", "已用容量/总容量"),
        "expected_objective": ("期望目标值", "随机优化期望最优值"),
        "objective_std": ("目标值标准差", "随机优化目标值波动"),
        "worst_case": ("最坏情况", "最坏场景目标值"),
        "robustness_ratio": ("鲁棒性比率", "最坏/期望，越接近1越鲁棒"),
        "n_scenarios": ("场景数", "蒙特卡洛模拟场景数"),
        "n_simulations": ("模拟次数", "蒙特卡洛模拟次数"),
        "simulation_seed": ("随机种子", "模拟随机种子"),
        "posterior_ratio_c": ("后验差比C", "GM(1,1)精度指标"),
        "small_error_probability": ("小误差概率P", "GM(1,1)精度指标"),
        "r_squared": ("R²", "线性回归决定系数"),
        "rmse": ("RMSE", "均方根误差"),
        "max_entropy": ("最大熵值", "熵权法指标"),
        "min_entropy": ("最小熵值", "熵权法指标"),
    }

    for key, value in metrics.items():
        label, desc = metric_labels.get(key, (key, ""))
        lines.append(f"| {label} | {_fmt_num(value)} | {desc} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. 验证报告表
# ---------------------------------------------------------------------------


def format_validation_table(
    validation: dict[str, Any],
    qid: str,
) -> str:
    """格式化验证报告为 Markdown 表格。

    将嵌套的 checks 列表展开为逐条检查结果表。
    """
    if not validation:
        return f"（问题 {qid} 验证待完成）"

    lines: list[str] = []

    # 汇总信息
    summary = validation.get("summary", {})
    status = validation.get("status", "unknown")
    status_labels = {
        "passed": "通过 ✓",
        "warning": "警告 ⚠",
        "failed": "失败 ✗",
    }
    status_label = status_labels.get(status, status)

    lines.append(f"**验证状态**：{status_label}")
    if summary:
        lines.append(
            f"**检查统计**：共 {summary.get('total_checks', 0)} 项，"
            f"通过 {summary.get('passed', 0)} 项，"
            f"警告 {summary.get('warnings', 0)} 项，"
            f"错误 {summary.get('errors', 0)} 项"
        )
    lines.append("")

    # 检查明细表
    checks = validation.get("checks", [])
    if checks:
        lines.append("| 检查项 | 类别 | 结果 | 严重级别 | 说明 |")
        lines.append("|--------|------|------|----------|------|")

        for check in checks:
            name = check.get("name", "")
            category = check.get("category", "")
            passed = "✓" if check.get("passed") else "✗"
            severity = check.get("severity", "info")
            detail = check.get("detail", "")

            # 严重级别中文标签
            sev_labels = {
                "info": "信息",
                "warning": "警告",
                "error": "错误",
            }
            sev_label = sev_labels.get(severity, severity)

            lines.append(f"| {name} | {category} | {passed} | {sev_label} | {detail} |")

    # 风险列表
    risks = validation.get("risks", [])
    if risks:
        lines.append("")
        lines.append("**主要风险**：")
        for risk in risks:
            lines.append(f"- {risk}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. 数据摘要表
# ---------------------------------------------------------------------------


def format_data_summary_table(
    computation: dict[str, Any],
    qid: str,
) -> str:
    """格式化数据摘要统计表。"""
    results = computation.get("results", {})

    if "data_summary" in results:
        ds = results["data_summary"]
        lines: list[str] = []
        lines.append("| 统计量 | 值 |")
        lines.append("|--------|------|")

        for key, value in ds.items():
            if isinstance(value, list):
                lines.append(f"| {key} | {_fmt_num(value)} |")
            elif isinstance(value, dict):
                for sub_key, sub_val in value.items():
                    lines.append(f"| {key}.{sub_key} | {_fmt_num(sub_val)} |")
            else:
                lines.append(f"| {key} | {_fmt_num(value)} |")

        return "\n".join(lines)

    if "simulation" in results:
        sim = results["simulation"]
        lines: list[str] = []
        lines.append("| 统计量 | 值 |")
        lines.append("|--------|------|")

        for key, value in sim.items():
            if isinstance(value, list):
                lines.append(f"| {key} | {_fmt_num(value)} |")
            elif isinstance(value, dict):
                for sub_key, sub_val in value.items():
                    lines.append(f"| {key}.{sub_key} | {_fmt_num(sub_val)} |")
            else:
                lines.append(f"| {key} | {_fmt_num(value)} |")

        return "\n".join(lines)

    return f"（问题 {qid} 无数据摘要）"


# ---------------------------------------------------------------------------
# 5. 多问对比表
# ---------------------------------------------------------------------------


def format_comparison_table(
    question_results: dict[str, Any],
) -> str:
    """格式化多问横向对比表。"""
    qids = sorted(question_results.keys())
    if not qids:
        return "（无小问结果）"

    lines: list[str] = []
    lines.append("| 问题 | 题型 | 方法 | 计算状态 | 目标值 | 验证状态 |")
    lines.append("|------|------|------|----------|--------|----------|")

    for qid in qids:
        result = question_results[qid]
        computation = result.computation if hasattr(result, "computation") else result.get("computation", {})
        interp = result.problem_interpretation if hasattr(result, "problem_interpretation") else result.get("problem_interpretation", None)
        findings = result.findings if hasattr(result, "findings") else result.get("findings", {})
        validation = result.validation if hasattr(result, "validation") else result.get("validation", {})

        task = interp.math_task if interp else "composite"
        task_labels = {
            "evaluation": "评价/排序",
            "prediction": "预测/回归",
            "optimization": "优化/规划",
            "stochastic_optimization": "随机优化",
            "classification": "分类",
            "clustering": "聚类",
            "simulation": "仿真/模拟",
            "mechanism": "机理建模",
            "composite": "综合任务",
        }
        task_label = task_labels.get(task, task)

        method = findings.get("selected_method", "未知")
        comp_status = findings.get("computation_status", "unknown")
        status_labels = {
            "success": "成功 ✓",
            "generic_stats": "统计完成",
            "insufficient_data": "数据不足",
            "no_data": "无数据",
            "error": "错误 ✗",
            "stub": "占位",
        }
        comp_label = status_labels.get(comp_status, comp_status)

        results = computation.get("results", {})
        obj = results.get("optimal_objective", results.get("expected_objective", "—"))
        obj_str = _fmt_num(obj) if isinstance(obj, (int, float)) else str(obj)

        val_status = validation.get("status", "—") if validation else "—"
        val_labels = {
            "passed": "通过 ✓",
            "warning": "警告 ⚠",
            "failed": "失败 ✗",
        }
        val_label = val_labels.get(val_status, val_status)

        lines.append(f"| {qid} | {task_label} | {method} | {comp_label} | {obj_str} | {val_label} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 6. 假设表
# ---------------------------------------------------------------------------


# 通用假设关键词 — 这些假设在多个问题中重复出现，仅在首次出现时保留
_GENERIC_ASSUMPTION_KEYWORDS = [
    "样本量有限",
    "无时间维度数据",
    "不可使用时间序列方法",
    "数值结果已由确定性代码生成",
    "可复现",
    "题型验证待",
]

# 继承前问假设的前缀 — 这些是递归引用，不含实质假设内容
_INHERIT_PREFIXES = ["继承前问假设"]


def _is_generic_assumption(text: str) -> bool:
    """判断是否为通用/递归假设（应在全局假设中只出现一次）。"""
    for kw in _GENERIC_ASSUMPTION_KEYWORDS:
        if kw in text:
            return True
    for prefix in _INHERIT_PREFIXES:
        if text.startswith(prefix):
            return True
    return False


def format_assumptions_table(
    question_results: dict[str, Any],
) -> str:
    """格式化各小问假设表（去重 + 过滤通用假设）。

    策略：
      - 通用假设（如"样本量有限"）仅在每个问题首次出现时保留
      - "继承前问假设"类递归引用不显示
      - 同一问题内的重复假设去重
    """
    qids = sorted(question_results.keys())

    lines: list[str] = []
    lines.append("| 问题 | 假设内容 |")
    lines.append("|------|----------|")

    # 全局已显示的通用假设
    global_generic_shown: set[str] = set()

    for qid in qids:
        result = question_results[qid]
        assumptions = result.assumptions if hasattr(result, "assumptions") else result.get("assumptions", [])
        seen_in_qid = set()
        for a in assumptions:
            # assumptions 可能是 dict 或 str
            if isinstance(a, dict):
                a_clean = (
                    a.get("content")
                    or a.get("description")
                    or a.get("text")
                    or str(a)
                )
            else:
                a_clean = str(a)
            a_clean = a_clean.strip()
            if not a_clean:
                continue
            # 跳过继承前问假设
            if any(a_clean.startswith(p) for p in _INHERIT_PREFIXES):
                continue
            # 跳过同问题内重复
            if a_clean in seen_in_qid:
                continue
            # 通用假设：每个只全局显示一次
            if _is_generic_assumption(a_clean):
                if a_clean in global_generic_shown:
                    continue
                global_generic_shown.add(a_clean)
            seen_in_qid.add(a_clean)
            lines.append(f"| {qid} | {a_clean} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 7. 符号表
# ---------------------------------------------------------------------------


def format_symbols_table(
    question_results: dict[str, Any],
) -> str:
    """格式化符号说明表（去重后）。"""
    qids = sorted(question_results.keys())

    lines: list[str] = []
    lines.append("| 符号 | 含义 | 所属问题 |")
    lines.append("|------|------|----------|")

    seen_symbols: set[str] = set()
    for qid in qids:
        result = question_results[qid]
        formulation = result.formulation if hasattr(result, "formulation") else result.get("formulation", {})
        if not formulation:
            continue

        decision_vars = formulation.get("decision_variables", [])
        params = formulation.get("parameters", {})

        for dv in decision_vars:
            if dv not in seen_symbols:
                seen_symbols.add(dv)
                lines.append(f"| {dv} | 决策变量 | {qid} |")

        for sym, desc in params.items():
            if sym not in seen_symbols:
                seen_symbols.add(sym)
                lines.append(f"| {sym} | {desc} | {qid} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 8. LaTeX 公式生成
# ---------------------------------------------------------------------------


def _unicode_to_latex(text: str) -> str:
    """将 Unicode 数学符号转换为 LaTeX 命令。"""
    # 注意：多字符替换必须在前，单字符替换在后
    replacements = [
        # 多字符组合（优先替换）
        ("β₀", r"\beta_0"), ("β₁", r"\beta_1"), ("β_j", r"\beta_j"),
        ("x_ij", r"x_{ij}"), ("y_i", r"y_i"),
        # 上标/下标符号
        ("²", "^2"), ("³", "^3"), ("₀", "_0"), ("₁", "_1"), ("₂", "_2"),
        ("ₙ", "_n"), ("ₘ", "_m"), ("ₚ", "_p"),
        # 数学运算符
        ("·", r"\cdot "), ("×", r"\times "), ("÷", r"\div "), ("±", r"\pm "),
        ("≤", r"\leq"), ("≥", r"\geq"), ("≠", r"\neq"),
        ("→", r"\to"), ("←", r"\leftarrow"), ("↔", r"\leftrightarrow"),
        ("∈", r"\in"), ("∉", r"\notin"), ("∀", r"\forall"), ("∃", r"\exists"),
        ("∞", r"\infty"), ("∂", r"\partial"),
        # 大写希腊字母
        ("Σ", r"\sum"), ("∏", r"\prod"), ("∫", r"\int"),
        ("Γ", r"\Gamma"), ("Δ", r"\Delta"), ("Θ", r"\Theta"),
        ("Λ", r"\Lambda"), ("Φ", r"\Phi"), ("Ψ", r"\Psi"), ("Ω", r"\Omega"),
        # 小写希腊字母
        ("α", r"\alpha"), ("β", r"\beta"), ("γ", r"\gamma"), ("δ", r"\delta"),
        ("ε", r"\epsilon"), ("ζ", r"\zeta"), ("η", r"\eta"), ("θ", r"\theta"),
        ("λ", r"\lambda"), ("μ", r"\mu"), ("ν", r"\nu"), ("ξ", r"\xi"),
        ("π", r"\pi"), ("ρ", r"\rho"), ("σ", r"\sigma"), ("τ", r"\tau"),
        ("φ", r"\phi"), ("χ", r"\chi"), ("ψ", r"\psi"), ("ω", r"\omega"),
    ]
    result = text
    for uni, latex in replacements:
        result = result.replace(uni, latex)
    return result


def _is_mathematical_constraint(text: str) -> bool:
    """判断约束条件是否为数学表达式（而非纯文字描述）。

    纯文字约束如"误差独立同分布"不应作为公式展示。
    """
    # 包含数学运算符或关系符的视为数学约束
    math_indicators = ["≤", "≥", "=", "<", ">", "≤", "≥", "+", "-",
                       "\\leq", "\\geq", "\\sum", "\\max", "\\min"]
    has_math = any(ind in text for ind in math_indicators)
    # 纯中文（无数学符号）的视为非数学约束
    has_chinese = any("\u4e00" <= ch <= "\u9fff" for ch in text)
    return has_math or not has_chinese


def generate_latex_formula(
    formulation: dict[str, Any],
    qid: str,
) -> list[tuple[str, str]]:
    """从模型表述生成规范的 LaTeX 公式列表。

    Args:
        formulation: 模型表述字典。
        qid: 小问 ID。

    Returns:
        [(标签, 公式)] 列表，标签为中文描述，公式为纯 LaTeX（不含 $$ 或 \\[\\]）。
    """
    formulas: list[tuple[str, str]] = []
    math_task = formulation.get("math_task", "")
    obj_func = formulation.get("objective_function", "")

    # 将目标函数中的 Unicode 符号转换为 LaTeX
    if obj_func:
        obj_func = _unicode_to_latex(obj_func)

    if math_task in ("optimization", "stochastic_optimization"):
        formulas.append(("目标函数", obj_func or r"\max / \min \quad c^T x"))
        formulas.append(("约束条件",
                         r"\text{s.t.}\quad \sum_{j=1}^{n} a_{ij} x_j \leq b_i, \quad i=1,\ldots,m"))
        formulas.append(("非负约束", r"x_j \geq 0, \quad j=1,\ldots,n"))

    elif math_task == "evaluation":
        formulas.append(("综合评价函数", obj_func or r"S = \sum_{j=1}^{m} w_j \cdot x_j"))
        formulas.append(("权重约束", r"w_j \geq 0, \quad \sum_{j=1}^{m} w_j = 1"))

    elif math_task == "prediction":
        formulas.append(("目标函数", obj_func or r"\min \sum_{i=1}^{n} (y_i - \hat{y}_i)^2"))
        formulas.append(("回归模型", r"\hat{y} = \beta_0 + \sum_{j=1}^{p} \beta_j x_j"))

    elif math_task == "simulation":
        formulas.append(("蒙特卡洛估计", r"\hat{\theta} = \frac{1}{N} \sum_{s=1}^{N} f(\xi_s)"))
        formulas.append(("分布假设", r"\xi_s \sim F(\cdot), \quad s=1,\ldots,N"))

    else:
        if obj_func:
            formulas.append(("目标函数", obj_func))

    return formulas


# ---------------------------------------------------------------------------
# 9. 统一入口：生成所有表格
# ---------------------------------------------------------------------------


def generate_all_tables(
    question_results: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """为所有小问生成格式化表格。

    Args:
        question_results: 所有小问结果。

    Returns:
        {qid: {table_type: markdown_table_string}} 的映射。
    """
    all_tables: dict[str, dict[str, str]] = {}

    for qid, result in question_results.items():
        computation = result.computation if hasattr(result, "computation") else result.get("computation", {})
        validation = result.validation if hasattr(result, "validation") else result.get("validation", {})
        data_prep = result.data_preparation if hasattr(result, "data_preparation") else result.get("data_preparation", {})

        tables: dict[str, str] = {}
        tables["solution"] = format_solution_table(
            computation, qid,
            data_prep.get("feature_names") if data_prep else None,
        )
        tables["metrics"] = format_metrics_table(computation, qid)
        tables["validation"] = format_validation_table(validation, qid)
        tables["data_summary"] = format_data_summary_table(computation, qid)

        all_tables[qid] = tables

    # 全局对比表
    all_tables["_global"] = {
        "comparison": format_comparison_table(question_results),
        "assumptions": format_assumptions_table(question_results),
        "symbols": format_symbols_table(question_results),
    }

    return all_tables
