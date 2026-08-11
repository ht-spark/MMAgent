"""
理解题目并建立可执行的子问题计划。

从题面提取研究对象、约束、目标和预期输出，将任务拆成带依赖关系的子问题，再判断任务类型。
该智能体只做语义分析，不产生数值结论。
"""
from __future__ import annotations

import json

from ..schemas.problem import (
    DataInventory,
    ProblemAnalysis,
    ProblemClassification,
    SubProblem,
    SubProblemList,
)
from .base import BaseAgent
from .decomposition_fallback import (
    fallback_subproblems_from_analysis,
    sanitize_subproblems,
    short_error,
)

__all__ = ["ProblemAnalyst"]


class ProblemAnalyst(BaseAgent):
    """L0 任务理解 Agent。

    三个核心方法可独立调用，也可通过 ``analyze`` 串联执行。

    Example::

        analyst = ProblemAnalyst(llm=my_llm)
        analysis = analyst.understand(problem_text, data_inventory)
        subproblems = analyst.decompose(analysis)
        classification = analyst.classify(analysis, subproblems)
    """

    # ------------------------------------------------------------------
    # understand — 理解任务
    # ------------------------------------------------------------------

    def understand(
        self,
        problem_text: str,
        data_inventory: DataInventory | None = None,
    ) -> ProblemAnalysis:
        """理解任务背景，提取关键信息。

        对应 architecture.md §4 L0 understand：
          提取研究对象、背景、显式小问、约束、预期输出、关键词。
          禁止推荐模型或开始求解。

        Args:
            problem_text: 任务全文。
            data_inventory: 可选的附件数据画像，为 LLM 提供数据上下文。

        Returns:
            ProblemAnalysis 对象。
        """
        template = self._load_prompt("problem_analysis")
        inv_str = (
            data_inventory.model_dump_json(indent=2)
            if data_inventory
            else "（无附件数据）"
        )
        prompt = self._render_prompt(
            template,
            problem_text=problem_text,
            data_inventory=inv_str,
        )
        return self._call_structured(ProblemAnalysis, prompt)

    # ------------------------------------------------------------------
    # decompose — 拆解子问题
    # ------------------------------------------------------------------

    def decompose(self, problem_analysis: ProblemAnalysis) -> list[SubProblem]:
        """将任务拆解为子问题 DAG。

        对应 architecture.md §4 L0 decompose：
          每个子问题含 id、task、input_requirements、expected_outputs、
          dependencies、parallelizable。

        Args:
            problem_analysis: understand 步骤的产出。

        Returns:
            子问题列表，依赖关系构成 DAG。
        """
        template = self._load_prompt("task_decomposition")
        pa_str = problem_analysis.model_dump_json(indent=2)
        prompt = self._render_prompt(template, problem_analysis=pa_str)
        errors: list[Exception] = []

        try:
            result = self._call_structured(SubProblemList, prompt)
            return sanitize_subproblems(result.subproblems, problem_analysis)
        except Exception as error:
            errors.append(error)

        try:
            result = self._call_structured_json_fallback(SubProblemList, prompt)
            return sanitize_subproblems(result.subproblems, problem_analysis)
        except Exception as error:
            errors.append(error)

        fallback = fallback_subproblems_from_analysis(problem_analysis)
        if fallback:
            print(
                "[problem_analyst] decompose 结构化输出不可用，已使用通用兜底分解: "
                f"{short_error(errors[-1])}"
            )
            return fallback

        details = "; ".join(short_error(error) for error in errors)
        raise ValueError(f"decompose failed and fallback produced no subproblems: {details}")

    # ------------------------------------------------------------------
    # classify — 题型分类
    # ------------------------------------------------------------------

    def classify(
        self,
        problem_analysis: ProblemAnalysis,
        subproblems: list[SubProblem],
    ) -> ProblemClassification:
        """判定题型（主类型 + 次类型）。

        对应 architecture.md §4 L0 classify：
          判定主类型（evaluation / prediction / optimization / classification /
          simulation / mechanism / composite），允许一主多次。

        Args:
            problem_analysis: understand 步骤的产出。
            subproblems: decompose 步骤的产出。

        Returns:
            ProblemClassification 对象。
        """
        template = self._load_prompt("problem_classification")
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
        )
        return self._call_structured(ProblemClassification, prompt)

    # ------------------------------------------------------------------
    # analyze — 串联三步
    # ------------------------------------------------------------------

    def analyze(
        self,
        problem_text: str,
        data_inventory: DataInventory | None = None,
    ) -> tuple[ProblemAnalysis, list[SubProblem], ProblemClassification]:
        """串联执行 understand → decompose → classify。

        Args:
            problem_text: 任务全文。
            data_inventory: 可选的附件数据画像。

        Returns:
            (ProblemAnalysis, list[SubProblem], ProblemClassification) 三元组。
        """
        analysis = self.understand(problem_text, data_inventory)
        subproblems = self.decompose(analysis)
        classification = self.classify(analysis, subproblems)
        return analysis, subproblems, classification
