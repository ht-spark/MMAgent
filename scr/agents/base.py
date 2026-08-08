"""LLM 智能体的公共基类。

负责加载和渲染提示词模板，并将模型响应解析为 Pydantic 结构化结果。
具体智能体继承本类以复用可注入的 LLM 调用能力。
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
        # 缓存标志：一旦发现 LLM 不支持 json_schema response_format，
        # 后续直接使用 json_mode，避免每次都尝试失败并打印错误日志。
        self._json_schema_unsupported: bool = False

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

        支持两种配置：
          1. OpenAI: OPENAI_API_KEY + MODEL_NAME + OPENAI_BASE_URL
          2. DeepSeek（兼容 OpenAI 接口）: DEEPSEEK_API_KEY + DEEPSEEK_MODEL + DEEPSEEK_BASE_URL
        """
        # 优先尝试 OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            model_name = os.getenv("MODEL_NAME", "gpt-4o")
            base_url = os.getenv("OPENAI_BASE_URL")
        else:
            # 尝试 DeepSeek
            api_key = os.getenv("DEEPSEEK_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "No API key found. Set OPENAI_API_KEY or DEEPSEEK_API_KEY "
                    "in .env, or pass an llm instance to the agent constructor."
                )
            model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
            base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

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

        三级回退策略：
          1. with_structured_output（默认，OpenAI 等支持 json_schema 的模型）
          2. with_structured_output(method="json_mode")（DeepSeek 等仅支持 json_object 的模型）
          3. JSON prompt + 手动解析（兼容所有模型）

        一旦方案 1 因 response_format 不可用而失败，会设置 ``_json_schema_unsupported``
        标志，后续调用直接跳到方案 2，避免重复尝试和错误日志刷屏。

        Args:
            schema: Pydantic 模型类，约束 LLM 输出结构。
            prompt: 渲染后的 prompt 文本。

        Returns:
            schema 的实例。
        """
        # 方案 1：尝试 structured output（默认方式，使用 json_schema）
        # 若已缓存"不支持 json_schema"标志，则跳过
        if not self._json_schema_unsupported:
            try:
                structured_llm = self.llm.with_structured_output(schema)
                result = structured_llm.invoke(prompt)
                if result is None:
                    # 部分 langchain 包装器在底层错误时吞掉异常并返回 None，
                    # 统一抛出以便上层 try/except 走回退路径（启发式）。
                    raise RuntimeError("LLM structured call returned None")
                return result
            except Exception as e:
                err_msg = str(e)
                if "response_format" not in err_msg and "BadRequestError" not in str(type(e).__name__):
                    raise  # 非 structured output 相关的错误，直接抛出
                # 记住此 LLM 不支持 json_schema，后续直接走 json_mode
                self._json_schema_unsupported = True

        # 方案 2：尝试 json_mode（兼容仅支持 json_object 的模型，如 DeepSeek）
        try:
            structured_llm = self.llm.with_structured_output(schema, method="json_mode")
            return structured_llm.invoke(prompt)
        except Exception:
            pass  # 继续尝试方案 3

        # 方案 3：JSON prompt + 手动解析（最终回退）
        return self._call_structured_json_fallback(schema, prompt)

    def _call_structured_json_fallback(self, schema: type[T], prompt: str) -> T:
        """JSON prompt + 手动解析（兼容不支持 response_format 的模型）。"""
        import json

        # 构建 JSON 示例
        schema_json = schema.model_json_schema()
        example = self._schema_to_example(schema_json)

        json_prompt = (
            prompt
            + "\n\n---\n**重要**：你必须用纯 JSON 格式回答，不要用 Markdown 代码块，不要加解释。\n"
            + f"JSON 格式和字段说明：\n```json\n{example}\n```\n"
            + "直接返回 JSON，不要 ```json 包裹。"
        )

        result = self.llm.invoke(json_prompt)
        text = (result.content if hasattr(result, "content") else str(result)).strip()

        # 鲁棒解析：剥离 <think> 思维链 + 代码块 + 括号平衡提取 JSON
        from ..tools.llm_response import extract_json

        try:
            data = extract_json(text)
        except ValueError:
            raise ValueError(f"JSON 解析失败，LLM 返回: {text[:300]}")

        return schema.model_validate(data)

    @staticmethod
    def _schema_to_example(schema_json: dict) -> str:
        """从 JSON Schema 生成简化的示例 JSON 字符串。"""
        import json

        props = schema_json.get("properties", {})
        example: dict = {}
        for key, prop in props.items():
            ptype = prop.get("type", "string")
            if ptype == "array":
                items = prop.get("items", {})
                if items.get("type") == "string":
                    example[key] = ["示例项1", "示例项2"]
                else:
                    example[key] = []
            elif ptype == "object":
                example[key] = {}
            elif ptype in ("integer", "number"):
                example[key] = 0
            elif ptype == "boolean":
                example[key] = False
            else:
                # 尝试从 enum 取第一个值
                enum = prop.get("enum")
                if enum:
                    example[key] = enum[0]
                else:
                    example[key] = "示例文本"
        return json.dumps(example, ensure_ascii=False, indent=2)
