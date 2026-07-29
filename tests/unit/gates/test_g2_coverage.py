"""G2 覆盖率门单元测试（demo 简化版）。"""
from __future__ import annotations

from scr.gates.g2_coverage import G2CoverageGate
from scr.schemas.research import (
    EvidenceItem,
    KnowledgeGap,
    SourceRecord,
)


def _make_complete_state() -> dict:
    """构造一个满足 G2 的完整 state。"""
    return {
        "knowledge_gaps": [
            KnowledgeGap(
                gap_type="model_precedent",
                description="熵权法标准实现",
                priority="high",
            ),
        ],
        "evidence_items": [
            EvidenceItem(
                claim="熵权法通过信息熵反映区分度",
                source_id="src_001",
                source_url="https://example.com/p1",
                fact_or_inference="fact",
                limitations="",
                confidence=0.9,
            ),
        ],
        "source_catalog": [
            SourceRecord(source_id="src_001", url="https://a.com", title="A", level="A", score=0.9),
            SourceRecord(source_id="src_002", url="https://b.com", title="B", level="S", score=0.95),
        ],
        "high_gap_coverage": 1.0,
    }


def test_complete_state_passes_g2():
    gate = G2CoverageGate()
    result = gate.evaluate(_make_complete_state())
    assert result.gate_id == "G2"
    assert result.passed is True
    assert result.action == "pass"


def test_insufficient_sa_sources_fails():
    """只 1 个 S/A 来源 → 失败。"""
    state = _make_complete_state()
    state["source_catalog"] = [
        SourceRecord(source_id="src_001", url="https://a.com", title="A", level="B", score=0.8),
        SourceRecord(source_id="src_002", url="https://b.com", title="B", level="C", score=0.7),
    ]
    gate = G2CoverageGate()
    result = gate.evaluate(state)
    assert result.passed is False
    assert "s_a_sources_count" in result.failed_checks[0] or "s_a_sources_count" in str(result.failed_checks)