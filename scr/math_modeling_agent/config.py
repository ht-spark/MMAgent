"""应用配置。

从环境变量读取 LLM 相关配置。
对应 plan.md Phase 0.3：pydantic-settings 读取 .env。
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfig:
    """LLM 调用配置。"""

    api_key: str | None
    model_name: str
    base_url: str | None
    temperature: float


def get_llm_config() -> LLMConfig:
    """从环境变量读取 LLM 配置。

    环境变量：
      - OPENAI_API_KEY: API 密钥
      - MODEL_NAME: 模型名（默认 gpt-4o）
      - OPENAI_BASE_URL: 自定义 API 地址（兼容第三方）
      - TEMPERATURE: 采样温度（默认 0.0，确定性输出）
    """
    return LLMConfig(
        api_key=os.getenv("OPENAI_API_KEY"),
        model_name=os.getenv("MODEL_NAME", "gpt-4o"),
        base_url=os.getenv("OPENAI_BASE_URL"),
        temperature=float(os.getenv("TEMPERATURE", "0.0")),
    )
