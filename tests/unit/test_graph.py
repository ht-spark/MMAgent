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


# ---------------------------------------------------------------------------
# 系统性加固：节点异常隔离（任何节点崩溃不终止整题运行）
# ---------------------------------------------------------------------------


class TestNodeExceptionIsolation:
    """_logged_node 包装器：节点异常降级而非抛给 LangGraph 终止整个图。"""

    def test_solve_question_exception_degrades_to_blocked(self):
        from scr.math_modeling_agent.graph import _logged_node

        @_logged_node("solve_question")
        def _boom(state):
            raise RuntimeError("模拟求解器崩溃")

        result = _boom({"current_question_id": "q1", "run_id": "test"})
        assert result["_gq_action"] == "blocked"
        assert result["current_result"].status == "blocked"
        assert result["errors"][0]["node"] == "solve_question"

    def test_other_node_exception_only_records_error(self):
        from scr.math_modeling_agent.graph import _logged_node

        @_logged_node("write_paper")
        def _boom(state):
            raise RuntimeError("模拟写作崩溃")

        result = _boom({"current_question_id": "", "run_id": "test"})
        assert result["errors"][0]["node"] == "write_paper"
        assert "_gq_action" not in result

    def test_degrade_never_raises(self):
        from scr.math_modeling_agent.graph import _degrade_node_failure

        # 任意异常类型都不会让降级函数自身抛错
        out = _degrade_node_failure("any_node", "q9", ValueError("任意错误"))
        assert isinstance(out, dict)
        assert out["errors"]
