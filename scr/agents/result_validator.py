"""结果验证器 Agent（Phase 5 实现）。

对应 architecture.md §5.6 结果验证与迭代。

职责：
  1. 按题型组合检查项，对 ``QuestionResult.computation`` 做确定性验证
  2. 通用检查：计算状态、结果完整性、指标合理性、可复现性、产物与假设
  3. 题型专项检查：
     - 评价/排序 (evaluation)：指标方向、权重和、排名完整性、排名稳定性（权重扰动）
     - 预测/回归 (prediction)：R²、残差分布、基线比较、时间泄漏检查
     - 优化/规划 (optimization)：约束可行性、目标值、边界情形、参数扰动
     - 分类/聚类 (classification/clustering)：指标、样本划分、稳定性
     - 仿真/机理 (simulation/mechanism)：量纲、边界条件、重复试验、参数敏感性
  4. 生成验证报告（status/checks/narrative/risks）与结果叙述

设计要点：
  - 确定性验证：仅用 numpy 做数值与逻辑检查，不依赖 LLM
  - 优雅降级：缺数据时记录风险而非崩溃
  - 权重扰动：对权重加 ±10% 噪声后重算排名，检查 top-3 是否稳定
  - 预算友好：验证迭代预算由 GQ 门控制（§5.6），本验证器只产出报告

通用检查（architecture.md §5.6）还包括：单位和量级是否合理、数据是否泄漏、
结论是否超出模型能力、是否满足任务所有约束、结果能否复跑。
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..schemas.question import QuestionResult


__all__ = ["ResultValidator", "validate_result_node"]


# 检查严重级别
_SEV_INFO = "info"
_SEV_WARNING = "warning"
_SEV_ERROR = "error"

# 题型中文标签（用于叙述）
_TASK_LABELS: dict[str, str] = {
    "evaluation": "评价/排序",
    "prediction": "预测/回归",
    "optimization": "优化/规划",
    "stochastic_optimization": "随机/鲁棒优化",
    "classification": "分类",
    "clustering": "聚类",
    "simulation": "仿真/机理",
    "mechanism": "机理建模",
    "composite": "综合任务",
}

# 权重扰动试验次数与幅度
_PERTURB_TRIALS = 5
_PERTURB_AMP = 0.10


def _make_check(
    name: str,
    category: str,
    passed: bool,
    severity: str,
    detail: str,
) -> dict[str, Any]:
    """构造单条检查结果字典。"""
    return {
        "name": name,
        "category": category,
        "passed": passed,
        "severity": severity,
        "detail": detail,
    }


class ResultValidator:
    """结果验证器 Agent（Phase 5）。

    对 QuestionResult.computation 按题型执行确定性验证，产出验证报告
    与结果叙述，写入 ``QuestionResult.validation``。

    Args:
        llm: 可选的 LLM 客户端（当前确定性验证不使用，保留以兼容接口）。
    """

    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def validate(self, question_result: QuestionResult) -> dict[str, Any]:
        """对一个小问的结果执行题型匹配的验证。

        Args:
            question_result: status="validating" 的小问结果包。

        Returns:
            验证报告字典，包含：
              - status: "passed" / "warning" / "failed"
              - math_task: 题型
              - checks: 检查结果列表
              - narrative: 结果叙述文本
              - risks: 风险描述列表
              - summary: 检查统计
        """
        qid = question_result.question_id
        interp = question_result.problem_interpretation
        math_task = interp.math_task if interp else "composite"

        # 键名归一化：兼容 LLM 提示词契约（solution/objective/r2）与预设方法契约（幂等）
        if question_result.computation:
            from ..tools.result_keys import normalize_computation

            normalize_computation(question_result.computation)

        checks: list[dict[str, Any]] = []
        checks.extend(self._validate_general(question_result))

        if math_task == "evaluation":
            checks.extend(self._validate_evaluation(question_result))
        elif math_task == "prediction":
            checks.extend(self._validate_prediction(question_result))
        elif math_task in ("optimization", "stochastic_optimization"):
            checks.extend(self._validate_optimization(question_result))
            if math_task == "stochastic_optimization":
                checks.extend(self._validate_stochastic(question_result))
        else:
            checks.extend(self._validate_generic(question_result, math_task))

        # 综合判定状态
        has_error = any(
            (not c["passed"]) and c["severity"] == _SEV_ERROR for c in checks
        )
        has_warning = any(
            (not c["passed"]) and c["severity"] == _SEV_WARNING for c in checks
        )
        if has_error:
            status = "failed"
        elif has_warning:
            status = "warning"
        else:
            status = "passed"

        risks = [
            c["detail"]
            for c in checks
            if (not c["passed"]) and c["severity"] in (_SEV_WARNING, _SEV_ERROR)
        ]

        narrative = self._build_narrative(question_result, checks, risks, math_task)

        report: dict[str, Any] = {
            "status": status,
            "math_task": math_task,
            "checks": checks,
            "narrative": narrative,
            "risks": risks,
            "summary": {
                "total_checks": len(checks),
                "passed": sum(1 for c in checks if c["passed"]),
                "warnings": sum(
                    1 for c in checks
                    if (not c["passed"]) and c["severity"] == _SEV_WARNING
                ),
                "errors": sum(
                    1 for c in checks
                    if (not c["passed"]) and c["severity"] == _SEV_ERROR
                ),
            },
        }

        print(
            f"[validator] 小问 {qid} 验证完成: {status} "
            f"(task={math_task}, checks={len(checks)}, "
            f"errors={report['summary']['errors']}, "
            f"warnings={report['summary']['warnings']})"
        )

        return report

    # ------------------------------------------------------------------
    # 通用检查
    # ------------------------------------------------------------------

    def _validate_general(self, question_result: QuestionResult) -> list[dict[str, Any]]:
        """通用检查：计算状态、结果完整性、指标合理性、可复现性、产物与假设。"""
        checks: list[dict[str, Any]] = []
        computation = question_result.computation or {}
        status = computation.get("status", "unknown")
        results = computation.get("results", {})
        metrics = computation.get("metrics", {})
        method = computation.get("method", "未知方法")

        # 1. 计算状态
        if status == "success":
            checks.append(_make_check(
                "computation_status", "general", True, _SEV_INFO,
                f"计算成功完成（方法: {method}）",
            ))
        elif status == "generic_stats":
            checks.append(_make_check(
                "computation_status", "general", True, _SEV_INFO,
                f"执行通用描述统计（方法: {method}），非专项建模",
            ))
        elif status == "no_data":
            checks.append(_make_check(
                "computation_status", "general", False, _SEV_ERROR,
                "无可用数据，计算未执行，结果为占位",
            ))
        elif status == "insufficient_data":
            checks.append(_make_check(
                "computation_status", "general", False, _SEV_ERROR,
                "数据不足，无法完成完整计算",
            ))
        elif status == "error":
            err = computation.get("error", "")
            checks.append(_make_check(
                "computation_status", "general", False, _SEV_ERROR,
                f"计算出错: {err[:120]}",
            ))
        elif status == "stub":
            checks.append(_make_check(
                "computation_status", "general", False, _SEV_WARNING,
                f"方法 {method} 为占位实现，需具体问题建模后才能验证",
            ))
        else:
            checks.append(_make_check(
                "computation_status", "general", False, _SEV_WARNING,
                f"计算状态未知: {status}",
            ))

        # 2. 结果完整性
        if status in ("success", "generic_stats"):
            if results:
                checks.append(_make_check(
                    "result_completeness", "general", True, _SEV_INFO,
                    "计算结果非空",
                ))
            else:
                checks.append(_make_check(
                    "result_completeness", "general", False, _SEV_ERROR,
                    "计算状态为成功但 results 为空",
                ))
            if metrics:
                checks.append(_make_check(
                    "metrics_present", "general", True, _SEV_INFO,
                    "已记录计算指标",
                ))
            else:
                checks.append(_make_check(
                    "metrics_present", "general", False, _SEV_WARNING,
                    "缺少计算指标，难以评估结果质量",
                ))

        # 3. 指标合理性 —— 数值有限性
        bad_metrics = [
            k for k, v in metrics.items()
            if isinstance(v, float) and not np.isfinite(v)
        ]
        if bad_metrics:
            checks.append(_make_check(
                "metric_finiteness", "general", False, _SEV_ERROR,
                f"指标含非有限值（NaN/Inf）: {bad_metrics}",
            ))
        else:
            checks.append(_make_check(
                "metric_finiteness", "general", True, _SEV_INFO,
                "所有数值指标均为有限值",
            ))

        # 4. 可复现性 —— 方法记录
        if method and method != "未知方法":
            checks.append(_make_check(
                "reproducibility", "general", True, _SEV_INFO,
                "已记录方法名称，结果可复现",
            ))
        else:
            checks.append(_make_check(
                "reproducibility", "general", False, _SEV_WARNING,
                "未记录方法名称，可复现性存疑",
            ))

        # 5. 产物完整性 —— 图表/表格
        if status in ("success", "generic_stats"):
            n_fig = len(question_result.figures)
            n_tab = len(question_result.tables)
            if n_fig == 0 and n_tab == 0:
                checks.append(_make_check(
                    "artifacts", "general", False, _SEV_WARNING,
                    "成功计算但未生成图表或表格，建议补充可视化",
                ))
            else:
                checks.append(_make_check(
                    "artifacts", "general", True, _SEV_INFO,
                    f"已生成 {n_fig} 图、{n_tab} 表",
                ))

        # 6. 假设记录
        if question_result.assumptions:
            checks.append(_make_check(
                "assumptions_recorded", "general", True, _SEV_INFO,
                f"已记录 {len(question_result.assumptions)} 条假设",
            ))
        else:
            checks.append(_make_check(
                "assumptions_recorded", "general", False, _SEV_WARNING,
                "未记录建模假设",
            ))

        # 7. 结论是否超出模型能力 —— 形式检查
        findings = question_result.findings or {}
        if findings.get("has_numerical_results") is False and status == "success":
            checks.append(_make_check(
                "conclusion_within_capability", "general", False, _SEV_WARNING,
                "标记为成功但无数值结果，结论可能超出当前模型能力",
            ))
        else:
            checks.append(_make_check(
                "conclusion_within_capability", "general", True, _SEV_INFO,
                "结论与计算产出一致",
            ))

        return checks

    # ------------------------------------------------------------------
    # 评价/排序
    # ------------------------------------------------------------------

    def _validate_evaluation(
        self, question_result: QuestionResult,
    ) -> list[dict[str, Any]]:
        """评价类检查：指标方向、权重和、排名完整性、排名稳定性（权重扰动）。"""
        checks: list[dict[str, Any]] = []
        computation = question_result.computation or {}
        results = computation.get("results", {})
        metrics = computation.get("metrics", {})
        intermediate = computation.get("intermediate_values", {})

        weights = results.get("weights") or metrics.get("weights")

        # 1. 权重非负与归一化
        if weights:
            w = np.array(weights, dtype=float)
            w_sum = float(w.sum())
            if np.any(w < -1e-9):
                checks.append(_make_check(
                    "weights_nonnegative", "evaluation", False, _SEV_ERROR,
                    "存在负权重，不符合赋权定义",
                ))
            else:
                checks.append(_make_check(
                    "weights_nonnegative", "evaluation", True, _SEV_INFO,
                    "所有权重非负",
                ))
            if abs(w_sum - 1.0) < 1e-6:
                checks.append(_make_check(
                    "weights_sum", "evaluation", True, _SEV_INFO,
                    f"权重和为 1（sum={w_sum:.6f}）",
                ))
            else:
                checks.append(_make_check(
                    "weights_sum", "evaluation", False, _SEV_ERROR,
                    f"权重和不为 1（sum={w_sum:.6f}），违反归一化约束",
                ))
            # 权重过度集中
            if len(w) > 2 and float(w.max()) > 0.6:
                checks.append(_make_check(
                    "weights_concentration", "evaluation", False, _SEV_WARNING,
                    f"单一指标权重过大（max={float(w.max()):.3f}），"
                    f"结果对该指标高度敏感，需确认指标方向正确",
                ))
            else:
                checks.append(_make_check(
                    "weights_concentration", "evaluation", True, _SEV_INFO,
                    "权重分布相对均衡",
                ))
        else:
            checks.append(_make_check(
                "weights_present", "evaluation", False, _SEV_WARNING,
                "评价结果缺少权重信息，无法校验权重和",
            ))

        # 2. 排名完整性
        ranking = results.get("ranking")
        n_expected = metrics.get("n_samples")
        if ranking:
            if n_expected and len(ranking) != n_expected:
                checks.append(_make_check(
                    "ranking_completeness", "evaluation", False, _SEV_ERROR,
                    f"排名数量({len(ranking)})与样本数({n_expected})不符",
                ))
            else:
                checks.append(_make_check(
                    "ranking_completeness", "evaluation", True, _SEV_INFO,
                    f"排名完整（{len(ranking)} 个样本）",
                ))
        else:
            scores = results.get("scores") or results.get("closeness")
            if scores:
                checks.append(_make_check(
                    "ranking_present", "evaluation", False, _SEV_WARNING,
                    "有评分但未生成显式排名",
                ))

        # 3. 指标方向一致性 —— 通过信息熵判断区分度
        entropy_vals = intermediate.get("entropy_values")
        if entropy_vals:
            ent = np.array(entropy_vals, dtype=float)
            n_low = int(np.sum(ent < 0.1))
            if n_low > 0:
                checks.append(_make_check(
                    "indicator_direction", "evaluation", False, _SEV_WARNING,
                    f"{n_low} 个指标信息熵接近 0（近似常数列），"
                    f"可能未正确区分指标方向或该指标无区分度",
                ))
            else:
                checks.append(_make_check(
                    "indicator_direction", "evaluation", True, _SEV_INFO,
                    "各指标均有区分度，方向处理合理",
                ))
        elif weights is not None:
            checks.append(_make_check(
                "indicator_direction", "evaluation", True, _SEV_INFO,
                "无熵值明细，权重非退化，方向检查跳过",
            ))

        # 4. 排名稳定性 —— 权重扰动
        checks.extend(self._check_ranking_stability(question_result))

        return checks

    def _check_ranking_stability(
        self, question_result: QuestionResult,
    ) -> list[dict[str, Any]]:
        """权重 ±10% 扰动后重算排名，检查 top-3 是否稳定。

        优先使用 data_preparation.data_matrix 重算排名；若无数据矩阵，
        退化为评分间隙代理检查。
        """
        checks: list[dict[str, Any]] = []
        computation = question_result.computation or {}
        results = computation.get("results", {})
        metrics = computation.get("metrics", {})
        data_prep = question_result.data_preparation or {}
        method = computation.get("method", "")

        ranking = results.get("ranking")
        if not ranking or len(ranking) < 3:
            checks.append(_make_check(
                "ranking_stability", "evaluation", True, _SEV_INFO,
                "样本数不足 3，跳过排名稳定性检查",
            ))
            return checks

        weights = results.get("weights") or metrics.get("weights")
        if weights is None:
            checks.append(_make_check(
                "ranking_stability", "evaluation", False, _SEV_WARNING,
                "缺少权重，无法做权重扰动稳定性检查",
            ))
            return checks

        w = np.array(weights, dtype=float)
        # 原始 top-3（ranking 为 1-based，转 0-based 索引集合）
        original_top3 = {int(r) - 1 for r in ranking[:3]}

        data_matrix = data_prep.get("data_matrix")
        if not data_matrix:
            # 无数据矩阵 → 评分间隙代理检查
            checks.append(self._score_gap_stability_check(results))
            return checks

        try:
            data = np.array(data_matrix, dtype=float)
        except (ValueError, TypeError):
            checks.append(self._score_gap_stability_check(results))
            return checks

        if data.ndim != 2 or data.shape[0] < 3 or data.shape[1] != len(w):
            checks.append(self._score_gap_stability_check(results))
            return checks

        # 按方法选择重算函数
        if "TOPSIS" in method:
            recompute = self._recompute_topsis_ranking
        else:
            # 熵权法及其它加权评价方法均采用 min-max 标准化 + 加权求和
            recompute = self._recompute_weighted_ranking

        rng = np.random.default_rng(42)
        unstable = 0
        for _ in range(_PERTURB_TRIALS):
            noise = 1.0 + rng.uniform(-_PERTURB_AMP, _PERTURB_AMP, size=len(w))
            w_pert = np.clip(w * noise, 1e-9, None)
            s = float(w_pert.sum())
            if s > 0:
                w_pert = w_pert / s
            try:
                new_rank = recompute(data, w_pert)
            except Exception:
                unstable = _PERTURB_TRIALS
                break
            if {int(x) for x in new_rank[:3]} != original_top3:
                unstable += 1

        if unstable == 0:
            checks.append(_make_check(
                "ranking_stability", "evaluation", True, _SEV_INFO,
                f"权重 ±{_PERTURB_AMP:.0%} 扰动 {_PERTURB_TRIALS} 次后 top-3 排名稳定",
            ))
        elif unstable <= _PERTURB_TRIALS // 2:
            checks.append(_make_check(
                "ranking_stability", "evaluation", False, _SEV_WARNING,
                f"权重 ±{_PERTURB_AMP:.0%} 扰动中 top-3 在 "
                f"{unstable}/{_PERTURB_TRIALS} 次试验中变化，排名中等稳定",
            ))
        else:
            checks.append(_make_check(
                "ranking_stability", "evaluation", False, _SEV_ERROR,
                f"权重 ±{_PERTURB_AMP:.0%} 扰动中 top-3 在 "
                f"{unstable}/{_PERTURB_TRIALS} 次试验中变化，"
                f"排名不稳定，结论对权重高度敏感",
            ))
        return checks

    def _score_gap_stability_check(self, results: dict) -> dict[str, Any]:
        """无原始数据时的排名稳定性代理检查：基于 top-3 边界评分间隙。"""
        scores = results.get("scores") or results.get("closeness")
        if not scores or len(scores) < 4:
            return _make_check(
                "ranking_stability", "evaluation", True, _SEV_INFO,
                "样本数不足，跳过排名稳定性检查",
            )
        s = np.sort(np.array(scores, dtype=float))[::-1]  # 降序
        spread = float(s[0] - s[-1])
        if spread <= 0:
            return _make_check(
                "ranking_stability", "evaluation", False, _SEV_WARNING,
                "所有评分相同，排名无意义",
            )
        gap = float(s[2] - s[3])  # 第 3 名与第 4 名间隙
        rel_gap = gap / spread
        if rel_gap < 0.05:
            return _make_check(
                "ranking_stability", "evaluation", False, _SEV_WARNING,
                f"第3名与第4名评分差距过小（相对差距 {rel_gap:.3f}），"
                f"top-3 边界不稳定（无原始数据，采用评分间隙代理检查）",
            )
        return _make_check(
            "ranking_stability", "evaluation", True, _SEV_INFO,
            f"top-3 边界评分差距充分（相对差距 {rel_gap:.3f}），"
            f"排名稳定（代理检查）",
        )

    @staticmethod
    def _recompute_weighted_ranking(data: np.ndarray, weights: np.ndarray) -> np.ndarray:
        """熵权法/加权求和排名重算：min-max 标准化 + 加权求和。"""
        col_min = data.min(axis=0)
        col_max = data.max(axis=0)
        ranges = col_max - col_min
        ranges[ranges == 0] = 1.0
        normalized = (data - col_min) / ranges
        scores = normalized @ weights
        return np.argsort(-scores)  # 0-based 降序

    @staticmethod
    def _recompute_topsis_ranking(data: np.ndarray, weights: np.ndarray) -> np.ndarray:
        """TOPSIS 排名重算：向量归一化 + 加权 + 相对接近度。"""
        norms = np.sqrt((data ** 2).sum(axis=0))
        norms[norms == 0] = 1.0
        normalized = data / norms
        weighted = normalized * weights
        pos = weighted.max(axis=0)
        neg = weighted.min(axis=0)
        d_pos = np.sqrt(((weighted - pos) ** 2).sum(axis=1))
        d_neg = np.sqrt(((weighted - neg) ** 2).sum(axis=1))
        closeness = d_neg / (d_pos + d_neg + 1e-12)
        return np.argsort(-closeness)

    # ------------------------------------------------------------------
    # 预测/回归
    # ------------------------------------------------------------------

    def _validate_prediction(
        self, question_result: QuestionResult,
    ) -> list[dict[str, Any]]:
        """预测类检查：R²、残差分布、基线比较、时间泄漏。"""
        checks: list[dict[str, Any]] = []
        computation = question_result.computation or {}
        method = computation.get("method", "")

        if "线性回归" in method:
            checks.extend(self._check_regression(question_result))
        elif "灰色" in method or "GM" in method:
            checks.extend(self._check_gm11(question_result))
        else:
            checks.append(_make_check(
                "prediction_method", "prediction", True, _SEV_INFO,
                f"预测方法 {method}，执行通用预测检查",
            ))
            checks.extend(self._check_generic_prediction(question_result))

        # 时间泄漏 / 训练测试划分（所有预测方法通用）
        checks.extend(self._check_time_leakage(question_result))
        return checks

    def _check_regression(
        self, question_result: QuestionResult,
    ) -> list[dict[str, Any]]:
        """线性回归检查：R²、残差均值/自相关/正态性、基线比较。"""
        checks: list[dict[str, Any]] = []
        computation = question_result.computation or {}
        results = computation.get("results", {})
        metrics = computation.get("metrics", {})

        r2 = metrics.get("r_squared")
        rmse = metrics.get("rmse")
        n = metrics.get("n_samples")
        residuals = results.get("residuals")
        predictions = results.get("predictions")

        # 1. R²
        if r2 is None:
            checks.append(_make_check(
                "r_squared", "prediction", False, _SEV_WARNING,
                "缺少 R² 指标",
            ))
        elif r2 < 0:
            checks.append(_make_check(
                "r_squared", "prediction", False, _SEV_ERROR,
                f"R² = {r2:.4f} 为负，模型拟合劣于均值基线",
            ))
        elif r2 < 0.3:
            checks.append(_make_check(
                "r_squared", "prediction", False, _SEV_WARNING,
                f"R² = {r2:.4f} 偏低，拟合优度不足",
            ))
        elif r2 > 0.99 and n is not None and n < 30:
            checks.append(_make_check(
                "r_squared", "prediction", False, _SEV_WARNING,
                f"R² = {r2:.4f} 接近 1 且样本量小（n={n}），警惕过拟合",
            ))
        else:
            checks.append(_make_check(
                "r_squared", "prediction", True, _SEV_INFO,
                f"R² = {r2:.4f}，拟合优度可接受",
            ))

        # 2. 残差分布
        if residuals and predictions:
            res = np.array(residuals, dtype=float)
            y = np.array(predictions, dtype=float) + res
            mean_res = float(res.mean())
            y_std = float(y.std())
            # 均值接近 0
            if y_std > 0 and abs(mean_res) / y_std > 0.05:
                checks.append(_make_check(
                    "residual_mean", "prediction", False, _SEV_WARNING,
                    f"残差均值 {mean_res:.4e} 偏离 0，可能存在系统偏差",
                ))
            else:
                checks.append(_make_check(
                    "residual_mean", "prediction", True, _SEV_INFO,
                    f"残差均值 {mean_res:.4e} 接近 0",
                ))
            # 自相关（Durbin-Watson）
            if len(res) >= 3:
                denom = float(np.sum(res ** 2)) + 1e-12
                dw = float(np.sum(np.diff(res) ** 2) / denom)
                if dw < 1.0:
                    checks.append(_make_check(
                        "residual_autocorrelation", "prediction", False, _SEV_WARNING,
                        f"Durbin-Watson = {dw:.3f} < 1，残差存在正自相关，"
                        f"独立性假设可能不成立",
                    ))
                elif dw > 3.0:
                    checks.append(_make_check(
                        "residual_autocorrelation", "prediction", False, _SEV_WARNING,
                        f"Durbin-Watson = {dw:.3f} > 3，残差存在负自相关",
                    ))
                else:
                    checks.append(_make_check(
                        "residual_autocorrelation", "prediction", True, _SEV_INFO,
                        f"Durbin-Watson = {dw:.3f}，残差独立性可接受",
                    ))
            # 偏度（正态性代理）
            if len(res) >= 4 and res.std() > 0:
                skew = float(
                    ((res - res.mean()) ** 3).mean()
                    / (res.std() ** 3 + 1e-12)
                )
                if abs(skew) > 1.0:
                    checks.append(_make_check(
                        "residual_normality", "prediction", False, _SEV_WARNING,
                        f"残差偏度 {skew:.3f} 偏大，正态性假设可能不成立",
                    ))
                else:
                    checks.append(_make_check(
                        "residual_normality", "prediction", True, _SEV_INFO,
                        f"残差偏度 {skew:.3f}，近似对称",
                    ))
        else:
            checks.append(_make_check(
                "residual_distribution", "prediction", False, _SEV_WARNING,
                "缺少残差或预测值，无法分析残差分布",
            ))

        # 3. 基线比较 —— 与均值基线 RMSE 对比
        if rmse is not None and predictions and residuals:
            res = np.array(residuals, dtype=float)
            y = np.array(predictions, dtype=float) + res
            baseline_rmse = float(np.sqrt(np.mean((y - y.mean()) ** 2)))
            if baseline_rmse <= 1e-12:
                checks.append(_make_check(
                    "baseline_comparison", "prediction", True, _SEV_INFO,
                    "目标变量方差近似 0，基线比较无意义",
                ))
            elif rmse >= baseline_rmse:
                checks.append(_make_check(
                    "baseline_comparison", "prediction", False, _SEV_ERROR,
                    f"模型 RMSE={rmse:.4f} >= 均值基线 RMSE={baseline_rmse:.4f}，"
                    f"模型未优于朴素基线",
                ))
            else:
                improvement = 1 - rmse / baseline_rmse
                checks.append(_make_check(
                    "baseline_comparison", "prediction", True, _SEV_INFO,
                    f"模型 RMSE={rmse:.4f} 优于均值基线 {baseline_rmse:.4f}"
                    f"（提升 {improvement:.1%}）",
                ))
        elif rmse is None:
            checks.append(_make_check(
                "baseline_comparison", "prediction", False, _SEV_WARNING,
                "缺少 RMSE，无法与基线比较",
            ))

        return checks

    def _check_gm11(
        self, question_result: QuestionResult,
    ) -> list[dict[str, Any]]:
        """GM(1,1) 灰色预测检查：后验差比、小误差概率、发展系数、基线比较。"""
        checks: list[dict[str, Any]] = []
        computation = question_result.computation or {}
        results = computation.get("results", {})
        metrics = computation.get("metrics", {})
        data_prep = question_result.data_preparation or {}

        a = results.get("development_coefficient_a")
        c = metrics.get("posterior_ratio_c")
        p = metrics.get("small_error_probability")
        fitted = results.get("fitted_values")
        future = results.get("predicted_future")

        # 1. 后验差比 c
        if c is None:
            checks.append(_make_check(
                "posterior_ratio", "prediction", False, _SEV_WARNING,
                "缺少后验差比 c",
            ))
        elif c < 0.35:
            checks.append(_make_check(
                "posterior_ratio", "prediction", True, _SEV_INFO,
                f"后验差比 c={c:.4f} < 0.35，模型精度好（一级）",
            ))
        elif c < 0.5:
            checks.append(_make_check(
                "posterior_ratio", "prediction", True, _SEV_INFO,
                f"后验差比 c={c:.4f}，模型精度合格（二级）",
            ))
        elif c < 0.65:
            checks.append(_make_check(
                "posterior_ratio", "prediction", False, _SEV_WARNING,
                f"后验差比 c={c:.4f}，模型精度勉强（三级），需谨慎使用",
            ))
        else:
            checks.append(_make_check(
                "posterior_ratio", "prediction", False, _SEV_ERROR,
                f"后验差比 c={c:.4f} >= 0.65，模型精度不合格（四级）",
            ))

        # 2. 小误差概率 p
        if p is None:
            checks.append(_make_check(
                "small_error_probability", "prediction", False, _SEV_WARNING,
                "缺少小误差概率 p",
            ))
        elif p > 0.95:
            checks.append(_make_check(
                "small_error_probability", "prediction", True, _SEV_INFO,
                f"小误差概率 p={p:.3f} > 0.95，模型精度好（一级）",
            ))
        elif p > 0.8:
            checks.append(_make_check(
                "small_error_probability", "prediction", True, _SEV_INFO,
                f"小误差概率 p={p:.3f}，模型精度合格（二级）",
            ))
        elif p > 0.7:
            checks.append(_make_check(
                "small_error_probability", "prediction", False, _SEV_WARNING,
                f"小误差概率 p={p:.3f}，模型精度勉强（三级）",
            ))
        else:
            checks.append(_make_check(
                "small_error_probability", "prediction", False, _SEV_ERROR,
                f"小误差概率 p={p:.3f} <= 0.7，模型精度不合格",
            ))

        # 3. 发展系数 a
        if a is not None:
            if abs(a) >= 1.0:
                checks.append(_make_check(
                    "development_coefficient", "prediction", False, _SEV_ERROR,
                    f"发展系数 |a|={abs(a):.4f} >= 1，GM(1,1) 失效，预测不可信",
                ))
            elif abs(a) >= 0.5:
                checks.append(_make_check(
                    "development_coefficient", "prediction", False, _SEV_WARNING,
                    f"发展系数 |a|={abs(a):.4f} 较大，仅适合短期预测",
                ))
            else:
                checks.append(_make_check(
                    "development_coefficient", "prediction", True, _SEV_INFO,
                    f"发展系数 a={a:.4f}，适合中长期预测",
                ))

        # 4. 拟合/预测完整性
        if fitted and future:
            checks.append(_make_check(
                "prediction_completeness", "prediction", True, _SEV_INFO,
                f"已提供拟合值({len(fitted)})和未来预测({len(future)}期)",
            ))
        else:
            checks.append(_make_check(
                "prediction_completeness", "prediction", False, _SEV_WARNING,
                "拟合值或未来预测缺失",
            ))

        # 5. 基线比较 —— 用原始序列均值作为基线
        data_matrix = data_prep.get("data_matrix")
        if fitted and data_matrix:
            try:
                data = np.array(data_matrix, dtype=float)
                if data.ndim == 2 and data.shape[0] >= len(fitted) and data.shape[1] >= 1:
                    x0 = data[:len(fitted), 0]
                    fitted_arr = np.array(fitted, dtype=float)
                    res = x0 - fitted_arr
                    gm_rmse = float(np.sqrt(np.mean(res ** 2)))
                    baseline_rmse = float(np.sqrt(np.mean((x0 - x0.mean()) ** 2)))
                    if baseline_rmse <= 1e-12:
                        checks.append(_make_check(
                            "baseline_comparison", "prediction", True, _SEV_INFO,
                            "原始序列方差近似 0，基线比较无意义",
                        ))
                    elif gm_rmse >= baseline_rmse:
                        checks.append(_make_check(
                            "baseline_comparison", "prediction", False, _SEV_WARNING,
                            f"GM(1,1) 拟合 RMSE={gm_rmse:.4f} >= "
                            f"均值基线 {baseline_rmse:.4f}，未优于朴素基线",
                        ))
                    else:
                        improvement = 1 - gm_rmse / baseline_rmse
                        checks.append(_make_check(
                            "baseline_comparison", "prediction", True, _SEV_INFO,
                            f"GM(1,1) 拟合 RMSE={gm_rmse:.4f} 优于均值基线 "
                            f"{baseline_rmse:.4f}（提升 {improvement:.1%}）",
                        ))
            except (ValueError, TypeError):
                checks.append(_make_check(
                    "baseline_comparison", "prediction", False, _SEV_WARNING,
                    "原始数据不可用，GM(1,1) 基线比较未执行",
                ))
        else:
            checks.append(_make_check(
                "baseline_comparison", "prediction", False, _SEV_WARNING,
                "缺少拟合值或原始数据，GM(1,1) 基线比较未执行",
            ))

        return checks

    def _check_generic_prediction(
        self, question_result: QuestionResult,
    ) -> list[dict[str, Any]]:
        """通用预测检查（非回归/非 GM 方法）。"""
        checks: list[dict[str, Any]] = []
        computation = question_result.computation or {}
        metrics = computation.get("metrics", {})
        rmse = metrics.get("rmse")
        mae = metrics.get("mae")
        if rmse is not None and np.isfinite(rmse) and rmse >= 0:
            checks.append(_make_check(
                "error_metric", "prediction", True, _SEV_INFO,
                f"RMSE={rmse:.4f}，误差指标有限",
            ))
        elif mae is not None and np.isfinite(mae) and mae >= 0:
            checks.append(_make_check(
                "error_metric", "prediction", True, _SEV_INFO,
                f"MAE={mae:.4f}，误差指标有限",
            ))
        else:
            checks.append(_make_check(
                "error_metric", "prediction", False, _SEV_WARNING,
                "缺少 RMSE/MAE 等误差指标，无法评估预测精度",
            ))
        return checks

    def _check_time_leakage(
        self, question_result: QuestionResult,
    ) -> list[dict[str, Any]]:
        """时间泄漏 / 训练测试划分检查。"""
        checks: list[dict[str, Any]] = []
        data_prep = question_result.data_preparation or {}
        computation = question_result.computation or {}
        has_split = bool(
            data_prep.get("train_test_split")
            or computation.get("train_test_split")
            or data_prep.get("holdout")
        )
        if has_split:
            checks.append(_make_check(
                "time_leakage", "prediction", True, _SEV_INFO,
                "已进行训练/测试划分，可估计泛化误差",
            ))
        else:
            checks.append(_make_check(
                "time_leakage", "prediction", False, _SEV_WARNING,
                "模型在全量数据上拟合，未保留独立测试集；"
                "无法估计泛化误差，存在过拟合与时间泄漏风险",
            ))
        return checks

    # ------------------------------------------------------------------
    # 优化/规划
    # ------------------------------------------------------------------

    def _validate_optimization(
        self, question_result: QuestionResult,
    ) -> list[dict[str, Any]]:
        """优化类检查：约束可行性、目标值、边界情形、参数扰动。"""
        checks: list[dict[str, Any]] = []
        computation = question_result.computation or {}
        results = computation.get("results", {})
        status = computation.get("status", "unknown")
        method = computation.get("method", "")
        formulation = question_result.formulation or {}
        constraints = formulation.get("constraints", [])

        # 占位实现
        if status == "stub":
            checks.append(_make_check(
                "constraint_feasibility", "optimization", False, _SEV_WARNING,
                f"{method} 为占位实现，未求解实际最优解，约束可行性无法验证",
            ))
            checks.append(_make_check(
                "objective_value", "optimization", False, _SEV_WARNING,
                "占位实现无目标值，需具体问题建模",
            ))
            checks.append(_make_check(
                "boundary_cases", "optimization", False, _SEV_WARNING,
                "占位实现无变量边界，边界情形无法检查",
            ))
            return checks

        # 1. 可行解存在性与有限性
        solution = (
            results.get("solution")
            or results.get("optimal_solution")
            or results.get("x")
        )
        if solution:
            checks.append(_make_check(
                "solution_present", "optimization", True, _SEV_INFO,
                "已求得可行解",
            ))
            try:
                sol = np.array(solution, dtype=float)
                if np.all(np.isfinite(sol)):
                    checks.append(_make_check(
                        "solution_finiteness", "optimization", True, _SEV_INFO,
                        "解的所有分量为有限值",
                    ))
                else:
                    checks.append(_make_check(
                        "solution_finiteness", "optimization", False, _SEV_ERROR,
                        "解含非有限值（NaN/Inf），求解失败",
                    ))
            except (ValueError, TypeError):
                checks.append(_make_check(
                    "solution_finiteness", "optimization", False, _SEV_WARNING,
                    "解格式无法解析为数值，有限性检查跳过",
                ))
        else:
            checks.append(_make_check(
                "solution_present", "optimization", False, _SEV_WARNING,
                "未找到显式最优解",
            ))

        # 2. 目标值
        obj = results.get("objective_value") or results.get("optimal_value")
        if obj is not None:
            if isinstance(obj, (int, float)) and np.isfinite(obj):
                checks.append(_make_check(
                    "objective_value", "optimization", True, _SEV_INFO,
                    f"目标值 = {float(obj):.4f}，为有限值",
                ))
            else:
                checks.append(_make_check(
                    "objective_value", "optimization", False, _SEV_ERROR,
                    f"目标值非有限: {obj}",
                ))
        else:
            checks.append(_make_check(
                "objective_value", "optimization", False, _SEV_WARNING,
                "未记录目标值",
            ))

        # 3. 约束满足情况
        if solution and constraints:
            checks.append(_make_check(
                "constraint_satisfaction", "optimization", True, _SEV_INFO,
                f"已记录 {len(constraints)} 条约束，需结合具体模型逐条校验",
            ))
        elif constraints:
            checks.append(_make_check(
                "constraint_satisfaction", "optimization", False, _SEV_WARNING,
                "有约束但无可行解，无法校验约束满足情况",
            ))
        else:
            checks.append(_make_check(
                "constraint_satisfaction", "optimization", True, _SEV_INFO,
                "未声明显式约束（无约束优化）",
            ))

        # 4. 边界情形
        bounds = (
            results.get("bounds")
            or formulation.get("parameters", {}).get("bounds")
        )
        if bounds and solution:
            checks.append(_make_check(
                "boundary_cases", "optimization", True, _SEV_INFO,
                "已记录变量边界，建议检查最优解是否顶在边界"
                "（边界解需敏感性分析）",
            ))
        else:
            checks.append(_make_check(
                "boundary_cases", "optimization", False, _SEV_WARNING,
                "未记录变量边界，边界情形无法检查",
            ))

        # 5. 参数扰动 —— 启发式优化需检查收敛稳定性
        if any(k in method for k in ("遗传", "粒子群", "模拟退火", "启发式")):
            checks.append(_make_check(
                "parameter_perturbation", "optimization", False, _SEV_WARNING,
                f"启发式方法 {method} 建议用不同随机种子多次求解，"
                f"检查目标值稳定性（当前未执行）",
            ))
        else:
            checks.append(_make_check(
                "parameter_perturbation", "optimization", True, _SEV_INFO,
                "确定性优化方法，参数扰动检查可选",
            ))

        return checks

    # ------------------------------------------------------------------
    # 随机/鲁棒优化专项检查
    # ------------------------------------------------------------------

    def _validate_stochastic(
        self, question_result: QuestionResult,
    ) -> list[dict[str, Any]]:
        """随机/鲁棒优化专项验证。"""
        checks: list[dict[str, Any]] = []
        computation = question_result.computation or {}
        results = computation.get("results", {})
        metrics = computation.get("metrics", {})

        # 1. 鲁棒性比率检查
        robustness_ratio = metrics.get("robustness_ratio", 0)
        if robustness_ratio > 0:
            if robustness_ratio >= 0.8:
                checks.append(_make_check(
                    "robustness_ratio", "stochastic", True, _SEV_INFO,
                    f"鲁棒性比率 {robustness_ratio:.4f} ≥ 0.8，解的鲁棒性良好",
                ))
            elif robustness_ratio >= 0.6:
                checks.append(_make_check(
                    "robustness_ratio", "stochastic", True, _SEV_WARNING,
                    f"鲁棒性比率 {robustness_ratio:.4f}，一般可接受但存在风险",
                ))
            else:
                checks.append(_make_check(
                    "robustness_ratio", "stochastic", False, _SEV_WARNING,
                    f"鲁棒性比率 {robustness_ratio:.4f} < 0.6，解对不确定性敏感",
                ))

        # 2. 场景数充分性
        n_scenarios = results.get("n_scenarios", metrics.get("n_scenarios", 0))
        if n_scenarios > 0:
            if n_scenarios >= 100:
                checks.append(_make_check(
                    "scenario_count", "stochastic", True, _SEV_INFO,
                    f"场景数 {n_scenarios} ≥ 100，统计估计充分",
                ))
            elif n_scenarios >= 30:
                checks.append(_make_check(
                    "scenario_count", "stochastic", True, _SEV_WARNING,
                    f"场景数 {n_scenarios}，建议增加至 100+ 以提高精度",
                ))
            else:
                checks.append(_make_check(
                    "scenario_count", "stochastic", False, _SEV_WARNING,
                    f"场景数 {n_scenarios} < 30，统计估计不充分",
                ))

        # 3. 期望 vs 基线对比
        expected_obj = results.get("expected_objective", metrics.get("expected_objective"))
        baseline_obj = results.get("baseline_objective", metrics.get("baseline_objective"))
        if expected_obj is not None and baseline_obj is not None and baseline_obj != 0:
            ratio = expected_obj / baseline_obj
            checks.append(_make_check(
                "expected_vs_baseline", "stochastic", True, _SEV_INFO,
                f"期望目标值/基线目标值 = {ratio:.4f}，"
                f"不确定性导致目标值变化 {abs(1-ratio)*100:.1f}%",
            ))

        # 4. 最坏情况分析
        worst_case = results.get("worst_case_objective", metrics.get("worst_case"))
        best_case = results.get("best_case_objective")
        if worst_case is not None and best_case is not None and best_case != 0:
            worst_best_ratio = worst_case / best_case
            if worst_best_ratio >= 0.7:
                checks.append(_make_check(
                    "worst_case_analysis", "stochastic", True, _SEV_INFO,
                    f"最坏/最优 = {worst_best_ratio:.4f}，解对场景变化不敏感",
                ))
            else:
                checks.append(_make_check(
                    "worst_case_analysis", "stochastic", False, _SEV_WARNING,
                    f"最坏/最优 = {worst_best_ratio:.4f}，解对场景变化较敏感",
                ))

        return checks

    # ------------------------------------------------------------------
    # 分类/聚类/仿真/机理/综合
    # ------------------------------------------------------------------

    def _validate_generic(
        self, question_result: QuestionResult, math_task: str,
    ) -> list[dict[str, Any]]:
        """分类/聚类/仿真/机理/综合任务的基础检查。"""
        checks: list[dict[str, Any]] = []
        computation = question_result.computation or {}
        results = computation.get("results", {})
        metrics = computation.get("metrics", {})

        if math_task in ("classification", "clustering"):
            # 样本划分
            labels = (
                results.get("labels")
                or results.get("clusters")
                or results.get("assignments")
            )
            if labels:
                checks.append(_make_check(
                    "sample_partition", math_task, True, _SEV_INFO,
                    f"已对 {len(labels)} 个样本划分类别/簇",
                ))
                try:
                    arr = np.array(labels)
                    unique, counts = np.unique(arr, return_counts=True)
                    if len(unique) > 0 and counts.min() > 0:
                        ratio = float(counts.max() / counts.min())
                        if ratio > 10:
                            checks.append(_make_check(
                                "partition_balance", math_task, False, _SEV_WARNING,
                                f"类别样本数极不均衡"
                                f"（最大/最小={ratio:.1f}），结果可能偏向大类",
                            ))
                        else:
                            checks.append(_make_check(
                                "partition_balance", math_task, True, _SEV_INFO,
                                f"类别划分相对均衡（{len(unique)} 类，"
                                f"最大/最小={ratio:.1f}）",
                            ))
                except (ValueError, TypeError):
                    pass
            else:
                checks.append(_make_check(
                    "sample_partition", math_task, False, _SEV_WARNING,
                    "未找到分类/聚类标签",
                ))
            # 指标
            if metrics.get("silhouette") is not None or metrics.get("accuracy") is not None:
                checks.append(_make_check(
                    "clustering_metric", math_task, True, _SEV_INFO,
                    "已记录聚类/分类指标",
                ))
            else:
                checks.append(_make_check(
                    "clustering_metric", math_task, False, _SEV_WARNING,
                    "缺少轮廓系数或准确率等指标",
                ))
            # 稳定性
            checks.append(_make_check(
                "stability", math_task, False, _SEV_WARNING,
                "聚类/分类稳定性需多次运行或更换随机种子验证，当前未执行",
            ))

        elif math_task == "simulation":
            # 量纲
            checks.append(_make_check(
                "dimension_check", "simulation", False, _SEV_WARNING,
                "量纲一致性需人工核对，当前未自动检查",
            ))
            # 重复试验
            n_sim = metrics.get("n_simulations") or metrics.get("n_samples")
            if n_sim and n_sim >= 30:
                checks.append(_make_check(
                    "repeated_trials", "simulation", True, _SEV_INFO,
                    f"模拟次数 {n_sim} 充足，统计量估计可靠",
                ))
            else:
                checks.append(_make_check(
                    "repeated_trials", "simulation", False, _SEV_WARNING,
                    f"模拟次数 {n_sim} 偏少，建议 >= 30 以保证统计可靠性",
                ))
            # 边界条件
            checks.append(_make_check(
                "boundary_conditions", "simulation", False, _SEV_WARNING,
                "边界条件满足情况需结合具体模型人工校验",
            ))
            # 参数敏感性
            checks.append(_make_check(
                "parameter_sensitivity", "simulation", False, _SEV_WARNING,
                "参数敏感性分析未执行，建议对关键参数做扰动测试",
            ))

        elif math_task == "mechanism":
            checks.append(_make_check(
                "mechanism_fit", "mechanism", False, _SEV_WARNING,
                "机理模型拟合优度与边界条件需人工校验",
            ))
            if metrics.get("r_squared") is not None:
                r2 = metrics["r_squared"]
                if r2 >= 0.3:
                    checks.append(_make_check(
                        "mechanism_goodness_of_fit", "mechanism", True, _SEV_INFO,
                        f"机理模型 R²={r2:.4f}，拟合可接受",
                    ))
                else:
                    checks.append(_make_check(
                        "mechanism_goodness_of_fit", "mechanism", False, _SEV_WARNING,
                        f"机理模型 R²={r2:.4f} 偏低",
                    ))

        else:  # composite
            checks.append(_make_check(
                "composite_completeness", "composite", True, _SEV_INFO,
                "组合任务，已执行通用检查；专项检查需按子任务补充",
            ))

        return checks

    # ------------------------------------------------------------------
    # 结果叙述
    # ------------------------------------------------------------------

    def _build_narrative(
        self,
        question_result: QuestionResult,
        checks: list[dict[str, Any]],
        risks: list[str],
        math_task: str,
    ) -> str:
        """生成结果叙述：方法、关键数值、结论、局限与风险。"""
        computation = question_result.computation or {}
        results = computation.get("results", {})
        metrics = computation.get("metrics", {})
        method = computation.get("method", "未知方法")
        status = computation.get("status", "unknown")
        qid = question_result.question_id

        parts: list[str] = []
        task_label = _TASK_LABELS.get(math_task, math_task)
        parts.append(
            f"小问 {qid}（{task_label}）采用 {method} 完成建模，"
            f"计算状态为「{status}」。"
        )

        # 关键数值
        if status == "success":
            if "weights" in results:
                w = results["weights"]
                try:
                    top_idx = max(range(len(w)), key=lambda i: w[i])
                    parts.append(
                        f"基于熵权法得到 {len(w)} 个指标权重，"
                        f"其中第 {top_idx + 1} 个指标权重最大（{w[top_idx]:.4f}）。"
                    )
                except (ValueError, IndexError):
                    parts.append(f"基于熵权法得到 {len(w)} 个指标权重。")
                if "ranking" in results:
                    ranking = results["ranking"]
                    parts.append(f"综合评分排名前三的样本为：{ranking[:3]}。")
            if "closeness" in results:
                ranking = results.get("ranking", [])
                parts.append(f"TOPSIS 相对接近度排名前三的方案为：{ranking[:3]}。")
            if "coefficients" in results:
                r2 = metrics.get("r_squared")
                rmse = metrics.get("rmse")
                coef = results["coefficients"]
                r2_str = f"R²={r2:.4f}" if r2 is not None else "R²缺失"
                rmse_str = f"RMSE={rmse:.4f}" if rmse is not None else ""
                parts.append(
                    f"线性回归拟合得到 {len(coef)} 个系数，{r2_str}"
                    f"{('，' + rmse_str) if rmse_str else ''}。"
                )
            if "development_coefficient_a" in results:
                a = results["development_coefficient_a"]
                future = results.get("predicted_future", [])
                c = metrics.get("posterior_ratio_c")
                c_str = f"c={c:.4f}" if c is not None else "c缺失"
                parts.append(
                    f"GM(1,1) 发展系数 a={a:.4f}，后验差比 {c_str}，"
                    f"未来 {len(future)} 期预测值为 {future}。"
                )
        elif status == "generic_stats":
            parts.append("计算以描述性统计为主，未执行专项建模，结论限于数据汇总。")

        # 验证结论
        n_pass = sum(1 for c in checks if c["passed"])
        n_total = len(checks)
        parts.append(f"验证共执行 {n_total} 项检查，通过 {n_pass} 项。")

        # 风险与局限
        if risks:
            shown = risks[:3]
            suffix = "。" if len(risks) <= 3 else "等。"
            parts.append("主要风险与局限：" + "；".join(shown) + suffix)
        if question_result.limitations:
            parts.append(
                "已记录局限：" + "；".join(question_result.limitations[:2]) + "。"
            )

        return " ".join(parts)


# ---------------------------------------------------------------------------
# LangGraph 节点封装
# ---------------------------------------------------------------------------


def validate_result_node(state: dict) -> dict:
    """LangGraph 节点：结果验证（Phase 5）。

    读取 ``current_result``，调用 :class:`ResultValidator` 执行题型匹配的
    确定性验证，将验证报告写入 ``current_result.validation``，并按报告状态
    更新 ``current_result.status``：
      - passed / warning → ``validated``（warning 时风险已记录）
      - failed → 保持 ``validating``，交由 GQ 门决定重试或阻塞

    Args:
        state: 项目状态。需要包含 ``current_result``。

    Returns:
        状态更新字典，包含更新后的 ``current_result``。
    """
    current_result: QuestionResult | None = state.get("current_result")

    if current_result is None:
        return {
            "errors": [{"msg": "current_result missing in validate_result_node"}],
        }

    validator = ResultValidator()
    report = validator.validate(current_result)

    # 写入验证报告
    current_result.validation = report

    # 根据报告更新状态
    if report["status"] in ("passed", "warning"):
        current_result.status = "validated"
    else:
        # failed：保持 validating，交由 GQ 门处理重试/阻塞
        current_result.status = "validating"

    return {"current_result": current_result}
