"""format_data_summary_table 对结果键类型的防御性回归测试。

回归场景：仿真类小问的 computation.results.simulation 是样本列表
（如蒙特卡洛的 1000 个采样值）时，旧实现直接调用 sim.items() 崩溃，
导致 write_paper 节点失败、paper.md 无法生成。
"""
from scr.tools.table_tools import format_data_summary_table


def test_simulation_list_samples_does_not_crash_and_summarizes():
    computation = {
        "status": "success",
        "results": {
            "simulation": [0.1, 0.2, 0.3, 0.4, 0.5],
            "confidence_interval": [0.2, 0.4],
        },
        "metrics": {},
    }

    table = format_data_summary_table(computation, "q1")

    assert "样本数 | 5" in table
    assert "均值" in table
    assert "中位数" in table
    assert "标准差" in table
    assert "最小值" in table
    assert "最大值" in table


def test_simulation_empty_list_does_not_crash():
    computation = {"status": "success", "results": {"simulation": []}}

    table = format_data_summary_table(computation, "q1")

    assert "非数值样本" in table or "样本数" in table


def test_data_summary_dict_keeps_working():
    computation = {
        "status": "success",
        "results": {"data_summary": {"mean": 1.0, "std": 0.5}},
    }

    table = format_data_summary_table(computation, "q1")

    assert "| mean | 1.0000 |" in table
    assert "| std | 0.5000 |" in table


def test_simulation_dict_nested_subkeys_flattened():
    computation = {
        "status": "success",
        "results": {"simulation": {"mean": 1.0, "percentiles": {"p25": 0.5, "p75": 1.5}}},
    }

    table = format_data_summary_table(computation, "q1")

    assert "| mean | 1.0000 |" in table
    assert "| percentiles.p25 | 0.5000 |" in table
    assert "| percentiles.p75 | 1.5000 |" in table


def test_scalar_simulation_value_rendered_single_row():
    computation = {"status": "success", "results": {"simulation": 3.14}}

    table = format_data_summary_table(computation, "q1")

    assert "| simulation | 3.1400 |" in table


def test_no_summary_key_returns_placeholder():
    computation = {"status": "success", "results": {"optimal_solution": [1, 2]}}

    table = format_data_summary_table(computation, "q1")

    assert "无数据摘要" in table
