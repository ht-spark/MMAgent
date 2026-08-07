"""报告审查 Agent（architecture.md §6.1 全任务一致性审查）。

职责：
  从评委视角对报告草稿进行全任务一致性审查，产出 ReviewReport。

审查维度（architecture.md §6.1）：
  1. 覆盖性：所有小问是否有结论，且结论覆盖任务要求
  2. 一致性：数据口径、单位、符号、假设、前问结果使用是否一致
  3. 可追溯性：关键数值、图表、表格能否定位到计算产物
  4. 验证充分性：各模型验证是否充分，结论强度是否与证据一致
  5. 格式合规性：章节完整、公式图表表编号引用、格式符合竞赛模板
  6. 引用可追溯性：外部事实和方法依据是否可追溯

设计要点：
  - 确定性检查：不依赖 LLM，用规则检查结构完整性和一致性
  - 严重级别：
      critical = 阻断性问题（缺小问、无计算、无验证）
      major    = 应修复问题（章节不全、缺引用）
      minor    = 建议改进（格式问题）
  - 通过条件：无 critical 且 major <= 2
"""
from __future__ import annotations

from ..schemas.context import ProjectContext
from ..schemas.paper import PaperDraft, ReviewIssue, ReviewReport
from ..schemas.question import QuestionResult

__all__ = ["Reviewer", "review_paper_node"]


class Reviewer:
    """报告审查 Agent（确定性检查，无 LLM）。

    从评委视角审查报告草稿和小问结果，产出结构化的 ReviewReport。

    Usage::

        reviewer = Reviewer()
        report = reviewer.review(state)
    """

    # ------------------------------------------------------------------
    # 主方法
    # ------------------------------------------------------------------

    def review(self, state: dict) -> ReviewReport:
        """执行全任务一致性审查。

        Args:
            state: 项目状态，需包含 question_results、project_context、paper_draft。

        Returns:
            ReviewReport 对象，包含所有审查问题和总体状态。
        """
        question_results: dict[str, QuestionResult] = state.get(
            "question_results", {}
        )
        project_context: ProjectContext | None = state.get("project_context")
        paper_draft: PaperDraft | None = state.get("paper_draft")

        print(f"[reviewer] 开始审查: {len(question_results)} 个小问结果")

        # 运行所有检查
        issues: list[ReviewIssue] = []
        issues.extend(self._check_coverage(question_results, project_context))
        issues.extend(self._check_consistency(question_results))
        issues.extend(
            self._check_traceability(paper_draft, question_results)
        )
        issues.extend(self._check_validation(question_results))
        issues.extend(self._check_format(paper_draft))

        # 重新分配 issue_id（全局连续编号）
        for i, issue in enumerate(issues, start=1):
            issue.issue_id = f"issue_{i}"

        # 判定总体状态
        overall_status = self._determine_status(issues)

        # 构建摘要
        critical_count = sum(
            1 for i in issues if i.severity == "critical"
        )
        major_count = sum(1 for i in issues if i.severity == "major")
        minor_count = sum(1 for i in issues if i.severity == "minor")

        summary = (
            f"审查完成：共 {len(issues)} 个问题"
            f"（critical={critical_count}, major={major_count}, "
            f"minor={minor_count}），总体状态={overall_status}。"
        )

        print(f"[reviewer] 审查完成: {overall_status} "
              f"(critical={critical_count}, major={major_count}, "
              f"minor={minor_count})")

        return ReviewReport(
            issues=issues,
            overall_status=overall_status,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # 检查 1: 覆盖性
    # ------------------------------------------------------------------

    def _check_coverage(
        self,
        question_results: dict[str, QuestionResult],
        project_context: ProjectContext | None,
    ) -> list[ReviewIssue]:
        """检查所有小问是否覆盖任务要求。

        Critical: 缺少小问结果、小问未通过验证。
        Major: 小问缺少结论。
        """
        issues: list[ReviewIssue] = []
        idx = 0

        # 检查 1.1: question_results 为空
        if not question_results:
            idx += 1
            issues.append(ReviewIssue(
                issue_id=f"coverage_{idx}",
                severity="critical",
                category="coverage",
                message="没有已验证的小问结果，无法生成完整报告",
                location="question_results",
                suggested_fix="确保至少有一个小问通过 GQ 验证",
            ))
            return issues

        # 检查 1.2: project_context 中的小问是否都有结果
        if project_context is not None:
            for q in project_context.questions:
                result = question_results.get(q.question_id)
                if result is None:
                    idx += 1
                    issues.append(ReviewIssue(
                        issue_id=f"coverage_{idx}",
                        severity="critical",
                        category="coverage",
                        message=f"小问 {q.question_id} 缺少已验证的结果",
                        location=q.question_id,
                        suggested_fix=(
                            f"完成小问 {q.question_id} 的求解与验证"
                        ),
                    ))
                elif result.status != "validated":
                    idx += 1
                    # blocked 小问已在报告中以占位章节说明原因，视为 major（记录风险）
                    # 而非 critical（致命）；其他异常状态仍为 critical。
                    severity = (
                        "major" if result.status == "blocked" else "critical"
                    )
                    message = (
                        f"小问 {q.question_id} 状态为 {result.status}，未通过验证"
                        + (
                            "（报告中已给出占位说明，建议后续重新求解）"
                            if result.status == "blocked"
                            else ""
                        )
                    )
                    issues.append(ReviewIssue(
                        issue_id=f"coverage_{idx}",
                        severity=severity,
                        category="coverage",
                        message=message,
                        location=q.question_id,
                        suggested_fix=(
                            f"重新求解小问 {q.question_id} 直至通过 GQ 验证"
                        ),
                    ))

        # 检查 1.3: 每个结果是否有结论（findings）
        for qid, result in question_results.items():
            if not result.findings:
                idx += 1
                issues.append(ReviewIssue(
                    issue_id=f"coverage_{idx}",
                    severity="major",
                    category="coverage",
                    message=f"小问 {qid} 缺少结论（findings 为空）",
                    location=qid,
                    suggested_fix="补充小问的结论和发现",
                ))
            elif not result.findings.get("summary"):
                idx += 1
                issues.append(ReviewIssue(
                    issue_id=f"coverage_{idx}",
                    severity="major",
                    category="coverage",
                    message=f"小问 {qid} 缺少结论摘要（findings.summary 为空）",
                    location=qid,
                    suggested_fix="补充小问的结论摘要",
                ))

        return issues

    # ------------------------------------------------------------------
    # 检查 2: 一致性
    # ------------------------------------------------------------------

    def _check_consistency(
        self, question_results: dict[str, QuestionResult]
    ) -> list[ReviewIssue]:
        """检查数据口径、单位、符号、假设、前问结果使用一致性。

        Major: 缺少假设、缺少可复用摘要（影响后题继承）。
        Minor: 假设格式不一致。
        """
        issues: list[ReviewIssue] = []
        idx = 0

        # 检查 2.1: 每个小问是否有假设记录
        for qid in sorted(question_results.keys()):
            result = question_results[qid]
            if not result.assumptions:
                idx += 1
                issues.append(ReviewIssue(
                    issue_id=f"consistency_{idx}",
                    severity="major",
                    category="consistency",
                    message=f"小问 {qid} 缺少模型假设记录",
                    location=qid,
                    suggested_fix="补充模型假设并说明依据",
                ))

        # 检查 2.2: 有依赖关系的小问是否继承了前问结果
        for qid in sorted(question_results.keys()):
            result = question_results[qid]
            interp = result.problem_interpretation
            if interp is None:
                continue
            # 如果与前问有关系但非 independent，检查 inherited_context
            if interp.relation_to_previous != "independent":
                if not result.inherited_context:
                    idx += 1
                    issues.append(ReviewIssue(
                        issue_id=f"consistency_{idx}",
                        severity="major",
                        category="consistency",
                        message=(
                            f"小问 {qid} 声明与前问有关系"
                            f"（{interp.relation_to_previous}），"
                            f"但未记录继承的前问上下文"
                        ),
                        location=qid,
                        suggested_fix="补充从前问继承的可复用摘要",
                    ))

        # 检查 2.3: 每个小问是否有 reusable_summary（供后题使用）
        for qid in sorted(question_results.keys()):
            result = question_results[qid]
            if result.reusable_summary is None:
                idx += 1
                issues.append(ReviewIssue(
                    issue_id=f"consistency_{idx}",
                    severity="major",
                    category="consistency",
                    message=f"小问 {qid} 缺少可复用摘要",
                    location=qid,
                    suggested_fix="生成 reusable_summary 供后续小问使用",
                ))

        # 检查 2.4: 局限性是否记录
        for qid in sorted(question_results.keys()):
            result = question_results[qid]
            if not result.limitations:
                idx += 1
                issues.append(ReviewIssue(
                    issue_id=f"consistency_{idx}",
                    severity="minor",
                    category="consistency",
                    message=f"小问 {qid} 缺少局限性说明",
                    location=qid,
                    suggested_fix="补充模型局限性说明",
                ))

        return issues

    # ------------------------------------------------------------------
    # 检查 3: 可追溯性
    # ------------------------------------------------------------------

    def _check_traceability(
        self,
        paper_draft: PaperDraft | None,
        question_results: dict[str, QuestionResult],
    ) -> list[ReviewIssue]:
        """检查关键数值、图表、表格能否定位到计算产物。

        Critical: 小问无计算结果。
        Major: 报告章节缺失、图表不可追溯。
        Minor: 报告缺少图表引用。
        """
        issues: list[ReviewIssue] = []
        idx = 0

        # 检查 3.1: 每个小问是否有计算结果
        for qid in sorted(question_results.keys()):
            result = question_results[qid]
            computation = result.computation
            if not computation:
                idx += 1
                issues.append(ReviewIssue(
                    issue_id=f"traceability_{idx}",
                    severity="critical",
                    category="traceability",
                    message=f"小问 {qid} 缺少计算结果（computation 为空）",
                    location=qid,
                    suggested_fix="执行建模计算并记录结果",
                ))
            else:
                status = computation.get("status", "unknown")
                if status in ("error", "no_data", "not_executed"):
                    idx += 1
                    issues.append(ReviewIssue(
                        issue_id=f"traceability_{idx}",
                        severity="critical",
                        category="traceability",
                        message=(
                            f"小问 {qid} 计算状态为 {status}，"
                            f"数值结果不可追溯"
                        ),
                        location=qid,
                        suggested_fix="修复计算问题并重新执行",
                    ))
                elif not computation.get("results"):
                    idx += 1
                    issues.append(ReviewIssue(
                        issue_id=f"traceability_{idx}",
                        severity="major",
                        category="traceability",
                        message=(
                            f"小问 {qid} 计算结果为空"
                            f"（computation.results 无内容）"
                        ),
                        location=qid,
                        suggested_fix="补充计算结果数据",
                    ))

        # 检查 3.2: 报告草稿是否存在
        if paper_draft is None:
            idx += 1
            issues.append(ReviewIssue(
                issue_id=f"traceability_{idx}",
                severity="critical",
                category="traceability",
                message="报告草稿缺失，无法检查数值可追溯性",
                location="paper_draft",
                suggested_fix="执行报告写作生成 PaperDraft",
            ))
            return issues

        # 检查 3.3: 报告中小问章节是否有内容
        for qid in sorted(question_results.keys()):
            q_sections = paper_draft.get_sections_by_question(qid)
            if not q_sections:
                idx += 1
                issues.append(ReviewIssue(
                    issue_id=f"traceability_{idx}",
                    severity="major",
                    category="traceability",
                    message=f"报告中缺少小问 {qid} 的章节",
                    location=qid,
                    suggested_fix=f"补充小问 {qid} 的报告章节",
                ))
            else:
                for section in q_sections:
                    if not section.content.strip():
                        idx += 1
                        issues.append(ReviewIssue(
                            issue_id=f"traceability_{idx}",
                            severity="major",
                            category="traceability",
                            message=(
                                f"小问 {qid} 的章节内容为空"
                                f"（section_id={section.section_id}）"
                            ),
                            location=section.section_id,
                            suggested_fix="补充章节内容",
                        ))

        # 检查 3.4: 图表是否在报告章节中引用
        for qid in sorted(question_results.keys()):
            result = question_results[qid]
            q_sections = paper_draft.get_sections_by_question(qid)
            if not q_sections:
                continue
            # 合并该小问所有章节的图表
            section_figs: list[str] = []
            section_tables: list[str] = []
            for s in q_sections:
                section_figs.extend(s.figures)
                section_tables.extend(s.tables)

            # 如果结果有图表但报告章节没有记录
            if result.figures and not section_figs:
                idx += 1
                issues.append(ReviewIssue(
                    issue_id=f"traceability_{idx}",
                    severity="minor",
                    category="traceability",
                    message=(
                        f"小问 {qid} 有 {len(result.figures)} 个图，"
                        f"但报告章节未引用"
                    ),
                    location=qid,
                    suggested_fix="在报告中引用相关图表",
                ))
            if result.tables and not section_tables:
                idx += 1
                issues.append(ReviewIssue(
                    issue_id=f"traceability_{idx}",
                    severity="minor",
                    category="traceability",
                    message=(
                        f"小问 {qid} 有 {len(result.tables)} 个表，"
                        f"但报告章节未引用"
                    ),
                    location=qid,
                    suggested_fix="在报告中引用相关表格",
                ))

        return issues

    # ------------------------------------------------------------------
    # 检查 4: 验证充分性
    # ------------------------------------------------------------------

    def _check_validation(
        self, question_results: dict[str, QuestionResult]
    ) -> list[ReviewIssue]:
        """检查各模型验证是否充分。

        Critical: 小问无验证记录。
        Major: 验证不完整（缺少关键检验项）。
        """
        issues: list[ReviewIssue] = []
        idx = 0

        for qid in sorted(question_results.keys()):
            result = question_results[qid]
            validation = result.validation

            if not validation:
                idx += 1
                issues.append(ReviewIssue(
                    issue_id=f"validation_{idx}",
                    severity="critical",
                    category="validation",
                    message=f"小问 {qid} 缺少验证记录（validation 为空）",
                    location=qid,
                    suggested_fix="执行题型匹配的验证并记录结果",
                ))
                continue

            # 检查验证内容是否足够
            # 至少应有一个验证项
            validation_keys = list(validation.keys())
            if len(validation_keys) < 1:
                idx += 1
                issues.append(ReviewIssue(
                    issue_id=f"validation_{idx}",
                    severity="major",
                    category="validation",
                    message=f"小问 {qid} 验证内容不充分（无验证项）",
                    location=qid,
                    suggested_fix="补充验证项，如敏感性分析、交叉验证等",
                ))

            # 检查计算状态是否为成功
            comp_status = result.findings.get("computation_status", "")
            if comp_status and comp_status not in (
                "success", "generic_stats"
            ):
                idx += 1
                issues.append(ReviewIssue(
                    issue_id=f"validation_{idx}",
                    severity="major",
                    category="validation",
                    message=(
                        f"小问 {qid} 计算状态为 {comp_status}，"
                        f"验证结论强度可能不足"
                    ),
                    location=qid,
                    suggested_fix="确保计算成功后再进行验证",
                ))

        return issues

    # ------------------------------------------------------------------
    # 检查 5: 格式合规性
    # ------------------------------------------------------------------

    def _check_format(
        self, paper_draft: PaperDraft | None
    ) -> list[ReviewIssue]:
        """检查报告格式是否符合竞赛模板。

        Major: 缺少必需章节、缺少摘要、缺少参考文献。
        Minor: 章节内容过短、缺少完整文本。
        """
        issues: list[ReviewIssue] = []
        idx = 0

        if paper_draft is None:
            idx += 1
            issues.append(ReviewIssue(
                issue_id=f"format_{idx}",
                severity="major",
                category="format",
                message="报告草稿缺失，无法检查格式",
                location="paper_draft",
                suggested_fix="执行报告写作生成 PaperDraft",
            ))
            return issues

        # 检查 5.1: 摘要是否存在且非空
        if not paper_draft.abstract.strip():
            idx += 1
            issues.append(ReviewIssue(
                issue_id=f"format_{idx}",
                severity="major",
                category="format",
                message="报告缺少摘要",
                location="abstract",
                suggested_fix="生成摘要（最后生成，不引入新数字）",
            ))

        # 检查 5.2: 必需章节是否齐全
        required_section_ids = {"1", "2", "3", "4", "5", "6", "7"}
        existing_ids = {s.section_id for s in paper_draft.sections}
        # 小问子章节 4.x 也算
        has_question_sections = any(
            s.question_id is not None for s in paper_draft.sections
        )

        for sid in required_section_ids:
            if sid not in existing_ids:
                idx += 1
                issues.append(ReviewIssue(
                    issue_id=f"format_{idx}",
                    severity="major",
                    category="format",
                    message=f"报告缺少必需章节（section_id={sid}）",
                    location=sid,
                    suggested_fix=f"补充章节 {sid}",
                ))

        # 检查 5.3: 是否有小问章节
        if not has_question_sections:
            idx += 1
            issues.append(ReviewIssue(
                issue_id=f"format_{idx}",
                severity="major",
                category="format",
                message="报告缺少小问章节（无 4.x 子章节）",
                location="4",
                suggested_fix="为每个小问生成独立章节",
            ))

        # 检查 5.4: 参考文献是否存在
        if not paper_draft.references:
            idx += 1
            issues.append(ReviewIssue(
                issue_id=f"format_{idx}",
                severity="major",
                category="citation",
                message="报告缺少参考文献",
                location="references",
                suggested_fix="补充方法相关的参考文献",
            ))

        # 检查 5.5: 完整文本是否存在
        if not paper_draft.full_text.strip():
            idx += 1
            issues.append(ReviewIssue(
                issue_id=f"format_{idx}",
                severity="major",
                category="format",
                message="报告缺少完整文本（full_text 为空）",
                location="full_text",
                suggested_fix="执行文本组装生成 full_text",
            ))

        # 检查 5.6: 各章节内容是否过短
        for section in paper_draft.sections:
            if section.section_id == "4":
                continue  # 引导章节允许较短
            if len(section.content.strip()) < 20:
                idx += 1
                issues.append(ReviewIssue(
                    issue_id=f"format_{idx}",
                    severity="minor",
                    category="format",
                    message=(
                        f"章节 {section.section_id}（{section.title}）"
                        f"内容过短（{len(section.content.strip())} 字符）"
                    ),
                    location=section.section_id,
                    suggested_fix="扩充章节内容",
                ))

        # 检查 5.7: 公式是否编号引用
        total_formulas = sum(len(s.formulas) for s in paper_draft.sections)
        if total_formulas == 0:
            idx += 1
            issues.append(ReviewIssue(
                issue_id=f"format_{idx}",
                severity="minor",
                category="format",
                message="报告中未包含任何公式",
                location="formulas",
                suggested_fix="补充模型公式并编号引用",
            ))

        return issues

    # ------------------------------------------------------------------
    # 状态判定
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_status(issues: list[ReviewIssue]) -> str:
        """根据问题列表判定总体状态。

        判定规则：
          - 有 critical 问题 → "failed"
          - 无 critical 且 major > 2 → "needs_revision"
          - 无 critical 且 major <= 2 → "passed"
        """
        critical_count = sum(
            1 for i in issues if i.severity == "critical"
        )
        major_count = sum(1 for i in issues if i.severity == "major")

        if critical_count > 0:
            return "failed"
        if major_count > 2:
            return "needs_revision"
        return "passed"


# ---------------------------------------------------------------------------
# LangGraph 节点封装
# ---------------------------------------------------------------------------


def review_paper_node(state: dict) -> dict:
    """LangGraph 节点：报告审查。

    读取 question_results 和 paper_draft，调用 Reviewer，输出 review_report。

    Args:
        state: 项目状态。需要包含 question_results 和 paper_draft。

    Returns:
        状态更新字典，包含 review_report。
    """
    reviewer = Reviewer()
    review_report = reviewer.review(state)
    return {"review_report": review_report}
