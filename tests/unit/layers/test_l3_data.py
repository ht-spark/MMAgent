"""L3 数据子图单元测试（demo 简化版）。"""
from __future__ import annotations

import pandas as pd
import pytest

from scr.layers.l3_data import L3DataSubgraph
from scr.schemas.problem import DataField, DataInventory


@pytest.fixture
def sample_csv(tmp_path) -> str:
    """数值列 + 一个常量列 + 一些缺失值。"""
    df = pd.DataFrame({
        "城市": ["北京", "上海", "广州", "深圳", None],
        "GDP(亿元)": [40269, 43215, 28232, 30664, None],
        "人口(万人)": [2189, 2487, 1881, 1768, 321],
        "常量": [7, 7, 7, 7, 7],  # 常量列应被剔除
    })
    path = tmp_path / "city.csv"
    df.to_csv(path, index=False, encoding="utf-8")
    return str(path)


@pytest.fixture
def sample_inventory() -> DataInventory:
    from scr.schemas.problem import NumericStats
    return DataInventory(
        file_name="city.csv",
        file_path="",
        file_type="csv",
        n_rows=5,
        n_cols=4,
        fields=[
            DataField(
                name="GDP(亿元)", dtype="float",
                missing_count=1, missing_rate=0.2,
                unique_count=4, numeric_stats=NumericStats(
                    min=27670, max=43215, mean=35000, std=5000, median=35000,
                ),
            ),
            DataField(
                name="人口(万人)", dtype="int",
                missing_count=0, missing_rate=0.0,
                unique_count=5,
            ),
            DataField(
                name="城市", dtype="str",
                missing_count=1, missing_rate=0.2,
                unique_count=4,
            ),
            DataField(
                name="常量", dtype="int",
                missing_count=0, missing_rate=0.0,
                unique_count=1,
            ),
        ],
        overall_missing_rate=0.1,
        has_time_column=False,
        numeric_columns=["GDP(亿元)", "人口(万人)", "常量"],
        categorical_columns=["城市"],
        sample_size=5,
    )


def test_full_pipeline_passes_g4(sample_csv, sample_inventory, tmp_path):
    """完整流程：plan_data → preprocess → quality_report + G4。"""
    subgraph = L3DataSubgraph(output_dir=tmp_path / "artifacts")
    result = subgraph.run(sample_csv, sample_inventory)

    # 计划了 4 个字段
    assert len(result["data_requirements"]) == 4
    # 预处理：常量列被剔除
    assert "常量" not in result["preprocessing_report"].columns_after
    # 质量报告存在
    assert result["quality_report"] is not None
    # 缺失率不超过阈值
    for r in result["quality_report"].missing_rates.values():
        assert r <= 0.5


def test_constant_column_removed_and_logged(sample_csv, sample_inventory, tmp_path):
    """常量列被自动剔除，且在 issues 中记录。"""
    subgraph = L3DataSubgraph(output_dir=tmp_path / "artifacts")
    result = subgraph.run(sample_csv, sample_inventory)

    quality = result["quality_report"]
    # "常量" 被识别为常量列
    assert "常量" in quality.constant_columns
    # 在 issues 中有对应记录
    constant_issues = [
        i for i in quality.issues if i.kind == "constant_column"
    ]
    assert len(constant_issues) >= 1