"""逐问闭环工作流单元测试。

对应 plan.md Phase 2 测试要求：
  - 两问递进题中，Q2 能读取 Q1 的可复用结论
  - Q2 不会接收到 Q1 的无关中间记录
  - Q2 验证失败时，Q1 的结果包与产物不变
  - 无依赖问题可被标识为可并行，但 MVP 默认仍按顺序执行
"""
from __future__ import annotations

import pytest

from scr.schemas.context import DataProfile, ProjectContext, QuestionInfo, FieldProfile, TableProfile
from scr.schemas.question import (
    CurrentQuestionContext,
    ProblemInterpretation,
    QuestionResult,
    ReusableSummary,
)
from scr.schemas.evidence import DecisionLog
from scr.workflow.question_loop import (
    assemble_context,
    archive_result,
    select_question,
    route_after_select,
    _selective_inherit,
    _is_dependency_satisfied,
    _build_data_quality_summary,
    create_stub_result,
)


# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------


def _make_question(qid: str, objective: str, deps: list[str] | None = None) -> QuestionInfo:
    """创建测试用 QuestionInfo。"""
    return QuestionInfo(
        question_id=qid,
        original_text=f"问题 {qid}: {objective}",
        objective=objective,
        expected_output="结果表",
        question_type="optimization",
        required_data=["data.csv"],
        depends_on=deps or [],
        status="pending",
    )


def _make_project_context(questions: list[QuestionInfo], deps: dict[str, list[str]] | None = None) -> ProjectContext:
    """创建测试用 ProjectContext。"""
    return ProjectContext(
        run_id="test001",
        problem_text="测试题目",
        background_summary="测试背景",
        objectives=[q.objective for q in questions],
        constraints=["约束1", "约束2"],
        terminology={},
        questions=questions,
        question_dependencies=deps or {q.question_id: q.depends_on for q in questions},
        question_data_map={q.question_id: q.required_data for q in questions},
    )


def _make_validated_result(qid: str, conclusions: list[str] | None = None) -> QuestionResult:
    """创建已验证的 QuestionResult。"""
    return QuestionResult(
        question_id=qid,
        status="validated",
        problem_interpretation=ProblemInterpretation(
            question_id=qid,
            math_task="optimization",
            result_form="最优方案表",
        ),
        findings={"summary": f"{qid} 求解完成"},
        reusable_summary=ReusableSummary(
            question_id=qid,
            verified_conclusions=conclusions or [f"{qid} 的结论"],
            limitations=["测试限制"],
        ),
        limitations=["测试限制"],
    )


# ---------------------------------------------------------------------------
# select_question 测试
# ---------------------------------------------------------------------------


class TestSelectQuestion:
    """select_question 节点测试。"""

    def test_select_first_question_no_deps(self):
        """无依赖的第一个小问应被优先选中。"""
        questions = [
            _make_question("q1", "建立评价模型"),
            _make_question("q2", "预测趋势", deps=["q1"]),
        ]
        state = {
            "project_context": _make_project_context(questions),
            "question_results": {},
        }

        result = select_question(state)
        assert result["current_question_id"] == "q1"
        assert result["workflow_status"] == "solving"

    def test_select_next_after_first_validated(self):
        """Q1 验证通过后，Q2 应被选中。"""
        questions = [
            _make_question("q1", "建立评价模型"),
            _make_question("q2", "预测趋势", deps=["q1"]),
        ]
        state = {
            "project_context": _make_project_context(questions),
            "question_results": {"q1": _make_validated_result("q1")},
        }

        result = select_question(state)
        assert result["current_question_id"] == "q2"

    def test_select_skips_blocked_dependency(self):
        """Q1 被阻塞后，Q2 仍可被选中（blocked 也算完成）。"""
        questions = [
            _make_question("q1", "建立评价模型"),
            _make_question("q2", "预测趋势", deps=["q1"]),
        ]
        blocked_result = _make_validated_result("q1")
        blocked_result.status = "blocked"
        blocked_result.error_message = "测试阻塞"

        state = {
            "project_context": _make_project_context(questions),
            "question_results": {"q1": blocked_result},
        }

        result = select_question(state)
        assert result["current_question_id"] == "q2"

    def test_select_returns_empty_when_all_done(self):
        """所有小问完成后应返回空。"""
        questions = [
            _make_question("q1", "建立评价模型"),
            _make_question("q2", "预测趋势", deps=["q1"]),
        ]
        state = {
            "project_context": _make_project_context(questions),
            "question_results": {
                "q1": _make_validated_result("q1"),
                "q2": _make_validated_result("q2"),
            },
        }

        result = select_question(state)
        assert result["current_question_id"] == ""
        assert result["workflow_status"] == "all_questions_done"

    def test_select_waits_for_dependency(self):
        """Q2 依赖 Q1，Q1 未完成时 Q2 不应被选中。"""
        questions = [
            _make_question("q1", "建立评价模型"),
            _make_question("q2", "预测趋势", deps=["q1"]),
            _make_question("q3", "优化方案", deps=["q1"]),
        ]
        # q1 还没完成，q2 和 q3 都依赖 q1
        state = {
            "project_context": _make_project_context(questions),
            "question_results": {},
        }

        result = select_question(state)
        assert result["current_question_id"] == "q1"

    def test_route_after_select_has_next(self):
        """有下一个小问时路由到 has_next。"""
        state = {"current_question_id": "q1"}
        assert route_after_select(state) == "has_next"

    def test_route_after_select_done(self):
        """没有下一个小问时路由到 done。"""
        state = {"current_question_id": ""}
        assert route_after_select(state) == "done"


# ---------------------------------------------------------------------------
# assemble_context 测试
# ---------------------------------------------------------------------------


class TestAssembleContext:
    """assemble_context 节点测试。"""

    def test_assemble_basic_context(self):
        """基本上下文装配。"""
        questions = [_make_question("q1", "建立评价模型")]
        state = {
            "project_context": _make_project_context(questions),
            "data_profile": DataProfile(),
            "question_results": {},
            "current_question_id": "q1",
        }

        result = assemble_context(state)
        ctx = result["current_context"]
        assert ctx.question_id == "q1"
        assert ctx.question_text == "问题 q1: 建立评价模型"
        assert ctx.objective == "建立评价模型"
        assert ctx.global_background == "测试背景"
        assert ctx.global_constraints == ["约束1", "约束2"]

    def test_assemble_with_inherited_summary(self):
        """Q2 能读取 Q1 的可复用结论。"""
        questions = [
            _make_question("q1", "建立评价模型"),
            _make_question("q2", "预测趋势", deps=["q1"]),
        ]
        state = {
            "project_context": _make_project_context(questions),
            "data_profile": DataProfile(),
            "question_results": {"q1": _make_validated_result("q1", ["Q1权重结果"])},
            "current_question_id": "q2",
        }

        result = assemble_context(state)
        ctx = result["current_context"]
        assert len(ctx.inherited_summaries) == 1
        assert ctx.inherited_summaries[0]["question_id"] == "q1"
        assert "Q1权重结果" in ctx.inherited_summaries[0]["verified_conclusions"]

    def test_assemble_no_irrelevant_data(self):
        """Q2 不会接收到 Q1 的无关中间记录。"""
        q1_result = _make_validated_result("q1")
        # 添加一些"中间记录"（不应被继承）
        q1_result.findings["intermediate_steps"] = "这是很长的中间推理过程..."
        q1_result.findings["failed_attempts"] = ["尝试1失败", "尝试2失败"]
        q1_result.computation = {"raw_data": "大量原始数据..."}

        questions = [
            _make_question("q1", "建立评价模型"),
            _make_question("q2", "预测趋势", deps=["q1"]),
        ]
        state = {
            "project_context": _make_project_context(questions),
            "data_profile": DataProfile(),
            "question_results": {"q1": q1_result},
            "current_question_id": "q2",
        }

        result = assemble_context(state)
        ctx = result["current_context"]
        # 只应该有 reusable_summary 的内容，不应有 findings/computation
        assert len(ctx.inherited_summaries) == 1
        summary = ctx.inherited_summaries[0]
        assert "verified_conclusions" in summary
        assert "intermediate_steps" not in summary
        assert "failed_attempts" not in summary
        assert "raw_data" not in summary

    def test_assemble_data_quality_summary(self):
        """数据质量摘要包含关键信息。"""
        from scr.schemas.context import FileRecord
        questions = [_make_question("q1", "建立评价模型")]
        data_profile = DataProfile(
            files=[FileRecord(file_name="data.csv", file_path="/tmp/data.csv", file_type="csv", file_size=100, read_status="success")],
            tables=[TableProfile(source_file="data.csv", sheet_name="", n_rows=100, n_cols=5, field_names=["a","b","c","d","e"])],
            fields=[FieldProfile(source_file="data.csv", field_name="date", dtype="datetime", missing_rate=0.0, unique_count=100, is_time_column=True)],
        )
        state = {
            "project_context": _make_project_context(questions),
            "data_profile": data_profile,
            "question_results": {},
            "current_question_id": "q1",
        }

        result = assemble_context(state)
        ctx = result["current_context"]
        assert "100 行" in ctx.data_quality_summary
        assert "时间列" in ctx.data_quality_summary


# ---------------------------------------------------------------------------
# archive_result 测试
# ---------------------------------------------------------------------------


class TestArchiveResult:
    """archive_result 节点测试。"""

    def test_archive_validated_result(self):
        """验证通过的结果正确归档。"""
        state = {
            "current_question_id": "q1",
            "current_result": _make_validated_result("q1"),
            "question_results": {},
            "decision_log": DecisionLog(),
        }

        result = archive_result(state)
        assert "q1" in result["question_results"]
        assert result["question_results"]["q1"].status == "validated"
        # 清理当前状态
        assert result["current_question_id"] == ""
        assert result["current_result"] is None
        assert result["_solve_retry_count"] == 0

    def test_archive_blocked_result(self):
        """被阻塞的结果正确归档。"""
        blocked = _make_validated_result("q1")
        blocked.status = "blocked"
        blocked.error_message = "求解失败"

        state = {
            "current_question_id": "q1",
            "current_result": blocked,
            "question_results": {},
            "decision_log": DecisionLog(),
        }

        result = archive_result(state)
        assert result["question_results"]["q1"].status == "blocked"

    def test_archive_does_not_affect_existing_results(self):
        """Q2 验证失败时，Q1 的结果包不变。"""
        q1_result = _make_validated_result("q1")
        q2_blocked = _make_validated_result("q2")
        q2_blocked.status = "blocked"
        q2_blocked.error_message = "Q2 失败"

        state = {
            "current_question_id": "q2",
            "current_result": q2_blocked,
            "question_results": {"q1": q1_result},
            "decision_log": DecisionLog(),
        }

        result = archive_result(state)
        # Q1 结果不变
        assert result["question_results"]["q1"].status == "validated"
        assert result["question_results"]["q1"].findings["summary"] == "q1 求解完成"
        # Q2 也被归档
        assert result["question_results"]["q2"].status == "blocked"

    def test_archive_logs_decision(self):
        """归档时记录决策日志。"""
        state = {
            "current_question_id": "q1",
            "current_result": _make_validated_result("q1"),
            "question_results": {},
            "decision_log": DecisionLog(),
        }

        result = archive_result(state)
        dl = result["decision_log"]
        assert len(dl.entries) > 0
        assert dl.entries[-1].question_id == "q1"


# ---------------------------------------------------------------------------
# 辅助函数测试
# ---------------------------------------------------------------------------


class TestSelectiveInherit:
    """选择性继承逻辑测试。"""

    def test_inherit_from_validated(self):
        """从已验证的依赖中继承。"""
        results = {"q1": _make_validated_result("q1", ["结论A"])}
        summaries = _selective_inherit(["q1"], results)
        assert len(summaries) == 1
        assert summaries[0]["question_id"] == "q1"
        assert "结论A" in summaries[0]["verified_conclusions"]

    def test_no_inherit_from_pending(self):
        """不从未完成的依赖中继承。"""
        pending = _make_validated_result("q1")
        pending.status = "pending"
        results = {"q1": pending}
        summaries = _selective_inherit(["q1"], results)
        assert len(summaries) == 0

    def test_inherit_error_from_blocked(self):
        """从被阻塞的依赖中继承错误信息。"""
        blocked = _make_validated_result("q1")
        blocked.status = "blocked"
        blocked.error_message = "Q1 失败"
        results = {"q1": blocked}
        summaries = _selective_inherit(["q1"], results)
        assert len(summaries) == 1
        assert summaries[0]["status"] == "blocked"
        assert "Q1 失败" in summaries[0]["error"]

    def test_no_inherit_from_non_dependency(self):
        """不继承非依赖的小问。"""
        results = {
            "q1": _make_validated_result("q1", ["Q1结论"]),
            "q2": _make_validated_result("q2", ["Q2结论"]),
        }
        # q3 只依赖 q1，不应继承 q2
        summaries = _selective_inherit(["q1"], results)
        assert len(summaries) == 1
        assert summaries[0]["question_id"] == "q1"

    def test_dependency_satisfied(self):
        """依赖满足检查。"""
        results = {"q1": _make_validated_result("q1")}
        assert _is_dependency_satisfied("q1", results) is True
        assert _is_dependency_satisfied("q2", results) is False

    def test_dependency_satisfied_blocked(self):
        """被阻塞的依赖也算满足。"""
        blocked = _make_validated_result("q1")
        blocked.status = "blocked"
        results = {"q1": blocked}
        assert _is_dependency_satisfied("q1", results) is True


# ---------------------------------------------------------------------------
# create_stub_result 测试
# ---------------------------------------------------------------------------


class TestCreateStubResult:
    """stub 结果创建测试。"""

    def test_stub_result_structure(self):
        """stub 结果结构完整。"""
        result = create_stub_result("q1")
        assert result.question_id == "q1"
        assert result.status == "validating"
        assert result.problem_interpretation is not None
        assert result.reusable_summary is not None
        assert len(result.limitations) > 0
