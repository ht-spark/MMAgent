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
    "format_formula_with_number",
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
    lines.append("| 序号 | 决策变量 | 最优取值 | 是否非零 |")
    lines.append("|------|----------|----------|----------|")

    # 分离非零和零变量
    nonzero_items = []
    zero_items = []
    for i, val in enumerate(solution):
        name = feature_names[i] if feature_names and i < len(feature_names) else f"x_{{{i+1}}}"
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

    # 需要跳过的代码级指标（不应在报告中展示）
    _SKIP_METRIC_KEYS = {
        "solver_status", "solver", "method", "status", "message",
        "simulation_seed",  # 随机种子是代码实现细节
        "baseline_objective",  # 基线目标值是内部对比用，非报告指标
        "best_case_objective",  # 最优场景目标值是内部统计
        "scenario_objectives",  # 场景目标值列表是原始数据
        "n_features",  # 特征数是代码级信息
        "n_samples",  # 样本数是代码级信息
    }

    for key, value in metrics.items():
        if key in _SKIP_METRIC_KEYS:
            continue
        # 跳过过长的字符串值（如求解器状态消息）
        if isinstance(value, str) and len(value) > 50:
            continue
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
    lines.append("| 问题 | 题型 | 方法 | 求解结果 | 验证状态 |")
    lines.append("|------|------|------|----------|----------|")

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

        # 求解结果：提取关键数值而非计算状态
        results = computation.get("results", {})
        metrics = computation.get("metrics", {})
        result_str = "—"
        if task in ("optimization", "stochastic_optimization"):
            obj = results.get("optimal_objective")
            if obj is not None:
                result_str = f"最优值 {obj:.4f}"
            elif metrics.get("expected_objective") is not None:
                result_str = f"期望值 {metrics['expected_objective']:.4f}"
        elif task == "simulation":
            n_sim = metrics.get("n_simulations")
            if n_sim is not None:
                result_str = f"{int(n_sim)} 次模拟"
        elif task == "prediction":
            r2 = metrics.get("r_squared")
            if r2 is not None:
                result_str = f"R² = {r2:.4f}"

        val_status = validation.get("status", "—") if validation else "—"
        val_labels = {
            "passed": "通过",
            "warning": "通过（含警告）",
            "failed": "未通过",
        }
        val_label = val_labels.get(val_status, val_status)

        lines.append(f"| {qid} | {task_label} | {method} | {result_str} | {val_label} |")

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
    problem_context: dict | None = None,
) -> list[tuple[str, str]]:
    """从模型表述生成规范的 MathType 风格 LaTeX 公式列表。

    数据驱动生成：优先使用 formulation 中的实际目标函数、决策变量和
    约束条件生成公式；当 formulation 数据不完整时，回退到方法级别的
    通用数学公式（如线性规划标准形、回归模型等），不硬编码任何特定
    领域内容。

    Args:
        formulation: 模型表述字典，包含 math_task, objective_function,
            decision_variables, constraints 等。
        qid: 小问 ID。
        problem_context: 问题上下文字典（可选），可包含字段：
              - problem_description: 问题描述文本
              - math_task: 题型覆盖
              - alpha: 机会约束置信水平
              - n_features: 特征数（预测类）

    Returns:
        [(标签, 公式)] 列表，标签为中文描述，公式为纯 LaTeX
        （不含 $$ 或 \\[\\]）。
    """
    formulas: list[tuple[str, str]] = []
    math_task = formulation.get("math_task", "")
    # problem_context 可覆盖 math_task
    if problem_context and problem_context.get("math_task"):
        math_task = problem_context["math_task"]
    obj_func = formulation.get("objective_function", "")
    decision_vars = formulation.get("decision_variables", [])
    constraints = formulation.get("constraints", [])

    # 将目标函数中的 Unicode 符号转换为 LaTeX
    if obj_func:
        obj_func = _unicode_to_latex(obj_func)

    if math_task == "optimization":
        formulas.extend(_build_optimization_formulas(
            obj_func, decision_vars, constraints, problem_context
        ))
    elif math_task == "stochastic_optimization":
        formulas.extend(_build_stochastic_formulas(
            obj_func, decision_vars, constraints, problem_context
        ))
    elif math_task == "evaluation":
        formulas.extend(_build_evaluation_formulas())
    elif math_task == "prediction":
        formulas.extend(_build_prediction_formulas(problem_context))
    elif math_task == "simulation":
        formulas.extend(_build_simulation_formulas(problem_context))
    else:
        # 通用：如果有自定义目标函数则使用
        if obj_func:
            formulas.append(("目标函数", obj_func))
        if constraints:
            math_constraints = [c for c in constraints if _is_mathematical_constraint(c)]
            for c in math_constraints[:3]:
                c_latex = _unicode_to_latex(c)
                formulas.append(("约束条件", c_latex))

    return formulas


def _is_valid_objective(obj_func: str) -> bool:
    """判断目标函数字符串是否为有效的数学表达式（非占位符）。"""
    _PLACEHOLDER_OBJS = {
        r"\max / \min \quad c^T x",
        r"\max\,/\,\min \quad c^T x",
        "max/min c^T x",
        "max/min cTx",
        "目标函数优化",
        "目标函数",
        "",
    }
    if not obj_func or obj_func.strip() in _PLACEHOLDER_OBJS:
        return False
    has_latex = "\\" in obj_func or any(c in obj_func for c in ["_", "^", "+", "-", "=", "≤", "≥"])
    return has_latex


def _build_optimization_formulas(
    obj_func: str,
    decision_vars: list[str],
    constraints: list[str],
    problem_context: dict | None,
) -> list[tuple[str, str]]:
    """构建确定性优化公式（领域无关，数据驱动）。

    优先使用 formulation 中的实际目标函数和约束条件；
    当数据缺失时回退到线性规划标准形的通用公式。

    通用记号：
      x_j — 决策变量（j = 1, ..., n）
      c_j — 目标函数系数
      a_{ij} — 约束系数矩阵
      b_i — 约束右端项
    """
    formulas: list[tuple[str, str]] = []

    # ----- 目标函数 -----
    if _is_valid_objective(obj_func):
        # 修复常见 LaTeX 格式问题
        obj_func = obj_func.replace(r"\inZ", r"\in \mathbb{Z}")
        obj_func = obj_func.replace(r"\inX", r"\in \mathbb{X}")
        formulas.append(("目标函数", obj_func))
    else:
        # 回退：线性规划标准形
        formulas.append((
            "目标函数",
            r"\max \; (\text{或} \; \min) \quad Z = \sum_{j=1}^{n} c_j \, x_j "
            r"= \mathbf{c}^{\top} \mathbf{x}",
        ))

    # ----- 约束条件 -----
    # 优先使用 formulation 中的实际约束
    math_constraints = [c for c in constraints if _is_mathematical_constraint(c)]
    existing_formulas = set()

    if math_constraints:
        for c in math_constraints[:5]:
            c_latex = _unicode_to_latex(c)
            if c_latex and c_latex not in existing_formulas:
                existing_formulas.add(c_latex)
                formulas.append(("约束条件", c_latex))
    else:
        # 回退：线性规划通用约束
        formulas.append((
            "约束条件",
            r"\text{s.t.} \quad \sum_{j=1}^{n} a_{ij} \, x_j "
            r"\leq \; (\text{或} \; =, \geq) \; b_i, "
            r"\quad i = 1, 2, \ldots, m",
        ))

    # ----- 非负约束 -----
    nonneg = r"x_j \geq 0, \quad j = 1, 2, \ldots, n"
    if nonneg not in existing_formulas:
        # 检查是否已有非负约束
        has_nonneg = any("geq 0" in f or "\\geq 0" in f for _, f in formulas)
        if not has_nonneg:
            formulas.append(("非负约束", nonneg))

    # ----- 决策变量定义 -----
    if decision_vars:
        var_list = ", ".join(decision_vars[:8])
        formulas.append((
            "决策变量定义",
            rf"\textbf{{x}} = (x_1, x_2, \ldots, x_n)^{{\top}} \in \mathbb{{R}}^n, "
            rf"\quad \text{{包括: }} {var_list}",
        ))

    return formulas


def _build_stochastic_formulas(
    obj_func: str,
    decision_vars: list[str],
    constraints: list[str],
    problem_context: dict | None,
) -> list[tuple[str, str]]:
    """构建随机优化公式（领域无关，数据驱动）。

    优先使用 formulation 中的实际目标函数和约束条件；
    当数据缺失时回退到随机规划的通用数学公式。

    通用记号：
      ξ — 随机向量
      E[·] — 期望算子
      P(·) — 概率测度
      α — 显著性水平
    """
    formulas: list[tuple[str, str]] = []
    alpha = 0.05
    if problem_context and isinstance(problem_context.get("alpha"), (int, float)):
        alpha = float(problem_context["alpha"])

    # ----- 期望值目标函数 -----
    if _is_valid_objective(obj_func):
        obj_func = obj_func.replace(r"\inZ", r"\in \mathbb{Z}")
        obj_func = obj_func.replace(r"\inX", r"\in \mathbb{X}")
        if "E[" in obj_func or r"E\left[" in obj_func:
            formulas.append(("目标函数（期望值模型）", obj_func))
        else:
            formulas.append(("目标函数", obj_func))
    else:
        # 回退：随机规划期望值模型标准形
        formulas.append((
            "目标函数（期望值模型）",
            r"\max \; E\left[ Z(\mathbf{x}, \boldsymbol{\xi}) \right] "
            r"= E\left[ f(\mathbf{x}, \boldsymbol{\xi}) \right]",
        ))

    # ----- 随机变量定义 -----
    formulas.append((
        "随机变量定义",
        r"\boldsymbol{\xi} = (\xi_1, \xi_2, \ldots, \xi_K)^{\top}, "
        r"\quad \xi_k \sim F_k(\cdot), \; k = 1, \ldots, K",
    ))

    # ----- 机会约束 -----
    formulas.append((
        "机会约束",
        rf"P\left( g_i(\mathbf{{x}}, \boldsymbol{{\xi}}) \leq 0 \right) "
        rf"\geq 1 - \alpha, \quad \alpha = {alpha}, \; i = 1, \ldots, m",
    ))

    # ----- 用户自定义约束 -----
    math_constraints = [c for c in constraints if _is_mathematical_constraint(c)]
    existing_formulas = {f for _, f in formulas}
    for c in math_constraints[:3]:
        c_latex = _unicode_to_latex(c)
        if c_latex and c_latex not in existing_formulas:
            existing_formulas.add(c_latex)
            formulas.append(("确定性约束条件", c_latex))

    # ----- 非负约束 -----
    nonneg = r"\mathbf{x} \geq \mathbf{0}"
    has_nonneg = any("geq 0" in f or "\\geq 0" in f or "geq \\mathbf{0}" in f
                     for _, f in formulas)
    if not has_nonneg:
        formulas.append(("非负约束", nonneg))

    # ----- CVaR 风险度量 -----
    formulas.append((
        "条件风险价值 CVaR",
        rf"\text{{CVaR}}_{{\alpha}}(Z) = \frac{{1}}{{\alpha}} "
        rf"\int_{{0}}^{{\alpha}} \text{{VaR}}_{{\tau}}(Z) \, d\tau, "
        rf"\quad \alpha = {alpha}",
    ))

    return formulas


def _build_evaluation_formulas() -> list[tuple[str, str]]:
    """构建评价类（熵权法 + TOPSIS）公式。"""
    formulas: list[tuple[str, str]] = []
    formulas.append((
        "数据标准化",
        r"z_{ij} = \frac{r_{ij} - \min_i r_{ij}}{\max_i r_{ij} - \min_i r_{ij}}, "
        r"\quad p_{ij} = \frac{r_{ij}}{\sum_{i=1}^{n} r_{ij}}",
    ))
    formulas.append((
        "熵值计算",
        r"E_j = -\frac{1}{\ln n} \sum_{i=1}^{n} p_{ij} \ln p_{ij}, "
        r"\quad E_j \in [0, 1]",
    ))
    formulas.append((
        "权重计算",
        r"w_j = \frac{1 - E_j}{\sum_{k=1}^{m} (1 - E_k)}, "
        r"\quad \sum_{j=1}^{m} w_j = 1, \; w_j \geq 0",
    ))
    formulas.append((
        "正理想解与负理想解",
        r"z_j^{+} = \max_i z_{ij}, \quad "
        r"z_j^{-} = \min_i z_{ij}",
    ))
    formulas.append((
        "TOPSIS 贴近度",
        r"C_i = \frac{D_i^{-}}{D_i^{+} + D_i^{-}}, \quad "
        r"D_i^{+} = \sqrt{\sum_{j=1}^{m} w_j \left( z_{ij} - z_j^{+} \right)^2}, \quad "
        r"D_i^{-} = \sqrt{\sum_{j=1}^{m} w_j \left( z_{ij} - z_j^{-} \right)^2}",
    ))
    return formulas


def _build_prediction_formulas(
    problem_context: dict | None,
) -> list[tuple[str, str]]:
    """构建预测/回归类公式（根据具体方法选择对应公式集）。

    当方法为 ARIMA 时生成时间序列公式；当方法为灰色预测时生成
    GM(1,1) 公式；否则生成多元线性回归公式。
    """
    method = ""
    if problem_context:
        method = str(problem_context.get("method", "")).lower()

    # ARIMA 时间序列预测公式
    if "arima" in method:
        return _build_arima_formulas()

    # 灰色预测 GM(1,1) 公式
    if "灰色" in method or "gm" in method:
        return _build_gm_formulas()

    # 默认：多元线性回归公式
    return _build_regression_formulas(problem_context)


def _build_arima_formulas() -> list[tuple[str, str]]:
    """构建 ARIMA 模型公式。"""
    formulas: list[tuple[str, str]] = []
    formulas.append((
        "ARIMA 模型一般形式",
        r"\Phi(B) \, (1 - B)^d \, y_t = \Theta(B) \, \varepsilon_t, "
        r"\quad \varepsilon_t \sim \text{WN}(0, \sigma^2)",
    ))
    formulas.append((
        "自回归多项式",
        r"\Phi(B) = 1 - \phi_1 B - \phi_2 B^2 - \cdots - \phi_p B^p",
    ))
    formulas.append((
        "移动平均多项式",
        r"\Theta(B) = 1 + \theta_1 B + \theta_2 B^2 + \cdots + \theta_q B^q",
    ))
    formulas.append((
        "差分操作",
        r"\nabla^d y_t = (1 - B)^d \, y_t, \quad "
        r"B^k y_t = y_{t-k}",
    ))
    formulas.append((
        "平稳性条件",
        r"\Phi(z) = 0 \implies |z| > 1, \quad "
        r"\Theta(z) = 0 \implies |z| > 1",
    ))
    formulas.append((
        "AIC 定阶准则",
        r"\text{AIC} = -2 \ln L(\hat{\boldsymbol{\theta}}) + 2(p + q + d), "
        r"\quad \text{BIC} = -2 \ln L(\hat{\boldsymbol{\theta}}) + (p + q + d) \ln n",
    ))
    formulas.append((
        "Ljung-Box 残差检验",
        r"Q = n(n+2) \sum_{k=1}^{K} \frac{\hat{\rho}_k^2}{n - k} "
        r"\sim \chi^2(K - p - q)",
    ))
    return formulas


def _build_gm_formulas() -> list[tuple[str, str]]:
    """构建灰色预测 GM(1,1) 模型公式。"""
    formulas: list[tuple[str, str]] = []
    formulas.append((
        "一次累加生成（AGO）",
        r"X^{(1)}(k) = \sum_{i=1}^{k} X^{(0)}(i), \quad k = 1, 2, \ldots, n",
    ))
    formulas.append((
        "GM(1,1) 白化方程",
        r"\frac{dX^{(1)}}{dt} + a \, X^{(1)} = b, \quad "
        r"-a \text{ 为发展系数}, \; b \text{ 为灰作用量}",
    ))
    formulas.append((
        "参数最小二乘估计",
        r"\hat{\mathbf{a}} = \left[ a, \, b \right]^{\top} "
        r"= \left( \mathbf{B}^{\top} \mathbf{B} \right)^{-1} \mathbf{B}^{\top} \mathbf{Y}",
    ))
    formulas.append((
        "矩阵 B 与向量 Y",
        r"\mathbf{B} = \begin{bmatrix} -\frac{1}{2}(X^{(1)}(1) + X^{(1)}(2)) & 1 \\ "
        r"\vdots & \vdots \\ -\frac{1}{2}(X^{(1)}(n-1) + X^{(1)}(n)) & 1 \end{bmatrix}, "
        r"\quad \mathbf{Y} = \begin{bmatrix} X^{(0)}(2) \\ \vdots \\ X^{(0)}(n) \end{bmatrix}",
    ))
    formulas.append((
        "时间响应函数",
        r"\hat{X}^{(1)}(k+1) = \left( X^{(0)}(1) - \frac{b}{a} \right) e^{-ak} + \frac{b}{a}",
    ))
    formulas.append((
        "还原预测值（IAGO）",
        r"\hat{X}^{(0)}(k+1) = \hat{X}^{(1)}(k+1) - \hat{X}^{(1)}(k)",
    ))
    formulas.append((
        "后验差检验",
        r"C = \frac{S_1}{S_0}, \quad P = P\left\{ |\Delta^{(0)}(k) - \bar{\Delta}| < 0.6745 \, S_0 \right\}",
    ))
    return formulas


def _build_regression_formulas(
    problem_context: dict | None,
) -> list[tuple[str, str]]:
    """构建多元线性回归公式。

    包含多元线性回归模型、最小二乘估计的矩阵形式、决定系数、
    调整决定系数、F 检验统计量以及预测置信区间。
    """
    formulas: list[tuple[str, str]] = []
    # 推断特征数 p（默认使用通用占位）
    p = "p"
    if problem_context and isinstance(problem_context.get("n_features"), int):
        p = str(problem_context["n_features"])

    formulas.append((
        "多元线性回归模型",
        rf"y_i = \beta_0 + \sum_{{j=1}}^{{{p}}} \beta_j x_{{ij}} + \varepsilon_i, "
        rf"\quad \varepsilon_i \sim \mathcal{{N}}(0, \sigma^2)",
    ))
    formulas.append((
        "回归模型矩阵形式",
        r"\mathbf{y} = \mathbf{X} \boldsymbol{\beta} + \boldsymbol{\varepsilon}, "
        r"\quad \mathbf{X} \in \mathbb{R}^{n \times (p+1)}",
    ))
    formulas.append((
        "最小二乘估计",
        r"\hat{\boldsymbol{\beta}} = "
        r"\left( \mathbf{X}^{\top} \mathbf{X} \right)^{-1} \mathbf{X}^{\top} \mathbf{y} = "
        r"\arg\min_{\boldsymbol{\beta}} \sum_{i=1}^{n} \left( y_i - \hat{y}_i \right)^2",
    ))
    formulas.append((
        "决定系数 R²",
        r"R^2 = 1 - \frac{\sum_{i=1}^{n} \left( y_i - \hat{y}_i \right)^2}"
        r"{\sum_{i=1}^{n} \left( y_i - \bar{y} \right)^2} = "
        r"\frac{\text{SSR}}{\text{SST}}",
    ))
    formulas.append((
        "调整决定系数",
        r"R_{\text{adj}}^2 = 1 - \frac{n - 1}{n - p - 1} \left( 1 - R^2 \right)",
    ))
    formulas.append((
        "F 检验统计量",
        r"F = \frac{\text{SSR} / p}{\text{SSE} / (n - p - 1)} "
        r"\sim F(p, \, n - p - 1)",
    ))
    formulas.append((
        "预测值与置信区间",
        r"\hat{y}_0 = \mathbf{x}_0^{\top} \hat{\boldsymbol{\beta}}, \quad "
        r"\text{CI}_{1-\alpha} = \left[ \hat{y}_0 \pm "
        r"t_{\alpha/2}(n-p-1) \cdot \hat{\sigma} "
        r"\sqrt{1 + \mathbf{x}_0^{\top} \left( \mathbf{X}^{\top} \mathbf{X} \right)^{-1} \mathbf{x}_0} \right]",
    ))
    return formulas


def _build_simulation_formulas(
    problem_context: dict | None,
) -> list[tuple[str, str]]:
    """构建仿真/蒙特卡洛类公式。

    包含蒙特卡洛估计量、大数定律收敛性、中心极限定理以及
    基于 t 分布的置信区间构造。
    """
    formulas: list[tuple[str, str]] = []
    # 默认置信水平
    alpha = 0.05
    if problem_context and isinstance(problem_context.get("alpha"), (int, float)):
        alpha = float(problem_context["alpha"])

    formulas.append((
        "蒙特卡洛估计量",
        r"\hat{\theta}_N = \frac{1}{N} \sum_{s=1}^{N} g\!\left( \mathbf{x}^{(s)} \right), "
        r"\quad \mathbf{x}^{(s)} \stackrel{\text{i.i.d.}}{\sim} F(\cdot)",
    ))
    formulas.append((
        "大数定律（收敛性）",
        r"\hat{\theta}_N \xrightarrow{\;P\;} \theta = E\!\left[ g(\mathbf{x}) \right], "
        r"\quad N \to \infty",
    ))
    formulas.append((
        "中心极限定理",
        r"\sqrt{N} \left( \hat{\theta}_N - \theta \right) "
        r"\xrightarrow{\;d\;} \mathcal{N}\!\left( 0, \, \sigma_g^2 \right), "
        r"\quad \sigma_g^2 = \text{Var}\!\left[ g(\mathbf{x}) \right]",
    ))
    formulas.append((
        "样本标准误",
        r"\hat{\sigma}_g = \sqrt{\frac{1}{N - 1} "
        r"\sum_{s=1}^{N} \left( g\!\left( \mathbf{x}^{(s)} \right) - \hat{\theta}_N \right)^2}, "
        r"\quad \text{SE} = \frac{\hat{\sigma}_g}{\sqrt{N}}",
    ))
    formulas.append((
        rf"{1 - alpha:.0%} 置信区间",
        rf"\left[ \hat{{\theta}}_N - t_{{\alpha/2}}(N-1) \cdot \frac{{\hat{{\sigma}}_g}}{{\sqrt{{N}}}}, "
        rf"\; \hat{{\theta}}_N + t_{{\alpha/2}}(N-1) \cdot \frac{{\hat{{\sigma}}_g}}{{\sqrt{{N}}}} \right]",
    ))
    return formulas


def format_formula_with_number(formula: str, number: int) -> str:
    """在公式右侧添加编号，生成 MathType 风格的带编号公式。

    使用 ``\\tag{n}`` 在公式右侧标注编号，适用于 LaTeX 行间公式
    （被 ``$$ ... $$`` 包裹后即可在 Word/MathType 中正确渲染）。

    Args:
        formula: 纯 LaTeX 公式字符串（不含 ``$$`` 或 ``\\[\\]``）。
        number: 公式编号（正整数）。

    Returns:
        带编号的纯 LaTeX 公式字符串（不含 ``$$``），形如
        ``formula \\tag{number}``。
    """
    formula = formula.strip()
    number = int(number)
    # 若已包含 \tag 则先移除避免重复编号
    if r"\tag{" in formula:
        import re

        formula = re.sub(r"\\tag\{\d+\}", "", formula).strip()
    return f"{formula} \\tag{{{number}}}"


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
