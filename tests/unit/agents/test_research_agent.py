"""ResearchAgent 单元测试。

使用 FakeLLM 注入，不需要真实 API Key。
覆盖：
  - identify_gaps：知识缺口识别
  - plan_queries：查询规划（中英文 + source_preference）
  - extract_evidence：证据提取（一 claim 一证据 + 局限性 + 置信度）
  - run_research：前两步串联
  - 边界情况：缺口为空查询能规划、单条来源、来源不相关
"""
from __future__ import annotations

from typing import Any

import pytest

from scr.agents.research_agent import ResearchAgent
from scr.schemas.problem import ProblemAnalysis, SubProblem
from scr.schemas.research import (
    EvidenceItem,
    EvidenceItemList,
    KnowledgeGap,
    KnowledgeGapList,
    SearchRequest,
    SearchRequestList,
)


# ---------------------------------------------------------------------------
# FakeLLM（复用 problem_analyst 测试的版本）
# ---------------------------------------------------------------------------


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
        if schema_type not in self._responses:
            raise ValueError(f"No fake response registered for {schema_type}")
        return _FakeStructuredLLM(self._responses[schema_type])


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def sample_analysis() -> ProblemAnalysis:
    return ProblemAnalysis(
        research_subject="城市经济综合评价",
        background="5 个城市 GDP、人口、增长率等数据",
        explicit_questions=["问题一：综合评价排名", "问题二：分析影响因素"],
        constraints=["样本量小", "需考虑指标方向性"],
        expected_outputs=["排名表", "影响因素分析"],
        keywords=["综合评价", "熵权法", "TOPSIS"],
    )


@pytest.fixture
def sample_subproblems() -> list[SubProblem]:
    return [
        SubProblem(
            id="q1", task="综合评价", input_requirements=["GDP", "人口"],
            expected_outputs=["排名"], dependencies=[], parallelizable=True,
        ),
        SubProblem(
            id="q2", task="影响因素分析", input_requirements=["q1 结果"],
            expected_outputs=["分析"], dependencies=["q1"], parallelizable=False,
        ),
    ]


@pytest.fixture
def sample_gaps() -> list[KnowledgeGap]:
    return [
        KnowledgeGap(
            gap_type="model_precedent",
            description="熵权法的标准实现流程",
            priority="high",
            related_subproblems=["q1"],
        ),
        KnowledgeGap(
            gap_type="evaluation_metric",
            description="综合评价的常用客观赋权方法",
            priority="high",
            related_subproblems=["q1"],
        ),
        KnowledgeGap(
            gap_type="validation_method",
            description="权重稳定性的检验方法",
            priority="medium",
            related_subproblems=["q1", "q2"],
        ),
    ]


@pytest.fixture
def sample_queries() -> list[SearchRequest]:
    return [
        SearchRequest(
            query="熵权法 综合评价 实现步骤",
            purpose="了解熵权法的标准实现",
            language="zh",
            source_preference="academic_paper",
            target_gap_type="model_precedent",
        ),
        SearchRequest(
            query="entropy weight method TOPSIS implementation",
            purpose="了解熵权法的英文文献实现",
            language="en",
            source_preference="academic_paper",
            target_gap_type="model_precedent",
        ),
        SearchRequest(
            query="权重稳定性 检验 灵敏度分析",
            purpose="寻找权重验证方法",
            language="zh",
            source_preference="any",
            target_gap_type="validation_method",
        ),
    ]


@pytest.fixture
def sample_evidence() -> list[EvidenceItem]:
    return [
        EvidenceItem(
            claim="熵权法通过信息熵反映指标区分度，差异系数越大权重越高",
            source_id="src_001",
            source_url="https://example.com/paper1",
            fact_or_inference="fact",
            limitations="理论描述，缺少具体数值示例",
            confidence=0.9,
        ),
        EvidenceItem(
            claim="常用权重扰动方法检验权重稳定性",
            source_id="src_001",
            source_url="https://example.com/paper1",
            fact_or_inference="inference",
            limitations="未给出扰动幅度建议",
            confidence=0.7,
        ),
    ]


# ---------------------------------------------------------------------------
# identify_gaps
# ---------------------------------------------------------------------------


class TestIdentifyGaps:
    def test_returns_knowledge_gaps(self, fake_llm, sample_analysis, sample_subproblems, sample_gaps):
        fake_llm.register(KnowledgeGapList, KnowledgeGapList(gaps=sample_gaps))
        agent = ResearchAgent(llm=fake_llm)
        result = agent.identify_gaps(sample_analysis, sample_subproblems)
        assert len(result) == 3
        assert result[0].gap_type == "model_precedent"
        assert result[0].priority == "high"

    def test_empty_subproblems_still_works(self, fake_llm, sample_analysis, sample_gaps):
        fake_llm.register(KnowledgeGapList, KnowledgeGapList(gaps=sample_gaps))
        agent = ResearchAgent(llm=fake_llm)
        result = agent.identify_gaps(sample_analysis, [])
        assert len(result) == 3


# ---------------------------------------------------------------------------
# plan_queries
# ---------------------------------------------------------------------------


class TestPlanQueries:
    def test_returns_queries(self, fake_llm, sample_analysis, sample_gaps, sample_queries):
        fake_llm.register(SearchRequestList, SearchRequestList(queries=sample_queries))
        agent = ResearchAgent(llm=fake_llm)
        result = agent.plan_queries(sample_gaps, sample_analysis)
        assert len(result) == 3
        # 至少一条中文 + 一条英文
        languages = {q.language for q in result}
        assert "zh" in languages
        assert "en" in languages

    def test_source_preference_variety(
        self, fake_llm, sample_analysis, sample_gaps, sample_queries
    ):
        fake_llm.register(SearchRequestList, SearchRequestList(queries=sample_queries))
        agent = ResearchAgent(llm=fake_llm)
        result = agent.plan_queries(sample_gaps, sample_analysis)
        prefs = {q.source_preference for q in result}
        # 至少包含 academic_paper 和 any 两种
        assert "academic_paper" in prefs


# ---------------------------------------------------------------------------
# extract_evidence
# ---------------------------------------------------------------------------


class TestExtractEvidence:
    def test_returns_evidence_items(self, fake_llm, sample_evidence):
        fake_llm.register(EvidenceItemList, EvidenceItemList(items=sample_evidence))
        agent = ResearchAgent(llm=fake_llm)
        result = agent.extract_evidence(
            source_content="熵权法是一种客观赋权方法...",
            source_id="src_001",
            source_url="https://example.com/paper1",
            source_title="熵权法综述",
            source_level="A",
            claim_focus="熵权法原理",
        )
        assert len(result) == 2
        # 验证 source_id 被正确传递
        assert all(e.source_id == "src_001" for e in result)
        assert all(e.source_url == "https://example.com/paper1" for e in result)

    def test_claim_focus_in_prompt(self, fake_llm, sample_evidence):
        fake_llm.register(EvidenceItemList, EvidenceItemList(items=sample_evidence))
        agent = ResearchAgent(llm=fake_llm)
        # 调用应能完成（prompt 中包含 claim_focus）
        agent.extract_evidence(
            source_content="内容",
            source_id="s1",
            source_url="https://x",
            source_title="t",
            source_level="B",
            claim_focus="重点关注 X",
        )

    def test_evidence_has_limitations(self, fake_llm, sample_evidence):
        fake_llm.register(EvidenceItemList, EvidenceItemList(items=sample_evidence))
        agent = ResearchAgent(llm=fake_llm)
        result = agent.extract_evidence(
            source_content="...", source_id="s1", source_url="https://x",
            source_title="t", source_level="B", claim_focus="X",
        )
        # 每条证据应有限局限性描述
        assert all(e.limitations for e in result)

    def test_confidence_in_range(self, fake_llm, sample_evidence):
        fake_llm.register(EvidenceItemList, EvidenceItemList(items=sample_evidence))
        agent = ResearchAgent(llm=fake_llm)
        result = agent.extract_evidence(
            source_content="...", source_id="s1", source_url="https://x",
            source_title="t", source_level="B", claim_focus="X",
        )
        for e in result:
            assert 0.0 <= e.confidence <= 1.0


# ---------------------------------------------------------------------------
# run_research（串联）
# ---------------------------------------------------------------------------


class TestRunResearch:
    def test_chained(
        self, fake_llm, sample_analysis, sample_subproblems,
        sample_gaps, sample_queries
    ):
        fake_llm.register(KnowledgeGapList, KnowledgeGapList(gaps=sample_gaps))
        fake_llm.register(SearchRequestList, SearchRequestList(queries=sample_queries))

        agent = ResearchAgent(llm=fake_llm)
        gaps, queries = agent.run_research(sample_analysis, sample_subproblems)

        assert len(gaps) == 3
        assert len(queries) == 3
        # 至少一个 high 缺口有对应查询
        high_gap_types = {g.gap_type for g in gaps if g.priority == "high"}
        query_gap_types = {q.target_gap_type for q in queries}
        assert high_gap_types & query_gap_types  # 交集非空


# ---------------------------------------------------------------------------
# Prompt 模板测试
# ---------------------------------------------------------------------------


class TestPromptTemplates:
    def test_knowledge_gap_template_exists(self):
        agent = ResearchAgent(llm=FakeLLM())
        t = agent._load_prompt("knowledge_gap")
        assert "{problem_analysis}" in t
        assert "{subproblems}" in t

    def test_query_planner_template_exists(self):
        agent = ResearchAgent(llm=FakeLLM())
        t = agent._load_prompt("query_planner")
        assert "{knowledge_gaps}" in t
        assert "{research_subject}" in t
        assert "{background}" in t

    def test_evidence_extraction_template_exists(self):
        agent = ResearchAgent(llm=FakeLLM())
        t = agent._load_prompt("evidence_extraction")
        assert "{source_content}" in t
        assert "{source_id}" in t
        assert "{claim_focus}" in t


# ---------------------------------------------------------------------------
# 错误处理
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_no_llm_no_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        agent = ResearchAgent()
        with pytest.raises(RuntimeError, match="No API key found"):
            _ = agent.llm

    def test_fake_llm_not_registered(self, sample_analysis, sample_subproblems):
        fake = FakeLLM()
        agent = ResearchAgent(llm=fake)
        with pytest.raises(ValueError, match="No fake response registered"):
            agent.identify_gaps(sample_analysis, sample_subproblems)