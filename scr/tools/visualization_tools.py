"""可视化工具 — 基于 matplotlib 生成论文图表。

确定性工具，不依赖 LLM，可单测、可复现。

功能：
  1. 优化问题结果可视化（最优解柱状图、资源分配饼图）
  2. 蒙特卡洛模拟结果可视化（分布直方图、收敛曲线）
  3. 多问对比可视化（目标值对比、方案差异雷达图）
  4. 数据画像可视化（字段分布、缺失率热力图）

所有图表保存为 PNG 文件，返回文件路径列表。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

# matplotlib 后端设置为 Agg（非交互式），避免线程问题
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# 中文字体设置
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "WenQuanYi Micro Hei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 150
plt.rcParams["savefig.dpi"] = 150
plt.rcParams["savefig.bbox"] = "tight"

__all__ = [
    "generate_optimization_chart",
    "generate_monte_carlo_chart",
    "generate_prediction_chart",
    "generate_comparison_chart",
    "generate_data_profile_chart",
    "generate_all_figures",
]


def _ensure_dir(path: str | Path) -> Path:
    """确保目录存在。"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _save_fig(fig: plt.Figure, output_dir: str, filename: str) -> str:
    """保存图表并关闭。"""
    _ensure_dir(output_dir)
    filepath = Path(output_dir) / filename
    fig.savefig(str(filepath), format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(filepath)


# ---------------------------------------------------------------------------
# 1. 优化问题结果可视化
# ---------------------------------------------------------------------------


def generate_optimization_chart(
    computation: dict[str, Any],
    qid: str,
    output_dir: str,
) -> list[str]:
    """为优化问题生成可视化图表。

    生成：
      - 最优解柱状图（各决策变量取值）
      - 资源分配饼图（非零变量的占比）

    Args:
        computation: 计算结果字典。
        qid: 小问 ID。
        output_dir: 输出目录。

    Returns:
        生成的图表文件路径列表。
    """
    figures: list[str] = []
    results = computation.get("results", {})
    solution = results.get("optimal_solution", [])
    objective = results.get("optimal_objective", 0)

    if not solution:
        return figures

    # 图 1: 最优解柱状图
    fig, ax = plt.subplots(figsize=(10, 5))
    colors = ["#2196F3" if v > 0 else "#E0E0E0" for v in solution]
    x_labels = [f"x{i+1}" for i in range(len(solution))]
    bars = ax.bar(range(len(solution)), solution, color=colors, edgecolor="white", linewidth=0.5)

    ax.set_xlabel("决策变量", fontsize=11)
    ax.set_ylabel("取值", fontsize=11)
    ax.set_title(f"问题 {qid}：最优解分布（目标值 = {objective:.2f}）", fontsize=13)
    ax.set_xticks(range(len(solution)))
    ax.set_xticklabels(x_labels, rotation=45, ha="right", fontsize=8)
    ax.axhline(y=0, color="gray", linewidth=0.5, linestyle="--")

    # 标注非零值
    for bar, val in zip(bars, solution):
        if val > 0.01:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.5,
                f"{val:.1f}",
                ha="center", va="bottom", fontsize=7, color="#333",
            )

    plt.tight_layout()
    figures.append(_save_fig(fig, output_dir, f"{qid}_solution_bar.png"))

    # 图 2: 资源分配饼图（仅非零变量）
    nonzero = [(i, v) for i, v in enumerate(solution) if v > 0.01]
    if len(nonzero) > 1:
        fig, ax = plt.subplots(figsize=(7, 7))
        labels = [f"x{i+1} ({v:.1f})" for i, v in nonzero]
        sizes = [v for _, v in nonzero]
        colors_pie = plt.cm.Set3(np.linspace(0, 1, len(nonzero)))

        wedges, texts, autotexts = ax.pie(
            sizes, labels=labels, autopct="%1.1f%%",
            colors=colors_pie, startangle=90,
            textprops={"fontsize": 9},
        )
        ax.set_title(f"问题 {qid}：非零决策变量分配占比", fontsize=13)

        plt.tight_layout()
        figures.append(_save_fig(fig, output_dir, f"{qid}_allocation_pie.png"))

    return figures


# ---------------------------------------------------------------------------
# 2. 蒙特卡洛模拟结果可视化
# ---------------------------------------------------------------------------


def generate_monte_carlo_chart(
    computation: dict[str, Any],
    qid: str,
    output_dir: str,
) -> list[str]:
    """为蒙特卡洛模拟生成可视化图表。

    生成：
      - 模拟结果分布直方图
      - 置信区间可视化

    Args:
        computation: 计算结果字典。
        qid: 小问 ID。
        output_dir: 输出目录。

    Returns:
        生成的图表文件路径列表。
    """
    figures: list[str] = []
    results = computation.get("results", {})
    intermediate = computation.get("intermediate_values", {})
    metrics = computation.get("metrics", {})

    # 图 1: 模拟结果分布直方图
    simulated_values = None
    if "simulation" in results:
        sim = results["simulation"]
        if "simulated_means" in sim:
            simulated_values = sim["simulated_means"]
    elif "scenario_objectives" in intermediate:
        simulated_values = intermediate["scenario_objectives"]

    if simulated_values and len(simulated_values) > 0:
        values = np.array(simulated_values, dtype=float)

        fig, ax = plt.subplots(figsize=(9, 5))
        n_bins = min(30, max(10, len(values) // 5))
        ax.hist(values, bins=n_bins, color="#4CAF50", edgecolor="white",
                alpha=0.7, density=True)

        # 叠加正态分布曲线
        mean_val = values.mean()
        std_val = values.std()
        if std_val > 0:
            x_range = np.linspace(values.min(), values.max(), 100)
            from scipy.stats import norm
            try:
                y_pdf = norm.pdf(x_range, mean_val, std_val)
                ax.plot(x_range, y_pdf, "r-", linewidth=2, label=f"N({mean_val:.2f}, {std_val:.2f})")
            except Exception:
                pass

        ax.axvline(mean_val, color="red", linestyle="--", linewidth=1.5, label=f"均值 = {mean_val:.2f}")
        ax.set_xlabel("模拟目标值", fontsize=11)
        ax.set_ylabel("概率密度", fontsize=11)
        ax.set_title(f"问题 {qid}：蒙特卡洛模拟结果分布", fontsize=13)
        ax.legend(fontsize=9)

        plt.tight_layout()
        figures.append(_save_fig(fig, output_dir, f"{qid}_mc_distribution.png"))

    # 图 2: 置信区间可视化
    if "simulation" in results:
        sim = results["simulation"]
        ci = sim.get("confidence_interval_90", {})
        if ci:
            sim_means = sim.get("simulated_means", [])
            if isinstance(sim_means, list) and len(sim_means) > 0:
                fig, ax = plt.subplots(figsize=(8, 5))
                n_features = len(sim_means)
                means = np.array(sim_means)
                lower = np.array(ci.get("lower", [0] * n_features))
                upper = np.array(ci.get("upper", [0] * n_features))

                x_pos = range(n_features)
                ax.errorbar(
                    x_pos, means,
                    yerr=[means - lower, upper - means],
                    fmt="o", color="#2196F3", capsize=5, capthick=2,
                    markersize=8, linewidth=2,
                )
                ax.fill_between(x_pos, lower, upper, alpha=0.2, color="#2196F3")
                ax.set_xlabel("变量", fontsize=11)
                ax.set_ylabel("取值", fontsize=11)
                ax.set_title(f"问题 {qid}：90% 置信区间", fontsize=13)
                ax.set_xticks(x_pos)
                ax.set_xticklabels([f"变量{i+1}" for i in x_pos])
                ax.axhline(y=0, color="gray", linewidth=0.5, linestyle="--")

                plt.tight_layout()
                figures.append(_save_fig(fig, output_dir, f"{qid}_confidence_interval.png"))

    # 图 3: 随机优化场景目标值
    if "scenario_objectives" in intermediate:
        scenario_objs = intermediate["scenario_objectives"]
        if len(scenario_objs) > 5:
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.plot(range(len(scenario_objs)), scenario_objs,
                    color="#FF9800", alpha=0.7, linewidth=1)
            ax.axhline(y=np.mean(scenario_objs), color="red", linestyle="--",
                       linewidth=1.5, label=f"期望值 = {np.mean(scenario_objs):.2f}")
            ax.fill_between(
                range(len(scenario_objs)),
                np.min(scenario_objs), np.max(scenario_objs),
                alpha=0.1, color="#FF9800",
            )
            ax.set_xlabel("场景编号", fontsize=11)
            ax.set_ylabel("目标值", fontsize=11)
            ax.set_title(f"问题 {qid}：各场景最优目标值", fontsize=13)
            ax.legend(fontsize=9)

            plt.tight_layout()
            figures.append(_save_fig(fig, output_dir, f"{qid}_scenario_objectives.png"))

    return figures


# ---------------------------------------------------------------------------
# 3. 预测/回归结果可视化
# ---------------------------------------------------------------------------


def generate_prediction_chart(
    computation: dict[str, Any],
    qid: str,
    output_dir: str,
) -> list[str]:
    """为预测/回归问题生成可视化图表。

    生成：
      - 实际值 vs 预测值散点图（含对角参考线）
      - 残差分析图（残差 vs 拟合值）

    Args:
        computation: 计算结果字典。
        qid: 小问 ID。
        output_dir: 输出目录。

    Returns:
        生成的图表文件路径列表。
    """
    figures: list[str] = []
    results = computation.get("results", {})
    metrics = computation.get("metrics", {})

    # 提取预测值和真实值
    predictions = results.get("predictions", [])
    true_values = results.get("true_values", [])
    residuals = results.get("residuals", [])
    fitted_values = results.get("fitted_values", [])

    # 如果没有预测值，尝试从 intermediate_values 获取
    if not predictions:
        intermediate = computation.get("intermediate_values", {})
        predictions = intermediate.get("predictions", [])
        true_values = intermediate.get("true_values", [])
        residuals = intermediate.get("residuals", [])
        fitted_values = intermediate.get("fitted_values", [])

    # 回归模型中 fitted_values 即为预测值
    if not predictions and fitted_values:
        predictions = fitted_values

    # 如果有残差和预测值，可以反推真实值: true = pred + residual
    if not true_values and predictions and residuals and len(predictions) == len(residuals):
        true_values = [p + r for p, r in zip(predictions, residuals)]

    # 如果有残差但没有 fitted_values，用 predictions 作为 fitted_values
    if not fitted_values and predictions:
        fitted_values = predictions

    # 图 1: 实际值 vs 预测值散点图
    if predictions and true_values and len(predictions) == len(true_values):
        y_true = np.array(true_values, dtype=float)
        y_pred = np.array(predictions, dtype=float)

        fig, ax = plt.subplots(figsize=(7, 7))

        # 散点
        ax.scatter(y_true, y_pred, color="#2196F3", alpha=0.6,
                   edgecolors="white", linewidth=0.5, s=50)

        # 对角参考线
        min_val = min(y_true.min(), y_pred.min())
        max_val = max(y_true.max(), y_pred.max())
        margin = (max_val - min_val) * 0.05
        ax.plot([min_val - margin, max_val + margin],
                [min_val - margin, max_val + margin],
                "r--", linewidth=1.5, label="完美预测线 (y=x)")

        # 回归线
        if len(y_true) > 2:
            try:
                z = np.polyfit(y_true, y_pred, 1)
                p = np.poly1d(z)
                x_fit = np.linspace(min_val, max_val, 100)
                ax.plot(x_fit, p(x_fit), "g-", linewidth=1.5, alpha=0.7,
                        label=f"回归线 (斜率={z[0]:.3f})")
            except Exception:
                pass

        # R² 标注
        r2 = metrics.get("r_squared")
        rmse = metrics.get("rmse")
        text_parts = []
        if r2 is not None:
            text_parts.append(f"$R^2$ = {r2:.4f}")
        if rmse is not None:
            text_parts.append(f"RMSE = {rmse:.4f}")
        if text_parts:
            ax.text(0.05, 0.95, "  ".join(text_parts),
                    transform=ax.transAxes, fontsize=11,
                    verticalalignment="top",
                    bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.8))

        ax.set_xlabel("实际值", fontsize=11)
        ax.set_ylabel("预测值", fontsize=11)
        ax.set_title(f"问题 {qid}：实际值 vs 预测值", fontsize=13)
        ax.legend(fontsize=9, loc="lower right")
        ax.set_xlim(min_val - margin, max_val + margin)
        ax.set_ylim(min_val - margin, max_val + margin)
        ax.set_aspect("equal")
        ax.grid(alpha=0.3)

        plt.tight_layout()
        figures.append(_save_fig(fig, output_dir, f"{qid}_pred_vs_actual.png"))

    # 图 2: 残差分析图
    if residuals and fitted_values and len(residuals) == len(fitted_values):
        res = np.array(residuals, dtype=float)
        fitted = np.array(fitted_values, dtype=float)

        fig, ax = plt.subplots(figsize=(8, 5))

        ax.scatter(fitted, res, color="#4CAF50", alpha=0.6,
                   edgecolors="white", linewidth=0.5, s=40)

        # 零参考线
        ax.axhline(y=0, color="red", linestyle="--", linewidth=1.5)

        # 残差均值标注
        res_mean = res.mean()
        ax.axhline(y=res_mean, color="blue", linestyle=":", linewidth=1,
                   label=f"残差均值 = {res_mean:.2e}")

        ax.set_xlabel("拟合值", fontsize=11)
        ax.set_ylabel("残差", fontsize=11)
        ax.set_title(f"问题 {qid}：残差分析", fontsize=13)
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)

        plt.tight_layout()
        figures.append(_save_fig(fig, output_dir, f"{qid}_residual_plot.png"))

    return figures


# ---------------------------------------------------------------------------
# 4. 多问对比可视化
# ---------------------------------------------------------------------------


def generate_comparison_chart(
    question_results: dict[str, Any],
    output_dir: str,
) -> list[str]:
    """生成多问对比图表。

    生成：
      - 各问目标值对比柱状图
      - 各问方法对比表格图

    Args:
        question_results: 所有小问结果 {qid: QuestionResult}。
        output_dir: 输出目录。

    Returns:
        生成的图表文件路径列表。
    """
    figures: list[str] = []

    # 收集各问目标值
    qids = sorted(question_results.keys())
    objectives = []
    labels = []

    for qid in qids:
        result = question_results[qid]
        computation = result.computation if hasattr(result, "computation") else result.get("computation", {})
        results = computation.get("results", {})
        obj = results.get("optimal_objective", results.get("expected_objective", None))
        if obj is not None:
            objectives.append(float(obj))
            labels.append(qid)

    if len(objectives) >= 2:
        # 图 1: 目标值对比柱状图
        fig, ax = plt.subplots(figsize=(8, 5))
        colors = plt.cm.viridis(np.linspace(0.2, 0.8, len(objectives)))
        bars = ax.bar(labels, objectives, color=colors, edgecolor="white", width=0.5)

        for bar, val in zip(bars, objectives):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(objectives) * 0.01,
                f"{val:.2f}",
                ha="center", va="bottom", fontsize=10, fontweight="bold",
            )

        ax.set_xlabel("问题编号", fontsize=11)
        ax.set_ylabel("目标值", fontsize=11)
        ax.set_title("各子问题最优目标值对比", fontsize=13)
        ax.grid(axis="y", alpha=0.3)

        plt.tight_layout()
        figures.append(_save_fig(fig, output_dir, "comparison_objectives.png"))

    # 图 2: 随机优化 vs 确定性优化对比
    if len(qids) >= 3:
        deterministic_objs = []
        stochastic_objs = []
        for qid in qids:
            result = question_results[qid]
            computation = result.computation if hasattr(result, "computation") else result.get("computation", {})
            results = computation.get("results", {})
            metrics = computation.get("metrics", {})

            baseline = results.get("baseline_objective", metrics.get("baseline_objective"))
            expected = results.get("expected_objective", metrics.get("expected_objective"))

            if baseline is not None and expected is not None:
                deterministic_objs.append(float(baseline))
                stochastic_objs.append(float(expected))

        if deterministic_objs and stochastic_objs:
            fig, ax = plt.subplots(figsize=(8, 5))
            x = range(len(deterministic_objs))
            width = 0.35
            ax.bar([i - width/2 for i in x], deterministic_objs, width,
                   label="确定性最优", color="#2196F3", edgecolor="white")
            ax.bar([i + width/2 for i in x], stochastic_objs, width,
                   label="期望最优（含不确定性）", color="#FF9800", edgecolor="white")
            ax.set_xlabel("场景", fontsize=11)
            ax.set_ylabel("目标值", fontsize=11)
            ax.set_title("确定性 vs 不确定性优化对比", fontsize=13)
            ax.legend(fontsize=10)
            ax.set_xticks(x)

            plt.tight_layout()
            figures.append(_save_fig(fig, output_dir, "deterministic_vs_stochastic.png"))

    return figures


# ---------------------------------------------------------------------------
# 4. 数据画像可视化
# ---------------------------------------------------------------------------


def generate_data_profile_chart(
    data_profile: Any,
    output_dir: str,
) -> list[str]:
    """为数据画像生成可视化图表。

    生成：
      - 各表行列数对比图
      - 字段缺失率柱状图

    Args:
        data_profile: DataProfile 对象。
        output_dir: 输出目录。

    Returns:
        生成的图表文件路径列表。
    """
    figures: list[str] = []

    if data_profile is None or not hasattr(data_profile, "tables"):
        return figures

    # 图 1: 各表行列数
    tables = data_profile.tables
    if tables:
        fig, ax = plt.subplots(figsize=(8, 5))
        names = [f"{t.source_file}\n({t.sheet_name})" for t in tables]
        rows = [t.n_rows for t in tables]
        cols = [t.n_cols for t in tables]

        x = range(len(tables))
        width = 0.35
        ax.bar([i - width/2 for i in x], rows, width, label="行数", color="#2196F3")
        ax.bar([i + width/2 for i in x], cols, width, label="列数", color="#FF9800")
        ax.set_xlabel("数据表", fontsize=11)
        ax.set_ylabel("数量", fontsize=11)
        ax.set_title("各数据表规模", fontsize=13)
        ax.legend(fontsize=10)
        ax.set_xticks(x)
        ax.set_xticklabels(names, fontsize=8, rotation=15, ha="right")

        plt.tight_layout()
        figures.append(_save_fig(fig, output_dir, "data_table_sizes.png"))

    # 图 2: 字段缺失率
    fields = data_profile.fields if hasattr(data_profile, "fields") else []
    if fields:
        high_missing = [(f.field_name, f.missing_rate) for f in fields if f.missing_rate > 0.05]
        if high_missing:
            high_missing.sort(key=lambda x: x[1], reverse=True)
            fig, ax = plt.subplots(figsize=(9, 5))
            names = [m[0][:15] for m in high_missing[:15]]
            rates = [m[1] * 100 for m in high_missing[:15]]
            colors = ["#F44336" if r > 50 else "#FF9800" if r > 10 else "#4CAF50" for r in rates]

            ax.barh(names, rates, color=colors, edgecolor="white")
            ax.set_xlabel("缺失率 (%)", fontsize=11)
            ax.set_title("字段缺失率（仅显示 > 5%）", fontsize=13)
            ax.grid(axis="x", alpha=0.3)

            plt.tight_layout()
            figures.append(_save_fig(fig, output_dir, "field_missing_rates.png"))

    return figures


# ---------------------------------------------------------------------------
# 5. 统一入口：根据题型自动选择图表
# ---------------------------------------------------------------------------


def generate_all_figures(
    question_results: dict[str, Any],
    data_profile: Any | None,
    output_dir: str,
) -> dict[str, list[str]]:
    """为所有小问和数据画像生成图表。

    Args:
        question_results: 所有小问结果。
        data_profile: 数据画像。
        output_dir: 图表输出目录。

    Returns:
        {qid: [图文件路径列表]} 的映射，特殊键 "data_profile" 和 "comparison"。
    """
    all_figures: dict[str, list[str]] = {}
    fig_dir = Path(output_dir) / "figures"
    _ensure_dir(fig_dir)

    # 数据画像图表
    if data_profile is not None:
        dp_figs = generate_data_profile_chart(data_profile, str(fig_dir))
        if dp_figs:
            all_figures["data_profile"] = dp_figs

    # 各小问图表
    for qid, result in question_results.items():
        computation = result.computation if hasattr(result, "computation") else result.get("computation", {})
        interp = result.problem_interpretation if hasattr(result, "problem_interpretation") else result.get("problem_interpretation", None)
        math_task = interp.math_task if interp else "composite"

        if math_task in ("optimization", "stochastic_optimization"):
            figs = generate_optimization_chart(computation, qid, str(fig_dir))
            if math_task == "stochastic_optimization":
                figs.extend(generate_monte_carlo_chart(computation, qid, str(fig_dir)))
        elif math_task == "simulation":
            figs = generate_monte_carlo_chart(computation, qid, str(fig_dir))
        elif math_task == "prediction":
            figs = generate_prediction_chart(computation, qid, str(fig_dir))
        elif math_task == "evaluation":
            # 评价类也可以用柱状图
            figs = generate_optimization_chart(computation, qid, str(fig_dir))
        else:
            figs = generate_optimization_chart(computation, qid, str(fig_dir))

        if figs:
            all_figures[qid] = figs

    # 对比图表
    if len(question_results) >= 2:
        comp_figs = generate_comparison_chart(question_results, str(fig_dir))
        if comp_figs:
            all_figures["comparison"] = comp_figs

    return all_figures
