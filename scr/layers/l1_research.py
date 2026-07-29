"""L1 研究子图。

对应 architecture.md §4 L1 与 plan.md Phase 4.11：
  gaps → queries → search → 评级 → 去重 → 证据 → 综合 + G2

当前为函数式 orchestrator（demo 简化版）：
  - 跳过综合步骤（synthesize），聚焦核心流程
  - 用 SearchProvider Protocol 注入搜索服务（测试用 FakeSearchProvider）
  - 来源评级使用确定性规则（URL 域名启发式）
  - 去重使用 URL 规范化
  - 调用 G2 校验覆盖率
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Protocol
from urllib.parse import urlparse

from ..agents.research_agent import ResearchAgent
from ..gates.g2_coverage import G2CoverageGate
from ..schemas.common import GateResult
from ..schemas.problem import ProblemAnalysis, SubProblem
from ..schemas.research import (
    EvidenceItem,
    KnowledgeGap,
    SearchRequest,
    SourceRecord,
)


# ---------------------------------------------------------------------------
# Search Provider 接口
# ---------------------------------------------------------------------------


class SearchHit(dict):
    """单条搜索命中（dict 子类，便于序列化）。"""

    def __init__(
        self,
        url: str,
        title: str,
        snippet: str,
        content: str = "",
    ) -> None:
        super().__init__(
            url=url,
            title=title,
            snippet=snippet,
            content=content or snippet,
        )


class SearchProvider(Protocol):
    """搜索服务接口。"""

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]: ...


# ---------------------------------------------------------------------------
# L1 子图
# ---------------------------------------------------------------------------


# 域名 → 来源级别（S/A/B/C/D）的简易启发式
_DOMAIN_LEVELS: dict[str, str] = {
    ".gov.cn": "S",
    ".gov": "S",
    "stats.gov.cn": "S",
    "moe.gov.cn": "S",
    "arxiv.org": "A",
    "ieee.org": "A",
    "acm.org": "A",
    "springer.com": "A",
    "sciencedirect.com": "A",
    "cnki.net": "A",
    "wanfangdata.com.cn": "A",
    "知乎": "D",
    "zhihu.com": "D",
    "csdn.net": "D",
    "baidu.com": "D",
    "blog.csdn.net": "D",
}


def _url_to_level(url: str) -> str:
    """根据 URL 域名推断来源分级。"""
    try:
        domain = urlparse(url).netloc.lower()
    except Exception:
        return "D"
    if not domain:
        return "D"
    # 检查是否包含特定关键词（按最长前缀优先）
    for key, level in sorted(_DOMAIN_LEVELS.items(), key=lambda x: -len(x[0])):
        if key in domain:
            return level
    # 默认 .edu → B
    if domain.endswith(".edu.cn") or domain.endswith(".edu"):
        return "B"
    return "C"


def _normalize_url(url: str) -> str:
    """URL 规范化（去掉尾部斜杠、fragment、统一 scheme）。"""
    parsed = urlparse(url.strip())
    return f"{parsed.scheme or 'http'}://{parsed.netloc}{parsed.path.rstrip('/')}"


class L1ResearchSubgraph:
    """L1 研究子图（demo 简化版）。

    流程：
      1. ResearchAgent.identify_gaps → list[KnowledgeGap]
      2. ResearchAgent.plan_queries → list[SearchRequest]
      3. 对每个查询调用 search_provider.search
      4. URL 规范化去重
      5. 域名启发式评级为 SourceRecord
      6. ResearchAgent.extract_evidence（mock LLM）
      7. G2 校验
    """

    def __init__(
        self,
        llm: Any = None,
        search_provider: SearchProvider | None = None,
        max_attempts: int = 3,
    ) -> None:
        self.research_agent = ResearchAgent(llm=llm)
        self.search_provider = search_provider
        self.gate = G2CoverageGate()
        self.max_attempts = max(1, max_attempts)

    def run(
        self,
        problem_analysis: ProblemAnalysis,
        subproblems: list[SubProblem],
    ) -> dict:
        """执行 L1 研究流程。

        Args:
            problem_analysis: L0 understand 产出。
            subproblems: L0 decompose 产出。

        Returns:
            State 部分更新 dict：
              - knowledge_gaps / search_plan / raw_search_results
              - source_catalog / evidence_items
              - gate_result / workflow_status
        """
        if self.search_provider is None:
            raise ValueError(
                "search_provider is required. "
                "Pass a SearchProvider implementation or a FakeSearchProvider for tests."
            )

        # 1-2. 识别缺口 + 规划查询
        gaps = self.research_agent.identify_gaps(problem_analysis, subproblems)
        queries = self.research_agent.plan_queries(gaps, problem_analysis)

        # 3. 执行搜索
        raw_results: list[dict] = []
        for q in queries:
            try:
                hits = self.search_provider.search(q.query)
                for hit in hits:
                    raw_results.append({
                        "query": q.query,
                        "purpose": q.purpose,
                        "url": hit["url"],
                        "title": hit["title"],
                        "snippet": hit["snippet"],
                        "content": hit.get("content", hit["snippet"]),
                    })
            except Exception:
                continue

        # 4. URL 规范化去重
        seen: dict[str, dict] = {}
        for r in raw_results:
            norm_url = _normalize_url(r["url"])
            if norm_url not in seen:
                seen[norm_url] = {**r, "url": norm_url}

        # 5. 评级为 SourceRecord
        source_catalog: list[SourceRecord] = []
        for idx, (url, item) in enumerate(seen.items()):
            source_id = "src_" + hashlib.md5(url.encode()).hexdigest()[:8]
            level = _url_to_level(url)
            # 简单的分数公式：S=0.95, A=0.85, B=0.7, C=0.5, D=0.3
            score_map = {"S": 0.95, "A": 0.85, "B": 0.7, "C": 0.5, "D": 0.3}
            source_catalog.append(
                SourceRecord(
                    source_id=source_id,
                    url=url,
                    title=item["title"],
                    level=level,  # type: ignore[arg-type]
                    score=score_map[level],
                )
            )

        # 6. 证据提取（对每个 source 调用 extract_evidence）
        evidence_items: list[EvidenceItem] = []
        for src in source_catalog:
            source_content = next(
                (r["content"] for r in seen.values() if r["url"] == src.url),
                src.title,
            )
            purpose = next(
                (r["purpose"] for r in seen.values() if r["url"] == src.url),
                "general research",
            )
            try:
                items = self.research_agent.extract_evidence(
                    source_content=source_content,
                    source_id=src.source_id,
                    source_url=src.url,
                    source_title=src.title,
                    source_level=src.level,
                    claim_focus=purpose,
                )
                evidence_items.extend(items)
            except Exception:
                continue

        # 7. G2 校验（带重试，模拟 search_round）
        gate_result: GateResult | None = None
        for attempt in range(1, self.max_attempts + 1):
            sa_count = sum(1 for s in source_catalog if s.level in ("S", "A"))
            independent_count = len({s.source_id for s in source_catalog})
            # 简化的高优覆盖率：evidence 数 ≥ high gap 数
            high_count = sum(1 for g in gaps if g.priority == "high")
            high_cov = min(1.0, len(evidence_items) / max(1, high_count))

            state = {
                "knowledge_gaps": gaps,
                "evidence_items": evidence_items,
                "source_catalog": source_catalog,
                "high_gap_coverage": high_cov,
                "_g2_budget_used": attempt - 1,
            }
            gate_result = self.gate.evaluate(state)
            if gate_result.passed:
                break

        # 兜底
        if gate_result is None:
            gate_result = self.gate.evaluate({
                "knowledge_gaps": gaps,
                "evidence_items": evidence_items,
                "source_catalog": source_catalog,
                "high_gap_coverage": 0.0,
            })

        if gate_result.passed:
            status = "l1_completed"
        elif gate_result.action == "human":
            status = "l1_human_review"
        else:
            status = "l1_in_progress"

        return {
            "knowledge_gaps": gaps,
            "search_plan": queries,
            "raw_search_results": list(seen.values()),
            "source_catalog": source_catalog,
            "evidence_items": evidence_items,
            "gate_result": gate_result,
            "workflow_status": status,
        }


# ---------------------------------------------------------------------------
# FakeSearchProvider — 测试用
# ---------------------------------------------------------------------------


class FakeSearchProvider:
    """测试用搜索 Provider：返回预设的命中列表。"""

    def __init__(self, hits: dict[str, list[SearchHit]] | None = None) -> None:
        # hits: query -> 命中列表
        self.hits = hits or {}
        self.call_log: list[str] = []

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        self.call_log.append(query)
        return self.hits.get(query, [])[:max_results]