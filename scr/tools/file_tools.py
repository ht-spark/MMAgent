"""文件读取与数据画像工具。

确定性工具，不依赖 LLM，可单测、可复现。

功能：
  - 读取 CSV / Excel / MATLAB(.mat) / Markdown 文件
  - 对数据文件生成确定性画像（data_inventory）

对应 plan.md:
  - Phase 3.1: tools/file_tools.py — CSV/Excel/JSON/Markdown/MAT 读取
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
    CorrelatedPair,
    DataField,
    DataInventory,
    NumericStats,
)

__all__ = [
    "read_csv",
    "read_excel",
    "read_excel_all_sheets",
    "read_mat",
    "read_mat_all_variables",
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


def _mat_to_dataframe(data: Any, var_name: str) -> pd.DataFrame | None:
    """将 MATLAB 变量转换为 DataFrame。

    处理 2D 数组、结构体、字符串数组等常见类型。
    """
    # scipy.io.loadmat 返回的 numpy 数组
    if isinstance(data, np.ndarray):
        # 去掉 MATLAB 的多余维度（MATLAB 一律至少 2D）
        squeezed = np.squeeze(data)

        # 字符串/字符数组
        if squeezed.dtype.kind in ("U", "S"):
            if squeezed.ndim <= 1:
                return pd.DataFrame({var_name: [str(squeezed)]})
            # 多行字符串
            return pd.DataFrame({var_name: [str(row) for row in squeezed]})

        # 2D 数值数组 → DataFrame
        if squeezed.ndim == 2:
            rows, cols = squeezed.shape
            if cols == 1:
                return pd.DataFrame({var_name: squeezed.flatten()})
            return pd.DataFrame(squeezed, columns=[f"{var_name}_{i}" for i in range(cols)])

        # 1D 数组
        if squeezed.ndim == 1:
            return pd.DataFrame({var_name: squeezed})

        # 多维数组展平为 2D
        if squeezed.ndim > 2:
            reshaped = squeezed.reshape(squeezed.shape[0], -1)
            return pd.DataFrame(
                reshaped,
                columns=[f"{var_name}_{i}" for i in range(reshaped.shape[1])],
            )

    # 结构体：scipy 返回带 dtype 字段名的 numpy void
    if hasattr(data, "dtype") and data.dtype.names:
        cols = {}
        for name in data.dtype.names:
            sub = data[name[0]] if isinstance(name, tuple) else data[name]
            sub_arr = np.squeeze(np.array(sub))
            if sub_arr.ndim == 1:
                cols[str(name)] = sub_arr
            elif sub_arr.ndim == 2 and sub_arr.shape[1] == 1:
                cols[str(name)] = sub_arr.flatten()
            else:
                cols[str(name)] = [str(sub_arr)]
        if cols:
            return pd.DataFrame(cols)

    # 标量
    if np.isscalar(data) or (isinstance(data, np.ndarray) and data.size == 1):
        return pd.DataFrame({var_name: [np.squeeze(data).item()]})

    return None


def read_mat(
    path: str | Path,
    variable_name: str | None = None,
) -> pd.DataFrame:
    """读取 MATLAB .mat 文件中的单个变量为 DataFrame。

    优先使用 scipy.io.loadmat（支持 v4/v6/v7/v7.2），
    失败时回退到 h5py（支持 v7.3 HDF5 格式，若已安装）。

    Args:
        path: .mat 文件路径。
        variable_name: 要读取的变量名。若为 None，自动选择第一个
                       可转为 DataFrame 的变量。

    Returns:
        pandas DataFrame.

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 文件无法解析或指定变量不存在。
        ImportError: 需要的依赖未安装。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"MAT file not found: {p}")

    variables = read_mat_all_variables(p)

    if variable_name is not None:
        if variable_name not in variables:
            available = ", ".join(variables.keys())
            raise ValueError(
                f"Variable '{variable_name}' not found in {p.name}. "
                f"Available: {available}"
            )
        return variables[variable_name]

    # 自动选择：优先选行数最多的变量
    best_df = None
    best_rows = -1
    for name, df in variables.items():
        if len(df) > best_rows:
            best_df = df
            best_rows = len(df)

    if best_df is None:
        raise ValueError(f"No convertible variables found in {p.name}")
    return best_df


def read_mat_all_variables(
    path: str | Path,
) -> dict[str, pd.DataFrame]:
    """读取 MATLAB .mat 文件的所有变量为 DataFrame 字典。

    类似于 ``read_excel_all_sheets``，每个 MATLAB 变量对应一个 DataFrame。
    自动跳过 MATLAB 内部元数据变量（以 ``__`` 开头）。

    Args:
        path: .mat 文件路径。

    Returns:
        {variable_name: DataFrame} 字典。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 文件无法解析。
        ImportError: 需要的依赖未安装。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"MAT file not found: {p}")

    # 尝试 scipy.io.loadmat（v4/v6/v7/v7.2）
    try:
        from scipy.io import loadmat
        raw = loadmat(p, struct_as_record=True, squeeze_me=True)
    except ImportError:
        raise ImportError(
            "scipy is required to read .mat files. "
            "Install with: pip install scipy"
        )
    except NotImplementedError:
        # v7.3 格式（HDF5），scipy 不支持，尝试 h5py
        return _read_mat_v73(p)
    except Exception as e:
        raise ValueError(f"Failed to parse .mat file {p.name}: {e}")

    result: dict[str, pd.DataFrame] = {}
    for name, data in raw.items():
        # 跳过 scipy 内部元数据
        if name.startswith("__"):
            continue
        df = _mat_to_dataframe(data, name)
        if df is not None:
            result[name] = df

    if not result:
        raise ValueError(f"No convertible variables found in {p.name}")

    return result


def _read_mat_v73(path: Path) -> dict[str, pd.DataFrame]:
    """读取 MATLAB v7.3 格式（HDF5）的 .mat 文件。

    需要 h5py 库。
    """
    try:
        import h5py
    except ImportError:
        raise ImportError(
            "This .mat file appears to be v7.3 format (HDF5-based). "
            "Install h5py to read it: pip install h5py"
        )

    result: dict[str, pd.DataFrame] = {}
    with h5py.File(path, "r") as f:
        for key in f.keys():
            if key.startswith("#"):
                # HDF5 内部引用
                continue
            data = f[key][()]
            if isinstance(data, np.ndarray):
                df = _mat_to_dataframe(data, key)
                if df is not None:
                    result[key] = df

    if not result:
        raise ValueError(f"No convertible variables found in {path.name}")
    return result


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
        path: 文件路径。支持 .csv / .xlsx / .xls / .mat / .md / .markdown / .txt。

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
    if ext == ".mat":
        return read_mat(p)
    if ext in (".md", ".markdown", ".txt"):
        return read_markdown(p)
    raise ValueError(
        f"Unsupported file type '{ext}'. "
        f"Supported: .csv, .xlsx, .xls, .mat, .md, .markdown, .txt"
    )


# ---------------------------------------------------------------------------
# 数据画像
# ---------------------------------------------------------------------------

# 时间列名称关键词（中英文）
_TIME_KEYWORDS = (
    "date", "time", "year", "month", "day", "hour",
    "日期", "时间", "年", "月", "日", "时",
)

# 非时间列名称关键词（ID/编号/序号等，即使被 pd.to_datetime 解析也不应判为时间列）
_NON_TIME_KEYWORDS = (
    "编号", "序号", "id", "code", "编号", "代码", "标识", "索引",
    "学号", "工号", "卡号", "牌号", "批号", "型号", "序号",
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
    (r"[\(\[（].*?(kg/m2|kg/㎡|密度|人均).*?[\)\]）]", "强度/密度"),
    (r"[\(\[（].*?(亿元|万元|百万|十亿|万).*?[\)\]）]", "金额量级"),
]

# 空间坐标列名称关键词（数据基本面·时空结构）
_SPATIAL_KEYWORDS = (
    "lat", "lon", "lng", "latitude", "longitude",
    "经度", "纬度", "东经", "北纬", "坐标x", "坐标y", "x坐标", "y坐标",
)

# 高相关列对阈值（分布特征·多变量 / 共线性风险）
_CORRELATION_THRESHOLD = 0.8


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
    # object / StringDtype 列：尝试判断是否可转为数值
    # （pandas 2.x 字符串列可能是 StringDtype 而非 object）
    if series.dtype == "object" or isinstance(series.dtype, pd.StringDtype):
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

    排除规则：
      - 字段名包含 ID/编号/序号等关键词时，即使可被 to_datetime 解析也不判为时间列
      - to_datetime 解析结果全部落在同一年内时，可能是数字误解析，不判为时间列
    """
    name_lower = name.lower()

    # 排除规则：ID/编号/序号等列名不判为时间列
    if any(kw in name_lower for kw in _NON_TIME_KEYWORDS):
        return False

    if any(kw in name_lower for kw in _TIME_KEYWORDS):
        return True

    if pd.api.types.is_datetime64_any_dtype(series):
        return True

    if series.dtype == "object":
        sample = series.dropna().head(20)
        if len(sample) > 0:
            try:
                parsed = pd.to_datetime(sample, errors="raise")
                # 验证：解析后的日期不应全部在同一年内（防止数字误解析）
                if hasattr(parsed, "dt"):
                    year_range = parsed.dt.year.nunique()
                    if year_range <= 1:
                        return False
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


def _detect_spatial_column(name: str) -> bool:
    """检测列是否为空间坐标列（经纬度等）。"""
    name_lower = name.lower().replace(" ", "")
    return any(kw in name_lower for kw in _SPATIAL_KEYWORDS)


def _compute_numeric_stats(numeric: pd.Series) -> NumericStats:
    """数值列的完整分布统计（集中/离散/偏态/峰态/离群）。"""
    n = len(numeric)
    q1 = float(numeric.quantile(0.25))
    q3 = float(numeric.quantile(0.75))
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    outliers = numeric[(numeric < lower) | (numeric > upper)]

    # 偏度/峰度：样本 < 3 或恒定时无定义（返回 None 而非 0）
    skewness: float | None = None
    kurtosis: float | None = None
    if n >= 3:
        try:
            sk = float(numeric.skew())
            ku = float(numeric.kurt())
            if not np.isnan(sk):
                skewness = sk
            if not np.isnan(ku):
                kurtosis = ku
        except (ValueError, TypeError):
            pass

    return NumericStats(
        min=_safe_float(numeric.min()),
        max=_safe_float(numeric.max()),
        mean=_safe_float(numeric.mean()),
        std=_safe_float(numeric.std()) if n > 1 else 0.0,
        median=_safe_float(numeric.median()),
        q1=_safe_float(q1),
        q3=_safe_float(q3),
        iqr=_safe_float(iqr),
        skewness=skewness,
        kurtosis=kurtosis,
        outlier_count=int(len(outliers)),
        outlier_rate=len(outliers) / n,
    )


def _compute_correlated_pairs(
    df: pd.DataFrame,
    threshold: float = _CORRELATION_THRESHOLD,
) -> list[CorrelatedPair]:
    """数值列两两相关，返回 |r| ≥ 阈值 的高相关列对。

    用于共线性风险提示（线性模型解释性、VIF 近似）。
    列数过多时限制为前 40 个数值列，避免 O(n²) 组合爆炸。
    """
    numeric_df = df.select_dtypes(include=[np.number])
    if numeric_df.shape[1] < 2 or numeric_df.shape[0] < 3:
        return []
    if numeric_df.shape[1] > 40:
        numeric_df = numeric_df.iloc[:, :40]

    corr = numeric_df.corr()
    cols = list(corr.columns)
    pairs: list[CorrelatedPair] = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            r = corr.iloc[i, j]
            if np.isnan(r):
                continue
            if abs(float(r)) >= threshold:
                pairs.append(
                    CorrelatedPair(col_a=cols[i], col_b=cols[j], correlation=float(r))
                )
    return pairs


def _compute_time_coverage(
    df: pd.DataFrame,
    time_col: str,
) -> tuple[str | None, str | None, int]:
    """时间列的覆盖范围与时间点数量（时空结构）。

    时间值规范化为短格式：纯日期截断为 ``YYYY-MM-DD``，含时分秒保留完整。
    """
    non_null = df[time_col].dropna()
    n = len(non_null)
    if n == 0:
        return None, None, 0
    unique_count = int(non_null.nunique())

    parsed = pd.to_datetime(non_null, errors="coerce").dropna()
    if len(parsed) > 0:
        return (
            _format_time_value(parsed.min()),
            _format_time_value(parsed.max()),
            unique_count,
        )
    # 无法解析为日期：退化用字符串 min/max
    return str(non_null.min()), str(non_null.max()), unique_count


def _format_time_value(value: Any) -> str:
    """将时间值规范化为短格式：'2023-01-01 00:00:00' → '2023-01-01'。"""
    s = str(value)
    if s.endswith(" 00:00:00"):
        return s[:-9]
    return s


def _build_modeling_constraints(
    n_rows: int,
    fields: list[DataField],
    time_columns: list[str],
    time_unique_count: int,
    correlated_pairs: list[CorrelatedPair],
    spatial_columns: list[str],
) -> list[str]:
    """建模假设预判：基于画像的确定性规则，输出模型可用性硬约束。

    这是数据画像第 6 维度的核心产出，直接服务 L2 模型过滤。
    """
    constraints: list[str] = []
    numeric_fields = [f for f in fields if f.dtype in ("int", "float")]
    categorical_fields = [f for f in fields if f.dtype in ("str", "category", "bool")]

    # 1. 时间维度
    if not time_columns:
        constraints.append("无时间维度列：排除时间序列模型（ARIMA/Prophet/LSTM 等）")
    elif time_unique_count == 0:
        constraints.append("时间列无有效值（全空或解析失败）：无法使用时间序列模型")
    elif time_unique_count < 30:
        constraints.append(
            f"时间点仅 {time_unique_count} 个：时序模型样本不足，慎用"
        )

    # 2. 样本量
    if n_rows < 30:
        constraints.append(
            f"样本量 {n_rows} < 30：排除高参数机器学习模型（随机森林/GBDT/深度学习）"
        )
    elif n_rows < 100:
        constraints.append(
            f"样本量 {n_rows} < 100：统计推断需谨慎，优先低参数模型"
        )

    # 3. 特征可用性
    if not numeric_fields:
        constraints.append("无数值特征列：排除回归/数值预测类方法")
    if not categorical_fields:
        constraints.append("无分类特征列：分类方法直接应用受限")

    # 4. 目标不平衡（目标变量特殊性）
    for f in categorical_fields:
        share = f.categorical_stats.max_category_share if f.categorical_stats else None
        if share is None:
            continue
        if share >= 0.9:
            constraints.append(
                f"分类字段 '{f.name}' 最大类别占比 {share:.1%}：严重不平衡，需采样/加权"
            )
        elif share >= 0.8:
            constraints.append(
                f"分类字段 '{f.name}' 最大类别占比 {share:.1%}：注意类别不平衡"
            )

    # 5. 共线性（分布特征·多变量）
    if correlated_pairs:
        names = ", ".join(f"{p.col_a}-{p.col_b}" for p in correlated_pairs[:3])
        constraints.append(
            f"存在高相关数值列对（|r|≥{_CORRELATION_THRESHOLD:.1f}）：{names}，线性模型注意共线性"
        )

    # 6. 高缺失（数据质量）
    for f in fields:
        if f.missing_rate > 0.5:
            constraints.append(
                f"字段 '{f.name}' 缺失率 {f.missing_rate:.1%}：需填充或删除决策"
            )

    # 7. 高离群（数据质量；空间坐标列/时间列不做数值离群约束）
    for f in fields:
        if (
            not f.is_spatial
            and not f.is_time_column
            and f.numeric_stats
            and f.numeric_stats.outlier_rate > 0.05
        ):
            constraints.append(
                f"字段 '{f.name}' 离群率 {f.numeric_stats.outlier_rate:.1%}：注意鲁棒性与异常值处理"
            )

    # 8. 常量列
    constant_cols = [f.name for f in fields if f.unique_count <= 1 and f.missing_rate == 0]
    if constant_cols:
        constraints.append(f"常量列（无信息量，建议剔除）：{', '.join(constant_cols[:5])}")

    # 9. 空间结构
    if spatial_columns:
        constraints.append(
            f"检测到空间坐标列 {', '.join(spatial_columns[:3])}：可考虑空间分析方法"
        )

    return constraints


def _cell_to_str(value: Any) -> str:
    """单元格值安全转字符串（JSON/嵌套类型不被 pd.isna 数组化误伤）。"""
    if isinstance(value, (list, dict, np.ndarray)):
        return str(value)
    if pd.isna(value):
        return ""
    return str(value)


def _build_field(name: str, series: pd.Series) -> DataField:
    """构建单个字段的画像。

    覆盖 6 大维度：
      - 基本面：dtype / is_candidate_key / is_spatial
      - 质量：missing_rate / outlier / numeric_parseable_rate（编码一致性）
      - 分布：skewness / kurtosis / iqr / value_range
      - 语义：unit_hint / max_category_share（不平衡）
      - 时空：is_time_column
    """
    total = len(series)
    missing_count = int(series.isna().sum())
    missing_rate = missing_count / total if total > 0 else 0.0
    unique_count = int(series.nunique(dropna=True))

    # 示例值（非缺失的前 5 个，转为字符串）
    sample_values = [str(v) for v in series.dropna().head(5).tolist()]

    dtype = _infer_dtype(series)
    is_time = _detect_time_column(series, name)
    unit_hint = _detect_unit_hint(name)
    is_spatial = _detect_spatial_column(name)
    # 候选主键：唯一且无缺失（粒度与关联键线索）
    is_candidate_key = total > 0 and missing_count == 0 and unique_count == total

    numeric_stats: NumericStats | None = None
    categorical_stats: CategoricalStats | None = None
    numeric_parseable_rate: float | None = None

    if dtype in ("int", "float"):
        numeric = pd.to_numeric(series, errors="coerce").dropna()
        if len(numeric) > 0:
            numeric_stats = _compute_numeric_stats(numeric)
    elif dtype in ("str", "category", "bool"):
        value_counts = series.value_counts().head(10)
        total_non_null = int(series.dropna().shape[0])
        max_share = None
        if total_non_null > 0 and len(value_counts) > 0:
            max_share = float(value_counts.iloc[0]) / total_non_null
        categorical_stats = CategoricalStats(
            top_values=[
                CategoryCount(value=str(k), count=int(v))
                for k, v in value_counts.items()
            ],
            max_category_share=max_share,
        )
        # 编码一致性：字符列中可解析为数值的比例（0<rate<1 表示类型混合风险）
        # 注意 pandas 2.x 字符串列可能是 StringDtype（str）而非 object
        if series.dtype == "object" or isinstance(series.dtype, pd.StringDtype):
            non_null = series.dropna()
            if len(non_null) > 0:
                parsed = pd.to_numeric(non_null, errors="coerce")
                numeric_parseable_rate = float(parsed.notna().mean())

    return DataField(
        name=name,
        dtype=dtype,
        missing_count=missing_count,
        missing_rate=missing_rate,
        unique_count=unique_count,
        sample_values=sample_values,
        unit_hint=unit_hint,
        is_time_column=is_time,
        is_candidate_key=is_candidate_key,
        is_spatial=is_spatial,
        numeric_parseable_rate=numeric_parseable_rate,
        numeric_stats=numeric_stats,
        categorical_stats=categorical_stats,
    )


def generate_data_inventory(
    file_path: str | Path,
    output_path: str | Path | None = None,
    sheet_name: str | int = 0,
    variable_name: str | None = None,
) -> DataInventory:
    """对数据文件生成确定性画像。

    画像包含：行列数、字段类型、缺失率、单位线索、时间维度。
    它是 L2 硬过滤的关键输入。

    Args:
        file_path: 数据文件路径（.csv / .xlsx / .xls / .mat / .json）。
        output_path: 可选，画像 JSON 写入路径。
                     若提供则创建父目录并写入 ``DataInventory.model_dump_json()``。
        sheet_name: Excel 工作表名称或索引，默认第一个。
        variable_name: MAT 文件变量名，None 时自动选择行数最多的变量。

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
    elif ext == ".mat":
        df = read_mat(p, variable_name=variable_name)
        file_type = "mat"
    elif ext == ".json":
        df = pd.read_json(p)
        file_type = "json"
    else:
        raise ValueError(
            f"Cannot generate data inventory for '{ext}' files. "
            f"Supported: .csv, .xlsx, .xls, .mat, .json"
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

    # 数据质量·重复噪声：完全重复的行
    duplicate_rows = 0
    duplicate_rate = 0.0
    if n_rows > 1:
        duplicate_rows = int(df.duplicated().sum())
        duplicate_rate = duplicate_rows / n_rows

    # 数据基本面·粒度：候选主键列
    candidate_keys = [f.name for f in fields if f.is_candidate_key]

    # 数据基本面·样例：前 5 行（值转为字符串，控制体积）
    sample_rows: list[dict] = []
    for _, row in df.head(5).iterrows():
        sample_rows.append({str(k): _cell_to_str(v) for k, v in row.items()})

    # 时空结构：时间覆盖 + 空间坐标列
    spatial_columns = [f.name for f in fields if f.is_spatial]
    time_min: str | None = None
    time_max: str | None = None
    time_unique_count = 0
    if time_columns:
        time_min, time_max, time_unique_count = _compute_time_coverage(
            df, time_columns[0]
        )

    # 分布特征·多变量：高相关列对（共线性）
    correlated_pairs = _compute_correlated_pairs(df)

    # 建模假设预判：确定性规则生成模型可用性约束
    modeling_constraints = _build_modeling_constraints(
        n_rows=n_rows,
        fields=fields,
        time_columns=time_columns,
        time_unique_count=time_unique_count,
        correlated_pairs=correlated_pairs,
        spatial_columns=spatial_columns,
    )

    inventory = DataInventory(
        file_name=p.name,
        file_path=str(p.resolve()),
        file_type=file_type,
        file_size=p.stat().st_size,
        n_rows=n_rows,
        n_cols=n_cols,
        fields=fields,
        overall_missing_rate=overall_missing_rate,
        duplicate_rows=duplicate_rows,
        duplicate_rate=duplicate_rate,
        candidate_keys=candidate_keys,
        sample_rows=sample_rows,
        has_time_column=len(time_columns) > 0,
        time_columns=time_columns,
        time_min=time_min,
        time_max=time_max,
        time_unique_count=time_unique_count,
        spatial_columns=spatial_columns,
        correlated_pairs=correlated_pairs,
        numeric_columns=numeric_columns,
        categorical_columns=categorical_columns,
        modeling_constraints=modeling_constraints,
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
    """对多个数据文件生成画像（Excel 展开 sheet，MAT 展开变量）。

    每个文件每个 sheet/变量生成一个独立的 DataInventory。
    Excel 多 sheet 时 file_name 标注为 ``"filename.xlsx::sheet_name"``。
    MAT 多变量时 file_name 标注为 ``"filename.mat::variable_name"``。

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
        elif ext == ".mat":
            # MAT：展开所有变量
            try:
                variables = read_mat_all_variables(p)
            except Exception:
                continue
            for var_name in variables:
                try:
                    inv = generate_data_inventory(p, variable_name=var_name)
                    inv = inv.model_copy(
                        update={"file_name": f"{p.name}::{var_name}"}
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
