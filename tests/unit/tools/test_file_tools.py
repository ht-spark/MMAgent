"""file_tools 单元测试。

覆盖：
  - CSV / Excel / Markdown 读取（正常 + 异常）
  - read_file 自动分发
  - generate_data_inventory 画像生成（字段类型、缺失率、时间检测、单位线索、统计、落盘）
  - 边界情况：空文件、全空列、常量列、字符串数字、小样本
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scr.tools.file_tools import (
    generate_data_inventory,
    read_csv,
    read_excel,
    read_file,
    read_markdown,
)
from scr.schemas.problem import DataInventory


# ---------------------------------------------------------------------------
# read_csv
# ---------------------------------------------------------------------------


class TestReadCSV:
    def test_basic(self, sample_csv: Path):
        df = read_csv(sample_csv)
        assert len(df) == 5
        assert list(df.columns) == ["城市", "GDP(亿元)", "人口(万人)", "日期", "增长率(%)"]

    def test_not_found(self):
        with pytest.raises(FileNotFoundError, match="CSV file not found"):
            read_csv("nonexistent_file.csv")

    def test_encoding_fallback(self, tmp_path: Path):
        """GBK 编码的 CSV 也能读取。"""
        df = pd.DataFrame({"名称": ["测试", "数据"], "值": [1, 2]})
        path = tmp_path / "gbk.csv"
        df.to_csv(path, index=False, encoding="gbk")
        result = read_csv(path)
        assert list(result["名称"]) == ["测试", "数据"]


# ---------------------------------------------------------------------------
# read_excel
# ---------------------------------------------------------------------------


class TestReadExcel:
    def test_basic(self, sample_excel: Path):
        df = read_excel(sample_excel)
        assert len(df) == 4
        assert list(df.columns) == ["产品", "价格(元)", "销量"]

    def test_sheet_by_index(self, sample_excel: Path):
        df = read_excel(sample_excel, sheet_name=0)
        assert len(df) == 4

    def test_not_found(self):
        with pytest.raises(FileNotFoundError, match="Excel file not found"):
            read_excel("nonexistent_file.xlsx")


# ---------------------------------------------------------------------------
# read_markdown
# ---------------------------------------------------------------------------


class TestReadMarkdown:
    def test_basic(self, sample_markdown: Path):
        content = read_markdown(sample_markdown)
        assert "数学建模题目" in content
        assert "数据说明" in content

    def test_not_found(self):
        with pytest.raises(FileNotFoundError, match="Markdown file not found"):
            read_markdown("nonexistent_file.md")

    def test_txt_extension(self, tmp_path: Path):
        path = tmp_path / "notes.txt"
        path.write_text("plain text content", encoding="utf-8")
        assert read_markdown(path) == "plain text content"


# ---------------------------------------------------------------------------
# read_file（自动分发）
# ---------------------------------------------------------------------------


class TestReadFile:
    def test_csv_dispatch(self, sample_csv: Path):
        df = read_file(sample_csv)
        assert isinstance(df, pd.DataFrame)

    def test_excel_dispatch(self, sample_excel: Path):
        df = read_file(sample_excel)
        assert isinstance(df, pd.DataFrame)

    def test_markdown_dispatch(self, sample_markdown: Path):
        content = read_file(sample_markdown)
        assert isinstance(content, str)

    def test_txt_dispatch(self, tmp_path: Path):
        path = tmp_path / "readme.txt"
        path.write_text("hello", encoding="utf-8")
        assert read_file(path) == "hello"

    def test_unsupported_type(self, tmp_path: Path):
        path = tmp_path / "data.xyz"
        path.write_text("unknown", encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported file type"):
            read_file(path)

    def test_not_found(self):
        with pytest.raises(FileNotFoundError):
            read_file("nonexistent.csv")


# ---------------------------------------------------------------------------
# generate_data_inventory
# ---------------------------------------------------------------------------


class TestGenerateDataInventory:
    def test_returns_data_inventory(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        assert isinstance(inv, DataInventory)

    def test_dimensions(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        assert inv.n_rows == 5
        assert inv.n_cols == 5

    def test_file_info(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        assert inv.file_name == "sample.csv"
        assert inv.file_type == "csv"
        assert inv.sample_size == 5

    def test_missing_rate(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        city = next(f for f in inv.fields if f.name == "城市")
        assert city.missing_count == 1
        assert city.missing_rate == 0.2

        growth = next(f for f in inv.fields if f.name == "增长率(%)")
        assert growth.missing_count == 1
        assert growth.missing_rate == 0.2

    def test_overall_missing_rate(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        # 5行×5列=25个单元格，2个缺失
        assert inv.overall_missing_rate == round(2 / 25, 4)

    def test_time_column_by_name(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        assert "日期" in inv.time_columns
        assert inv.has_time_column is True

    def test_no_time_column(self, sample_excel: Path):
        inv = generate_data_inventory(sample_excel)
        assert inv.has_time_column is False
        assert len(inv.time_columns) == 0

    def test_unit_hint_currency(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        gdp = next(f for f in inv.fields if f.name == "GDP(亿元)")
        assert gdp.unit_hint == "货币"

    def test_unit_hint_percent(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        growth = next(f for f in inv.fields if f.name == "增长率(%)")
        assert growth.unit_hint == "百分比"

    def test_unit_hint_none(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        city = next(f for f in inv.fields if f.name == "城市")
        assert city.unit_hint is None

    def test_numeric_stats(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        gdp = next(f for f in inv.fields if f.name == "GDP(亿元)")
        assert gdp.numeric_stats is not None
        assert gdp.numeric_stats.min == 27670.0
        assert gdp.numeric_stats.max == 43215.0
        assert gdp.numeric_stats.mean > 0

    def test_numeric_stats_none_for_categorical(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        city = next(f for f in inv.fields if f.name == "城市")
        assert city.numeric_stats is None
        assert city.categorical_stats is not None

    def test_categorical_stats(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        city = next(f for f in inv.fields if f.name == "城市")
        assert city.categorical_stats is not None
        assert len(city.categorical_stats.top_values) > 0
        assert all(tc.count > 0 for tc in city.categorical_stats.top_values)

    def test_numeric_columns(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        assert "GDP(亿元)" in inv.numeric_columns
        assert "人口(万人)" in inv.numeric_columns
        assert "城市" not in inv.numeric_columns

    def test_categorical_columns(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        assert "城市" in inv.categorical_columns
        assert "GDP(亿元)" not in inv.categorical_columns

    def test_dtype_int(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        pop = next(f for f in inv.fields if f.name == "人口(万人)")
        assert pop.dtype in ("int", "float")

    def test_dtype_float(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        growth = next(f for f in inv.fields if f.name == "增长率(%)")
        assert growth.dtype == "float"

    def test_dtype_str(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        city = next(f for f in inv.fields if f.name == "城市")
        assert city.dtype == "str"

    def test_sample_values(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        city = next(f for f in inv.fields if f.name == "城市")
        assert len(city.sample_values) <= 5
        assert "北京" in city.sample_values

    def test_unique_count(self, sample_csv: Path):
        inv = generate_data_inventory(sample_csv)
        city = next(f for f in inv.fields if f.name == "城市")
        # 5行1缺失 → 4个唯一非空值
        assert city.unique_count == 4

    def test_output_path(self, sample_csv: Path, tmp_path: Path):
        out = tmp_path / "reports" / "data_inventory.json"
        inv = generate_data_inventory(sample_csv, output_path=out)
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["file_name"] == "sample.csv"
        assert data["n_rows"] == 5

    def test_excel_inventory(self, sample_excel: Path):
        inv = generate_data_inventory(sample_excel)
        assert inv.file_type == "excel"
        assert inv.n_rows == 4
        assert inv.n_cols == 3
        assert inv.sample_size == 4


# ---------------------------------------------------------------------------
# 边界情况
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_csv(self, empty_csv: Path):
        inv = generate_data_inventory(empty_csv)
        assert inv.n_rows == 0
        assert inv.n_cols == 3
        assert inv.sample_size == 0
        assert inv.overall_missing_rate == 0.0

    def test_small_sample(self, small_sample_csv: Path):
        """样本量 < 30 → L2 硬过滤应淘汰 ML 候选。"""
        inv = generate_data_inventory(small_sample_csv)
        assert inv.sample_size < 30

    def test_string_numbers(self, str_number_csv: Path):
        """字符串数字应被推断为数值类型。"""
        inv = generate_data_inventory(str_number_csv)
        field = inv.fields[0]
        assert field.dtype in ("int", "float")
        assert field.numeric_stats is not None

    def test_all_null_column(self, all_null_csv: Path):
        inv = generate_data_inventory(all_null_csv)
        null_field = next(f for f in inv.fields if f.name == "全空")
        assert null_field.missing_count == 3
        assert null_field.missing_rate == 1.0

    def test_constant_column(self, constant_csv: Path):
        inv = generate_data_inventory(constant_csv)
        const_field = next(f for f in inv.fields if f.name == "常量")
        assert const_field.unique_count == 1
        if const_field.numeric_stats is not None:
            assert const_field.numeric_stats.min == const_field.numeric_stats.max

    def test_json_output_is_valid(self, sample_csv: Path, tmp_path: Path):
        out = tmp_path / "inv.json"
        generate_data_inventory(sample_csv, output_path=out)
        # 确保产物是合法 JSON 且能还原为 DataInventory
        raw = out.read_text(encoding="utf-8")
        restored = DataInventory.model_validate_json(raw)
        assert restored.n_rows == 5
        assert len(restored.fields) == 5

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="Data file not found"):
            generate_data_inventory("nonexistent.csv")

    def test_unsupported_type_for_inventory(self, tmp_path: Path):
        path = tmp_path / "data.xyz"
        path.write_text("unknown", encoding="utf-8")
        with pytest.raises(ValueError, match="Cannot generate data inventory"):
            generate_data_inventory(path)
