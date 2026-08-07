"""LLM Agent 包。

每个 Agent 负责一个特定角色（任务理解、研究、建模、求解、写作、审查）。
Agent 加载 prompt 模板，调用 LLM，返回结构化输出。
"""
from __future__ import annotations

from .base import BaseAgent
from .modeling_agent import ModelingAgent
from .problem_analyst import ProblemAnalyst
from .research_agent import ResearchAgent

__all__ = ["BaseAgent", "ModelingAgent", "ProblemAnalyst", "ResearchAgent"]
