"""方法探索与决策 Agent 测试。"""
from __future__ import annotations

import json

from scr.agents.method_explorer import MethodExplorer
from scr.agents.question_solver import QuestionSolver
from scr.schemas.question import CurrentQuestionContext, ProblemInterpretation


class MockBudgetManager:
    """固定 CANDIDATE 限额并允许 SEARCH/CANDIDATE 消耗的预算管理器。"""

    def __init__(self, candidate_limit: int = 2) -> None:
        self.candidate_limit = candidate_limit
        self.consumed: list[tuple[str, str, int]] = []

    def remaining(self, budget_type, question_id: str) -> int:
        if getattr(budget_type, "name", "") == "CANDIDATE":
            return self.candidate_limit
        return 1

    def consume(self, budget_type, amount: int = 1, question_id: str = "") -> bool:
        self.consumed.append((getattr(budget_type, "name", str(budget_type)), question_id, amount))
        return True


class MockSearchTool:
    available = True

    def search_methods(self, math_task: str, problem_description: str) -> list[dict]:
        return [
            {
                "title": "Optimization method",
                "url": "https://example.com/optimization",
                "content": "Linear programming and robust optimization are common.",
                "score": 0.9,
            }
        ]

    def extract_method_candidates(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("不应调用非 LLM 的搜索启发式提取")


class MockExplorerLLM:
    """按 prompt 类型返回候选列表或最终决策。"""

    def __init__(self, pick: str = "LLM方法1") -> None:
        self._schema = None
        self.pick = pick

    def with_structured_output(self, schema, method=None):
        self._schema = schema
        return self

    def invoke(self, prompt: str):
        assert self._schema is not None
        schema_name = self._schema.__name__
        if schema_name == "WebMethodCandidateList":
            prefix = "搜索方法" if "搜索结果" in prompt else "LLM方法"
            return self._schema.model_validate({
                "candidates": [
                    {
                        "name": f"{prefix}{i}",
                        "family": "数学规划",
                        "description": f"{prefix}{i} 描述",
                        "pros": ["可实现"],
                        "cons": ["需校验假设"],
                        "assumptions": ["输入数据可用"],
                        "required_data": ["题目数据"],
                        "implementation_difficulty": "medium",
                        "validation_method": "敏感性分析",
                        "required_outputs": ["solution"],
                        "validation_requirements": ["feasibility_check"],
                        "source_url": "https://example.com" if prefix == "搜索方法" else "",
                        "source_title": "search" if prefix == "搜索方法" else "",
                        "relevance_score": 0.8,
                    }
                    for i in range(1, 3)
                ]
            })
        return self._schema.model_validate_json(json.dumps({
            "selected_method": self.pick,
            "canonical_method": "linear_programming",
            "canonical_family": "数学规划",
            "reason": "由 LLM 在候选中综合判断",
            "validation_method": "约束可行性检验",
            "assumptions": ["目标与约束可数学表达"],
            "required_outputs": ["solution"],
            "validation_requirements": ["feasibility_check"],
        }))


def _context() -> CurrentQuestionContext:
    return CurrentQuestionContext(
        question_id="q1",
        question_text="问题1 求最优方案",
        objective="求最优方案",
        data_quality_summary="1 张表、100 行数据",
    )


def _interpretation(math_task: str = "optimization") -> ProblemInterpretation:
    return ProblemInterpretation(
        question_id="q1",
        math_task=math_task,
        math_task_description="在约束下求收益最大",
        result_form="最优方案表",
    )


def test_explore_without_llm_returns_no_candidates():
    """无 LLM 时不生成 fallback 候选。"""
    explorer = MethodExplorer(llm=None, search_tool=None)

    candidates = explorer.explore(_context(), _interpretation())
    decision = explorer.decide(candidates, _context(), _interpretation())

    assert candidates == []
    assert decision["decision_source"] == "none"
    assert decision["selected_method"] == "无可用方法"


def test_explore_without_search_uses_llm_think_only():
    """联网搜索不可用时，只由 LLM 生成预算 N 个候选。"""
    explorer = MethodExplorer(
        llm=MockExplorerLLM(),
        search_tool=None,
        budget_manager=MockBudgetManager(candidate_limit=2),
    )

    candidates = explorer.explore(_context(), _interpretation())

    assert len(candidates) == 2
    assert {c["source"] for c in candidates} == {"llm_think"}
    assert all("heuristic_score" not in c for c in candidates)
    assert all(c["eliminated"] is False for c in candidates)


def test_explore_with_search_uses_search_and_llm_branches():
    """搜索可用时，搜索整理和 LLM 思考各生成 N 个候选。"""
    budget = MockBudgetManager(candidate_limit=2)
    explorer = MethodExplorer(
        llm=MockExplorerLLM(),
        search_tool=MockSearchTool(),
        budget_manager=budget,
    )

    candidates = explorer.explore(_context(), _interpretation())

    assert len(candidates) == 4
    assert [c["source"] for c in candidates].count("web_search") == 2
    assert [c["source"] for c in candidates].count("llm_think") == 2
    assert all("heuristic_score" not in c for c in candidates)
    assert any(entry[0] == "SEARCH" for entry in budget.consumed)


def test_explore_and_decide_uses_llm_final_pick():
    """最终方法由 LLM 在全部候选中判断。"""
    explorer = MethodExplorer(
        llm=MockExplorerLLM(pick="搜索方法1"),
        search_tool=MockSearchTool(),
        budget_manager=MockBudgetManager(candidate_limit=2),
    )

    candidates, decision = explorer.explore_and_decide(_context(), _interpretation())

    assert len(candidates) == 4
    assert decision["decision_source"] == "llm"
    assert decision["selected_method"] == "搜索方法1"
    assert decision["canonical_method"] == "linear_programming"
    assert decision["eliminated"] == []


def test_question_solver_without_llm_does_not_fabricate_method():
    """QuestionSolver 无 LLM 时流程不中断，但不再伪造候选方法。"""
    solver = QuestionSolver(llm=None, search_tool=None)
    context = CurrentQuestionContext(
        question_id="q1",
        question_text="问题1 建立评价模型",
        objective="建立评价模型",
    )

    result = solver.solve(context, data_profile=None)

    assert result.method_candidates == []
    assert result.decision_record["decision_source"] == "none"
    assert result.decision_record["selected_method"] == "无可用方法"
    assert result.assumptions == []
