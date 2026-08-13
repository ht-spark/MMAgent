# 预算管理系统

`BudgetManager` 管理建模全流程的资源消耗，分**强制**（超额阻塞）和**监控**（纯统计）两类。

## 强制预算（6 项）

按小问计数，超额拒绝继续，每问重置。

| 类型 | 默认上限 | 管理内容 | 超额行为 | 配置时机 |
|------|---------|---------|---------|---------|
| `SEARCH` | 10 次/问 | 联网检索 | 跳过搜索 | 每问弹窗 |
| `CANDIDATE` | 4 个/问 | 方法候选 | 减少候选，优先简单基线 | 每问弹窗 |
| `CODE_REPAIR` | 3 次/问 | 代码修复（执行失败后重写） | 回退预设方法 | 每问弹窗 |
| `VALIDATION_ITERATION` | 2 次/问 | GQ 质量门整问重试 | 强制 blocked + 风险说明 | 每问弹窗 |
| `INTAKE_RETRY` | 3 次/问 | G0 输入质量门重试 | 强制 blocked | **任务启动时** |
| `PAPER_REVISION` | 2 次/问 | GF 交付质量门修订 | 接受当前版本，记录风险 | **任务启动时** |

## 监控预算（2 项）

全程累计，**无阈值**，不阻塞，仅用于事后统计报告。

| 类型 | 管理内容 |
|------|---------|
| `TIME` | 每问耗时 + 任务总耗时 |
| `TOKEN` | 每问 token + 任务总 token |

## 核心方法

| 方法 | 作用 |
|------|------|
| `consume(bt, qid)` | 消耗强制预算，超额返回 `False` |
| `check(bt, qid)` | 只读检查是否可继续（不消耗） |
| `record_monitor(bt, amount, qid)` | 监控型记账，始终成功 |
| `update_run_limits({bt: limit})` | 任务启动时配置任务级上限（INTAKE_RETRY/PAPER_REVISION） |
| `set_question_limits(qid, {bt: limit})` | 临时覆盖指定小问上限（每问级） |
| `reset_for_new_question()` | 新小问重置单问用量 |

## 用量追踪

每个预算类型维护两个计数器：

- **used** — 当前小问用量，按问重置
- **run_total** — 任务全程累计，永不重置

## 降级策略

使用率超过 70% 时，按优先级生成建议（从低价值到高价值）：

```
SEARCH → CANDIDATE → CODE_REPAIR → VALIDATION_ITERATION → INTAKE_RETRY → PAPER_REVISION
```

> TIME/TOKEN 纯监控，不参与降级。

## 弹窗配置流程

### 任务启动时（初始预算）

任务创建后、工作流启动前，弹出**任务预算配置**窗口：

| 设置项 | 对应预算类型 | 默认值 |
|--------|------------|--------|
| G0 输入质量门重试 | INTAKE_RETRY | 3 |
| GF 交付质量门修订 | PAPER_REVISION | 2 |

- **使用默认**：不覆盖，直接继续
- **确认覆盖**：通过 `update_run_limits()` 写入运行级上限

### 每问求解前（每问预算）

每个子问题求解前，弹出**确认预算**窗口：

| 设置项 | 对应预算类型 | 默认值 |
|--------|------------|--------|
| 联网检索次数 | SEARCH | 10 |
| 方法候选数量 | CANDIDATE | 4 |
| 代码修复次数 | CODE_REPAIR | 3 |
| 验证迭代次数 | VALIDATION_ITERATION | 2 |

- **使用默认**：不覆盖，直接继续
- **确认覆盖**：通过 `set_question_limits()` 仅对当前小问生效

## CODE_REPAIR vs VALIDATION_ITERATION

| 维度 | CODE_REPAIR | VALIDATION_ITERATION |
|------|------------|---------------------|
| 管理层 | model_builder 内部 | GQ 质量门 |
| 触发 | 代码执行失败（语法/超时） | 执行成功但结果未通过质量检查 |
| 重试范围 | 反馈 LLM 修复代码 | 整个小问重新求解 |
| 默认 | 3 次/问 | 2 次/问 |

## 预算控制流程

```
check() 只读检查 → 路由决策（可重试？）→ consume() 消耗预算 → can_retry 反映消耗后状态
```

- G0 门禁：消耗 `INTAKE_RETRY`，耗尽则 blocked
- GQ 门禁：消耗 `VALIDATION_ITERATION`，耗尽则 blocked + 风险说明
- GF 门禁：消耗 `PAPER_REVISION`，耗尽则接受当前版本
- 代码执行：消耗 `CODE_REPAIR`，耗尽则回退预设方法
