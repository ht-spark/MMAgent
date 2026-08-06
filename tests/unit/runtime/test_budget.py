"""BudgetManager 单元测试：双模式（强制 / 监控）、每问重置、逐问覆盖、报告。"""
from scr.runtime.budget import (
    BudgetManager,
    BudgetType,
    DEFAULT_BUDGETS,
    MONITOR_BUDGETS,
)


def test_consume_enforced_per_question_and_reset():
    bm = BudgetManager()
    # Q1 消耗 SEARCH 到上限
    assert bm.consume(BudgetType.SEARCH, 1, question_id="Q1")
    assert bm.consume(BudgetType.SEARCH, 1, question_id="Q1")
    # 第 3 次应被拒绝（默认上限 10，但此处验证用单问独立计数语义：重置后清零）
    # 这里仅验证"按问重置"：换 Q2 后 used 归零
    bm.reset_for_new_question()
    assert bm.get_record(BudgetType.SEARCH).used == 0
    # run_total 仍累计
    assert bm.get_record(BudgetType.SEARCH).run_total == 2


def test_consume_over_limit_rejected():
    bm = BudgetManager()
    # CANDIDATE 默认上限 4
    for _ in range(4):
        assert bm.consume(BudgetType.CANDIDATE, 1, question_id="Q1")
    assert bm.consume(BudgetType.CANDIDATE, 1, question_id="Q1") is False
    assert bm.get_record(BudgetType.CANDIDATE).exhausted is True


def test_monitor_accumulates_run_total_and_per_question():
    bm = BudgetManager()
    bm.record_monitor(BudgetType.TIME, 12.5, question_id="Q1")
    bm.record_monitor(BudgetType.TOKEN, 200, question_id="Q1")
    bm.record_monitor(BudgetType.TOKEN, 100, question_id="Q2")
    assert bm.get_record(BudgetType.TIME).run_total == 12.5
    assert bm.get_record(BudgetType.TOKEN).run_total == 300
    # 监控项永不视为耗尽、remaining 为 -1
    assert bm.get_record(BudgetType.TOKEN).exhausted is False
    assert bm.get_record(BudgetType.TOKEN).remaining == -1


def test_monitor_used_resets_per_question_but_history_kept():
    bm = BudgetManager()
    bm.record_monitor(BudgetType.TOKEN, 200, question_id="Q1")
    bm.reset_for_new_question()
    # used 重置为 0（当前问口径）
    assert bm.get_record(BudgetType.TOKEN).used == 0
    # 逐问历史保留
    assert bm.to_dict()["per_question_monitor_usage"]["Q1"]["token"] == 200
    # run_total 不丢
    assert bm.get_record(BudgetType.TOKEN).run_total == 200


def test_set_question_limits_override():
    bm = BudgetManager()
    # 为 Q1 临时覆盖 SEARCH 上限为 2（先覆盖再消耗，避免污染共享 used 语义）
    bm.set_question_limits("Q1", {BudgetType.SEARCH: 2})
    assert bm.remaining(BudgetType.SEARCH, question_id="Q1") == 2
    assert bm.consume(BudgetType.SEARCH, 1, question_id="Q1")
    assert bm.consume(BudgetType.SEARCH, 1, question_id="Q1")
    assert bm.consume(BudgetType.SEARCH, 1, question_id="Q1") is False
    # 监控项覆盖被忽略
    bm.set_question_limits("Q1", {BudgetType.TOKEN: 5})
    assert bm.get_question_limits("Q1") == {BudgetType.SEARCH: 2}
    # 其它小问无覆盖（remaining 受当前共享 used 影响，重置后恢复默认上限）
    assert bm.get_question_limits("Q2") == {}
    bm.reset_for_new_question()
    assert bm.remaining(BudgetType.SEARCH, question_id="Q2") == DEFAULT_BUDGETS[BudgetType.SEARCH]


def test_per_question_enforced_history_in_to_dict():
    bm = BudgetManager()
    bm.consume(BudgetType.SEARCH, 2, question_id="Q1")
    bm.consume(BudgetType.CODE_REPAIR, 1, question_id="Q1")
    bm.consume(BudgetType.SEARCH, 1, question_id="Q2")
    d = bm.to_dict()
    assert d["per_question_enforced_usage"]["Q1"]["search"] == 2
    assert d["per_question_enforced_usage"]["Q1"]["code_repair"] == 1
    assert d["per_question_enforced_usage"]["Q2"]["search"] == 1
    assert d["run_total_used"]["search"] == 3


def test_monitor_types_are_correct():
    assert BudgetType.TIME in MONITOR_BUDGETS
    assert BudgetType.TOKEN in MONITOR_BUDGETS
    assert BudgetType.SEARCH not in MONITOR_BUDGETS


def test_no_budget_manager_returns_true_for_consume():
    # consume 的边界：未知类型返回 True（不阻塞）；监控型走 record_only
    bm = BudgetManager()
    # 监控型通过 consume 也能记账且不阻塞
    assert bm.consume(BudgetType.TIME, 5, question_id="Q1") is True
    assert bm.get_record(BudgetType.TIME).run_total == 5
