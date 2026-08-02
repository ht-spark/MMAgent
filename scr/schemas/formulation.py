"""Generic mathematical modeling formulation IR.

The IR is intentionally domain-neutral. It captures the structure every
competition solution should expose before a solver or paper writer uses it.
Existing code can keep consuming the legacy formulation dict; builders attach
this IR under ``formulation["ir"]`` as a stable bridge for future adapters.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ModelingTask = Literal[
    "evaluation",
    "prediction",
    "optimization",
    "stochastic_optimization",
    "classification",
    "clustering",
    "simulation",
    "mechanism",
    "composite",
]

MODELING_TASKS = {
    "evaluation",
    "prediction",
    "optimization",
    "stochastic_optimization",
    "classification",
    "clustering",
    "simulation",
    "mechanism",
    "composite",
}


class VariableIR(BaseModel):
    """A decision, state, score, or fitted variable in a model."""

    symbol: str
    meaning: str = ""
    domain: str = "real"
    indices: list[str] = Field(default_factory=list)


class ConstraintIR(BaseModel):
    """A model constraint with a machine-checkable role label."""

    expression: str
    meaning: str = ""
    role: str = "generic"


class FormulationIR(BaseModel):
    """Domain-neutral formulation for a mathematical modeling subproblem."""

    question_id: str
    math_task: ModelingTask
    method_key: str = ""
    method_name: str = ""
    sets: list[str] = Field(default_factory=list)
    indices: list[str] = Field(default_factory=list)
    parameters: dict[str, str] = Field(default_factory=dict)
    variables: list[VariableIR] = Field(default_factory=list)
    objective: str = ""
    objective_sense: Literal["min", "max", "score", "estimate", "simulate", "none"] = "none"
    constraints: list[ConstraintIR] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    required_outputs: list[str] = Field(default_factory=list)
    validation_requirements: list[str] = Field(default_factory=list)

    def to_legacy_dict(self) -> dict:
        """Return fields compatible with the existing formulation dict."""
        return {
            "method": self.method_name,
            "math_task": self.math_task,
            "decision_variables": [
                f"{v.symbol}: {v.meaning}" if v.meaning else v.symbol
                for v in self.variables
            ],
            "objective_function": self.objective,
            "constraints": [c.expression for c in self.constraints],
            "parameters": self.parameters,
            "ir": self.model_dump(),
        }
