"""G3 决策门单元测试（demo 简化版）。"""
from __future__ import annotations

from scr.gates.g3_decision import G3DecisionGate
from scr.schemas.model import ModelCriticReport


def test_passed_judgment_action_pass():
    """Critic 裁决 passed → action=pass，进入 H1。"""
    gate = G3DecisionGate()
    state = {
        "model_critic_report": ModelCriticReport(
            overall_judgment="passed",
            checks={"gap_coverage": "通过"},
            suggested_action="approve",
            reasoning="候选合理",
        ),
    }
    result = gate.evaluate(state)
    assert result.passed is True
    assert result.action == "pass"


def test_insufficient_evidence_escalates_to_l1():
    """Critic 裁决 insufficient_evidence → action=escalate。"""
    gate = G3DecisionGate()
    state = {
        "model_critic_report": ModelCriticReport(
            overall_judgment="insufficient_evidence",
            checks={"authoritative_source": "失败：缺 S/A 证据"},
            suggested_action="back_to_L1",
            reasoning="证据不足",
        ),
    }
    result = gate.evaluate(state)
    assert result.passed is False
    assert result.action == "escalate"
    assert "insufficient_evidence" in result.failed_checks