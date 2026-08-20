"""
LLM 客户端工厂。

支持按请求显式传参（provider / api_key / base_url / model），
也兼容通用环境变量（LLM_*）和原有配置（OPENAI_* / DEEPSEEK_*）。

provider 取值：
  - "openai"    : OpenAI 兼容（含自定义 base_url）
  - "deepseek"  : DeepSeek（兼容 OpenAI 接口）
  - "custom"    : 完全自定义，必须同时提供 api_key / base_url / model
  - None        : 按环境变量自动选择（优先 LLM_*，其次 OPENAI、DEEPSEEK）
"""
from __future__ import annotations

import os
from typing import Any

from ..runtime.logging import get_logger


def create_llm(
    provider: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    *,
    fallback_env: bool = True,
) -> Any | None:
    """创建一个 OpenAI 兼容的 LLM 客户端。

    Args:
        provider: "openai" | "deepseek" | "custom" | None（自动）。
        api_key: API Key，缺省时回退到环境变量。
        base_url: 自定义 API 基地址，缺省时回退到环境变量。
        model: 模型名，缺省时回退到环境变量默认值。
        fallback_env: 当显式参数缺失时是否回退到环境变量。

    Returns:
        ChatOpenAI 实例，或可回退时返回 None（交给调用方走无 LLM 路径）。
    """
    resolved_provider = provider
    resolved_key = api_key
    resolved_url = base_url
    resolved_model = model

    # 通用 OpenAI 兼容配置，适用于任意服务商。
    env_generic_provider = os.getenv("LLM_PROVIDER")
    env_generic_key = os.getenv("LLM_API_KEY")
    env_generic_url = os.getenv("LLM_BASE_URL")
    env_generic_model = os.getenv("LLM_MODEL")

    # 自动探测 provider（仅在未显式指定时）
    env_openai = os.getenv("OPENAI_API_KEY")
    env_deepseek = os.getenv("DEEPSEEK_API_KEY")

    if resolved_provider is None:
        if env_generic_provider:
            resolved_provider = env_generic_provider
        elif env_generic_key:
            resolved_provider = "custom"
        elif env_openai:
            resolved_provider = "openai"
        elif env_deepseek:
            resolved_provider = "deepseek"
        else:
            resolved_provider = "openai"  # 默认尝试 openai

    if resolved_provider == "openai":
        resolved_key = resolved_key or env_openai
        resolved_model = resolved_model or os.getenv("MODEL_NAME", "gpt-4o")
        resolved_url = resolved_url or os.getenv("OPENAI_BASE_URL")
    elif resolved_provider == "deepseek":
        resolved_key = resolved_key or env_deepseek
        resolved_model = resolved_model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        resolved_url = resolved_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    elif resolved_provider == "custom":
        resolved_key = resolved_key or env_generic_key
        resolved_url = resolved_url or env_generic_url
        resolved_model = resolved_model or env_generic_model
        if not (resolved_key and resolved_url and resolved_model):
            return None
    else:
        return None

    if not resolved_key:
        if fallback_env:
            # 实在没有凭据：返回 None，由调用方决定降级
            return None
        return None

    try:
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {"model": resolved_model, "api_key": resolved_key}
        if resolved_url:
            kwargs["base_url"] = resolved_url
        # 单次调用超时（秒）。避免 LLM 端点无响应时线程无限阻塞，
        # 也让「中断任务」能在当前节点结束后尽快在边界生效。
        kwargs["timeout"] = 120
        # 生成参数：控制输出的随机性
        kwargs["temperature"] = 0.3
        return ChatOpenAI(**kwargs)
    except ImportError:
        get_logger().warning("[llm] langchain_openai 未安装，LLM 不可用")
        return None
