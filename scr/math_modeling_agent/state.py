"""
项目状态管理。
  状态采用"全局只读上下文 + 当前小问可写状态 + 已完成结果库"的分区方式。
  这样后续小问能获得必要信息，又不会被历史细节和无效尝试淹没。
状态分区：
  1. 全局只读上下文 — 在读题阶段生成，后续只允许补充澄清
  2. 当前小问可写状态 — 逐问求解时写入，完成验证后归档到结果库
  3. 已完成结果库 — 每问验证后写入，后续小问和报告的唯一可信输入
  4. 运行时配置 — 贯穿整个运行
  5. 最终产物 — 全任务审查和写作后生成
"""
from __future__ import annotations

from typing import Any, TypedDict

from ..runtime.budget import BudgetManager
from ..schemas.context import DataProfile, ProjectContext
from ..schemas.evidence import (
    ArtifactRegistry,
    DecisionLog,
    EvidenceCatalog,
    RunLedger,
)
from ..schemas.paper import PaperDraft, ReviewReport
from ..schemas.question import CurrentQuestionContext, QuestionResult


class ProjectState(TypedDict, total=False):
    """项目状态（LangGraph 主图状态）。

    分区设计：
      - 全局只读上下文：在读题阶段生成后只读
      - 当前小问可写状态：逐问求解时写入
      - 已完成结果库：每问验证后写入
      - 运行时状态：贯穿整个运行
      - 最终产物：全任务审查和写作后生成
    """

    # --- 运行时配置 ---
    run_id: str
    output_dir: str
    llm: Any
    search_provider: Any
    budget_manager: BudgetManager | None  # 预算管理器（强制项按小问重置 + 监控项全程累计）
    budget_config_callback: Any            # 可选回调：在指定小问让用户临时覆盖预算
    clarification_callback: Any            # 可选回调：G0 硬失败时暂停等用户选择终止或补充材料
    data_paths: list[str]  # 原始数据文件路径列表

    # --- 全局只读上下文（Phase 1 生成）---
    project_context: ProjectContext
    data_profile: DataProfile
    evidence_catalog: EvidenceCatalog
    artifact_registry: ArtifactRegistry
    decision_log: DecisionLog
    run_ledger: RunLedger

    # --- 当前小问可写状态（Phase 2 生成）---
    current_question_id: str  # 当前正在处理的小问 ID
    current_context: CurrentQuestionContext  # 当前小问的上下文包
    current_result: QuestionResult  # 当前小问的结果包

    # --- 已完成结果库 ---
    question_results: dict[str, QuestionResult]  # question_id -> QuestionResult

    # --- 最终产物（Phase 6 生成）---
    paper_draft: PaperDraft
    review_report: ReviewReport
    final_package_dir: str

    # --- 运行状态 ---
    workflow_status: str  # initializing/intake_ready/context_ready/solving/reviewing/delivered/failed
    errors: list[dict]
    checkpoints: list[str]  # 检查点 ID 列表

    # --- 内部跟踪（图路由用，非持久化）---
    _g0_retry_count: int       # G0 质量门重试计数
    _g0_clarification_action: str  # G0 澄清动作 (terminate/continue)
    _solve_retry_count: int    # 当前小问求解重试计数
    _gq_action: str            # GQ 质量门最近一次动作 (pass/retry/blocked)
    _gf_retry_count: int       # GF 交付质量门修订计数


def create_initial_state(
    run_id: str,
    output_dir: str,
    problem_text: str = "",
    data_paths: list[str] | None = None,
    llm: Any = None,
    search_provider: Any = None,
    budget_manager: BudgetManager | None = None,
    budget_config_callback: Any = None,
    clarification_callback: Any = None,
) -> ProjectState:
    """创建初始项目状态。

    Args:
        run_id: 运行 ID。
        output_dir: 产物输出目录。
        problem_text: 任务文本。
        data_paths: 数据文件路径列表。
        llm: 可选的 LLM 客户端。
        search_provider: 可选的搜索 Provider。
        budget_manager: 预算管理器（可选；未传则在 run_graph 自动实例化）。
        budget_config_callback: 可选回调；签名
            ``(state) -> dict[BudgetType, int] | None``，返回 None 表示沿用默认。
        clarification_callback: 可选回调；签名
            ``(state) -> dict | None``，G0 硬失败时暂停等待用户选择终止或补充材料。

    Returns:
        初始化的 ProjectState 字典。
    """
    return ProjectState(
        run_id=run_id,
        output_dir=output_dir,
        llm=llm,
        search_provider=search_provider,
        budget_manager=budget_manager,
        budget_config_callback=budget_config_callback,
        clarification_callback=clarification_callback,
        data_paths=data_paths or [],
        project_context=ProjectContext(
            run_id=run_id,
            problem_text=problem_text,
        ),
        data_profile=DataProfile(),
        evidence_catalog=EvidenceCatalog(),
        artifact_registry=ArtifactRegistry(),
        decision_log=DecisionLog(),
        run_ledger=RunLedger(),
        question_results={},
        workflow_status="initializing",
        errors=[],
        checkpoints=[],
        _g0_retry_count=0,
        _g0_clarification_action="",
        _solve_retry_count=0,
        _gq_action="",
        _gf_retry_count=0,
    )


def get_validated_results(state: ProjectState) -> dict[str, QuestionResult]:
    """获取所有已验证通过的小问结果。"""
    results = state.get("question_results", {})
    return {
        qid: result
        for qid, result in results.items()
        if result.status == "validated"
    }


def get_reusable_summaries(state: ProjectState) -> list[dict]:
    """获取所有已验证小问的可复用摘要列表。"""
    summaries: list[dict] = []
    for result in get_validated_results(state).values():
        if result.reusable_summary is not None:
            summaries.append(result.reusable_summary.model_dump())
    return summaries


def is_question_completed(state: ProjectState, question_id: str) -> bool:
    """检查指定小问是否已完成（验证通过或被阻塞）。"""
    results = state.get("question_results", {})
    result = results.get(question_id)
    if result is None:
        return False
    return result.status in ("validated", "blocked")


def get_pending_questions(state: ProjectState) -> list[str]:
    """获取所有待处理的小问 ID（按依赖顺序）。"""
    context = state.get("project_context")
    if context is None:
        return []
    results = state.get("question_results", {})
    pending: list[str] = []
    for q in context.questions:
        result = results.get(q.question_id)
        if result is None or result.status == "pending":
            # 检查依赖是否已满足
            deps = q.depends_on
            if all(is_question_completed(state, dep) for dep in deps):
                pending.append(q.question_id)
    return pending
