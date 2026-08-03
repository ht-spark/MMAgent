"""pytest 全局配置：路径设置 + 测试夹具。"""
from __future__ import annotations

import sys
from pathlib import Path

# 将项目根目录加入 sys.path，使 scr 包可被导入
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# 文件夹具：在 tmp_path 中动态创建测试文件
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """小型 CSV：含中文、缺失值、时间列、单位线索、数值/分类混合。"""
    data = {
        "城市": ["北京", "上海", "广州", "深圳", None],
        "GDP(亿元)": [40269, 43215, 28232, 30664, 27670],
        "人口(万人)": [2189, 2487, 1881, 1768, 321],
        "日期": ["2023-01", "2023-02", "2023-03", "2023-04", "2023-05"],
        "增长率(%)": [5.2, 3.1, None, 4.8, 2.9],
    }
    df = pd.DataFrame(data)
    path = tmp_path / "sample.csv"
    df.to_csv(path, index=False, encoding="utf-8")
    return path


@pytest.fixture
def sample_excel(tmp_path: Path) -> Path:
    """小型 Excel：无时间列、含单位线索。"""
    data = {
        "产品": ["A", "B", "C", "D"],
        "价格(元)": [100, 200, 150, 300],
        "销量": [50, 30, 45, 20],
    }
    df = pd.DataFrame(data)
    path = tmp_path / "sample.xlsx"
    df.to_excel(path, index=False)
    return path


@pytest.fixture
def sample_markdown(tmp_path: Path) -> Path:
    """Markdown 文本文件。"""
    content = "# 数学建模题目\n\n某城市经济数据分析。\n\n## 数据说明\n\n附件包含 5 个城市的 GDP 与人口数据。"
    path = tmp_path / "problem.md"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def empty_csv(tmp_path: Path) -> Path:
    """只有表头、无数据行的 CSV。"""
    path = tmp_path / "empty.csv"
    path.write_text("a,b,c\n", encoding="utf-8")
    return path


@pytest.fixture
def small_sample_csv(tmp_path: Path) -> Path:
    """样本量 < 30 的 CSV（触发 L2 硬过滤条件）。"""
    df = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})
    path = tmp_path / "small.csv"
    df.to_csv(path, index=False)
    return path


@pytest.fixture
def str_number_csv(tmp_path: Path) -> Path:
    """字符串形式数字的 CSV。"""
    df = pd.DataFrame({"数值": ["1", "2", "3", "4"]})
    path = tmp_path / "strnum.csv"
    df.to_csv(path, index=False)
    return path


@pytest.fixture
def all_null_csv(tmp_path: Path) -> Path:
    """含全空列的 CSV。"""
    df = pd.DataFrame({"正常": [1, 2, 3], "全空": [None, None, None]})
    path = tmp_path / "nulls.csv"
    df.to_csv(path, index=False)
    return path


@pytest.fixture
def constant_csv(tmp_path: Path) -> Path:
    """含常量列的 CSV。"""
    df = pd.DataFrame({"变量": [1, 2, 3, 4, 5], "常量": [7, 7, 7, 7, 7]})
    path = tmp_path / "const.csv"
    df.to_csv(path, index=False)
    return path


@pytest.fixture
def sample_mat(tmp_path: Path) -> Path:
    """小型 MAT 文件：含 2D 数值数组和 1D 向量两个变量。"""
    import numpy as np
    from scipy.io import savemat

    data = {
        "matrix": np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]),
        "vector": np.array([10.0, 20.0, 30.0, 40.0]),
    }
    path = tmp_path / "sample.mat"
    savemat(str(path), data)
    return path


@pytest.fixture
def sample_mat_multi_var(tmp_path: Path) -> Path:
    """多变量 MAT 文件：含矩阵、向量和标量。"""
    import numpy as np
    from scipy.io import savemat

    data = {
        "data_matrix": np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]),
        "labels": np.array(["A", "B", "C"]),
        "count": np.array(42),
    }
    path = tmp_path / "multi.mat"
    savemat(str(path), data)
    return path
