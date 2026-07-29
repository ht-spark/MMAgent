"""L3 数据子图。

对应 architecture.md §4 L3 与 plan.md Phase 6：
  plan_data → preprocess → quality_report + G4

流程：
  1. plan_data：基于 selected_models + data_inventory 生成字段级 DataRequirement
  2. preprocess：用 pandas 清洗（缺失值填均值/众数、剔除常量列、类型转换）
  3. quality_report：生成数据质量报告
  4. G4 校验

简化版（demo）：
  - 单文件处理（多文件场景下依次处理）
  - 缺失策略：数值列均值 / 分类列众数
  - 原始数据不覆盖，写入 artifacts/<run_id>/data/processed.csv
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..gates.g4_data import G4DataGate
from ..schemas.common import GateResult
from ..schemas.data import (
    DataRequirement,
    PreprocessingReport,
    PreprocessingStep,
    QualityIssue,
    QualityReport,
)
from ..schemas.model import ModelScore
from ..schemas.problem import DataInventory


class L3DataSubgraph:
    """L3 数据子图（demo 简化版）。

    Args:
        output_dir: 产物输出根目录（默认 artifacts/<run_id>/data）。
        max_attempts: G4 失败时最大重试次数。
    """

    def __init__(
        self,
        output_dir: str | Path | None = None,
        max_attempts: int = 3,
    ) -> None:
        self.output_dir = Path(output_dir) if output_dir else Path("artifacts/default/data")
        self.gate = G4DataGate()
        self.max_attempts = max(1, max_attempts)

    def run(
        self,
        data_path: str | Path,
        data_inventory: DataInventory,
        selected_models: list[ModelScore] | None = None,
    ) -> dict:
        """执行 L3 数据流程。

        Args:
            data_path: 数据文件路径。
            data_inventory: L0 生成的 DataInventory。
            selected_models: 可选，L2 选中的模型（用于推断字段需求）。

        Returns:
            State 部分更新 dict：
              - data_requirements / preprocessing_report / quality_report
              - processed_data_path / gate_result / workflow_status
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 1. plan_data
        requirements = self._plan_data(data_inventory, selected_models or [])

        # 2-3. preprocess + quality_report（带 G4 重试）
        quality_report: QualityReport | None = None
        preprocessing_report: PreprocessingReport | None = None
        processed_path: Path | None = None
        gate_result: GateResult | None = None

        for attempt in range(1, self.max_attempts + 1):
            # preprocess
            preprocessing_report, processed_path = self._preprocess(
                data_path, data_inventory, requirements
            )

            # quality_report
            quality_report = self._build_quality_report(
                processed_path, data_inventory
            )

            # G4 校验
            state = {
                "data_requirements": requirements,
                "quality_report": quality_report,
                "_g4_budget_used": attempt - 1,
            }
            gate_result = self.gate.evaluate(state)
            if gate_result.passed:
                break

        # 决定 workflow_status
        if gate_result is None or not gate_result.passed:
            if gate_result and gate_result.action == "human":
                status = "l3_human_review"
            else:
                status = "l3_failed"
        else:
            status = "l3_completed"

        return {
            "data_requirements": requirements,
            "preprocessing_report": preprocessing_report,
            "quality_report": quality_report,
            "processed_data_path": str(processed_path) if processed_path else "",
            "gate_result": gate_result,
            "workflow_status": status,
        }

    # ------------------------------------------------------------------
    # 内部：plan_data
    # ------------------------------------------------------------------

    def _plan_data(
        self,
        inventory: DataInventory,
        selected_models: list[ModelScore],
    ) -> list[DataRequirement]:
        """基于 DataInventory + selected_models 生成字段级需求。"""
        requirements: list[DataRequirement] = []

        # 收集所有 candidate_id（通过 scores 找 candidates）
        # 简化：从 inventory 直接推断每个字段的需求
        for field in inventory.fields:
            if field.dtype in ("int", "float"):
                missing_strategy = "mean"
                risk = "medium" if field.missing_rate > 0.2 else "low"
            elif field.dtype in ("str", "category"):
                missing_strategy = "drop"
                risk = "medium" if field.missing_rate > 0.2 else "low"
            else:
                missing_strategy = "none"
                risk = "low"

            requirements.append(
                DataRequirement(
                    name=field.name,
                    field=field.name,
                    type=field.dtype,
                    unit=field.unit_hint or "",
                    source="附件",
                    missing_strategy=missing_strategy,
                    preprocessing_method=(
                        f"缺失值{missing_strategy}填充"
                        if field.missing_count > 0 else "无需处理"
                    ),
                    quality_risk=risk,
                )
            )
        return requirements

    # ------------------------------------------------------------------
    # 内部：preprocess
    # ------------------------------------------------------------------

    def _preprocess(
        self,
        data_path: str | Path,
        inventory: DataInventory,
        requirements: list[DataRequirement],
    ) -> tuple[PreprocessingReport, Path]:
        """执行预处理，写入 processed.csv（原始数据不覆盖）。"""
        df = pd.read_csv(data_path, encoding="utf-8")
        rows_before = len(df)
        steps: list[PreprocessingStep] = []

        for req in requirements:
            if req.field not in df.columns:
                continue

            # 缺失值处理
            if req.missing_strategy == "mean" and df[req.field].dtype.kind in "biufc":
                mean_val = df[req.field].mean()
                if pd.notna(mean_val):
                    df[req.field] = df[req.field].fillna(mean_val)
                    steps.append(PreprocessingStep(
                        operation="fillna_mean",
                        target_column=req.field,
                        parameters={"value": float(mean_val)},
                    ))
            elif req.missing_strategy == "drop":
                df = df.dropna(subset=[req.field])
                steps.append(PreprocessingStep(
                    operation="dropna",
                    target_column=req.field,
                ))

            # 剔除常量列（unique_count == 1）
            if df[req.field].nunique(dropna=True) <= 1:
                df = df.drop(columns=[req.field])
                steps.append(PreprocessingStep(
                    operation="drop_constant",
                    target_column=req.field,
                ))

        # 写盘
        processed_path = self.output_dir / "processed.csv"
        df.to_csv(processed_path, index=False, encoding="utf-8")

        return (
            PreprocessingReport(
                steps=steps,
                output_path=str(processed_path),
                rows_before=rows_before,
                rows_after=len(df),
                columns_after=list(df.columns),
            ),
            processed_path,
        )

    # ------------------------------------------------------------------
    # 内部：quality_report
    # ------------------------------------------------------------------

    def _build_quality_report(
        self, processed_path: Path, original_inventory: DataInventory
    ) -> QualityReport:
        """基于清洗后数据生成质量报告。"""
        df = pd.read_csv(processed_path)
        n_rows, n_cols = df.shape

        # 各字段缺失率
        missing_rates = {}
        for col in df.columns:
            n_missing = int(df[col].isna().sum())
            missing_rates[col] = round(n_missing / n_rows if n_rows > 0 else 0.0, 4)

        # 重复行
        duplicate_rows = int(df.duplicated().sum())

        # 常量列（基于原始 inventory 检测，因为处理后列已被剔除）
        constant_columns = [
            f.name for f in original_inventory.fields
            if f.unique_count <= 1
        ]

        # 问题列表
        issues: list[QualityIssue] = []
        if n_rows == 0:
            issues.append(QualityIssue(
                kind="missing_rate", severity="high",
                message="处理后无数据行", target="",
            ))
        for c in constant_columns:
            issues.append(QualityIssue(
                kind="constant_column", severity="medium",
                message=f"列 {c} 为常量，无区分度", target=c,
            ))
        if duplicate_rows > 0:
            issues.append(QualityIssue(
                kind="duplicate", severity="low",
                message=f"{duplicate_rows} 行重复", target="",
            ))

        # 综合评分
        avg_missing = (
            sum(missing_rates.values()) / max(1, len(missing_rates))
        )
        overall_score = round(
            max(0.0, 1.0 - avg_missing * 0.5 - len(constant_columns) * 0.1),
            4,
        )

        return QualityReport(
            row_count=n_rows,
            column_count=n_cols,
            missing_rates=missing_rates,
            duplicate_rows=duplicate_rows,
            constant_columns=constant_columns,
            issues=issues,
            overall_score=overall_score,
        )