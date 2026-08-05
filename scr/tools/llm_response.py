"""LLM 响应鲁棒解析工具。

系统性解决"LLM 输出格式不可预测"问题：
  - DeepSeek 等推理模型会在正式输出前附带 ``<think>...</think>`` 思维链
  - 响应可能被 markdown 代码块、解释文字、前后缀包裹
  - JSON 可能被截断、含注释、或括号不匹配

提供三个通用函数（不依赖具体 LLM/题目）：
  - ``strip_thinking``   剥离思维链标签
  - ``extract_json``     括号平衡法提取第一个完整 JSON 对象
  - ``extract_code``     提取 Python 代码（剥离思维链 + 代码块围栏）
"""
from __future__ import annotations

import json
import re
from typing import Any

__all__ = ["strip_thinking", "extract_json", "extract_code"]


def strip_thinking(text: str) -> str:
    """剥离 DeepSeek 等推理模型的 ``<think>...</think>`` 思维链。

    规则：
      - 有闭合标签：移除 ``<think>`` 到**最后一个** ``</think>`` 之间的内容
      - 无闭合标签：截断到 ``<think>`` 之前（视为思维链未完成）
    """
    text = text or ""
    if "<think>" in text:
        if "</think>" in text:
            idx_end = text.rfind("</think>") + len("</think>")
            text = text[idx_end:]
        else:
            text = text[: text.find("<think>")]
    return text.strip()


def extract_json(text: str) -> dict:
    """从 LLM 响应中提取第一个完整 JSON 对象（鲁棒）。

    策略：
      1. 剥离思维链
      2. 直接解析；失败则尝试 ```json 代码块
      3. 逐起点做括号平衡匹配（正确处理字符串内的大括号），
         从合法候选解析 dict

    Raises:
        ValueError: 无法提取到合法 JSON 对象。
    """
    text = strip_thinking(text)
    if not text:
        raise ValueError("LLM 响应为空")

    # 1. 直接解析
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 2. markdown json 代码块
    block = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if block:
        try:
            obj = json.loads(block.group(1).strip())
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # 3. 括号平衡提取（容忍前后杂文本 / 思维链残留）
    obj = _extract_balanced_dict(text)
    if obj is not None:
        return obj

    raise ValueError(
        f"无法从 LLM 响应中解析 JSON。响应片段: {text[:300]}"
    )


def extract_code(text: str) -> str:
    """从 LLM 响应中提取 Python 代码（剥离思维链与代码块围栏）。"""
    text = strip_thinking(text)
    if not text:
        raise ValueError("LLM 响应为空")

    block = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
    if block:
        code = block.group(1).strip()
    else:
        code = text.strip()

    if not code:
        raise ValueError("LLM 未返回代码")
    return code


def _extract_balanced_dict(text: str) -> dict | None:
    """从文本中逐起点做括号平衡匹配，返回第一个可解析的 dict。"""
    start = text.find("{")
    while start != -1:
        end = _match_brace(text, start)
        if end != -1:
            candidate = text[start:end + 1]
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass  # 该起点不合法，继续下一个 {
        start = text.find("{", start + 1)
    return None


def _match_brace(text: str, start: int) -> int:
    """返回从 start 开始的平衡花括号的结束下标；不合法返回 -1。

    正确处理：字符串内的 {}、转义符、换行。
    """
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1
