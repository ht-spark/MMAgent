"""方法探索与决策 Agent。

对应 architecture.md §5.3-5.4 方法探索与方法决策。

职责：
  1. explore — 基于问题澄清和数据画像，从方法目录中生成候选方法
  2. decide — 对候选方法评分和排序，选择最佳方法
  3. generate_assumptions — 为选中方法生成假设列表

设计要点：
  - 确定性硬过滤：根据数据要求淘汰不满足条件的方法
  - 启发式评分：无 LLM 时用规则评分（数据匹配度、实现难度、适用性）
  - LLM 增强：有 LLM 时用 LLM 精调候选和评分
  - 决策可追溯：记录选择理由、备选方案和淘汰原因
"""
from __future__ import annotations

from typing import Any

from ..schemas.context import DataProfile
from ..schemas.question import CurrentQuestionContext, ProblemInterpretation
from .method_catalog import get_candidates_for_task


class MethodExplorer:
    """方法探索与决策 Agent。

    Args:
        llm: 可选的 LLM 客户端。无则使用启发式规则。
    """

    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm

    # ------------------------------------------------------------------
    # explore — 候选生成
    # ------------------------------------------------------------------

    def explore(
        self,
        context: CurrentQuestionContext,
        interpretation: ProblemInterpretation,
        data_profile: DataProfile | None = None,
    ) -> list[dict]:
        """基于问题澄清生成候选方法。

        步骤：
          1. 从方法目录中获取 math_task 对应的候选方法
          2. 硬过滤：淘汰不满足数据要求的方法
          3. 为每个候选添加评分信息
          4. 如果有 LLM，用 LLM 精调候选列表

        Args:
            context: 当前小问上下文。
            interpretation: 问题澄清结果。
            data_profile: 数据画像（用于硬过滤）。

        Returns:
            候选方法列表，每个方法包含目录字段 + score + eliminated + reason。
        """
        math_task = interpretation.math_task
        candidates = get_candidates_for_task(math_task)

        # 硬过滤
        data_info = _extract_data_info(data_profile, context)
        filtered = []
        eliminated = []

        for c in candidates:
            reason = _check_eligibility(c, data_info, interpretation)
            if reason:
                c["eliminated"] = True
                c["elimination_reason"] = reason
                eliminated.append(c)
            else:
                c["eliminated"] = False
                c["elimination_reason"] = ""
                # 启发式评分
                c["heuristic_score"] = _heuristic_score(c, data_info, interpretation)
                filtered.append(c)

        # 如果全部被淘汰，保留得分最高的淘汰候选（降级处理）
        if not filtered and eliminated:
            best_eliminated = max(eliminated, key=lambda x: x.get("heuristic_score", 0))
            best_eliminated["eliminated"] = False
            best_eliminated["elimination_reason"] = ""
            best_eliminated["degraded"] = True
            filtered.append(best_eliminated)

        # 按启发式分数排序
        filtered.sort(key=lambda x: x.get("heuristic_score", 0), reverse=True)

        # 合并结果（保留被淘汰的记录用于决策追溯）
        all_candidates = filtered + [c for c in eliminated if c not in filtered]

        print(f"[explorer] 小问 {context.question_id}: "
              f"候选 {len(candidates)} → 通过 {len(filtered)} → 淘汰 {len(eliminated)}")
        if filtered:
            print(f"  → 推荐: {filtered[0]['name']} (score={filtered[0].get('heuristic_score', 0):.3f})")

        return all_candidates

    # ------------------------------------------------------------------
    # decide — 方法决策
    # ------------------------------------------------------------------

    def decide(
        self,
        candidates: list[dict],
        context: CurrentQuestionContext,
        interpretation: ProblemInterpretation,
    ) -> dict:
        """从候选方法中选择最佳方法，生成决策记录。

        Args:
            candidates: explore 产出的候选列表。
            context: 当前小问上下文。
            interpretation: 问题澄清结果。

        Returns:
            决策记录字典，包含：
              - selected_method: 选中方法名称
              - selected_family: 方法家族
              - selected_reason: 选择理由
              - alternatives: 备选方法列表
              - eliminated: 被淘汰方法及原因
              - assumptions: 选中方法的核心假设
              - validation_method: 推荐的验证方法
        """
        # 获取未淘汰的候选
        viable = [c for c in candidates if not c.get("eliminated", False)]

        if not viable:
            # 降级：选择第一个候选
            viable = candidates[:1] if candidates else []
            if viable:
                viable[0]["degraded"] = True

        if not viable:
            return {
                "selected_method": "无可用方法",
                "selected_family": "",
                "selected_reason": "所有候选方法均被淘汰且无降级候选",
                "alternatives": [],
                "eliminated": [],
                "assumptions": [],
                "validation_method": "",
            }

        # 选择得分最高的
        selected = viable[0]
        alternatives = viable[1:4]  # 最多 3 个备选
        eliminated = [c for c in candidates if c.get("eliminated", False)]

        # 提取假设
        assumptions = _format_assumptions(selected, context, interpretation)

        # 构建决策记录
        decision = {
            "selected_method": selected["name"],
            "selected_family": selected.get("family", ""),
            "selected_reason": _build_selection_reason(selected, interpretation, context),
            "alternatives": [
                {
                    "name": a["name"],
                    "family": a.get("family", ""),
                    "score": a.get("heuristic_score", 0),
                    "reason": f"备选方案，得分 {a.get('heuristic_score', 0):.3f}",
                }
                for a in alternatives
            ],
            "eliminated": [
                {
                    "name": e["name"],
                    "reason": e.get("elimination_reason", ""),
                }
                for e in eliminated
            ],
            "assumptions": assumptions,
            "validation_method": selected.get("validation_method", ""),
            "implementation_difficulty": selected.get("implementation_difficulty", "medium"),
            "selected_details": selected,
        }

        print(f"[explorer] 决策: {selected['name']} "
              f"(备选 {len(alternatives)}, 淘汰 {len(eliminated)})")

        return decision

    # ------------------------------------------------------------------
    # explore_and_decide — 串联两步
    # ------------------------------------------------------------------

    def explore_and_decide(
        self,
        context: CurrentQuestionContext,
        interpretation: ProblemInterpretation,
        data_profile: DataProfile | None = None,
    ) -> tuple[list[dict], dict]:
        """串联 explore → decide。

        Returns:
            (candidates, decision) 二元组。
        """
        candidates = self.explore(context, interpretation, data_profile)
        decision = self.decide(candidates, context, interpretation)
        return candidates, decision


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _extract_data_info(
    data_profile: DataProfile | None,
    context: CurrentQuestionContext,
) -> dict:
    """从数据画像和上下文中提取用于硬过滤的数据信息。

    Returns:
        包含 sample_size, feature_count, has_time_column 的字典。
    """
    info = {
        "sample_size": 0,
        "feature_count": 0,
        "has_time_column": False,
        "data_quality_summary": context.data_quality_summary or "",
    }

    if data_profile is not None:
        info["sample_size"] = data_profile.max_sample_size
        info["feature_count"] = len(data_profile.fields)
        info["has_time_column"] = data_profile.has_time_column

    return info


def _check_eligibility(
    method: dict,
    data_info: dict,
    interpretation: ProblemInterpretation,
) -> str:
    """检查方法是否满足数据要求（硬过滤）。

    Returns:
        空字符串表示通过，非空字符串为淘汰原因。
    """
    req = method.get("data_requirements", {})

    # 检查最小样本量
    min_samples = req.get("min_samples", 0)
    if min_samples > 0 and data_info["sample_size"] < min_samples:
        return f"样本量不足: 需要≥{min_samples}, 实际={data_info['sample_size']}"

    # 检查最小特征数
    min_features = req.get("min_features", 0)
    if min_features > 0 and data_info["feature_count"] < min_features:
        return f"特征数不足: 需要≥{min_features}, 实际={data_info['feature_count']}"

    # 检查时间列要求
    needs_time = req.get("needs_time", False)
    if needs_time and not data_info["has_time_column"]:
        return "需要时间列但数据中无时间维度"

    return ""


def _heuristic_score(
    method: dict,
    data_info: dict,
    interpretation: ProblemInterpretation,
) -> float:
    """启发式评分（0-1）。

    评分维度：
      - data_fit (0.25): 数据是否满足方法要求（满足程度）
      - implementation (0.20): 实现难度（越简单越高）
      - interpretability (0.15): 可解释性（简单方法更高）
      - robustness (0.10): 鲁棒性（有无淘汰条件）
      - suitability (0.10): 与任务类型的匹配度
      - text_match (0.20): 题目文本与方法的匹配度

    Returns:
      0-1 之间的分数。
    """
    score = 0.0

    # data_fit: 数据满足程度
    req = method.get("data_requirements", {})
    min_samples = req.get("min_samples", 0)
    if min_samples == 0:
        score += 0.25 * 1.0  # 无数据要求，满分
    elif data_info["sample_size"] >= min_samples * 3:
        score += 0.25 * 1.0  # 充足
    elif data_info["sample_size"] >= min_samples:
        score += 0.25 * 0.7  # 刚好满足
    else:
        score += 0.25 * 0.3  # 不足但未淘汰

    # implementation: 实现难度
    difficulty = method.get("implementation_difficulty", "medium")
    diff_score = {"low": 1.0, "medium": 0.6, "high": 0.3}.get(difficulty, 0.5)
    score += 0.20 * diff_score

    # interpretability: 可解释性（简单方法更高）
    family = method.get("family", "")
    interpretable_families = [
        "客观赋权法", "主观赋权法", "多属性决策", "线性模型",
        "数学规划", "灰色系统理论", "树模型",
    ]
    if family in interpretable_families:
        score += 0.15 * 0.9
    elif family in ["机器学习", "启发式算法"]:
        score += 0.15 * 0.5
    else:
        score += 0.15 * 0.6

    # robustness: 淘汰条件越少越鲁棒
    elimination_count = len(method.get("elimination_conditions", []))
    rob_score = max(0.3, 1.0 - 0.2 * elimination_count)
    score += 0.10 * rob_score

    # suitability: 与任务类型匹配（已在目录中按类型组织，所以匹配度高）
    score += 0.10 * 0.9

    # text_match: 题目文本与方法的匹配度
    score += 0.20 * _text_match_score(method, interpretation)

    return round(score, 4)


def _text_match_score(
    method: dict,
    interpretation: ProblemInterpretation,
) -> float:
    """计算题目文本与方法的匹配度（0-1）。

    根据题目文本中的关键词与方法描述的匹配程度评分。
    匹配度高的方法获得更高分数，从而实现方法推荐的差异化。
    """
    # 从 math_task_description 中提取文本
    text = (interpretation.math_task_description or "").lower()
    method_name = method.get("name", "").lower()
    method_desc = method.get("description", "").lower()
    method_family = method.get("family", "").lower()

    score = 0.5  # 基础分

    # 不确定性相关 → 随机/鲁棒优化方法加分
    uncertainty_keywords = ["不确定性", "随机", "鲁棒", "概率", "波动", "风险", "不确定"]
    has_uncertainty = any(kw in text for kw in uncertainty_keywords)
    if has_uncertainty:
        if any(kw in method_name for kw in ["随机", "鲁棒", "蒙特卡洛", "机会约束"]):
            score = 1.0
        elif any(kw in method_family for kw in ["随机", "鲁棒"]):
            score = 0.9
        elif "确定性" in method_name:
            score = 0.3  # 确定性方法在不确定性场景下降分
        else:
            score = 0.4

    # 整数/离散相关 → 整数规划加分
    integer_keywords = ["整数", "离散", "0-1", "二元", "integer", "discrete"]
    has_integer = any(kw in text for kw in integer_keywords)
    if has_integer:
        if "整数" in method_name:
            score = max(score, 0.9)
        elif "遗传" in method_name or "粒子群" in method_name:
            score = max(score, 0.7)
        elif "线性规划" in method_name and "整数" not in method_name:
            score = min(score, 0.4)  # 纯连续LP在整数场景下降分

    # 非线性相关 → 启发式算法加分
    nonlinear_keywords = ["非线性", "nonlinear", "复杂约束"]
    has_nonlinear = any(kw in text for kw in nonlinear_keywords)
    if has_nonlinear:
        if method.get("family") == "启发式算法":
            score = max(score, 0.85)
        elif "线性规划" in method_name:
            score = min(score, 0.3)

    # 时间序列/趋势相关 → 时间序列方法加分
    time_keywords = ["时间序列", "趋势", "forecast", "预测"]
    has_time = any(kw in text for kw in time_keywords)
    if has_time:
        if "arima" in method_name or "时间序列" in method_name:
            score = max(score, 0.9)
        elif "灰色" in method_name or "gm" in method_name:
            score = max(score, 0.8)
        elif "线性回归" in method_name:
            score = max(score, 0.6)

    # 多指标评价相关 → 评价方法加分
    eval_keywords = ["评价", "排序", "评估", "rank", "evaluate"]
    has_eval = any(kw in text for kw in eval_keywords)
    if has_eval:
        if any(kw in method_name for kw in ["熵权", "topsis", "ahp", "层次"]):
            score = max(score, 0.9)
        elif "灰色关联" in method_name:
            score = max(score, 0.75)

    return score


def _format_assumptions(
    method: dict,
    context: CurrentQuestionContext,
    interpretation: ProblemInterpretation,
) -> list[dict]:
    """格式化选中方法的假设列表。

    Returns:
        假设列表，每个假设包含 description, type, verifiable 字段。
    """
    assumptions: list[dict] = []

    # 方法自带假设
    for a in method.get("assumptions", []):
        assumptions.append({
            "description": a,
            "type": "method_inherent",
            "verifiable": True,
        })

    # 基于数据质量的假设
    if context.data_quality_summary:
        if "小样本" in context.data_quality_summary or "样本量" in context.data_quality_summary:
            assumptions.append({
                "description": "样本量有限，结果可能存在统计偏差",
                "type": "data_limitation",
                "verifiable": True,
            })
        if "无时间" in context.data_quality_summary:
            assumptions.append({
                "description": "无时间维度数据，不可使用时间序列方法",
                "type": "data_limitation",
                "verifiable": True,
            })

    # 基于前问继承的假设
    if context.inherited_summaries:
        for s in context.inherited_summaries:
            if s.get("status") == "validated":
                prev_limitations = s.get("limitations", [])
                for lim in prev_limitations[:1]:  # 只取第一条
                    assumptions.append({
                        "description": f"继承前问假设: {lim}",
                        "type": "inherited",
                        "verifiable": False,
                    })

    return assumptions


def _build_selection_reason(
    selected: dict,
    interpretation: ProblemInterpretation,
    context: CurrentQuestionContext,
) -> str:
    """构建方法选择理由。"""
    reasons: list[str] = []

    # 任务匹配
    reasons.append(
        f"任务类型 {interpretation.math_task} 与方法 {selected['name']} "
        f"({selected.get('family', '')}) 匹配"
    )

    # 数据匹配
    req = selected.get("data_requirements", {})
    if req.get("min_samples", 0) == 0:
        reasons.append("无特殊数据要求")
    else:
        reasons.append(f"满足数据要求（最小样本量 {req.get('min_samples', 0)}）")

    # 实现难度
    difficulty = selected.get("implementation_difficulty", "medium")
    if difficulty == "low":
        reasons.append("实现难度低，竞赛中可快速落地")
    elif difficulty == "medium":
        reasons.append("实现难度适中")
    else:
        reasons.append("实现难度较高，需要更多工程投入")

    # 继承关系
    if context.inherited_summaries:
        dep_ids = [s.get("question_id", "?") for s in context.inherited_summaries]
        reasons.append(f"可利用前问 {', '.join(dep_ids)} 的结论作为输入")

    # 降级标记
    if selected.get("degraded"):
        reasons.append("⚠ 降级选择：数据不完全满足要求，结果需谨慎解读")

    return "; ".join(reasons)
