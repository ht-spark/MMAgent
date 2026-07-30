"""预算与降级管理。

对应 architecture.md §8.3：
  预算包括联网检索次数、方法候选数量、代码修复次数、验证迭代次数、时间和令牌。
  预算紧张时的降级顺序为：减少低价值候选、优先简单基线、减少非关键图表、
  保留必要验证；不得跳过数据质量检查、数值复现和题目覆盖检查。
"""
from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from typing import Literal


class BudgetType(str, Enum):
    """预算类型。"""
    SEARCH = "search"                    # 联网检索次数
    CANDIDATE = "candidate"              # 方法候选数量
    CODE_REPAIR = "code_repair"          # 代码修复次数
    VALIDATION_ITERATION = "validation"  # 验证迭代次数
    TIME = "time"                        # 时间预算（秒）
    TOKEN = "token"                      # 令牌预算


# 默认预算配置
DEFAULT_BUDGETS: dict[BudgetType, int] = {
    BudgetType.SEARCH: 10,
    BudgetType.CANDIDATE: 4,
    BudgetType.CODE_REPAIR: 3,
    BudgetType.VALIDATION_ITERATION: 2,
    BudgetType.TIME: 3600,  # 1 小时
    BudgetType.TOKEN: 100000,
}

# 降级顺序（从低价值到高价值）
DEGRADATION_ORDER: list[BudgetType] = [
    BudgetType.SEARCH,          # 先减少检索
    BudgetType.CANDIDATE,       # 再减少候选
    BudgetType.TOKEN,           # 再减少令牌消耗
    BudgetType.CODE_REPAIR,     # 再减少代码修复
    BudgetType.VALIDATION_ITERATION,  # 最后减少验证
    # TIME 不可降级
]


@dataclass
class BudgetRecord:
    """单个预算类型的记录。"""
    budget_type: BudgetType
    limit: int
    used: int = 0
    unit: str = "次"
    
    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)
    
    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit
    
    @property
    def usage_ratio(self) -> float:
        return self.used / self.limit if self.limit > 0 else 1.0
    
    def consume(self, amount: int = 1) -> bool:
        """消耗预算，返回是否成功。"""
        if self.used + amount > self.limit:
            return False
        self.used += amount
        return True
    
    def reset(self) -> None:
        """重置已用预算（用于新小问开始时）。"""
        self.used = 0


class BudgetManager:
    """预算管理器。
    
    管理各类资源预算，支持消耗、检查剩余和降级建议。
    
    Args:
        budgets: 可选的自定义预算配置。未指定的类型使用 DEFAULT_BUDGETS。
    """
    
    def __init__(self, budgets: dict[BudgetType, int] | None = None) -> None:
        config = {**DEFAULT_BUDGETS, **(budgets or {})}
        self._records: dict[BudgetType, BudgetRecord] = {
            bt: BudgetRecord(
                budget_type=bt,
                limit=limit,
                unit="秒" if bt == BudgetType.TIME else "个" if bt == BudgetType.CANDIDATE else "次",
            )
            for bt, limit in config.items()
        }
    
    def consume(self, budget_type: BudgetType, amount: int = 1) -> bool:
        """消耗指定类型的预算。"""
        record = self._records.get(budget_type)
        if record is None:
            return True  # 未配置的预算类型不限制
        return record.consume(amount)
    
    def check(self, budget_type: BudgetType) -> bool:
        """检查指定类型的预算是否还有剩余。"""
        record = self._records.get(budget_type)
        if record is None:
            return True
        return not record.exhausted
    
    def remaining(self, budget_type: BudgetType) -> int:
        """获取指定类型的剩余预算。"""
        record = self._records.get(budget_type)
        if record is None:
            return -1  # 无限
        return record.remaining
    
    def get_record(self, budget_type: BudgetType) -> BudgetRecord | None:
        """获取预算记录。"""
        return self._records.get(budget_type)
    
    def all_records(self) -> dict[BudgetType, BudgetRecord]:
        """获取所有预算记录。"""
        return dict(self._records)
    
    def reset_for_new_question(self) -> None:
        """新小问开始时重置小问级预算（代码修复和验证迭代）。"""
        for bt in [BudgetType.CODE_REPAIR, BudgetType.VALIDATION_ITERATION]:
            record = self._records.get(bt)
            if record:
                record.reset()
    
    def get_degradation_suggestions(self) -> list[str]:
        """获取降级建议（按优先级排序）。"""
        suggestions: list[str] = []
        for bt in DEGRADATION_ORDER:
            record = self._records.get(bt)
            if record and record.usage_ratio > 0.7:
                if bt == BudgetType.SEARCH:
                    suggestions.append(f"检索预算已用 {record.usage_ratio:.0%}，建议减少低价值检索")
                elif bt == BudgetType.CANDIDATE:
                    suggestions.append(f"候选预算已用 {record.usage_ratio:.0%}，建议优先简单基线方案")
                elif bt == BudgetType.TOKEN:
                    suggestions.append(f"令牌预算已用 {record.usage_ratio:.0%}，建议减少非关键 LLM 调用")
                elif bt == BudgetType.CODE_REPAIR:
                    suggestions.append(f"代码修复预算已用 {record.usage_ratio:.0%}，建议简化模型实现")
                elif bt == BudgetType.VALIDATION_ITERATION:
                    suggestions.append(f"验证迭代预算已用 {record.usage_ratio:.0%}，建议接受当前结果并记录风险")
        return suggestions
    
    def to_dict(self) -> dict[str, dict]:
        """序列化为字典（用于检查点和日志）。"""
        return {
            bt.value: {
                "limit": r.limit,
                "used": r.used,
                "remaining": r.remaining,
                "exhausted": r.exhausted,
            }
            for bt, r in self._records.items()
        }
