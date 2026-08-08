"""规划研究检索并整理可引用证据。

识别领域知识、参数、验证标准和实现条件中的缺口，生成中英文查询，并将
检索内容整理为与具体主张对应的结构化证据；实际网络访问由工具层执行。
"""
from __future__ import annotations

from ..schemas.problem import ProblemAnalysis, SubProblem
from ..schemas.research import (
    EvidenceItem,
    EvidenceItemList,
    KnowledgeGap,
    KnowledgeGapList,
    SearchRequest,
    SearchRequestList,
)
from .base import BaseAgent

__all__ = ["ResearchAgent"]


class ResearchAgent(BaseAgent):
    """L1 研究 Agent。

    三个核心方法可独立调用，也可通过 ``run_research`` 串联前两步。

    Example::

        agent = ResearchAgent(llm=my_llm)
        gaps = agent.identify_gaps(analysis, subproblems)
        queries = agent.plan_queries(gaps, analysis)
        # 执行搜索后（外部），对每条结果调用：
        evidence = agent.extract_evidence(
            source_content=..., source_id=..., source_url=..., ...
        )
    """

    # ------------------------------------------------------------------
    # identify_gaps — 识别知识缺口
    # ------------------------------------------------------------------

    def identify_gaps(
        self,
        problem_analysis: ProblemAnalysis,
        subproblems: list[SubProblem],
    ) -> list[KnowledgeGap]:
        """识别任务的知识缺口。

        对应 architecture.md §4 L1 gaps 节点：
          识别 domain_definition / mechanism / standard / data_source /
          model_precedent / parameter_range / evaluation_metric /
          validation_method / constraint / implementation。

        Args:
            problem_analysis: L0 understand 产出。
            subproblems: L0 decompose 产出。

        Returns:
            知识缺口列表（通常 3-8 个）。
        """
        template = self._load_prompt("knowledge_gap")
        pa_str = problem_analysis.model_dump_json(indent=2)
        sp_str = self._dump_subproblems(subproblems)
        prompt = self._render_prompt(
            template,
            problem_analysis=pa_str,
            subproblems=sp_str,
        )
        result = self._call_structured(KnowledgeGapList, prompt)
        return result.gaps

    # ------------------------------------------------------------------
    # plan_queries — 规划搜索查询
    # ------------------------------------------------------------------

    def plan_queries(
        self,
        gaps: list[KnowledgeGap],
        problem_analysis: ProblemAnalysis,
    ) -> list[SearchRequest]:
        """为知识缺口生成中英文搜索查询组。

        对应 architecture.md §4 L1 queries 节点：
          每个高优先缺口生成中英文查询组；
          带 purpose 与 source preference。

        Args:
            gaps: identify_gaps 产出。
            problem_analysis: 用于上下文（提供研究主题与背景）。

        Returns:
            搜索请求列表。
        """
        template = self._load_prompt("query_planner")
        gaps_str = self._dump_gaps(gaps)
        prompt = self._render_prompt(
            template,
            knowledge_gaps=gaps_str,
            research_subject=problem_analysis.research_subject,
            background=problem_analysis.background,
        )
        result = self._call_structured(SearchRequestList, prompt)
        return result.queries

    # ------------------------------------------------------------------
    # extract_evidence — 从来源中提取证据
    # ------------------------------------------------------------------

    def extract_evidence(
        self,
        source_content: str,
        source_id: str,
        source_url: str | None,
        source_title: str,
        source_level: str,
        claim_focus: str,
    ) -> list[EvidenceItem]:
        """从单个来源中提取证据项。

        对应 architecture.md §4 L1 extract_evidence 节点：
          一个证据项支撑一个 claim，必记来源与局限性，区分事实与推断。

        Args:
            source_content: 来源正文（已抓取的文本）。
            source_id: 来源 ID。
            source_url: 来源 URL（可空）。
            source_title: 来源标题。
            source_level: 来源分级（S/A/B/C/D）。
            claim_focus: 要从来源中提取的 claim 方向（搜索查询的 purpose）。

        Returns:
            证据项列表（2-5 条）。
        """
        template = self._load_prompt("evidence_extraction")
        prompt = self._render_prompt(
            template,
            source_content=source_content,
            source_id=source_id,
            source_url=source_url or "（无）",
            source_title=source_title,
            source_level=source_level,
            claim_focus=claim_focus,
        )
        result = self._call_structured(EvidenceItemList, prompt)
        return result.items

    # ------------------------------------------------------------------
    # run_research — 串联前两步
    # ------------------------------------------------------------------

    def run_research(
        self,
        problem_analysis: ProblemAnalysis,
        subproblems: list[SubProblem],
    ) -> tuple[list[KnowledgeGap], list[SearchRequest]]:
        """串联 identify_gaps → plan_queries。

        Args:
            problem_analysis: L0 understand 产出。
            subproblems: L0 decompose 产出。

        Returns:
            (gaps, queries) 二元组。
        """
        gaps = self.identify_gaps(problem_analysis, subproblems)
        queries = self.plan_queries(gaps, problem_analysis)
        return gaps, queries

    # ------------------------------------------------------------------
    # 内部 helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _dump_subproblems(subproblems: list[SubProblem]) -> str:
        """格式化子问题列表供 prompt 使用。"""
        import json

        return json.dumps(
            [sp.model_dump() for sp in subproblems],
            ensure_ascii=False,
            indent=2,
        )

    @staticmethod
    def _dump_gaps(gaps: list[KnowledgeGap]) -> str:
        """格式化缺口列表供 prompt 使用。"""
        import json

        return json.dumps(
            [g.model_dump() for g in gaps],
            ensure_ascii=False,
            indent=2,
        )
