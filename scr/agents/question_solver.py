"""小问求解器 Agent（Phase 4 实现）。

对应 architecture.md §5.2-5.5 和 plan.md Phase 2-4。

当前实现职责：
  1. 读取 CurrentQuestionContext
  2. 生成 ProblemInterpretation（问题澄清，§5.2）
  3. 调用 MethodExplorer 进行方法探索与决策（§5.3-5.4）
  4. 调用 ModelBuilder 执行建模计算与可视化（§5.5）
  5. 生成结构完整的 QuestionResult（status="validating"）
  6. 生成 ReusableSummary（供后续小问继承）

Phase 5+ 将替换为：
  - 题型验证与结果沉淀（§5.6-5.7）
"""
from __future__ import annotations

import json
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..runtime.logging import get_run_logger, log_step
from ..schemas.context import DataProfile
from ..schemas.question import (
    CurrentQuestionContext,
    ProblemInterpretation,
    QuestionResult,
    ReusableSummary,
)
from .base import BaseAgent
from .method_explorer import MethodExplorer
from .model_builder import ModelBuilder


class _SelfReview(BaseModel):
    """LLM 结果自评输出（P2-C1：反思循环）。"""
    verdict: Literal["pass", "revise"] = "pass"
    review: str = ""
    suggestions: str = ""


class QuestionSolver(BaseAgent):
    """小问求解器 Agent。

    Phase 4 集成了方法探索、决策和建模计算。
    Phase 5+ 将集成题型验证。

    Args:
        llm: 可选的 LLM 客户端。
        search_tool: 可选的联网搜索工具（TavilySearchTool）。
                     若不传则 MethodExplorer 自动从环境变量创建。
    """

    def __init__(
        self,
        llm: Any | None = None,
        search_tool: Any | None = None,
    ) -> None:
        super().__init__(llm=llm)
        self._explorer = MethodExplorer(llm=llm, search_tool=search_tool)
        self._builder = ModelBuilder(llm=llm)

    def solve(
        self,
        context: CurrentQuestionContext,
        data_profile: DataProfile | None = None,
        output_dir: str | None = None,
    ) -> QuestionResult:
        """求解当前小问。

        Args:
            context: 当前小问的上下文包。
            data_profile: 数据画像（供方法探索器硬过滤和建模数据准备）。
            output_dir: 产物目录（LLM 生成的解题代码将保存到其 questions/<qid>/ 下）。

        Returns:
            status="validating" 的 QuestionResult。
        """
        qid = context.question_id
        logger = get_run_logger()

        # 步骤 1: 问题澄清（§5.2）
        t0 = time.monotonic()
        log_step(logger, "solve.interpret", "started", question_id=qid)
        interpretation = self._interpret_problem(context)
        log_step(
            logger,
            "solve.interpret",
            "completed",
            question_id=qid,
            duration=time.monotonic() - t0,
            detail=f"任务类型: {interpretation.math_task}",
        )

        # 步骤 2: 方法探索与决策（§5.3-5.4）
        t0 = time.monotonic()
        log_step(logger, "solve.explore", "started", question_id=qid)
        method_candidates, decision_record = self._explorer.explore_and_decide(
            context, interpretation, data_profile
        )
        selected_method = decision_record.get("selected_method", "未知方法")
        log_step(
            logger,
            "solve.explore",
            "completed",
            question_id=qid,
            duration=time.monotonic() - t0,
            detail=(
                f"候选 {len(method_candidates)} 个，决策: {selected_method}"
            ),
        )

        # 步骤 3: 建模计算与可视化（§5.5）
        t0 = time.monotonic()
        log_step(logger, "solve.build", "started", question_id=qid)
        model_output = self._builder.build(
            context, interpretation, decision_record, data_profile,
            output_dir=output_dir,
        )
        comp_status = model_output["computation"].get("status", "unknown")
        log_step(
            logger,
            "solve.build",
            "completed",
            question_id=qid,
            duration=time.monotonic() - t0,
            detail=(
                f"计算状态: {comp_status}，"
                f"图表 {len(model_output.get('figures', []))} 张，"
                f"表格 {len(model_output.get('tables', []))} 张"
            ),
        )

        # 步骤 3.5: LLM 自评反思（P2-C1）—— revise 时带建议重算一次
        self_review = self._self_review(context, interpretation, model_output)
        if self_review and self_review.get("verdict") == "revise":
            suggestions = self_review.get("suggestions", "")
            print(f"[solver] 自评建议修订，重算小问 {qid}: {suggestions[:100]}")
            log_step(
                logger, "solve.self_review", "revise", question_id=qid,
                detail=f"按自评建议重算: {suggestions[:120]}",
            )
            t1 = time.monotonic()
            model_output = self._builder.build(
                context, interpretation, decision_record, data_profile,
                output_dir=output_dir,
                feedback=suggestions,
            )
            log_step(
                logger, "solve.build", "completed", question_id=qid,
                duration=time.monotonic() - t1,
                detail="自评修订后的重算完成",
            )
        model_output["self_review"] = self_review
        comp_status = model_output["computation"].get("status", "unknown")

        # 步骤 4: 提取假设
        assumptions = decision_record.get("assumptions", [])

        # 步骤 5: 生成可复用摘要（包含实际计算结果）
        t0 = time.monotonic()
        reusable_summary = self._build_summary(
            qid, context, interpretation, decision_record, model_output
        )
        log_step(
            logger,
            "solve.summary",
            "completed",
            question_id=qid,
            duration=time.monotonic() - t0,
            detail=f"生成 {len(reusable_summary.verified_conclusions)} 条可复用结论",
        )

        # 步骤 6: 组装 QuestionResult
        computation = model_output["computation"]
        comp_status = computation.get("status", "unknown")

        # 构建发现摘要
        findings = self._build_findings(
            qid, interpretation, decision_record, model_output
        )
        if self_review:
            findings["self_review"] = self_review

        result = QuestionResult(
            question_id=qid,
            status="validating",
            problem_interpretation=interpretation,
            inherited_context={"inherited_summaries": context.inherited_summaries},
            method_candidates=method_candidates,
            decision_record=decision_record,
            assumptions=assumptions,
            formulation=model_output["formulation"],
            data_preparation=model_output["data_preparation"],
            computation=computation,
            validation={},         # Phase 5 填充
            findings=findings,
            figures=model_output["figures"],
            tables=model_output["tables"],
            reusable_summary=reusable_summary,
            limitations=self._build_limitations(
                decision_record, interpretation, model_output
            ),
        )

        print(f"[solver] 小问 {qid} 求解完成 "
              f"(task={interpretation.math_task}, method={selected_method}, "
              f"computation={comp_status})")
        log_step(
            logger,
            "solve",
            "completed",
            question_id=qid,
            detail=(
                f"小问求解完成: task={interpretation.math_task}, "
                f"method={selected_method}, computation={comp_status}"
            ),
        )
        return result

    def _build_findings(
        self,
        qid: str,
        interpretation: ProblemInterpretation,
        decision_record: dict,
        model_output: dict,
    ) -> dict:
        """构建 findings 字段，包含实际计算结果摘要。"""
        selected_method = decision_record.get("selected_method", "未知方法")
        computation = model_output["computation"]
        comp_status = computation.get("status", "unknown")
        results = computation.get("results", {})
        metrics = computation.get("metrics", {})

        findings = {
            "summary": f"小问 {qid} 建模完成: {selected_method} (状态: {comp_status})",
            "math_task": interpretation.math_task,
            "result_form": interpretation.result_form,
            "selected_method": selected_method,
            "selected_family": decision_record.get("selected_family", ""),
            "alternatives_count": len(decision_record.get("alternatives", [])),
            "validation_method": decision_record.get("validation_method", ""),
            "computation_status": comp_status,
            "has_numerical_results": bool(results) and comp_status == "success",
            "figures_count": len(model_output.get("figures", [])),
            "tables_count": len(model_output.get("tables", [])),
        }

        # 提取关键数值
        if comp_status == "success":
            if "weights" in results:
                findings["key_result"] = f"权重: {results['weights']}"
            elif "closeness" in results:
                findings["key_result"] = f"相对接近度: {results['closeness']}"
            elif "coefficients" in results:
                findings["key_result"] = f"回归系数: {results['coefficients']}"
            elif "predicted_future" in results:
                findings["key_result"] = f"预测值: {results['predicted_future']}"
            elif "expected_objective" in results:
                findings["key_result"] = (
                    f"期望目标值: {results.get('expected_objective', 0):.4f}, "
                    f"最坏情况: {results.get('worst_case_objective', 0):.4f}"
                )
            elif "optimal_objective" in results:
                findings["key_result"] = f"最优目标值: {results['optimal_objective']}"
            elif "data_summary" in results:
                findings["key_result"] = "描述统计完成"
            else:
                findings["key_result"] = "计算成功"

            # 记录关键指标
            if metrics:
                findings["key_metrics"] = {
                    k: round(v, 4) if isinstance(v, float) else v
                    for k, v in list(metrics.items())[:5]
                }

        return findings

    def _interpret_problem(
        self,
        context: CurrentQuestionContext,
    ) -> ProblemInterpretation:
        """问题澄清（architecture.md §5.2）。

        优先用 LLM 深度理解生成（决策变量/目标/约束/假设/结果形式）；
        无 LLM 或调用失败时回退到启发式关键词判断。
        """
        llm_interpretation = self._interpret_problem_llm(context)
        if llm_interpretation is not None:
            return llm_interpretation

        # ---- 启发式回退（原有逻辑）----
        qid = context.question_id

        # 启发式判断数学任务类型
        math_task = self._guess_math_task(context)

        # 推断结果形式
        result_form = self._guess_result_form(context, math_task)

        # 可用数据
        available_data = context.required_data[:]

        # 与前问的关系
        relation = "independent"
        relation_desc = ""
        if context.inherited_summaries:
            relation = "inherit"
            dep_ids = [s.get("question_id", "?") for s in context.inherited_summaries]
            relation_desc = f"继承前问 {', '.join(dep_ids)} 的可复用结论"

        return ProblemInterpretation(
            question_id=qid,
            math_task=math_task,
            math_task_description=context.objective[:200] if context.objective else "目标待明确",
            decision_variables=[],  # Phase 4+ 填充
            objective_function="",  # Phase 4+ 填充
            constraints=context.global_constraints[:3],  # 取前 3 条约束
            evaluation_metrics=[],  # Phase 4+ 填充
            result_form=result_form,
            available_data=available_data,
            missing_data=[],  # Phase 4+ 填充
            necessary_assumptions=[],  # Phase 4+ 填充
            acceptable_simplifications=[],  # Phase 4+ 填充
            relation_to_previous=relation,
            relation_description=relation_desc,
        )

    def _self_review(
        self,
        context: CurrentQuestionContext,
        interpretation: ProblemInterpretation,
        model_output: dict,
    ) -> dict | None:
        """LLM 对求解结果做自评反思（P2-C1）。

        判断结果是否回答了题目、数值是否合理；verdict=revise 时由调用方
        携带建议重算一次。失败或无 LLM 时返回 None（跳过反思，不阻塞）。
        """
        if self._llm is None:
            return None
        computation = model_output.get("computation", {})
        results = computation.get("results", {}) or {}
        metrics = computation.get("metrics", {}) or {}
        try:
            prompt = self._render_prompt(
                self._load_prompt("self_review"),
                question_text=context.question_text,
                math_task=interpretation.math_task,
                math_task_description=interpretation.math_task_description,
                decision_variables=interpretation.decision_variables,
                objective_function=interpretation.objective_function,
                constraints=interpretation.constraints,
                status=computation.get("status", "unknown"),
                results=json.dumps(results, ensure_ascii=False, default=str)[:1000],
                metrics=json.dumps(metrics, ensure_ascii=False, default=str)[:500],
            )
            review = self._call_structured(_SelfReview, prompt)
            result: dict = {
                "verdict": review.verdict,
                "review": review.review,
                "suggestions": review.suggestions,
            }
            log_step(
                get_run_logger(), "solve.self_review", "completed",
                question_id=context.question_id,
                detail=f"verdict={review.verdict}: {review.review[:100]}",
            )
            return result
        except Exception as e:
            print(f"[solver] 自评失败（不影响结果）: {e}")
            return None

    def _interpret_problem_llm(
        self, context: CurrentQuestionContext
    ) -> ProblemInterpretation | None:
        """用 LLM 生成问题澄清（ProblemInterpretation）。

        Returns:
            LLM 生成的问题澄清；无 LLM 或调用失败时返回 None（回退启发式）。
        """
        if self._llm is None:
            return None
        try:
            inherited = json.dumps(
                context.inherited_summaries, ensure_ascii=False
            )[:1500]
            prompt = self._render_prompt(
                self._load_prompt("problem_clarification"),
                question_text=context.question_text,
                objective=context.objective,
                global_background=context.global_background,
                global_constraints=context.global_constraints,
                available_data=context.required_data,
                data_quality_summary=context.data_quality_summary,
                inherited_summaries=inherited,
            )
            interp = self._call_structured(ProblemInterpretation, prompt)
            interp.question_id = context.question_id
            log_step(
                get_run_logger(),
                "solve.interpret.llm",
                "completed",
                question_id=context.question_id,
                detail=(
                    f"LLM 问题澄清: task={interp.math_task}, "
                    f"变量 {len(interp.decision_variables)} 个, "
                    f"约束 {len(interp.constraints)} 条, "
                    f"假设 {len(interp.necessary_assumptions)} 条"
                ),
            )
            return interp
        except Exception as e:
            print(f"[solver] LLM 问题澄清失败，回退启发式: {e}")
            return None

    def _guess_math_task(self, context: CurrentQuestionContext) -> str:
        """启发式判断数学任务类型。

        基于题目文本关键词判断：
          - 评价/排序/评估 → evaluation
          - 预测/趋势/预报 → prediction
          - 模拟/仿真（含"通过模拟数据求解"等明确指示）→ simulation
          - 不确定性/随机/鲁棒 → stochastic_optimization（优先于普通 optimization）
          - 优化/最优/策略/规划 → optimization
          - 分类/聚类 → classification/clustering
          - 默认 → composite

        注意：
          - simulation 在 optimization 之前检查，因为"通过模拟数据求解"
            是比"最优策略"更明确的任务指示。
          - stochastic_optimization 在 optimization 之前检查，因为"不确定性"
            是比"最优"更具体的任务指示，需要不同的方法族。
        """
        text = (context.question_text + " " + context.objective).lower()
        original = (context.question_text + " " + context.objective)

        # 评价类：排序、评估、综合评价
        if any(kw in text for kw in ["评价", "排序", "评估", "综合评", "排名", "evaluate", "rank"]):
            return "evaluation"

        # 预测类：预测、趋势、预报
        if any(kw in text for kw in ["预测", "趋势", "预报", "predict", "forecast"]):
            return "prediction"

        # 仿真类：明确要求"模拟数据""仿真"等（优先于优化判断）
        # 因为"通过模拟数据进行求解"是比"最优策略"更具体的任务指示
        sim_keywords = ["模拟数据", "仿真", "蒙特卡洛", "simulate", "simulation", "monte carlo"]
        if any(kw in original for kw in sim_keywords):
            return "simulation"
        # "模拟" + "求解" 的组合也算仿真
        if "模拟" in original and ("求解" in original or "分析" in original):
            return "simulation"

        # 随机/鲁棒优化类：含不确定性关键词（优先于普通 optimization）
        # 因为"考虑不确定性"需要随机规划或鲁棒优化，而非确定性线性规划
        stochastic_keywords = [
            "不确定性", "随机规划", "鲁棒优化", "鲁棒", "概率分布",
            "随机变量", "概率约束", "场景规划", "stochastic", "robust",
            "uncertain", "不确定性", "潜在风险", "波动", "随机波动",
        ]
        # 同时检查"最优"/"策略"/"规划" + 不确定性关键词的组合
        has_optimization_intent = any(
            kw in text for kw in ["优化", "最优", "策略", "规划", "optimize", "optimal", "strategy", "plan"]
        )
        has_uncertainty = any(kw in original for kw in stochastic_keywords)
        if has_optimization_intent and has_uncertainty:
            return "stochastic_optimization"

        # 优化类：最优、优化、策略、规划
        if any(kw in text for kw in ["优化", "最优", "策略", "规划", "optimize", "optimal", "strategy", "plan"]):
            return "optimization"

        # 分类/聚类
        if any(kw in text for kw in ["分类", "聚类", "classify", "cluster"]):
            return "classification"

        # 默认复合类型
        return "composite"

    def _guess_result_form(
        self,
        context: CurrentQuestionContext,
        math_task: str,
    ) -> str:
        """根据数学任务类型推断结果形式。"""
        forms = {
            "evaluation": "评价排名表",
            "prediction": "预测值与误差表",
            "optimization": "最优方案表",
            "stochastic_optimization": "鲁棒最优方案表",
            "classification": "分类结果表",
            "clustering": "聚类标签表",
            "simulation": "仿真结果统计表",
            "mechanism": "机理模型与参数",
            "composite": "综合结果表",
        }
        return forms.get(math_task, "结果表")

    def _build_summary(
        self,
        qid: str,
        context: CurrentQuestionContext,
        interpretation: ProblemInterpretation,
        decision_record: dict,
        model_output: dict,
    ) -> ReusableSummary:
        """构建可复用摘要（Phase 4 版本）。

        包含选中方法信息和实际计算结果，供后续小问参考。
        """
        selected_method = decision_record.get("selected_method", "未知")
        computation = model_output.get("computation", {})
        comp_status = computation.get("status", "unknown")
        results = computation.get("results", {})
        metrics = computation.get("metrics", {})

        conclusions = [
            f"小问 {qid} 的数学任务类型: {interpretation.math_task}",
            f"选用方法: {selected_method}",
            f"方法家族: {decision_record.get('selected_family', '未知')}",
            f"计算状态: {comp_status}",
        ]

        # 提取关键数值结论
        if comp_status == "success":
            if "weights" in results:
                weights_str = ", ".join(
                    f"{model_output.get('data_preparation', {}).get('feature_names', ['x'])[i] if i < len(model_output.get('data_preparation', {}).get('feature_names', [])) else f'x{i}'}={w:.4f}"
                    for i, w in enumerate(results["weights"][:5])
                )
                conclusions.append(f"指标权重: {weights_str}")
            if "ranking" in results:
                conclusions.append(f"排名: {results['ranking'][:5]}")
            if "r_squared" in metrics:
                conclusions.append(f"R² = {metrics['r_squared']:.4f}")
            if "predicted_future" in results:
                conclusions.append(f"预测值: {results['predicted_future']}")
            if "development_coefficient_a" in results:
                conclusions.append(f"发展系数 a = {results['development_coefficient_a']:.6f}")
            if "expected_objective" in results:
                conclusions.append(f"期望目标值 = {results['expected_objective']:.4f}")
            if "worst_case_objective" in results:
                conclusions.append(f"最坏情况目标值 = {results['worst_case_objective']:.4f}")
            if "robustness_ratio" in metrics:
                conclusions.append(f"鲁棒性比率 = {metrics['robustness_ratio']:.4f}")
            if "optimal_objective" in results and "expected_objective" not in results:
                conclusions.append(f"最优目标值 = {results['optimal_objective']:.4f}")

        # 如果继承了前问结论，也记录到可复用摘要
        if context.inherited_summaries:
            for s in context.inherited_summaries:
                if s.get("status") == "validated":
                    prev_conclusions = s.get("verified_conclusions", [])
                    conclusions.extend(prev_conclusions[:2])  # 只取前 2 条

        # 提取关键参数
        key_params: dict[str, float | str] = {}
        if metrics:
            for k, v in list(metrics.items())[:4]:
                if isinstance(v, (int, float)):
                    key_params[k] = round(float(v), 6)
                else:
                    key_params[k] = str(v)

        # 可复用数据集
        reusable_datasets = []
        data_prep = model_output.get("data_preparation", {})
        if data_prep.get("data_source"):
            reusable_datasets.append(data_prep["data_source"])

        return ReusableSummary(
            question_id=qid,
            verified_conclusions=conclusions,
            reusable_datasets=reusable_datasets,
            model_interface=f"{selected_method}_{interpretation.math_task}",
            key_parameters=key_params,
            limitations=self._build_limitations(decision_record, interpretation, model_output),
            improvement_directions=[
                "Phase 5: 完成题型验证与结果沉淀",
                "Phase 6: 整合到论文写作",
            ],
        )

    def _build_limitations(
        self,
        decision_record: dict,
        interpretation: ProblemInterpretation,
        model_output: dict | None = None,
    ) -> list[str]:
        """构建局限列表（Phase 4 版本，包含实际计算状态）。"""
        limitations: list[str] = []
        computation = {}
        if model_output:
            computation = model_output.get("computation", {})

        comp_status = computation.get("status", "unknown")

        if comp_status == "success":
            limitations.append("数值结果已由确定性代码生成，可复现")
        elif comp_status == "no_data":
            limitations.append("⚠ 无可用数据，计算未执行，结果为占位")
        elif comp_status == "insufficient_data":
            limitations.append("⚠ 数据不足，无法完成完整计算")
        elif comp_status == "error":
            limitations.append(f"⚠ 计算错误: {computation.get('error', '未知错误')[:100]}")
        elif comp_status == "stub":
            limitations.append("⚠ 当前方法为占位实现，需要具体问题建模")
        else:
            limitations.append("计算状态未知")

        # 验证待完成
        limitations.append("题型验证待 Phase 5 完成")

        # 添加方法局限
        selected_details = decision_record.get("selected_details", {})
        for con in selected_details.get("cons", [])[:2]:
            limitations.append(f"方法局限: {con}")

        # 降级标记
        if selected_details.get("degraded"):
            limitations.append("⚠ 降级选择：数据不完全满足方法要求")

        return limitations


# ---------------------------------------------------------------------------
# LangGraph 节点封装
# ---------------------------------------------------------------------------


def solve_question_node(state: dict) -> dict:
    """LangGraph 节点：小问求解。

    读取 current_context，调用 QuestionSolver，输出 current_result。

    Args:
        state: 项目状态。需要包含 current_context。

    Returns:
        状态更新字典，包含 current_result。
    """
    current_context: CurrentQuestionContext | None = state.get("current_context")
    data_profile: DataProfile | None = state.get("data_profile")
    llm = state.get("llm")
    output_dir = state.get("output_dir")
    retry_count = state.get("_solve_retry_count", 0)

    if current_context is None:
        return {
            "errors": [{"msg": "current_context missing in solve_question_node"}],
            "_gq_action": "blocked",
        }

    solver = QuestionSolver(llm=llm)

    # Phase 3：方法探索 + 决策，无论是否重试都重新探索
    # Phase 4+ 将根据 retry_count 选择不同的方法候选
    result = solver.solve(
        current_context, data_profile=data_profile, output_dir=output_dir
    )

    if retry_count > 0:
        result.retry_count = retry_count
        result.findings["retry_note"] = f"第 {retry_count} 次重试"

    return {"current_result": result}
