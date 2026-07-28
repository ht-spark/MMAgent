"""L0 子图单元测试。

使用 FakeLLM 注入，不需要真实 API Key。
覆盖：
  - 完整流程（data_inventory + understand + decompose + classify + G1 通过）
  - G1 失败重试（第 1 次产出不合格 → 第 2 次产出合格）
  - 数据文件失败不影响流程
  - 空数据文件列表
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from scr.layers.l0_understanding import L0UnderstandingSubgraph
from scr.schemas.problem import (
    ProblemAnalysis,
    ProblemClassification,
    SubProblem,
    SubProblemList,
)


# ---------------------------------------------------------------------------
# FakeLLM（支持按调用顺序返回不同响应）
# ---------------------------------------------------------------------------


class _FakeStructuredLLM:
    def __init__(self, responses: list[Any], counter: list[int]) -> None:
        self._responses = responses
        self._counter = counter

    def invoke(self, prompt: str) -> Any:
        idx = min(self._counter[0], len(self._responses) - 1)
        self._counter[0] += 1
        return self._responses[idx]


class FakeLLM:
    """支持按调用顺序返回多个响应的假 LLM。"""

    def __init__(self) -> None:
        self._sequences: dict[type, list[Any]] = {}
        self._counters: dict[type, list[int]] = {}

    def register_sequence(self, schema_type: type, responses: list[Any]) -> None:
        self._sequences[schema_type] = responses
        self._counters[schema_type] = [0]

    def with_structured_output(self, schema_type: type) -> _FakeStructuredLLM:
        if schema_type not in self._sequences:
            raise ValueError(f"No fake response registered for {schema_type}")
        return _FakeStructuredLLM(
            self._sequences[schema_type],
            self._counters[schema_type],
        )


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def good_analysis() -> ProblemAnalysis:
    return ProblemAnalysis(
        research_subject="城市经济评价",
        background="5 个城市经济数据综合评价",
        explicit_questions=["问题一：建立评价模型并排名"],
        constraints=[],
        expected_outputs=["排名表"],
        keywords=["综合评价", "熵权法"],
    )


@pytest.fixture
def bad_analysis() -> ProblemAnalysis:
    """explicit_questions 为空（应触发 G1 失败）。"""
    return ProblemAnalysis(
        research_subject="x",
        background="x",
        explicit_questions=[],  # 空 → G1 失败
        constraints=[],
        expected_outputs=[],
        keywords=[],
    )


@pytest.fixture
def good_subproblems() -> list[SubProblem]:
    return [
        SubProblem(
            id="q1", task="建立评价模型", input_requirements=[],
            expected_outputs=["排名"], dependencies=[], parallelizable=True,
        ),
    ]


@pytest.fixture
def good_classification() -> ProblemClassification:
    return ProblemClassification(
        primary_type="evaluation",
        secondary_types=[],
        reasoning="综合评价类",
    )


@pytest.fixture
def sample_csv(tmp_path) -> str:
    df = pd.DataFrame({
        "城市": ["北京", "上海", "广州"],
        "GDP(亿元)": [40269, 43215, 28232],
        "人口(万人)": [2189, 2487, 1881],
    })
    path = tmp_path / "city.csv"
    df.to_csv(path, index=False, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------


class TestL0Subgraph:
    def test_full_pipeline_passes_g1(
        self, fake_llm, sample_csv, good_analysis, good_subproblems, good_classification
    ):
        fake_llm.register_sequence(ProblemAnalysis, [good_analysis])
        fake_llm.register_sequence(
            SubProblemList, [SubProblemList(subproblems=good_subproblems)]
        )
        fake_llm.register_sequence(ProblemClassification, [good_classification])

        subgraph = L0UnderstandingSubgraph(llm=fake_llm)
        result = subgraph.run(
            problem_text="5 个城市经济数据综合评价",
            data_files=[sample_csv],
        )

        assert result["workflow_status"] == "l0_completed"
        assert isinstance(result["problem_analysis"], ProblemAnalysis)
        assert isinstance(result["subproblems"], list)
        assert isinstance(result["problem_classification"], ProblemClassification)
        assert result["gate_result"] is not None
        assert result["gate_result"].passed is True
        assert len(result["data_inventories"]) == 1

    def test_g1_fail_then_retry_success(
        self, fake_llm, sample_csv, bad_analysis, good_analysis,
        good_subproblems, good_classification
    ):
        """第 1 次：空小问（G1 失败）→ 第 2 次：完整小问（G1 通过）。"""
        fake_llm.register_sequence(ProblemAnalysis, [bad_analysis, good_analysis])
        fake_llm.register_sequence(
            SubProblemList,
            [
                SubProblemList(subproblems=good_subproblems),  # 第 1 次 decompose
                SubProblemList(subproblems=good_subproblems),  # 第 2 次 decompose
            ],
        )
        fake_llm.register_sequence(
            ProblemClassification, [good_classification, good_classification]
        )

        subgraph = L0UnderstandingSubgraph(llm=fake_llm, max_attempts=3)
        result = subgraph.run(problem_text="题目", data_files=[sample_csv])

        # 第 2 次成功
        assert result["workflow_status"] == "l0_completed"
        assert result["gate_result"].passed is True
        assert result["problem_analysis"].explicit_questions != []

    def test_g1_exhausted_budget(
        self, fake_llm, sample_csv, bad_analysis,
        good_subproblems, good_classification
    ):
        """3 次都失败 → workflow_status = l0_failed。"""
        # 3 次都返回 bad_analysis（空小问）
        fake_llm.register_sequence(
            ProblemAnalysis, [bad_analysis, bad_analysis, bad_analysis]
        )
        fake_llm.register_sequence(
            SubProblemList,
            [SubProblemList(subproblems=good_subproblems)] * 3,
        )
        fake_llm.register_sequence(
            ProblemClassification, [good_classification] * 3
        )

        subgraph = L0UnderstandingSubgraph(llm=fake_llm, max_attempts=3)
        result = subgraph.run(problem_text="题目", data_files=[sample_csv])

        assert result["workflow_status"] == "l0_failed"
        assert result["gate_result"].passed is False
        assert result["gate_result"].action == "human"

    def test_invalid_data_file_skipped(self, fake_llm, good_analysis, good_subproblems, good_classification):
        """不存在的文件被跳过，不影响整体流程。"""
        fake_llm.register_sequence(ProblemAnalysis, [good_analysis])
        fake_llm.register_sequence(
            SubProblemList, [SubProblemList(subproblems=good_subproblems)]
        )
        fake_llm.register_sequence(ProblemClassification, [good_classification])

        subgraph = L0UnderstandingSubgraph(llm=fake_llm)
        result = subgraph.run(
            problem_text="题目",
            data_files=["nonexistent.csv"],  # 不存在
        )

        assert result["workflow_status"] == "l0_completed"
        assert result["data_inventories"] == []  # 空列表

    def test_no_data_files(self, fake_llm, good_analysis, good_subproblems, good_classification):
        """无附件数据时，understand 仍能调用（不传 data_inventory）。"""
        fake_llm.register_sequence(ProblemAnalysis, [good_analysis])
        fake_llm.register_sequence(
            SubProblemList, [SubProblemList(subproblems=good_subproblems)]
        )
        fake_llm.register_sequence(ProblemClassification, [good_classification])

        subgraph = L0UnderstandingSubgraph(llm=fake_llm)
        result = subgraph.run(problem_text="题目", data_files=None)

        assert result["workflow_status"] == "l0_completed"
        assert result["data_inventories"] == []

    def test_llm_exception_keeps_retrying(
        self, fake_llm, sample_csv, good_analysis, good_subproblems, good_classification
    ):
        """LLM 抛异常 → 重试 → 第 2 次成功。"""

        class BoomStructuredLLM:
            """第 1 次调用抛异常。"""
            def __init__(self, real):
                self.real = real
                self.called = 0
            def invoke(self, prompt):
                self.called += 1
                if self.called == 1:
                    raise RuntimeError("LLM 调用失败")
                return self.real.invoke(prompt)

        # 注册两次：第 1 次给 BoomStructuredLLM 用，第 2 次给真实 FakeLLM
        real_responses = [good_analysis]
        fake_llm.register_sequence(ProblemAnalysis, real_responses)

        # 替换 ProblemAnalysis 的 with_structured_output 让它返回 Boom
        original = fake_llm.with_structured_output
        counter = [0]
        def patched_with_structured_output(schema_type):
            if schema_type == ProblemAnalysis:
                counter[0] += 1
                if counter[0] == 1:
                    # 第 1 次：包装抛异常的
                    class Boom:
                        def invoke(self_inner, prompt):
                            raise RuntimeError("LLM 失败")
                    return Boom()
            return original(schema_type)
        fake_llm.with_structured_output = patched_with_structured_output

        fake_llm.register_sequence(
            SubProblemList, [SubProblemList(subproblems=good_subproblems)]
        )
        fake_llm.register_sequence(ProblemClassification, [good_classification])

        subgraph = L0UnderstandingSubgraph(llm=fake_llm, max_attempts=3)
        result = subgraph.run(problem_text="题目", data_files=[sample_csv])

        assert result["workflow_status"] == "l0_completed"
        assert result["gate_result"].passed is True