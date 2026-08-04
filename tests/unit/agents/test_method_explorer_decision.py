"""方法决策 LLM 化（P1-B2）单元测试。

覆盖：
  - 有 LLM 时决策由 LLM 综合权衡生成（含 canonical_method 映射）
  - 无 LLM / LLM 选择未知方法 / LLM 失败时回退启发式
"""
from __future__ import annotations

import json

from scr.agents.method_explorer import MethodExplorer
from scr.schemas.question import CurrentQuestionContext, ProblemInterpretation


class MockStructuredLLM:
    """支持 with_structured_output 的 Mock LLM：invoke 返回 schema 实例。"""

    def __init__(self, payload) -> None:
        self._payload = payload
        self._schema = None

    def with_structured_output(self, schema, method=None):
        self._schema = schema
        return self

    def invoke(self, prompt: str):
        assert self._schema is not None, "with_structured_output 未被调用"
        return self._schema.model_validate_json(self._payload)


def _context() -> CurrentQuestionContext:
    return CurrentQuestionContext(
        question_id="q1",
        question_text="求最优种植方案使总收益最大",
        objective="求最优种植方案使总收益最大",
        global_background="",
        global_constraints=[],
        required_data=["data.csv"],
        data_quality_summary="1 张表、99 行",
        inherited_summaries=[],
        budget_info={},
    )


def _interpretation() -> ProblemInterpretation:
    return ProblemInterpretation(
        question_id="q1",
        math_task="optimization",
        math_task_description="在种植成本与土地约束下最大化总收益",
        decision_variables=["x_i"],
        objective_function="max sum(p_i*x_i)",
        constraints=["sum(x_i)<=120"],
        available_data=["data.csv"],
    )


def _candidates() -> list[dict]:
    return [
        {
            "name": "线性规划模型",
            "family": "线性规划",
            "description": "在资源约束下求目标最优",
            "pros": ["可求得全局最优"],
            "cons": ["要求线性"],
            "implementation_difficulty": "low",
            "canonical_method": "",
            "heuristic_score": 0.8,
            "eliminated": False,
        },
        {
            "name": "遗传算法",
            "family": "进化算法",
            "description": "启发式全局寻优",
            "pros": ["非线性也可用"],
            "cons": ["结果随机"],
            "implementation_difficulty": "high",
            "canonical_method": "",
            "heuristic_score": 0.6,
            "eliminated": False,
        },
    ]


def _llm_payload() -> str:
    return json.dumps({
        "selected_method": "线性规划模型",
        "canonical_method": "linear_programming",
        "canonical_family": "线性规划",
        "reason": "题意匹配且数据支持，可确定性求解",
        "validation_method": "约束可行性检验与参数扰动",
        "assumptions": ["目标与约束均为线性"],
        "required_outputs": ["optimal_solution", "optimal_objective"],
        "validation_requirements": ["constraint_satisfaction", "parameter_perturbation"],
    })


def test_decide_uses_llm_when_available():
    """有 LLM 时决策使用 LLM 的选择与 canonical 映射。"""
    explorer = MethodExplorer(
        llm=MockStructuredLLM(_llm_payload()), search_tool=None
    )
    decision = explorer.decide(_candidates(), _context(), _interpretation())

    assert decision["decision_source"] == "llm"
    assert decision["selected_method"] == "线性规划模型"
    assert decision["canonical_method"] == "linear_programming"
    assert decision["selected_reason"].startswith("题意匹配")
    assert decision["assumptions"] == ["目标与约束均为线性"]
    assert decision["required_outputs"] == ["optimal_solution", "optimal_objective"]


def test_decide_falls_back_without_llm():
    """无 LLM 时回退启发式：取启发式评分最高者。"""
    explorer = MethodExplorer(llm=None, search_tool=None)
    decision = explorer.decide(_candidates(), _context(), _interpretation())

    assert decision["decision_source"] == "heuristic"
    assert decision["selected_method"] == "线性规划模型"  # 分数 0.8 最高
    assert decision["canonical_method"] == ""


def test_decide_falls_back_when_llm_picks_unknown_method():
    """LLM 选择不在候选列表中的方法时回退启发式。"""
    payload = json.dumps({
        "selected_method": "不存在的方法",
        "canonical_method": "",
        "canonical_family": "",
        "reason": "测试",
        "validation_method": "",
        "assumptions": [],
        "required_outputs": [],
        "validation_requirements": [],
    })
    explorer = MethodExplorer(
        llm=MockStructuredLLM(payload), search_tool=None
    )
    decision = explorer.decide(_candidates(), _context(), _interpretation())

    assert decision["decision_source"] == "heuristic"
    assert decision["selected_method"] == "线性规划模型"
