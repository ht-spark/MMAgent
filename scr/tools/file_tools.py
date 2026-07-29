"""文件读取与数据画像工具。

确定性工具，不依赖 LLM，可单测、可复现。

功能：
  - 读取 CSV / Excel / Markdown 文件
  - 对数据文件生成确定性画像（data_inventory）

对应 plan.md:
  - Phase 3.1: tools/file_tools.py — CSV/Excel/JSON/Markdown 读取
  - Phase 3.2: tools/data_tools.py 的 data_inventory — 附件确定性画像

画像包含：行列数、字段类型、缺失率、单位线索、时间维度。
它是 L2 硬过滤的关键输入：
  - 无时间列 → 淘汰 ARIMA
  - 样本量 < 30 → 淘汰机器学习类候选
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..schemas.problem import (
    CategoryCount,
    CategoricalStats,
    DataField,
    DataInventory,
    NumericStats,
)

__all__ = [
    "read_csv",
    "read_excel",
    "read_excel_all_sheets",
    "read_markdown",
    "read_file",
    "generate_data_inventory",
    "generate_data_inventories",
]

# ---------------------------------------------------------------------------
# 文件读取
# ---------------------------------------------------------------------------


def read_csv(path: str | Path, **kwargs: Any) -> pd.DataFrame:
    """读取 CSV 文件为 DataFrame。

    Args:
        path: CSV 文件路径。
        **kwargs: 透传给 pandas.read_csv 的参数。

    Returns:
        pandas DataFrame.

    Raises:
        FileNotFoundError: 文件不存在。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CSV file not found: {p}")
    # 默认用 utf-8，失败时回退 gbk（中文 Windows 常见编码）
    encoding = kwargs.pop("encoding", None)
    if encoding is None:
        try:
            return pd.read_csv(p, encoding="utf-8", **kwargs)
        except UnicodeDecodeError:
            return pd.read_csv(p, encoding="gbk", **kwargs)
    return pd.read_csv(p, encoding=encoding, **kwargs)


def read_excel(
    path: str | Path,
    sheet_name: str | int = 0,
    **kwargs: Any,
) -> pd.DataFrame:
    """读取 Excel 文件（单工作表）。

    Args:
        path: Excel 文件路径（.xlsx / .xls）。
        sheet_name: 工作表名称或索引，默认第一个。
        **kwargs: 透传给 pandas.read_excel 的参数。

    Returns:
        pandas DataFrame.

    Raises:
        FileNotFoundError: 文件不存在。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Excel file not found: {p}")
    return pd.read_excel(p, sheet_name=sheet_name, **kwargs)


def read_excel_all_sheets(
    path: str | Path,
    **kwargs: Any,
) -> dict[str, pd.DataFrame]:
    """读取 Excel 文件的所有工作表。

    Args:
        path: Excel 文件路径（.xlsx / .xls）。
        **kwargs: 透传给 pandas.read_excel 的参数。

    Returns:
        {sheet_name: DataFrame} 字典。

    Raises:
        FileNotFoundError: 文件不存在。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Excel file not found: {p}")
    sheets = pd.read_excel(p, sheet_name=None, **kwargs)
    # pandas 返回的 key 可能是 int（sheet 索引），统一转为 str
    return {str(k): v for k, v in sheets.items()}


def read_markdown(path: str | Path, encoding: str = "utf-8") -> str:
    """读取 Markdown / 纯文本文件为字符串。

    Args:
        path: 文件路径（.md / .markdown / .txt）。
        encoding: 文件编码，默认 utf-8。

    Returns:
        文件全文内容。

    Raises:
        FileNotFoundError: 文件不存在。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Markdown file not found: {p}")
    return p.read_text(encoding=encoding)


def read_file(path: str | Path) -> pd.DataFrame | str:
    """根据扩展名自动分发读取。

    Args:
        path: 文件路径。支持 .csv / .xlsx / .xls / .md / .markdown / .txt。

    Returns:
        DataFrame（表格文件）或 str（文本文件）。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 不支持的文件类型。
    """
    p = Path(path)
    ext = p.suffix.lower()

    if ext == ".csv":
        return read_csv(p)
    if ext in (".xlsx", ".xls"):
        return read_excel(p)
    if ext in (".md", ".markdown", ".txt"):
        return read_markdown(p)
    raise ValueError(
        f"Unsupported file type '{ext}'. "
        f"Supported: .csv, .xlsx, .xls, .md, .markdown, .txt"
    )


# ---------------------------------------------------------------------------
# 数据画像
# ---------------------------------------------------------------------------

# 时间列名称关键词（中英文）
_TIME_KEYWORDS = (
    "date", "time", "year", "month", "day", "hour",
    "日期", "时间", "年", "月", "日", "时",
)

# 单位线索正则（从字段名括号中提取）
_UNIT_PATTERNS: list[tuple[str, str]] = [
    (r"[\(\[（].*?(kg|g|吨|克|千克).*?[\)\]）]", "重量"),
    (r"[\(\[（].*?(km|m|cm|mm|米|千米|厘米|毫米).*?[\)\]）]", "长度"),
    (r"[\(\[（].*?(min|h|hour|sec|s|分|时|秒).*?[\)\]）]", "时长"),
    (r"[\(\[（].*?(%|百分|percent|percentage).*?[\)\]）]", "百分比"),
    (r"[\(\[（].*?(元|￥|¥|\$|dollar|rmb|yuan).*?[\)\]）]", "货币"),
    (r"[\(\[（].*?(℃|°c|度|温度|temp).*?[\)\]）]", "温度"),
    (r"[\(\[（].*?(hz|khz|mhz|ghz).*?[\)\]）]", "频率"),
    (r"[\(\[（].*?(w|kw|mw|瓦|千瓦).*?[\)\]）]", "功率"),
]


def _infer_dtype(series: pd.Series) -> str:
    """推断 pandas Series 的语义数据类型。"""
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_bool_dtype(series):
        return "bool"
    if pd.api.types.is_integer_dtype(series):
        return "int"
    if pd.api.types.is_float_dtype(series):
        return "float"
    if isinstance(series.dtype, pd.CategoricalDtype):
        return "category"
    # object 列：尝试判断是否可转为数值
    if series.dtype == "object":
        non_null = series.dropna()
        if len(non_null) > 0:
            numeric = pd.to_numeric(non_null, errors="coerce")
            if numeric.notna().all():
                # 全部可转数值
                if (numeric % 1 == 0).all():
                    return "int"
                return "float"
    return "str"


def _detect_time_column(series: pd.Series, name: str) -> bool:
    """检测列是否为时间维度。

    判定规则（任一满足即为时间列）：
      1. 字段名包含时间关键词
      2. pandas 已识别为 datetime 类型
      3. object 列可被 pd.to_datetime 成功解析（抽样检查）
    """
    name_lower = name.lower()
    if any(kw in name_lower for kw in _TIME_KEYWORDS):
        return True

    if pd.api.types.is_datetime64_any_dtype(series):
        return True

    if series.dtype == "object":
        sample = series.dropna().head(20)
        if len(sample) > 0:
            try:
                pd.to_datetime(sample, errors="raise")
                return True
            except (ValueError, TypeError):
                pass

    return False


def _detect_unit_hint(name: str) -> str | None:
    """从字段名中推断单位线索。"""
    for pattern, unit_type in _UNIT_PATTERNS:
        if re.search(pattern, name, re.IGNORECASE):
            return unit_type
    return None


def _safe_float(value: Any) -> float:
    """安全转为 float，处理 NaN / inf。"""
    v = float(value)
    if np.isnan(v) or np.isinf(v):
        return 0.0
    return v


def _build_field(name: str, series: pd.Series) -> DataField:
    """构建单个字段的画像。"""
    total = len(series)
    missing_count = int(series.isna().sum())
    missing_rate = missing_count / total if total > 0 else 0.0
    unique_count = int(series.nunique(dropna=True))

    # 示例值（非缺失的前 5 个，转为字符串）
    sample_values = [str(v) for v in series.dropna().head(5).tolist()]

    dtype = _infer_dtype(series)
    is_time = _detect_time_column(series, name)
    unit_hint = _detect_unit_hint(name)

    numeric_stats: NumericStats | None = None
    categorical_stats: CategoricalStats | None = None

    if dtype in ("int", "float"):
        numeric = pd.to_numeric(series, errors="coerce").dropna()
        if len(numeric) > 0:
            numeric_stats = NumericStats(
                min=_safe_float(numeric.min()),
                max=_safe_float(numeric.max()),
                mean=_safe_float(numeric.mean()),
                std=_safe_float(numeric.std()) if len(numeric) > 1 else 0.0,
                median=_safe_float(numeric.median()),
            )
    elif dtype in ("str", "category", "bool"):
        value_counts = series.value_counts().head(10)
        categorical_stats = CategoricalStats(
            top_values=[
                CategoryCount(value=str(k), count=int(v))
                for k, v in value_counts.items()
            ]
        )

    return DataField(
        name=name,
        dtype=dtype,
        missing_count=missing_count,
        missing_rate=missing_rate,
        unique_count=unique_count,
        sample_values=sample_values,
        unit_hint=unit_hint,
        is_time_column=is_time,
        numeric_stats=numeric_stats,
        categorical_stats=categorical_stats,
    )


def generate_data_inventory(
    file_path: str | Path,
    output_path: str | Path | None = None,
    sheet_name: str | int = 0,
) -> DataInventory:
    """对数据文件生成确定性画像。

    画像包含：行列数、字段类型、缺失率、单位线索、时间维度。
    它是 L2 硬过滤的关键输入。

    Args:
        file_path: 数据文件路径（.csv / .xlsx / .xls / .json）。
        output_path: 可选，画像 JSON 写入路径。
                     若提供则创建父目录并写入 ``DataInventory.model_dump_json()``。
        sheet_name: Excel 工作表名称或索引，默认第一个。

    Returns:
        DataInventory 对象。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 不支持的数据文件类型。
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"Data file not found: {p}")

    ext = p.suffix.lower()

    if ext == ".csv":
        df = read_csv(p)
        file_type = "csv"
    elif ext in (".xlsx", ".xls"):
        df = read_excel(p, sheet_name=sheet_name)
        file_type = "excel"
    elif ext == ".json":
        df = pd.read_json(p)
        file_type = "json"
    else:
        raise ValueError(
            f"Cannot generate data inventory for '{ext}' files. "
            f"Supported: .csv, .xlsx, .xls, .json"
        )

    n_rows, n_cols = df.shape
    fields = [_build_field(col, df[col]) for col in df.columns]

    total_cells = n_rows * n_cols
    total_missing = sum(f.missing_count for f in fields)
    overall_missing_rate = total_missing / total_cells if total_cells > 0 else 0.0

    time_columns = [f.name for f in fields if f.is_time_column]
    numeric_columns = [f.name for f in fields if f.dtype in ("int", "float")]
    categorical_columns = [
        f.name for f in fields if f.dtype in ("str", "category", "bool")
    ]

    inventory = DataInventory(
        file_name=p.name,
        file_path=str(p.resolve()),
        file_type=file_type,
        n_rows=n_rows,
        n_cols=n_cols,
        fields=fields,
        overall_missing_rate=overall_missing_rate,
        has_time_column=len(time_columns) > 0,
        time_columns=time_columns,
        numeric_columns=numeric_columns,
        categorical_columns=categorical_columns,
        sample_size=n_rows,
    )

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            inventory.model_dump_json(indent=2),
            encoding="utf-8",
        )

    return inventory


def generate_data_inventories(
    file_paths: list[str | Path],
    output_dir: str | Path | None = None,
) -> list[DataInventory]:
    """对多个数据文件生成画像（Excel 文件自动展开所有 sheet）。

    每个文件每个 sheet 生成一个独立的 DataInventory。
    Excel 多 sheet 时 file_name 标注为 ``"filename.xlsx::sheet_name"``。

    Args:
        file_paths: 数据文件路径列表。
        output_dir: 可选，画像 JSON 写入目录（每个文件一个 JSON）。

    Returns:
        DataInventory 列表（不可读文件自动跳过）。
    """
    inventories: list[DataInventory] = []

    for fp in file_paths:
        p = Path(fp)
        if not p.exists():
            continue
        ext = p.suffix.lower()

        if ext in (".xlsx", ".xls"):
            # Excel：展开所有 sheet
            try:
                sheets = read_excel_all_sheets(p)
            except Exception:
                continue
            for sheet_name in sheets:
                try:
                    inv = generate_data_inventory(p, sheet_name=sheet_name)
                    # file_name 标注 sheet 名
                    inv = inv.model_copy(
                        update={"file_name": f"{p.name}::{sheet_name}"}
                    )
                    inventories.append(inv)
                except Exception:
                    continue
        else:
            try:
                inv = generate_data_inventory(p)
                inventories.append(inv)
            except (FileNotFoundError, ValueError):
                continue

    # 可选写盘
    if output_dir is not None and inventories:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        for i, inv in enumerate(inventories):
            safe_name = inv.file_name.replace("::", "_").replace("/", "_")
            out_path = out / f"data_inventory_{i}_{safe_name}.json"
            out_path.write_text(inv.model_dump_json(indent=2), encoding="utf-8")

    return inventories
