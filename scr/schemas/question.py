"""小问求解相关 Schema。

对应 architecture.md §3.3 QuestionResult, §5.1 CurrentQuestionContext, §5.2 ProblemInterpretation。
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, field_validator


class ProblemInterpretation(BaseModel):
    """问题澄清（architecture.md §5.2）。
    
    当前小问的问题理解输出，必须能使审查器判断"所建模型是否真正回答了该问"。
    """
    question_id: str
    math_task: Literal[
        "evaluation", "prediction", "optimization",
        "stochastic_optimization",
        "classification", "clustering", "simulation",
        "mechanism", "composite",
    ]
    math_task_description: str = ""
    decision_variables: list[str] = Field(default_factory=list)
    objective_function: str = ""
    constraints: list[str] = Field(default_factory=list)
    evaluation_metrics: list[str] = Field(default_factory=list)
    result_form: str = ""  # 排名表/预测值/最优方案等
    available_data: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    necessary_assumptions: list[str] = Field(default_factory=list)
    acceptable_simplifications: list[str] = Field(default_factory=list)
    relation_to_previous: Literal[
        "inherit", "compare", "improve", "independent", "refute",
    ] = "independent"
    relation_description: str = ""


class CurrentQuestionContext(BaseModel):
    """当前小问上下文包（architecture.md §5.1）。
    
    装配器注入当前题、相关数据、全局约束和前问 reusable_summary。
    """
    question_id: str
    question_text: str
    objective: str = ""
    global_background: str = ""
    global_constraints: list[str] = Field(default_factory=list)
    required_data: list[str] = Field(default_factory=list)
    data_quality_summary: str = ""
    inherited_summaries: list[dict] = Field(default_factory=list)
    budget_info: dict = Field(default_factory=dict)


class ReusableSummary(BaseModel):
    """可复用摘要（QuestionResult.reusable_summary 的结构化版本）。
    
    只保存后题确实可能需要的信息：已验证的结论、可复用数据集、
    模型接口、关键参数、限制和改进方向。它不是完整的思考记录。
    """
    question_id: str
    verified_conclusions: list[str] = Field(default_factory=list)
    reusable_datasets: list[str] = Field(default_factory=list)
    model_interface: str = ""  # 模型名称和关键接口
    key_parameters: dict[str, float | str] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    improvement_directions: list[str] = Field(default_factory=list)


class QuestionResult(BaseModel):
    """小问结果包（architecture.md §3.3）。
    
    每个小问完成后写入结果库，并视为后续问题和论文的唯一可信输入。
    """
    question_id: str
    status: Literal["pending", "solving", "validating", "validated", "blocked"] = "pending"
    problem_interpretation: ProblemInterpretation | None = None
    inherited_context: dict = Field(default_factory=dict)
    method_candidates: list[dict] = Field(default_factory=list)
    decision_record: dict = Field(default_factory=dict)
    assumptions: list[dict] = Field(default_factory=list)
    formulation: dict = Field(default_factory=dict)
    data_preparation: dict = Field(default_factory=dict)
    computation: dict = Field(default_factory=dict)
    validation: dict = Field(default_factory=dict)
    findings: dict = Field(default_factory=dict)
    figures: list[str] = Field(default_factory=list)
    tables: list[str] = Field(default_factory=list)
    reusable_summary: ReusableSummary | None = None
    limitations: list[str] = Field(default_factory=list)
    error_message: str = ""
    retry_count: int = Field(ge=0, default=0)

    # ------------------------------------------------------------------
    # 边界兜底校验：防止上游（尤其 LLM 输出）类型不匹配导致整个流程崩溃
    # ------------------------------------------------------------------

    @field_validator("assumptions", mode="before")
    @classmethod
    def _coerce_assumptions(cls, v: object) -> list[dict]:
        """兼容 list[str] 假设来源，统一转为 list[dict]。

        防回归：explorer 的 LLM 决策路径会输出字符串假设列表
        （如 "目标函数和约束条件可线性化"），直接构造 QuestionResult
        会触发 pydantic ``dict_type`` 校验错误。在 schema 边界兜底，
        任何构造点传入字符串列表都不会再崩。
        """
        if v is None:
            return []
        if not isinstance(v, (list, tuple)):
            return [{"description": str(v), "type": "method_inherent", "verifiable": True}]
        out: list[dict] = []
        for a in v:
            if isinstance(a, dict):
                entry = dict(a)
                desc = (
                    entry.get("description")
                    or entry.get("content")
                    or entry.get("assumption")
                    or ""
                )
                entry["description"] = str(desc)
                entry.setdefault("type", "method_inherent")
                entry.setdefault("verifiable", True)
                out.append(entry)
            else:
                out.append({
                    "description": str(a),
                    "type": "method_inherent",
                    "verifiable": True,
                })
        return out

    @field_validator("method_candidates", mode="before")
    @classmethod
    def _coerce_method_candidates(cls, v: object) -> list[dict]:
        """过滤候选列表中的非 dict 项（LLM 输出异常时）。"""
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        return [c for c in v if isinstance(c, dict)]
