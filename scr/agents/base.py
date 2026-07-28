"""BaseAgent — LLM Agent 基类。

职责：
  - 加载 prompt 模板（prompts/*.md）
  - 渲染模板（替换占位符）
  - 调用 LLM 并返回 Pydantic 结构化输出

设计要点：
  - LLM 可注入（测试时传 FakeLLM，生产时从 config 创建 ChatOpenAI）
  - prompt 模板用 {var} 占位符，渲染时只替换已知变量，不影响 JSON 示例中的 {}
  - 对应 plan.md §1：Prompt 与代码分离，agents/ 依赖 schemas/prompts
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# scr 包根目录（agents/ 的上一级）
_SCR_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PROMPT_DIR = _SCR_ROOT / "prompts"


class BaseAgent:
    """LLM Agent 基类。

    Args:
        llm: 可选的 LLM 客户端。需实现 ``with_structured_output(schema)`` 和
             ``invoke(prompt)`` 接口（如 langchain 的 ChatOpenAI）。
             测试时传入 FakeLLM；生产时不传则从环境变量自动创建。
        prompt_dir: prompt 模板目录，默认为 ``scr/prompts/``。
    """

    def __init__(
        self,
        llm: Any | None = None,
        prompt_dir: str | Path | None = None,
    ) -> None:
        self._llm = llm
        self._prompt_dir = Path(prompt_dir) if prompt_dir else _DEFAULT_PROMPT_DIR

    # ------------------------------------------------------------------
    # LLM 管理
    # ------------------------------------------------------------------

    @property
    def llm(self) -> Any:
        """惰性初始化 LLM 客户端。"""
        if self._llm is None:
            self._llm = self._create_default_llm()
        return self._llm

    def _create_default_llm(self) -> Any:
        """从环境变量创建默认 LLM 客户端（langchain ChatOpenAI）。

        需要设置环境变量：
          - OPENAI_API_KEY: API 密钥（必需）
          - MODEL_NAME: 模型名（默认 gpt-4o）
          - OPENAI_BASE_URL: 自定义 API 地址（可选，用于兼容第三方接口）
        """
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Either set the environment variable "
                "or pass an llm instance to the agent constructor."
            )

        model_name = os.getenv("MODEL_NAME", "gpt-4o")
        base_url = os.getenv("OPENAI_BASE_URL")

        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {"model": model_name, "api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)

    # ------------------------------------------------------------------
    # Prompt 管理
    # ------------------------------------------------------------------

    def _load_prompt(self, name: str) -> str:
        """加载 prompt 模板文件。

        Args:
            name: 模板名（不含扩展名），如 "problem_analysis"。

        Returns:
            模板文本。

        Raises:
            FileNotFoundError: 模板文件不存在。
        """
        path = self._prompt_dir / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _render_prompt(template: str, **kwargs: Any) -> str:
        """渲染 prompt 模板。

        用 ``{var}`` 风格的占位符，逐个替换已知变量。
        不会影响模板中 JSON 示例里的 ``{}``。

        Args:
            template: 模板文本。
            **kwargs: 占位符名 → 值。

        Returns:
            渲染后的 prompt 字符串。
        """
        result = template
        for key, value in kwargs.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result

    # ------------------------------------------------------------------
    # LLM 调用
    # ------------------------------------------------------------------

    def _call_structured(self, schema: type[T], prompt: str) -> T:
        """调用 LLM 并返回结构化输出。

        Args:
            schema: Pydantic 模型类，约束 LLM 输出结构。
            prompt: 渲染后的 prompt 文本。

        Returns:
            schema 的实例。
        """
        structured_llm = self.llm.with_structured_output(schema)
        return structured_llm.invoke(prompt)
