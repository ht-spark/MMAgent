## 一、g0 门控架构总结

### 定位

G0 是建模流程的**入口质量门**，位于输入摄入（intake）和上下文建立（context）之后、逐问求解之前。对应脚本：`scr/gates/g0_intake.py`。

### 检查项（6 项）

| 序号 | 检查项 | 失败标识 | 类型 |
|---|---|---|---|
| 1 | ProjectContext 存在且有小问 | `project_context_missing` / `questions_empty` | 硬失败 |
| 2 | 每问有目标和预期输出 | `{qid}_objective_empty` / `{qid}_expected_output_empty` | 软失败 |
| 3 | 依赖关系无环 | `dependency_cycle_detected` | 硬失败 |
| 4 | 附件文件状态明确 | `file_{name}_unknown_status` / `file_{name}_error_missing` | 软失败 |
| 5 | 任务文本非空 | `problem_text_empty` | 硬失败 |
| 6 | 检测 fallback 生成的问题 | `decomposition_fallback_used` | 软失败 |

### 路由逻辑

```
无失败项 → pass（进入逐问求解）

有失败项 + 有剩余预算 → retry（重跑 intake + context）

有失败项 + 预算耗尽 + 含硬失败 → human（人工介入弹窗）

有失败项 + 预算耗尽 + 仅软失败 → pass（降级通过，记录风险）
```

### 预算管理

通过 `BudgetManager` 的 `INTAKE_RETRY` 类型管理重试上限，默认 3 次。每次重试消耗 1 次预算，耗尽后不再重试。

### 硬失败集合

`G0_HARD_FAILURES = {project_context_missing, questions_empty, dependency_cycle_detected, problem_text_empty}`

不在该集合中的检查项均为软失败，允许预算耗尽后降级通过。

### LangGraph 集成

`route_g0(state)` 作为条件边路由函数，返回 `"pass"` / `"retry"` / `"human"` 三个值，分别对应三条边。其中 `"human"` 触发前端的澄清弹窗交互，终止建模或上传补充材料。


## 二、gq 门控架构总结
