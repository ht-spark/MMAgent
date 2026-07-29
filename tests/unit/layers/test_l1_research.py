"""L1 子图单元测试（demo 简化版）。"""
from __future__ import annotations

from typing import Any

from scr.layers.l1_research import FakeSearchProvider, L1ResearchSubgraph, SearchHit
from scr.schemas.problem import ProblemAnalysis, SubProblem
from scr.schemas.research import (
    EvidenceItem,
    EvidenceItemList,
    KnowledgeGap,
    KnowledgeGapList,
    SearchRequest,
    SearchRequestList,
)


class _FakeStructuredLLM:
    def __init__(self, response: Any) -> None:
        self._response = response

    def invoke(self, prompt: str) -> Any:
        return self._response


class FakeLLM:
    """L1 测试用：返回固定响应。"""

    def __init__(self) -> None:
        self._responses: dict[type, Any] = {}

    def register(self, schema_type: type, response: Any) -> None:
        self._responses[schema_type] = response

    def with_structured_output(self, schema_type: type) -> _FakeStructuredLLM:
        return _FakeStructuredLLM(self._responses[schema_type])


def _make_setup() -> tuple[ProblemAnalysis, list[SubProblem], FakeLLM, FakeSearchProvider]:
    analysis = ProblemAnalysis(
        research_subject="城市经济综合评价",
        background="5 个城市经济数据",
        explicit_questions=["问题一：综合评价"],
        constraints=[],
        expected_outputs=["排名表"],
        keywords=["综合评价"],
    )
    subproblems = [
        SubProblem(
            id="q1", task="综合评价", input_requirements=["GDP"],
            expected_outputs=["排名"], dependencies=[], parallelizable=True,
        ),
    ]
    fake_llm = FakeLLM()
    fake_llm.register(KnowledgeGapList, KnowledgeGapList(gaps=[
        KnowledgeGap(
            gap_type="model_precedent",
            description="熵权法标准实现",
            priority="high",
        ),
    ]))
    fake_llm.register(SearchRequestList, SearchRequestList(queries=[
        SearchRequest(
            query="熵权法 综合评价",
            purpose="了解熵权法",
            language="zh",
            source_preference="academic_paper",
            target_gap_type="model_precedent",
        ),
    ]))
    # evidence extraction 默认调用，对每个来源返回 1 条
    fake_llm.register(EvidenceItemList, EvidenceItemList(items=[
        EvidenceItem(
            claim="熵权法基于信息熵",
            source_id="placeholder",  # 实际替换
            source_url="https://placeholder",
            fact_or_inference="fact",
            limitations="",
            confidence=0.8,
        ),
    ]))

    search = FakeSearchProvider({
        "熵权法 综合评价": [
            SearchHit(
                url="https://www.gov.cn/report.pdf",
                title="政府统计报告",
                snippet="介绍综合评价方法",
                content="熵权法基于信息熵原理...",
            ),
            SearchHit(
                url="https://arxiv.org/abs/1234",
                title="Entropy Method Paper",
                snippet="学术论文介绍熵权法",
                content="Entropy weight method...",
            ),
        ],
    })
    return analysis, subproblems, fake_llm, search


def test_full_l1_pipeline_passes_g2():
    analysis, subproblems, fake_llm, search = _make_setup()
    subgraph = L1ResearchSubgraph(llm=fake_llm, search_provider=search)
    result = subgraph.run(analysis, subproblems)

    assert result["workflow_status"] == "l1_completed"
    assert len(result["knowledge_gaps"]) == 1
    assert len(result["source_catalog"]) >= 2  # 两条不同来源
    assert result["gate_result"].passed is True
    # 验证搜索被实际调用
    assert "熵权法 综合评价" in search.call_log


def test_no_search_results_fails_g2():
    analysis, subproblems, fake_llm, _ = _make_setup()
    empty_search = FakeSearchProvider()  # 无命中
    subgraph = L1ResearchSubgraph(llm=fake_llm, search_provider=empty_search)
    result = subgraph.run(analysis, subproblems)
    # 无来源 → G2 失败
    assert result["gate_result"].passed is False
    assert "s_a_sources_count" in str(result["gate_result"].failed_checks)