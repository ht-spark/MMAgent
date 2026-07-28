"""G1 理解门单元测试。

覆盖：
  - 通过路径：完整状态 → pass
  - 失败路径：小问空 / 依赖成环 / 主类型缺失 / 整体缺失
  - 预算机制：第 N 次失败 → retry / human
  - DAG 校验工具：基本无环 / 自环 / 三角形环 / 跨环 / 不存在的依赖被忽略
"""
from __future__ import annotations

import pytest

from scr.gates.g1_understanding import G1UnderstandingGate, _is_dag
from scr.schemas.common import GateResult
from scr.schemas.problem import (
    ProblemAnalysis,
    ProblemClassification,
    SubProblem,
)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest.fixture
def gate() -> G1UnderstandingGate:
    return G1UnderstandingGate()


@pytest.fixture
def sample_analysis() -> ProblemAnalysis:
    return ProblemAnalysis(
        research_subject="城市经济评价",
        background="5 个城市经济数据",
        explicit_questions=["问题一：建立评价模型", "问题二：分析影响因素"],
        constraints=[],
        expected_outputs=["排名表"],
        keywords=["综合评价"],
    )


@pytest.fixture
def sample_subproblems() -> list[SubProblem]:
    return [
        SubProblem(
            id="q1", task="评价", input_requirements=[],
            expected_outputs=[], dependencies=[], parallelizable=True,
        ),
        SubProblem(
            id="q2", task="分析", input_requirements=[],
            expected_outputs=[], dependencies=["q1"], parallelizable=False,
        ),
    ]


@pytest.fixture
def sample_classification() -> ProblemClassification:
    return ProblemClassification(
        primary_type="evaluation",
        secondary_types=[],
        reasoning="综合评价类",
    )


@pytest.fixture
def complete_state(
    sample_analysis, sample_subproblems, sample_classification
) -> dict:
    return {
        "problem_analysis": sample_analysis,
        "subproblems": sample_subproblems,
        "problem_classification": sample_classification,
    }


# ---------------------------------------------------------------------------
# DAG 校验工具测试
# ---------------------------------------------------------------------------


class TestDAGCheck:
    def test_empty_is_dag(self):
        assert _is_dag([]) is True

    def test_acyclic_is_dag(self, sample_subproblems):
        assert _is_dag(sample_subproblems) is True

    def test_self_loop_is_not_dag(self):
        sp = SubProblem(
            id="q1", task="t", input_requirements=[],
            expected_outputs=[], dependencies=["q1"], parallelizable=True,
        )
        assert _is_dag([sp]) is False

    def test_cycle_is_not_dag(self):
        """q1 → q2 → q3 → q1 的循环依赖。"""
        sps = [
            SubProblem(
                id="q1", task="t1", input_requirements=[],
                expected_outputs=[], dependencies=["q3"], parallelizable=True,
            ),
            SubProblem(
                id="q2", task="t2", input_requirements=[],
                expected_outputs=[], dependencies=["q1"], parallelizable=True,
            ),
            SubProblem(
                id="q3", task="t3", input_requirements=[],
                expected_outputs=[], dependencies=["q2"], parallelizable=True,
            ),
        ]
        assert _is_dag(sps) is False

    def test_dependency_to_nonexistent_ignored(self):
        """指向不存在节点的依赖被忽略（视为外部输入）。"""
        sp = SubProblem(
            id="q1", task="t", input_requirements=[],
            expected_outputs=[], dependencies=["q_unknown"], parallelizable=True,
        )
        assert _is_dag([sp]) is True

    def test_diamond_is_dag(self):
        """菱形依赖：q1 → q2, q1 → q3, q2 → q4, q3 → q4。"""
        sps = [
            SubProblem(
                id="q1", task="t", input_requirements=[],
                expected_outputs=[], dependencies=[], parallelizable=True,
            ),
            SubProblem(
                id="q2", task="t", input_requirements=[],
                expected_outputs=[], dependencies=["q1"], parallelizable=True,
            ),
            SubProblem(
                id="q3", task="t", input_requirements=[],
                expected_outputs=[], dependencies=["q1"], parallelizable=True,
            ),
            SubProblem(
                id="q4", task="t", input_requirements=[],
                expected_outputs=[], dependencies=["q2", "q3"], parallelizable=True,
            ),
        ]
        assert _is_dag(sps) is True


# ---------------------------------------------------------------------------
# G1 通过路径
# ---------------------------------------------------------------------------


class TestG1Pass:
    def test_complete_state_passes(self, gate, complete_state):
        result = gate.evaluate(complete_state)
        assert isinstance(result, GateResult)
        assert result.gate_id == "G1"
        assert result.passed is True
        assert result.failed_checks == []
        assert result.action == "pass"
        assert result.budget_remaining == 2


# ---------------------------------------------------------------------------
# G1 失败路径
# ---------------------------------------------------------------------------


class TestG1Fail:
    def test_analysis_missing(self, gate, sample_subproblems, sample_classification):
        state = {
            "subproblems": sample_subproblems,
            "problem_classification": sample_classification,
        }
        result = gate.evaluate(state)
        assert result.passed is False
        assert "problem_analysis_missing" in result.failed_checks
        assert result.action == "retry"

    def test_explicit_questions_empty(self, gate, sample_subproblems, sample_classification):
        bad_analysis = ProblemAnalysis(
            research_subject="x", background="x",
            explicit_questions=[],  # 空列表
            constraints=[], expected_outputs=[], keywords=[],
        )
        state = {
            "problem_analysis": bad_analysis,
            "subproblems": sample_subproblems,
            "problem_classification": sample_classification,
        }
        result = gate.evaluate(state)
        assert result.passed is False
        assert "explicit_questions_empty" in result.failed_checks

    def test_subproblems_empty(self, gate, sample_analysis, sample_classification):
        state = {
            "problem_analysis": sample_analysis,
            "subproblems": [],
            "problem_classification": sample_classification,
        }
        result = gate.evaluate(state)
        assert "subproblems_empty" in result.failed_checks

    def test_dependencies_have_cycle(self, gate, sample_analysis, sample_classification):
        cyclic_sps = [
            SubProblem(
                id="q1", task="t", input_requirements=[],
                expected_outputs=[], dependencies=["q2"], parallelizable=True,
            ),
            SubProblem(
                id="q2", task="t", input_requirements=[],
                expected_outputs=[], dependencies=["q1"], parallelizable=True,
            ),
        ]
        state = {
            "problem_analysis": sample_analysis,
            "subproblems": cyclic_sps,
            "problem_classification": sample_classification,
        }
        result = gate.evaluate(state)
        assert "subproblem_dependencies_have_cycle" in result.failed_checks

    def test_classification_missing(self, gate, sample_analysis, sample_subproblems):
        state = {
            "problem_analysis": sample_analysis,
            "subproblems": sample_subproblems,
            # problem_classification 缺失
        }
        result = gate.evaluate(state)
        assert "problem_classification_missing" in result.failed_checks

    def test_multiple_failures_collected(self, gate):
        state = {}  # 全部缺失
        result = gate.evaluate(state)
        assert result.passed is False
        assert "problem_analysis_missing" in result.failed_checks
        assert "subproblems_empty" in result.failed_checks
        assert "problem_classification_missing" in result.failed_checks
        assert len(result.failed_checks) >= 3


# ---------------------------------------------------------------------------
# G1 预算机制
# ---------------------------------------------------------------------------


class TestG1Budget:
    def test_first_failure_action_retry(self, gate):
        state = {}  # 全部缺失
        result = gate.evaluate(state)
        assert result.action == "retry"
        assert result.budget_used == 1
        assert result.budget_remaining == 1

    def test_second_failure_action_retry(self, gate):
        state = {"_g1_budget_used": 1}
        result = gate.evaluate(state)
        assert result.action == "retry"
        assert result.budget_used == 2
        assert result.budget_remaining == 0

    def test_third_failure_action_human(self, gate):
        state = {"_g1_budget_used": 2}
        result = gate.evaluate(state)
        assert result.action == "human"
        assert result.budget_remaining == 0

    def test_pass_resets_budget(self, gate, complete_state):
        # 即使预算已耗尽，一旦通过就 action="pass"
        complete_state["_g1_budget_used"] = 2
        result = gate.evaluate(complete_state)
        assert result.passed is True
        assert result.action == "pass"