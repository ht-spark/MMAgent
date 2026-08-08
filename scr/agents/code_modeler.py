"""任务驱动的 LLM 建模器：分段生成数学模型与求解代码。

对应"任务驱动建模 + 代码执行"计算层的建模端，分两段调用 LLM：
  1. ``generate_model``   — 只生成数学模型 JSON
  2. ``generate_code``    — 基于模型设计生成求解代码
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "code_based_modeling.md"
_CODE_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "code_generation.md"

#: 允许参与"任务驱动建模"的任务类型
CODE_BASED_TASKS = {
    "optimization",
    "stochastic_optimization",
    "evaluation",
    "prediction",
    "simulation",
    "classification",
    "clustering",
    "composite",
}

#: 模型设计调用超时（秒）——"思考"阶段，给足时间（6 分钟）
MODEL_DESIGN_TIMEOUT = 360
#: 代码生成调用超时（秒）——"写代码"阶段，给足时间（6 分钟）
CODE_GENERATION_TIMEOUT = 360
#: 等待进度打印间隔（秒）
_PROGRESS_INTERVAL = 60


class CodeModelingError(Exception):
    """LLM 建模失败（解析失败或缺少关键字段）。"""


class LLMTimeoutError(CodeModelingError):
    """LLM 调用超时。上层应"超时即回退"，不重试同一生成。"""


class CodeModeler:
    """分段调用 LLM 生成"数学模型 + 求解代码"。

    Args:
        llm: langchain 风格 LLM（须支持 invoke）。
    """

    def __init__(self, llm: Any) -> None:
        if llm is None:
            raise CodeModelingError("CodeModeler 需要 LLM 实例")
        self._llm = llm

    # ------------------------------------------------------------------
    # 第一段：数学模型设计
    # ------------------------------------------------------------------

    def generate_model(
        self,
        question_text: str,
        math_task: str,
        method_hint: str = "",
        data_summary: str = "",
        feedback: str = "",
    ) -> dict:
        """生成数学模型 JSON（不含代码）。

        Raises:
            CodeModelingError: 解析或校验失败。
            LLMTimeoutError: LLM 调用超时。
        """
        prompt = self._build_model_prompt(
            question_text, math_task, method_hint, data_summary, feedback
        )
        t0 = time.time()
        print(
            f"[code_modeler] 第 1 段：LLM 设计数学模型"
            f"（题型={math_task}，方法={method_hint or 'auto'}，超时 {MODEL_DESIGN_TIMEOUT}s）..."
        )
        content = self._invoke(prompt, timeout=MODEL_DESIGN_TIMEOUT)

        model_json = self._parse_json(content)
        model_json.setdefault("model_name", "未命名模型")
        model_json.setdefault("model_summary", "")
        print(
            f"[code_modeler] 模型设计完成（耗时 {time.time() - t0:.1f}s，"
            f"模型={model_json.get('model_name', '?')}）"
        )
        return model_json

    # ------------------------------------------------------------------
    # 第二段：求解代码生成
    # ------------------------------------------------------------------

    def generate_code(
        self,
        model_json: dict,
        question_text: str = "",
        data_summary: str = "",
        feedback: str = "",
    ) -> str:
        """基于模型设计生成求解代码。

        Returns:
            完整可运行的 Python 代码字符串。

        Raises:
            CodeModelingError: LLM 未返回代码。
            LLMTimeoutError: LLM 调用超时。
        """
        prompt = self._build_code_prompt(model_json, question_text, data_summary, feedback)
        t0 = time.time()
        print(
            f"[code_modeler] 第 2 段：LLM 生成求解代码"
            f"（模型={model_json.get('model_name', '?')}，超时 {CODE_GENERATION_TIMEOUT}s）..."
        )
        content = self._invoke(prompt, timeout=CODE_GENERATION_TIMEOUT)

        code = self._extract_code(content)
        code_len = len(code)
        print(f"[code_modeler] 代码生成完成（耗时 {time.time() - t0:.1f}s，{code_len} 字符）")
        return code

    # ------------------------------------------------------------------
    # LLM 调用（超时 + 进度）
    # ------------------------------------------------------------------

    def _invoke(self, prompt: str, timeout: float) -> str:
        """调用 LLM，超时抛 LLMTimeoutError，等待期间打印进度。"""
        import threading

        box: dict[str, Any] = {}
        err: dict[str, Exception] = {}

        def _worker() -> None:
            try:
                box["raw"] = self._llm.invoke(prompt)
            except Exception as e:  # noqa: BLE001 - 收集任意异常供主线程
                err["exc"] = e

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

        waited = 0.0
        while True:
            t.join(timeout=min(_PROGRESS_INTERVAL, timeout - waited))
            waited += min(_PROGRESS_INTERVAL, timeout - waited)
            if not t.is_alive():
                break
            if waited >= timeout:
                raise LLMTimeoutError(f"LLM 调用超时（>{timeout:.0f}s），已放弃本次生成")
            print(f"[code_modeler]   ↳ LLM 调用进行中（已等待 {waited:.0f}s / {timeout:.0f}s）...")

        if "exc" in err:
            raise err["exc"]
        if "raw" not in box:
            raise CodeModelingError("LLM 调用未返回结果")
        raw = box["raw"]
        return self._extract_content(raw)

    # ------------------------------------------------------------------
    # Prompt 构建
    # ------------------------------------------------------------------

    def _build_model_prompt(
        self,
        question_text: str,
        math_task: str,
        method_hint: str,
        data_summary: str,
        feedback: str,
    ) -> str:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
        return self._fill(
            template,
            question_text=question_text,
            math_task=math_task,
            method_hint=method_hint,
            data_summary=data_summary,
            feedback=feedback,
        )

    def _build_code_prompt(
        self,
        model_json: dict,
        question_text: str,
        data_summary: str,
        feedback: str,
    ) -> str:
        template = _CODE_PROMPT_PATH.read_text(encoding="utf-8")
        return self._fill(
            template,
            model_json=json.dumps(model_json, ensure_ascii=False, indent=2),
            question_text=question_text,
            data_summary=data_summary,
            feedback=feedback,
        )

    @staticmethod
    def _fill(template: str, **kwargs: Any) -> str:
        """用 replace 填充占位符（模板含 JSON 示例花括号，不能用 str.format）。"""
        result = template
        for key, value in kwargs.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result

    # ------------------------------------------------------------------
    # 响应解析
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_content(raw: Any) -> str:
        """兼容 langchain 消息对象与纯字符串。"""
        if hasattr(raw, "content"):
            return str(raw.content)
        return str(raw)

    @staticmethod
    def _parse_json(content: str) -> dict:
        """从 LLM 响应中提取 JSON（剥离思维链 + 代码块 + 括号平衡）。"""
        from ..tools.llm_response import extract_json

        try:
            return extract_json(content)
        except ValueError as e:
            raise CodeModelingError(str(e)) from e

    @staticmethod
    def _extract_code(content: str) -> str:
        """从 LLM 响应中提取 Python 代码（剥离思维链与代码块围栏）。"""
        from ..tools.llm_response import extract_code as _extract

        try:
            return _extract(content)
        except ValueError as e:
            raise CodeModelingError(str(e)) from e
