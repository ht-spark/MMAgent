"""LLM 监控包装器：在每次调用时记录耗时（TIME）与令牌（TOKEN）到预算管理器。

监控型预算（TIME / TOKEN）全程累计、永不阻塞；仅用于事后报告
"每问耗时/令牌"与"任务总耗时/总令牌"（见 budget.py）。

设计要点：
  - 透明包装任意 langchain LLM（ChatOpenAI 等），转发 invoke / ainvoke /
    with_structured_output。
  - 令牌通过 UsageMetadataCallbackHandler 在每次调用时就近采集，规避
    with_structured_output 返回已解析对象导致 usage_metadata 丢失的问题。
  - qid_getter：动态获取当前小问 ID，使监控能区分"每问消耗"与"任务总消耗"。
  - 包装器仅在节点函数内局部创建并传给 Agent，不写回 state，避免破坏
    checkpoint 序列化（state["llm"] 不应持有不可 pickle 的 lambda / 闭包）。
"""
from __future__ import annotations

import importlib
import time
from typing import Any, Callable

from .budget import BudgetManager, BudgetType


def _new_usage_handler() -> Any | None:
    """创建一个用量回调处理器，用于就近采集令牌。

    在多个可能的模块路径中尝试导入 ``UsageMetadataCallbackHandler``，
    全部失败（如未安装 langchain）时返回 None，由调用方回退到从响应对象提取。
    """
    for mod_path in (
        "langchain.callbacks",
        "langchain_community.callbacks",
        "langchain_core.callbacks",
    ):
        try:
            m = importlib.import_module(mod_path)
        except Exception:
            continue
        handler_cls = getattr(m, "UsageMetadataCallbackHandler", None)
        if handler_cls is not None:
            try:
                return handler_cls()
            except Exception:
                return None
    return None


def _extract_tokens(response: Any, handler: Any) -> int:
    """从回调处理器或响应对象中提取本次调用的令牌总数。"""
    if handler is not None:
        total = getattr(handler, "total_tokens", None)
        if total:
            return int(total)
    if response is not None:
        um = getattr(response, "usage_metadata", None)
        if isinstance(um, dict) and um.get("total_tokens"):
            return int(um["total_tokens"])
        rm = getattr(response, "response_metadata", None)
        if isinstance(rm, dict):
            tu = rm.get("token_usage", {})
            if isinstance(tu, dict) and tu.get("total_tokens"):
                return int(tu["total_tokens"])
    return 0


class InstrumentedLLM:
    """透明包装 langchain LLM，记录 TIME / TOKEN 监控用量（不阻塞）。"""

    def __init__(
        self,
        llm: Any,
        budget_manager: BudgetManager | None = None,
        qid_getter: Callable[[], str | None] | None = None,
    ) -> None:
        # 幂等：若已包裹，复用内层 llm 与 budget_manager，qid_getter 以本次为准
        if isinstance(llm, InstrumentedLLM):
            inner = llm._llm
            bm = budget_manager or llm._budget_manager
            base_qid = llm._qid_getter
        else:
            inner = llm
            bm = budget_manager
            base_qid = None
        self._llm = inner
        self._budget_manager = bm
        self._qid_getter = qid_getter or base_qid

    def _current_qid(self) -> str | None:
        if self._qid_getter is None:
            return None
        try:
            return self._qid_getter()
        except Exception:
            return None

    @staticmethod
    def _attach_callbacks(kwargs: dict, handler: Any) -> dict:
        """在 Invoke 配置中附加回调处理器（保留已有 callbacks）。"""
        cfg = dict(kwargs.get("config") or {})
        cbs = list(cfg.get("callbacks") or [])
        cbs.append(handler)
        cfg["callbacks"] = cbs
        new_kwargs = dict(kwargs)
        new_kwargs["config"] = cfg
        return new_kwargs

    def invoke(self, prompt: Any, *args: Any, **kwargs: Any) -> Any:
        if self._budget_manager is None or self._llm is None:
            return self._llm.invoke(prompt, *args, **kwargs)
        t0 = time.monotonic()
        handler = _new_usage_handler()
        invoke_kwargs = self._attach_callbacks(kwargs, handler) if handler is not None else kwargs
        try:
            response = self._llm.invoke(prompt, *args, **invoke_kwargs)
        finally:
            elapsed = time.monotonic() - t0
        qid = self._current_qid()
        # 时间：秒（浮点，精确累计）；监控型预算不做限制
        self._budget_manager.record_monitor(BudgetType.TIME, elapsed, question_id=qid)
        tokens = _extract_tokens(response, handler)
        if tokens > 0:
            self._budget_manager.record_monitor(BudgetType.TOKEN, tokens, question_id=qid)
        return response

    async def ainvoke(self, prompt: Any, *args: Any, **kwargs: Any) -> Any:
        if self._budget_manager is None or self._llm is None:
            return await self._llm.ainvoke(prompt, *args, **kwargs)
        t0 = time.monotonic()
        handler = _new_usage_handler()
        invoke_kwargs = self._attach_callbacks(kwargs, handler) if handler is not None else kwargs
        try:
            response = await self._llm.ainvoke(prompt, *args, **invoke_kwargs)
        finally:
            elapsed = time.monotonic() - t0
        qid = self._current_qid()
        self._budget_manager.record_monitor(BudgetType.TIME, elapsed, question_id=qid)
        tokens = _extract_tokens(response, handler)
        if tokens > 0:
            self._budget_manager.record_monitor(BudgetType.TOKEN, tokens, question_id=qid)
        return response

    def with_structured_output(self, *args: Any, **kwargs: Any) -> "InstrumentedLLM":
        structured = self._llm.with_structured_output(*args, **kwargs)
        return InstrumentedLLM(structured, self._budget_manager, qid_getter=self._qid_getter)

    def __getattr__(self, name: str) -> Any:
        # 透传底层 llm 的其它属性（如 model_name / bind 等），避免部分调用方
        # 直接访问底层属性时报错。注意避免对 _llm 自身触发递归。
        if name == "_llm":
            raise AttributeError(name)
        return getattr(self._llm, name)
