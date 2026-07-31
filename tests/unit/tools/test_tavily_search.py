"""Tavily 搜索工具单元测试。

测试覆盖：
  1. 工具创建与可用性检查
  2. 搜索方法（mocked，不实际调用 API）
  3. 启发式方法提取
  4. 辅助函数（关键词提取、方法名提取、家族推断等）
  5. MethodExplorer 集成（外部候选合并与评分）
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from scr.tools.tavily_search import (
    TavilySearchTool,
    WebMethodCandidate,
    WebMethodCandidateList,
    create_search_tool,
    _extract_keywords,
    _extract_method_names,
    _infer_family,
    _infer_difficulty,
    _extract_pros,
    _extract_cons,
)


# ---------------------------------------------------------------------------
# 工具创建与可用性
# ---------------------------------------------------------------------------


class TestTavilySearchToolCreation:
    """测试搜索工具的创建和可用性检查。"""

    def test_create_with_api_key(self):
        """有 API key 时工具可用。"""
        tool = TavilySearchTool(api_key="test-key")
        assert tool.available is True

    def test_create_without_api_key(self):
        """无 API key 时工具不可用。"""
        tool = TavilySearchTool(api_key=None)
        assert tool.available is False

    def test_create_with_empty_api_key(self):
        """空 API key 时工具不可用。"""
        tool = TavilySearchTool(api_key="")
        assert tool.available is False

    def test_from_env_with_key(self, monkeypatch):
        """从环境变量创建工具（有 key）。"""
        monkeypatch.setenv("TAVILY_API_KEY", "env-test-key")
        tool = TavilySearchTool.from_env()
        assert tool.available is True
        assert tool.api_key == "env-test-key"

    def test_from_env_with_mixed_case_key(self, monkeypatch):
        """从环境变量创建工具（混合大小写 key 名）。

        注意：Windows 上环境变量名大小写不敏感，TAVILY_API_KEY 和
        Tavily_API_KEY 是同一个变量。此测试验证 from_env 能正确读取。
        """
        monkeypatch.setenv("Tavily_API_KEY", "mixed-case-key")
        tool = TavilySearchTool.from_env()
        assert tool.available is True
        assert tool.api_key == "mixed-case-key"

    def test_from_env_without_key(self, monkeypatch):
        """从环境变量创建工具（无 key）。"""
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.delenv("Tavily_API_KEY", raising=False)
        monkeypatch.delenv("tavily_api_key", raising=False)
        tool = TavilySearchTool.from_env()
        assert tool.available is False

    def test_create_search_tool_factory(self, monkeypatch):
        """工厂函数创建工具。"""
        monkeypatch.setenv("TAVILY_API_KEY", "factory-key")
        tool = create_search_tool()
        assert tool.available is True


# ---------------------------------------------------------------------------
# 搜索方法（mocked）
# ---------------------------------------------------------------------------


class TestTavilySearch:
    """测试搜索方法（mocked TavilyClient）。"""

    def test_search_unavailable_returns_empty(self):
        """无 API key 时搜索返回空结果。"""
        tool = TavilySearchTool(api_key=None)
        result = tool.search("test query")
        assert result["results"] == []
        assert "error" in result

    @patch("scr.tools.tavily_search.TavilySearchTool._get_client")
    def test_search_success(self, mock_get_client):
        """模拟搜索成功。"""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "query": "test",
            "answer": "AI answer",
            "results": [
                {"title": "Result 1", "url": "https://example.com/1", "content": "Content 1", "score": 0.95},
                {"title": "Result 2", "url": "https://example.com/2", "content": "Content 2", "score": 0.80},
            ],
            "response_time": 1.5,
        }
        mock_get_client.return_value = mock_client

        tool = TavilySearchTool(api_key="test-key")
        result = tool.search("test query")

        assert len(result["results"]) == 2
        assert result["answer"] == "AI answer"
        mock_client.search.assert_called_once()

    @patch("scr.tools.tavily_search.TavilySearchTool._get_client")
    def test_search_error_returns_empty(self, mock_get_client):
        """模拟搜索失败时优雅降级。"""
        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("Network error")
        mock_get_client.return_value = mock_client

        tool = TavilySearchTool(api_key="test-key")
        result = tool.search("test query")

        assert result["results"] == []
        assert "error" in result

    @patch("scr.tools.tavily_search.TavilySearchTool.search")
    def test_search_methods_merges_results(self, mock_search):
        """方法搜索合并中英文结果并去重。"""
        def side_effect(query, **kwargs):
            if "数学建模" in query:
                return {
                    "results": [
                        {"title": "中文结果1", "url": "https://zh.com/1", "content": "熵权法评价", "score": 0.9},
                        {"title": "中文结果2", "url": "https://zh.com/2", "content": "TOPSIS方法", "score": 0.85},
                    ],
                    "answer": "",
                }
            else:
                return {
                    "results": [
                        {"title": "English Result 1", "url": "https://en.com/1", "content": "AHP method", "score": 0.88},
                        {"title": "中文结果1", "url": "https://zh.com/1", "content": "重复URL", "score": 0.7},  # 重复 URL
                    ],
                    "answer": "",
                }

        mock_search.side_effect = side_effect

        tool = TavilySearchTool(api_key="test-key")
        results = tool.search_methods("evaluation", "多指标评价排序")

        # 去重后应有 3 条
        assert len(results) == 3
        # 按 score 降序
        assert results[0]["score"] >= results[1]["score"]
        # URL 去重
        urls = [r["url"] for r in results]
        assert len(urls) == len(set(urls))

    def test_search_methods_unavailable_returns_empty(self):
        """无 API key 时方法搜索返回空。"""
        tool = TavilySearchTool(api_key=None)
        results = tool.search_methods("evaluation", "test")
        assert results == []


# ---------------------------------------------------------------------------
# 启发式方法提取
# ---------------------------------------------------------------------------


class TestExtractMethodCandidates:
    """测试从搜索结果中启发式提取方法候选。"""

    def test_extract_from_chinese_results(self):
        """从中文搜索结果中提取方法。"""
        tool = TavilySearchTool(api_key="test-key")
        results = [
            {
                "title": "数学建模评价方法详解",
                "url": "https://example.com/1",
                "content": "熵权法是一种客观赋权法，基于信息熵计算指标权重。优点：完全客观，计算简单。缺点：对极端值敏感。",
                "score": 0.95,
            },
            {
                "title": "TOPSIS方法介绍",
                "url": "https://example.com/2",
                "content": "TOPSIS是逼近理想解排序法，属于多属性决策方法。",
                "score": 0.88,
            },
        ]
        candidates = tool.extract_method_candidates(results, "evaluation")

        assert len(candidates) > 0
        # 应该提取到方法名
        names = [c.name for c in candidates]
        assert any("熵权" in n for n in names)

    def test_extract_from_english_results(self):
        """从英文搜索结果中提取方法。"""
        tool = TavilySearchTool(api_key="test-key")
        results = [
            {
                "title": "Genetic Algorithm for Optimization",
                "url": "https://example.com/ga",
                "content": "Genetic algorithm is a heuristic optimization method inspired by natural selection.",
                "score": 0.90,
            },
        ]
        candidates = tool.extract_method_candidates(results, "optimization")

        assert len(candidates) > 0
        # 应该推断出家族
        families = [c.family for c in candidates]
        assert any("启发式" in f for f in families)

    def test_extract_with_empty_results(self):
        """空搜索结果返回空列表。"""
        tool = TavilySearchTool(api_key="test-key")
        candidates = tool.extract_method_candidates([], "evaluation")
        assert candidates == []

    def test_extract_dedup_methods(self):
        """重复方法名应去重。"""
        tool = TavilySearchTool(api_key="test-key")
        results = [
            {
                "title": "熵权法介绍",
                "url": "https://a.com",
                "content": "熵权法是一种客观赋权法",
                "score": 0.9,
            },
            {
                "title": "熵权法应用",
                "url": "https://b.com",
                "content": "熵权法是一种客观赋权法",
                "score": 0.85,
            },
        ]
        candidates = tool.extract_method_candidates(results, "evaluation")
        names = [c.name for c in candidates]
        # "熵权法" 应只出现一次
        assert names.count("熵权法") <= 1

    def test_relevance_score_capped(self):
        """相关性分数不超过 1.0。"""
        tool = TavilySearchTool(api_key="test-key")
        results = [
            {
                "title": "测试方法",
                "url": "https://a.com",
                "content": "测试法是一种方法",
                "score": 1.5,  # 超过 1.0
            },
        ]
        candidates = tool.extract_method_candidates(results, "evaluation")
        for c in candidates:
            assert c.relevance_score <= 1.0


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    """测试辅助函数。"""

    def test_extract_keywords_chinese(self):
        """中文关键词提取。"""
        text = "对多个指标进行综合评价和排序"
        keywords = _extract_keywords(text)
        assert len(keywords) > 0
        assert "指标" in keywords or "评价" in keywords

    def test_extract_keywords_empty(self):
        """空文本返回空字符串。"""
        assert _extract_keywords("") == ""

    def test_extract_keywords_filters_stopwords(self):
        """停用词被过滤。"""
        text = "的 了 在 是 和"
        keywords = _extract_keywords(text)
        assert keywords == ""

    def test_extract_method_names_chinese(self):
        """中文方法名提取。"""
        names = _extract_method_names("熵权法介绍", "熵权法是一种客观赋权法")
        assert "熵权法" in names

    def test_extract_method_names_english(self):
        """英文方法名提取。"""
        names = _extract_method_names("TOPSIS Method", "TOPSIS is a method for ranking")
        assert "TOPSIS" in names

    def test_extract_method_names_empty(self):
        """空内容返回空列表。"""
        assert _extract_method_names("", "") == []

    def test_infer_family_entropy(self):
        """熵权法 → 客观赋权法。"""
        assert _infer_family("熵权法", "熵权法") == "客观赋权法"

    def test_infer_family_topsis(self):
        """TOPSIS → 多属性决策。"""
        assert _infer_family("TOPSIS", "TOPSIS method") == "多属性决策"

    def test_infer_family_genetic_algorithm(self):
        """遗传算法 → 启发式算法。"""
        assert _infer_family("遗传算法", "genetic algorithm") == "启发式算法"

    def test_infer_family_unknown(self):
        """未知方法 → 其他方法。"""
        assert _infer_family("未知方法", "一些内容") == "其他方法"

    def test_infer_difficulty_low(self):
        """简单方法 → low。"""
        assert _infer_difficulty("熵权法", "客观赋权法") == "low"

    def test_infer_difficulty_high(self):
        """复杂方法 → high。"""
        assert _infer_difficulty("神经网络", "机器学习") == "high"

    def test_infer_difficulty_medium(self):
        """中等方法 → medium。"""
        assert _infer_difficulty("遗传算法", "启发式算法") == "medium"

    def test_extract_pros(self):
        """提取优点。"""
        content = "熵权法的优点：完全客观，计算简单，可复现性强。缺点：对极端值敏感。"
        pros = _extract_pros(content)
        assert len(pros) > 0
        assert any("客观" in p for p in pros)

    def test_extract_cons(self):
        """提取缺点。"""
        content = "熵权法的优点：完全客观。缺点：对极端值敏感，无法处理定性指标。"
        cons = _extract_cons(content)
        assert len(cons) > 0
        assert any("极端值" in c for c in cons)

    def test_extract_pros_empty(self):
        """无优点时返回空列表。"""
        assert _extract_pros("这是一段普通文本") == []


# ---------------------------------------------------------------------------
# WebMethodCandidate 数据模型
# ---------------------------------------------------------------------------


class TestWebMethodCandidate:
    """测试 WebMethodCandidate 数据模型。"""

    def test_create_candidate(self):
        """创建方法候选。"""
        candidate = WebMethodCandidate(
            name="熵权法",
            family="客观赋权法",
            description="基于信息熵的赋权方法",
            pros=["客观", "简单"],
            cons=["敏感"],
        )
        assert candidate.name == "熵权法"
        assert candidate.family == "客观赋权法"
        assert len(candidate.pros) == 2

    def test_default_values(self):
        """默认值正确。"""
        candidate = WebMethodCandidate(name="测试方法")
        assert candidate.family == ""
        assert candidate.implementation_difficulty == "medium"
        assert candidate.relevance_score == 0.5
        assert candidate.pros == []

    def test_relevance_score_validation(self):
        """相关性分数范围验证。"""
        with pytest.raises(Exception):
            WebMethodCandidate(name="test", relevance_score=1.5)
        with pytest.raises(Exception):
            WebMethodCandidate(name="test", relevance_score=-0.1)

    def test_candidate_list(self):
        """方法候选列表。"""
        lst = WebMethodCandidateList(candidates=[
            WebMethodCandidate(name="方法1"),
            WebMethodCandidate(name="方法2"),
        ])
        assert len(lst.candidates) == 2


# ---------------------------------------------------------------------------
# MethodExplorer 集成
# ---------------------------------------------------------------------------


class TestMethodExplorerIntegration:
    """测试 MethodExplorer 与搜索工具的集成。"""

    def test_explorer_without_search_tool(self):
        """无搜索工具时不报错。"""
        from scr.agents.method_explorer import MethodExplorer

        explorer = MethodExplorer(
            llm=None,
            search_tool=TavilySearchTool(api_key=None),
        )
        # 搜索工具不可用，_search_external_methods 应返回空列表
        result = explorer._search_external_methods(
            context=MagicMock(),
            interpretation=MagicMock(),
        )
        assert result == []

    def test_convert_web_candidates(self):
        """WebMethodCandidate 转换为目录格式。"""
        from scr.agents.method_explorer import MethodExplorer

        web_candidates = [
            WebMethodCandidate(
                name="熵权法",
                family="客观赋权法",
                description="基于信息熵的赋权方法",
                pros=["客观"],
                cons=["敏感"],
                implementation_difficulty="low",
                source_url="https://example.com",
                relevance_score=0.9,
            ),
        ]
        catalog = MethodExplorer._convert_web_candidates(web_candidates)

        assert len(catalog) == 1
        assert catalog[0]["name"] == "熵权法"
        assert catalog[0]["source"] == "web_search"
        assert catalog[0]["data_requirements"]["min_samples"] == 0
        assert catalog[0]["relevance_score"] == 0.9

    def test_external_candidate_scoring_adjustment(self):
        """外部方法候选的评分微调。"""
        from scr.agents.method_explorer import _heuristic_score
        from scr.schemas.question import ProblemInterpretation

        interpretation = ProblemInterpretation(
            question_id="test",
            math_task="evaluation",
            math_task_description="多指标评价排序",
            decision_variables=[],
            objective_function="",
            constraints=[],
            evaluation_metrics=[],
            result_form="评价排名表",
            available_data=[],
            missing_data=[],
            necessary_assumptions=[],
            acceptable_simplifications=[],
            relation_to_previous="independent",
            relation_description="",
        )

        data_info = {
            "sample_size": 100,
            "feature_count": 5,
            "has_time_column": False,
            "data_quality_summary": "",
        }

        # 内置方法
        catalog_method = {
            "name": "熵权法",
            "family": "客观赋权法",
            "implementation_difficulty": "low",
            "elimination_conditions": [],
            "data_requirements": {"min_samples": 3, "min_features": 2, "needs_time": False},
        }
        catalog_score = _heuristic_score(catalog_method, data_info, interpretation)

        # 外部方法（相同属性但标记为 web_search）
        web_method = dict(catalog_method)
        web_method["source"] = "web_search"
        web_method["relevance_score"] = 0.5
        web_score = _heuristic_score(web_method, data_info, interpretation)

        # 外部方法应该因相关性微调而略低
        assert web_score < catalog_score

        # 但高相关性的外部方法应该接近内置方法
        web_method_high = dict(catalog_method)
        web_method_high["source"] = "web_search"
        web_method_high["relevance_score"] = 1.0
        web_score_high = _heuristic_score(web_method_high, data_info, interpretation)
        assert web_score_high == catalog_score  # relevance=1.0 时无惩罚
