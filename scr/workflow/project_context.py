"""
全局上下文建立工作流节点。
职责：
  1. 调用题目理解 Agent，提取背景、目标、约束、小问、预期输出和歧义点
  2. 拆分小问，建立依赖图
  3. 生成题目-数据映射表
  4. 构建 ProjectContext

题目理解器只负责回答"题目要求什么"，不在此阶段推荐模型。
"""
from __future__ import annotations

import time
from typing import Any

from ..agents.decomposition_fallback import (
    fallback_subproblems_from_analysis,
    short_error,
)
from ..runtime.instrumented_llm import InstrumentedLLM
from ..runtime.logging import get_run_logger, log_step
from ..schemas.context import DataProfile, ProjectContext, QuestionInfo
from ..schemas.problem import ProblemAnalysis, SubProblem


def run_context(state: dict) -> dict:
    """LangGraph 节点：全局上下文建立。
    
    调用题目理解 Agent，构建 ProjectContext。
    
    Args:
        state: 项目状态。需要包含 problem_text, data_profile, llm, run_id。
    
    Returns:
        状态更新字典，包含 project_context 和 workflow_status。
    """
    problem_text = state.get("project_context", ProjectContext(run_id="", problem_text="")).problem_text
    if not problem_text:
        problem_text = state.get("problem_text", "")
    
    data_profile = state.get("data_profile")
    llm = state.get("llm")
    run_id = state.get("run_id", "default")

    # 监控包装（全局阶段，无当前小问）：记录 TIME/TOKEN 到预算管理器
    budget_manager = state.get("budget_manager")
    if budget_manager is not None and llm is not None:
        llm = InstrumentedLLM(llm, budget_manager, qid_getter=None)
    
    # 调用题目理解 Agent
    analysis, subproblems, classification = _run_problem_analysis(
        problem_text, data_profile, llm
    )
    
    # 构建 ProjectContext
    project_context = _build_project_context(
        run_id=run_id,
        problem_text=problem_text,
        analysis=analysis,
        subproblems=subproblems,
        data_profile=data_profile,
    )
    
    return {
        "project_context": project_context,
        "workflow_status": "context_ready",
    }


def _run_problem_analysis(
    problem_text: str,
    data_profile: DataProfile | None,
    llm: Any | None,
) -> tuple[ProblemAnalysis | None, list[SubProblem], Any | None]:
    """执行题目理解三步：understand → decompose → classify。
    
    无 LLM 时使用占位分析。
    """
    if llm is None:
        # 无 LLM 占位
        # 清理 PDF 页码标记
        import re
        clean_text = re.sub(r"---\s*第\s*\d+\s*页\s*---\s*", "", problem_text).strip()
        analysis = ProblemAnalysis(
            research_subject=clean_text[:50] + "..." if len(clean_text) > 50 else clean_text,
            background=clean_text[:300],
            explicit_questions=_extract_questions_heuristic(problem_text),
            constraints=[],
            expected_outputs=[],
            keywords=[],
        )
        subproblems = _create_fallback_subproblems(analysis)
        return analysis, subproblems, None
    
    from ..agents.problem_analyst import ProblemAnalyst

    analyst = ProblemAnalyst(llm=llm)
    logger = get_run_logger()

    # 将 DataProfile 转为 DataInventory 供 Agent 使用
    # Agent 需要 DataInventory 或 None
    data_inventory = None
    if data_profile and data_profile.tables:
        # 构建简化的 inventory 摘要供 Agent 参考
        from ..schemas.problem import DataInventory
        # 用第一个表的信息构建简化 inventory
        first_table = data_profile.tables[0]
        data_inventory = DataInventory(
            file_name=first_table.source_file,
            file_path=first_table.source_file,
            file_type="excel" if first_table.source_file.endswith((".xlsx", ".xls")) else "mat" if first_table.source_file.endswith(".mat") else "csv",
            n_rows=first_table.n_rows,
            n_cols=first_table.n_cols,
            fields=[],
            overall_missing_rate=0.0,
            has_time_column=data_profile.has_time_column,
            time_columns=[f.field_name for f in data_profile.fields if f.is_time_column],
            numeric_columns=[f.field_name for f in data_profile.fields if f.dtype in ("int", "float")],
            categorical_columns=[f.field_name for f in data_profile.fields if f.dtype in ("str", "category")],
            sample_size=first_table.n_rows,
        )
    
    try:
        t0 = time.monotonic()
        log_step(logger, "context.understand", "started", detail="LLM 题目理解")
        analysis = analyst.understand(problem_text, data_inventory)
        log_step(
            logger,
            "context.understand",
            "completed",
            duration=time.monotonic() - t0,
            detail=f"研究对象: {(analysis.research_subject or '')[:50]}",
        )
    except Exception as e:
        log_step(logger, "context.understand", "failed", error=str(e)[:200])
        print(f"[context] understand 失败: {e}")
        import re
        clean_text = re.sub(r"---\s*第\s*\d+\s*页\s*---\s*", "", problem_text).strip()
        analysis = ProblemAnalysis(
            research_subject=clean_text[:50] + "..." if len(clean_text) > 50 else clean_text,
            background=clean_text[:300],
            explicit_questions=_extract_questions_heuristic(problem_text),
            constraints=[],
            expected_outputs=[],
            keywords=[],
        )
    
    try:
        t0 = time.monotonic()
        log_step(logger, "context.decompose", "started", detail="LLM 小问拆分")
        subproblems = analyst.decompose(analysis)
        log_step(
            logger,
            "context.decompose",
            "completed",
            duration=time.monotonic() - t0,
            detail=f"拆分为 {len(subproblems)} 个小问",
        )
    except Exception as e:
        log_step(logger, "context.decompose", "failed", error=short_error(e))
        print(f"[context] decompose 结构化输出不可用，已自动降级: {short_error(e)}")
        subproblems = _create_fallback_subproblems(analysis)

    # 如果 decompose 返回空，使用应急子问题
    if not subproblems:
        print("[context] subproblems 为空，使用应急子问题")
        log_step(
            logger,
            "context.decompose",
            "completed",
            detail="subproblems 为空，使用应急子问题",
        )
        subproblems = _create_fallback_subproblems(analysis)

    try:
        t0 = time.monotonic()
        log_step(logger, "context.classify", "started", detail="LLM 题目分类")
        classification = analyst.classify(analysis, subproblems)
        log_step(
            logger,
            "context.classify",
            "completed",
            duration=time.monotonic() - t0,
            detail=(
                f"题型: {getattr(classification, 'primary_type', 'unknown')}"
            ),
        )
    except Exception as e:
        log_step(logger, "context.classify", "failed", error=str(e)[:200])
        print(f"[context] classify 失败: {e}")
        from ..schemas.problem import ProblemClassification
        classification = ProblemClassification(
            primary_type="composite",
            secondary_types=[],
            reasoning="LLM 分类失败，使用默认复合类型",
        )
    
    return analysis, subproblems, classification


def _build_project_context(
    run_id: str,
    problem_text: str,
    analysis: ProblemAnalysis | None,
    subproblems: list[SubProblem],
    data_profile: DataProfile | None,
) -> ProjectContext:
    """从分析结果构建 ProjectContext。
    
    将 ProblemAnalysis + SubProblem 转换为新架构的 ProjectContext。
    """
    # 提取背景和约束
    background = analysis.background if analysis else ""
    objectives = analysis.explicit_questions if analysis else []
    constraints = analysis.constraints if analysis else []
    
    # 术语表（从 keywords 构建）
    terminology: dict[str, str] = {}
    if analysis and analysis.keywords:
        for kw in analysis.keywords:
            terminology[kw] = ""  # 待后续填充定义
    
    # 构建 QuestionInfo 列表
    questions: list[QuestionInfo] = []
    for sp in subproblems:
        questions.append(QuestionInfo(
            question_id=sp.id,
            original_text=sp.task,
            objective=sp.task,
            expected_output="; ".join(sp.expected_outputs) if sp.expected_outputs else "",
            question_type="",  # 待 classify 填充
            required_data=sp.input_requirements,
            depends_on=sp.dependencies,
            status="pending",
        ))
    
    # 依赖关系图
    question_dependencies = {sp.id: sp.dependencies for sp in subproblems}
    
    # 题目-数据映射
    question_data_map = _map_questions_to_data(subproblems, data_profile)
    
    return ProjectContext(
        run_id=run_id,
        problem_text=problem_text,
        background_summary=background,
        objectives=objectives,
        constraints=constraints,
        terminology=terminology,
        questions=questions,
        question_dependencies=question_dependencies,
        question_data_map=question_data_map,
    )


def _map_questions_to_data(
    subproblems: list[SubProblem],
    data_profile: DataProfile | None,
) -> dict[str, list[str]]:
    """生成题目-数据映射表。
    
    根据子问题的 input_requirements 和数据画像的字段名进行模糊匹配。
    """
    if data_profile is None or not data_profile.files:
        return {sp.id: [] for sp in subproblems}
    
    mapping: dict[str, list[str]] = {}
    all_file_names = [f.file_name for f in data_profile.files]
    
    for sp in subproblems:
        mapped_files: list[str] = []
        # 简单策略：如果 input_requirements 非空，映射到所有文件
        # 后续可通过字段名匹配优化
        if sp.input_requirements:
            mapped_files = all_file_names[:]
        else:
            # 无明确需求，映射到所有文件作为默认
            mapped_files = all_file_names[:]
        mapping[sp.id] = mapped_files
    
    return mapping


def _extract_questions_heuristic(problem_text: str) -> list[str]:
    """启发式提取题目中的显式小问。

    策略：以"问题N"为分隔符，捕获每个问题从标记开始到下一个"问题M"标记之前的完整文本。
    只匹配行首或段首的"问题N"模式，避免误匹配"在问题2的基础上"等引用。
    """
    import re

    # 清理 PDF 提取的页码标记
    clean_text = re.sub(r"---\s*第\s*\d+\s*页\s*---", "", problem_text)

    # 匹配行首/段首的"问题N"或"问题 N"（N 为数字或中文数字）
    # 使用 MULTILINE 使 ^ 匹配每行开头
    # 模式：^问题\s*(\d+|[一二三四五六七八九十]+)\s+(?!的基础上)
    pattern = re.compile(
        r"(?:^|\n)\s*问题\s*(\d+|[一二三四五六七八九十]+)\s+(?!的基础上)(.+?)(?=(?:\n\s*问题\s*(?:\d+|[一二三四五六七八九十]+)\s+(?!的基础上))|附件|$)",
        re.DOTALL,
    )

    matches = pattern.findall(clean_text)

    if matches:
        questions = []
        for num, text in matches:
            # 清理文本：去除多余空白和换行
            cleaned = re.sub(r"\s+", " ", text).strip()
            # 截取合理长度（最多 500 字符）
            if len(cleaned) > 500:
                cleaned = cleaned[:500] + "..."
            questions.append(f"问题{num} {cleaned}")
        return questions

    # 后备：按段落分割，查找以"问题"开头的段落
    lines = clean_text.split("\n")
    questions = [line.strip() for line in lines if line.strip().startswith("问题")]
    return questions if questions else ["问题一：综合分析"]


def _create_fallback_subproblems(analysis: ProblemAnalysis) -> list[SubProblem]:
    """当 decompose 失败时创建应急子问题。

    确保 expected_outputs 非空，避免 G0 门因 expected_output_empty 失败。
    """
    return fallback_subproblems_from_analysis(analysis)
