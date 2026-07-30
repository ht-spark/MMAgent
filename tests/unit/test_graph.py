"""LangGraph 图构建 smoke 测试（无 LLM）。

详细的端到端测试见 test_graph_phase2.py。
"""
from scr.math_modeling_agent.graph import build_graph


def test_build_graph():
    """构建 LangGraph 主图不报错。"""
    app = build_graph(checkpoint=False)
    assert app is not None


def test_build_graph_with_checkpoint():
    """带 checkpoint 的图构建不报错。"""
    app = build_graph(checkpoint=True)
    assert app is not None
