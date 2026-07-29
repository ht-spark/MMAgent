"""ModelingAgent — L2 模型决策 Agent。

对应 architecture.md §4 L2 与 plan.md Phase 5.2：
  - generate_candidates：为每个子问题生成 2-4 个候选模型
  - score_candidates：LLM 给单项分（0-1），代码用 SCORE_WEIGHTS 加权算总分
  - criticize：检查缺口覆盖、权威来源、候选差异、是否遗漏简单模型等

评分公式（architecture.md §4 L2）：
  total = 0.25*problem_fit + 0.20*data_fit + 0.15*assumption_validity
        + 0.15*validation_feasibility + 0.10*interpretability
        + 0.10*implementation_feasibility + 0.05*innovation
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from ..schemas.model import (
    ModelCandidate,
    ModelCandidateList,
    ModelCriticReport,
    ModelScore,
    compute_total_score,
)
from ..schemas.problem import ProblemAnalysis, SubProblem
from ..schemas.research import EvidenceItem
from .base import BaseAgent

__all__ = ["ModelingAgent"]


# LLM 返回的原始评分（不含 total_score）
class _ScoreInput(BaseModel):
    """LLM 返回的单项评分（不含 total_score，由代码计算）。"""

    candidate_id: str
    problem_fit: float
    data_fit: float
    assumption_validity: float
    validation_feasibility: float
    interpretability: float
    implementation_feasibility: float
    innovation: float
    reasoning: str = ""


class _ScoreInputList(BaseModel):
    """_ScoreInput 列表包装。"""

    scores: list[_ScoreInput]


class ModelingAgent(BaseAgent):
    """L2 模型决策 Agent。

    三个核心方法：
      - generate_candidates：生成候选模型
      - score_candidates：评分（LLM 给单项 → 代码算总分）
      - criticize：Critic 审查
    """

    # ------------------------------------------------------------------
    # generate_candidates — 候选生成
    # ------------------------------------------------------------------

    def generate_candidates(
        self,
        problem_analysis: ProblemAnalysis,
        subproblems: list[SubProblem],
        data_inventory: Any = None,
        evidence: list[EvidenceItem] | None = None,
    ) -> list[ModelCandidate]:
        """为每个子问题生成 2-4 个候选模型。

        对应 architecture.md §4 L2 generate_candidates。

        Args:
            problem_analysis: L0 understand 产出。
            subproblems: L0 decompose 产出。
            data_inventory: 可选的数据画像。
            evidence: 可用证据列表。

        Returns:
            候选模型列表（按子问题分组）。
        """
        template = self._load_prompt("model_candidate")
        inv_str = (
            data_inventory.model_dump_json(indent=2)
            if data_inventory is not None
            else "（无数据画像）"
        )
        ev_summary = self._summarize_evidence(evidence or [])

        pa_str = problem_analysis.model_dump_json(indent=2)
        sp_str = json.dumps(
            [sp.model_dump() for sp in subproblems],
            ensure_ascii=False,
            indent=2,
        )

        prompt = self._render_prompt(
            template,
            problem_analysis=pa_str,
            subproblems=sp_str,
            data_inventory=inv_str,
            evidence_summary=ev_summary,
        )
        result = self._call_structured(ModelCandidateList, prompt)
        return result.candidates

    # ------------------------------------------------------------------
    # score_candidates — 评分
    # ------------------------------------------------------------------

    def score_candidates(
        self,
        candidates: list[ModelCandidate],
        problem_analysis: ProblemAnalysis,
        subproblems: list[SubProblem],
        data_inventory: Any = None,
    ) -> list[ModelScore]:
        """为候选模型评分。

        LLM 输出 7 个单项分（0–1），代码用 ``compute_total_score``
        按 SCORE_WEIGHTS 加权计算总分。

        对应 architecture.md §4 L2 score（"LLM 只出单项分与理由，
        Pydantic 约束分数 0-1，总分由代码计算"）。

        Args:
            candidates: 候选模型列表。
            problem_analysis: 用于上下文。
            subproblems: 用于上下文。
            data_inventory: 可选的数据画像。

        Returns:
            ModelScore 列表（含代码计算的 total_score）。
        """
        template = self._load_prompt("model_scoring")
        candidates_str = json.dumps(
            [c.model_dump() for c in candidates],
            ensure_ascii=False,
            indent=2,
        )
        inv_str = (
            data_inventory.model_dump_json(indent=2)
            if data_inventory is not None
            else "（无数据画像）"
        )
        pa_str = problem_analysis.model_dump_json(indent=2)
        sp_str = json.dumps(
            [sp.model_dump() for sp in subproblems],
            ensure_ascii=False,
            indent=2,
        )

        prompt = self._render_prompt(
            template,
            candidates=candidates_str,
            problem_analysis=pa_str,
            subproblems=sp_str,
            data_inventory=inv_str,
        )
        result = self._call_structured(_ScoreInputList, prompt)

        # 用代码计算 total_score
        scores: list[ModelScore] = []
        for raw in result.scores:
            total = compute_total_score(
                raw.problem_fit,
                raw.data_fit,
                raw.assumption_validity,
                raw.validation_feasibility,
                raw.interpretability,
                raw.implementation_feasibility,
                raw.innovation,
            )
            scores.append(
                ModelScore(
                    candidate_id=raw.candidate_id,
                    problem_fit=raw.problem_fit,
                    data_fit=raw.data_fit,
                    assumption_validity=raw.assumption_validity,
                    validation_feasibility=raw.validation_feasibility,
                    interpretability=raw.interpretability,
                    implementation_feasibility=raw.implementation_feasibility,
                    innovation=raw.innovation,
                    total_score=total,
                    reasoning=raw.reasoning,
                )
            )
        return scores

    # ------------------------------------------------------------------
    # criticize — Critic 审查
    # ------------------------------------------------------------------

    def criticize(
        self,
        scored_candidates: list[ModelScore],
        problem_analysis: ProblemAnalysis,
        evidence: list[EvidenceItem] | None = None,
    ) -> ModelCriticReport:
        """对候选与评分进行 Critic 审查。

        对应 architecture.md §4 L2 criticize。
        """
        template = self._load_prompt("model_critic")
        scored_str = json.dumps(
            [s.model_dump() for s in scored_candidates],
            ensure_ascii=False,
            indent=2,
        )
        ev_summary = self._summarize_evidence(evidence or [])
        pa_str = problem_analysis.model_dump_json(indent=2)

        prompt = self._render_prompt(
            template,
            scored_candidates=scored_str,
            problem_analysis=pa_str,
            evidence_summary=ev_summary,
        )
        return self._call_structured(ModelCriticReport, prompt)

    # ------------------------------------------------------------------
    # run_modeling — 串联三步
    # ------------------------------------------------------------------

    def run_modeling(
        self,
        problem_analysis: ProblemAnalysis,
        subproblems: list[SubProblem],
        data_inventory: Any = None,
        evidence: list[EvidenceItem] | None = None,
    ) -> tuple[list[ModelCandidate], list[ModelScore], ModelCriticReport]:
        """串联 generate_candidates → score_candidates → criticize。

        Returns:
            (candidates, scores, critic_report) 三元组。
        """
        candidates = self.generate_candidates(
            problem_analysis, subproblems, data_inventory, evidence
        )
        scores = self.score_candidates(
            candidates, problem_analysis, subproblems, data_inventory
        )
        critic = self.criticize(scores, problem_analysis, evidence)
        return candidates, scores, critic

    # ------------------------------------------------------------------
    # 内部 helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize_evidence(evidence: list[EvidenceItem]) -> str:
        """生成证据摘要文本供 prompt 使用。"""
        if not evidence:
            return "（暂无证据）"
        lines = []
        for e in evidence:
            src = f"[{e.source_id}]"
            lines.append(f"- {src} {e.claim} (confidence={e.confidence})")
        return "\n".join(lines)