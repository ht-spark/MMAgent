"""question_solver 单元测试：assumptions 规范化（防 LLM list[str] 崩溃回归）。"""
from __future__ import annotations

from scr.agents.question_solver import QuestionSolver
from scr.schemas.question import QuestionResult


class TestNormalizeAssumptions:
    """QuestionResult.assumptions 要求 list[dict]，需兼容 LLM 输出的 list[str]。"""

    def test_str_list_to_dict(self):
        raw = ["目标函数和约束条件可线性化", "决策变量为连续或整数"]
        norm = QuestionSolver._normalize_assumptions(raw)
        assert len(norm) == 2
        assert all(isinstance(a, dict) for a in norm)
        assert norm[0]["description"] == "目标函数和约束条件可线性化"
        assert norm[0]["type"] == "method_inherent"
        assert norm[0]["verifiable"] is True

    def test_dict_list_preserved(self):
        raw = [{"description": "样本量有限", "type": "data_limitation", "verifiable": True}]
        assert QuestionSolver._normalize_assumptions(raw) == raw

    def test_mixed(self):
        norm = QuestionSolver._normalize_assumptions(
            ["假设A", {"description": "假设B", "type": "custom"}]
        )
        assert len(norm) == 2
        assert all(isinstance(a, dict) for a in norm)
        assert norm[1]["type"] == "custom"

    def test_empty_and_none(self):
        assert QuestionSolver._normalize_assumptions([]) == []
        assert QuestionSolver._normalize_assumptions(None) == []

    def test_question_result_accepts_normalized(self):
        """回归：LLM list[str] 假设经规范化后 QuestionResult 不再报 dict_type。"""
        norm = QuestionSolver._normalize_assumptions(
            ["目标函数和约束条件可线性化"]
        )
        r = QuestionResult(
            question_id="q1",
            status="validating",
            assumptions=norm,
        )
        assert r.assumptions[0]["description"] == "目标函数和约束条件可线性化"

    def test_schema_coerces_str_assumptions(self):
        """schema 边界兜底：直接传 list[str] 假设也不再崩溃。"""
        raw = [
            "无人机运动方向和速度服从均匀分布",
            "导弹飞行轨迹为直线",
            "烟幕干扰弹起爆后匀速下沉",
        ]
        r = QuestionResult(question_id="q1", status="validating", assumptions=raw)
        assert all(isinstance(a, dict) for a in r.assumptions)
        assert r.assumptions[0]["description"] == "无人机运动方向和速度服从均匀分布"
        assert r.assumptions[0]["type"] == "method_inherent"

    def test_schema_filters_method_candidates(self):
        """method_candidates 边界兜底：非 dict 项被过滤。"""
        r = QuestionResult(
            question_id="q1",
            method_candidates=[{"name": "熵权法"}, "bad", 42, None],
        )
        assert r.method_candidates == [{"name": "熵权法"}]
