"""
读取任务和附件，并生成供后续智能体使用的数据画像。

职责：
  1. 读取任务文档（Markdown/TXT/PDF/DOCX 文本提取）
  2. 读取 CSV、Excel、JSON 数据文件；Excel 遍历全部 Sheet
  3. 生成确定性数据画像（行列数、字段类型、缺失率、单位线索、时间维度）
  4. 将原始输入登记为只读产物

数据画像由确定性工具生成（file_tools.py），不依赖 LLM。
画像的作用是约束后续方法选择：无时间列淘汰时间序列、样本量过小淘汰高参数模型。

画像覆盖六个维度：
  1. 数据基本面 — 规模、类型构成、粒度（候选键）、时空覆盖
  2. 数据质量 — 缺失/重复/离群/类型混合（编码一致性）
  3. 分布特征 — 偏态/峰态/取值范围、高相关列对（共线性）
  4. 业务语义 — 单位线索、目标不平衡度
  5. 时空结构 — 时间覆盖、空间坐标列
  6. 建模假设预判 — modeling_constraints 硬约束
"""
from __future__ import annotations

import time
from pathlib import Path

from ..runtime.logging import get_run_logger, log_step
from ..schemas.context import (
    DataProfile,
    DataProfileIssue,
    FieldProfile,
    FileRecord,
    TableProfile,
    TableRelationship,
)
from ..schemas.problem import DataField, DataInventory
from ..tools.file_tools import generate_data_inventories


def run_intake(state: dict) -> dict:
    """LangGraph 节点：输入摄入。

    读取任务和附件，生成数据画像，登记原始输入。

    Args:
        state: 项目状态。需要包含 data_paths 和 output_dir。

    Returns:
        状态更新字典，包含 data_profile 和 workflow_status。
    """
    data_paths = state.get("data_paths", [])
    output_dir = state.get("output_dir", "artifacts/default")

    logger = get_run_logger()
    log_step(
        logger,
        "workflow.intake",
        "started",
        detail=f"开始输入摄入，待读取 {len(data_paths)} 个数据文件",
    )

    # 生成数据画像（确定性工具，Excel 自动展开所有 Sheet）
    t0 = time.monotonic()
    data_profile = _build_data_profile(data_paths, output_dir)
    log_step(
        logger,
        "workflow.intake",
        "completed",
        duration=time.monotonic() - t0,
        detail=(
            f"完成数据画像: {len(data_profile.files)} 个文件、"
            f"{len(data_profile.tables)} 张表、{len(data_profile.fields)} 个字段"
        ),
    )

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
    然后转换为新架构的 DataProfile，并登记画像产物。

    Args:
        data_paths: 数据文件路径列表。
        output_dir: 画像报告输出目录。

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
    profile = _convert_inventories_to_profile(inventories, data_paths)

    # 登记画像产物（DataProfile 报告 + 各表 inventory JSON）
    if inventory_output is not None:
        _register_profile_artifacts(profile, inventory_output)

    return profile


def _register_profile_artifacts(profile: DataProfile, context_dir: Path) -> None:
    """登记画像产物路径：DataProfile 报告 + 各表 inventory JSON。

    对应 architecture.md §3.2 artifacts（画像报告、描述统计路径）。
    """
    artifacts: list[str] = []

    # 数据画像报告（DataProfile 全量 JSON）
    report_path = context_dir / "data_profile_report.json"
    report_path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    artifacts.append(str(report_path))

    # 各表确定性画像 JSON（file_tools 已生成）
    for inv_path in sorted(context_dir.glob("data_inventory_*.json")):
        artifacts.append(str(inv_path))

    profile.artifacts = artifacts


def _convert_inventories_to_profile(
    inventories: list[DataInventory],
    original_paths: list[str],
) -> DataProfile:
    """将 DataInventory 列表转换为 DataProfile。

    覆盖数据画像 6 大维度：
      1. 基本面 — FileRecord（含真实大小）/ TableProfile（规模、样例、候选键、时空覆盖）
      2. 质量 — quality_issues（缺失/重复/离群/不平衡/类型混合）
      3. 分布 — FieldProfile(skew/kurt/value_range) + TableProfile.correlated_pairs
      4. 语义 — unit_hint / max_category_share（目标不平衡）
      5. 时空 — is_time_column / time_coverage / spatial_columns
      6. 建模假设 — modeling_constraints 合并去重

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
    modeling_constraints: list[str] = []

    # 登记已成功读取的文件
    read_file_names: set[str] = set()
    for inv in inventories:
        # DataInventory 的 file_name 可能是 "filename.xlsx::sheet_name" 格式
        raw_name = inv.file_name.split("::")[0] if "::" in inv.file_name else inv.file_name
        read_file_names.add(raw_name)

        sheet_name = inv.file_name.split("::")[1] if "::" in inv.file_name else ""

        # FileRecord（每个原始文件一个，避免重复；file_size 取真实大小）
        if not any(f.file_name == raw_name for f in files):
            files.append(FileRecord(
                file_name=raw_name,
                file_path=inv.file_path,
                file_type=inv.file_type,
                file_size=inv.file_size,
                read_status="success",
            ))

        # TableProfile：规模/样例/质量/粒度/时空覆盖
        tables.append(TableProfile(
            source_file=raw_name,
            sheet_name=sheet_name,
            n_rows=inv.n_rows,
            n_cols=inv.n_cols,
            field_names=[f.name for f in inv.fields],
            sample_rows=inv.sample_rows,
            duplicate_rows=inv.duplicate_rows,
            duplicate_rate=inv.duplicate_rate,
            candidate_keys=inv.candidate_keys,
            correlated_pairs=inv.correlated_pairs,
            time_coverage=_build_time_coverage_text(inv),
            spatial_columns=inv.spatial_columns,
        ))

        # 表级质量 issues（重复行、高相关列对）
        _append_table_quality_issues(quality_issues, inv, raw_name, sheet_name)

        # FieldProfile + 字段级质量 issues
        for df in inv.fields:
            fields.append(FieldProfile(
                source_file=raw_name,
                sheet_name=sheet_name,
                field_name=df.name,
                dtype=df.dtype,
                unit_hint=df.unit_hint,
                missing_count=df.missing_count,
                missing_rate=df.missing_rate,
                unique_count=df.unique_count,
                value_range=_build_value_range(df),
                is_time_column=df.is_time_column,
                is_candidate_key=df.is_candidate_key,
                is_spatial=df.is_spatial,
                skewness=df.numeric_stats.skewness if df.numeric_stats else None,
                kurtosis=df.numeric_stats.kurtosis if df.numeric_stats else None,
                outlier_rate=df.numeric_stats.outlier_rate if df.numeric_stats else 0.0,
                max_category_share=(
                    df.categorical_stats.max_category_share
                    if df.categorical_stats else None
                ),
                numeric_parseable_rate=df.numeric_parseable_rate,
            ))
            _append_field_quality_issues(quality_issues, df, raw_name, sheet_name)

        # 建模假设预判：合并去重
        for c in inv.modeling_constraints:
            if c not in modeling_constraints:
                modeling_constraints.append(c)

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

    # 表间关联（同名列 + 候选键加权置信度）
    relationships = _detect_table_relationships(tables)

    # 初步发现（6 维度汇总）
    findings = _build_preliminary_findings(
        files, tables, fields, quality_issues, relationships, modeling_constraints,
    )

    return DataProfile(
        files=files,
        tables=tables,
        fields=fields,
        relationships=relationships,
        quality_issues=quality_issues,
        preliminary_findings=findings,
        modeling_constraints=modeling_constraints,
        artifacts=[],
    )


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _build_time_coverage_text(inv: DataInventory) -> str:
    """构建时间覆盖文本（时空结构）。"""
    if not inv.time_columns:
        return ""
    if inv.time_min and inv.time_max:
        return f"{inv.time_min} ~ {inv.time_max} ({inv.time_unique_count} 个时间点)"
    return f"{inv.time_unique_count} 个时间点"


def _format_number(v: float) -> str:
    """数值规范化：整数去尾零，小数用 4 位有效数字（避免科学计数法）。"""
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.4g}"


def _build_value_range(df: DataField) -> str:
    """结构化的取值范围文本：数值列 'min~max'，分类列 top3（带频次）。"""
    if df.numeric_stats:
        return f"{_format_number(df.numeric_stats.min)}~{_format_number(df.numeric_stats.max)}"
    if df.categorical_stats and df.categorical_stats.top_values:
        top3 = [
            f"{tv.value}({tv.count})"
            for tv in df.categorical_stats.top_values[:3]
        ]
        return " / ".join(top3)
    return ""


def _append_table_quality_issues(
    issues: list[DataProfileIssue],
    inv: DataInventory,
    raw_name: str,
    sheet_name: str,
) -> None:
    """表级质量 issue：重复行、高相关列对（共线性）。"""
    # 重复噪声
    if inv.duplicate_rate > 0:
        issues.append(DataProfileIssue(
            source_file=raw_name,
            sheet_name=sheet_name,
            issue_type="duplicate",
            severity="high" if inv.duplicate_rate > 0.05 else "medium",
            message=f"存在 {inv.duplicate_rows} 行完全重复（占比 {inv.duplicate_rate:.1%}）",
            target=raw_name,
        ))

    # 共线性（分布特征·多变量）
    for cp in inv.correlated_pairs:
        issues.append(DataProfileIssue(
            source_file=raw_name,
            sheet_name=sheet_name,
            issue_type="high_correlation",
            severity="medium",
            message=f"字段 '{cp.col_a}' 与 '{cp.col_b}' 相关系数 {cp.correlation:.2f}",
            target=f"{cp.col_a}-{cp.col_b}",
        ))


def _append_field_quality_issues(
    issues: list[DataProfileIssue],
    df: DataField,
    raw_name: str,
    sheet_name: str,
) -> None:
    """字段级质量 issue：缺失率、常量列、离群值、不平衡、类型混合。"""
    # 缺失率
    if df.missing_rate > 0.5:
        issues.append(DataProfileIssue(
            source_file=raw_name, sheet_name=sheet_name,
            issue_type="missing_rate", severity="high",
            message=f"字段 '{df.name}' 缺失率 {df.missing_rate:.1%}",
            target=df.name,
        ))
    elif df.missing_rate > 0.2:
        issues.append(DataProfileIssue(
            source_file=raw_name, sheet_name=sheet_name,
            issue_type="missing_rate", severity="medium",
            message=f"字段 '{df.name}' 缺失率 {df.missing_rate:.1%}",
            target=df.name,
        ))

    # 常量列（无信息量）
    if df.unique_count <= 1 and df.missing_rate == 0:
        issues.append(DataProfileIssue(
            source_file=raw_name, sheet_name=sheet_name,
            issue_type="constant_column", severity="low",
            message=f"字段 '{df.name}' 为常量列（唯一值数={df.unique_count}）",
            target=df.name,
        ))

    # 离群值（IQR 法；空间坐标列/时间列不做数值离群判定，避免统计误报）
    if (
        not df.is_spatial
        and not df.is_time_column
        and df.numeric_stats
        and df.numeric_stats.outlier_rate > 0.05
    ):
        rate = df.numeric_stats.outlier_rate
        issues.append(DataProfileIssue(
            source_file=raw_name, sheet_name=sheet_name,
            issue_type="outlier",
            severity="high" if rate > 0.2 else "medium",
            message=f"字段 '{df.name}' 离群率 {rate:.1%}（IQR 法）",
            target=df.name,
        ))

    # 类别不平衡（目标变量特殊性）
    share = df.categorical_stats.max_category_share if df.categorical_stats else None
    if share is not None and share >= 0.8:
        issues.append(DataProfileIssue(
            source_file=raw_name, sheet_name=sheet_name,
            issue_type="imbalance",
            severity="high" if share >= 0.9 else "medium",
            message=f"字段 '{df.name}' 最大类别占比 {share:.1%}（不平衡）",
            target=df.name,
        ))

    # 编码一致性（类型混合：字符列中混入可解析为数值的值）
    if df.numeric_parseable_rate is not None and 0 < df.numeric_parseable_rate < 1:
        issues.append(DataProfileIssue(
            source_file=raw_name, sheet_name=sheet_name,
            issue_type="encoding", severity="medium",
            message=(
                f"字段 '{df.name}' 字符列中 {df.numeric_parseable_rate:.1%} 的值"
                "可解析为数值，疑似类型混合/编码不一致"
            ),
            target=df.name,
        ))


def _detect_table_relationships(
    tables: list[TableProfile],
) -> list[TableRelationship]:
    """表间关联候选：跨表同名列 + 候选键加权置信度。

    置信度规则（architecture.md §3.2 relationships：关联键与置信度）：
      - 共享列在任一张表中是候选主键 → 0.8（强关联候选）
      - 普通同名列 → 0.5（提示级，需人工确认）

    Args:
        tables: 表画像列表。

    Returns:
        表间关联候选列表（每对表最多 5 条，按置信度降序）。
    """
    rels: list[TableRelationship] = []
    for i in range(len(tables)):
        for j in range(i + 1, len(tables)):
            t1, t2 = tables[i], tables[j]
            if t1.source_file == t2.source_file and t1.sheet_name == t2.sheet_name:
                continue

            shared = sorted(set(t1.field_names) & set(t2.field_names))
            if not shared:
                continue

            key_cols_1 = set(t1.candidate_keys)
            key_cols_2 = set(t2.candidate_keys)

            # 按置信度排序，优先候选键关联
            candidates = sorted(
                (
                    (0.8 if (col in key_cols_1 or col in key_cols_2) else 0.5, col)
                    for col in shared
                ),
                reverse=True,
            )

            left = t1.source_file if not t1.sheet_name else f"{t1.source_file}::{t1.sheet_name}"
            right = t2.source_file if not t2.sheet_name else f"{t2.source_file}::{t2.sheet_name}"

            for conf, col in candidates[:5]:
                rels.append(TableRelationship(
                    left_table=left,
                    left_field=col,
                    right_table=right,
                    right_field=col,
                    confidence=conf,
                ))
    return rels


def _build_preliminary_findings(
    files: list[FileRecord],
    tables: list[TableProfile],
    fields: list[FieldProfile],
    quality_issues: list[DataProfileIssue],
    relationships: list[TableRelationship],
    modeling_constraints: list[str],
) -> list[str]:
    """构建初步发现（6 维度汇总，供后续节点快速浏览）。"""
    findings: list[str] = []
    total_tables = len(tables)
    total_rows = sum(t.n_rows for t in tables)
    total_fields = len(fields)

    # 1. 基本面：规模与类型构成
    if total_tables > 0:
        findings.append(
            f"共读取 {len(files)} 个文件、{total_tables} 张表、{total_rows} 行、{total_fields} 个字段"
        )
        n_num = sum(1 for f in fields if f.dtype in ("int", "float"))
        n_cat = sum(1 for f in fields if f.dtype in ("str", "category", "bool"))
        n_time = sum(1 for f in fields if f.is_time_column)
        n_spatial = sum(1 for f in fields if f.is_spatial)
        parts = [f"数值列 {n_num}", f"分类列 {n_cat}", f"时间列 {n_time}"]
        if n_spatial:
            parts.append(f"空间列 {n_spatial}")
        findings.append("字段构成: " + "、".join(parts))

    # 粒度：候选主键
    key_tables = [t for t in tables if t.candidate_keys]
    if key_tables:
        detail = "; ".join(
            f"{t.source_file}({','.join(t.candidate_keys[:3])})"
            for t in key_tables[:3]
        )
        findings.append(f"候选主键: {detail}")

    # 2. 质量摘要
    high_issues = [q for q in quality_issues if q.severity == "high"]
    dup_tables = [t for t in tables if t.duplicate_rate > 0]
    if high_issues:
        findings.append(f"高严重度质量问题 {len(high_issues)} 项")
    if dup_tables:
        findings.append(f"{len(dup_tables)} 张表存在重复行")

    # 5. 时空结构
    time_tables = [t for t in tables if t.time_coverage]
    if time_tables:
        findings.append(f"时间维度: {time_tables[0].time_coverage}")
    spatial_tables = [t for t in tables if t.spatial_columns]
    if spatial_tables:
        findings.append(
            f"空间坐标列: {', '.join(spatial_tables[0].spatial_columns[:3])}"
        )

    # 关联候选
    if relationships:
        findings.append(f"检测到 {len(relationships)} 组表间关联候选")

    # 6. 建模假设预判
    if modeling_constraints:
        findings.append(f"建模约束 {len(modeling_constraints)} 条（详见 modeling_constraints）")

    return findings
