"""题目驱动的 LLM 建模器：生成具体数学模型与求解代码。

对应"题目驱动建模 + 代码执行"计算层的建模端：
  - 输入：小问文本、题型、方法建议、数据结构摘要（可选修复反馈）
  - 输出：建模 JSON（model_name/model_summary/variables/objective/constraints/
          key_parameters/solution_code）

代码由 code_executor 沙箱执行；无 LLM 或解析失败时由上层回退预设方法。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "code_based_modeling.md"

#: 允许参与"题目驱动建模"的任务类型
CODE_BASED_TASKS = {
    "optimization",
    "stochastic_optimization",
    "evaluation",
    "prediction",
    "simulation",
}


class CodeModelingError(Exception):
    """LLM 建模失败（无 LLM、响应解析失败或缺少 solution_code）。"""


class CodeModeler:
    """调用 LLM 生成"数学模型 + 求解代码"。

    Args:
        llm: langchain 风格 LLM（须支持 invoke）。
    """

    def __init__(self, llm: Any) -> None:
        if llm is None:
            raise CodeModelingError("CodeModeler 需要 LLM 实例")
        self._llm = llm

    def generate_model(
        self,
        question_text: str,
        math_task: str,
        method_hint: str = "",
        data_summary: str = "",
        feedback: str = "",
    ) -> dict:
        """生成建模 JSON（含 solution_code）。

        Args:
            question_text: 小问原文。
            math_task: 题型（optimization 等）。
            method_hint: 方法建议（如 "线性规划"）。
            data_summary: 数据结构摘要（字段/类型/样例）。
            feedback: 修复反馈（重试时传入上次失败原因）。

        Returns:
            建模 JSON dict。

        Raises:
            CodeModelingError: LLM 调用或解析失败、缺少 solution_code。
        """
        prompt = self._build_prompt(
            question_text, math_task, method_hint, data_summary, feedback
        )
        try:
            raw = self._llm.invoke(prompt)
        except Exception as e:
            raise CodeModelingError(f"LLM 调用失败: {e}")

        content = self._extract_content(raw)
        model_json = self._parse_json(content)
        self._validate(model_json)
        return model_json

    # ------------------------------------------------------------------
    # Prompt 构建
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        question_text: str,
        math_task: str,
        method_hint: str,
        data_summary: str,
        feedback: str,
    ) -> str:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
        feedback_block = (
            f"上一轮生成的模型/代码未能通过执行校验，错误如下：\n{feedback}\n"
            if feedback
            else "无"
        )
        # 用 replace 而非 str.format：模板中的 JSON 示例含 {} 花括号，
        # format 会把 {"model_name"} 等误当作占位符触发 KeyError。
        replacements = {
            "{question_text}": question_text[:2000],
            "{math_task}": math_task,
            "{method_hint}": method_hint or "由你根据题型选择合适方法",
            "{data_summary}": data_summary[:3000] or "（无数据摘要）",
            "{feedback}": feedback_block,
        }
        prompt = template
        for key, value in replacements.items():
            prompt = prompt.replace(key, value)
        return prompt

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
        """从 LLM 响应中提取 JSON（容忍 markdown 代码块与前后杂文本）。"""
        text = content.strip()

        # 尝试直接解析
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

        # 尝试 ```json ... ``` 代码块
        block = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if block:
            try:
                obj = json.loads(block.group(1).strip())
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass

        # 尝试截取首个 { 到末个 }
        start = text.find("{")
        end = text.rfind("}")
        if 0 <= start < end:
            try:
                obj = json.loads(text[start:end + 1])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass

        raise CodeModelingError(
            f"无法从 LLM 响应中解析建模 JSON。响应片段: {text[:300]}"
        )

    @staticmethod
    def _validate(model_json: dict) -> None:
        """校验建模 JSON 的关键字段。"""
        if not model_json.get("solution_code") or not str(
            model_json["solution_code"]
        ).strip():
            raise CodeModelingError("建模 JSON 缺少 solution_code（求解代码）")
        for field in ("model_name", "model_summary"):
            if not model_json.get(field):
                model_json[field] = model_json.get("model_name", "未命名模型")
