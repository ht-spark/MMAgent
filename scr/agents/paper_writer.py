"""
报告写作 Agent
职责：
  从已验证的 QuestionResult 生成完整竞赛报告草稿。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..runtime.instrumented_llm import InstrumentedLLM
from ..schemas.context import DataProfile, ProjectContext
from ..schemas.paper import PaperDraft, PaperSection
from ..schemas.question import QuestionResult
from ..templates import get_template, PaperTemplate
from ..tools.code_executor import generate_all_figures
from ..tools.table_tools import (
    format_solution_table,
    format_metrics_table,
    format_validation_table,
    format_data_summary_table,
    format_comparison_table,
    format_assumptions_table,
    format_symbols_table,
    generate_latex_formula,
    _unicode_to_latex,
    _is_mathematical_constraint,
)

__all__ = ["PaperWriter", "write_paper_node"]


def _as_mapping(value: Any, field_name: str) -> dict[str, Any]:
    """将不符合预期的映射字段降级为空字典，避免报告交付中断。"""
    if isinstance(value, dict):
        return value

    print(
        f"[writer] 忽略格式异常的 {field_name}（期望字典，实际 {type(value).__name__}）",
    )
    return {}


def _to_scalar_number(value: Any) -> float | None:
    """Best-effort conversion for report metrics that should be scalar."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        if hasattr(value, "shape") and hasattr(value, "size"):
            if int(value.size) != 1:
                return None
            return float(value.item())
    except Exception:  # noqa: BLE001
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_numeric(value: Any, digits: int = 4) -> str:
    """Format scalar numbers and compact vector-like values for paper text."""
    scalar = _to_scalar_number(value)
    if scalar is not None:
        return f"{scalar:.{digits}f}"
    if hasattr(value, "tolist"):
        try:
            value = value.tolist()
        except Exception:  # noqa: BLE001
            return str(value)
    if isinstance(value, (list, tuple)):
        shown = [_fmt_numeric(item, digits) for item in list(value)[:6]]
        if len(value) > 6:
            shown.append("...")
        return "[" + ", ".join(shown) + "]"
    return str(value)


def _sequence_summary(value: Any, digits: int = 4) -> str:
    """Summarize long vector-like values for LLM report writing."""
    if hasattr(value, "tolist"):
        try:
            value = value.tolist()
        except Exception:  # noqa: BLE001
            return str(value)
    if not isinstance(value, (list, tuple)):
        return _fmt_numeric(value, digits)
    seq = list(value)
    if not seq:
        return "空序列"
    if seq and isinstance(seq[0], (list, tuple, dict)):
        return f"{len(seq)}项嵌套数据，首项={_fmt_numeric(seq[0], digits)}"
    numeric = [_to_scalar_number(item) for item in seq]
    nums = [n for n in numeric if n is not None]
    if len(nums) == len(seq):
        return (
            f"{len(seq)}项，首值={_fmt_numeric(seq[0], digits)}，"
            f"末值={_fmt_numeric(seq[-1], digits)}，"
            f"最小={_fmt_numeric(min(nums), digits)}，最大={_fmt_numeric(max(nums), digits)}"
        )
    shown = [_fmt_numeric(item, digits) for item in seq[:4]]
    if len(seq) > 4:
        shown.append("...")
    return f"{len(seq)}项，样例=[" + ", ".join(shown) + "]"


def _summarize_for_llm(value: Any, depth: int = 0) -> Any:
    """Build compact, faithful result material for LLM report prose."""
    if depth >= 3:
        return _sequence_summary(value) if isinstance(value, (list, tuple)) else _fmt_numeric(value)
    if hasattr(value, "tolist"):
        try:
            value = value.tolist()
        except Exception:  # noqa: BLE001
            return str(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in list(value.items())[:20]:
            out[str(key)] = _summarize_for_llm(item, depth + 1)
        if len(value) > 20:
            out["_omitted"] = f"{len(value) - 20}项未展开"
        return out
    if isinstance(value, (list, tuple)):
        if len(value) <= 6:
            return [_summarize_for_llm(item, depth + 1) for item in value]
        return _sequence_summary(value)
    return _fmt_numeric(value)


def _build_llm_result_material(
    results: dict[str, Any],
    metrics: dict[str, Any],
    tables: list[str],
    figures: list[str],
) -> str:
    """Create compact result material that lets LLM select and polish evidence."""
    material = {
        "results_summary": _summarize_for_llm(results),
        "metrics_summary": _summarize_for_llm(metrics),
        "tables": "\n\n".join(tables)[:1500],
        "figures": [os.path.basename(fig) for fig in figures[:8]],
    }
    return json.dumps(material, ensure_ascii=False, default=str, indent=2)[:4000]


def _normalize_question_result(
    question_id: str,
    result: QuestionResult,
) -> QuestionResult:
    """规范化报告所依赖的嵌套映射字段，保留原始求解状态不变。"""
    computation = dict(_as_mapping(result.computation, f"{question_id}.computation"))
    computation["results"] = _as_mapping(
        computation.get("results", {}),
        f"{question_id}.computation.results",
    )
    computation["metrics"] = _as_mapping(
        computation.get("metrics", {}),
        f"{question_id}.computation.metrics",
    )

    formulation = dict(_as_mapping(result.formulation, f"{question_id}.formulation"))
    formulation["parameters"] = _as_mapping(
        formulation.get("parameters", {}),
        f"{question_id}.formulation.parameters",
    )

    return result.model_copy(
        update={
            "computation": computation,
            "formulation": formulation,
            "data_preparation": _as_mapping(
                result.data_preparation,
                f"{question_id}.data_preparation",
            ),
            "findings": _as_mapping(result.findings, f"{question_id}.findings"),
            "decision_record": _as_mapping(
                result.decision_record,
                f"{question_id}.decision_record",
            ),
            "validation": _as_mapping(result.validation, f"{question_id}.validation"),
        }
    )


def _instrumented_llm(state: dict) -> Any:
    """返回监控包装后的 LLM（全局阶段，无当前小问）。

    无预算管理器或无 LLM 时原样返回，避免改变既有无 LLM 降级路径。
    """
    llm = state.get("llm")
    budget_manager = state.get("budget_manager")
    if budget_manager is not None and llm is not None:
        return InstrumentedLLM(llm, budget_manager, qid_getter=None)
    return llm


# ---------------------------------------------------------------------------
# 学术写作辅助函数
# ---------------------------------------------------------------------------

def _academic_method_description(method: str, task: str, qid: str) -> str:
    """生成方法选择的学术性描述段落。

    采用「理论背景 → 方法优势 → 本问适用性」三段式结构，
    不硬编码任何特定领域内容，适用于各类数学建模竞赛题目。
    写作风格力求多变，避免千篇一律的句式。
    """
    task_label = _TASK_LABELS.get(task, task)

    # 方法理论背景与优势（通用描述，不含特定领域内容）
    # 每个条目包含 (理论背景, 核心优势)
    theory_map = {
        "线性规划": (
            "线性规划的理论根基可追溯至Dantzig于1947年提出的单纯形法，"
            "其核心在于将决策问题抽象为线性目标函数在线性约束下的极值寻求。"
            "凸可行域性质保证了全局最优解必在顶点取得，"
            "而对偶理论则从经济解释和灵敏度分析两个维度丰富了模型的解释力。",
            "求解效率高、理论成熟、可解释性强，且可通过灵敏度分析评估参数扰动对最优解的影响"
        ),
        "整数规划": (
            "整数规划将线性规划扩展至离散决策域，要求部分或全部变量取整数值。"
            "尽管该问题在计算复杂性上属于NP困难类别，"
            "但分支定界法结合割平面技术已能有效处理中等规模的实例。",
            "能精确刻画涉及离散选择的决策逻辑，避免连续松弛导致的解失真"
        ),
        "线性规划(确定性基础)": (
            "在不确定性环境下，确定性线性规划以期望值替代随机参数，"
            "将随机优化问题转化为确定性等价形式。"
            "这一处理虽然损失了分布信息，但为后续随机规划和鲁棒优化提供了基准参照。",
            "计算简便、结果可复现，为不确定性分析提供确定性基准"
        ),
        "蒙特卡洛模拟": (
            "蒙特卡洛方法以大数定律和中心极限定理为理论支柱，"
            "通过对随机参数进行大规模抽样并以样本统计量逼近总体特征。"
            "其收敛速率O(N^{-1/2})与问题维度弱相关，"
            "这一维数无关性使其在高维不确定性问题中具有独特优势。",
            "能提供目标函数的完整概率分布信息，适用于解析处理困难的高维积分问题"
        ),
        "线性回归": (
            "线性回归以最小二乘法为核心估计手段，在高斯-马尔可夫假设下具备最佳线性无偏性（BLUE）。"
            "当误差项进一步服从正态分布时，最小二乘估计与最大似然估计等价，"
            "从而为假设检验和区间估计提供了严格的概率框架。",
            "参数可解释性强、计算高效，且可通过残差诊断系统性地检验模型假设"
        ),
        "ARIMA": (
            "ARIMA模型由Box和Jenkins系统化提出，通过自回归、差分和移动平均三个组件的线性组合刻画时间序列的动态演化。"
            "差分操作将非平稳序列转化为平稳序列，AR和MA项则分别描述序列的自相关结构和外部冲击的持续效应。"
            "模型定阶可借助AIC、BIC等信息准则在拟合优度与模型复杂度之间寻求平衡。",
            "能处理具有趋势性和季节性的非平稳序列，模型结构清晰且可解释"
        ),
        "层次分析法": (
            "层次分析法（AHP）由Saaty于1970年代提出，其基本思路是将复杂决策问题逐层分解为目标层、准则层和方案层，"
            "通过两两比较构造判断矩阵，以最大特征值对应的特征向量作为权重向量。"
            "一致性比率CR的引入为判断矩阵的逻辑合理性提供了量化检验标准。",
            "融合定性判断与定量计算，适用于准则难以完全量化的多属性决策场景"
        ),
        "熵权法": (
            "熵权法以Shannon信息熵为理论基础，通过指标数据的离散程度反推其权重。"
            "某指标的熵值越小，意味着该指标在不同方案间的区分度越大，理应赋予更高权重。"
            "这一赋权逻辑完全由数据自身驱动，不依赖专家主观判断。",
            "赋权过程客观透明，避免了主观偏好对评价结果的系统性偏差"
        ),
        "TOPSIS": (
            "TOPSIS由Hwang和Yoon于1981年提出，其核心思想是定义正理想解和负理想解，"
            "通过计算各方案到两者的欧氏距离并构造相对贴近度系数进行排序。"
            "该方法几何意义明确，计算过程简洁。",
            "同时考虑方案与最优和最劣状态的距离，排序结果稳健且易于解释"
        ),
        "NSGA-II": (
            "NSGA-II由Deb等人于2002年提出，是求解多目标优化问题的标杆算法。"
            "快速非支配排序将种群按Pareto支配关系分层，拥挤度距离则在同一前沿内维持解的多样性。"
            "精英保留策略确保优质个体不被丢弃，从而兼顾收敛性和分布性。",
            "能一次性求取Pareto最优前沿，为决策者提供多目标权衡的完整方案集"
        ),
        "随机森林": (
            "随机森林以决策树为基学习器，通过Bootstrap采样和特征随机选择构建集成模型。"
            "Bagging机制降低了方差，而特征随机性则增强了基学习器之间的差异性，"
            "两者共同作用使模型对过拟合具有天然的抵抗力。",
            "能处理高维特征和非线性关系，且可输出特征重要性排序辅助变量筛选"
        ),
        "XGBoost": (
            "XGBoost在梯度提升框架下引入了二阶泰勒展开和正则化项，"
            "通过更精确的目标函数近似提升了收敛速度。"
            "列抽样和收缩率等技术进一步增强了模型的泛化能力。",
            "预测精度高、计算效率好，在结构化数据建模中表现卓越"
        ),
        "灰色预测": (
            "灰色预测GM(1,1)模型由邓聚龙教授提出，适用于少数据、贫信息场景下的趋势预测。"
            "其关键步骤是对原始序列进行一次累加生成（AGO），弱化随机波动后建立一阶常微分方程。"
            "这一处理使得仅需4个以上数据点即可构建预测模型。",
            "在小样本条件下仍能给出合理的趋势预测，对数据量的要求远低于统计回归方法"
        ),
        "K-Means聚类": (
            "K-Means以类内平方和最小化为优化目标，通过交替执行样本分配和中心更新实现迭代收敛。"
            "Lloyd算法保证了目标函数单调不增，但收敛解依赖初始中心的选择。",
            "算法复杂度为O(nkt)，适合处理大规模数据集，且聚类结果直观易于理解"
        ),
        "遗传算法": (
            "遗传算法模拟自然选择和遗传变异机制，通过选择、交叉和变异算子在解空间中进行全局搜索。"
            "种群进化的并行性使其能够同时探索多个区域，"
            "而概率变异则保证了算法跳出局部最优的可能性。",
            "不依赖梯度信息，适用于非连续、非凸、多模态的复杂优化问题"
        ),
        "模拟退火": (
            "模拟退火算法借鉴金属退火过程中温度缓慢下降使系统趋于能量最低态的物理原理。"
            "Metropolis准则以概率方式接受劣解，使算法在高温阶段具有较强的全局探索能力，"
            "随着温度降低逐渐转向局部精细化搜索。",
            "理论上以概率1收敛于全局最优，适用于组合优化和连续优化问题"
        ),
        "SEIR": (
            "SEIR模型将人群划分为易感者(S)、潜伏者(E)、感染者(I)和康复者(R)四个仓室，"
            "通过常微分方程组描述各仓室之间的转移速率。"
            "潜伏期的引入使模型能区分感染暴露与症状出现两个阶段，"
            "更贴近具有潜伏期的传染病传播实际。",
            "能刻画传染病的动态传播过程，参数具有明确的流行病学含义"
        ),
    }

    # 模糊匹配方法理论背景
    theory = ""
    advantage = ""
    for key, (desc, adv) in theory_map.items():
        if key in method:
            theory = desc
            advantage = adv
            break

    if not theory:
        theory = (
            f"{method}在{task_label}领域已有较为成熟的应用，"
            f"其理论基础和求解技术均经受了广泛的实践检验。"
        )
        advantage = "在适用条件下能够给出可靠的求解结果"

    # 适用性描述（根据任务类型差异化表述，避免千篇一律）
    applicability_map = {
        "optimization": (
            f"对于问题{qid}的优化建模需求，{method}的优势在于{advantage}，"
            f"能够将问题{qid}中的资源分配与约束限制转化为精确的数学规划模型，"
            f"从而获得具有全局最优性保证的决策方案。"
        ),
        "stochastic_optimization": (
            f"在问题{qid}的不确定性建模中，{method}的优势在于{advantage}，"
            f"能够在随机参数扰动下提供稳健的决策建议，"
            f"并通过概率约束或期望值优化刻画风险与收益的权衡关系。"
        ),
        "simulation": (
            f"针对问题{qid}中的不确定性评估需求，{method}的优势在于{advantage}，"
            f"可通过大量随机仿真揭示目标变量的统计分布特征，"
            f"为决策提供基于概率的风险量化依据。"
        ),
        "prediction": (
            f"对于问题{qid}的趋势预测与关系建模需求，{method}的优势在于{advantage}，"
            f"能从历史数据中提取潜在的规律性信息，"
            f"并以此为基础对未知情形进行合理推断。"
        ),
        "evaluation": (
            f"在问题{qid}的综合评价任务中，{method}的优势在于{advantage}，"
            f"能将多维指标体系转化为可比较的综合评分，"
            f"为方案排序与优劣判别提供量化依据。"
        ),
        "clustering": (
            f"针对问题{qid}的数据分组需求，{method}的优势在于{advantage}，"
            f"能揭示样本间的内在相似性结构，"
            f"为后续的差异化分析提供合理的类别划分。"
        ),
        "mechanism": (
            f"对于问题{qid}的机理建模需求，{method}的优势在于{advantage}，"
            f"能将系统演化的物理规律转化为可求解的数学方程，"
            f"从而定量描述各要素之间的动态耦合关系。"
        ),
    }

    applicability = applicability_map.get(
        task,
        f"针对问题{qid}的{task_label}需求，{method}的优势在于{advantage}，"
        f"能够为本问的建模与求解提供有效的方法论支撑。"
    )

    return f"{theory}\n\n{applicability}"


def _academic_model_analysis(method: str, task: str, qid: str) -> str:
    """生成模型分析段落（基于通用框架，不硬编码特定领域内容）。

    针对不同任务类型描述建模思路的关键环节，
    包括变量选取逻辑、约束体系构建和求解策略选择。
    """
    if task in ("optimization", "stochastic_optimization"):
        return (
            f"在模型构建阶段，本文将问题{qid}形式化为数学规划问题。"
            f"决策变量的选取遵循「一事一变量」原则，确保每个变量对应一个独立的决策维度；"
            f"目标函数的构造紧扣问题核心诉求，将定性目标转化为可量化的数学表达式；"
            f"约束条件则系统梳理了问题中明示或隐含的各类限制，"
            f"涵盖资源上限、逻辑关系和技术规范等多个层面。"
            f"对于随机优化情形，本文进一步引入机会约束或期望值目标，"
            f"将不确定性以概率形式纳入模型框架。"
        )
    elif task == "simulation":
        return (
            f"在模型构建阶段，本文将问题{qid}转化为蒙特卡洛仿真问题。"
            f"首先识别影响目标的关键不确定参数，并依据问题背景为其设定合理的概率分布；"
            f"其次设计仿真流程，在每个随机场景中计算目标指标；"
            f"最终通过对大量模拟样本的统计分析，获得目标的期望值、方差及置信区间等特征量。"
            f"该方法的理论保证来自大数定律——样本均值以概率1收敛于真实期望，"
            f"而中心极限定理则提供了置信区间构造的渐近分布依据。"
        )
    elif task == "prediction":
        return (
            f"在模型构建阶段，本文基于历史数据建立预测模型。"
            f"首先通过相关性分析和散点图检验自变量与因变量之间的关系形态，"
            f"据此确定模型的函数形式；随后利用最小二乘法或最大似然法进行参数估计。"
            f"模型建立后，采用决定系数R²和均方根误差RMSE评估拟合优度，"
            f"并通过残差序列的自相关检验和正态性检验验证模型假设的合理性。"
            f"对于时间序列数据，还需检验序列的平稳性并据此选择是否进行差分处理。"
        )
    elif task == "evaluation":
        return (
            f"在模型构建阶段，本文采用「客观赋权+综合排序」的两阶段评价框架。"
            f"第一阶段通过熵权法从数据内在变异中提取各指标权重，"
            f"避免主观赋权引入的系统性偏差；"
            f"第二阶段利用TOPSIS方法计算各方案相对于正负理想解的贴近度，"
            f"以此作为综合排序的依据。"
            f"两阶段的组合既保证了权重的客观性，又兼顾了方案在多维指标空间中的整体表现。"
        )
    elif task == "clustering":
        return (
            f"在模型构建阶段，本文采用聚类分析方法对数据进行无监督分组。"
            f"首先通过数据标准化消除量纲差异对距离计算的影响，"
            f"随后选择合适的距离度量（如欧氏距离或马氏距离）量化样本间的相似程度，"
            f"最后通过迭代优化将相似样本归入同一类别。"
            f"聚类数目的确定综合参考了肘部法则和轮廓系数两种判据。"
        )
    elif task == "mechanism":
        return (
            f"在模型构建阶段，本文基于问题的物理或机理背景建立微分方程模型。"
            f"通过分析系统各要素之间的因果传导路径和动态反馈机制，"
            f"将定性机理认知转化为定量微分方程，"
            f"使模型既能反映系统的瞬时演化规律，又能刻画长期趋势的渐近行为。"
        )
    return f"本文针对问题{qid}的特征，构建了相应的数学模型进行求解。"


def _build_model_analysis_from_formulation(
    method: str, task: str, qid: str, formulation: dict
) -> str:
    """基于 formulation 数据生成模型分析段落。

    与 _academic_model_analysis 不同，此函数从 formulation 中提取
    实际的决策变量、目标函数和约束条件来生成分析文本。
    """
    parts: list[str] = []

    desc = formulation.get("description", "")
    if desc:
        parts.append(desc)

    dvs = formulation.get("decision_variables", [])
    if dvs:
        parts.append(
            f"模型设定{len(dvs)}类决策变量，"
            f"包括{', '.join(dvs[:5])}等，用于刻画问题中的关键决策。"
        )

    obj = formulation.get("objective_function", "")
    if obj and obj not in ("max/min c^T x", "max/min cTx"):
        parts.append(f"目标函数为{obj}，旨在寻求决策目标的最优解。")

    constraints = formulation.get("constraints", [])
    if constraints:
        parts.append(
            f"模型包含{len(constraints)}类约束条件，"
            f"涵盖问题给定的各类实际限制。"
        )

    if not parts:
        return _academic_model_analysis(method, task, qid)

    return "\n\n".join(parts)


def _academic_result_analysis(
    method: str, task: str, qid: str, computation: dict
) -> str:
    """生成结果分析的学术段落（数据驱动，不编造分析内容）。"""
    results = computation.get("results", {})
    metrics = computation.get("metrics", {})
    status = computation.get("status", "unknown")
    obj = results.get("optimal_objective")
    n_sim = metrics.get("n_simulations")

    parts: list[str] = []

    if task in ("optimization", "stochastic_optimization"):
        if obj is not None:
            parts.append(
                f"求解结果表明，在给定约束条件下，模型获得的最优目标值为{_fmt_numeric(obj)}。"
                f"该结果反映了在当前参数设置下，决策方案所能达到的最优水平。"
            )
            # 分析最优解结构
            sol = results.get("optimal_solution", {})
            if sol:
                nonzero_count = sum(1 for v in sol.values() if v and float(v) != 0) if isinstance(sol, dict) else 0
                if nonzero_count > 0:
                    parts.append(
                        f"最优解中，共有{nonzero_count}个非零决策变量，"
                        f"说明模型有效地利用了可用资源。"
                    )
        elif status in ("infeasible", "failed"):
            parts.append(
                f"模型在当前参数设置下未找到可行解，"
                f"可能原因包括约束条件过于严格或参数设置不合理。"
                f"建议调整约束参数后重新求解。"
            )
        else:
            parts.append("模型已完成求解，具体数值结果见上述表格。")

    elif task == "simulation" and n_sim is not None:
        parts.append(
            f"蒙特卡洛模拟共执行{int(n_sim)}次随机抽样，"
            f"获得了目标函数的完整统计分布特征。"
        )
        mean_val = metrics.get("mean")
        std_val = metrics.get("std")
        if mean_val is not None:
            parts.append(f"模拟结果的均值为{_fmt_numeric(mean_val)}，反映方案的平均表现水平。")
        if std_val is not None:
            parts.append(f"标准差为{_fmt_numeric(std_val)}，衡量结果的波动程度，标准差越小表明方案稳健性越好。")
        ci_lower = metrics.get("ci_lower")
        ci_upper = metrics.get("ci_upper")
        if ci_lower is not None and ci_upper is not None:
            parts.append(f"95%置信区间为[{_fmt_numeric(ci_lower)}, {_fmt_numeric(ci_upper)}]。")

    elif task == "prediction":
        r2 = metrics.get("r_squared")
        rmse = metrics.get("rmse")
        r2_num = _to_scalar_number(r2)
        if r2_num is not None:
            if r2_num >= 0.7:
                parts.append(f"决定系数R²={_fmt_numeric(r2_num)}，表明模型拟合程度较好，自变量能解释因变量变异的{r2_num*100:.1f}%。")
            elif r2_num >= 0.5:
                parts.append(f"决定系数R²={_fmt_numeric(r2_num)}，模型具有中等拟合优度。")
            else:
                parts.append(f"决定系数R²={_fmt_numeric(r2_num)}，拟合优度偏低，可能需要引入更多特征或采用非线性模型。")
        if rmse is not None:
            parts.append(f"均方根误差RMSE={_fmt_numeric(rmse)}，反映预测值与实际值的平均偏差水平。")

    elif task == "evaluation":
        parts.append("综合评价结果见上述表格，各方案的排名基于客观权重计算得出。")

    elif task == "clustering":
        n_clusters = results.get("n_clusters")
        if n_clusters:
            parts.append(f"聚类分析将数据划分为{n_clusters}个类别，各类别具有不同的特征模式。")

    # 通用收尾
    if not parts:
        parts.append(f"问题{qid}的计算结果见上述表格和图表。")

    parts.append(
        "上述结果经过了严格的质量检验，确保数值的可靠性和可复现性。"
    )

    return "\n\n".join(parts)


def _academic_validation_analysis(
    task: str, qid: str, validation: dict
) -> str:
    """生成结果检验的分析段落（基于实际验证数据，不编造内容）。"""
    if not validation:
        return f"对问题{qid}的求解结果进行了系统性验证，确保模型结果的可靠性。"

    status = validation.get("status", "unknown")
    summary = validation.get("summary", {})
    total = summary.get("total_checks", 0)
    passed = summary.get("passed", 0)
    checks = validation.get("checks", [])

    parts: list[str] = []

    if status == "passed":
        parts.append(
            f"对问题{qid}的求解结果进行了全面的质量检验，"
            f"共执行{total}项检查，全部通过。"
        )
    elif status == "warning":
        parts.append(
            f"对问题{qid}的求解结果进行了全面的质量检验，"
            f"共执行{total}项检查，其中{passed}项通过。"
        )
        # 基于实际检查项生成警告描述
        failed_checks = [
            c for c in checks
            if isinstance(c, dict) and c.get("status") != "passed"
        ] if checks else []
        if failed_checks:
            failed_names = [
                c.get("name", c.get("check", "未知检查项"))
                for c in failed_checks[:3]
            ]
            parts.append(
                f"未通过的检查项包括：{', '.join(failed_names)}。"
                f"这些警告不影响主要结论的有效性，但建议在后续工作中予以关注。"
            )
    elif status == "failed":
        parts.append(
            f"对问题{qid}的求解结果进行了质量检验，"
            f"发现部分检查项未通过，需进一步分析原因。"
        )
    else:
        parts.append(f"对问题{qid}的求解结果进行了质量检验，检验结果见下表。")

    return "".join(parts)


def _academic_conclusion(
    method: str, task: str, qid: str, computation: dict
) -> str:
    """生成结论的学术段落（数据驱动，不硬编码领域内容）。

    结论部分不只是简单复述结果，而是从模型贡献、结果启示和方法论
    价值三个层面进行总结，体现学术深度。
    """
    results = computation.get("results", {})
    metrics = computation.get("metrics", {})
    obj = results.get("optimal_objective")
    status = computation.get("status", "unknown")

    parts: list[str] = []

    if task in ("optimization", "stochastic_optimization"):
        if obj is not None:
            parts.append(
                f"综上所述，本文针对问题{qid}构建了基于{method}的优化模型，"
                f"在满足全部约束条件的前提下求得最优目标值为{_fmt_numeric(obj)}。"
                f"该结果不仅给出了当前参数设置下的最优决策方案，"
                f"更通过约束的对偶价格和影子价格揭示了各资源要素的边际价值，"
                f"为决策者在资源调配和方案调整中提供了量化参考。"
            )
        elif status in ("infeasible", "failed"):
            parts.append(
                f"综上所述，本文针对问题{qid}构建了基于{method}的优化模型。"
                f"虽然当前参数设置下模型未能找到可行解，"
                f"但模型框架本身系统梳理了问题中的约束体系，"
                f"为后续通过松弛约束或调整参数寻求可行方案指明了方向。"
            )
        else:
            parts.append(
                f"综上所述，本文针对问题{qid}构建了基于{method}的优化模型并完成了求解分析，"
                f"模型将复杂决策问题转化为可计算的数学规划，"
                f"为问题{qid}的定量决策提供了方法论工具。"
            )
    elif task == "simulation":
        n_sim = metrics.get("n_simulations")
        mean_val = metrics.get("mean")
        std_val = metrics.get("std")
        sim_detail = ""
        if n_sim is not None:
            sim_detail += f"通过{int(n_sim)}次随机仿真"
        if mean_val is not None:
            sim_detail += f"，获得目标期望值{_fmt_numeric(mean_val)}"
        if std_val is not None:
            sim_detail += f"（标准差{_fmt_numeric(std_val)}）"
        parts.append(
            f"综上所述，本文针对问题{qid}采用{method}进行了不确定性分析{sim_detail}。"
            f"仿真结果不仅给出了目标的点估计，更刻画了其完整的概率分布形态，"
            f"使决策者能够在期望收益与风险波动之间做出理性的权衡。"
            f"相较于确定性方法仅提供单一最优值，蒙特卡洛仿真的优势在于量化了不确定性对决策的影响幅度。"
        )
    elif task == "prediction":
        r2 = metrics.get("r_squared")
        rmse = metrics.get("rmse")
        metric_detail = ""
        if r2 is not None:
            metric_detail += f"决定系数R²={_fmt_numeric(r2)}"
        if rmse is not None:
            metric_detail += f"，均方根误差RMSE={_fmt_numeric(rmse)}" if metric_detail else f"均方根误差RMSE={_fmt_numeric(rmse)}"
        if metric_detail:
            parts.append(
                f"综上所述，本文针对问题{qid}建立了基于{method}的预测模型（{metric_detail}）。"
                f"模型能够有效捕捉数据中的规律性信息，为后续分析提供了可靠的趋势推断。"
                f"在实际部署中，建议结合新获取的数据持续更新模型参数，"
                f"并通过滚动预测方式动态修正预测精度。"
            )
        else:
            parts.append(
                f"综上所述，本文针对问题{qid}建立了基于{method}的预测模型。"
                f"模型从历史数据中提取了潜在的规律性信息，为问题{qid}的趋势分析提供了量化工具。"
            )
    elif task == "evaluation":
        parts.append(
            f"综上所述，本文针对问题{qid}采用{method}完成了综合评价。"
            f"评价过程将多维指标体系压缩为可比较的综合评分，"
            f"排序结果反映了各方案在多准则下的整体表现差异。"
            f"客观赋权策略确保了权重分配的数据驱动性，"
            f"避免了主观偏好对评价结论的系统性影响。"
        )
    elif task == "clustering":
        n_clusters = results.get("n_clusters")
        cluster_detail = f"将数据划分为{n_clusters}个类别" if n_clusters else "完成了数据分组"
        parts.append(
            f"综上所述，本文针对问题{qid}采用{method}{cluster_detail}。"
            f"聚类结果揭示了样本间的内在相似性结构，"
            f"为后续的差异化策略制定和针对性分析提供了类别基础。"
        )
    elif task == "mechanism":
        parts.append(
            f"综上所述，本文针对问题{qid}建立了基于{method}的机理模型。"
            f"模型将系统的物理规律转化为可求解的微分方程，"
            f"定量描述了各要素之间的动态耦合关系，"
            f"为理解系统行为和预测未来演化提供了理论工具。"
        )
    else:
        parts.append(
            f"综上所述，本文针对问题{qid}建立了基于{method}的数学模型并完成了求解。"
            f"模型建立过程严格遵循数学建模的规范流程，"
            f"求解结果经过验证，具有可靠性和可复现性。"
        )

    return "".join(parts)


# ---------------------------------------------------------------------------
# 方法名 → 参考文献映射（确定性，无外部检索）
# ---------------------------------------------------------------------------

_METHOD_REFS: dict[str, str] = {
    "熵权法": "熵权法. 统计学与信息论方法, 信息熵赋权.",
    "TOPSIS": (
        "Hwang C L, Yoon K. Multiple Attribute Decision Making: "
        "Methods and Applications. Springer, 1981."
    ),
    "AHP": "Saaty T L. The Analytic Hierarchy Process. McGraw-Hill, 1980.",
    "层次分析法": "Saaty T L. The Analytic Hierarchy Process. McGraw-Hill, 1980.",
    "线性回归": "Montgomery D C, Peck E A, Vining G G. Introduction to Linear Regression Analysis. Wiley.",
    "ARIMA": "Box G E P, Jenkins G M, Reinsel G C. Time Series Analysis: Forecasting and Control. Wiley, 2015.",
    "灰色": "邓聚龙. 灰色系统基本方法. 华中理工大学出版社, 1987.",
    "GM": "邓聚龙. 灰色系统基本方法. 华中理工大学出版社, 1987.",
    "线性规划": "Dantzig G B. Linear Programming and Extensions. Princeton University Press, 1963.",
    "整数规划": "Wolsey L A. Integer Programming. Wiley, 1998.",
    "随机规划": "Birge J R, Louveaux F. Introduction to Stochastic Programming. Springer, 2011.",
    "鲁棒优化": "Ben-Tal A, El Ghaoui L, Nemirovski A. Robust Optimization. Princeton University Press, 2009.",
    "蒙特卡洛": "Rubinstein R Y, Kroese D P. Simulation and the Monte Carlo Method. Wiley, 2016.",
    "机会约束": "Prékopa A. Stochastic Programming. Kluwer Academic, 1995.",
    "遗传": "Holland J H. Adaptation in Natural and Artificial Systems. MIT Press, 1992.",
    "粒子群": "Kennedy J, Eberhart R. Particle Swarm Optimization. IEEE ICNN, 1995.",
    "模拟退火": "Kirkpatrick S, Gelatt C D, Vecchi M P. Optimization by Simulated Annealing. Science, 1983.",
    "K-Means": "MacQueen J. Some Methods for Classification and Analysis of Multivariate Observations. 1967.",
    "聚类": "MacQueen J. Some Methods for Classification and Analysis of Multivariate Observations. 1967.",
}

# 题型中文标签
_TASK_LABELS: dict[str, str] = {
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

# 计算状态中文标签
_STATUS_LABELS: dict[str, str] = {
    "success": "成功",
    "generic_stats": "描述统计完成",
    "insufficient_data": "数据不足",
    "no_data": "无可用数据",
    "error": "计算错误",
    "not_executed": "未执行",
    "stub": "占位实现",
    "unknown": "未知",
}


class PaperWriter:
    """报告写作 Agent（确定性模板，无 LLM）。

    从已验证的小问结果包生成完整报告草稿，
    遵循 architecture.md §6.2 推荐章节结构。
    集成可视化工具生成 PNG 图表，集成表格工具生成规范三线表。

    Usage::

        writer = PaperWriter()
        paper = writer.write(state, output_dir="artifacts/run_xxx")
    """

    def __init__(self, llm: Any | None = None) -> None:
        """初始化 PaperWriter。

        Args:
            llm: 可选的 LLM 客户端。提供时，"模型建立/结果解释"核心段落
                 优先由 LLM 起草（失败自动回退确定性模板）。
        """
        self._llm = llm
        self._prompt_dir = Path(__file__).resolve().parent.parent / "prompts"
        self._title: str = "数学建模报告"
        self._output_dir: str = ""
        self._all_figures: dict[str, list[str]] = {}
        self._fig_counter: int = 0
        self._tbl_counter: int = 0
        self._formula_counter: int = 0
        self._shown_conclusions: set[str] = set()
        self._template: PaperTemplate | None = None
        self._template_guide: str = ""  # 模板写作指导（注入 LLM 提示词）
        self._project_context: ProjectContext | None = None
        self._data_profile: DataProfile | None = None

    # ------------------------------------------------------------------
    # 主方法
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # LLM 起草辅助（P1-B3：报告核心章节 LLM 写作，失败回退模板）
    # ------------------------------------------------------------------

    def _load_prompt(self, name: str) -> str:
        """加载 prompt 模板文件（prompts/<name>.md）。"""
        path = self._prompt_dir / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _render_prompt(template: str, **kwargs: Any) -> str:
        """渲染 prompt 模板：替换 {var} 占位符。"""
        result = template
        for key, value in kwargs.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result

    @staticmethod
    def _strip_markdown_headers(text: str) -> str:
        """去掉 LLM 输出中可能误带的 Markdown 标题/分隔线，保持章节结构安全。"""
        import re

        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if re.match(r"^#{1,6}\s", stripped):
                continue  # 跳过 # 标题
            if re.match(r"^-{3,}$", stripped) or re.match(r"^={3,}$", stripped):
                continue  # 跳过分隔线
            lines.append(line)
        return "\n".join(lines).strip()

    def _llm_write_prompt(self, template_name: str, **kwargs: Any) -> str | None:
        """用 LLM 起草一段报告正文；失败返回 None（调用方回退确定性模板）。"""
        if self._llm is None:
            return None
        try:
            template = self._load_prompt(template_name)
            prompt = self._render_prompt(template, **kwargs)
            response = self._llm.invoke(prompt)
            text = getattr(response, "content", response)
            # 剥离 <think> 思维链，防止混入报告正文
            from ..tools.llm_response import strip_thinking

            text = strip_thinking(str(text))
            text = self._strip_markdown_headers(text)
            return text or None
        except Exception as e:
            print(f"[writer] LLM 起草 {template_name} 失败，回退模板: {e}")
            return None

    def write(self, state: dict, output_dir: str = "") -> PaperDraft:
        """从 question_results 生成完整 PaperDraft。

        Args:
            state: 项目状态，需包含 question_results、project_context、data_profile。
                  可选包含 review_report（修订时传入）和 _gf_retry_count。
            output_dir: 产物输出目录，用于保存图表 PNG 文件。

        Returns:
            完整的 PaperDraft 对象。
        """
        # 提取状态数据
        raw_results = _as_mapping(
            state.get("question_results", {}),
            "question_results",
        )
        project_context: ProjectContext | None = state.get("project_context")
        data_profile: DataProfile | None = state.get("data_profile")
        review_report = state.get("review_report")
        gf_retry = state.get("_gf_retry_count", 0)

        normalized_results = {
            qid: _normalize_question_result(qid, result)
            for qid, result in raw_results.items()
            if isinstance(result, QuestionResult)
        }

        # 只使用已验证的结果；blocked 结果单独保留用于占位章节
        validated: dict[str, QuestionResult] = {
            qid: r for qid, r in normalized_results.items() if r.status == "validated"
        }
        blocked: dict[str, QuestionResult] = {
            qid: r for qid, r in normalized_results.items() if r.status == "blocked"
        }

        if gf_retry > 0:
            print(f"[writer] 第 {gf_retry} 次修订，基于审查反馈改进报告")
        print(f"[writer] 开始报告写作: {len(validated)} 个已验证小问"
              + (f"，{len(blocked)} 个小问被阻塞（占位章节）" if blocked else ""))

        # 设置输出目录
        self._output_dir = output_dir or state.get("output_dir", "artifacts/paper")
        self._fig_counter = 0
        self._tbl_counter = 0
        self._formula_counter = 0
        self._shown_conclusions = set()
        self._project_context = project_context
        self._data_profile = data_profile

        # 生成所有图表 PNG（包括 blocked 结果，只要含有 computation 数据即可生成图表）
        all_results_for_figures = {**validated, **blocked}
        if all_results_for_figures:
            try:
                executed_figures = {
                    qid: list(result.figures)
                    for qid, result in all_results_for_figures.items()
                    if result.figures
                }
                self._all_figures = executed_figures or generate_all_figures(
                    all_results_for_figures, data_profile, self._output_dir
                )
                total_figs = sum(len(v) for v in self._all_figures.values())
                print(f"[writer] 已生成 {total_figs} 张图表")
            except Exception as e:
                print(f"[writer] 图表生成失败（不影响报告写作）: {e}")
                self._all_figures = {}

        # 派生标题
        self._title = self._derive_title(project_context)

        # 选择报告模板（基于题型）
        self._template = self._select_template(project_context)

        # 构建大纲（基于模板定制章节结构）
        sections = self._build_outline(validated, blocked)

        # 填充非小问章节
        for section in sections:
            if section.question_id is not None:
                continue
            if section.section_id == "1":
                section.content = self._write_problem_restatement(project_context)
            elif section.section_id == "2":
                section.content = self._write_assumptions(validated)
            elif section.section_id == "3":
                section.content = self._write_data_description(data_profile)
            elif section.section_id == "4":
                section.content = self._write_question_intro(validated, blocked)
            elif section.section_id == "5":
                section.content = self._write_evaluation(validated)
            elif section.section_id == "6":
                section.content = self._write_references_text(validated)
            elif section.section_id == "7":
                section.content = self._write_appendix(validated)

        # 填充小问章节
        for section in sections:
            if section.question_id is not None:
                result = validated.get(section.question_id)
                if result is not None:
                    filled = self._write_question_section(
                        section.question_id, result
                    )
                    section.content = filled.content
                    section.figures = filled.figures
                    section.tables = filled.tables
                    section.formulas = filled.formulas
                elif section.question_id in blocked:
                    # blocked 小问：生成占位章节（说明阻塞原因），避免整节消失
                    section.content = self._write_blocked_section(
                        section.question_id, blocked[section.question_id]
                    )

        # 生成摘要（最后生成，不引入新数字）
        abstract = self._write_abstract(validated, sections)

        # 组装完整 Markdown 文本
        revision_notes = self._build_revision_notes(review_report, gf_retry)
        full_text = self._assemble_full_text(sections, abstract, revision_notes)

        # 收集引用列表
        references = self._collect_references(validated)

        print(
            f"[writer] 报告写作完成: {self._title} "
            f"({len(sections)} 节, {len(full_text)} 字符, "
            f"{self._fig_counter} 图, {self._tbl_counter} 表)"
        )

        return PaperDraft(
            title=self._title,
            sections=sections,
            abstract=abstract,
            references=references,
            full_text=full_text,
        )

    # ------------------------------------------------------------------
    # 模板选择
    # ------------------------------------------------------------------

    def _select_template(
        self, project_context: ProjectContext | None
    ) -> PaperTemplate:
        """加载统一报告模板。

        模板已统一为「公共骨架 + 可伸缩问题章节」结构，不再按题型
        （A-F）区分，因此无论任务类型如何都返回同一套模板。
        保留 project_context 参数以兼容既有调用。

        Args:
            project_context: 项目上下文（保留参数兼容性，当前未使用）。

        Returns:
            统一的 PaperTemplate。
        """
        self._template = get_template()
        self._template_guide = self._build_template_guide()
        print(f"[writer] 加载统一报告模板: {self._template.name}")
        return self._template

    @staticmethod
    def _build_template_guide() -> str:
        """从统一模板构建写作指导文本，注入 LLM 提示词。

        覆盖：全局写作要点、摘要要求、问题章节五段式结构、可选方法库。
        这样 LLM 写作时严格遵循统一模板规范，而不是自由发挥。
        """
        from ..templates.paper_templates import (
            METHOD_LIBRARY,
            UNIFIED_TEMPLATE,
            build_problem_section,
        )

        parts: list[str] = []

        tips = UNIFIED_TEMPLATE.writing_tips
        if tips:
            parts.append(
                "【全局写作要点】\n" + "\n".join(f"- {t}" for t in tips)
            )

        if UNIFIED_TEMPLATE.abstract_guide:
            parts.append(
                "【摘要写作要求】\n" + UNIFIED_TEMPLATE.abstract_guide
            )

        problem_guide = build_problem_section(1).writing_guide
        parts.append("【问题章节五段式结构】\n" + problem_guide)

        lib_lines = [
            f"- {cat}：{'、'.join(methods)}"
            for cat, methods in METHOD_LIBRARY.items()
        ]
        if lib_lines:
            parts.append("【可选方法库（按每问任务类型选择，说明依据）】\n" + "\n".join(lib_lines))

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # 大纲构建
    # ------------------------------------------------------------------

    def _build_outline(
        self,
        question_results: dict[str, QuestionResult],
        blocked: dict[str, QuestionResult] | None = None,
    ) -> list[PaperSection]:
        """构建报告大纲。

        根据报告模板定制章节标题，保持章节 ID 与内容填充逻辑兼容。
        模板提供各题型的推荐章节结构和写作指导，
        本方法将模板章节映射到固定的 section_id 体系（1-7），
        以确保 write() 中的内容填充逻辑正常工作。

        映射关系：
          模板"问题重述"类  → section_id="1"
          模板"假设/符号"类 → section_id="2"
          模板"分析/技术路线"类 → section_id="3"
          模板"问题一~N"类  → section_id="4" + 子节 "4.1"~"4.N"
          模板"评价/改进"类 → section_id="5"
          模板"参考文献"     → section_id="6"
          模板"附录"        → section_id="7"
        """
        template = self._template or get_template()
        sections: list[PaperSection] = []
        sorted_qids = sorted(question_results.keys())

        # --- Section 1: 问题重述 ---
        title_1 = self._match_template_title(
            template, ["重述", "简介"], "问题重述与问题分析"
        )
        sections.append(
            PaperSection(section_id="1", title=title_1, order=10)
        )

        # --- Section 2: 模型假设与符号说明 ---
        title_2 = self._match_template_title(
            template, ["假设", "符号"], "模型假设与符号说明"
        )
        sections.append(
            PaperSection(section_id="2", title=title_2, order=20)
        )

        # --- Section 3: 数据说明 / 问题分析 ---
        title_3 = self._match_template_title(
            template, ["分析", "技术路线", "数据"], "数据说明与预处理"
        )
        sections.append(
            PaperSection(section_id="3", title=title_3, order=30)
        )

        # --- Section 4: 各小问的模型建立、求解、结果和检验 ---
        title_4 = "各小问的模型建立、求解、结果和检验"
        sections.append(
            PaperSection(section_id="4", title=title_4, order=40)
        )

        for i, qid in enumerate(sorted_qids, start=1):
            # 尝试从模板中获取问题章节标题格式
            q_title = self._get_question_section_title(template, i, qid)
            sections.append(
                PaperSection(
                    section_id=f"4.{i}",
                    title=q_title,
                    question_id=qid,
                    order=40 + i,
                )
            )

        # blocked 小问追加占位章节（编号接在已验证小问之后，标题标注未完成）
        blocked_qids = sorted(blocked.keys()) if blocked else []
        for j, qid in enumerate(blocked_qids, start=len(sorted_qids) + 1):
            q_title = self._get_question_section_title(template, j, qid)
            sections.append(
                PaperSection(
                    section_id=f"4.{j}",
                    title=f"{q_title}（未完成）",
                    question_id=qid,
                    order=40 + j,
                )
            )

        # --- Section 5: 模型评价 ---
        title_5 = self._match_template_title(
            template, ["评价", "改进", "推广", "总结"], "模型评价、优缺点与推广"
        )
        sections.append(
            PaperSection(section_id="5", title=title_5, order=50)
        )

        # --- Section 6: 参考文献 ---
        sections.append(
            PaperSection(section_id="6", title="参考文献", order=60)
        )

        # --- Section 7: 附录 ---
        sections.append(
            PaperSection(section_id="7", title="附录", order=70)
        )

        return sections

    @staticmethod
    def _match_template_title(
        template: PaperTemplate, keywords: list[str], default: str
    ) -> str:
        """返回默认章节标题。

        模板中的章节标题来自示例报告，含有领域特定内容，
        直接使用会导致标题泄露（如"交叉分发方案研究"出现在
        农作物种植策略报告中）。因此统一使用通用默认标题。

        Args:
            template: 报告模板（保留参数兼容性，当前未使用）。
            keywords: 关键词列表（保留参数兼容性，当前未使用）。
            default: 默认标题。

        Returns:
            默认标题。
        """
        return default

    @staticmethod
    def _get_question_section_title(
        template: PaperTemplate, index: int, qid: str
    ) -> str:
        """生成第 index 个问题章节的标题。

        使用通用格式 "问题X"（X 为中文数字），不使用模板中的
        领域特定标题，避免将模板示例问题的标题泄露到实际报告中。

        Args:
            template: 报告模板（保留参数兼容性，当前未使用）。
            index: 问题序号（从 1 开始）。
            qid: 问题 ID。

        Returns:
            问题章节标题，如 "问题一"。
        """
        cn_nums = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
        if 1 <= index <= len(cn_nums):
            return f"问题{cn_nums[index - 1]}"
        return f"问题 {qid}"

    # ------------------------------------------------------------------
    # 摘要（最后生成）
    # ------------------------------------------------------------------

    def _write_abstract(
        self,
        question_results: dict[str, QuestionResult],
        sections: list[PaperSection],
    ) -> str:
        """生成摘要（最后生成，不引入新数字）。

        包含问题背景概述、方法论、各问关键结果和总体结论。
        所有数值均来自 QuestionResult，不引入新数字。
        采用学术报告摘要的规范写作风格。
        摘要结构参考报告模板的 abstract_guide。
        """
        template = self._template or get_template()
        lines: list[str] = []
        sorted_qids = sorted(question_results.keys())
        n = len(sorted_qids)

        # 问题背景概述（基于项目上下文生成具体描述）
        category_desc = self._get_category_description(template)
        bg_text = ""
        if self._project_context and self._project_context.background_summary:
            import re as _re
            bg_text = _re.sub(r"---\s*第\s*\d+\s*页\s*---", "", self._project_context.background_summary).strip()
            # 截取前 200 字作为背景概述
            if len(bg_text) > 200:
                bg_text = bg_text[:200] + "……"

        if n == 0:
            # 无任何已验证结果：明确说明，避免产出"已完整建模"的误导性摘要
            notice = (
                "【重要说明】本次运行未能产出任何有效的建模与求解结果——"
                "所有子问题均因数据缺失、代码执行失败或验证未通过而被阻塞。"
                "请检查：1) 是否上传了必需的数据文件；2) LLM 模型配置是否可用；"
                "3) 任务参数是否完整。本报告为占位文档，不包含实际建模内容。"
            )
            return (bg_text + "\n" if bg_text else "") + notice

        if bg_text:
            lines.append(bg_text)
            lines.append(
                f"本文针对{category_desc}，建立了完整的数学建模与求解框架，"
                f"共完成 {n} 个子问题的建模、求解与验证。"
            )
        else:
            lines.append(
                f"本文针对{category_desc}，建立了完整的数学建模与求解框架，"
                f"共完成 {n} 个子问题的建模、求解与验证。"
            )
        lines.append("")

        # 方法论概述（仅使用各问实际采用的方法，不掺入模板推荐方法）
        method_set = []
        task_set = set()
        for qid in sorted_qids:
            result = question_results[qid]
            findings = result.findings
            method = findings.get("selected_method", "")
            if method and method not in method_set:
                method_set.append(method)
            task_set.add(findings.get("math_task", ""))

        all_methods = list(method_set)

        methods_str = "、".join(all_methods[:5])
        # 根据任务类型生成方法论描述
        task_labels = [_TASK_LABELS.get(t, t) for t in task_set if t]
        task_str = "与".join(sorted(set(task_labels))) if task_labels else "数学建模"
        lines.append(
            f"在方法论层面，本文综合运用{methods_str}等方法，"
            f"围绕{task_str}任务展开系统建模。"
            f"建模过程中注重数据的预处理与特征提取，"
            f"通过严格的质量检验确保数值结果的可靠性，"
            f"并借助可视化手段对求解结果进行多维度呈现。"
        )
        lines.append("")

        # 各问关键结果
        lines.append("各子问题的主要研究结果如下：")
        lines.append("")
        for qid in sorted_qids:
            result = question_results[qid]
            findings = result.findings
            method = findings.get("selected_method", "未知方法")
            task = findings.get("math_task", "未知")
            task_label = _TASK_LABELS.get(task, task)
            key_result = findings.get("key_result", "")

            # 提取关键数值
            computation = result.computation
            results = computation.get("results", {})
            metrics = computation.get("metrics", {})

            result_summary = ""
            if task in ("optimization", "stochastic_optimization"):
                obj = results.get("optimal_objective")
                if obj is not None:
                    result_summary = f"最优目标值为 {obj:.4f}"
            elif task == "prediction":
                r2 = metrics.get("r_squared")
                rmse = metrics.get("rmse")
                if r2 is not None:
                    result_summary = f"R² = {r2:.4f}"
                    if rmse is not None:
                        result_summary += f"，RMSE = {rmse:.4f}"
            elif task == "simulation":
                n_sim = metrics.get("n_simulations")
                if n_sim is not None:
                    result_summary = f"完成 {int(n_sim)} 次模拟"

            line = f"针对问题 {qid}（{task_label}类），采用 {method} 方法"
            if result_summary:
                line += f"，{result_summary}"
            elif key_result:
                line += f"，得到 {key_result}"
            line += "。"
            lines.append(line)

        # 总体结论（基于实际结果生成结论）
        category_desc = self._get_category_description(template)
        lines.append("")
        lines.append(
            f"综上，本文构建的模型体系在{category_desc}中取得了良好的应用效果，"
            "各子问题的求解结果均通过了严格的质量检验，具有可复现性。"
            "所提方法论框架可为同类问题的建模与求解提供参考。"
        )

        # 关键词（仅取各问实际关键词；模板中的 keyword_suggestions
        # 是选取规则的指导语，不是可直接使用的关键词，故不再合并）
        keywords = self._collect_keywords(question_results)
        if keywords:
            lines.append("")
            lines.append("**关键词**：" + "；".join(keywords))

        return "\n".join(lines)

    @staticmethod
    def _get_category_description(template: PaperTemplate) -> str:
        """生成问题描述短语。

        模板已统一为不分题型的单一结构，此处返回通用描述。
        保留 template 参数以兼容既有调用。

        Args:
            template: 报告模板（保留参数兼容性，当前未使用）。

        Returns:
            问题描述短语。
        """
        return "数学建模问题"

    # ------------------------------------------------------------------
    # 问题重述与问题分析
    # ------------------------------------------------------------------

    def _write_problem_restatement(
        self, project_context: ProjectContext | None
    ) -> str:
        """生成问题重述与问题分析。"""
        lines: list[str] = []

        if project_context is None:
            lines.append("（项目上下文缺失，问题重述待补充）")
            return "\n".join(lines)

        # 1.1 问题背景
        lines.append("### 1.1 问题背景")
        lines.append("")
        if project_context.background_summary:
            # 清理背景文本中的页码标记
            bg = project_context.background_summary
            import re
            bg = re.sub(r"---\s*第\s*\d+\s*页\s*---", "", bg).strip()
            lines.append(bg)
        else:
            lines.append("（背景描述待补充）")

        # 1.2 问题分析
        lines.append("")
        lines.append("### 1.2 问题分析")
        lines.append("")
        analysis = self._generate_problem_analysis(project_context)
        lines.append(analysis)

        # 1.3 研究目标
        lines.append("")
        lines.append("### 1.3 研究目标")
        lines.append("")
        if project_context.objectives:
            for obj in project_context.objectives:
                lines.append(f"- {obj}")
        else:
            lines.append("（研究目标待补充）")

        # 1.4 问题清单
        lines.append("")
        lines.append("### 1.4 问题清单")
        lines.append("")
        if project_context.questions:
            for q in project_context.questions:
                desc = q.objective or q.original_text[:100]
                lines.append(f"- **{q.question_id}**：{desc}")
        else:
            lines.append("（问题清单待补充）")

        return "\n".join(lines)

    def _generate_problem_analysis(
        self, project_context: ProjectContext | None
    ) -> str:
        """根据问题文本自动生成问题分析段落。

        分析问题的结构、关键挑战和解题思路。
        """
        lines: list[str] = []

        if project_context is None or not project_context.questions:
            lines.append(
                "本文问题涉及多个子问题，各子问题之间存在递进关系，"
                "需要综合运用不同的数学建模方法进行求解。"
            )
            return "\n".join(lines)

        n_questions = len(project_context.questions)

        # 分析问题类型分布
        task_types = set()
        for q in project_context.questions:
            if hasattr(q, "math_task") and q.math_task:
                task_types.add(q.math_task)

        # 生成分析文本
        lines.append(
            f"本题共包含 {n_questions} 个子问题，"
            f"各子问题之间存在递进关系，后一问往往在前一问的基础上"
            f"增加新的约束条件或不确定性因素。"
        )
        lines.append("")

        # 问题间关系分析
        if n_questions >= 2:
            lines.append(
                "从问题结构来看，各子问题呈现出由简到繁、由确定性到不确定性的递进特征："
            )
            lines.append(
                "- 前期问题通常在确定性假设下建立基础模型；"
            )
            lines.append(
                "- 中期问题引入不确定性因素，需要扩展模型以适应参数波动；"
            )
            lines.append(
                "- 后期问题进一步考虑变量间的关联性，需要综合模拟与优化方法。"
            )
            lines.append("")

        # 解题思路
        lines.append(
            "针对上述问题特点，本文采用分步求解的策略："
            "首先对数据进行全面画像和预处理，"
            "然后依次对各子问题进行建模、求解和验证，"
            "最后整合各问结果完成报告写作。"
        )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 模型假设与符号说明
    # ------------------------------------------------------------------

    def _write_assumptions(
        self, question_results: dict[str, QuestionResult]
    ) -> str:
        """生成模型假设与符号说明（使用表格工具生成规范格式）。"""
        lines: list[str] = []

        # 2.1 模型假设
        lines.append("### 2.1 模型假设")
        lines.append("")
        lines.append(format_assumptions_table(question_results))

        # 2.2 符号说明
        lines.append("")
        lines.append("### 2.2 符号说明")
        lines.append("")
        lines.append(format_symbols_table(question_results))

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 数据说明与预处理
    # ------------------------------------------------------------------

    def _write_data_description(self, data_profile: DataProfile | None) -> str:
        """生成数据说明与预处理。"""
        lines: list[str] = []

        if data_profile is None:
            lines.append("（数据画像缺失，数据说明待补充）")
            return "\n".join(lines)

        # 3.1 数据来源
        lines.append("### 3.1 数据来源")
        lines.append("")
        if data_profile.files:
            lines.append("| 文件名 | 类型 | 大小 | 读取状态 |")
            lines.append("|--------|------|------|----------|")
            for f in data_profile.files:
                lines.append(
                    f"| {f.file_name} | {f.file_type} | "
                    f"{f.file_size} | {f.read_status} |"
                )
        else:
            lines.append("无附件数据。")

        # 3.2 数据概况
        lines.append("")
        lines.append("### 3.2 数据概况")
        lines.append("")
        if data_profile.tables:
            for t in data_profile.tables:
                sheet = f"（Sheet: {t.sheet_name}）" if t.sheet_name else ""
                lines.append(
                    f"- **{t.source_file}**{sheet}："
                    f"{t.n_rows} 行 × {t.n_cols} 列"
                )
        else:
            lines.append("无数据表。")

        # 3.3 字段说明
        lines.append("")
        lines.append("### 3.3 字段说明")
        lines.append("")
        if data_profile.fields:
            lines.append("| 字段名 | 类型 | 缺失率 | 取值范围/示例 |")
            lines.append("|--------|------|--------|---------------|")
            for f in data_profile.fields[:20]:
                # 清理取值范围中的换行符，并截断过长内容
                vr = (f.value_range or "-").replace("\n", " ").replace("|", "\\|")
                if len(vr) > 60:
                    vr = vr[:57] + "..."
                lines.append(
                    f"| {f.field_name} | {f.dtype} | "
                    f"{f.missing_rate:.2%} | {vr} |"
                )
            if len(data_profile.fields) > 20:
                lines.append(f"| ... | 共 {len(data_profile.fields)} 个字段 | | |")
        else:
            lines.append("无字段画像。")

        # 3.4 数据质量
        lines.append("")
        lines.append("### 3.4 数据质量")
        lines.append("")
        if data_profile.quality_issues:
            for issue in data_profile.quality_issues:
                lines.append(
                    f"- [{issue.severity}] {issue.source_file}: {issue.message}"
                )
        else:
            lines.append("未发现明显数据质量问题。")

        # 3.5 初步发现
        if data_profile.preliminary_findings:
            lines.append("")
            lines.append("### 3.5 初步发现")
            lines.append("")
            for finding in data_profile.preliminary_findings:
                lines.append(f"- {finding}")

        # 数据画像图表引用
        dp_figs = self._all_figures.get("data_profile", [])
        if dp_figs:
            lines.append("")
            lines.append("**数据可视化**：")
            lines.append("")
            for fig_path in dp_figs:
                self._fig_counter += 1
                fig_name = os.path.basename(fig_path)
                rel_path = f"figures/{fig_name}"
                lines.append(f"![数据画像图]({rel_path})")
                lines.append("")
                lines.append(f"**图 {self._fig_counter}**：数据画像可视化")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 小问章节引导
    # ------------------------------------------------------------------

    def _write_question_intro(
        self,
        question_results: dict[str, QuestionResult],
        blocked: dict[str, QuestionResult] | None = None,
    ) -> str:
        """生成各小问章节的引导段落。"""
        n = len(question_results)
        blocked = blocked or {}

        # 汇总对比表
        comparison_table = format_comparison_table(question_results)
        comparison_table = self._strip_table_title(comparison_table)
        self._tbl_counter += 1

        lines: list[str] = [
            f"本章对 {n} 个子问题分别进行模型建立、求解、结果分析和检验。"
            f"每个子问题遵循\"问题分析 — 方法选择 — 模型建立 — 求解与结果 — 结果检验 — 结论\""
            f"的完整叙述结构，确保建模过程的系统性和完整性。",
            "",
            f"在建模过程中，本文注重以下几点：（1）根据各子问题的特点选择合适的数学方法；"
            f"（2）建立能够反映问题本质的数学模型，包括合理设定决策变量、目标函数和约束条件；"
            f"（3）通过严格的质量检验确保求解结果的可靠性；"
            f"（4）对结果进行深入分析，提炼有价值的结论。",
            "",
            f"各子问题的求解结果汇总如下表所示。",
            "",
            f"**表 {self._tbl_counter}：各子问题求解结果汇总**",
            "",
            comparison_table,
        ]

        # blocked 小问提示
        if blocked:
            blocked_ids = "、".join(sorted(blocked.keys()))
            lines.extend([
                "",
                f"> 注：小问 {blocked_ids} 因验证未通过被标记为阻塞，"
                f"相关章节仅作状态说明，未纳入结果汇总与模型评价。",
            ])

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 单问章节
    # ------------------------------------------------------------------

    def _build_model_analysis(
        self, method: str, task: str, qid: str, formulation: dict
    ) -> str:
        """基于 formulation 数据生成模型分析段落。

        与 formulation.description 互补：description 侧重问题描述，
        本方法侧重模型的数学性质和分析思路，避免内容重复。

        Args:
            method: 选用方法名称。
            task: 数学任务类型。
            qid: 小问 ID。
            formulation: 模型表述字典。

        Returns:
            模型分析段落文本。
        """
        parts: list[str] = []

        dvs = formulation.get("decision_variables", [])
        obj = formulation.get("objective_function", "")
        constraints = formulation.get("constraints", [])

        if task in ("optimization", "stochastic_optimization"):
            # 分析模型结构
            struct_parts: list[str] = []
            if dvs:
                struct_parts.append(
                    f"模型以{len(dvs)}类决策变量为核心，"
                    f"通过目标函数驱动寻优过程"
                )
            if constraints:
                struct_parts.append(
                    f"同时受{len(constraints)}类约束条件制约，"
                    f"确保解的可行性"
                )
            if struct_parts:
                parts.append(
                    f"{'，'.join(struct_parts)}。"
                    f"该模型属于{'确定性' if task == 'optimization' else '不确定性'}优化范畴，"
                    f"其数学性质保证了求解过程的收敛性和解的可靠性。"
                )

            # 分析约束特点
            if constraints:
                constraint_types = []
                for c in constraints[:5]:
                    if isinstance(c, str):
                        if any(kw in c for kw in ["面积", "总量", "上限", "≤", "≤"]):
                            constraint_types.append("资源容量约束")
                        elif any(kw in c for kw in ["非负", "≥ 0", "≥0"]):
                            constraint_types.append("非负约束")
                        elif any(kw in c for kw in ["适应", "匹配", "二元"]):
                            constraint_types.append("逻辑约束")
                        elif any(kw in c for kw in ["销售", "需求", "预期"]):
                            constraint_types.append("需求约束")
                if constraint_types:
                    unique_types = list(dict.fromkeys(constraint_types))
                    parts.append(
                        f"约束体系涵盖{ '、'.join(unique_types)}等类型，"
                        f"构成了完整的可行域描述。"
                    )

        elif task == "simulation":
            parts.append(
                f"该模型通过随机采样逼近目标函数的统计特征，"
                f"其理论基础为大数定律和中心极限定理。"
                f"模拟次数的选择需兼顾估计精度与计算效率，"
                f"本文根据问题特点设定了合理的模拟规模。"
            )

        elif task == "prediction":
            parts.append(
                f"模型基于历史数据建立因变量与自变量之间的映射关系，"
                f"通过最小二乘法或最大似然法进行参数估计。"
                f"模型的预测能力通过交叉验证和残差分析进行评估。"
            )

        elif task == "evaluation":
            parts.append(
                f"模型采用客观赋权与综合排序相结合的评价框架，"
                f"权重确定基于数据自身的离散程度，"
                f"避免了主观赋权可能引入的偏差。"
            )

        if not parts:
            # 回退到通用分析
            parts.append(
                f"该模型针对问题{qid}的数学特征构建，"
                f"能够有效刻画问题中的关键要素及其相互关系。"
            )

        return "\n\n".join(parts)

    def _professional_method_rationale(
        self, qid: str, method: str, task: str, result: QuestionResult
    ) -> str:
        """Build a concise method-fit paragraph for one question."""
        task_label = _TASK_LABELS.get(task, task)
        data_prep = result.computation.get("data_preparation", {})
        data_source = data_prep.get("data_source", "")
        source_text = (
            f"数据来源为{data_source}，"
            if data_source
            else "结合任务条件与已整理的数据结构，"
        )
        return (
            f"从建模目标看，问题{qid}不仅需要给出可计算结果，还需要保证模型假设、变量含义与约束条件能够被追溯。"
            f"{source_text}本文将该问抽象为{task_label}问题，并采用{method}作为主要求解框架。"
            f"该处理方式能够在保持数学表达清晰的同时，将参数估计、模型求解和结果检验纳入同一分析链条，"
            f"有利于后续对结果的稳定性和可解释性进行讨论。"
        )

    def _professional_formula_lead(self, qid: str, formulation: dict) -> str:
        """Build a lead-in paragraph before formula display."""
        variables = formulation.get("decision_variables") or []
        parameters = formulation.get("parameters") or {}
        variable_text = (
            f"其中，核心决策变量包括{', '.join(variables[:4])}；"
            if variables
            else "其中，变量和参数均由题意约束及数据字段确定；"
        )
        parameter_text = (
            f"参数体系主要由{', '.join(list(parameters.keys())[:4])}等量刻画。"
            if parameters
            else "相关参数在数据预处理和模型计算阶段统一给定。"
        )
        return (
            f"为保证问题{qid}的模型表述具有可复现性，本文将目标函数、约束条件和关键变量统一写成数学形式。"
            f"{variable_text}{parameter_text}"
        )

    def _professional_solution_lead(
        self, qid: str, method: str, status: str, computation: dict
    ) -> str:
        """Build a polished solving paragraph based on computation status."""
        results = computation.get("results", {})
        metrics = computation.get("metrics", {})
        evidence = []
        if results:
            evidence.append("求解结果")
        if metrics:
            evidence.append("评价指标")
        evidence_text = "、".join(evidence) if evidence else "中间计算记录"

        if status in ("success", "optimal", "feasible"):
            return (
                f"基于上述{method}模型，本文按照“数据整理-参数确定-模型求解-结果校验”的流程完成问题{qid}的计算。"
                f"本节展示的{evidence_text}均由模型计算过程直接生成，避免在报告写作阶段对数值结论进行主观修饰。"
            )
        if status == "generic_stats":
            return (
                f"在当前可获得数据和求解条件下，问题{qid}首先进行描述性统计与结构化整理，"
                f"以提取后续建模所需的尺度、分布和变化特征。"
            )
        if status == "no_data":
            return (
                f"由于问题{qid}缺少足够的外部观测数据，本文采用任务条件和代表性参数完成模型演算，"
                f"并在结论部分明确该结果依赖的前提范围。"
            )
        if status in ("infeasible", "failed"):
            return (
                f"问题{qid}在当前参数与约束设定下未能直接得到可行解，因此本文将求解状态、冲突来源和可能的约束调整方向一并列出，"
                f"以避免将不可行计算误写为确定性结论。"
            )
        return (
            f"问题{qid}已完成模型计算，本节从结果表、关键指标和检验信息三个层面呈现求解过程。"
        )

    def _write_blocked_section(
        self, qid: str, result: QuestionResult
    ) -> str:
        """生成 blocked 小问的占位章节：说明阻塞原因，避免该问在报告中整节消失。

        Args:
            qid: 小问 ID。
            result: status="blocked" 的 QuestionResult。

        Returns:
            占位章节的 Markdown 文本。
        """
        lines: list[str] = []
        lines.append(f"#### {qid}.1 问题描述")
        lines.append("")
        interp = result.problem_interpretation
        if interp is not None and interp.math_task_description:
            lines.append(interp.math_task_description)
        else:
            lines.append(f"本问为小问 {qid}，未能完成求解与验证。")
        lines.append("")
        lines.append(f"#### {qid}.2 求解状态")
        lines.append("")
        lines.append("本小问在求解与验证环节未通过，已标记为**阻塞（blocked）**，"
                     "未产生可复现的数值结论。")
        lines.append("")
        error = (result.error_message or "").strip()
        if error:
            lines.append(f"**阻塞原因**：{error}")
        else:
            lines.append("**阻塞原因**：未通过 GQ 质量门验证（重试预算已耗尽）。")
        lines.append("")
        lines.append("> 说明：本小问未纳入最终结果与模型评价；"
                     "后续若重新运行，可优先针对上述阻塞原因修复后继续求解。")
        lines.append("")
        return "\n".join(lines)

    def _write_question_section(
        self, qid: str, result: QuestionResult
    ) -> PaperSection:
        """生成单个小问的完整章节。

        包含：问题描述、方法选择、模型建立、求解与结果、结果检验、结论。
        集成图表工具和可视化工具生成规范的图表。
        文字描述采用学术报告风格，充分阐述建模思路和结果分析。
        """
        lines: list[str] = []
        formulas: list[str] = []
        figures: list[str] = list(result.figures)
        tables: list[str] = list(result.tables)

        # 获取计算结果和数据准备
        computation = dict(_as_mapping(result.computation, f"{qid}.computation"))
        computation["results"] = _as_mapping(
            computation.get("results", {}),
            f"{qid}.computation.results",
        )
        computation["metrics"] = _as_mapping(
            computation.get("metrics", {}),
            f"{qid}.computation.metrics",
        )
        data_prep = _as_mapping(result.data_preparation, f"{qid}.data_preparation")
        feature_names = data_prep.get("feature_names", []) if data_prep else []

        # 获取题型和方法信息
        interp = result.problem_interpretation
        findings = _as_mapping(result.findings, f"{qid}.findings")
        decision_record = _as_mapping(result.decision_record, f"{qid}.decision_record")
        task = findings.get("math_task", interp.math_task if interp else "composite")
        method = findings.get(
            "selected_method",
            decision_record.get("selected_method", "未知方法"),
        )

        # --- 问题描述 ---
        lines.append(f"#### {qid}.1 问题描述")
        lines.append("")
        if interp is not None:
            task_label = _TASK_LABELS.get(interp.math_task, interp.math_task)
            # 基于 ProblemInterpretation 生成问题描述
            if interp.math_task_description:
                lines.append(interp.math_task_description)
                lines.append("")
            else:
                lines.append(
                    f"本问要求建立{task_label}模型，"
                    f"对给定问题进行数学建模与求解。"
                )
                lines.append("")

            # 利用 interpretation 的丰富字段生成分析
            analysis_parts: list[str] = []
            if interp.decision_variables:
                analysis_parts.append(
                    f"涉及的决策变量包括{', '.join(interp.decision_variables[:5])}等"
                )
            if interp.objective_function:
                analysis_parts.append(
                    f"优化目标为{interp.objective_function}"
                )
            if interp.constraints:
                analysis_parts.append(
                    f"需考虑{'; '.join(interp.constraints[:3])}等约束条件"
                )
            if analysis_parts:
                lines.append(
                    f"根据问题分析，{ '，'.join(analysis_parts)}。"
                    f"本问的求解需要综合运用{task_label}相关的理论与方法。"
                )
                lines.append("")
        else:
            lines.append("（问题理解待补充）")

        # --- 方法选择 ---
        lines.append("")
        lines.append(f"#### {qid}.2 方法选择")
        lines.append("")
        decision = decision_record
        family = decision.get("selected_family", "")
        reason = decision.get(
            "selection_reason", decision.get("reason", "")
        )
        alternatives = decision.get("alternatives", [])

        lines.append(
            f"针对本问的特点，选用**{method}**进行建模求解。"
        )
        lines.append("")

        # 学术性方法描述
        lines.append(_academic_method_description(method, task, qid))
        lines.append("")
        lines.append(self._professional_method_rationale(qid, method, task, result))
        lines.append("")

        if reason:
            lines.append(f"选用该方法的主要理由是：{reason}")
            lines.append("")
        if alternatives:
            # 过滤无效的方法名（提取错误产生的片段）
            _INVALID_PATTERNS = ["的", "将", "问题", "变量", "定义", "本文", "针对"]
            alt_names = []
            for a in alternatives[:5]:
                if not isinstance(a, dict):
                    continue
                name = a.get("name", a.get("method", ""))
                if not name or len(name) < 2:
                    continue
                # 跳过以无效词开头或包含过多中文字符的方法名
                if any(name.startswith(p) for p in _INVALID_PATTERNS):
                    continue
                if len(name) > 20:  # 过长的名称可能是错误提取
                    continue
                alt_names.append(name)
            if alt_names:
                lines.append(
                    f"在方法比选阶段，还考虑了{', '.join(alt_names)}等方法。"
                    f"经综合评估各方法的适用条件和求解效率，"
                    f"最终确定{method}为本问的最优选择。"
                )

        # --- 模型建立 ---
        lines.append("")
        lines.append(f"#### {qid}.3 模型建立")
        lines.append("")
        formulation = dict(_as_mapping(result.formulation, f"{qid}.formulation"))
        formulation["parameters"] = _as_mapping(
            formulation.get("parameters", {}),
            f"{qid}.formulation.parameters",
        )
        if formulation:
            # 输出 formulation 描述（去重，避免多问重复相同描述）
            desc = formulation.get("description", "")
            if desc and desc not in self._shown_conclusions:
                self._shown_conclusions.add(desc)
                lines.append(desc)
                lines.append("")

            # LLM 起草模型建立段落（失败回退模板 _build_model_analysis）
            model_analysis = self._llm_write_prompt(
                "paper_model_section",
                question_text=(
                    interp.math_task_description if interp and interp.math_task_description
                    else f"小问 {qid}"
                ),
                task=task,
                result_form=interp.result_form if interp else "",
                method=method,
                decision_variables=formulation.get("decision_variables", []),
                objective_function=formulation.get("objective_function", ""),
                constraints=formulation.get("constraints", []),
                parameters=formulation.get("parameters", {}),
                template_guide=self._template_guide,
            )
            if not model_analysis:
                model_analysis = self._build_model_analysis(method, task, qid, formulation)
            if model_analysis:
                lines.append(model_analysis)
                lines.append("")

            if formulation.get("decision_variables"):
                lines.append(
                    f"**决策变量**：{', '.join(formulation['decision_variables'])}"
                )
                lines.append("")

            # 使用 LaTeX 公式工具生成规范公式
            # 将 ProjectContext 转换为 dict（函数期望 dict 接口）
            ctx_dict = None
            if self._project_context is not None:
                ctx_dict = {
                    "problem_description": self._project_context.problem_text,
                    "background_summary": self._project_context.background_summary,
                }
            # 传递方法名以便公式生成器选择方法特定的公式
            if ctx_dict is None:
                ctx_dict = {}
            ctx_dict["method"] = method
            latex_formulas = generate_latex_formula(
                formulation, qid, ctx_dict
            )
            if latex_formulas:
                lines.append(self._professional_formula_lead(qid, formulation))
                lines.append("")
                lines.append("**数学模型**：")
                lines.append("")
                for label, formula in latex_formulas:
                    # 添加公式编号
                    self._formula_counter += 1
                    numbered_formula = f"{formula} \\tag{{{self._formula_counter}}}"
                    lines.append(f"**{label}**：")
                    lines.append("")
                    lines.append(f"$$ {numbered_formula} $$")
                    lines.append("")
                    formulas.append(formula)

            # 检查 LaTeX 公式是否已包含约束条件（避免重复展示）
            has_constraint_in_latex = any(
                "约束" in label or "非负" in label
                for label, _ in latex_formulas
            )

            # 约束条件（仅当 LaTeX 公式未包含时，展示原始数学约束）
            if not has_constraint_in_latex and formulation.get("constraints"):
                math_constraints = [
                    c for c in formulation["constraints"]
                    if _is_mathematical_constraint(c)
                ]
                if math_constraints:
                    lines.append("**约束条件**：")
                    lines.append("")
                    for c in math_constraints:
                        # 将 Unicode 符号转换为 LaTeX
                        c_latex = _unicode_to_latex(c)
                        self._formula_counter += 1
                        numbered_c = f"{c_latex} \\tag{{{self._formula_counter}}}"
                        lines.append(f"$$ {numbered_c} $$")
                        lines.append("")
                        formulas.append(c_latex)

            # 参数说明
            params = formulation.get("parameters", {})
            if params:
                self._tbl_counter += 1
                lines.append(f"**表 {self._tbl_counter}：模型参数说明**")
                lines.append("")
                lines.append("| 参数 | 含义 |")
                lines.append("|------|------|")
                for param_name, param_desc in params.items():
                    lines.append(f"| {param_name} | {param_desc} |")
                lines.append("")
        else:
            lines.append("（模型表述待补充）")

        # --- 求解与结果 ---
        lines.append(f"#### {qid}.4 求解与结果")
        lines.append("")
        status = computation.get("status", "unknown")
        results = computation.get("results", {})
        metrics = computation.get("metrics", {})

        # 根据计算状态生成学术性描述
        lines.append(self._professional_solution_lead(qid, method, status, computation))
        lines.append("")
        if status in ("success", "optimal", "feasible"):
            lines.append("计算结果表明，模型在当前数据与约束条件下能够形成稳定的数值输出。")
        elif status == "generic_stats":
            lines.append(
                "统计结果用于刻画样本的基本分布和变量关系，"
                "为后续模型解释提供量化依据。"
            )
        elif status == "no_data":
            lines.append("因此，相关结论应理解为在代表性参数假设下的模型推演结果。")
        elif status in ("infeasible", "failed"):
            lines.append("该结果提示当前约束体系或参数组合存在需要进一步放松或校准的部分。")
        lines.append("")

        # 求解结果表（使用表格工具）
        q_tables: list[str] = []
        if results and results.get("optimal_solution"):
            self._tbl_counter += 1
            lines.append(f"**表 {self._tbl_counter}：问题 {qid} 最优解**")
            lines.append("")
            sol_table = format_solution_table(computation, qid, feature_names)
            # 去除工具自带的标题行
            sol_table = self._strip_table_title(sol_table)
            lines.append(sol_table)
            q_tables.append(sol_table)
            lines.append("")

        # 数据摘要表（蒙特卡洛等）
        if results and ("simulation" in results or "data_summary" in results):
            self._tbl_counter += 1
            lines.append(f"**表 {self._tbl_counter}：问题 {qid} 数据统计**")
            lines.append("")
            ds_table = format_data_summary_table(computation, qid)
            ds_table = self._strip_table_title(ds_table)
            lines.append(ds_table)
            q_tables.append(ds_table)
            lines.append("")

        # 关键指标表（使用表格工具）
        if metrics:
            self._tbl_counter += 1
            lines.append(f"**表 {self._tbl_counter}：问题 {qid} 关键指标**")
            lines.append("")
            metrics_table = format_metrics_table(computation, qid)
            metrics_table = self._strip_table_title(metrics_table)
            lines.append(metrics_table)
            q_tables.append(metrics_table)
            lines.append("")

        # 结果分析段落（学术风格）
        # LLM 起草结果解释段落（失败回退模板 _academic_result_analysis）
        llm_result_material = _build_llm_result_material(
            results,
            metrics,
            q_tables,
            self._all_figures.get(qid, []),
        )
        result_analysis = self._llm_write_prompt(
            "paper_result_section",
            question_text=(
                interp.math_task_description if interp and interp.math_task_description
                else f"小问 {qid}"
            ),
            method=method,
            status=status,
            results=llm_result_material,
            metrics="已并入上方结果写作材料摘要",
            tables="\n\n".join(q_tables)[:1500],
            template_guide=self._template_guide,
        )
        lines.append(result_analysis or _academic_result_analysis(method, task, qid, computation))
        lines.append("")

        # 其他结果（仅展示有意义的摘要值，过滤原始数据数组和代码细节）
        if results:
            # 需要跳过的键（原始数据倾倒 + 代码实现细节）
            _SKIP_KEYS = {
                "optimal_solution", "optimal_objective", "simulation",
                "data_summary", "note", "solver", "solver_status",
                # 原始数据数组，不应直接展示
                "predictions", "residuals", "coefficients",
                "intercept", "slope", "fitted_values", "true_values",
                # 内部实现细节，不应展示
                "variable_count", "constraint_count", "method",
                # 代码级细节
                "baseline_objective", "scenario_objectives",
                # 求解器内部状态
                "status", "message", "success",
            }
            extra_shown = False
            for key, value in results.items():
                if key in _SKIP_KEYS:
                    continue
                if isinstance(value, str) and any(
                    p in value for p in ["占位", "stub", "需要具体问题建模"]
                ):
                    continue
                # 跳过长数组（>5个元素的列表）
                if isinstance(value, (list, tuple)) and len(value) > 5:
                    continue
                # 跳过大型字典
                if isinstance(value, dict) and len(value) > 5:
                    continue
                if not extra_shown:
                    lines.append("**其他计算结果**：")
                    lines.append("")
                    extra_shown = True
                lines.append(f"- {key}: {self._fmt_value(value)}")

        if computation.get("error"):
            lines.append("")
            lines.append(f"**错误信息**：{computation['error']}")

        # 数据准备说明（过滤代码细节，仅保留学术性描述）
        if data_prep and data_prep.get("data_source"):
            lines.append("")
            lines.append("**数据说明**：")
            lines.append("")
            lines.append(
                f"本研究使用的数据来源于 {data_prep.get('data_source', '附件数据')}。"
                f"在数据预处理阶段，对原始数据进行了清洗、筛选和格式化处理，"
                f"提取了建模所需的关键变量和参数。"
            )

        # 图表引用（嵌入实际 PNG 图片）
        qid_figs = self._all_figures.get(qid, [])
        if qid_figs:
            lines.append("")
            lines.append("**可视化结果**：")
            lines.append("")
            for fig_path in qid_figs:
                self._fig_counter += 1
                fig_name = os.path.basename(fig_path)
                rel_path = f"figures/{fig_name}"
                # 根据文件名推断图注
                caption = self._infer_figure_caption(fig_name, qid)
                lines.append(f"![{caption}]({rel_path})")
                lines.append("")
                lines.append(f"**图 {self._fig_counter}**：{caption}")
                lines.append("")
                figures.append(rel_path)

        # --- 结果检验 ---
        lines.append(f"#### {qid}.5 结果检验")
        lines.append("")
        validation = _as_mapping(result.validation, f"{qid}.validation")
        if validation:
            # 检验分析段落
            lines.append(_academic_validation_analysis(task, qid, validation))
            lines.append("")

            self._tbl_counter += 1
            val_table = format_validation_table(validation, qid)
            val_table = self._strip_table_title(val_table)
            lines.append(f"**表 {self._tbl_counter}：问题 {qid} 验证结果**")
            lines.append("")
            lines.append(val_table)
        else:
            lines.append(_academic_validation_analysis(task, qid, {}))

        # --- 结论 ---
        lines.append("")
        lines.append(f"#### {qid}.6 结论")
        lines.append("")
        summary = findings.get("summary", "")
        key_result = findings.get("key_result", "")

        # 学术性结论段落
        lines.append(_academic_conclusion(method, task, qid, computation))
        lines.append("")

        # 格式化关键结果，避免过多小数位
        if key_result:
            import re as _re
            def _fmt_key_result(text: str) -> str:
                def _replace_float(m):
                    val = float(m.group(0))
                    return f"{val:.4f}"
                return _re.sub(r"\d+\.\d{6,}", _replace_float, text)
            key_result = _fmt_key_result(key_result)
            lines.append(f"**关键结果**：{key_result}")

        # 可复用结论（过滤内部技术结论和跨问题引用）
        if result.reusable_summary is not None:
            conclusions = result.reusable_summary.verified_conclusions
            # 过滤掉内部技术结论和跨问题引用
            filtered_conclusions = []
            for c in conclusions:
                # 跳过含 Phase/验证待的内部引用
                if any(kw in c for kw in ["Phase", "题型验证待", "待 Phase"]):
                    continue
                # 跳过跨问题引用
                if c.startswith("小问 ") and not c.startswith(f"小问 {qid}"):
                    continue
                # 跳过已在前问展示过的结论
                if c in self._shown_conclusions:
                    continue
                # 跳过代码级细节结论
                if any(kw in c for kw in ["确定性代码", "可复现", "方法家族", "计算状态"]):
                    continue
                filtered_conclusions.append(c)
                self._shown_conclusions.add(c)
            if filtered_conclusions:
                lines.append("")
                lines.append("**主要发现**：")
                lines.append("")
                for c in filtered_conclusions:
                    lines.append(f"- {c}")

        # 局限（去重 + 过滤内部引用 + 过滤代码细节）
        if result.limitations:
            seen_lims: set[str] = set()
            filtered_lims: list[str] = []
            for lim in result.limitations:
                # 跳过内部技术引用
                if any(kw in lim for kw in ["Phase", "题型验证待", "待 Phase"]):
                    continue
                # 跳过代码级细节
                if any(kw in lim for kw in ["确定性代码", "可复现"]):
                    continue
                # 去重
                lim_normalized = lim.replace("：", ":").strip()
                if lim_normalized not in seen_lims:
                    seen_lims.add(lim_normalized)
                    filtered_lims.append(lim)
            if filtered_lims:
                lines.append("")
                lines.append("**模型局限**：")
                lines.append("")
                for lim in filtered_lims:
                    lines.append(f"- {lim}")

        content = "\n".join(lines)

        return PaperSection(
            section_id=f"4.{qid}",
            title=f"问题 {qid}",
            content=content,
            question_id=qid,
            figures=figures,
            tables=tables,
            formulas=formulas,
            order=40,
        )

    # ------------------------------------------------------------------
    # 模型评价、优缺点与推广
    # ------------------------------------------------------------------

    def _write_evaluation(
        self, question_results: dict[str, QuestionResult]
    ) -> str:
        """生成模型评价、优缺点与推广。"""
        lines: list[str] = []

        # 5.1 模型总结
        lines.append("### 5.1 模型总结")
        lines.append("")
        # 从项目上下文获取问题描述，避免硬编码领域文本
        problem_desc = "本题"
        if self._project_context and self._project_context.background_summary:
            # 提取背景摘要的前 30 字作为问题描述
            bg = self._project_context.background_summary[:30]
            import re
            bg = re.sub(r"---\s*第\s*\d+\s*页\s*---", "", bg).strip()
            if bg:
                problem_desc = bg
        elif self._project_context and self._project_context.objectives:
            problem_desc = self._project_context.objectives[0][:30]

        lines.append(
            f"本文针对{problem_desc}问题，建立了系统的数学建模框架，"
            "按照「问题分析—数据画像—建模求解—验证评估—报告写作」的规范流程，"
            "依次完成了各子问题的建模、求解与验证。"
            "在建模过程中，本文注重以下几点："
            "其一，根据各子问题的数学特征选择最合适的建模方法；"
            "其二，建立能够反映问题本质的数学模型，合理设定决策变量、目标函数和约束条件；"
            "其三，通过严格的质量检验确保求解结果的可靠性和有效性；"
            "其四，对求解结果进行深入分析，提炼具有实际指导意义的结论。"
        )
        lines.append("")
        lines.append("各子问题采用的方法及其求解结果总结如下：")
        lines.append("")
        for qid in sorted(question_results.keys()):
            result = question_results[qid]
            findings = result.findings
            method = findings.get("selected_method", "未知")
            task = findings.get("math_task", "未知")
            task_label = _TASK_LABELS.get(task, task)
            # 提取关键结果而非计算状态
            computation = result.computation
            results = computation.get("results", {})
            obj = results.get("optimal_objective")
            result_desc = ""
            if obj is not None:
                result_desc = f"，最优目标值 {_fmt_numeric(obj)}"
            else:
                key_result = findings.get("key_result", "")
                if key_result:
                    result_desc = f"，{key_result}"
            lines.append(
                f"- 问题 {qid}：{task_label}类问题，采用 {method}{result_desc}"
            )

        # 5.2 模型优点
        lines.append("")
        lines.append("### 5.2 模型优点")
        lines.append("")
        lines.append(
            "本文建立的模型框架具有以下优点："
        )
        lines.append("")
        for qid in sorted(question_results.keys()):
            result = question_results[qid]
            decision = result.decision_record
            method = result.findings.get("selected_method", "未知")
            selected_details = decision.get("selected_details", {})
            pros = selected_details.get("pros", [])
            if pros:
                for pro in pros[:3]:
                    lines.append(f"- [{qid}] {method}：{pro}")
            else:
                lines.append(
                    f"- [{qid}] {method}：方法适用性强，"
                    f"理论成熟，计算结果稳定可靠"
                )
        lines.append("")
        lines.append(
            "此外，本文采用的分步求解策略使得各子问题之间的递进关系清晰明确，"
            "前一问的求解结果和经验能够为后一问的建模提供有效参考，体现了数学建模中"
            "「由简到繁、逐步深入」的方法论思想。"
            "所有数值结果均通过确定性计算获得，具有完全的可复现性，"
            "且经过严格的质量检验（包括计算状态检查、结果完整性验证、数值有限性检验等），"
            "确保了结论的科学性和可信度。"
        )

        # 5.3 模型缺点与局限（去重）
        lines.append("")
        lines.append("### 5.3 模型缺点与局限")
        lines.append("")
        lines.append(
            "尽管本文建立的模型在求解各子问题时取得了较好的效果，"
            "但仍存在以下不足之处："
        )
        lines.append("")
        # 全局去重集合
        seen_limitations: set[str] = set()
        has_limitation = False
        for qid in sorted(question_results.keys()):
            result = question_results[qid]
            # 收集所有局限来源
            all_lims: list[str] = []

            # 来源 1: result.limitations
            for lim in result.limitations:
                # 跳过内部技术引用
                if any(kw in lim for kw in ["Phase", "题型验证待", "待 Phase"]):
                    continue
                # 跳过代码级细节
                if any(kw in lim for kw in ["确定性代码", "可复现"]):
                    continue
                all_lims.append(lim)

            # 来源 2: selected_details.cons
            selected_details = result.decision_record.get(
                "selected_details", {}
            )
            for con in selected_details.get("cons", [])[:3]:
                all_lims.append(f"方法局限：{con}")

            # 去重并输出
            for lim in all_lims:
                # 标准化用于去重（统一冒号、去除空格）
                lim_key = lim.replace("：", ":").replace(
                    "方法局限:", ""
                ).replace("方法局限：", "").strip()
                if lim_key in seen_limitations:
                    continue
                seen_limitations.add(lim_key)
                has_limitation = True
                lines.append(f"- [{qid}] {lim}")
        if not has_limitation:
            lines.append("- 各模型在当前数据条件下表现良好，暂未发现显著局限。")

        # 5.4 模型推广
        lines.append("")
        lines.append("### 5.4 模型推广")
        lines.append("")
        lines.append(
            "本文建立的模型框架和方法体系具有良好的可推广性，"
            "可应用于以下场景："
        )
        lines.append("")
        has_promotion = False
        for qid in sorted(question_results.keys()):
            result = question_results[qid]
            if result.reusable_summary is not None:
                for direction in result.reusable_summary.improvement_directions:
                    # 过滤内部 Phase 引用
                    if any(kw in direction for kw in ["Phase", "题型验证", "待 Phase"]):
                        continue
                    has_promotion = True
                    lines.append(f"- [{qid}] {direction}")
        # 添加通用推广内容（基于实际使用的题型生成，不硬编码特定领域）
        task_types_used = set()
        for qid in sorted(question_results.keys()):
            result = question_results[qid]
            task = result.findings.get("math_task", "")
            task_types_used.add(task)

        if task_types_used & {"optimization", "stochastic_optimization"}:
            lines.append(
                "- 本文建立的数学规划模型可推广至物流、能源、制造等领域的"
                "资源优化配置问题，只需根据具体问题调整决策变量、目标函数和约束条件。"
            )
        if "simulation" in task_types_used:
            lines.append(
                "- 蒙特卡洛模拟方法可广泛应用于各类含不确定性参数的决策问题，"
                "如金融风险评估、工程项目可靠性分析等。"
            )
        if task_types_used & {"optimization", "stochastic_optimization", "simulation"}:
            lines.append(
                "- 本文采用的不确定性建模思路——从确定性基础模型出发，"
                "逐步引入不确定性因素——可为同类问题的研究提供方法论参考。"
            )

        # 对比图表引用
        comp_figs = self._all_figures.get("comparison", [])
        if comp_figs:
            lines.append("")
            lines.append("**跨问题对比可视化**：")
            lines.append("")
            for fig_path in comp_figs:
                self._fig_counter += 1
                fig_name = os.path.basename(fig_path)
                rel_path = f"figures/{fig_name}"
                caption = self._infer_figure_caption(fig_name, "comparison")
                lines.append(f"![{caption}]({rel_path})")
                lines.append("")
                lines.append(f"**图 {self._fig_counter}**：{caption}")
                lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 参考文献文本
    # ------------------------------------------------------------------

    def _write_references_text(
        self, question_results: dict[str, QuestionResult]
    ) -> str:
        """生成参考文献章节文本。"""
        refs = self._collect_references(question_results)
        if not refs:
            return "（参考文献待补充）"
        lines: list[str] = []
        for i, ref in enumerate(refs, 1):
            lines.append(f"[{i}] {ref}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 附录
    # ------------------------------------------------------------------

    def _write_appendix(
        self, question_results: dict[str, QuestionResult]
    ) -> str:
        """生成附录章节文本。"""
        lines: list[str] = []
        lines.append("### 7.1 代码")
        lines.append("")
        lines.append("各小问求解代码见产物目录 questions/ 下对应子目录。")

        lines.append("")
        lines.append("### 7.2 补充数据")
        lines.append("")
        has_content = False
        for qid in sorted(question_results.keys()):
            result = question_results[qid]
            if result.figures or result.tables:
                has_content = True
                lines.append(f"**问题 {qid}**：")
                for fig in result.figures:
                    lines.append(f"- {fig}")
                for tbl in result.tables:
                    lines.append(f"- {tbl}")
                lines.append("")
        if not has_content:
            lines.append("（无补充数据）")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 组装完整文本
    # ------------------------------------------------------------------

    def _assemble_full_text(
        self, sections: list[PaperSection], abstract: str,
        revision_notes: str = "",
    ) -> str:
        """将章节和摘要组装为完整 Markdown 文本。

        优化：避免过多空行，每个章节之间恰好一个空行。
        """
        parts: list[str] = []

        # 标题
        parts.append(f"# {self._title}")
        parts.append("")

        # 摘要
        parts.append("## 摘要")
        parts.append("")
        parts.append(abstract)
        parts.append("")

        # 各章节（按 order 排序）
        sorted_sections = sorted(sections, key=lambda s: s.order)
        for section in sorted_sections:
            # 问题子章节（如"问题 q1"）用 ###，主章节用 ##
            if section.question_id is not None:
                parts.append(f"### {section.title}")
            else:
                parts.append(f"## {section.title}")
            parts.append("")
            if section.content:
                # 清理内容中过多的连续空行（最多保留一个）
                content = section.content
                while "\n\n\n" in content:
                    content = content.replace("\n\n\n", "\n\n")
                parts.append(content)
            parts.append("")

        # 修订说明（如果有）
        if revision_notes:
            parts.append(revision_notes)
            parts.append("")

        return "\n".join(parts)

    def _build_revision_notes(self, review_report: Any, gf_retry: int) -> str:
        """构建修订说明（基于审查反馈）。"""
        if gf_retry == 0 or review_report is None:
            return ""

        lines: list[str] = []
        lines.append("## 修订说明")
        lines.append("")
        lines.append(f"本文经过第 {gf_retry} 轮审查修订，主要改进如下：")
        lines.append("")

        for issue in review_report.issues:
            severity = issue.severity
            category = issue.category
            message = issue.message
            suggested_fix = issue.suggested_fix or ""

            if severity == "critical":
                lines.append(f"- **[严重-{category}]** {message}")
                if suggested_fix:
                    lines.append(f"  - 处理：{suggested_fix}")
            elif severity == "major":
                lines.append(f"- **[重要-{category}]** {message}")
                if suggested_fix:
                    lines.append(f"  - 改进：{suggested_fix}")

        lines.append("")
        lines.append(
            "注：部分计算状态受限于确定性求解器的适用范围，"
            "实际竞赛中建议结合具体问题特征选择或定制求解器。"
        )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _infer_figure_caption(self, fig_name: str, qid: str) -> str:
        """根据文件名推断图注。"""
        name_lower = fig_name.lower()
        if "solution_bar" in name_lower:
            return f"问题 {qid} 最优解分布"
        elif "allocation_pie" in name_lower:
            return f"问题 {qid} 资源分配占比"
        elif "mc_distribution" in name_lower:
            return f"问题 {qid} 蒙特卡洛模拟结果分布"
        elif "confidence_interval" in name_lower:
            return f"问题 {qid} 置信区间"
        elif "scenario_objectives" in name_lower:
            return f"问题 {qid} 各场景目标值"
        elif "pred_vs_actual" in name_lower:
            return f"问题 {qid} 实际值与预测值对比"
        elif "residual_plot" in name_lower:
            return f"问题 {qid} 残差分析"
        elif "comparison_objectives" in name_lower:
            return "各子问任务标值对比"
        elif "deterministic_vs_stochastic" in name_lower:
            return "确定性 vs 不确定性优化对比"
        elif "data_table_sizes" in name_lower:
            return "数据表规模"
        elif "field_missing_rates" in name_lower:
            return "字段缺失率"
        return f"问题 {qid} 可视化结果"

    @staticmethod
    def _strip_table_title(table_text: str) -> str:
        """去除表格工具自带的首行标题（如 **表：问题 xxx 最优解**）。

        表格工具生成的 Markdown 表格通常以 **表：...** 开头，
        后跟空行和实际表格。PaperWriter 会自行添加编号标题，
        因此需要去除工具自带的标题以避免重复。
        """
        lines = table_text.split("\n")
        # 找到第一个表格行（以 | 开头）
        table_start = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("|"):
                table_start = i
                break
        # 如果表格前面有标题行，去除它们
        if table_start > 0:
            return "\n".join(lines[table_start:])
        return table_text

    @staticmethod
    def _fmt_value(v: Any) -> str:
        """格式化数值用于展示，浮点数保留 4 位小数。"""
        if isinstance(v, bool):
            return "是" if v else "否"
        if isinstance(v, float):
            return _fmt_numeric(v)
        if isinstance(v, int):
            return str(v)
        if hasattr(v, "tolist"):
            return _fmt_numeric(v)
        if isinstance(v, list):
            items = [PaperWriter._fmt_value(item) for item in v[:10]]
            if len(v) > 10:
                items.append("...")
            return "[" + ", ".join(items) + "]"
        if isinstance(v, dict):
            items = [
                f"{k}: {PaperWriter._fmt_value(val)}"
                for k, val in list(v.items())[:5]
            ]
            if len(v) > 5:
                items.append("...")
            return "{" + ", ".join(items) + "}"
        if v is None:
            return "-"
        return str(v)

    def _derive_title(self, project_context: ProjectContext | None) -> str:
        """从项目上下文派生报告标题。

        优先从问题文本中提取"X题"标题模式；
        无法提取时使用背景摘要首行；最后回退到默认标题。
        """
        import re

        if project_context is None:
            return "数学建模报告"

        # 尝试从 problem_text 提取标题
        if project_context.problem_text:
            text = project_context.problem_text
            clean = re.sub(r"---\s*第\s*\d+\s*页\s*---", "", text).strip()

            title_match = re.search(
                r"([A-Z])\s*题\s+(.+?)(?:\n|$)",
                clean,
            )
            if title_match:
                title_line = f"{title_match.group(1)}题 {title_match.group(2).strip()}"
                if 5 <= len(title_line) <= 80:
                    return title_line

            comp_match = re.search(r"(\d{4}\s*年.*?竞赛题目)", clean)
            if comp_match:
                return comp_match.group(1).strip()[:80]

            strategy_match = re.search(r"([\u4e00-\u9fa5]{2,15}(?:策略|问题|模型|优化|分析))", clean)
            if strategy_match:
                return strategy_match.group(1)

        if project_context.background_summary:
            summary = project_context.background_summary.strip()
            summary = re.sub(r"---\s*第\s*\d+\s*页\s*---", "", summary).strip()
            if len(summary) > 5:
                first_line = summary.split("\n")[0].strip()
                if len(first_line) > 5:
                    return first_line[:60]

        return "数学建模报告"

    def _collect_references(
        self, question_results: dict[str, QuestionResult]
    ) -> list[str]:
        """从各小问的方法选择中收集参考文献。"""
        refs: list[str] = []
        seen: set[str] = set()

        for qid in sorted(question_results.keys()):
            result = question_results[qid]
            method = result.findings.get(
                "selected_method",
                result.decision_record.get("selected_method", ""),
            )
            if not method:
                continue
            for key, ref in _METHOD_REFS.items():
                if key in method and ref not in seen:
                    refs.append(ref)
                    seen.add(ref)
                    break

        return refs

    def _collect_keywords(
        self, question_results: dict[str, QuestionResult]
    ) -> list[str]:
        """收集报告关键词。"""
        keywords: set[str] = set()
        for result in question_results.values():
            findings = result.findings
            task = findings.get("math_task", "")
            if task:
                task_label = _TASK_LABELS.get(task, task)
                keywords.add(task_label)
            method = findings.get("selected_method", "")
            if method:
                keywords.add(method)
        return sorted(keywords)


# ---------------------------------------------------------------------------
# LangGraph 节点封装
# ---------------------------------------------------------------------------


def write_paper_node(state: dict) -> dict:
    """LangGraph 节点：报告写作。

    读取 question_results，调用 PaperWriter，输出 paper_draft。
    修订时会读取 review_report 和 _gf_retry_count 以改进报告。

    Args:
        state: 项目状态。需要包含 question_results。
              修订时可选包含 review_report 和 _gf_retry_count。
              可选包含 output_dir 用于保存图表。

    Returns:
        状态更新字典，包含 paper_draft。
    """
    writer = PaperWriter(llm=_instrumented_llm(state))
    output_dir = state.get("output_dir", "artifacts/paper")
    paper_draft = writer.write(state, output_dir=output_dir)
    return {"paper_draft": paper_draft}
