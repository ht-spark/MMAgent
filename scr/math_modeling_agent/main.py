"""
数学建模智能体 — 端到端入口。
当前为 Phase 0 骨架：
  - 初始化项目状态
  - 创建产物目录结构
  - 后续阶段将逐步添加完整工作流
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from .state import create_initial_state
from ..runtime.artifacts import ArtifactManager
from ..runtime.budget import BudgetManager, BudgetType, DEFAULT_BUDGETS
from ..runtime.logging import get_logger
from ..tools.file_tools import read_file


# ---------------------------------------------------------------------------
# LLM 创建
# ---------------------------------------------------------------------------


def _create_llm_from_env() -> Any | None:
    """从环境变量创建 LLM。

    支持两种配置：
      1. OpenAI: OPENAI_API_KEY + MODEL_NAME + OPENAI_BASE_URL
      2. DeepSeek（兼容 OpenAI 接口）: DEEPSEEK_API_KEY + DEEPSEEK_MODEL + DEEPSEEK_BASE_URL
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        model_name = os.getenv("MODEL_NAME", "gpt-4o")
        base_url = os.getenv("OPENAI_BASE_URL")
    else:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return None
        model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        print(f"[main] 使用 DeepSeek API（model={model_name}）")

    try:
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {"model": model_name, "api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)
    except ImportError:
        print("[main] 警告：langchain-openai 未安装，LLM 功能不可用")
        return None


# ---------------------------------------------------------------------------
# 预算交互
# ---------------------------------------------------------------------------


def _make_budget_config_callback(pause_at: list[str] | None):
    """构造 budget_config_callback：在指定小问让用户在 STDIN 覆盖预算上限。

    - pause_at 为空：每个有小问都暂停询问。
    - pause_at 非空：仅列表中的小问暂停询问，其余沿用默认（返回 None）。
    - 非交互终端（stdin 非 tty）：直接返回 None，不阻断自动化/批处理运行。

    返回的函数签名满足 run_graph 要求：``(state) -> dict[BudgetType, int] | None``。
    """
    enforced = [
        BudgetType.SEARCH,
        BudgetType.CANDIDATE,
        BudgetType.CODE_REPAIR,
        BudgetType.VALIDATION_ITERATION,
    ]
    labels = {
        BudgetType.SEARCH: "联网检索次数上限 (search)",
        BudgetType.CANDIDATE: "方法候选数量上限 (candidate)",
        BudgetType.CODE_REPAIR: "代码修复次数上限 (code_repair)",
        BudgetType.VALIDATION_ITERATION: "验证迭代次数上限 (validation)",
    }

    def callback(state: dict):
        qid = state.get("current_question_id")
        if pause_at and qid not in pause_at:
            return None
        if not sys.stdin.isatty():
            return None
        print(f"\n=== 预算设置（小问 {qid}）===")
        print("  回车保留默认上限；输入正整数覆盖单问上限。")
        overrides: dict = {}
        for bt in enforced:
            default = DEFAULT_BUDGETS[bt]
            try:
                raw = input(f"  {labels[bt]} [{default}]: ").strip()
            except (EOFError, KeyboardInterrupt):
                return None
            if raw:
                try:
                    val = int(raw)
                    if val > 0:
                        overrides[bt] = val
                except ValueError:
                    pass
        return overrides or None

    return callback


def _print_budget_report(budget_manager: BudgetManager) -> None:
    """打印预算消耗报告：每问消耗 + 任务总消耗。"""
    report = budget_manager.to_dict()
    limits = report["limits"]
    total = report["run_total_used"]
    per_enf = report.get("per_question_enforced_usage", {})
    per_mon = report.get("per_question_monitor_usage", {})

    enforced_types = [
        BudgetType.SEARCH.value,
        BudgetType.CANDIDATE.value,
        BudgetType.CODE_REPAIR.value,
        BudgetType.VALIDATION_ITERATION.value,
    ]

    print("  [强制预算·每问消耗]")
    all_qids = sorted(set(per_enf.keys()) | set(per_mon.keys()))
    if all_qids:
        for qid in all_qids:
            parts: list[str] = []
            for t in enforced_types:
                v = per_enf.get(qid, {}).get(t)
                if v:
                    parts.append(f"{t}={v}")
            mon = per_mon.get(qid, {})
            if mon:
                if mon.get("token"):
                    parts.append(f"token={mon['token']}")
                if mon.get("time"):
                    parts.append(f"time={mon['time']:.1f}s")
            print(f"    {qid}: " + (", ".join(parts) if parts else "（无消耗）"))
    else:
        print("    （暂无小问消耗记录）")

    print("  [监控预算·任务总消耗]")
    print(f"    time={total.get('time', 0):.1f}s  token={total.get('token', 0)}")

    print("  [强制预算·任务总消耗 / 上限]")
    for t in enforced_types:
        print(f"    {t}={total.get(t, 0)}/{limits.get(t)}")


# ---------------------------------------------------------------------------
# 命令：init — 初始化项目骨架
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    """初始化项目：创建状态、产物目录、日志。"""
    # 读取任务
    p = Path(args.problem)
    problem_text = p.read_text(encoding="utf-8") if p.exists() and p.is_file() else args.problem

    # 统一数据路径
    data_paths = args.data or []

    # 创建 LLM
    llm = None if args.no_llm else _create_llm_from_env()
    if llm is None and not args.no_llm:
        print("[main] 提示：OPENAI_API_KEY 未设置，使用无 LLM 模式")

    # 生成 run_id
    run_id = uuid.uuid4().hex[:8]
    output_dir = args.output or f"artifacts/{run_id}"

    # 创建产物目录
    artifacts = ArtifactManager(base_dir="artifacts", run_id=run_id)

    # 创建日志
    logger = get_logger(name="mmagent", run_id=run_id, log_file=artifacts.run_dir / "run.log")
    log_path = artifacts.run_dir / "run.log"

    # 初始化状态
    state = create_initial_state(
        run_id=run_id,
        output_dir=output_dir,
        problem_text=problem_text,
        data_paths=data_paths,
        llm=llm,
    )

    # 复制输入文件到产物目录
    if p.exists() and p.is_file():
        artifacts.copy_input(p)
        logger.info(f"已复制任务文件: {p.name}")

    for dp in data_paths:
        dp_path = Path(dp)
        if dp_path.exists():
            artifacts.copy_input(dp_path)
            logger.info(f"已复制数据文件: {dp_path.name}")

    # 保存初始状态快照
    from ..runtime.checkpoint import CheckpointManager

    ckpt = CheckpointManager(checkpoint_dir="artifacts/_checkpoints", run_id=run_id)
    ckpt.save(phase="init", state={"problem_text": problem_text, "data_paths": data_paths},
              description="项目初始化")

    print(f"\n=== 初始化完成 ===")
    print(f"Run ID: {run_id}")
    print(f"产物目录: {artifacts.run_dir}")
    print(f"日志文件: {log_path}")
    print(f"状态: {state['workflow_status']}")
    print(f"小问数: {len(state['project_context'].questions)} (待 Phase 1 解析)")
    print(f"\n后续阶段将实现:")
    print(f"  Phase 1: 输入摄入与全局上下文")
    print(f"  Phase 2: 逐问求解闭环")
    print(f"  Phase 6: 全任务审查与报告写作")

    return 0


# ---------------------------------------------------------------------------
# 命令：run — 运行工作流（当前为骨架）
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    """运行工作流。当前为 Phase 0 骨架，仅初始化。"""
    import logging as _logging

    from .graph import run_graph

    # 读取任务
    p = Path(args.problem)
    problem_text = p.read_text(encoding="utf-8") if p.exists() and p.is_file() else args.problem

    # 创建 LLM
    llm = None if args.no_llm else _create_llm_from_env()
    if llm is None and not args.no_llm:
        print("[main] 提示：OPENAI_API_KEY 未设置，使用无 LLM 模式")

    # 日志级别
    log_level = getattr(_logging, str(args.log_level).upper(), _logging.INFO)

    # 预算：实例化管理器，并按 --budget-pause-at 构造交互回调
    budget_manager = BudgetManager()
    budget_config_callback = _make_budget_config_callback(args.budget_pause_at)

    try:
        result = run_graph(
            problem_text=problem_text,
            data_paths=args.data,
            output_dir=args.output,
            llm=llm,
            log_level=log_level,
            budget_manager=budget_manager,
            budget_config_callback=budget_config_callback,
        )

        # 打印结果摘要
        print(f"\n{'='*60}")
        print(f"=== 工作流完成 ===")
        print(f"{'='*60}")
        print(f"Run ID: {result.get('run_id', 'N/A')}")
        print(f"产物目录: {result.get('output_dir', 'N/A')}")
        print(f"工作流状态: {result.get('workflow_status', 'unknown')}")

        # 数据画像摘要
        dp = result.get("data_profile")
        if dp:
            print(f"\n--- 数据画像 ---")
            print(f"文件数: {len(dp.files)}")
            print(f"表数: {len(dp.tables)}")
            print(f"字段数: {len(dp.fields)}")
            for finding in dp.preliminary_findings:
                print(f"  → {finding}")

        # 小问求解摘要
        pc = result.get("project_context")
        question_results = result.get("question_results", {})
        if pc:
            print(f"\n--- 小问求解结果 ---")
            print(f"总小问数: {len(pc.questions)}")
            for q in pc.questions:
                qr = question_results.get(q.question_id)
                if qr:
                    status_icon = "✓" if qr.status == "validated" else "✗" if qr.status == "blocked" else "○"
                    print(f"  {status_icon} {q.question_id}: {qr.status}")
                    if qr.problem_interpretation:
                        print(f"      任务类型: {qr.problem_interpretation.math_task}")
                        print(f"      结果形式: {qr.problem_interpretation.result_form}")
                    if qr.reusable_summary:
                        print(f"      可复用结论: {len(qr.reusable_summary.verified_conclusions)} 条")
                    if qr.status == "blocked" and qr.error_message:
                        print(f"      错误: {qr.error_message}")
                else:
                    print(f"  ○ {q.question_id}: 未处理")

        # 决策日志
        dl = result.get("decision_log")
        if dl and dl.entries:
            print(f"\n--- 决策日志 ({len(dl.entries)} 条) ---")
            for entry in dl.entries[-5:]:  # 只显示最近 5 条
                print(f"  [{entry.decision_type}] {entry.description}")

        # 报告草稿摘要
        paper = result.get("paper_draft")
        if paper:
            print(f"\n--- 报告草稿 ---")
            print(f"标题: {paper.title or '(未设置)'}")
            print(f"章节数: {len(paper.sections)}")
            print(f"全文长度: {len(paper.full_text)} 字符")
            print(f"摘要长度: {len(paper.abstract)} 字符")
            print(f"引用数: {len(paper.references)}")
            for s in paper.sections:
                print(f"  → {s.section_id}: {s.title} ({len(s.content)} 字)")

        # 审查报告摘要
        review = result.get("review_report")
        if review:
            print(f"\n--- 审查报告 ---")
            print(f"状态: {review.overall_status}")
            print(f"问题数: {len(review.issues)} (critical={review.critical_count}, major={review.major_count})")
            if review.summary:
                print(f"摘要: {review.summary[:200]}")
            for issue in review.issues[:5]:
                print(f"  [{issue.severity}] {issue.category}: {issue.message}")

        # 错误
        errors = result.get("errors", [])
        if errors:
            print(f"\n--- 错误 ({len(errors)} 条) ---")
            for err in errors:
                print(f"  ✗ {err.get('msg', err)}")

        # 预算消耗报告（每问消耗 + 任务总消耗）
        print(f"\n--- 预算消耗报告 ---")
        _print_budget_report(budget_manager)

    except Exception as e:
        import traceback
        print(f"\n[main] 错误: {e}")
        traceback.print_exc()
        return 1

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="math-modeling-agent",
        description="数学建模智能体 — 端到端入口",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init — 初始化项目骨架
    init_parser = subparsers.add_parser("init", help="初始化项目骨架")
    init_parser.add_argument("--problem", required=True, help="任务文本或文件路径")
    init_parser.add_argument("--data", nargs="+", help="数据文件路径（可多个）")
    init_parser.add_argument("--output", help="产物输出目录")
    init_parser.add_argument("--no-llm", action="store_true", help="不使用 LLM")

    # run — 运行工作流
    run_parser = subparsers.add_parser("run", help="运行工作流（当前为骨架）")
    run_parser.add_argument("--problem", required=True, help="任务文本或文件路径")
    run_parser.add_argument("--data", nargs="+", help="数据文件路径（可多个）")
    run_parser.add_argument("--output", help="产物输出目录")
    run_parser.add_argument("--no-llm", action="store_true", help="不使用 LLM")
    run_parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        default="info",
        help="运行日志级别（写入 run.log，默认 info）",
    )
    run_parser.add_argument(
        "--budget-pause-at",
        nargs="+",
        metavar="QID",
        help="仅在这些小问（如 Q1 Q3）暂停并让用户通过 STDIN 设置预算上限；"
             "省略则每个小问都询问（非交互终端自动跳过）",
    )

    args = parser.parse_args(argv)

    if args.command == "init":
        return cmd_init(args)
    elif args.command == "run":
        return cmd_run(args)
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
