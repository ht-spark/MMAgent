"""预算与降级管理。

对应 architecture.md §8.3：
  预算包括联网检索次数、方法候选数量、代码修复次数、验证迭代次数、时间和 token。
  预算紧张时的降级顺序为：减少低价值候选、优先简单基线、减少非关键图表、
  保留必要验证；不得跳过数据质量检查、数值复现和任务覆盖检查。

本模块同时承担两类不同性质的预算：
  - 强制（enforced）：SEARCH / CANDIDATE / CODE_REPAIR / VALIDATION_ITERATION。
    按小问独立计数，超额拒绝继续；每问开始时自动重置；用户可临时覆盖单问上限。
  - 监控（monitor）：TIME / TOKEN。
    全程累计，不强制阻塞；用于事后报告"每问耗时/token"和"任务总耗时/总 token"。

典型用法：

    bm = BudgetManager()
    # 消耗强制预算：超额返回 False
    if bm.consume(BudgetType.SEARCH, amount=1, question_id=qid):
        tavily.search(...)
    else:
        # 跳过本次搜索，进入降级
        ...
    # 监控式记账：始终成功
    bm.record_monitor(BudgetType.TIME, elapsed_seconds, question_id=qid)
    bm.record_monitor(BudgetType.TOKEN, tokens_used, question_id=qid)
    # 用户在指定小问临时覆盖上限
    bm.set_question_limits(qid, {BudgetType.SEARCH: 20, BudgetType.CANDIDATE: 6})
    # 报告
    report = bm.to_dict()
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BudgetType(str, Enum):
    """预算类型。"""

    SEARCH = "search"                       # 联网检索次数
    CANDIDATE = "candidate"                 # 方法候选数量
    CODE_REPAIR = "code_repair"             # 代码修复次数
    VALIDATION_ITERATION = "validation"     # 验证迭代次数
    INTAKE_RETRY = "intake_retry"           # G0 输入质量门重试次数
    PAPER_REVISION = "paper_revision"       # GF 交付质量门修订次数
    TIME = "time"                           # 时间预算（秒）
    TOKEN = "token"                         # token 预算


# 强制类型：按小问计数、超额拒绝、按问重置（用户可临时覆盖）
ENFORCED_BUDGETS: frozenset[BudgetType] = frozenset({
    BudgetType.SEARCH,
    BudgetType.CANDIDATE,
    BudgetType.CODE_REPAIR,
    BudgetType.VALIDATION_ITERATION,
    BudgetType.INTAKE_RETRY,
    BudgetType.PAPER_REVISION,
})

# 监控类型：全程累计、不阻塞
MONITOR_BUDGETS: frozenset[BudgetType] = frozenset({
    BudgetType.TIME,
    BudgetType.TOKEN,
})


# 默认预算配置（强制项为单问上限；监控项为参考上限）
DEFAULT_BUDGETS: dict[BudgetType, int] = {
    BudgetType.SEARCH: 10,
    BudgetType.CANDIDATE: 4,
    BudgetType.CODE_REPAIR: 3,
    BudgetType.VALIDATION_ITERATION: 2,
    BudgetType.INTAKE_RETRY: 3,
    BudgetType.PAPER_REVISION: 2,
    BudgetType.TIME: 3600,     # 1 小时（监控阈值，不强制）
    BudgetType.TOKEN: 100000,
}


# 降级顺序（从低价值到高价值；TIME/TOKEN 不可降级）
DEGRADATION_ORDER: list[BudgetType] = [
    BudgetType.SEARCH,
    BudgetType.CANDIDATE,
    BudgetType.TOKEN,
    BudgetType.CODE_REPAIR,
    BudgetType.VALIDATION_ITERATION,
    BudgetType.INTAKE_RETRY,
    BudgetType.PAPER_REVISION,
]


@dataclass
class BudgetRecord:
    """单个预算类型的记录。

    同时持有"单问用量"（used，按小问重置）和"累计用量"（run_total，全局不重置），
    方便报告"每问消耗"与"任务总消耗"。
    """

    budget_type: BudgetType
    limit: int
    used: int = 0                # 当前小问的已用量；按问重置
    run_total: int = 0           # 任务全程累计；永远只增
    unit: str = "次"

    @property
    def remaining(self) -> int:
        """剩余预算（强制项有效；监控项无意义，返回 -1）。"""
        if self.budget_type in MONITOR_BUDGETS:
            return -1
        return max(0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        """强制项是否超额。监控项永不视为耗尽。"""
        if self.budget_type in MONITOR_BUDGETS:
            return False
        return self.used >= self.limit

    @property
    def usage_ratio(self) -> float:
        """强制项已用比例；监控项按 run_total / limit 估计。"""
        if self.budget_type in MONITOR_BUDGETS:
            return self.run_total / self.limit if self.limit > 0 else 0.0
        return self.used / self.limit if self.limit > 0 else 1.0

    def consume(self, amount: int = 1, *, override_limit: int | None = None) -> bool:
        """消耗强制预算；超额返回 False。

        Args:
            amount: 消耗量。
            override_limit: 临时上限（用于 set_question_limits 覆盖单问限额），
                None 表示使用 self.limit。
        """
        effective_limit = override_limit if override_limit is not None else self.limit
        if self.used + amount > effective_limit:
            return False
        self.used += amount
        self.run_total += amount
        return True

    def record_only(self, amount: int) -> None:
        """监控型记账：始终成功，同时更新 used 和 run_total。"""
        if amount <= 0:
            return
        self.used += amount
        self.run_total += amount

    def reset(self) -> None:
        """重置"单问用量"（used），保留 run_total。"""
        self.used = 0


class BudgetManager:
    """预算管理器。

    一次性创建，全程持有。两类预算共享同一份 record，但语义不同：
      - 强制项（SEARCH/CANDIDATE/CODE_REPAIR/VALIDATION_ITERATION）：
          - 默认上限来自 DEFAULT_BUDGETS；
          - 通过 set_question_limits(qid, ...) 在指定小问临时覆盖；
          - 重试/消耗前调用 consume()，超额返回 False；
          - 新小问开始时调用 reset_for_new_question() 重置 used。
      - 监控项（TIME/TOKEN）：
          - 始终调用 record_monitor() 记账，永不阻塞；
          - used 与 run_total 都在增长，前者在按问重置时清零。

    Args:
        run_limits: 运行级上限覆盖（用于强制项的默认值与监控项的参考上限）。
        per_question_limits: 初始每问覆盖映射
            {question_id: {BudgetType: limit}}。
    """

    def __init__(
        self,
        run_limits: dict[BudgetType, int] | None = None,
        per_question_limits: dict[str, dict[BudgetType, int]] | None = None,
    ) -> None:
        config = {**DEFAULT_BUDGETS, **(run_limits or {})}
        self._records: dict[BudgetType, BudgetRecord] = {
            bt: BudgetRecord(
                budget_type=bt,
                limit=limit,
                unit=("秒" if bt == BudgetType.TIME
                      else "个" if bt == BudgetType.CANDIDATE
                      else "次"),
            )
            for bt, limit in config.items()
        }
        # 用户对指定小问的临时覆盖：{qid: {BudgetType: limit}}
        self._question_limits: dict[str, dict[BudgetType, int]] = {
            qid: dict(limits) for qid, limits in (per_question_limits or {}).items()
        }
        # 监控型预算（TIME/TOKEN）的逐问累计：{qid: {BudgetType: amount}}
        # 用于报告"每个问题消耗"。run_total 仍是任务全程累计。
        self._question_monitor_usage: dict[str, dict[BudgetType, int]] = {}
        # 强制型预算（SEARCH/CANDIDATE/CODE_REPAIR/VALIDATION_ITERATION）的逐问累计
        self._question_enforced_usage: dict[str, dict[BudgetType, int]] = {}

    # ------------------------------------------------------------------
    # 强制型：消耗
    # ------------------------------------------------------------------

    def consume(
        self,
        budget_type: BudgetType,
        amount: int = 1,
        *,
        question_id: str | None = None,
    ) -> bool:
        """消耗指定类型的强制预算。

        若 question_id 配置了临时上限，则以临时上限为准；否则使用运行级 limit。
        监控项调用本方法视作记账（不会失败）。

        Returns:
            True 表示允许继续；False 表示强制项超额。
        """
        record = self._records.get(budget_type)
        if record is None:
            return True
        if budget_type in MONITOR_BUDGETS:
            record.record_only(amount)
            return True
        override = self._get_override(budget_type, question_id)
        ok = record.consume(amount, override_limit=override)
        if ok and question_id is not None:
            q = self._question_enforced_usage.setdefault(question_id, {})
            q[budget_type] = q.get(budget_type, 0) + amount
        return ok

    def check(self, budget_type: BudgetType, *, question_id: str | None = None) -> bool:
        """检查指定类型的预算是否还有剩余（不消耗）。"""
        record = self._records.get(budget_type)
        if record is None or budget_type in MONITOR_BUDGETS:
            return True
        if record.exhausted:
            # 若本问有更高覆盖，仍可继续
            override = self._get_override(budget_type, question_id)
            if override is not None and record.used < override:
                return True
            return False
        return True

    def remaining(
        self,
        budget_type: BudgetType,
        *,
        question_id: str | None = None,
    ) -> int:
        """获取剩余预算；监控项返回 -1。"""
        record = self._records.get(budget_type)
        if record is None or budget_type in MONITOR_BUDGETS:
            return -1
        override = self._get_override(budget_type, question_id)
        effective_limit = override if override is not None else record.limit
        return max(0, effective_limit - record.used)

    # ------------------------------------------------------------------
    # 监控型：记账
    # ------------------------------------------------------------------

    def record_monitor(
        self,
        budget_type: BudgetType,
        amount: int,
        *,
        question_id: str | None = None,
    ) -> None:
        """记账（TIME/TOKEN 用）。始终成功，永不阻塞。

        同时更新：当前小问用量（used，按问重置）、任务全程累计（run_total）、
        以及逐问累计（_question_monitor_usage），以便报告"每个问题消耗"。
        """
        record = self._records.get(budget_type)
        if record is None or amount <= 0:
            return
        record.record_only(amount)
        if question_id is not None and budget_type in MONITOR_BUDGETS:
            q_usage = self._question_monitor_usage.setdefault(question_id, {})
            q_usage[budget_type] = q_usage.get(budget_type, 0) + amount

    # ------------------------------------------------------------------
    # 每问配置
    # ------------------------------------------------------------------

    def set_question_limits(
        self,
        question_id: str,
        type_limits: dict[BudgetType, int],
    ) -> None:
        """为指定小问临时覆盖某些类型的上限。

        仅对强制项生效；监控项覆盖会被忽略。已存在的覆盖会被新值替换。
        """
        filtered = {
            bt: lim
            for bt, lim in type_limits.items()
            if bt in ENFORCED_BUDGETS and lim > 0
        }
        if not filtered:
            return
        self._question_limits[question_id] = filtered

    def get_question_limits(self, question_id: str) -> dict[BudgetType, int]:
        """获取指定小问的临时覆盖（无覆盖则返回空 dict）。"""
        return dict(self._question_limits.get(question_id, {}))

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def reset_for_new_question(self) -> None:
        """新小问开始时重置所有预算类型的"单问用量"（used）。

        强制项的 used 重置后重新开始计数；监控项（TIME/TOKEN）的 used 也
        重置为 0（其逐问累计保存在 _question_monitor_usage，全局累计 run_total
        永不重置），从而 get_question_usage 能正确报告"当前小问消耗"。
        """
        for record in self._records.values():
            record.reset()

    # ------------------------------------------------------------------
    # 报告
    # ------------------------------------------------------------------

    def get_record(self, budget_type: BudgetType) -> BudgetRecord | None:
        return self._records.get(budget_type)

    def all_records(self) -> dict[BudgetType, BudgetRecord]:
        return dict(self._records)

    def get_total_usage(self) -> dict[BudgetType, int]:
        """获取任务全程累计用量。"""
        return {bt: r.run_total for bt, r in self._records.items()}

    def get_question_usage(self) -> dict[BudgetType, int]:
        """获取当前小问的用量（reset 之后）。"""
        return {bt: r.used for bt, r in self._records.items()}

    def get_degradation_suggestions(self) -> list[str]:
        """获取降级建议（按优先级排序）。"""
        suggestions: list[str] = []
        for bt in DEGRADATION_ORDER:
            record = self._records.get(bt)
            if record is None:
                continue
            ratio = record.usage_ratio
            if ratio <= 0.7:
                continue
            if bt == BudgetType.SEARCH:
                suggestions.append(
                    f"检索预算已用 {ratio:.0%}，建议减少低价值检索"
                )
            elif bt == BudgetType.CANDIDATE:
                suggestions.append(
                    f"候选预算已用 {ratio:.0%}，建议优先简单基线方案"
                )
            elif bt == BudgetType.TOKEN:
                suggestions.append(
                    f"token 预算已用 {ratio:.0%}（监控项），建议减少非关键 LLM 调用"
                )
            elif bt == BudgetType.CODE_REPAIR:
                suggestions.append(
                    f"代码修复预算已用 {ratio:.0%}，建议简化模型实现"
                )
            elif bt == BudgetType.VALIDATION_ITERATION:
                suggestions.append(
                    f"验证迭代预算已用 {ratio:.0%}，建议接受当前结果并记录风险"
                )
        return suggestions

    def to_dict(self) -> dict:
        """序列化为字典（用于检查点、日志与前端报告）。"""
        per_q = self.get_question_usage()
        total = self.get_total_usage()
        # 监控项逐问累计（TIME/TOKEN）：{qid: {type_value: amount}}
        per_q_monitor = {
            qid: {bt.value: amt for bt, amt in usage.items()}
            for qid, usage in self._question_monitor_usage.items()
        }
        return {
            "limits": {bt.value: r.limit for bt, r in self._records.items()},
            "per_question_used": per_q,
            "run_total_used": total,
            "per_question_monitor_usage": per_q_monitor,
            "per_question_enforced_usage": {
                qid: {bt.value: amt for bt, amt in usage.items()}
                for qid, usage in self._question_enforced_usage.items()
            },
            "exhausted": {
                bt.value: r.exhausted
                for bt, r in self._records.items()
            },
            "usage_ratio": {
                bt.value: round(r.usage_ratio, 4)
                for bt, r in self._records.items()
            },
            "question_limit_overrides": {
                qid: {bt.value: lim for bt, lim in limits.items()}
                for qid, limits in self._question_limits.items()
            },
            "degradation_suggestions": self.get_degradation_suggestions(),
        }

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _get_override(
        self,
        budget_type: BudgetType,
        question_id: str | None,
    ) -> int | None:
        if question_id is None:
            return None
        return self._question_limits.get(question_id, {}).get(budget_type)