"""L5 论文写作子图。

对应 architecture.md §4 L5 与 plan.md Phase 8：
  outline → section_writers → citation_registry → assemble → consistency_check → abstract

简化版（demo，零 token）：
  - 跳过 outline / citation_registry（不需要 LLM）
  - 用预定义 Markdown 模板填充 ExecutionResult 数据
  - 程序化数值一致性核对（不调用 LLM）
  - 写盘 artifacts/<run_id>/paper/paper_draft.md
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..schemas.problem import ProblemAnalysis, SubProblem
from ..schemas.result import ExecutionResult


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


def _assemble_paper(
    problem_analysis: ProblemAnalysis,
    subproblems: list[SubProblem],
    execution_result: ExecutionResult,
    selected_model_name: str = "",
) -> str:
    """组装完整论文（Markdown）。"""
    sections: list[str] = []

    # 1. 标题
    sections.append(f"# {problem_analysis.research_subject}\n")

    # 2. 问题重述
    sections.append("## 1. 问题重述\n")
    sections.append(f"{problem_analysis.background}\n")

    # 3. 问题分析
    sections.append("## 2. 问题分析\n")
    for q in problem_analysis.explicit_questions:
        sections.append(f"- {q}")
    sections.append("")

    # 4. 模型假设
    sections.append("## 3. 模型假设\n")
    constraints = problem_analysis.constraints or ["（无特殊约束）"]
    for c in constraints:
        sections.append(f"- {c}")
    sections.append("")

    # 5. 符号说明
    sections.append("## 4. 符号说明\n")
    sections.append("| 符号 | 含义 |")
    sections.append("|------|------|")
    for sp in subproblems:
        sections.append(f"| — | 子问题 {sp.id}：{sp.task} |")
    sections.append("")

    # 6. 数据预处理
    sections.append("## 5. 数据预处理\n")
    sections.append("对原始数据进行缺失值填充、常量列剔除、类型转换等处理。"
                    "详见 `artifacts/<run_id>/reports/preprocessing_report.json`。\n")

    # 7. 模型建立与求解
    sections.append("## 6. 模型建立与求解\n")
    if selected_model_name:
        sections.append(f"选用 **{selected_model_name}** 作为求解模型。\n")
    sections.append("使用预定义模板自动生成求解代码并执行。\n")

    # 8. 结果分析
    sections.append("## 7. 结果分析\n")
    if execution_result.success:
        sections.append("模型成功执行，关键数值如下：\n")
        sections.append(_format_numeric_outputs(execution_result.numeric_outputs))
    else:
        sections.append(f"模型执行失败：{execution_result.error_message}\n")

    # 9. 模型检验
    sections.append("## 8. 模型检验\n")
    sections.append("建议从权重稳定性（评价类）/ 残差分析（预测类）/ 约束满足（优化类）"
                    "等角度进行敏感性分析。\n")

    # 10. 模型评价与推广
    sections.append("## 9. 模型评价与推广\n")
    sections.append("模型优势：实现简单、可解释性强。\n")
    sections.append("局限性：对数据质量敏感，扩展到更大规模数据时需重新训练。\n")

    # 11. 参考文献
    sections.append("## 参考文献\n")
    sections.append("[1] 系统自动生成的内部报告（详见 `artifacts/<run_id>/`）。\n")

    # 12. 摘要（最后生成，plan.md Phase 8.5）
    sections.append("## 摘要\n")
    if execution_result.success:
        model_name = selected_model_name or "所选模型"
        sections.append(
            f"本文针对{problem_analysis.research_subject}，"
            f"使用{model_name}对题目进行了建模与求解。"
            f"主要结果包括 {len(execution_result.numeric_outputs)} 个关键指标。"
            f"模型经验证可行，可为相关决策提供参考。\n"
        )

    return "\n".join(sections)


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


class L5WritingSubgraph:
    """L5 论文写作子图（demo 零 token 简化版）。"""

    def __init__(self, output_dir: str | Path | None = None) -> None:
        self.output_dir = Path(output_dir) if output_dir else Path("artifacts/default")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        problem_analysis: ProblemAnalysis,
        subproblems: list[SubProblem],
        execution_result: ExecutionResult,
        selected_model_name: str = "",
    ) -> dict:
        """执行 L5 论文生成。

        Returns:
            State 部分更新：
              - paper_draft_path / paper_text
              - numeric_consistency_passed / numeric_consistency_issues
              - section_completeness_passed / missing_sections
              - workflow_status
        """
        paper_text = _assemble_paper(
            problem_analysis, subproblems, execution_result, selected_model_name
        )

        # 写盘
        paper_path = self.output_dir / "paper_draft.md"
        paper_path.write_text(paper_text, encoding="utf-8")

        # 数值一致性核对
        num_passed, num_issues = _check_numeric_consistency(
            paper_text, execution_result.numeric_outputs
        )

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