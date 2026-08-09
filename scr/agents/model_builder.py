"""将建模决策转为可执行计算和可复现产物。

负责构建模型表述、准备数据、调用大模型生成或预设的求解代码、执行计算，
并返回数值结果、表格、图表和复现所需的代码/数据文件。
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from ..schemas.context import DataProfile
from ..schemas.formulation import MODELING_TASKS, ConstraintIR, FormulationIR, VariableIR
from ..schemas.question import CurrentQuestionContext, ProblemInterpretation

#: 任务驱动建模的题型范围（LLM 建模 + 代码执行）
from .code_modeler import CODE_BASED_TASKS

#: 代码生成/执行/校验的重试上限
CODE_GEN_MAX_RETRIES = 2


class ModelBuilder:
    """建模计算与可视化 Agent。

    Args:
        llm: 可选的 LLM 客户端（Phase 4 暂不使用，Phase 5+ 可用于模型精调）。
        budget_manager: 可选的预算管理器。提供时，"任务驱动建模"路径的代码
            生成/执行/校验重试会消耗 CODE_REPAIR；耗尽立即停止重试并返回 error。
    """

    def __init__(self, llm: Any | None = None, budget_manager: Any | None = None) -> None:
        self._llm = llm
        self._budget_manager = budget_manager

    def _consume_code_repair_or_stop(
        self,
        question_id: str,
        stage: str,
        last_error: str,
    ) -> bool:
        """消耗 1 次 CODE_REPAIR；预算耗尽返回 True，调用方应退出重试。

        用于 _execute_code_based 的 4 处 continue 路径；无 budget_manager 时
        直接返回 False（不限制，由 CODE_GEN_MAX_RETRIES 兜底）。
        """
        if self._budget_manager is None:
            return False
        try:
            from ..runtime.budget import BudgetType
            ok = self._budget_manager.consume(
                BudgetType.CODE_REPAIR, amount=1, question_id=question_id
            )
            if not ok:
                print(f"[builder] 预算：CODE_REPAIR 已耗尽（{stage}），停止重试")
                return True
            rem = self._budget_manager.remaining(
                BudgetType.CODE_REPAIR, question_id=question_id
            )
            print(
                f"[builder] 预算：CODE_REPAIR 消耗 1 次（{stage}），剩余 {rem}"
            )
        except Exception as e:
            print(f"[builder] CODE_REPAIR 预算记账跳过: {e}")
        return False

    def build(
        self,
        context: CurrentQuestionContext,
        interpretation: ProblemInterpretation,
        decision_record: dict,
        data_profile: DataProfile | None = None,
        output_dir: str | Path | None = None,
        feedback: str = "",
    ) -> dict:
        """执行完整的建模计算流程。

        Args:
            context: 当前小问上下文。
            interpretation: 问题澄清。
            decision_record: 方法决策记录（Phase 3 产出）。
            data_profile: 数据画像。
            output_dir: 产物目录（LLM 生成的解题代码将保存到其 questions/<qid>/ 下）。
            feedback: 自评/前次尝试的改进建议（作为代码生成的初始反馈）。

        Returns:
            包含 formulation, data_preparation, computation, figures, tables 的字典。
        """
        selected_method = decision_record.get("selected_method", "未知方法")
        method_key = decision_record.get("canonical_method", "")
        math_task = interpretation.math_task

        # 从决策记录中获取 required_outputs 和 validation_requirements
        # （由联网搜索+LLM生成，不再依赖预设方法目录）
        required_outputs = decision_record.get("required_outputs", [])
        validation_requirements = decision_record.get("validation_requirements", [])

        # 步骤 1: 构建模型表述
        formulation = self._build_formulation(
            selected_method, math_task, interpretation, context, method_key
        )
        # 注入决策记录中的输出和验证要求
        if required_outputs:
            formulation["required_outputs"] = required_outputs
        if validation_requirements:
            formulation["validation_requirements"] = validation_requirements

        # 步骤 2: 准备数据
        data_preparation = self._prepare_data(
            selected_method, data_profile, context
        )

        # 步骤 3: 执行计算
        computation = self._execute(
            selected_method, math_task, data_preparation, formulation, context,
            method_key, output_dir, feedback,
        )

        # 步骤 4: 生成输出
        tables = self._generate_tables(
            selected_method, math_task, computation, data_preparation, context
        )
        figures = computation.get("figures") or self._generate_figure_descriptions(
            selected_method, math_task, computation, context
        )

        print(f"[builder] 建模完成: {selected_method} "
              f"(computation_status={computation.get('status', 'unknown')})")

        return {
            "formulation": formulation,
            "data_preparation": data_preparation,
            "computation": computation,
            "figures": figures,
            "tables": tables,
        }

    # ------------------------------------------------------------------
    # 模型表述构建
    # ------------------------------------------------------------------

    def _build_formulation(
        self,
        method_name: str,
        math_task: str,
        interpretation: ProblemInterpretation,
        context: CurrentQuestionContext,
        method_key: str = "",
    ) -> dict:
        """构建数学模型表述。"""
        formulation = {
            "method": method_name,
            "method_key": method_key,
            "math_task": math_task,
            "decision_variables": [],
            "objective_function": "",
            "constraints": [],
            "parameters": {},
            "description": "",
            "required_outputs": self._default_required_outputs(math_task),
            "validation_requirements": self._default_validation_requirements(math_task),
        }

        if math_task == "evaluation":
            formulation.update(self._formulation_evaluation(method_name, interpretation))
        elif math_task == "prediction":
            formulation.update(self._formulation_prediction(method_name, interpretation))
        elif math_task == "optimization":
            formulation.update(self._formulation_optimization(method_name, interpretation))
        elif math_task == "stochastic_optimization":
            formulation.update(self._formulation_stochastic(method_name, interpretation))
        elif math_task == "classification":
            formulation.update(self._formulation_classification(method_name, interpretation))
        elif math_task == "clustering":
            formulation.update(self._formulation_clustering(method_name, interpretation))
        elif math_task == "simulation":
            formulation.update(self._formulation_simulation(method_name, interpretation))
        elif math_task == "mechanism":
            formulation.update(self._formulation_mechanism(method_name, interpretation))
        else:
            formulation.update(self._formulation_composite(method_name, interpretation))

        return self._attach_ir(formulation, method_name, math_task, interpretation, context, method_key)

    def _attach_ir(
        self,
        formulation: dict,
        method_name: str,
        math_task: str,
        interpretation: ProblemInterpretation,
        context: CurrentQuestionContext,
        method_key: str = "",
    ) -> dict:
        """Attach a generic modeling IR while preserving legacy fields.

        required_outputs 和 validation_requirements 直接从 formulation 或
        decision_record 传入（由联网搜索+LLM生成），不再依赖预设方法目录。
        """
        # 确保 required_outputs 和 validation_requirements 存在
        formulation.setdefault("required_outputs", [])
        formulation.setdefault("validation_requirements", [])
        formulation.setdefault("method_key", method_key)
        formulation.setdefault("canonical_method", method_key)

        variables = [
            self._variable_ir_from_text(v)
            for v in formulation.get("decision_variables", [])
        ]
        if not variables:
            variables = self._default_variables_for_task(math_task)

        constraints = [
            ConstraintIR(expression=str(c), meaning=str(c), role=self._constraint_role(str(c)))
            for c in formulation.get("constraints", [])
        ]

        objective = formulation.get("objective_function") or interpretation.objective_function
        ir = FormulationIR(
            question_id=context.question_id,
            math_task=math_task if math_task in MODELING_TASKS else "composite",
            method_key=method_key,
            method_name=method_name,
            sets=self._infer_sets(context, interpretation),
            indices=self._infer_indices(context, interpretation),
            parameters=formulation.get("parameters", {}),
            variables=variables,
            objective=objective,
            objective_sense=self._objective_sense(objective, math_task),
            constraints=constraints,
            assumptions=list(interpretation.necessary_assumptions),
            required_outputs=list(formulation.get("required_outputs", [])),
            validation_requirements=list(formulation.get("validation_requirements", [])),
        )
        formulation["ir"] = ir.model_dump()
        return formulation

    @staticmethod
    def _variable_ir_from_text(text: str) -> VariableIR:
        symbol, _, meaning = str(text).partition(":")
        symbol = symbol.strip() or str(text).strip()
        return VariableIR(symbol=symbol, meaning=meaning.strip(), domain="real")

    @staticmethod
    def _default_variables_for_task(math_task: str) -> list[VariableIR]:
        defaults = {
            "evaluation": [VariableIR(symbol="s_i", meaning="evaluation score")],
            "prediction": [VariableIR(symbol="y_hat", meaning="predicted value")],
            "optimization": [VariableIR(symbol="x_j", meaning="decision variable")],
            "stochastic_optimization": [VariableIR(symbol="x_j", meaning="first-stage decision variable")],
            "simulation": [VariableIR(symbol="theta_hat", meaning="simulated statistic")],
        }
        return defaults.get(math_task, [VariableIR(symbol="z", meaning="model output")])

    @staticmethod
    def _default_required_outputs(math_task: str) -> list[str]:
        """根据任务类型返回默认的 required_outputs。"""
        defaults = {
            "evaluation": ["indicator_weights", "scores_or_ranking"],
            "prediction": ["predictions", "error_metrics"],
            "optimization": ["decision_solution", "objective_value", "constraint_check"],
            "stochastic_optimization": ["scenario_solutions", "expected_objective", "risk_metrics"],
            "simulation": ["simulation_summary", "confidence_interval"],
            "classification": ["classification_labels", "accuracy_metrics"],
            "clustering": ["cluster_assignments", "cluster_centers"],
            "mechanism": ["model_parameters", "fitting_goodness"],
        }
        return defaults.get(math_task, ["model_output"])

    @staticmethod
    def _default_validation_requirements(math_task: str) -> list[str]:
        """根据任务类型返回默认的 validation_requirements。"""
        defaults = {
            "evaluation": ["weight_sensitivity", "ranking_stability"],
            "prediction": ["residual_analysis", "error_metrics"],
            "optimization": ["objective_recompute", "constraint_feasibility", "sensitivity_analysis"],
            "stochastic_optimization": ["scenario_sensitivity", "baseline_comparison"],
            "simulation": ["seed_reproducibility", "sample_size_sensitivity"],
            "classification": ["cross_validation", "confusion_matrix"],
            "clustering": ["silhouette_score", "cluster_stability"],
            "mechanism": ["residual_analysis", "parameter_significance"],
        }
        return defaults.get(math_task, ["result_validation"])

    @staticmethod
    def _constraint_role(expression: str) -> str:
        text = expression.lower()
        if "≥ 0" in expression or "\\geq 0" in text or "nonnegative" in text:
            return "domain"
        if "sum" in text or "Σ" in expression or "容量" in expression or "capacity" in text:
            return "resource"
        if "概率" in expression or "probability" in text or "p(" in text:
            return "risk"
        return "generic"

    @staticmethod
    def _objective_sense(objective: str, math_task: str) -> str:
        text = (objective or "").lower()
        if "max" in text or "最大" in objective:
            return "max"
        if "min" in text or "最小" in objective:
            return "min"
        if math_task == "evaluation":
            return "score"
        if math_task == "prediction":
            return "estimate"
        if math_task == "simulation":
            return "simulate"
        return "none"

    @staticmethod
    def _infer_sets(
        context: CurrentQuestionContext,
        interpretation: ProblemInterpretation,
    ) -> list[str]:
        sets = []
        if context.required_data or interpretation.available_data:
            sets.append("data_records")
        if interpretation.decision_variables:
            sets.append("decision_options")
        if "年" in context.question_text or "time" in context.question_text.lower():
            sets.append("time_periods")
        return sets

    @staticmethod
    def _infer_indices(
        context: CurrentQuestionContext,
        interpretation: ProblemInterpretation,
    ) -> list[str]:
        indices = []
        if interpretation.decision_variables:
            indices.append("j")
        if context.required_data or interpretation.available_data:
            indices.append("i")
        if "年" in context.question_text or "time" in context.question_text.lower():
            indices.append("t")
        return indices

    def _formulation_evaluation(self, method: str, interp: ProblemInterpretation) -> dict:
        """评价类模型表述。"""
        if "熵权法" in method:
            return {
                "decision_variables": ["各指标权重 w_j"],
                "objective_function": "maximize 信息熵 H = -Σ (p_j * ln(p_j))",
                "constraints": ["Σ w_j = 1", "w_j ≥ 0"],
                "parameters": {"n_indicators": "指标数", "n_samples": "样本数"},
                "description": "通过信息熵计算各指标权重，熵值越小权重越大",
            }
        elif "TOPSIS" in method:
            return {
                "decision_variables": ["各方案到理想解的距离"],
                "objective_function": "minimize C_i = D_i⁻ / (D_i⁺ + D_i⁻)",
                "constraints": ["权重由外部确定", "数据需标准化"],
                "parameters": {"weights": "指标权重向量"},
                "description": "计算各方案与正负理想解的相对接近度",
            }
        elif "AHP" in method or "层次" in method:
            return {
                "decision_variables": ["各指标权重 w_j"],
                "objective_function": "求解判断矩阵 A 的最大特征值对应特征向量",
                "constraints": ["Σ w_j = 1", "CR < 0.1 (一致性检验)"],
                "parameters": {"judgment_matrix": "判断矩阵", "RI": "随机一致性指标"},
                "description": "通过专家判断矩阵计算权重，需通过一致性检验",
            }
        return {
            "decision_variables": ["评价得分"],
            "objective_function": "综合评价函数",
            "constraints": [],
            "parameters": {},
            "description": f"{method} 评价模型",
        }

    def _formulation_prediction(self, method: str, interp: ProblemInterpretation) -> dict:
        if "线性回归" in method:
            return {
                "decision_variables": ["回归系数 β"],
                "objective_function": "minimize Σ(y_i - β₀ - Σβ_j·x_ij)²",
                "constraints": ["误差独立同分布", "无多重共线性"],
                "parameters": {"n_features": "特征数", "n_samples": "样本数"},
                "description": "最小二乘法拟合线性模型",
            }
        elif "ARIMA" in method:
            return {
                "decision_variables": ["AR参数 φ", "MA参数 θ", "差分阶数 d"],
                "objective_function": "minimize AIC/BIC",
                "constraints": ["序列平稳", "参数可逆"],
                "parameters": {"p": "AR阶数", "d": "差分阶数", "q": "MA阶数"},
                "description": "ARIMA(p,d,q) 时间序列预测",
            }
        elif "灰色" in method or "GM" in method:
            return {
                "decision_variables": ["发展系数 a", "灰作用量 b"],
                "objective_function": "minimize 残差平方和",
                "constraints": ["级比检验通过", "数据呈指数趋势"],
                "parameters": {"a": "发展系数", "b": "灰作用量"},
                "description": "GM(1,1) 灰色预测模型",
            }
        return {
            "decision_variables": ["模型参数"],
            "objective_function": "预测误差最小化",
            "constraints": [],
            "parameters": {},
            "description": f"{method} 预测模型",
        }

    def _formulation_optimization(self, method: str, interp: ProblemInterpretation) -> dict:
        if "线性规划" in method:
            return {
                "decision_variables": ["决策变量 x_j (连续)"],
                "objective_function": "max/min c^T x",
                "constraints": ["Ax ≤ b", "x ≥ 0"],
                "parameters": {"c": "目标系数", "A": "约束矩阵", "b": "约束右端"},
                "description": "线性规划求解全局最优",
            }
        elif "整数" in method:
            return {
                "decision_variables": ["决策变量 x_j (整数)"],
                "objective_function": "max/min c^T x",
                "constraints": ["Ax ≤ b", "x ∈ Z⁺"],
                "parameters": {"c": "目标系数", "A": "约束矩阵", "b": "约束右端"},
                "description": "整数规划求解离散最优",
            }
        elif "遗传" in method or "粒子群" in method or "模拟退火" in method:
            return {
                "decision_variables": ["决策变量 x_j"],
                "objective_function": "max/min f(x)",
                "constraints": ["g_i(x) ≤ 0", "变量范围约束"],
                "parameters": {
                    "population_size": "种群规模",
                    "max_generations": "最大迭代次数",
                    "mutation_rate": "变异概率",
                },
                "description": f"{method} 启发式全局优化",
            }
        return {
            "decision_variables": ["决策变量"],
            "objective_function": "目标函数优化",
            "constraints": [],
            "parameters": {},
            "description": f"{method} 优化模型",
        }

    def _formulation_classification(self, method: str, interp: ProblemInterpretation) -> dict:
        return {
            "decision_variables": ["分类边界参数"],
            "objective_function": "minimize 分类错误率",
            "constraints": [],
            "parameters": {},
            "description": f"{method} 分类模型",
        }

    def _formulation_stochastic(self, method: str, interp: ProblemInterpretation) -> dict:
        """随机/鲁棒优化模型表述。"""
        if "随机规划" in method:
            return {
                "decision_variables": ["第一阶段决策 x", "第二阶段补偿决策 y(ξ)"],
                "objective_function": "minimize c^T x + E_ξ[Q(x, ξ)]",
                "constraints": ["Ax ≤ b", "x ≥ 0", "Q(x,ξ) = min q^T y s.t. Wy ≤ h(ξ)-T(ξ)x"],
                "parameters": {"xi": "随机变量", "n_scenarios": "场景数", "P(xi)": "场景概率"},
                "description": "两阶段随机规划：第一阶段确定性决策 + 第二阶段场景补偿",
            }
        elif "鲁棒" in method:
            return {
                "decision_variables": ["决策变量 x", "不确定性参数 ζ ∈ Z"],
                "objective_function": "minimize max_{ζ∈Z} f(x, ζ)",
                "constraints": ["g_i(x, ζ) ≤ 0, ∀ζ∈Z", "x ∈ X"],
                "parameters": {"Z": "不确定性集合", "Gamma": "鲁棒性参数"},
                "description": "鲁棒优化：在最坏情况不确定性下优化决策",
            }
        elif "蒙特卡洛" in method:
            return {
                "decision_variables": ["决策变量 x", "模拟场景 ξ_s (s=1,...,N)"],
                "objective_function": "minimize (1/N) Σ_s f(x, ξ_s)",
                "constraints": ["g_i(x, ξ_s) ≤ 0, ∀s", "x ≥ 0"],
                "parameters": {"N": "模拟次数", "dist": "随机参数分布"},
                "description": "蒙特卡洛模拟 + 优化：通过随机采样场景求解期望最优",
            }
        elif "机会约束" in method:
            return {
                "decision_variables": ["决策变量 x"],
                "objective_function": "minimize c^T x",
                "constraints": ["P(g_i(x, ξ) ≤ 0) ≥ 1 - α_i", "x ≥ 0"],
                "parameters": {"alpha": "违约概率上限", "dist": "随机参数分布"},
                "description": "机会约束规划：约束以概率 1-α 满足",
            }
        else:
            return {
                "decision_variables": ["决策变量 x", "随机参数 ξ"],
                "objective_function": "minimize E[f(x, ξ)]",
                "constraints": ["g_i(x, ξ) ≤ 0 (以概率满足)", "x ∈ X"],
                "parameters": {"xi": "不确定参数", "confidence": "置信水平"},
                "description": f"{method} 不确定性优化模型",
            }

    def _formulation_clustering(self, method: str, interp: ProblemInterpretation) -> dict:
        return {
            "decision_variables": ["聚类中心", "样本归属"],
            "objective_function": "minimize 簇内距离和",
            "constraints": ["每个样本属于一个簇"],
            "parameters": {"k": "簇数"},
            "description": f"{method} 聚类模型",
        }

    def _formulation_simulation(self, method: str, interp: ProblemInterpretation) -> dict:
        return {
            "decision_variables": ["模拟参数"],
            "objective_function": "统计量估计",
            "constraints": ["分布假设合理"],
            "parameters": {"n_simulations": "模拟次数"},
            "description": f"{method} 仿真模型",
        }

    def _formulation_mechanism(self, method: str, interp: ProblemInterpretation) -> dict:
        return {
            "decision_variables": ["模型参数"],
            "objective_function": "拟合实测数据",
            "constraints": ["初始条件", "边界条件"],
            "parameters": {},
            "description": f"{method} 机理模型",
        }

    def _formulation_composite(self, method: str, interp: ProblemInterpretation) -> dict:
        return {
            "decision_variables": ["多阶段决策变量"],
            "objective_function": "多阶段综合目标",
            "constraints": [],
            "parameters": {},
            "description": f"{method} 组合模型",
        }

    # ------------------------------------------------------------------
    # 数据准备
    # ------------------------------------------------------------------

    def _prepare_data(
        self,
        method_name: str,
        data_profile: DataProfile | None,
        context: CurrentQuestionContext,
    ) -> dict:
        """准备模型所需数据。

        从 DataProfile 中查找完整文件路径（FileRecord.file_path），
        而非仅使用 source_file（文件名）。
        """
        prep = {
            "method": method_name,
            "data_available": data_profile is not None and len(data_profile.tables) > 0,
            "data_source": "",
            "n_samples": 0,
            "n_features": 0,
            "feature_names": [],
            "preprocessing": [],
            "data_matrix": None,  # 实际数据矩阵（如果有）
            "loaded_tables": [],  # 所有已加载表的摘要
        }

        if data_profile is None or not data_profile.tables:
            return prep

        # 构建 file_name → file_path 的查找映射
        file_path_map: dict[str, str] = {}
        for f in data_profile.files:
            if f.read_status == "success":
                file_path_map[f.file_name] = f.file_path

        # 尝试加载每张表的数据，优先选择有数值列的表
        best_df = None
        best_table = None

        for table in data_profile.tables:
            raw_name = table.source_file
            full_path = file_path_map.get(raw_name, "")

            try:
                import pandas as pd
                from pathlib import Path

                # 如果映射中没有，尝试用 source_file 直接作为路径
                if not full_path:
                    # source_file 可能本身就是路径（旧版本兼容）
                    p = Path(raw_name)
                    if p.exists():
                        full_path = raw_name
                    else:
                        prep["preprocessing"].append(
                            f"跳过表 {raw_name}: 无法解析完整路径"
                        )
                        continue

                # 读取数据
                ext = Path(full_path).suffix.lower()
                if ext == ".csv":
                    df = pd.read_csv(full_path)
                elif ext in (".xlsx", ".xls"):
                    df = pd.read_excel(
                        full_path,
                        sheet_name=table.sheet_name or 0,
                    )
                elif ext == ".mat":
                    from ..tools.file_tools import read_mat
                    var_name = table.sheet_name or None
                    df = read_mat(full_path, variable_name=var_name)
                elif ext in (".json", ".jsonl", ".ndjson"):
                    from ..tools.file_tools import read_json
                    df = read_json(full_path)
                else:
                    continue

                if df is None or len(df) == 0:
                    continue

                # 记录已加载表
                numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
                prep["loaded_tables"].append({
                    "source": raw_name,
                    "sheet": table.sheet_name,
                    "n_rows": len(df),
                    "n_numeric_cols": len(numeric_cols),
                })

                # 选择数值列最多的表作为主数据
                if best_df is None or len(numeric_cols) > len(
                    best_df.select_dtypes(include=[np.number]).columns
                ):
                    best_df = df
                    best_table = table

            except Exception as e:
                prep["preprocessing"].append(
                    f"加载表 {raw_name} 失败: {str(e)[:80]}"
                )

        # 使用最佳表的数据
        if best_df is not None and best_table is not None:
            prep["data_source"] = best_table.source_file
            prep["n_samples"] = len(best_df)

            numeric_cols = best_df.select_dtypes(include=[np.number]).columns.tolist()
            if numeric_cols:
                data_matrix = best_df[numeric_cols].values
                # 清理 NaN 和 inf
                data_matrix = np.nan_to_num(data_matrix, nan=0.0, posinf=1e10, neginf=-1e10)
                prep["data_matrix"] = data_matrix.tolist()
                prep["feature_names"] = list(numeric_cols[:15])
                prep["n_features"] = len(numeric_cols)
                prep["preprocessing"].append(
                    f"从 {best_table.source_file} 选择 {len(numeric_cols)} 个数值列"
                )
            else:
                prep["preprocessing"].append("主表无数值列可用")
        else:
            prep["preprocessing"].append("未能加载任何数据表")

        # 添加预处理步骤
        if prep["n_samples"] > 0:
            if "熵权法" in method_name or "TOPSIS" in method_name:
                prep["preprocessing"].append("数据标准化（min-max）")
            elif "回归" in method_name or "ARIMA" in method_name:
                prep["preprocessing"].append("检查缺失值和异常值")
            elif "规划" in method_name:
                prep["preprocessing"].append("提取决策变量和约束参数")

        return prep

    # ------------------------------------------------------------------
    # 计算执行
    # ------------------------------------------------------------------

    def _execute(
        self,
        method_name: str,
        math_task: str,
        data_prep: dict,
        formulation: dict,
        context: CurrentQuestionContext,
        method_key: str = "",
        output_dir: str | Path | None = None,
        feedback: str = "",
    ) -> dict:
        """执行模型计算。

        Args:
            method_name: 选中方法名称。
            math_task: 数学任务类型。
            data_prep: 数据准备结果。
            formulation: 模型表述。
            context: 当前小问上下文。
            method_key: 方法标识。
            output_dir: 产物目录（LLM 生成代码保存到 questions/<qid>/）。
            feedback: 自评/前次尝试的改进建议（作为代码生成的初始反馈）。
        """
        method_key = method_key or formulation.get("method_key", "")
        computation = {
            "method": method_name,
            "method_key": method_key,
            "status": "not_executed",
            "results": {},
            "metrics": {},
            "parameters_used": formulation.get("parameters", {}),
            "intermediate_values": {},
            "error": "",
        }

        data_matrix = data_prep.get("data_matrix")

        # 任务驱动建模：有 LLM 且题型支持时，优先用 LLM 生成具体数学模型与
        # 求解代码并沙箱执行，得到真实计算结果；失败则回退预设方法目录。
        if self._llm is not None and math_task in CODE_BASED_TASKS:
            try:
                code_computation = self._execute_code_based(
                    method_name, math_task, data_prep, formulation, context, output_dir,
                    feedback=feedback,
                )
                if code_computation.get("status") == "success":
                    return code_computation
                print(
                    f"[builder] 任务驱动建模未成功（{code_computation.get('status')}），"
                    f"回退预设方法: {code_computation.get('error', '')[:120]}"
                )
            except Exception as e:
                print(f"[builder] 任务驱动建模异常，回退预设方法: {e}")

        try:
            if data_matrix is not None and len(data_matrix) > 0:
                data = np.array(data_matrix, dtype=float)

                # 按方法分发
                if method_key == "entropy_weight" or "熵权法" in method_name:
                    computation.update(self._compute_entropy_weight(data))
                elif method_key == "topsis" or "TOPSIS" in method_name:
                    computation.update(self._compute_topsis(data))
                elif method_key == "linear_regression" or "线性回归" in method_name:
                    computation.update(self._compute_linear_regression(data))
                elif method_key == "gm11" or "灰色" in method_name or "GM" in method_name:
                    computation.update(self._compute_gm11(data))
                elif method_key in ("linear_programming", "integer_programming") or any(
                    kw in method_name for kw in ["线性规划", "整数规划", "数学规划", "非线性规划"]
                ):
                    computation.update(self._compute_lp_stub(data, formulation))
                elif method_key in (
                    "stochastic_programming",
                    "robust_optimization",
                    "monte_carlo_optimization",
                    "chance_constrained_programming",
                ) or any(kw in method_name for kw in [
                    "随机规划", "鲁棒", "蒙特卡洛+优化", "机会约束", "确定性基础",
                    "随机优化", "不确定性优化", "场景优化",
                ]):
                    computation.update(self._compute_stochastic_lp(data, formulation, method_name))
                elif method_key == "monte_carlo_simulation":
                    computation.update(self._compute_generic(data, "蒙特卡洛模拟"))
                else:
                    computation.update(self._compute_generic(data, method_name))
            else:
                # 无数据时的占位计算
                computation["status"] = "no_data"
                computation["results"] = {
                    "note": "无可用数据，无法执行实际计算",
                    "method": method_name,
                }
                computation["metrics"] = {"data_available": 0}
        except Exception as e:
            computation["status"] = "error"
            computation["error"] = str(e)[:200]
            computation["results"] = {"error": str(e)[:200]}

        # 预设方法路径：生成并保存 solution.py（与 LLM 代码路径产物结构一致）
        if computation.get("status") == "success" and output_dir and context.question_id:
            try:
                code = self._generate_preset_solution_code(
                    method_name, method_key, data_prep, computation, formulation
                )
                data_csv_path = self._write_data_csv(data_prep)
                self._persist_question_artifacts(
                    question_id=context.question_id,
                    output_dir=output_dir,
                    code=code,
                    data_csv_path=data_csv_path,
                    results=computation.get("results", {}),
                    method_name=method_name,
                    model_name=formulation.get("method", method_name),
                )
            except Exception as e:
                print(f"[builder] 预设方法代码保存失败（不影响计算）: {e}")

        return computation

    # ------------------------------------------------------------------
    # 任务驱动建模：LLM 生成模型 + 代码沙箱执行
    # ------------------------------------------------------------------

    def _execute_code_based(
        self,
        method_name: str,
        math_task: str,
        data_prep: dict,
        formulation: dict,
        context: CurrentQuestionContext,
        output_dir: str | Path | None = None,
        feedback: str = "",
    ) -> dict:
        """任务驱动建模：分段调用 LLM（模型设计→代码生成），沙箱执行并校验。

        流程：准备数据 CSV → LLM 设计数学模型 → LLM 生成求解代码
              （各 10 分钟超时）→ 沙箱执行 → 按题型校验 → 失败反馈修复重试。

        超时策略（超时即回退）：
          - 模型设计 / 代码生成 **超时** → 立即回退预设方法（不再重试，
            因为重试大概率仍超时，避免 180s 白等后再次 180s）
          - 其他失败（解析 / 执行 / 校验）→ 反馈给 LLM 修复重试（≤2 次）

        Args:
            method_name: 选中方法名称。
            math_task: 数学任务类型。
            data_prep: 数据准备结果。
            formulation: 模型表述。
            context: 当前小问上下文。
            output_dir: 产物目录（解题代码/数据/结果保存到 questions/<qid>/）。
            feedback: 自评/前次尝试的改进建议（作为首轮代码生成的初始反馈）。
        """
        from ..agents.code_modeler import (
            CodeModeler,
            CodeModelingError,
            LLMTimeoutError,
        )
        from ..tools.code_executor import CodeExecutionError, execute_model_code

        import time

        csv_path = self._write_data_csv(data_prep)
        # 无数据文件时不 bail：让 LLM 生成自包含代码（题面参数直接写入代码常量）。
        # 仅当确实需要外部数据却拿不到时才视为失败（此处交由 LLM 判断）。
        data_summary = self._build_data_summary(data_prep)[:800]
        if csv_path is None:
            data_summary = (
                (data_summary + "\n" if data_summary else "")
                + "【重要】本题无外部数据文件。请不要读取 CSV/Excel，"
                "将任务给出的参数（如速度、距离、时间、坐标等）直接作为常量写入代码，"
                "生成完全自包含的求解代码。"
            )
            print("[builder] 无数据文件，要求 LLM 生成自包含代码（参数写入代码）")

        # 提示词瘦身（C）：问题文本 1000 字符，减少生成 token
        question_text = context.question_text[:1000]

        modeler = CodeModeler(self._llm)
        feedback = feedback or ""
        last_error = ""
        t_start = time.time()
        # 预算：若 budget_manager 可用，按 CODE_REPAIR 剩余动态调整最大尝试次数。
        # 首次 attempt 不消耗 CODE_REPAIR；之后每次失败 retry 消耗 1 次。
        max_attempts = CODE_GEN_MAX_RETRIES
        if self._budget_manager is not None:
            try:
                from ..runtime.budget import BudgetType
                rem = self._budget_manager.remaining(
                    BudgetType.CODE_REPAIR, question_id=context.question_id
                )
                max_attempts = max(1, min(CODE_GEN_MAX_RETRIES, rem + 1))
            except Exception:
                pass
        print(
            f"[builder] 任务驱动建模开始（题型={math_task}，方法={method_name}，"
            f"最多尝试 {max_attempts} 次，模型设计/代码生成超时均为 10 分钟）"
        )

        try:
            for attempt in range(max_attempts):
                print(f"[builder]   └ 第 {attempt + 1}/{max_attempts} 次尝试...")
                # 1. 模型设计（超时即回退）
                try:
                    model_json = modeler.generate_model(
                        question_text=question_text,
                        math_task=math_task,
                        method_hint=method_name,
                        data_summary=data_summary,
                        feedback=feedback,
                    )
                except LLMTimeoutError as e:
                    print(f"[builder]     ↳ 模型设计超时（{e}）→ 直接回退预设方法")
                    return {"status": "error", "error": f"模型设计超时: {e}"}
                except CodeModelingError as e:
                    last_error = str(e)
                    feedback = f"模型设计失败: {last_error}"
                    print(f"[builder]     ↳ 模型设计失败: {last_error[:120]}")
                    if self._consume_code_repair_or_stop(context.question_id, "模型设计", last_error):
                        return {"status": "error", "error": f"代码修复预算耗尽（模型设计: {last_error[:100]}）"}
                    continue

                # 2. 代码生成（超时即回退）
                try:
                    code = modeler.generate_code(
                        model_json,
                        question_text=question_text,
                        data_summary=data_summary,
                        feedback=feedback,
                    )
                except LLMTimeoutError as e:
                    print(f"[builder]     ↳ 代码生成超时（{e}）→ 直接回退预设方法")
                    return {"status": "error", "error": f"代码生成超时: {e}"}
                except CodeModelingError as e:
                    last_error = str(e)
                    feedback = f"代码生成失败: {last_error}"
                    print(f"[builder]     ↳ 代码生成失败: {last_error[:120]}")
                    if self._consume_code_repair_or_stop(context.question_id, "代码生成", last_error):
                        return {"status": "error", "error": f"代码修复预算耗尽（代码生成: {last_error[:100]}）"}
                    continue

                # 3. 沙箱执行
                t_exec = time.time()
                print(
                    f"[builder]     ↳ 模型代码就绪（{model_json.get('model_name', '?')}，"
                    f"{len(code)} 字符），开始沙箱执行..."
                )
                try:
                    figure_output_dir = (
                        Path(output_dir) / "figures" if output_dir else None
                    )
                    result = execute_model_code(
                        code,
                        data_csv_path=csv_path,
                        figure_output_dir=figure_output_dir,
                        figure_prefix=context.question_id,
                        require_figures=figure_output_dir is not None,
                    )
                except CodeExecutionError as e:
                    last_error = str(e)
                    feedback = f"求解代码执行失败: {last_error}"
                    print(
                        f"[builder]     ↳ 代码执行失败（耗时 {time.time() - t_exec:.1f}s）: "
                        f"{last_error[:150]}"
                    )
                    if self._consume_code_repair_or_stop(context.question_id, "代码执行", last_error):
                        return {"status": "error", "error": f"代码修复预算耗尽（代码执行: {last_error[:100]}）"}
                    continue
                print(f"[builder]     ↳ 代码执行成功（耗时 {time.time() - t_exec:.1f}s），校验结果...")

                # 4. 按题型校验结果
                try:
                    self._validate_task_results(result, math_task)
                except Exception as e:
                    last_error = str(e)
                    feedback = f"结果不满足题型要求: {last_error}"
                    print(f"[builder]     ↳ 结果校验未通过: {last_error[:150]}")
                    if self._consume_code_repair_or_stop(context.question_id, "结果校验", last_error):
                        return {"status": "error", "error": f"代码修复预算耗尽（结果校验: {last_error[:100]}）"}
                    continue

                # 5. 成功
                print(
                    f"[builder]   └ 任务驱动建模成功（总耗时 {time.time() - t_start:.1f}s，"
                    f"第 {attempt + 1} 次尝试）"
                )
                # 5.1 持久化解题代码/数据/结果到 artifacts/questions/<qid>/
                artifacts_dir = self._persist_question_artifacts(
                    question_id=context.question_id,
                    output_dir=output_dir,
                    code=code,
                    data_csv_path=csv_path,
                    results=result,
                    method_name=method_name,
                    model_name=model_json.get("model_name", method_name),
                )
                return {
                    "status": "success",
                    "method": method_name,
                    "method_key": "code_based",
                    "model_name": model_json.get("model_name", method_name),
                    "model_summary": model_json.get("model_summary", ""),
                    "results": result,
                    "metrics": result.get("metrics", {}) if isinstance(result, dict) else {},
                    "figures": result.get("figures", []) if isinstance(result, dict) else [],
                    "parameters_used": model_json.get("key_parameters", {}),
                    "intermediate_values": {
                        "generation_attempts": attempt + 1,
                        "solution_code_snippet": code[:200],
                        "variables": model_json.get("variables", []),
                        "objective": model_json.get("objective", ""),
                        "constraints": model_json.get("constraints", []),
                    },
                    "artifacts_dir": str(artifacts_dir) if artifacts_dir else "",
                    "error": "",
                }

            print(
                f"[builder]   └ 任务驱动建模失败（总耗时 {time.time() - t_start:.1f}s）: "
                f"{last_error[:150]}"
            )
            return {"status": "error", "error": last_error or "建模/执行/校验全部失败"}
        finally:
            if csv_path and os.path.exists(csv_path):
                try:
                    os.unlink(csv_path)
                except OSError:
                    pass

    def _persist_question_artifacts(
        self,
        question_id: str,
        output_dir: str | Path | None,
        code: str,
        data_csv_path: str | Path | None,
        results: dict,
        method_name: str,
        model_name: str,
    ) -> Path | None:
        """将小问的建模解题产物保存到 <output_dir>/questions/<qid>/。

        保存内容（architecture.md §6.3 每问代码/数据/结果包）：
          - solution.py：LLM 生成的完整求解代码
          - data.csv：传入沙箱执行的输入数据
          - result.json：执行结果（results + 方法信息）

        Args:
            question_id: 小问 ID。
            output_dir: 产物根目录（artifacts/<run_id>）。
            code: LLM 生成的完整求解代码。
            data_csv_path: 沙箱执行用的数据 CSV（临时文件，保存为副本）。
            results: 沙箱执行返回的结果字典。
            method_name: 选中方法名称。
            model_name: 生成的模型名称。

        Returns:
            保存目录 Path；output_dir 为空时不保存并返回 None。
        """
        if not output_dir or not question_id:
            return None

        q_dir = Path(output_dir) / "questions" / question_id
        q_dir.mkdir(parents=True, exist_ok=True)

        # 完整求解代码
        (q_dir / "solution.py").write_text(code, encoding="utf-8")

        # 输入数据（保存副本，避免随临时文件删除）
        if data_csv_path and Path(data_csv_path).exists():
            shutil.copy2(data_csv_path, q_dir / "data.csv")

        # 执行结果
        (q_dir / "result.json").write_text(
            json.dumps(
                {
                    "status": "success",
                    "method": method_name,
                    "model_name": model_name,
                    "results": results,
                    "metrics": results.get("metrics", {}) if isinstance(results, dict) else {},
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        print(f"[builder] 解题代码/数据/结果已保存: {q_dir}")
        return q_dir

    def _generate_preset_solution_code(
        self,
        method_name: str,
        method_key: str,
        data_prep: dict,
        computation: dict,
        formulation: dict,
    ) -> str:
        """为预设方法路径生成 solution.py 脚本。

        根据 method_key 选择对应的计算逻辑模板，生成可独立运行的 Python 脚本。
        脚本从同目录 data.csv 读取数据，执行计算并输出结果。
        """
        feature_names = data_prep.get("feature_names") or []
        n_samples = data_prep.get("n_samples", 0)

        # 选择计算逻辑模板
        if method_key == "entropy_weight" or "熵权法" in method_name:
            compute_block = '''# 熵权法计算权重
n, m = data.shape
# 归一化（正向指标）
data_norm = np.zeros_like(data, dtype=float)
for j in range(m):
    col = data[:, j]
    col_min, col_max = col.min(), col.max()
    if col_max - col_min > 1e-12:
        data_norm[:, j] = (col - col_min) / (col_max - col_min)
    else:
        data_norm[:, j] = 0.0

# 计算信息熵
P = data_norm / (data_norm.sum(axis=0, keepdims=True) + 1e-12)
e = -np.sum(P * np.log(P + 1e-12), axis=0) / np.log(n)
d = 1 - e
weights = d / d.sum()

# 计算综合得分
scores = data_norm @ weights
print("各指标权重:", weights)
print("综合得分:", scores)'''

        elif method_key == "topsis" or "TOPSIS" in method_name:
            compute_block = '''# TOPSIS 综合评价
n, m = data.shape
# 标准化
norm = np.sqrt((data ** 2).sum(axis=0))
data_norm = data / (norm + 1e-12)

# 等权重
weights = np.ones(m) / m
data_weighted = data_norm * weights

# 正负理想解
ideal_best = data_weighted.max(axis=0)
ideal_worst = data_weighted.min(axis=0)

# 计算距离
d_best = np.sqrt(((data_weighted - ideal_best) ** 2).sum(axis=1))
d_worst = np.sqrt(((data_weighted - ideal_worst) ** 2).sum(axis=1))

# 相对接近度
closeness = d_worst / (d_best + d_worst + 1e-12)
ranking = np.argsort(-closeness) + 1
print("相对接近度:", closeness)
print("排名:", ranking)'''

        elif method_key == "linear_regression" or "线性回归" in method_name:
            compute_block = '''# 线性回归
n, m = data.shape
X = data[:, :-1]
y = data[:, -1]
# 最小二乘法
X_ext = np.column_stack([X, np.ones(n)])
beta = np.linalg.lstsq(X_ext, y, rcond=None)[0]
y_pred = X_ext @ beta
r2 = 1 - ((y - y_pred) ** 2).sum() / ((y - y.mean()) ** 2 + 1e-12)
print("回归系数:", beta)
print("R²:", r2)'''

        elif method_key == "gm11" or "灰色" in method_name or "GM" in method_name:
            compute_block = '''# GM(1,1) 灰色预测
x0 = data[:, 0] if data.ndim > 1 else data
n = len(x0)
# 累加生成
x1 = np.cumsum(x0)
z1 = -0.5 * (x1[:-1] + x1[1:])
B = np.column_stack([z1, np.ones(n - 1)])
Y = x0[1:]
a, b = np.linalg.lstsq(B, Y, rcond=None)[0]
# 预测
k = np.arange(n + 5)
x1_pred = (x0[0] - b / a) * np.exp(-a * k) + b / a
x0_pred = np.diff(np.concatenate([[x0[0]], x1_pred]))
print("发展系数 a:", a)
print("灰作用量 b:", b)
print("预测值:", x0_pred)'''

        elif method_key in ("linear_programming", "integer_programming") or any(
            kw in method_name for kw in ["线性规划", "整数规划", "数学规划"]
        ):
            compute_block = '''# 线性规划求解
from scipy.optimize import linprog
n, m = data.shape
# 目标函数系数（示例：最大化第一列，取负转化为最小化）
c = -data[0, :m] if n > 0 else np.zeros(m)
# 约束：A_ub @ x <= b_ub
A_ub = data[1:, :m] if n > 1 else np.zeros((1, m))
b_ub = data[1:, m] if data.shape[1] > m else np.zeros(n - 1) if n > 1 else np.zeros(1)
bounds = [(0, None)] * m
result = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method='highs')
if result.success:
    print("最优解:", result.x)
    print("最优值:", -result.fun)
else:
    print("求解失败:", result.message)'''

        else:
            # 通用模板
            compute_block = '''# 通用数据分析
n, m = data.shape
print(f"数据规模: {n} 行 × {m} 列")
print("描述统计:")
print(f"  均值: {data.mean(axis=0)}")
print(f"  标准差: {data.std(axis=0)}")
print(f"  最小值: {data.min(axis=0)}")
print(f"  最大值: {data.max(axis=0)}")'''

        feature_str = ", ".join(repr(f) for f in feature_names) if feature_names else ""
        method_str = method_name or method_key or "预设方法"

        code = f'''"""
{method_str} - 求解代码

由 MMAgent 预设方法路径自动生成。
数据来源: 同目录 data.csv
计算结果: 见同目录 result.json
"""
import numpy as np
import pandas as pd
import json

# 读取数据
df = pd.read_csv("data.csv")
feature_names = [{feature_str}]
data = df.values.astype(float)

print("=" * 60)
print("方法: {method_str}")
print(f"样本量: {{len(data)}}")
print(f"特征: {{list(df.columns)}}")
print("=" * 60)

{compute_block}

# 保存结果
results = {{
    "method": "{method_str}",
    "n_samples": int(len(data)),
    "feature_names": list(df.columns),
}}
with open("result.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("\\n结果已保存到 result.json")
'''
        return code

    def _write_data_csv(self, data_prep: dict) -> str | None:
        """将数据矩阵（含表头）写入临时 CSV，供生成代码读取。"""
        import tempfile

        matrix = data_prep.get("data_matrix")
        if not matrix:
            return None

        names = list(data_prep.get("feature_names") or [])
        n_cols = len(matrix[0]) if matrix else 0
        if len(names) < n_cols:
            names = names + [f"col_{i}" for i in range(len(names), n_cols)]
        names = names[:n_cols]

        import pandas as pd

        fd, path = tempfile.mkstemp(suffix=".csv", prefix="mma_data_")
        os.close(fd)
        try:
            pd.DataFrame(matrix, columns=names).to_csv(path, index=False)
        except Exception:
            if os.path.exists(path):
                os.unlink(path)
            return None
        return path

    def _build_data_summary(self, data_prep: dict) -> str:
        """构建数据结构摘要（供 LLM 建模参考）。"""
        lines = []
        lines.append(f"- 样本量: {data_prep.get('n_samples', 0)} 行")
        lines.append(f"- 特征列: {data_prep.get('feature_names', [])}")
        tables = data_prep.get("loaded_tables", [])
        if tables:
            lines.append(f"- 已加载表: {tables[:3]}")
        for p in data_prep.get("preprocessing", [])[:5]:
            lines.append(f"- 预处理: {p}")
        return "\n".join(lines)

    def _validate_task_results(self, result: dict, math_task: str) -> None:
        """按题型校验代码输出结果的关键字段。"""
        from ..tools.result_keys import normalize_result_dict

        # 归一化键名：兼容 LLM 提示词契约（solution/objective/r2）与预设方法契约
        result = normalize_result_dict(result)

        if not isinstance(result, dict):
            raise ValueError("结果不是 dict")
        if not result:
            raise ValueError("结果为空")

        if math_task == "optimization":
            if "solution" not in result and "optimal_solution" not in result:
                raise ValueError("缺少 solution（最优解）")
            if "objective" not in result and "optimal_objective" not in result:
                raise ValueError("缺少 objective（最优目标值）")
        elif math_task == "stochastic_optimization":
            if "robust_solution" not in result and "scenario_solutions" not in result:
                raise ValueError("缺少 robust_solution 或 scenario_solutions")
            if not any(k in result for k in ("expected_objective", "worst_case", "objective_std")):
                raise ValueError("缺少期望/最坏目标值等风险指标")
        elif math_task == "evaluation":
            if not any(k in result for k in ("weights", "scores", "ranking")):
                raise ValueError("缺少 weights/scores/ranking")
        elif math_task == "prediction":
            if not any(k in result for k in ("predictions", "forecast", "fitted_values")):
                raise ValueError("缺少 predictions/forecast")
            metrics = result.get("metrics") or {}
            if not any(k in metrics for k in ("r_squared", "rmse", "mse", "mae", "mape")):
                raise ValueError("缺少误差指标（r2/rmse/mae 等）")
        elif math_task == "simulation":
            if "simulation" not in result and "n_simulations" not in (result.get("metrics") or {}):
                raise ValueError("缺少模拟结果")
            if "confidence_interval" not in result and "confidence_interval_90" not in str(result):
                raise ValueError("缺少置信区间")
        # 其他题型不强制校验

    def _compute_entropy_weight(self, data: np.ndarray) -> dict:
        """熵权法计算。"""
        n, m = data.shape

        # 标准化（min-max）
        col_min = data.min(axis=0)
        col_max = data.max(axis=0)
        ranges = col_max - col_min
        ranges[ranges == 0] = 1  # 避免除零
        normalized = (data - col_min) / ranges

        # 计算概率矩阵
        col_sum = normalized.sum(axis=0)
        col_sum[col_sum == 0] = 1
        p = normalized / col_sum

        # 计算熵值
        ln_p = np.where(p > 0, np.log(p + 1e-12), 0)
        entropy = -np.sum(p * ln_p, axis=0) / np.log(n)

        # 计算权重
        d = 1 - entropy
        d_sum = d.sum()
        d_sum = d_sum if d_sum > 0 else 1
        weights = d / d_sum

        # 计算综合得分
        scores = np.dot(normalized, weights)

        # 排序
        ranking = np.argsort(-scores)  # 降序

        return {
            "status": "success",
            "results": {
                "weights": weights.tolist(),
                "scores": scores.tolist(),
                "ranking": (ranking + 1).tolist(),  # 1-based
            },
            "metrics": {
                "n_samples": n,
                "n_features": m,
                "max_entropy": float(entropy.max()),
                "min_entropy": float(entropy.min()),
            },
            "intermediate_values": {
                "entropy_values": entropy.tolist(),
                "difference_coefficients": d.tolist(),
            },
        }

    def _compute_topsis(self, data: np.ndarray) -> dict:
        """TOPSIS 计算。"""
        n, m = data.shape

        # 标准化（向量归一化）
        norms = np.sqrt((data ** 2).sum(axis=0))
        norms[norms == 0] = 1
        normalized = data / norms

        # 等权重
        weights = np.ones(m) / m
        weighted = normalized * weights

        # 正负理想解
        positive_ideal = weighted.max(axis=0)
        negative_ideal = weighted.min(axis=0)

        # 计算距离
        d_positive = np.sqrt(((weighted - positive_ideal) ** 2).sum(axis=1))
        d_negative = np.sqrt(((weighted - negative_ideal) ** 2).sum(axis=1))

        # 相对接近度
        closeness = d_negative / (d_positive + d_negative + 1e-12)

        ranking = np.argsort(-closeness)

        return {
            "status": "success",
            "results": {
                "closeness": closeness.tolist(),
                "ranking": (ranking + 1).tolist(),
                "positive_ideal": positive_ideal.tolist(),
                "negative_ideal": negative_ideal.tolist(),
                "d_positive": d_positive.tolist(),
                "d_negative": d_negative.tolist(),
            },
            "metrics": {
                "n_samples": n,
                "n_features": m,
                "weights": weights.tolist(),
            },
        }

    def _compute_linear_regression(self, data: np.ndarray) -> dict:
        """线性回归计算。"""
        n, m = data.shape

        if m < 2 or n < 3:
            return {
                "status": "insufficient_data",
                "results": {"note": "数据不足，需要至少 2 列 3 行"},
                "metrics": {"n_samples": n, "n_features": m},
            }

        # 最后一列作为因变量，其余为自变量
        X = data[:, :-1]
        y = data[:, -1]

        # 添加截距项
        X_with_intercept = np.column_stack([np.ones(n), X])

        # 最小二乘法
        try:
            beta = np.linalg.lstsq(X_with_intercept, y, rcond=None)[0]
            y_pred = X_with_intercept @ beta
            residuals = y - y_pred
            ss_res = np.sum(residuals ** 2)
            ss_tot = np.sum((y - y.mean()) ** 2)
            r_squared = 1 - ss_res / (ss_tot + 1e-12)

            return {
                "status": "success",
                "results": {
                    "coefficients": beta.tolist(),
                    "intercept": float(beta[0]),
                    "slope": beta[1:].tolist() if len(beta) > 1 else [],
                    "predictions": y_pred.tolist(),
                    "residuals": residuals.tolist(),
                },
                "metrics": {
                    "r_squared": float(r_squared),
                    "n_samples": n,
                    "n_features": m - 1,
                    "rmse": float(np.sqrt(ss_res / n)),
                },
            }
        except np.linalg.LinAlgError as e:
            return {
                "status": "error",
                "error": f"线性代数错误: {e}",
                "results": {},
                "metrics": {},
            }

    def _compute_gm11(self, data: np.ndarray) -> dict:
        """GM(1,1) 灰色预测计算。"""
        # 取第一列作为原始序列
        if data.shape[1] >= 1:
            x0 = data[:, 0]
        else:
            x0 = np.array([1.0, 2.0, 3.0, 4.0])

        n = len(x0)
        if n < 4:
            return {
                "status": "insufficient_data",
                "results": {"note": "GM(1,1) 需要至少 4 个数据点"},
                "metrics": {"n_samples": n},
            }

        # 累加生成
        x1 = np.cumsum(x0)

        # 紧邻均值序列
        z1 = 0.5 * (x1[:-1] + x1[1:])

        # 最小二乘估计参数
        B = np.column_stack([-z1, np.ones(n - 1)])
        Y = x0[1:]
        try:
            params = np.linalg.lstsq(B, Y, rcond=None)[0]
            a, b = params

            # 预测
            x1_pred = (x0[0] - b / a) * np.exp(-a * np.arange(n)) + b / a
            x0_pred = np.diff(np.concatenate([[x0[0]], x1_pred[1:]]))

            # 后验差检验
            residuals = x0 - x0_pred
            s1 = np.std(x0)
            s2 = np.std(residuals)
            c = s2 / (s1 + 1e-12)  # 后验差比

            # 预测未来 3 期
            future_steps = 3
            future_x1 = (x0[0] - b / a) * np.exp(-a * np.arange(n, n + future_steps)) + b / a
            future_x0 = np.diff(np.concatenate([[x1_pred[-1]], future_x1]))

            return {
                "status": "success",
                "results": {
                    "development_coefficient_a": float(a),
                    "grey_action_b": float(b),
                    "fitted_values": x0_pred.tolist(),
                    "predicted_future": future_x0.tolist(),
                },
                "metrics": {
                    "posterior_ratio_c": float(c),
                    "n_samples": n,
                    "small_error_probability": float(np.mean(np.abs(residuals) < 0.6745 * s1)),
                },
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"GM(1,1) 计算失败: {e}",
                "results": {},
                "metrics": {},
            }

    def _compute_lp_stub(self, data: np.ndarray, formulation: dict) -> dict:
        """线性规划求解（优先 scipy，降级为 numpy 启发式）。

        从数据矩阵自动构建一个资源分配型 LP：
          - 决策变量：每行对应的分配量 x_i
          - 目标：最大化 sum(c_i * x_i)
          - 约束：sum(x_i) ≤ 总容量；各列加权和 ≤ 列总和
          - 边界：0 ≤ x_i ≤ 每行上限

        求解策略：
          1. 优先使用 scipy.optimize.linprog（HiGHS 求解器）
          2. scipy 不可用时，使用 numpy 启发式贪心分配
        """
        n, m = data.shape

        if n < 2 or m < 1:
            return {
                "status": "insufficient_data",
                "results": {"note": "LP 需要至少 2 行 1 列数据"},
                "metrics": {"n_samples": n, "n_features": m},
            }

        # 构建目标系数和约束数据
        if m >= 2:
            c = data[:, -1]  # 价值/收益系数
            constraints_data = data[:, :-1]
        else:
            c = data[:, 0]
            constraints_data = data

        # 总容量
        total_capacity = float(np.max(np.abs(c)) * n * 0.8)
        if total_capacity <= 0:
            total_capacity = n * 1.0

        # 变量边界
        bounds = [(0, float(max(abs(ci), 1.0))) for ci in c]

        # 尝试 scipy 求解
        try:
            from scipy.optimize import linprog

            c_min = -np.abs(c)  # 最大化 → 最小化负值

            # 构建约束矩阵
            A_ub = np.ones((1, n))
            b_ub = np.array([total_capacity])

            if constraints_data.shape[1] >= 1:
                for j in range(min(constraints_data.shape[1], 3)):
                    col = constraints_data[:, j]
                    col_abs = np.abs(col)
                    if col_abs.sum() > 0:
                        A_ub = np.vstack([A_ub, col_abs.reshape(1, -1)])
                        b_ub = np.append(b_ub, float(col_abs.sum() * 0.8))

            result = linprog(
                c=c_min, A_ub=A_ub, b_ub=b_ub,
                bounds=bounds, method="highs",
            )

            if result.success:
                x_opt = result.x
                obj_value = -result.fun

                return {
                    "status": "success",
                    "results": {
                        "optimal_solution": x_opt.tolist(),
                        "optimal_objective": float(obj_value),
                        "variable_count": n,
                        "constraint_count": len(b_ub),
                        "solver": "scipy.linprog (HiGHS)",
                    },
                    "metrics": {
                        "n_samples": n, "n_features": m,
                        "objective_value": float(obj_value),
                        "total_allocation": float(x_opt.sum()),
                        "solver_status": result.message[:100],
                    },
                    "intermediate_values": {
                        "coefficients": c.tolist(),
                        "capacity": total_capacity,
                    },
                }
            else:
                # scipy 求解失败，降级到 numpy 启发式
                print(f"[builder] scipy LP 求解失败: {result.message[:80]}，降级到 numpy 启发式")
                return self._compute_lp_numpy(data, c, constraints_data, bounds, total_capacity)

        except ImportError:
            # scipy 不可用，使用 numpy 启发式
            print("[builder] scipy 未安装，使用 numpy 启发式 LP 求解")
            return self._compute_lp_numpy(data, c, constraints_data, bounds, total_capacity)
        except Exception as e:
            print(f"[builder] LP 异常: {e}，降级到 numpy 启发式")
            return self._compute_lp_numpy(data, c, constraints_data, bounds, total_capacity)

    def _compute_lp_numpy(
        self,
        data: np.ndarray,
        c: np.ndarray,
        constraints_data: np.ndarray,
        bounds: list[tuple[float, float]],
        total_capacity: float,
    ) -> dict:
        """纯 numpy 启发式 LP 求解器（贪心分配）。

        当 scipy 不可用时的降级方案。
        策略：按价值/资源比降序贪心分配，在约束边界内最大化目标。
        """
        n = len(c)
        m = data.shape[1]

        # 计算每行的"性价比"（价值系数 / 资源消耗）
        abs_c = np.abs(c)
        if constraints_data.shape[1] >= 1:
            resource_per_row = np.abs(constraints_data[:, 0])
            resource_per_row[resource_per_row == 0] = 1.0
        else:
            resource_per_row = np.ones(n)

        efficiency = abs_c / resource_per_row

        # 按性价比降序排列
        sorted_indices = np.argsort(-efficiency)

        # 贪心分配
        x_opt = np.zeros(n)
        remaining_capacity = total_capacity

        # 约束余量（每个约束列）
        constraint_caps = []
        if constraints_data.shape[1] >= 1:
            for j in range(min(constraints_data.shape[1], 3)):
                col = np.abs(constraints_data[:, j])
                constraint_caps.append(float(col.sum() * 0.8))
        else:
            constraint_caps = [total_capacity]

        for idx in sorted_indices:
            # 受限于变量上界和总容量
            upper = bounds[idx][1]
            alloc = min(upper, remaining_capacity)

            # 受限于各约束列
            for j, cap in enumerate(constraint_caps):
                if j < constraints_data.shape[1]:
                    col_val = abs(constraints_data[idx, j])
                    if col_val > 0:
                        remaining_j = cap - np.dot(
                            x_opt, np.abs(constraints_data[:, j])
                        )
                        if col_val > 0 and remaining_j / col_val < alloc:
                            alloc = max(0, remaining_j / col_val)

            x_opt[idx] = round(alloc, 6)
            remaining_capacity -= alloc
            if remaining_capacity <= 0:
                break

        # 计算目标值
        obj_value = float(np.dot(x_opt, abs_c))

        return {
            "status": "success",
            "results": {
                "optimal_solution": x_opt.tolist(),
                "optimal_objective": obj_value,
                "variable_count": n,
                "constraint_count": 1 + len(constraint_caps),
                "solver": "numpy_greedy_heuristic",
                "note": "使用 numpy 启发式贪心求解（scipy 不可用时的降级方案）",
            },
            "metrics": {
                "n_samples": n,
                "n_features": m,
                "objective_value": obj_value,
                "total_allocation": float(x_opt.sum()),
                "solver_status": "heuristic_solution",
                "capacity_utilization": float(x_opt.sum() / total_capacity) if total_capacity > 0 else 0,
            },
            "intermediate_values": {
                "coefficients": c.tolist(),
                "efficiency_ranking": sorted_indices.tolist(),
                "capacity": total_capacity,
            },
        }

    def _compute_stochastic_lp(
        self,
        data: np.ndarray,
        formulation: dict,
        method_name: str,
    ) -> dict:
        """随机/鲁棒优化计算。

        策略：
          1. 先用确定性 LP 求解基线方案
          2. 对参数加入随机扰动模拟不确定性场景
          3. 在每个场景下求解 LP，统计最优解分布
          4. 产出鲁棒性指标（期望目标值、最坏情况、方差等）
        """
        n, m = data.shape

        if n < 2 or m < 1:
            return {
                "status": "insufficient_data",
                "results": {"note": "随机优化需要至少 2 行 1 列数据"},
                "metrics": {"n_samples": n, "n_features": m},
            }

        # 构建目标系数
        if m >= 2:
            c_base = data[:, -1]
            constraints_data = data[:, :-1]
        else:
            c_base = data[:, 0]
            constraints_data = data

        total_capacity = float(np.max(np.abs(c_base)) * n * 0.8)
        if total_capacity <= 0:
            total_capacity = n * 1.0

        bounds = [(0, float(max(abs(ci), 1.0))) for ci in c_base]

        # 步骤 1: 确定性基线
        baseline = self._compute_lp_stub(data, formulation)

        # 步骤 2: 蒙特卡洛场景模拟
        n_scenarios = 100
        rng = np.random.RandomState(42)
        scenario_objs = []
        scenario_solutions = []

        for s in range(n_scenarios):
            # 对系数加入 ±10% 随机扰动
            noise = 1.0 + rng.uniform(-0.1, 0.1, size=n)
            c_noisy = c_base * noise

            # 构建扰动数据矩阵
            data_noisy = data.copy()
            if m >= 2:
                data_noisy[:, -1] = c_noisy
            else:
                data_noisy[:, 0] = c_noisy

            # 求解扰动场景
            try:
                from scipy.optimize import linprog

                c_min = -np.abs(c_noisy)
                A_ub = np.ones((1, n))
                b_ub = np.array([total_capacity])

                if constraints_data.shape[1] >= 1:
                    for j in range(min(constraints_data.shape[1], 3)):
                        col = np.abs(constraints_data[:, j])
                        if col.sum() > 0:
                            A_ub = np.vstack([A_ub, col.reshape(1, -1)])
                            b_ub = np.append(b_ub, float(col.sum() * 0.8))

                result = linprog(
                    c=c_min, A_ub=A_ub, b_ub=b_ub,
                    bounds=bounds, method="highs",
                )

                if result.success:
                    scenario_objs.append(-result.fun)
                    scenario_solutions.append(result.x.tolist())
                else:
                    # 使用 numpy 启发式
                    np_result = self._compute_lp_numpy(
                        data_noisy, c_noisy, constraints_data, bounds, total_capacity
                    )
                    scenario_objs.append(np_result["results"]["optimal_objective"])
                    scenario_solutions.append(np_result["results"]["optimal_solution"])
            except Exception:
                # 降级到 numpy
                np_result = self._compute_lp_numpy(
                    data_noisy, c_noisy, constraints_data, bounds, total_capacity
                )
                scenario_objs.append(np_result["results"]["optimal_objective"])
                scenario_solutions.append(np_result["results"]["optimal_solution"])

        scenario_objs = np.array(scenario_objs)
        scenario_solutions = np.array(scenario_solutions)

        # 步骤 3: 统计分析
        mean_solution = scenario_solutions.mean(axis=0)
        std_solution = scenario_solutions.std(axis=0)

        return {
            "status": "success",
            "results": {
                "baseline_solution": baseline.get("results", {}).get("optimal_solution", []),
                "baseline_objective": baseline.get("results", {}).get("optimal_objective", 0),
                "robust_solution": mean_solution.tolist(),
                "solution_std": std_solution.tolist(),
                "expected_objective": float(scenario_objs.mean()),
                "worst_case_objective": float(scenario_objs.min()),
                "best_case_objective": float(scenario_objs.max()),
                "n_scenarios": n_scenarios,
                "solver": "monte_carlo_lp_scipy",
            },
            "metrics": {
                "n_samples": n,
                "n_features": m,
                "expected_objective": float(scenario_objs.mean()),
                "objective_std": float(scenario_objs.std()),
                "worst_case": float(scenario_objs.min()),
                "robustness_ratio": float(scenario_objs.min() / scenario_objs.mean()) if scenario_objs.mean() != 0 else 0,
                "n_scenarios": n_scenarios,
                "baseline_objective": baseline.get("results", {}).get("optimal_objective", 0),
            },
            "intermediate_values": {
                "scenario_objectives": scenario_objs.tolist()[:20],  # 只保存前 20 个
                "solution_cv": (std_solution / (np.abs(mean_solution) + 1e-10)).tolist(),  # 变异系数
            },
        }

    def _compute_generic(self, data: np.ndarray, method_name: str) -> dict:
        """通用计算（描述性统计 + 基础分析）。"""
        n, m = data.shape

        # 描述性统计
        stats = {
            "mean": np.mean(data, axis=0).tolist(),
            "std": np.std(data, axis=0).tolist(),
            "min": np.min(data, axis=0).tolist(),
            "max": np.max(data, axis=0).tolist(),
            "median": np.median(data, axis=0).tolist(),
        }

        # 相关性矩阵（如果有多列）
        correlation = None
        if m >= 2:
            try:
                corr_matrix = np.corrcoef(data.T)
                correlation = corr_matrix.tolist()
            except Exception:
                pass

        # 如果是模拟类方法，附加随机采样结果
        if "蒙特卡洛" in method_name or "模拟" in method_name or "仿真" in method_name:
            # 简单蒙特卡洛模拟：对每列进行 N 次随机采样
            n_simulations = 1000
            rng = np.random.default_rng(seed=42)

            # 使用数据的均值和标准差构建分布
            means = np.mean(data, axis=0)
            stds = np.std(data, axis=0)
            stds[stds == 0] = 0.01  # 避免零标准差

            # 生成模拟样本
            simulated = rng.normal(means, stds, size=(n_simulations, m))

            # 计算模拟统计量
            sim_means = np.mean(simulated, axis=0)
            sim_stds = np.std(simulated, axis=0)
            sim_p5 = np.percentile(simulated, 5, axis=0)
            sim_p95 = np.percentile(simulated, 95, axis=0)

            return {
                "status": "success",
                "results": {
                    "method": method_name,
                    "data_summary": stats,
                    "simulation": {
                        "n_simulations": n_simulations,
                        "simulated_means": sim_means.tolist(),
                        "simulated_stds": sim_stds.tolist(),
                        "confidence_interval_90": {
                            "lower": sim_p5.tolist(),
                            "upper": sim_p95.tolist(),
                        },
                    },
                },
                "metrics": {
                    "n_samples": n,
                    "n_features": m,
                    "n_simulations": n_simulations,
                    "simulation_seed": 42,
                },
                "intermediate_values": {
                    "correlation_matrix": correlation if correlation else None,
                    "distribution_params": {
                        "means": means.tolist(),
                        "stds": stds.tolist(),
                    },
                },
            }

        return {
            "status": "generic_stats",
            "results": {
                "method": method_name,
                "data_summary": stats,
            },
            "metrics": {
                "n_samples": n,
                "n_features": m,
            },
            "intermediate_values": {
                "correlation_matrix": correlation if correlation else None,
            },
        }

    # ------------------------------------------------------------------
    # 结果表格生成
    # ------------------------------------------------------------------

    def _generate_tables(
        self,
        method_name: str,
        math_task: str,
        computation: dict,
        data_prep: dict,
        context: CurrentQuestionContext,
    ) -> list[str]:
        """生成结果表格描述。"""
        tables: list[str] = []
        status = computation.get("status", "unknown")
        results = computation.get("results", {})

        if status == "success":
            if "熵权法" in method_name:
                tables.append("表: 各指标权重和熵值")
                tables.append("表: 各样本综合得分与排名")
            elif "TOPSIS" in method_name:
                tables.append("表: 各方案相对接近度与排名")
                tables.append("表: 正负理想解值")
            elif "线性回归" in method_name:
                tables.append("表: 回归系数与统计量")
                tables.append("表: 预测值与残差")
            elif "灰色" in method_name or "GM" in method_name:
                tables.append("表: GM(1,1) 参数与拟合值")
                tables.append("表: 未来预测值")
            elif "规划" in method_name:
                tables.append("表: 最优解")
                tables.append("表: 约束条件满足情况")
            else:
                tables.append(f"表: {method_name} 计算结果")
        elif status == "no_data":
            tables.append(f"表: {method_name} 结果（无数据，待填充）")
        else:
            tables.append(f"表: {method_name} 结果（{status}）")

        return tables

    # ------------------------------------------------------------------
    # 图表描述生成
    # ------------------------------------------------------------------

    def _generate_figure_descriptions(
        self,
        method_name: str,
        math_task: str,
        computation: dict,
        context: CurrentQuestionContext,
    ) -> list[str]:
        """生成图表描述（非实际图片）。"""
        figures: list[str] = []
        status = computation.get("status", "unknown")

        if status == "success":
            if "熵权法" in method_name:
                figures.append("图: 各指标权重柱状图")
                figures.append("图: 综合得分排名条形图")
            elif "TOPSIS" in method_name:
                figures.append("图: 相对接近度雷达图")
                figures.append("图: 各方案到理想解距离散点图")
            elif "线性回归" in method_name:
                figures.append("图: 回归拟合散点图")
                figures.append("图: 残差分析图")
            elif "灰色" in method_name or "GM" in method_name:
                figures.append("图: 原始值与拟合值对比折线图")
                figures.append("图: 未来预测趋势图")
            elif "规划" in method_name:
                figures.append("图: 最优解可视化")
            else:
                figures.append(f"图: {method_name} 结果可视化")

        return figures
