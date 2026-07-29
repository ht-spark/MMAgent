"""ModelingAgent 单元测试（demo 简化版）。"""
from __future__ import annotations

from typing import Any

import pytest

from scr.agents.modeling_agent import ModelingAgent
from scr.schemas.model import (
    ModelCandidate,
    ModelCandidateList,
    ModelCriticReport,
    compute_total_score,
)
from scr.schemas.problem import ProblemAnalysis, SubProblem


class _FakeStructuredLLM:
    def __init__(self, response: Any) -> None:
        self._response = response

    def invoke(self, prompt: str) -> Any:
        return self._response


class FakeLLM:
    def __init__(self) -> None:
        self._responses: dict[type, Any] = {}

    def register(self, schema_type: type, response: Any) -> None:
        self._responses[schema_type] = response

    def with_structured_output(self, schema_type: type) -> _FakeStructuredLLM:
        return _FakeStructuredLLM(self._responses[schema_type])


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def sample_analysis() -> ProblemAnalysis:
    return ProblemAnalysis(
        research_subject="城市经济综合评价",
        background="5 个城市经济数据",
        explicit_questions=["问题一：综合评价排名"],
        constraints=["样本量小"],
        expected_outputs=["排名表"],
        keywords=["综合评价"],
    )


@pytest.fixture
def sample_subproblems() -> list[SubProblem]:
    return [
        SubProblem(
            id="q1", task="综合评价", input_requirements=["GDP", "人口"],
            expected_outputs=["排名"], dependencies=[], parallelizable=True,
        ),
    ]


def test_compute_total_score():
    """评分公式正确性。"""
    # 全 1 分：加权求和 = 1.0
    assert compute_total_score(
        problem_fit=1.0, data_fit=1.0, assumption_validity=1.0,
        validation_feasibility=1.0, interpretability=1.0,
        implementation_feasibility=1.0, innovation=1.0,
    ) == 1.0
    # 全 0 分
    assert compute_total_score(
        problem_fit=0.0, data_fit=0.0, assumption_validity=0.0,
        validation_feasibility=0.0, interpretability=0.0,
        implementation_feasibility=0.0, innovation=0.0,
    ) == 0.0
    # 部分：0.25*0.8 + 0.20*0.6 + 0.15*0.7 + 0.15*0.5 + 0.10*0.9 + 0.10*0.8 + 0.05*0.5
    # = 0.20 + 0.12 + 0.105 + 0.075 + 0.09 + 0.08 + 0.025 = 0.695
    result = compute_total_score(
        problem_fit=0.8, data_fit=0.6, assumption_validity=0.7,
        validation_feasibility=0.5, interpretability=0.9,
        implementation_feasibility=0.8, innovation=0.5,
    )
    assert abs(result - 0.695) < 0.001


def test_generate_candidates(fake_llm, sample_analysis, sample_subproblems):
    """候选生成：LLM 返回候选 → Agent 直接透传。"""
    candidates = [
        ModelCandidate(
            id="q1_c1", name="熵权法", family="客观赋权法",
            required_data=["GDP", "人口"],
            assumptions=["指标独立"],
            output_description="权重 + 得分",
            validation_method="权重扰动",
            supporting_evidence_ids=["src_001"],
            pros=["客观", "易实现"],
            cons=["要求指标独立"],
            elimination_conditions=[],
        ),
        ModelCandidate(
            id="q1_c2", name="TOPSIS", family="逼近理想解法",
            required_data=["GDP", "人口"],
            assumptions=["指标可比"],
            output_description="贴近度 + 排名",
            validation_method="敏感性分析",
            supporting_evidence_ids=["src_001"],
            pros=["处理多指标"],
            cons=["需要权重输入"],
            elimination_conditions=[],
        ),
    ]
    fake_llm.register(ModelCandidateList, ModelCandidateList(candidates=candidates))
    agent = ModelingAgent(llm=fake_llm)

    result = agent.generate_candidates(sample_analysis, sample_subproblems)
    assert len(result) == 2
    assert result[0].name == "熵权法"
    assert result[1].family == "逼近理想解法"


def test_score_candidates_uses_code_for_total(
    fake_llm, sample_analysis, sample_subproblems
):
    """评分：LLM 给单项 → 代码算 total_score。"""
    # 注册 _ScoreInputList（内部类）
    from scr.agents.modeling_agent import _ScoreInput, _ScoreInputList

    candidates = [
        ModelCandidate(
            id="q1_c1", name="熵权法", family="客观赋权法",
            required_data=["GDP"], assumptions=[],
            output_description="", validation_method="",
        ),
    ]
    fake_llm.register(_ScoreInputList, _ScoreInputList(scores=[
        _ScoreInput(
            candidate_id="q1_c1",
            problem_fit=0.9, data_fit=0.8, assumption_validity=0.7,
            validation_feasibility=0.8, interpretability=0.9,
            implementation_feasibility=0.9, innovation=0.5,
            reasoning="熵权法匹配题目",
        ),
    ]))

    agent = ModelingAgent(llm=fake_llm)
    scores = agent.score_candidates(candidates, sample_analysis, sample_subproblems)
    assert len(scores) == 1
    s = scores[0]
    # 验证 total_score 是代码计算的结果，不是 LLM 给的
    expected_total = compute_total_score(
        0.9, 0.8, 0.7, 0.8, 0.9, 0.9, 0.5
    )
    assert s.total_score == expected_total
    assert abs(s.total_score - 0.815) < 0.001


def test_criticize(fake_llm, sample_analysis):
    """Critic：返回审查报告。"""
    from scr.agents.modeling_agent import ModelingAgent
    from scr.schemas.model import ModelScore

    report = ModelCriticReport(
        overall_judgment="passed",
        checks={"gap_coverage": "通过：候选覆盖了高优缺口"},
        suggested_action="approve",
        reasoning="候选合理，可以进入 H1",
    )
    fake_llm.register(ModelCriticReport, report)

    agent = ModelingAgent(llm=fake_llm)
    scores = [ModelScore(
        candidate_id="q1_c1", problem_fit=0.8, data_fit=0.7,
        assumption_validity=0.7, validation_feasibility=0.7,
        interpretability=0.8, implementation_feasibility=0.8,
        innovation=0.5, total_score=0.74, reasoning="",
    )]
    result = agent.criticize(scores, sample_analysis)
    assert result.overall_judgment == "passed"
    assert "gap_coverage" in result.checks