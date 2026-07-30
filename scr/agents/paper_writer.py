"""论文写作 Agent（architecture.md §6.2）。

职责：
  从已验证的 QuestionResult 生成完整竞赛论文草稿。

设计要点：
  - 确定性模板：不依赖 LLM，使用固定模板生成 Markdown
  - 集成可视化工具：自动生成 PNG 图表并嵌入论文
  - 集成表格工具：生成规范三线表格式
  - 集成 LaTeX 公式：生成规范数学公式
  - 每个小问对应完整的"问题 - 方法 - 结果 - 检验 - 结论"叙述
  - 公式、图、表编号并在正文引用
  - 计算数值来自 QuestionResult.computation
  - 摘要最后生成，不引入新数字
"""
from __future__ import annotations

import os
from typing import Any

from ..schemas.context import DataProfile, ProjectContext
from ..schemas.paper import PaperDraft, PaperSection
from ..schemas.question import QuestionResult
from ..tools.visualization_tools import generate_all_figures
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
    """论文写作 Agent（确定性模板，无 LLM）。

    从已验证的小问结果包生成完整论文草稿，
    遵循 architecture.md §6.2 推荐章节结构。
    集成可视化工具生成 PNG 图表，集成表格工具生成规范三线表。

    Usage::

        writer = PaperWriter()
        paper = writer.write(state, output_dir="artifacts/run_xxx")
    """

    def __init__(self) -> None:
        self._title: str = "数学建模论文"
        self._output_dir: str = ""
        self._all_figures: dict[str, list[str]] = {}
        self._fig_counter: int = 0
        self._tbl_counter: int = 0
        self._shown_conclusions: set[str] = set()

    # ------------------------------------------------------------------
    # 主方法
    # ------------------------------------------------------------------

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
        raw_results: dict[str, QuestionResult] = state.get("question_results", {})
        project_context: ProjectContext | None = state.get("project_context")
        data_profile: DataProfile | None = state.get("data_profile")
        review_report = state.get("review_report")
        gf_retry = state.get("_gf_retry_count", 0)

        # 只使用已验证的结果
        validated: dict[str, QuestionResult] = {
            qid: r for qid, r in raw_results.items() if r.status == "validated"
        }

        if gf_retry > 0:
            print(f"[writer] 第 {gf_retry} 次修订，基于审查反馈改进论文")
        print(f"[writer] 开始论文写作: {len(validated)} 个已验证小问")

        # 设置输出目录
        self._output_dir = output_dir or state.get("output_dir", "artifacts/paper")
        self._fig_counter = 0
        self._tbl_counter = 0
        self._shown_conclusions = set()

        # 生成所有图表 PNG
        if validated:
            try:
                self._all_figures = generate_all_figures(
                    validated, data_profile, self._output_dir
                )
                total_figs = sum(len(v) for v in self._all_figures.values())
                print(f"[writer] 已生成 {total_figs} 张图表")
            except Exception as e:
                print(f"[writer] 图表生成失败（不影响论文写作）: {e}")
                self._all_figures = {}

        # 派生标题
        self._title = self._derive_title(project_context)

        # 构建大纲
        sections = self._build_outline(validated)

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
                section.content = self._write_question_intro(validated)
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

        # 生成摘要（最后生成，不引入新数字）
        abstract = self._write_abstract(validated, sections)

        # 组装完整 Markdown 文本
        revision_notes = self._build_revision_notes(review_report, gf_retry)
        full_text = self._assemble_full_text(sections, abstract, revision_notes)

        # 收集引用列表
        references = self._collect_references(validated)

        print(
            f"[writer] 论文写作完成: {self._title} "
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
    # 大纲构建
    # ------------------------------------------------------------------

    def _build_outline(
        self, question_results: dict[str, QuestionResult]
    ) -> list[PaperSection]:
        """构建论文大纲。

        按 architecture.md §6.2 推荐章节顺序创建章节骨架，
        包括固定章节和按小问数量动态生成的小问子章节。
        """
        sections: list[PaperSection] = []
        sorted_qids = sorted(question_results.keys())

        sections.append(
            PaperSection(section_id="1", title="问题重述与问题分析", order=10)
        )
        sections.append(
            PaperSection(section_id="2", title="模型假设与符号说明", order=20)
        )
        sections.append(
            PaperSection(section_id="3", title="数据说明与预处理", order=30)
        )
        sections.append(
            PaperSection(
                section_id="4",
                title="各小问的模型建立、求解、结果和检验",
                order=40,
            )
        )

        for i, qid in enumerate(sorted_qids, start=1):
            sections.append(
                PaperSection(
                    section_id=f"4.{i}",
                    title=f"问题 {qid}",
                    question_id=qid,
                    order=40 + i,
                )
            )

        sections.append(
            PaperSection(section_id="5", title="模型评价、优缺点与推广", order=50)
        )
        sections.append(PaperSection(section_id="6", title="参考文献", order=60))
        sections.append(
            PaperSection(section_id="7", title="附录", order=70)
        )

        return sections

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
        """
        lines: list[str] = []
        sorted_qids = sorted(question_results.keys())
        n = len(sorted_qids)

        # 问题背景概述
        lines.append(
            f"本文针对给定的数学建模问题，建立了完整的求解框架，"
            f"共完成 {n} 个子问题的建模与求解。"
        )
        lines.append("")

        # 方法论概述
        method_set = set()
        task_set = set()
        for result in question_results.values():
            findings = result.findings
            method_set.add(findings.get("selected_method", ""))
            task_set.add(findings.get("math_task", ""))
        methods_str = "、".join(sorted(m for m in method_set if m))
        lines.append(
            f"本文综合运用{methods_str}等方法，"
            f"对问题进行系统建模、求解与验证。"
        )
        lines.append("")

        # 各问关键结果
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
                    result_summary = f"R^2 = {r2:.4f}"
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

        # 总体结论
        lines.append("")
        lines.append(
            "各模型均经过确定性验证，数值结果可复现。"
            "本文建立的模型框架具有良好的可靠性和可解释性，"
            "可为同类数学建模问题提供参考。"
        )

        # 关键词
        keywords = self._collect_keywords(question_results)
        if keywords:
            lines.append("")
            lines.append("**关键词**：" + "；".join(keywords))

        return "\n".join(lines)

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
            "最后整合各问结果完成论文写作。"
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
        self, question_results: dict[str, QuestionResult]
    ) -> str:
        """生成各小问章节的引导段落。"""
        n = len(question_results)

        # 汇总对比表
        comparison_table = format_comparison_table(question_results)
        comparison_table = self._strip_table_title(comparison_table)
        self._tbl_counter += 1

        lines: list[str] = [
            f"本章对 {n} 个子问题分别进行模型建立、求解、结果分析和检验。",
            '每个子问题遵循"问题 - 方法 - 结果 - 检验 - 结论"的完整叙述结构。',
            "",
            f"**表 {self._tbl_counter}：各子问题求解结果汇总**",
            "",
            comparison_table,
        ]

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 单问章节
    # ------------------------------------------------------------------

    def _write_question_section(
        self, qid: str, result: QuestionResult
    ) -> PaperSection:
        """生成单个小问的完整章节。

        包含：问题描述、方法选择、模型建立、求解与结果、结果检验、结论。
        集成图表工具和可视化工具生成规范的图表。
        """
        lines: list[str] = []
        formulas: list[str] = []
        figures: list[str] = list(result.figures)
        tables: list[str] = list(result.tables)

        # 获取计算结果和数据准备
        computation = result.computation
        data_prep = result.data_preparation
        feature_names = data_prep.get("feature_names", []) if data_prep else []

        # --- 问题描述 ---
        lines.append(f"#### {qid}.1 问题描述")
        lines.append("")
        interp = result.problem_interpretation
        if interp is not None:
            task_label = _TASK_LABELS.get(interp.math_task, interp.math_task)
            lines.append(f"本题的数学任务类型为 **{task_label}**。")
            if interp.math_task_description:
                lines.append("")
                lines.append(interp.math_task_description)
            if interp.result_form:
                lines.append("")
                lines.append(f"预期输出形式：{interp.result_form}。")
            if interp.relation_to_previous != "independent":
                lines.append("")
                lines.append(
                    f"与前问关系：{interp.relation_to_previous}。"
                    f"{interp.relation_description}"
                )
        else:
            lines.append("（问题理解待补充）")

        # --- 方法选择 ---
        lines.append("")
        lines.append(f"#### {qid}.2 方法选择")
        lines.append("")
        decision = result.decision_record
        method = decision.get("selected_method", "未知方法")
        family = decision.get("selected_family", "未知")
        reason = decision.get(
            "selection_reason", decision.get("reason", "")
        )
        alternatives = decision.get("alternatives", [])

        lines.append(
            f"经过方法探索与决策，最终选用 **{method}**"
            f"（方法家族：{family}）。"
        )
        if reason:
            lines.append("")
            lines.append(f"选择理由：{reason}")
        if alternatives:
            alt_names = [
                a.get("name", a.get("method", "未知"))
                for a in alternatives[:5]
                if isinstance(a, dict)
            ]
            if alt_names:
                lines.append("")
                lines.append(f"候选方法包括：{', '.join(alt_names)} 等。")

        # --- 模型建立 ---
        lines.append("")
        lines.append(f"#### {qid}.3 模型建立")
        lines.append("")
        formulation = result.formulation
        if formulation:
            if formulation.get("description"):
                lines.append(formulation["description"])
                lines.append("")

            if formulation.get("decision_variables"):
                lines.append(
                    f"**决策变量**：{', '.join(formulation['decision_variables'])}"
                )
                lines.append("")

            # 使用 LaTeX 公式工具生成规范公式
            latex_formulas = generate_latex_formula(formulation, qid)
            if latex_formulas:
                lines.append("**数学模型**：")
                lines.append("")
                for label, formula in latex_formulas:
                    lines.append(f"**{label}**：")
                    lines.append("")
                    lines.append(f"$$ {formula} $$")
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
                        lines.append(f"$$ {c_latex} $$")
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
        status_label = _STATUS_LABELS.get(status, status)
        lines.append(f"计算状态：**{status_label}**")
        lines.append("")

        results = computation.get("results", {})
        metrics = computation.get("metrics", {})

        # 求解结果表（使用表格工具）
        if results and results.get("optimal_solution"):
            self._tbl_counter += 1
            lines.append(f"**表 {self._tbl_counter}：问题 {qid} 最优解**")
            lines.append("")
            sol_table = format_solution_table(computation, qid, feature_names)
            # 去除工具自带的标题行
            sol_table = self._strip_table_title(sol_table)
            lines.append(sol_table)
            lines.append("")

        # 数据摘要表（蒙特卡洛等）
        if results and ("simulation" in results or "data_summary" in results):
            self._tbl_counter += 1
            lines.append(f"**表 {self._tbl_counter}：问题 {qid} 数据统计**")
            lines.append("")
            ds_table = format_data_summary_table(computation, qid)
            ds_table = self._strip_table_title(ds_table)
            lines.append(ds_table)
            lines.append("")

        # 关键指标表（使用表格工具）
        if metrics:
            self._tbl_counter += 1
            lines.append(f"**表 {self._tbl_counter}：问题 {qid} 关键指标**")
            lines.append("")
            metrics_table = format_metrics_table(computation, qid)
            metrics_table = self._strip_table_title(metrics_table)
            lines.append(metrics_table)
            lines.append("")

        # 其他结果（仅展示有意义的摘要值，过滤原始数据数组）
        if results:
            # 需要跳过的键（原始数据倾倒）
            _SKIP_KEYS = {
                "optimal_solution", "optimal_objective", "simulation",
                "data_summary", "note", "solver", "solver_status",
                # 原始数据数组，不应直接展示
                "predictions", "residuals", "coefficients",
                "intercept", "slope", "fitted_values", "true_values",
                # 内部实现细节，不应展示
                "variable_count", "constraint_count", "method",
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

        # 数据准备说明
        if data_prep and data_prep.get("data_source"):
            lines.append("")
            lines.append("**数据准备**：")
            lines.append("")
            lines.append(
                f"- 数据来源：{data_prep.get('data_source', '未知')}"
            )
            lines.append(
                f"- 样本数：{data_prep.get('n_samples', 0)}, "
                f"特征数：{data_prep.get('n_features', 0)}"
            )
            for step in data_prep.get("preprocessing", []):
                lines.append(f"- 预处理：{step}")

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
        lines.append("")
        lines.append(f"#### {qid}.5 结果检验")
        lines.append("")
        validation = result.validation
        if validation:
            self._tbl_counter += 1
            val_table = format_validation_table(validation, qid)
            val_table = self._strip_table_title(val_table)
            lines.append(f"**表 {self._tbl_counter}：问题 {qid} 验证结果**")
            lines.append("")
            lines.append(val_table)
        else:
            lines.append("（验证待完成）")

        # --- 结论 ---
        lines.append("")
        lines.append(f"#### {qid}.6 结论")
        lines.append("")
        findings = result.findings
        summary = findings.get("summary", "")
        key_result = findings.get("key_result", "")

        # 格式化关键结果，避免过多小数位
        if key_result:
            import re as _re
            # 将 "数值: 123.456789012345" 格式化为 "数值: 123.4568"
            def _fmt_key_result(text: str) -> str:
                def _replace_float(m):
                    val = float(m.group(0))
                    return f"{val:.4f}"
                return _re.sub(r"\d+\.\d{6,}", _replace_float, text)
            key_result = _fmt_key_result(key_result)

        if summary:
            lines.append(summary)
        if key_result:
            lines.append("")
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
                # 跳过跨问题引用（如 q2 结论中出现"小问 q1 的..."）
                if c.startswith("小问 ") and not c.startswith(f"小问 {qid}"):
                    continue
                # 跳过已在前问展示过的结论（避免跨问题重复）
                if c in self._shown_conclusions:
                    continue
                filtered_conclusions.append(c)
                self._shown_conclusions.add(c)
            if filtered_conclusions:
                lines.append("")
                lines.append("**已验证结论**：")
                lines.append("")
                for c in filtered_conclusions:
                    lines.append(f"- {c}")

        # 局限（去重 + 过滤内部引用）
        if result.limitations:
            seen_lims: set[str] = set()
            filtered_lims: list[str] = []
            for lim in result.limitations:
                # 跳过内部技术引用
                if any(kw in lim for kw in ["Phase", "题型验证待", "待 Phase"]):
                    continue
                # 去重（忽略冒号差异）
                lim_normalized = lim.replace("：", ":").strip()
                if lim_normalized not in seen_lims:
                    seen_lims.add(lim_normalized)
                    filtered_lims.append(lim)
            if filtered_lims:
                lines.append("")
                lines.append("**局限**：")
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
        for qid in sorted(question_results.keys()):
            result = question_results[qid]
            findings = result.findings
            method = findings.get("selected_method", "未知")
            task = findings.get("math_task", "未知")
            task_label = _TASK_LABELS.get(task, task)
            status = findings.get("computation_status", "未知")
            status_label = _STATUS_LABELS.get(status, status)
            lines.append(
                f"- 问题 {qid}：{task_label}类问题，采用 {method}，"
                f"计算状态 {status_label}"
            )

        # 5.2 模型优点
        lines.append("")
        lines.append("### 5.2 模型优点")
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
                    f"计算结果可复现"
                )

        # 5.3 模型缺点与局限（去重）
        lines.append("")
        lines.append("### 5.3 模型缺点与局限")
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
            lines.append("- （局限待补充）")

        # 5.4 模型推广
        lines.append("")
        lines.append("### 5.4 模型推广")
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
        # 添加通用推广内容
        lines.append(
            "- 本文建立的模型框架可推广至同类资源优化配置、"
            "不确定性决策等数学建模问题的求解。"
        )
        lines.append(
            "- 各子问题采用的建模方法（线性规划、回归分析、"
            "蒙特卡洛模拟等）均为经典方法，可灵活组合应用于"
            "不同领域的决策优化问题。"
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
            return "各子问题目标值对比"
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
            return f"{v:.4f}"
        if isinstance(v, int):
            return str(v)
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
        """从项目上下文派生论文标题。

        优先从问题文本中提取"X题"标题模式；
        无法提取时使用背景摘要首行；最后回退到默认标题。
        """
        import re

        if project_context is None:
            return "数学建模论文"

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

        return "数学建模论文"

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
        """收集论文关键词。"""
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
    """LangGraph 节点：论文写作。

    读取 question_results，调用 PaperWriter，输出 paper_draft。
    修订时会读取 review_report 和 _gf_retry_count 以改进论文。

    Args:
        state: 项目状态。需要包含 question_results。
              修订时可选包含 review_report 和 _gf_retry_count。
              可选包含 output_dir 用于保存图表。

    Returns:
        状态更新字典，包含 paper_draft。
    """
    writer = PaperWriter()
    output_dir = state.get("output_dir", "artifacts/paper")
    paper_draft = writer.write(state, output_dir=output_dir)
    return {"paper_draft": paper_draft}
