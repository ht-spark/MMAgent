"""LangGraph 集成：主图组装。

对应 architecture.md §9：
  每层编译为独立子图，单测粒度对齐 Phase；
  主图串联子图 + Gate 条件边 + Checkpoint。

简化版（demo）：
  - G1 作为 L0 → L1 的条件边（pass / retry / human）
  - 其余 Gate 只做记录，线性串联
  - 用 MemorySaver 做 checkpoint（可 resume）
  - 保留 main.py 的函数式 run() 作为兼容入口

用法::

    from scr.math_modeling_agent.graph import build_graph, run_graph

    graph = build_graph()
    result = run_graph(graph, problem_text="...", data_path="...")
"""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from ..gates.g1_understanding import G1UnderstandingGate
from ..layers.l1_research import FakeSearchProvider, L1ResearchSubgraph
from ..layers.l3_data import L3DataSubgraph
from ..layers.l4_solve import L4SolveSubgraph
from ..layers.l5_writing import L5WritingSubgraph
from ..layers.l6_review import L6ReviewSubgraph
from ..schemas.model import ModelCandidate, ModelScore
from ..schemas.problem import ProblemAnalysis, SubProblem
from ..schemas.result import ExecutionResult
from ..tools.file_tools import generate_data_inventory, generate_data_inventories


# ---------------------------------------------------------------------------
# State 定义
# ---------------------------------------------------------------------------


class GraphState(TypedDict, total=False):
    """LangGraph 主图状态。"""

    # 输入
    problem_text: str
    data_paths: list  # list[str]，Excel 自动展开所有 sheet
    output_dir: str
    llm: Any
    search_provider: Any

    # L0
    problem_analysis: ProblemAnalysis
    subproblems: list  # list[SubProblem]
    data_inventory: Any
    problem_classification: Any

    # L1
    knowledge_gaps: list
    evidence_items: list

    # L2
    selected_models: list  # list[(ModelCandidate, ModelScore)]

    # L3
    processed_data_path: str

    # L4
    execution_result: ExecutionResult

    # L5
    paper_text: str
    paper_path: str

    # L6
    final_package_dir: str
    workflow_status: str

    # 运行时
    _g1_budget_used: int
    errors: list


# ---------------------------------------------------------------------------
# Node 函数
# ---------------------------------------------------------------------------


def _l0_node(state: GraphState) -> dict:
    """L0: 摄入 + 数据画像 + 题目理解。"""
    print("[L0] 开始：数据画像 + 题目理解...")
    llm = state.get("llm")
    data_paths = state.get("data_paths", [])
    problem_text = state["problem_text"]

    # 多文件多 sheet 数据画像
    inventories = generate_data_inventories(data_paths) if data_paths else []
    primary_inventory = inventories[0] if inventories else None
    print(f"[L0] 生成 {len(inventories)} 个数据画像")

    if llm is not None:
        # 直接调用 ProblemAnalyst（跳过 L0UnderstandingSubgraph 的重试，自己控制）
        from ..agents.problem_analyst import ProblemAnalyst
        analyst = ProblemAnalyst(llm=llm)
        # 传入数据画像摘要给 LLM（减小 prompt）
        inv_summary = primary_inventory.model_dump_json(indent=2) if primary_inventory else ""
        try:
            print("[L0] 调用 LLM understand...")
            analysis = analyst.understand(problem_text, primary_inventory)
            print(f"[L0] 小问数: {len(analysis.explicit_questions)}, 关键词: {analysis.keywords[:5]}")
        except Exception as e:
            print(f"[L0] understand 失败: {e}")
            analysis = None

        if analysis is not None:
            try:
                print("[L0] 调用 LLM decompose...")
                subproblems = analyst.decompose(analysis)
                print(f"[L0] decompose 完成: {len(subproblems)} 个子问题")
            except Exception as e:
                print(f"[L0] decompose 失败: {e}")
                subproblems = []

            try:
                print("[L0] 调用 LLM classify...")
                classification = analyst.classify(analysis, subproblems) if subproblems else None
                print(f"[L0] classify 完成: {classification.primary_type if classification else 'N/A'}")
            except Exception as e:
                print(f"[L0] classify 失败: {e}")
                classification = None
        else:
            subproblems = []
            classification = None

        # 如果 decompose 返回空 → 在 L0 内部重试一次（不同的 temperature 或简化 prompt）
        if not subproblems and analysis is not None:
            print("[L0] subproblems 为空，重试 decompose（简化版）...")
            try:
                subproblems = [SubProblem(
                    id="q1",
                    task=analysis.explicit_questions[0] if analysis.explicit_questions else "综合分析",
                    input_requirements=analysis.keywords[:5] if analysis.keywords else [],
                    expected_outputs=analysis.expected_outputs[:3] if analysis.expected_outputs else [],
                    dependencies=[],
                    parallelizable=True,
                )]
                print("[L0] 使用应急子问题（1 个）")
            except Exception:
                pass
    else:
        # 占位分支（无 LLM）
        from ..schemas.problem import ProblemClassification
        analysis = ProblemAnalysis(
            research_subject=problem_text[:30],
            background=problem_text[:100],
            explicit_questions=["问题一：综合评价"],
            constraints=[],
            expected_outputs=["排名"],
            keywords=[],
        )
        subproblems = [SubProblem(
            id="q1", task="综合评价", input_requirements=[],
            expected_outputs=[], dependencies=[], parallelizable=True,
        )]
        classification = ProblemClassification(
            primary_type="evaluation",
            secondary_types=[],
            reasoning="占位分类",
        )

    return {
        "problem_analysis": analysis,
        "subproblems": subproblems,
        "data_inventory": primary_inventory,
        "problem_classification": classification,
    }


def _route_g1(state: GraphState) -> str:
    """G1 路由：pass → l1, retry → l0, human → END。预算 3 次防无限循环。"""
    gate = G1UnderstandingGate()
    budget_used = int(state.get("_g1_budget_used", 0))

    # 如果 subproblems 为空但是在 _l0_node 已经尝试过应急方案 → 直接 pass
    subproblems = state.get("subproblems", [])
    if not subproblems:
        budget_used += 1  # 手动递增

    result = gate.evaluate({
        "problem_analysis": state.get("problem_analysis"),
        "subproblems": subproblems,
        "problem_classification": state.get("problem_classification"),
        "_g1_budget_used": budget_used,
    })

    if result.passed:
        return "pass"

    # 防止无限循环：最多 retry 2 次
    if budget_used >= 2:
        print(f"[G1] 预算耗尽（{budget_used} 次），强制通过 → END")
        return "human"

    return "retry"


def _l1_node(state: GraphState) -> dict:
    """L1: 研究（可选，无 search_provider 时跳过）。"""
    llm = state.get("llm")
    sp = state.get("search_provider")
    analysis = state.get("problem_analysis")
    subproblems = state.get("subproblems", [])

    if llm is not None and sp is not None and analysis is not None:
        l1 = L1ResearchSubgraph(llm=llm, search_provider=sp)
        result = l1.run(analysis, subproblems)
        return {
            "knowledge_gaps": result.get("knowledge_gaps", []),
            "evidence_items": result.get("evidence_items", []),
        }
    return {"knowledge_gaps": [], "evidence_items": []}


def _l2_node(state: GraphState) -> dict:
    """L2: 模型决策（无 LLM 时使用占位候选）。"""
    print("[L2] 开始：模型决策...")
    llm = state.get("llm")
    analysis = state.get("problem_analysis")
    subproblems = state.get("subproblems", [])

    if llm is not None and analysis is not None:
        try:
            from ..agents.modeling_agent import ModelingAgent
            agent = ModelingAgent(llm=llm)
            print("[L2] 调用 LLM generate_candidates...")
            candidates, scores, _ = agent.run_modeling(
                analysis, subproblems, state.get("data_inventory"),
                state.get("evidence_items"),
            )
            selected = list(zip(candidates, scores))
            print(f"[L2] 生成 {len(selected)} 个候选模型")
        except Exception as e:
            print(f"[L2] LLM 调用失败：{e}，降级为占位")
            llm = None
    if llm is None or analysis is None:
        candidate = ModelCandidate(
            id="q1_c1", name="熵权法", family="客观赋权法",
            required_data=[], assumptions=[], output_description="",
            validation_method="",
        )
        score = ModelScore(
            candidate_id="q1_c1",
            problem_fit=0.8, data_fit=0.8, assumption_validity=0.7,
            validation_feasibility=0.7, interpretability=0.9,
            implementation_feasibility=0.9, innovation=0.5,
            total_score=0.78, reasoning="占位",
        )
        selected = [(candidate, score)]

    return {"selected_models": selected}


def _l3_node(state: GraphState) -> dict:
    """L3: 数据处理。"""
    output_dir = state.get("output_dir", "artifacts/default")
    data_paths = state.get("data_paths", [])
    l3 = L3DataSubgraph(output_dir=f"{output_dir}/data")
    result = l3.run(
        data_paths[0] if data_paths else "",
        state["data_inventory"],
        [s for _, s in state.get("selected_models", [])],
    )
    return {"processed_data_path": result["processed_data_path"]}


def _l4_node(state: GraphState) -> dict:
    """L4: 求解。"""
    output_dir = state.get("output_dir", "artifacts/default")
    l4 = L4SolveSubgraph(output_dir=output_dir, timeout_seconds=30)
    result = l4.run(
        state["processed_data_path"],
        state.get("selected_models", []),
    )
    return {"execution_result": result["execution_result"]}


def _l5_node(state: GraphState) -> dict:
    """L5: 论文写作。"""
    output_dir = state.get("output_dir", "artifacts/default")
    l5 = L5WritingSubgraph(output_dir=f"{output_dir}/paper")
    selected = state.get("selected_models", [])
    model_name = selected[0][0].name if selected else ""
    result = l5.run(
        state["problem_analysis"],
        state.get("subproblems", []),
        state["execution_result"],
        selected_model_name=model_name,
    )
    return {
        "paper_text": result["paper_text"],
        "paper_path": result["paper_draft_path"],
    }


def _l6_node(state: GraphState) -> dict:
    """L6: 审查与交付。"""
    output_dir = state.get("output_dir", "artifacts/default")
    l6 = L6ReviewSubgraph(output_dir=output_dir)
    result = l6.run(
        problem_analysis=state["problem_analysis"],
        execution_result=state["execution_result"],
        paper_text=state["paper_text"],
        paper_path=state["paper_path"],
        artifacts={
            "processed_data": state.get("processed_data_path", ""),
        },
    )
    return {
        "final_package_dir": result["final_package_dir"],
        "workflow_status": result["workflow_status"],
    }


# ---------------------------------------------------------------------------
# 主图构建
# ---------------------------------------------------------------------------


def build_graph(checkpoint: bool = True):
    """构建 LangGraph 主图。

    Args:
        checkpoint: 是否启用 MemorySaver checkpoint（可 resume）。

    Returns:
        编译后的 LangGraph app。
    """
    builder = StateGraph(GraphState)

    # 添加节点
    builder.add_node("l0", _l0_node)
    builder.add_node("l1", _l1_node)
    builder.add_node("l2", _l2_node)
    builder.add_node("l3", _l3_node)
    builder.add_node("l4", _l4_node)
    builder.add_node("l5", _l5_node)
    builder.add_node("l6", _l6_node)

    # 边
    builder.add_edge(START, "l0")
    # G1 条件边：L0 → L1 / L0 / END
    builder.add_conditional_edges(
        "l0",
        _route_g1,
        {"pass": "l1", "retry": "l0", "human": END},
    )
    # 其余线性串联
    builder.add_edge("l1", "l2")
    builder.add_edge("l2", "l3")
    builder.add_edge("l3", "l4")
    builder.add_edge("l4", "l5")
    builder.add_edge("l5", "l6")
    builder.add_edge("l6", END)

    # Checkpoint
    if checkpoint:
        return builder.compile(checkpointer=MemorySaver())
    return builder.compile()


# ---------------------------------------------------------------------------
# 运行入口
# ---------------------------------------------------------------------------


def run_graph(
    problem_text: str,
    data_paths: str | list[str],
    output_dir: str | None = None,
    llm: Any | None = None,
    search_provider: Any | None = None,
    checkpoint: bool = True,
) -> dict:
    """用 LangGraph 运行完整工作流。

    Args:
        problem_text: 题目文本。
        data_paths: 数据文件路径（单个或列表，Excel 自动展开所有 sheet）。
        output_dir: 产物目录。
        llm: 可选 LLM 注入（无则使用占位数据）。
        search_provider: 可选搜索 Provider。
        checkpoint: 是否启用 checkpoint。

    Returns:
        最终 State。
    """
    import uuid

    # 统一为列表
    if isinstance(data_paths, str):
        data_paths = [data_paths]

    run_id = uuid.uuid4().hex[:8]
    output_dir = output_dir or f"artifacts/{run_id}"

    app = build_graph(checkpoint=checkpoint)
    config = {"configurable": {"thread_id": run_id}}

    initial_state: GraphState = {
        "problem_text": problem_text,
        "data_paths": data_paths,
        "output_dir": output_dir,
        "llm": llm,
        "search_provider": search_provider,
    }

    final_state = app.invoke(initial_state, config=config)
    return dict(final_state)