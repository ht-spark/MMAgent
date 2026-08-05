"""LLM 响应鲁棒解析工具单元测试。

覆盖 DeepSeek 等推理模型的 <think> 思维链、代码块围栏、前后杂文本等
不可预测输出格式（系统性修复，不针对具体题目）。
"""
from __future__ import annotations

import pytest

from scr.tools.llm_response import extract_code, extract_json, strip_thinking


class TestStripThinking:
    def test_standard_closed(self):
        text = "<think>分析过程</think>{\"model_name\": \"A\"}"
        assert strip_thinking(text) == '{"model_name": "A"}'

    def test_thinking_contains_braces(self):
        text = "<think>JSON 结构 { 应该这样 } 结束</think>{\"x\": 1}"
        assert strip_thinking(text) == '{"x": 1}'

    def test_unclosed_think_truncated(self):
        text = "<think>思维链未完成\n继续思考\n{\"model_name\": \"A\"}"
        assert strip_thinking(text) == ""

    def test_no_think_passthrough(self):
        assert strip_thinking('{"model_name": "A"}') == '{"model_name": "A"}'

    def test_multiple_think_blocks(self):
        text = "<think>一</think>正文1<think>二</think>{\"x\": 2}"
        # 保留最后一个 </think> 之后的内容（think 块与其间文本均视为前导噪音）
        assert strip_thinking(text) == '{"x": 2}'


class TestExtractJson:
    def test_think_then_json(self):
        payload = "<think>先分析题目\n</think>" + '{"model_name": "测试LP"}'
        assert extract_json(payload) == {"model_name": "测试LP"}

    def test_think_with_braces_then_json(self):
        """思维链里含 { } 字符（用户日志中的真实场景）。"""
        payload = (
            "<think>用户指出模型设计失败，可能是因为之前的响应格式不符合要求。"
            "首先检查 JSON 结构 { variables, objective }</think>"
            '{"model_name": "评价模型", "math_task": "evaluation"}'
        )
        obj = extract_json(payload)
        assert obj["model_name"] == "评价模型"
        assert obj["math_task"] == "evaluation"

    def test_fenced_json(self):
        payload = "<think>思考</think>\n```json\n{\"a\": 1}\n```"
        assert extract_json(payload) == {"a": 1}

    def test_surrounding_text(self):
        payload = "好的，以下是模型：\n{\"a\": 1}\n以上。"
        assert extract_json(payload) == {"a": 1}

    def test_braces_inside_string(self):
        """字符串值内含大括号不应破坏平衡匹配。"""
        payload = '{"text": "包含{花括号}的文本", "n": 1}'
        assert extract_json(payload) == {"text": "包含{花括号}的文本", "n": 1}

    def test_unparseable_raises(self):
        with pytest.raises(ValueError, match="无法从 LLM 响应中解析"):
            extract_json("<think>只有思考没有输出</think>这不是 JSON")


class TestExtractCode:
    def test_think_then_fenced_code(self):
        payload = (
            "<think>写代码</think>\n"
            "```python\nimport json\nprint(1)\n```"
        )
        code = extract_code(payload)
        assert "import json" in code
        assert "print(1)" in code

    def test_plain_code(self):
        assert extract_code("import json\nprint(1)") == "import json\nprint(1)"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="未返回代码|为空"):
            extract_code("   \n  ")
