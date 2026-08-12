"""方法决策 LLM 化单元测试。

覆盖：
  - 有 LLM 时决策由 LLM 综合权衡生成（含 canonical_method 映射）
  - 无 LLM / LLM 选择未知方法时不再回退启发式
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
            "source": "llm_think",
            "eliminated": False,
        },
        {
            "name": "遗传算法",
            "family": "进化算法",
            "description": "全局寻优算法",
            "pros": ["非线性也可用"],
            "cons": ["结果随机"],
            "implementation_difficulty": "high",
            "canonical_method": "",
            "source": "web_search",
            "eliminated": False,
        },
    ]


def _llm_payload(selected_method: str = "线性规划模型") -> str:
    return json.dumps({
        "selected_method": selected_method,
        "canonical_method": "linear_programming",
        "canonical_family": "线性规划",
        "reason": "题意匹配且数据支持，可确定性求解",
        "validation_method": "约束可行性检验与参数扰动",
        "assumptions": ["目标与约束均为线性"],
        "required_outputs": ["optimal_solution", "optimal_objective"],
        "validation_requirements": ["constraint_satisfaction", "parameter_perturbation"],
    })


def test_decide_uses_llm_reference_when_available():
    """有 LLM 时候选方法只作为问题驱动建模参考。"""
    explorer = MethodExplorer(
        llm=MockStructuredLLM(_llm_payload()), search_tool=None
    )
    decision = explorer.decide(_candidates(), _context(), _interpretation())

    assert decision["decision_source"] == "llm"
    assert decision["selected_method"] == "问题驱动建模"
    assert decision["canonical_method"] == ""
    assert decision["selected_details"]["name"] == "线性规划模型"
    assert decision["selected_reason"].startswith("题意匹配")
    assert decision["assumptions"] == ["目标与约束均为线性"]
    assert decision["required_outputs"] == ["optimal_solution", "optimal_objective"]
    assert "score" not in decision["alternatives"][0]


def test_decide_without_llm_does_not_use_heuristic():
    """无 LLM 时不再用启发式选择候选。"""
    explorer = MethodExplorer(llm=None, search_tool=None)
    decision = explorer.decide(_candidates(), _context(), _interpretation())

    assert decision["decision_source"] == "llm_unavailable"
    assert decision["selected_method"] == "无可用方法"
    assert "未启用非 LLM 回退策略" in decision["selected_reason"]


def test_decide_unknown_llm_pick_does_not_use_heuristic():
    """LLM 选择不在候选列表中时不再回退启发式。"""
    explorer = MethodExplorer(
        llm=MockStructuredLLM(_llm_payload("不存在的方法")), search_tool=None
    )
    decision = explorer.decide(_candidates(), _context(), _interpretation())

    assert decision["decision_source"] == "llm_unavailable"
    assert decision["selected_method"] == "无可用方法"
