"""输入摄入工作流节点。

对应 architecture.md §4.1 输入摄入和 plan.md Phase 1.1-1.3。

职责：
  1. 读取题目文档（Markdown/TXT/PDF/DOCX 文本提取）
  2. 读取 CSV、Excel、JSON 数据文件；Excel 遍历全部 Sheet
  3. 生成确定性数据画像（行列数、字段类型、缺失率、单位线索、时间维度）
  4. 将原始输入登记为只读产物

数据画像由确定性工具生成（file_tools.py），不依赖 LLM。
画像的作用是约束后续方法选择：无时间列淘汰时间序列、样本量过小淘汰高参数模型。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..schemas.context import (
    DataProfile,
    DataProfileIssue,
    FieldProfile,
    FileRecord,
    TableProfile,
)
from ..schemas.problem import DataInventory
from ..tools.file_tools import generate_data_inventories, read_file


def run_intake(state: dict) -> dict:
    """LangGraph 节点：输入摄入。

    读取题目和附件，生成数据画像，登记原始输入。

    Args:
        state: 项目状态。需要包含 data_paths 和 output_dir。

    Returns:
        状态更新字典，包含 data_profile 和 workflow_status。
    """
    data_paths = state.get("data_paths", [])
    output_dir = state.get("output_dir", "artifacts/default")

    # 生成数据画像（确定性工具，Excel 自动展开所有 Sheet）
    data_profile = _build_data_profile(data_paths, output_dir)

    return {
        "data_profile": data_profile,
        "workflow_status": "intake_ready",
    }


def _build_data_profile(
    data_paths: list[str],
    output_dir: str | None = None,
) -> DataProfile:
    """从数据文件列表构建 DataProfile。

    复用 file_tools.generate_data_inventories 生成 DataInventory 列表，
    然后转换为新架构的 DataProfile。

    Args:
        data_paths: 数据文件路径列表。
        output_dir: 可选的画像报告输出目录。

    Returns:
        DataProfile 对象。
    """
    if not data_paths:
        return DataProfile(preliminary_findings=["无附件数据"])

    # 使用确定性工具生成画像（Excel 自动展开所有 Sheet）
    inventory_output = None
    if output_dir:
        inventory_output = Path(output_dir) / "context"
        inventory_output.mkdir(parents=True, exist_ok=True)

    inventories = generate_data_inventories(data_paths, output_dir=inventory_output)

    # 转换为 DataProfile
    return _convert_inventories_to_profile(inventories, data_paths)


def _convert_inventories_to_profile(
    inventories: list[DataInventory],
    original_paths: list[str],
) -> DataProfile:
    """将 DataInventory 列表转换为 DataProfile。

    Args:
        inventories: 确定性工具生成的数据画像列表。
        original_paths: 原始文件路径列表（用于登记读取失败的文件）。

    Returns:
        DataProfile 对象。
    """
    files: list[FileRecord] = []
    tables: list[TableProfile] = []
    fields: list[FieldProfile] = []
    quality_issues: list[DataProfileIssue] = []
    findings: list[str] = []

    # 登记已成功读取的文件
    read_file_names: set[str] = set()
    for inv in inventories:
        # DataInventory 的 file_name 可能是 "filename.xlsx::sheet_name" 格式
        raw_name = inv.file_name.split("::")[0] if "::" in inv.file_name else inv.file_name
        read_file_names.add(raw_name)

        sheet_name = inv.file_name.split("::")[1] if "::" in inv.file_name else ""

        # FileRecord（每个原始文件一个，避免重复）
        if not any(f.file_name == raw_name for f in files):
            files.append(FileRecord(
                file_name=raw_name,
                file_path=inv.file_path,
                file_type=inv.file_type,
                file_size=0,  # DataInventory 不含文件大小，用 0 占位
                read_status="success",
            ))

        # TableProfile
        tables.append(TableProfile(
            source_file=raw_name,
            sheet_name=sheet_name,
            n_rows=inv.n_rows,
            n_cols=inv.n_cols,
            field_names=[f.name for f in inv.fields],
            sample_rows=[],  # 不保存样例行，避免过大
        ))

        # FieldProfile + 质量问题
        for df in inv.fields:
            value_range = ""
            if df.numeric_stats:
                value_range = f"{df.numeric_stats.min:.4g}~{df.numeric_stats.max:.4g}"
            elif df.categorical_stats and df.categorical_stats.top_values:
                top3 = [tv.value for tv in df.categorical_stats.top_values[:3]]
                value_range = " / ".join(top3)

            fields.append(FieldProfile(
                source_file=raw_name,
                sheet_name=sheet_name,
                field_name=df.name,
                dtype=df.dtype,
                unit_hint=df.unit_hint,
                missing_rate=df.missing_rate,
                unique_count=df.unique_count,
                value_range=value_range,
                is_time_column=df.is_time_column,
            ))

            # 提取质量问题
            if df.missing_rate > 0.5:
                quality_issues.append(DataProfileIssue(
                    source_file=raw_name, sheet_name=sheet_name,
                    issue_type="missing_rate", severity="high",
                    message=f"字段 '{df.name}' 缺失率 {df.missing_rate:.1%}",
                    target=df.name,
                ))
            elif df.missing_rate > 0.2:
                quality_issues.append(DataProfileIssue(
                    source_file=raw_name, sheet_name=sheet_name,
                    issue_type="missing_rate", severity="medium",
                    message=f"字段 '{df.name}' 缺失率 {df.missing_rate:.1%}",
                    target=df.name,
                ))

            # 常量列检测
            if df.unique_count <= 1 and df.missing_rate == 0:
                quality_issues.append(DataProfileIssue(
                    source_file=raw_name, sheet_name=sheet_name,
                    issue_type="constant_column", severity="low",
                    message=f"字段 '{df.name}' 为常量列（唯一值数={df.unique_count}）",
                    target=df.name,
                ))

    # 登记读取失败的文件
    for fp in original_paths:
        p = Path(fp)
        if p.name not in read_file_names:
            files.append(FileRecord(
                file_name=p.name,
                file_path=str(p.resolve()),
                file_type=p.suffix.lstrip(".").lower(),
                file_size=p.stat().st_size if p.exists() else 0,
                read_status="failed",
                error_message="文件读取或画像生成失败",
            ))

    # 初步发现
    total_tables = len(tables)
    total_rows = sum(t.n_rows for t in tables)
    total_fields = len(fields)
    has_time = any(f.is_time_column for f in fields)
    high_severity = sum(1 for q in quality_issues if q.severity == "high")

    if total_tables > 0:
        findings.append(f"共读取 {len(files)} 个文件、{total_tables} 张表、{total_rows} 行数据")
        findings.append(f"共 {total_fields} 个字段，其中时间列 {'存在' if has_time else '不存在'}")
    if high_severity > 0:
        findings.append(f"发现 {high_severity} 个高严重度数据质量问题")
    if has_time:
        time_cols = [f.field_name for f in fields if f.is_time_column]
        findings.append(f"时间维度列: {', '.join(time_cols[:5])}")

    return DataProfile(
        files=files,
        tables=tables,
        fields=fields,
        relationships=[],  # 表间关联在后续阶段检测
        quality_issues=quality_issues,
        preliminary_findings=findings,
        artifacts=[],
    )
