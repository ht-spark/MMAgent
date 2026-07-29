"""L6 审查与交付子图。

对应 architecture.md §4 L6 与 plan.md Phase 9：
  programmatic_checks → llm_review → route → H2 → final_package

简化版（demo 零 token）：
  - 跳过 llm_review / H2 interrupt
  - 5 项程序化检查
  - 生成 final_package/ 与 submission_checklist.md
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..schemas.problem import ProblemAnalysis
from ..schemas.result import ExecutionResult


def _check_question_coverage(paper_text: str, analysis: ProblemAnalysis) -> tuple[bool, list[str]]:
    """每个显式小问是否在论文中有对应章节。"""
    missing: list[str] = []
    for q in analysis.explicit_questions:
        # 简化检查：要求论文中至少提及 "问题一/问题二/问题一："/ 关键短语
        q_text = q.lstrip().lstrip("问题一二三四五六七八九十：: ")
        # 取前 8 个字符作为关键词
        keyword = q_text[:8] if len(q_text) >= 8 else q_text
        if keyword and keyword not in paper_text:
            missing.append(q)
    return len(missing) == 0, missing


def _check_artifact_existence(artifacts: dict[str, str]) -> tuple[bool, list[str]]:
    """所有声明的产物文件是否真实存在（跳过空路径）。"""
    missing: list[str] = []
    for key, path in artifacts.items():
        if not path:  # 跳过未提供路径的产物
            continue
        p = Path(path)
        if not p.exists():
            missing.append(f"{key}: {path}")
    return len(missing) == 0, missing


def _check_validation_presence(paper_text: str) -> tuple[bool, list[str]]:
    """是否有模型检验章节。"""
    if "模型检验" in paper_text or "检验" in paper_text:
        return True, []
    return False, ["missing_validation_section"]


def _check_symbol_definition(paper_text: str) -> tuple[bool, list[str]]:
    """是否有符号说明章节。"""
    if "符号说明" in paper_text or "符号" in paper_text:
        return True, []
    return False, ["missing_symbol_definition"]


def _build_final_package(
    output_dir: Path,
    paper_text: str,
    artifacts: dict[str, str],
    review_results: dict[str, Any],
) -> Path:
    """生成 final_package：复制论文 + 各种报告 + submission_checklist。"""
    final_dir = output_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)

    # 论文
    (final_dir / "paper_final.md").write_text(paper_text, encoding="utf-8")

    # 审查报告
    (final_dir / "review_report.json").write_text(
        json.dumps(review_results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 提交清单
    checklist_lines = [
        "# 提交清单",
        "",
        f"生成时间：{datetime.now().isoformat()}",
        "",
        "## 文件清单",
        "",
    ]
    for key, path in artifacts.items():
        exists = "✓" if path and Path(path).exists() else "✗"
        checklist_lines.append(f"- {exists} **{key}**: `{path}`")

    checklist_lines.extend([
        "",
        "## 审查结果",
        "",
    ])
    for check_name, result in review_results.items():
        status = "✓" if result.get("passed") else "✗"
        checklist_lines.append(f"- {status} **{check_name}**: {result.get('message', '')}")

    (final_dir / "submission_checklist.md").write_text(
        "\n".join(checklist_lines),
        encoding="utf-8",
    )

    return final_dir


class L6ReviewSubgraph:
    """L6 审查与交付子图（demo 零 token 简化版）。"""

    def __init__(self, output_dir: str | Path | None = None) -> None:
        self.output_dir = Path(output_dir) if output_dir else Path("artifacts/default")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        problem_analysis: ProblemAnalysis,
        execution_result: ExecutionResult,
        paper_text: str,
        paper_path: str,
        artifacts: dict[str, str] | None = None,
    ) -> dict:
        """执行 L6 审查与交付。

        Args:
            problem_analysis: L0 产出。
            execution_result: L4 产出。
            paper_text: 论文正文。
            paper_path: 论文路径。
            artifacts: 所有产物路径字典。

        Returns:
            State 部分更新：
              - review_report / final_package_dir / submission_checklist_path
              - workflow_status
        """
        all_artifacts = {
            "paper": paper_path,
            "code": "",  # demo 简化
            **(artifacts or {}),
        }

        # 程序化检查
        qc_pass, qc_missing = _check_question_coverage(paper_text, problem_analysis)
        vp_pass, vp_issues = _check_validation_presence(paper_text)
        sd_pass, sd_issues = _check_symbol_definition(paper_text)
        ae_pass, ae_missing = _check_artifact_existence(all_artifacts)

        review_results = {
            "question_coverage": {"passed": qc_pass, "message": f"missing={qc_missing}"},
            "validation_presence": {"passed": vp_pass, "message": str(vp_issues)},
            "symbol_definition": {"passed": sd_pass, "message": str(sd_issues)},
            "artifact_existence": {"passed": ae_pass, "message": f"missing={ae_missing}"},
            "execution_success": {
                "passed": execution_result.success,
                "message": execution_result.error_message or "OK",
            },
        }

        all_passed = all(r["passed"] for r in review_results.values())

        # final_package
        final_dir = _build_final_package(
            self.output_dir, paper_text, all_artifacts, review_results
        )

        return {
            "review_report": review_results,
            "final_package_dir": str(final_dir),
            "submission_checklist_path": str(final_dir / "submission_checklist.md"),
            "workflow_status": "l6_completed" if all_passed else "l6_issues",
        }