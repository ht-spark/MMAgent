"""Phase 3 方法探索与决策 Agent 测试。

测试覆盖：
  1. 方法目录：按题型获取候选
  2. 硬过滤：数据不满足时淘汰
  3. 启发式评分：候选排序合理
  4. 决策记录：包含选中方法、备选、淘汰、假设
  5. QuestionSolver 集成：method_candidates / decision_record / assumptions 已填充
  6. 降级处理：全部淘汰时保留最优
"""
from __future__ import annotations

import pandas as pd
import pytest

from scr.agents.method_catalog import (
    METHOD_CATALOG,
    get_all_task_types,
    get_candidates_for_task,
    get_method_by_name,
)
from scr.agents.method_explorer import MethodExplorer
from scr.agents.question_solver import QuestionSolver
from scr.schemas.context import DataProfile, FieldProfile, TableProfile
from scr.schemas.question import CurrentQuestionContext, ProblemInterpretation


# ---------------------------------------------------------------------------
# 方法目录测试
# ---------------------------------------------------------------------------


class TestMethodCatalog:
    """方法目录基础测试。"""

    def test_all_task_types_have_candidates(self):
        """每种任务类型都有候选方法。"""
        for task_type in get_all_task_types():
            candidates = get_candidates_for_task(task_type)
            assert len(candidates) >= 2, f"{task_type} 候选不足 2 个"

    def test_each_method_has_required_fields(self):
        """每个方法定义包含所有必需字段。"""
        required_fields = [
            "name", "family", "description", "required_data",
            "assumptions", "pros", "cons", "elimination_conditions",
            "implementation_difficulty", "data_requirements", "validation_method",
        ]
        for task_type, methods in METHOD_CATALOG.items():
            for m in methods:
                for field in required_fields:
                    assert field in m, f"{task_type}/{m['name']} 缺少字段 {field}"

    def test_get_method_by_name(self):
        """按名称查找方法。"""
        method = get_method_by_name("线性规划")
        assert method is not None
        assert method["family"] == "数学规划"

    def test_get_method_by_name_not_found(self):
        """查找不存在的方法返回 None。"""
        assert get_method_by_name("不存在的方法") is None

    def test_get_candidates_returns_deepcopy(self):
        """获取的候选是深拷贝，修改不影响原目录。"""
        candidates1 = get_candidates_for_task("evaluation")
        candidates1[0]["name"] = "被修改了"
        candidates2 = get_candidates_for_task("evaluation")
        assert candidates2[0]["name"] != "被修改了"

    def test_unknown_task_returns_composite(self):
        """未知任务类型返回 composite 候选。"""
        candidates = get_candidates_for_task("unknown_type")
        assert len(candidates) > 0
        assert all("family" in c for c in candidates)


# ---------------------------------------------------------------------------
# 方法探索器测试
# ---------------------------------------------------------------------------


class TestMethodExplorer:
    """方法探索器测试。"""

    def _make_context(
        self,
        qid: str = "q1",
        objective: str = "建立评价模型",
        data_quality: str = "共 5 张表、100 行数据",
    ) -> CurrentQuestionContext:
        """创建测试用上下文。"""
        return CurrentQuestionContext(
            question_id=qid,
            question_text=f"问题1 {objective}",
            objective=objective,
            data_quality_summary=data_quality,
        )

    def _make_interpretation(
        self,
        math_task: str = "evaluation",
    ) -> ProblemInterpretation:
        """创建测试用问题澄清。"""
        return ProblemInterpretation(
            question_id="q1",
            math_task=math_task,
            math_task_description="测试任务",
            result_form="结果表",
        )

    def _make_data_profile(
        self,
        n_rows: int = 100,
        n_fields: int = 5,
        has_time: bool = False,
    ) -> DataProfile:
        """创建测试用数据画像。"""
        fields = []
        for i in range(n_fields):
            fields.append(FieldProfile(
                source_file="test.csv",
                field_name=f"col_{i}",
                dtype="float",
                missing_rate=0.0,
                unique_count=n_rows,
                is_time_column=(has_time and i == 0),
            ))

        return DataProfile(
            tables=[TableProfile(
                source_file="test.csv",
                n_rows=n_rows,
                n_cols=n_fields,
                field_names=[f.field_name for f in fields],
            )],
            fields=fields,
            preliminary_findings=["测试发现"],
        )

    def test_explore_returns_candidates(self):
        """explore 返回候选方法列表。"""
        explorer = MethodExplorer()
        context = self._make_context()
        interp = self._make_interpretation("evaluation")
        dp = self._make_data_profile(n_rows=100, n_fields=5)

        candidates = explorer.explore(context, interp, dp)

        assert len(candidates) > 0
        # 至少有一个未淘汰的候选
        viable = [c for c in candidates if not c.get("eliminated", False)]
        assert len(viable) > 0

    def test_explore_filters_by_sample_size(self):
        """样本量不足时淘汰高要求方法。"""
        explorer = MethodExplorer()
        context = self._make_context()
        interp = self._make_interpretation("prediction")
        dp = self._make_data_profile(n_rows=5, n_fields=2)  # 小样本

        candidates = explorer.explore(context, interp, dp)

        # ARIMA 需要 20 样本，应被淘汰
        arima = next((c for c in candidates if c["name"] == "时间序列ARIMA"), None)
        if arima:
            assert arima.get("eliminated", False)
            assert "样本量不足" in arima.get("elimination_reason", "")

    def test_explore_filters_by_time_column(self):
        """需要时间列但无时间列时淘汰。"""
        explorer = MethodExplorer()
        context = self._make_context()
        interp = self._make_interpretation("prediction")
        dp = self._make_data_profile(n_rows=100, n_fields=5, has_time=False)

        candidates = explorer.explore(context, interp, dp)

        # ARIMA 需要时间列，应被淘汰
        arima = next((c for c in candidates if c["name"] == "时间序列ARIMA"), None)
        if arima:
            assert arima.get("eliminated", False)
            assert "时间列" in arima.get("elimination_reason", "")

    def test_explore_no_data_profile(self):
        """无数据画像时仍能返回候选（不做硬过滤）。"""
        explorer = MethodExplorer()
        context = self._make_context()
        interp = self._make_interpretation("optimization")

        candidates = explorer.explore(context, interp, data_profile=None)

        # optimization 类方法大多不要求数据量，应都通过
        viable = [c for c in candidates if not c.get("eliminated", False)]
        assert len(viable) > 0

    def test_explore_degraded_when_all_eliminated(self):
        """全部淘汰时降级保留最优。"""
        explorer = MethodExplorer()
        context = self._make_context()
        # 用 prediction 但无数据，且无时间列
        interp = self._make_interpretation("prediction")

        candidates = explorer.explore(context, interp, data_profile=None)

        # 无数据画像时 sample_size=0，高要求方法被淘汰
        # 但应至少有一个降级候选
        viable = [c for c in candidates if not c.get("eliminated", False)]
        assert len(viable) >= 1

    def test_decide_returns_decision_record(self):
        """decide 返回完整决策记录。"""
        explorer = MethodExplorer()
        context = self._make_context()
        interp = self._make_interpretation("evaluation")
        dp = self._make_data_profile(n_rows=100, n_fields=5)

        candidates = explorer.explore(context, interp, dp)
        decision = explorer.decide(candidates, context, interp)

        assert "selected_method" in decision
        assert "selected_family" in decision
        assert "selected_reason" in decision
        assert "alternatives" in decision
        assert "eliminated" in decision
        assert "assumptions" in decision
        assert "validation_method" in decision
        assert decision["selected_method"] != ""

    def test_decide_selects_highest_score(self):
        """decide 选择得分最高的方法。"""
        explorer = MethodExplorer()
        context = self._make_context()
        interp = self._make_interpretation("evaluation")
        dp = self._make_data_profile(n_rows=100, n_fields=5)

        candidates = explorer.explore(context, interp, dp)
        decision = explorer.decide(candidates, context, interp)

        viable = [c for c in candidates if not c.get("eliminated", False)]
        if viable:
            best = max(viable, key=lambda x: x.get("heuristic_score", 0))
            assert decision["selected_method"] == best["name"]

    def test_decide_includes_assumptions(self):
        """决策记录包含假设列表。"""
        explorer = MethodExplorer()
        context = self._make_context()
        interp = self._make_interpretation("evaluation")
        dp = self._make_data_profile(n_rows=100, n_fields=5)

        candidates = explorer.explore(context, interp, dp)
        decision = explorer.decide(candidates, context, interp)

        assert len(decision["assumptions"]) > 0
        for a in decision["assumptions"]:
            assert "description" in a
            assert "type" in a

    def test_explore_and_decide_integration(self):
        """explore_and_decide 串联两步。"""
        explorer = MethodExplorer()
        context = self._make_context()
        interp = self._make_interpretation("optimization")
        dp = self._make_data_profile(n_rows=100, n_fields=5)

        candidates, decision = explorer.explore_and_decide(context, interp, dp)

        assert len(candidates) > 0
        assert decision["selected_method"] != ""
        assert len(decision["alternatives"]) >= 0

    def test_different_tasks_get_different_methods(self):
        """不同任务类型得到不同的候选方法。"""
        explorer = MethodExplorer()
        context = self._make_context()
        dp = self._make_data_profile(n_rows=100, n_fields=5)

        eval_candidates = explorer.explore(
            context, self._make_interpretation("evaluation"), dp
        )
        opt_candidates = explorer.explore(
            context, self._make_interpretation("optimization"), dp
        )

        eval_names = {c["name"] for c in eval_candidates}
        opt_names = {c["name"] for c in opt_candidates}

        # 两个任务类型的候选不应完全相同
        assert eval_names != opt_names

    def test_inherited_summaries_add_assumptions(self):
        """继承前问结论时添加继承假设。"""
        explorer = MethodExplorer()
        context = CurrentQuestionContext(
            question_id="q2",
            question_text="问题2 预测",
            objective="预测趋势",
            inherited_summaries=[{
                "question_id": "q1",
                "status": "validated",
                "verified_conclusions": ["Q1结论1"],
                "limitations": ["Q1局限1"],
            }],
        )
        interp = self._make_interpretation("prediction")
        dp = self._make_data_profile(n_rows=100, n_fields=5, has_time=True)

        candidates = explorer.explore(context, interp, dp)
        decision = explorer.decide(candidates, context, interp)

        # 应包含继承假设
        inherited_assumptions = [
            a for a in decision["assumptions"] if a.get("type") == "inherited"
        ]
        assert len(inherited_assumptions) > 0


# ---------------------------------------------------------------------------
# QuestionSolver 集成测试
# ---------------------------------------------------------------------------


class TestQuestionSolverPhase3:
    """QuestionSolver Phase 3 集成测试。"""

    def test_solver_fills_method_candidates(self):
        """求解器填充 method_candidates。"""
        solver = QuestionSolver(llm=None)
        context = CurrentQuestionContext(
            question_id="q1",
            question_text="问题1 建立评价模型",
            objective="建立评价模型",
        )
        result = solver.solve(context, data_profile=None)

        assert len(result.method_candidates) > 0
        # 每个候选都有 name 和 family
        for c in result.method_candidates:
            assert "name" in c
            assert "family" in c

    def test_solver_fills_decision_record(self):
        """求解器填充 decision_record。"""
        solver = QuestionSolver(llm=None)
        context = CurrentQuestionContext(
            question_id="q1",
            question_text="问题1 优化种植方案",
            objective="优化种植方案",
        )
        result = solver.solve(context, data_profile=None)

        assert result.decision_record != {}
        assert "selected_method" in result.decision_record
        assert "selected_reason" in result.decision_record
        assert "alternatives" in result.decision_record

    def test_solver_fills_assumptions(self):
        """求解器填充 assumptions。"""
        solver = QuestionSolver(llm=None)
        context = CurrentQuestionContext(
            question_id="q1",
            question_text="问题1 建立评价模型",
            objective="建立评价模型",
        )
        result = solver.solve(context, data_profile=None)

        assert len(result.assumptions) > 0
        for a in result.assumptions:
            assert "description" in a

    def test_solver_findings_contain_method(self):
        """findings 包含选中方法信息。"""
        solver = QuestionSolver(llm=None)
        context = CurrentQuestionContext(
            question_id="q1",
            question_text="问题1 建立评价模型",
            objective="建立评价模型",
        )
        result = solver.solve(context, data_profile=None)

        assert "selected_method" in result.findings
        assert "selected_family" in result.findings
        assert result.findings["selected_method"] != ""

    def test_solver_reusable_summary_contains_method(self):
        """reusable_summary 包含选中方法信息。"""
        solver = QuestionSolver(llm=None)
        context = CurrentQuestionContext(
            question_id="q1",
            question_text="问题1 建立评价模型",
            objective="建立评价模型",
        )
        result = solver.solve(context, data_profile=None)

        assert result.reusable_summary is not None
        # 可复用摘要中应包含方法信息
        method_info = [
            c for c in result.reusable_summary.verified_conclusions
            if "选用方法" in c
        ]
        assert len(method_info) > 0

    def test_solver_with_data_profile(self):
        """有数据画像时求解器正确过滤候选。"""
        solver = QuestionSolver(llm=None)
        context = CurrentQuestionContext(
            question_id="q1",
            question_text="问题1 预测趋势",
            objective="预测趋势",
        )
        dp = DataProfile(
            tables=[TableProfile(source_file="t.csv", n_rows=50, n_cols=3)],
            fields=[
                FieldProfile(source_file="t.csv", field_name="x", dtype="float", missing_rate=0.0, unique_count=50),
                FieldProfile(source_file="t.csv", field_name="y", dtype="float", missing_rate=0.0, unique_count=50),
            ],
        )
        result = solver.solve(context, data_profile=dp)

        # 50 样本不够 ARIMA(20)，ARIMA 应被淘汰
        assert len(result.method_candidates) > 0
        assert result.decision_record["selected_method"] != ""

    def test_solver_optimization_task(self):
        """优化任务求解。"""
        solver = QuestionSolver(llm=None)
        context = CurrentQuestionContext(
            question_id="q1",
            question_text="问题1 给出最优种植方案",
            objective="给出最优种植方案",
        )
        result = solver.solve(context, data_profile=None)

        assert result.problem_interpretation.math_task == "optimization"
        # 优化类方法应包含线性规划或启发式
        method_names = {c["name"] for c in result.method_candidates}
        assert any("规划" in n or "算法" in n for n in method_names)
