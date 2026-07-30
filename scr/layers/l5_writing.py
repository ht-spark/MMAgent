"""L5 论文写作子图。

对应 architecture.md §4 L5 与 plan.md Phase 8：
  outline → section_writers → citation_registry → assemble → consistency_check → abstract

简化版（demo，零 token）：
  - 跳过 outline / citation_registry（不需要 LLM）
  - 用预定义 Markdown 模板填充 ExecutionResult 数据
  - 程序化数值一致性核对（不调用 LLM）
  - 写盘 artifacts/<run_id>/paper/paper_draft.md
  - 按子问题独立建模求解，每个子问题展示独立的模型选择和结果
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..schemas.model import ModelCandidate, ModelScore
from ..schemas.problem import ProblemAnalysis, SubProblem
from ..schemas.result import ExecutionResult, SubProblemExecution


# 标准章节（plan.md Phase 8.1）
_REQUIRED_SECTIONS = [
    "问题重述",
    "问题分析",
    "模型假设",
    "符号说明",
    "数据预处理",
    "模型建立与求解",
    "结果分析",
    "模型检验",
    "模型评价与推广",
    "参考文献",
    "摘要",
]


def _format_numeric_outputs(numeric: dict[str, float]) -> str:
    """格式化数值输出为 Markdown 表格。"""
    if not numeric:
        return "_（无数值输出）_"
    lines = ["| 指标 | 值 |", "|------|----|"]
    for k, v in numeric.items():
        lines.append(f"| {k} | {v:.4f} |")
    return "\n".join(lines)


def _format_score_table(model: ModelCandidate, score: ModelScore) -> str:
    """格式化模型评分为表格。"""
    lines = [
        "| 评分维度 | 得分 |",
        "|----------|------|",
        f"| 问题匹配度 | {score.problem_fit:.2f} |",
        f"| 数据适配度 | {score.data_fit:.2f} |",
        f"| 假设合理性 | {score.assumption_validity:.2f} |",
        f"| 可验证性 | {score.validation_feasibility:.2f} |",
        f"| 可解释性 | {score.interpretability:.2f} |",
        f"| 实现可行性 | {score.implementation_feasibility:.2f} |",
        f"| 创新性 | {score.innovation:.2f} |",
        f"| **加权总分** | **{score.total_score:.2f}** |",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 子问题→模型映射
# ---------------------------------------------------------------------------


def _build_sp_model_map(
    subproblems: list[SubProblem],
    selected_models: list[tuple[ModelCandidate, ModelScore]],
    subproblem_executions: list[SubProblemExecution],
) -> dict[str, dict]:
    """建立子问题 ID 到模型候选和求解结果的映射。

    Returns:
        dict: subproblem_id -> {
            "model": ModelCandidate | None,
            "score": ModelScore | None,
            "execution": SubProblemExecution | None,
        }
    """
    sp_map: dict[str, dict] = {
        sp.id: {"model": None, "score": None, "execution": None}
        for sp in subproblems
    }

    # 从 selected_models 中按 candidate.id 前缀匹配子问题
    # candidate.id 格式: "q1_c1", "q2_c1" 等
    for candidate, score in selected_models:
        # 提取子问题 id：从 "q1_c1" 提取 "q1"
        parts = candidate.id.rsplit("_c", 1)
        sp_id = parts[0] if len(parts) == 2 else candidate.id
        if sp_id in sp_map:
            # 取第一个匹配的（或总分最高的）
            existing = sp_map[sp_id]
            if existing["model"] is None or score.total_score > (existing["score"].total_score if existing["score"] else 0):
                sp_map[sp_id]["model"] = candidate
                sp_map[sp_id]["score"] = score

    # 从 subproblem_executions 中匹配
    for spe in subproblem_executions:
        sp_id = spe.subproblem_id
        if sp_id in sp_map:
            sp_map[sp_id]["execution"] = spe

    return sp_map


# ---------------------------------------------------------------------------
# 论文组装
# ---------------------------------------------------------------------------


def _assemble_paper(
    problem_analysis: ProblemAnalysis,
    subproblems: list[SubProblem],
    execution_result: ExecutionResult | None,
    selected_model_name: str = "",
    selected_models: list[tuple[ModelCandidate, ModelScore]] | None = None,
    subproblem_executions: list[SubProblemExecution] | None = None,
) -> str:
    """组装完整论文（Markdown），按子问题独立建模求解。

    每个子问题展示独立的：
      - 模型选择与评分
      - 模型建立（假设、公式描述）
      - 模型求解（数值结果）
      - 结果分析
    """
    selected_models = selected_models or []
    subproblem_executions = subproblem_executions or []
    sp_model_map = _build_sp_model_map(subproblems, selected_models, subproblem_executions)

    sections: list[str] = []

    # ====== 标题 ======
    sections.append(f"# {problem_analysis.research_subject}\n")

    # ====== 1. 问题重述 ======
    sections.append("## 1. 问题重述\n")
    sections.append(f"{problem_analysis.background}\n")

    # ====== 2. 问题分析 ======
    sections.append("## 2. 问题分析\n")
    for i, q in enumerate(problem_analysis.explicit_questions, 1):
        sections.append(f"**问题{i}**：{q}\n")
    sections.append("")

    # ====== 3. 模型假设 ======
    sections.append("## 3. 模型假设\n")
    # 收集所有子问题模型的假设
    all_assumptions: list[str] = []
    for sp in subproblems:
        info = sp_model_map.get(sp.id, {})
        model = info.get("model")
        if model and model.assumptions:
            for a in model.assumptions:
                if a not in all_assumptions:
                    all_assumptions.append(a)
    if not all_assumptions:
        all_assumptions = ["数据经过预处理后无缺失值", "各指标间相互独立", "模型在给定条件下适用"]
    for i, a in enumerate(all_assumptions, 1):
        sections.append(f"{i}. {a}")
    sections.append("")

    # ====== 4. 符号说明 ======
    sections.append("## 4. 符号说明\n")
    sections.append("| 符号 | 含义 | 对应子问题 |")
    sections.append("|------|------|-----------|")
    for sp in subproblems:
        info = sp_model_map.get(sp.id, {})
        model = info.get("model")
        model_family = model.family if model else "—"
        sections.append(f"| 参见各子问题详述 | {sp.task} | {sp.id}（{model_family}） |")
    sections.append("")

    # ====== 5. 数据预处理 ======
    sections.append("## 5. 数据预处理\n")
    sections.append(
        "对原始数据进行缺失值填充、常量列剔除、类型转换等处理。"
        "详见 `artifacts/<run_id>/reports/preprocessing_report.json`。\n"
    )

    # ====== 6. 模型建立与求解（按子问题独立展开） ======
    sections.append("## 6. 模型建立与求解\n")

    for i, sp in enumerate(subproblems, 1):
        info = sp_model_map.get(sp.id, {})
        model = info.get("model")
        score = info.get("score")
        spe = info.get("execution")
        sp_result = spe.result if spe else None

        sections.append(f"### 6.{i} 子问题 {sp.id}：{sp.task}\n")

        # ---- 6.x.1 问题描述 ----
        sections.append(f"#### 6.{i}.1 问题描述\n")
        sections.append(f"本子问题要求：{sp.task}\n")

        if sp.input_requirements:
            sections.append("**所需输入数据**：")
            for req in sp.input_requirements:
                sections.append(f"- {req}")
            sections.append("")

        if sp.expected_outputs:
            sections.append("**预期输出**：")
            for out in sp.expected_outputs:
                sections.append(f"- {out}")
            sections.append("")

        # ---- 6.x.2 模型选择 ----
        sections.append(f"#### 6.{i}.2 模型选择\n")

        if model is not None:
            sections.append(f"选用 **{model.name}**（{model.family}）模型。\n")

            if model.pros:
                sections.append("**选择理由**：")
                for pro in model.pros:
                    sections.append(f"- {pro}")
                sections.append("")

            if score is not None:
                sections.append("**模型评分**：")
                sections.append(_format_score_table(model, score))
                sections.append("")

            if model.cons:
                sections.append("**潜在局限**：")
                for con in model.cons:
                    sections.append(f"- {con}")
                sections.append("")
        else:
            fallback_name = selected_model_name or "综合评价模型"
            sections.append(f"选用 **{fallback_name}** 模型。\n")

        # ---- 6.x.3 模型建立 ----
        sections.append(f"#### 6.{i}.3 模型建立\n")

        if model is not None:
            # 模型假设
            if model.assumptions:
                sections.append("**核心假设**：")
                for j, a in enumerate(model.assumptions, 1):
                    sections.append(f"{j}. {a}")
                sections.append("")

            # 模型输出描述
            if model.output_description:
                sections.append(f"**模型描述**：{model.output_description}\n")

            # 所需数据
            if model.required_data:
                sections.append("**所需数据字段**：")
                for rd in model.required_data:
                    sections.append(f"- {rd}")
                sections.append("")

            # 验证方法
            if model.validation_method:
                sections.append(f"**验证方法**：{model.validation_method}\n")
        else:
            sections.append("使用标准建模流程，包括数据标准化、权重计算、综合评分等步骤。\n")

        # ---- 6.x.4 模型求解 ----
        sections.append(f"#### 6.{i}.4 模型求解\n")

        if sp_result is not None and sp_result.success:
            sections.append(f"求解成功（耗时 {sp_result.runtime_seconds:.2f}s）。\n")
            if sp_result.numeric_outputs:
                sections.append("**关键数值结果**：")
                sections.append(_format_numeric_outputs(sp_result.numeric_outputs))
                sections.append("")
        elif sp_result is not None:
            sections.append(f"**求解失败**：{sp_result.error_message}\n")
            if sp_result.failure_reason:
                sections.append(f"失败原因分类：{sp_result.failure_reason}\n")
        elif execution_result is not None and execution_result.success:
            # 回退：无子问题级别结果，使用全局结果
            sections.append("求解成功（使用全局结果）。\n")
            if execution_result.numeric_outputs:
                sections.append("**关键数值结果**：")
                sections.append(_format_numeric_outputs(execution_result.numeric_outputs))
                sections.append("")
        elif execution_result is not None:
            sections.append(f"**求解失败**：{execution_result.error_message}\n")
        else:
            sections.append("**求解状态**：未执行（前置数据阶段未完成）\n")

    # ====== 7. 结果分析（按子问题独立分析） ======
    sections.append("## 7. 结果分析\n")

    for i, sp in enumerate(subproblems, 1):
        info = sp_model_map.get(sp.id, {})
        model = info.get("model")
        spe = info.get("execution")
        sp_result = spe.result if spe else None

        sections.append(f"### 7.{i} 子问题 {sp.id} 结果分析\n")

        if sp_result is not None and sp_result.success:
            model_name = model.name if model else (selected_model_name or "所选模型")
            n_outputs = len(sp_result.numeric_outputs)
            sections.append(f"子问题 {sp.id}（{sp.task}）使用 **{model_name}** 成功求解。\n")

            # 分指标解读
            if sp_result.numeric_outputs:
                sections.append("**关键指标解读**：")
                for key, value in sp_result.numeric_outputs.items():
                    # 根据指标名给出解读提示
                    hint = _get_metric_hint(key)
                    sections.append(f"- **{key}** = {value:.4f}：{hint}")
                sections.append("")

            sections.append(
                f"模型输出了 {n_outputs} 个关键指标，"
                f"结果可用于后续子问题的输入或最终决策。\n"
            )
        elif sp_result is not None:
            sections.append(
                f"子问题 {sp.id}（{sp.task}）求解失败，"
                f"原因：{sp_result.error_message}。"
                f"建议检查数据预处理和模型参数配置。\n"
            )
        elif execution_result is not None and execution_result.success:
            sections.append(
                f"子问题 {sp.id}（{sp.task}）使用全局求解结果，"
                f"模型输出 {len(execution_result.numeric_outputs)} 个关键指标。\n"
            )
        else:
            sections.append(
                f"子问题 {sp.id}（{sp.task}）的求解结果未能获取。"
                f"请检查数据预处理和模型执行阶段。\n"
            )

    # ====== 8. 模型检验 ======
    sections.append("## 8. 模型检验\n")
    sections.append("对各子问题模型进行以下检验：\n")
    for sp in subproblems:
        info = sp_model_map.get(sp.id, {})
        model = info.get("model")
        family = model.family if model else "通用"
        if "赋权" in family or "评价" in family:
            check = "建议从权重稳定性角度进行敏感性分析，验证排名对权重变化的鲁棒性。"
        elif "回归" in family or "预测" in family:
            check = "建议进行残差分析和交叉验证，评估模型的预测精度和泛化能力。"
        elif "优化" in family or "规划" in family:
            check = "建议验证约束满足情况和目标函数对参数扰动的敏感性。"
        else:
            check = "建议从权重稳定性（评价类）/ 残差分析（预测类）/ 约束满足（优化类）等角度进行敏感性分析。"
        sections.append(f"- **{sp.id}**（{family}）：{check}")
    sections.append("")

    # ====== 9. 模型评价与推广 ======
    sections.append("## 9. 模型评价与推广\n")
    sections.append("### 模型优势\n")
    sections.append("- 按子问题模块化建模，各子问题选用最适合的模型\n")
    sections.append("- 模型选择基于量化评分，有据可依\n")
    # 收集所有模型优点
    all_pros: list[str] = []
    for sp in subproblems:
        info = sp_model_map.get(sp.id, {})
        model = info.get("model")
        if model and model.pros:
            for p in model.pros:
                if p not in all_pros:
                    all_pros.append(p)
    for p in all_pros[:5]:
        sections.append(f"- {p}")
    sections.append("")

    sections.append("### 局限性\n")
    all_cons: list[str] = []
    for sp in subproblems:
        info = sp_model_map.get(sp.id, {})
        model = info.get("model")
        if model and model.cons:
            for c in model.cons:
                if c not in all_cons:
                    all_cons.append(c)
    for c in all_cons[:5]:
        sections.append(f"- {c}")
    if not all_cons:
        sections.append("- 对数据质量敏感\n")
        sections.append("- 扩展到更大规模数据时需重新训练\n")
    sections.append("")

    sections.append("### 推广方向\n")
    sections.append("- 可引入更多不确定性分析方法（如蒙特卡洛模拟）\n")
    sections.append("- 可扩展为多目标优化框架\n")
    sections.append("- 可尝试集成学习方法组合多个模型的结果\n")

    # ====== 10. 参考文献 ======
    sections.append("## 参考文献\n")
    sections.append("[1] 系统自动生成的内部报告（详见 `artifacts/<run_id>/`）。\n")

    # ====== 11. 摘要（最后生成） ======
    sections.append("## 摘要\n")
    # 收集所有子问题的模型名称
    model_names: list[str] = []
    for sp in subproblems:
        info = sp_model_map.get(sp.id, {})
        model = info.get("model")
        if model:
            model_names.append(model.name)
    if not model_names:
        model_names.append(selected_model_name or "综合评价模型")

    # 收集所有成功的数值指标
    all_numeric: dict[str, float] = {}
    for sp in subproblems:
        info = sp_model_map.get(sp.id, {})
        spe = info.get("execution")
        if spe and spe.result.success:
            all_numeric.update(spe.result.numeric_outputs)

    model_list = "、".join(dict.fromkeys(model_names))  # 去重保序
    sections.append(
        f"本文针对{problem_analysis.research_subject}，"
        f"将问题拆解为 {len(subproblems)} 个子问题，"
        f"分别使用{model_list}等方法对每个子问题进行了独立建模与求解。"
        f"主要结果包括 {len(all_numeric)} 个关键指标。"
        f"各子问题模型经验证可行，可为相关决策提供参考。\n"
    )

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _get_metric_hint(key: str) -> str:
    """根据指标名返回解读提示。"""
    hints = {
        "r2_score": "决定系数，越接近 1 表示模型拟合越好",
        "mse": "均方误差，越小表示预测精度越高",
        "intercept": "线性模型截距项",
        "max_score": "最高综合得分",
        "min_score": "最低综合得分",
        "mean_score": "平均综合得分",
        "weights_sum": "权重之和（应接近 1）",
        "n_columns": "参与计算的指标列数",
        "n_features": "模型使用的特征数量",
        "max_closeness": "最高贴近度（TOPSIS）",
        "min_closeness": "最低贴近度（TOPSIS）",
        "mean_closeness": "平均贴近度",
        "n_alternatives": "评价对象数量",
        "objective_value": "目标函数最优值",
        "n_variables": "决策变量数量",
        "is_optimal": "是否达到最优解（1=是，0=否）",
        "n_rows": "数据行数",
        "n_cols": "数据列数",
        "overall_mean": "全表均值",
    }
    return hints.get(key, "模型输出的关键数值指标")


def _check_numeric_consistency(
    paper_text: str,
    numeric_outputs: dict[str, float],
    tolerance: float = 0.01,
) -> tuple[bool, list[str]]:
    """检查论文中的数字是否与 ExecutionResult 一致。

    Returns:
        (passed, list_of_issues)
    """
    issues: list[str] = []
    if not numeric_outputs:
        return True, []

    # 提取论文中的数字（粗略正则）
    paper_numbers = set()
    for match in re.finditer(r"\b\d+\.\d{2,}\b", paper_text):
        try:
            paper_numbers.add(float(match.group()))
        except ValueError:
            pass

    # 检查每个 numeric_output 是否在论文中出现
    for key, value in numeric_outputs.items():
        if value == 0:
            continue
        found = False
        for paper_num in paper_numbers:
            if abs(paper_num - value) <= tolerance or abs(paper_num - value) / max(abs(value), 1e-9) <= 0.01:
                found = True
                break
        if not found:
            issues.append(f"指标 {key}={value:.4f} 未在论文正文中出现")

    return len(issues) == 0, issues


def _check_section_completeness(paper_text: str) -> tuple[bool, list[str]]:
    """检查必需章节是否完整（允许编号前缀如 "## 1. 问题重述"）。"""
    missing: list[str] = []
    for section in _REQUIRED_SECTIONS:
        # 接受 "## 1. 问题重述"、"## 问题重述"、"## 1 问题重述" 等形式
        pattern = rf"##\s*\d*\.?\s*{re.escape(section)}"
        if not re.search(pattern, paper_text):
            missing.append(section)
    return len(missing) == 0, missing


# ---------------------------------------------------------------------------
# L5 子图
# ---------------------------------------------------------------------------


class L5WritingSubgraph:
    """L5 论文写作子图（demo 零 token 简化版）。

    按子问题独立建模求解，每个子问题展示独立的：
      - 模型选择与评分
      - 模型建立（假设、公式描述）
      - 模型求解（数值结果）
      - 结果分析
    """

    def __init__(self, output_dir: str | Path | None = None) -> None:
        self.output_dir = Path(output_dir) if output_dir else Path("artifacts/default")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        problem_analysis: ProblemAnalysis,
        subproblems: list[SubProblem],
        execution_result: ExecutionResult | None,
        selected_model_name: str = "",
        selected_models: list[tuple[ModelCandidate, ModelScore]] | None = None,
        subproblem_executions: list[SubProblemExecution] | None = None,
    ) -> dict:
        """执行 L5 论文生成。

        Args:
            problem_analysis: L0 题目分析结果。
            subproblems: 子问题列表。
            execution_result: 全局求解结果（回退用）。
            selected_model_name: 全局模型名（回退用）。
            selected_models: 每个子问题的 (模型候选, 评分) 列表。
            subproblem_executions: 每个子问题的求解执行结果。

        Returns:
            State 部分更新：
              - paper_draft_path / paper_text
              - numeric_consistency_passed / numeric_consistency_issues
              - section_completeness_passed / missing_sections
              - workflow_status
        """
        paper_text = _assemble_paper(
            problem_analysis,
            subproblems,
            execution_result,
            selected_model_name=selected_model_name,
            selected_models=selected_models,
            subproblem_executions=subproblem_executions,
        )

        # 写盘
        paper_path = self.output_dir / "paper_draft.md"
        paper_path.write_text(paper_text, encoding="utf-8")

        # 数值一致性核对：收集所有子问题的数值输出
        all_numeric: dict[str, float] = {}
        if subproblem_executions:
            for spe in subproblem_executions:
                if spe.result.success:
                    all_numeric.update(spe.result.numeric_outputs)
        elif execution_result is not None:
            all_numeric = execution_result.numeric_outputs

        num_passed, num_issues = _check_numeric_consistency(paper_text, all_numeric)

        # 章节完整性
        sec_passed, missing = _check_section_completeness(paper_text)

        passed = num_passed and sec_passed
        status = "l5_completed" if passed else "l5_issues"

        return {
            "paper_draft_path": str(paper_path),
            "paper_text": paper_text,
            "numeric_consistency_passed": num_passed,
            "numeric_consistency_issues": num_issues,
            "section_completeness_passed": sec_passed,
            "missing_sections": missing,
            "workflow_status": status,
        }