"""数学建模智能体 — 端到端入口。

对应 architecture.md §9：
  python -m math_modeling_agent.main run --problem problem.md --data data.csv
  python -m math_modeling_agent.main run-graph --problem problem.md --data data.csv

串联 L0 → L1 → L2 → L3 → L4 → L5 → L6 形成完整 demo。

支持两种模式：
  - `run`：函数式编排（保留兼容）
  - `run-graph`：LangGraph 编排（带 G1 条件边 + checkpoint）

环境变量从 .env 自动加载（OPENAI_API_KEY / MODEL_NAME / OPENAI_BASE_URL）。
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

# 加载 .env 文件（在导入 agent 之前）
load_dotenv()

from ..layers.l0_understanding import L0UnderstandingSubgraph
from ..layers.l1_research import FakeSearchProvider, SearchHit, L1ResearchSubgraph
from ..layers.l3_data import L3DataSubgraph
from ..layers.l4_solve import L4SolveSubgraph
from ..layers.l5_writing import L5WritingSubgraph
from ..layers.l6_review import L6ReviewSubgraph
from ..schemas.model import ModelCandidate, ModelScore
from ..schemas.problem import ProblemAnalysis, SubProblem
from ..schemas.result import ExecutionResult
from ..tools.file_tools import generate_data_inventory, generate_data_inventories, read_file


# ---------------------------------------------------------------------------
# 占位数据（无 LLM 时使用）
# ---------------------------------------------------------------------------


def _stub_analysis(problem_text: str) -> ProblemAnalysis:
    """无 LLM 时构造最小 ProblemAnalysis。"""
    return ProblemAnalysis(
        research_subject=problem_text[:30] + "..." if len(problem_text) > 30 else problem_text,
        background=problem_text[:100],
        explicit_questions=["问题一：综合评价"],
        constraints=["样本量较小"],
        expected_outputs=["排名表"],
        keywords=["综合评价"],
    )


def _stub_subproblems() -> list[SubProblem]:
    return [SubProblem(
        id="q1", task="综合评价", input_requirements=["数据"],
        expected_outputs=["排名"], dependencies=[], parallelizable=True,
    )]


def _stub_candidate() -> ModelCandidate:
    return ModelCandidate(
        id="q1_c1", name="熵权法", family="客观赋权法",
        required_data=[], assumptions=[], output_description="",
        validation_method="",
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run(
    problem_text: str,
    data_paths: str | Path | list[str | Path],
    output_dir: str | Path | None = None,
    llm: Any | None = None,
    search_provider: Any | None = None,
) -> dict:
    """端到端运行 L0 → L6。

    Args:
        problem_text: 题目文本。
        data_paths: 数据文件路径（单个或列表，Excel 自动展开所有 sheet）。
        output_dir: 产物输出目录（默认 artifacts/<run_id>）。
        llm: 可选 LLM 注入（无 LLM 时使用占位数据）。
        search_provider: 可选 SearchProvider 注入。

    Returns:
        端到端结果 dict。
    """
    # 统一为列表
    if isinstance(data_paths, (str, Path)):
        data_paths = [data_paths]
    data_paths = [str(p) for p in data_paths]

    run_id = uuid.uuid4().hex[:8]
    output_dir = Path(output_dir) if output_dir else Path(f"artifacts/{run_id}")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[main] run_id={run_id}")
    print(f"[main] output_dir={output_dir}")
    print(f"[main] data_files: {data_paths}")

    # L0: 摄入 + 数据画像 + 题目理解
    print("[main] L0: 摄入与理解...")
    # 多文件多 sheet 画像
    inventories = generate_data_inventories(
        data_paths, output_dir=output_dir / "reports"
    )
    print(f"[main] L0: 生成 {len(inventories)} 个数据画像")
    # 第一个画像用于 L0 understand 的上下文
    primary_inventory = inventories[0] if inventories else None

    if llm is not None:
        l0 = L0UnderstandingSubgraph(llm=llm)
        l0_result = l0.run(problem_text, data_paths)
        analysis = l0_result["problem_analysis"]
        subproblems = l0_result["subproblems"]
    else:
        analysis = _stub_analysis(problem_text)
        subproblems = _stub_subproblems()

    # L1: 研究（可选，无 search_provider 时跳过）
    print("[main] L1: 研究...")
    if search_provider is not None and llm is not None:
        l1 = L1ResearchSubgraph(llm=llm, search_provider=search_provider)
        l1.run(analysis, subproblems)
    else:
        print("[main] L1: 跳过（无 LLM 或 search_provider）")

    # L2: 模型决策（无 LLM 时使用占位 candidate）
    print("[main] L2: 模型决策...")
    candidate = _stub_candidate()
    score = ModelScore(
        candidate_id="q1_c1",
        problem_fit=0.8, data_fit=0.8, assumption_validity=0.7,
        validation_feasibility=0.7, interpretability=0.9,
        implementation_feasibility=0.9, innovation=0.5,
        total_score=0.78, reasoning="无 LLM，使用占位",
    )
    selected_models = [(candidate, score)]

    # L3: 数据处理
    print("[main] L3: 数据处理...")
    l3 = L3DataSubgraph(output_dir=output_dir / "data")
    l3_result = l3.run(data_paths[0], primary_inventory, [s for _, s in selected_models])
    processed_data_path = l3_result["processed_data_path"]

    # L4: 求解
    print("[main] L4: 求解...")
    l4 = L4SolveSubgraph(output_dir=output_dir, timeout_seconds=30)
    l4_result = l4.run(processed_data_path, selected_models)
    execution_result = l4_result["execution_result"]

    # L5: 写作
    print("[main] L5: 论文写作...")
    l5 = L5WritingSubgraph(output_dir=output_dir / "paper")
    l5_result = l5.run(
        analysis, subproblems, execution_result,
        selected_model_name=candidate.name,
        selected_models=selected_models,
        subproblem_executions=l4_result.get("subproblem_executions", []),
    )
    paper_path = l5_result["paper_draft_path"]
    paper_text = l5_result["paper_text"]

    # L6: 审查 + 交付
    print("[main] L6: 审查与交付...")
    l6 = L6ReviewSubgraph(output_dir=output_dir)
    l6_result = l6.run(
        problem_analysis=analysis,
        execution_result=execution_result,
        paper_text=paper_text,
        paper_path=paper_path,
        artifacts={
            "processed_data": processed_data_path,
            "code": str(output_dir / "code" / f"{candidate.id}.py"),
            "paper_draft": paper_path,
        },
    )

    print(f"[main] 完成。最终交付包：{l6_result['final_package_dir']}")

    return {
        "run_id": run_id,
        "output_dir": str(output_dir),
        "final_package_dir": l6_result["final_package_dir"],
        "workflow_status": l6_result["workflow_status"],
        "l4_execution": {
            "success": execution_result.success,
            "numeric_outputs": execution_result.numeric_outputs,
        },
        "l5_paper_path": paper_path,
        "l6_review": l6_result["review_report"],
    }


# ---------------------------------------------------------------------------
# LLM 创建
# ---------------------------------------------------------------------------


def _create_llm_from_env() -> Any | None:
    """从环境变量创建 LLM。

    支持两种配置：
      1. OpenAI: OPENAI_API_KEY + MODEL_NAME + OPENAI_BASE_URL
      2. DeepSeek（兼容 OpenAI 接口）: DEEPSEEK_API_KEY + DEEPSEEK_MODEL + DEEPSEEK_BASE_URL
    """
    import os

    # 优先尝试 OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        model_name = os.getenv("MODEL_NAME", "gpt-4o")
        base_url = os.getenv("OPENAI_BASE_URL")
    else:
        # 尝试 DeepSeek
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
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="math-modeling-agent",
        description="数学建模智能体 — 端到端入口",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run（函数式）
    run_parser = subparsers.add_parser("run", help="函数式编排运行完整工作流")
    run_parser.add_argument("--problem", required=True, help="题目文本或文件路径")
    run_parser.add_argument("--data", required=True, nargs="+", help="数据文件路径（可多个，Excel 自动展开所有 sheet）")
    run_parser.add_argument("--output", help="产物输出目录（默认 artifacts/<run_id>）")
    run_parser.add_argument("--no-llm", action="store_true", help="不使用 LLM（占位数据）")

    # run-graph（LangGraph）
    graph_parser = subparsers.add_parser("run-graph", help="LangGraph 编排（带 G1 条件边 + checkpoint）")
    graph_parser.add_argument("--problem", required=True, help="题目文本或文件路径")
    graph_parser.add_argument("--data", required=True, nargs="+", help="数据文件路径（可多个）")
    graph_parser.add_argument("--output", help="产物输出目录")
    graph_parser.add_argument("--no-llm", action="store_true", help="不使用 LLM")

    args = parser.parse_args(argv)

    # 读取题目
    p = Path(args.problem)
    problem_text = p.read_text(encoding="utf-8") if p.exists() and p.is_file() else args.problem

    # 创建 LLM
    llm = None if args.no_llm else _create_llm_from_env()
    if llm is None and not args.no_llm:
        print("[main] 提示：OPENAI_API_KEY 未设置，使用占位数据（无 LLM）")

    try:
        if args.command == "run":
            result = run(problem_text, args.data, output_dir=args.output, llm=llm)
        elif args.command == "run-graph":
            from .graph import run_graph
            final_state = run_graph(
                problem_text=problem_text,
                data_paths=args.data,
                output_dir=args.output,
                llm=llm,
            )
            result = {
                "workflow_status": final_state.get("workflow_status", "unknown"),
                "final_package_dir": final_state.get("final_package_dir", ""),
            }
        else:
            return 1
    except Exception as e:
        import traceback
        print(f"\n[main] 错误: {e}")
        traceback.print_exc()
        return 1

    print(f"\n=== 完成 ===")
    print(f"工作流状态: {result['workflow_status']}")
    print(f"最终包: {result['final_package_dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())