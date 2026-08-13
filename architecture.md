# MMAgent 系统架构

> **定位**：面向通用数学建模任务的端到端智能体。给定题目与附件，自动完成理解、建模、计算、验证与报告交付。
> **核心设定**：① 通用性优先，不针对单题做局限性修改；② **LLM-only 建模策略**——不做方法预设、不对问题分类后套用僵化方法，而是聚焦问题本身、具体问题具体分析。

---

## 1. 总体工作流

```
intake → context → G0 ─┐
                        ↓ (pass)
   select_question → assemble_context → configure_question_budget
      → solve_question(澄清→探索→建模→自评) → validate_result
      → GQ ── pass/blocked ──→ archive_result ──┐
            │ retry(回 solve_question)            │
            └────────────────────────────────────┘ (回到 select，直到无下一问)
                                                  ↓ (done)
   configure_delivery_budget → global_review → write_paper → review_paper
      → GF ── deliver / revise(回 write_paper) ──→ deliver → END
```

六阶段：① 摄入与数据画像（确定性）② 全局上下文与子任务拆分 ③ 逐问求解闭环（含验证）④ 全任务一致性审查 ⑤ 报告写作 ⑥ 交付质量门与交付。

---

## 2. 项目结构

```text
MMAgent/
├── scr/                        # 核心引擎（LangGraph 状态图）
│   ├── math_modeling_agent/    # 入口：main.py(CLI) / graph.py(主图) / state.py(状态) / llm.py(LLM 工厂)
│   ├── workflow/               # 工作流节点：intake(摄入) / project_context(上下文) / question_loop(逐子任务循环)
│   ├── agents/                 # 结构化推理（见下）
│   ├── gates/                  # 质量门：g0_intake / gq_question / gf_delivery
│   ├── schemas/                # Pydantic 数据契约（状态与 LLM 输出）
│   ├── tools/                  # 确定性工具：文件读取 / 代码执行 / 可视化 / 表格 / 搜索 / DOCX 转换
│   ├── runtime/                # 运行时：产物 / 检查点 / 预算 / 日志
│   ├── prompts/                # LLM 提示词模板
│   └── templates/              # 报告模板
├── server/                     # 服务层：FastAPI + SQLite（提交 / 异步执行 / 进度 / 产物托管）
├── web/                        # 前端：React + Vite（新建任务 / 进度 / 结果 / 历史）
├── tests/                      # 单元测试
├── examples/                   # 样例任务与附件
└── artifacts/                  # 每次运行的产物，按 run_id 隔离
```

**agents/ 关键模块**

| 模块 | 职责 |
|------|------|
| `base.py` | Agent 基类：prompt 加载、渲染、三级回退结构化输出 |
| `problem_analyst.py` | 任务理解 + 子任务拆分（DAG、依赖、歧义点）；不判题型、不分类 |
| `method_explorer.py` | LLM 从问题本身推导候选方法（可联网检索补充证据），由 LLM 决策定主方法；无硬过滤、无启发式评分 |
| `code_modeler.py` | 分两段调 LLM：先生成数学模型 JSON，再生成求解代码 |
| `model_builder.py` | 编排模型表述 → 数据准备 → 代码执行/确定性计算 → 图表/表格（含 CODE_REPAIR 重试） |
| `question_solver.py` | 单问端到端编排：澄清 → 方法探索 → 建模计算 → 自评 → 生成可复用摘要 |
| `result_validator.py` | 按子任务契约做确定性验证（约束可行性、残差、权重扰动、种子复现、量纲、数据泄漏等） |
| `paper_writer.py` | 从各子任务结果包生成竞赛报告（Markdown + DOCX） |
| `reviewer.py` | 评委视角审查：覆盖性、一致性、可追溯性、验证充分性、格式合规 |

---

## 3. 核心设计原则

- **LLM-only 驱动建模**：方法由 LLM 从问题本身推导，不预设方法库、不按题型分支套用；联网检索仅作补充证据，不替代 LLM 判断。
- **契约而非分类**：子任务的验收依据是问题契约（`result_form` / `required_outputs` / `formulation`），而非粗糙的"题型标签"。
- **聚焦问题本身**：每个子任务独立分析其数学结构、假设与求解路径，可解释性与可复现性优先。
- **数值可复现**：所有图表、表格与关键数字由确定性代码生成，可追溯至数据与代码版本。
- **系统性降级**：任何节点异常不终止整题，隔离后继续；预算耗尽产出风险说明而非伪造通过。

---

## 4. 逐问求解闭环（solve_question 内部）

1. **装配上下文**：当前子任务原文 + 目标、相关全局约束、数据质量信息、前序子任务的 `reusable_summary`（仅继承结论、可复用数据、模型接口与限制）。
2. **问题澄清**：明确决策变量、目标函数、约束、必要假设，以及与前序任务的关系（继承 / 比较 / 改进 / 独立）。
3. **方法探索（LLM-only）**：LLM 从问题推导候选方法（可联网检索），由 LLM 决策选定主方法并映射到可执行实现，输出选择理由、放弃理由与验证计划。
4. **建模计算**：输出规范化模型表述（假设 / 符号 / 变量 / 约束 / 推导）→ 确定性工具或沙箱代码执行，记录数据版本、代码路径、参数、随机种子与结果文件。
5. **结果验证（validate_result）**：按子任务契约组合检查，覆盖约束可行性、残差、权重扰动稳定性、种子复现、单位量级、数据泄漏等。
6. **自评沉淀**：自评结论完整性，生成 `reusable_summary`（已验证结论 + 局限），供后续任务与报告写作复用。

---

## 5. 三道质量门

| 门 | 检查内容 | 失败处理 |
|----|---------|---------|
| **G0** 输入门 | 子任务完整、附件已读、依赖无环、数据缺口已记录 | 重跑摄入；硬失败 + 预算耗尽 → 人工澄清（终止或补材料） |
| **GQ** 子任务门 | 契约达成：问题契约交付物齐备、方法/假设/参数可解释、计算可复现、验证完成、局限与 `reusable_summary` 已记录 | 消耗 `VALIDATION_ITERATION` 后重试；耗尽 → `blocked`（不伪造通过） |
| **GF** 交付门 | 完整性：`review_report` 存在且无 critical、状态非 failed、`paper_draft` 存在且非空（含章节 / 摘要） | 消耗 `PAPER_REVISION` 后修订重写；**预算耗尽 → 强制交付并记录风险** |

> **GQ 为契约驱动**：校验 `result_form` / `required_outputs` / `formulation` 声明的交付物是否被计算结果 / 表格 / 图表 / 结论证据覆盖，不按题型硬编码输出键。
> **GF 为完整性门而非质量门**：只验证产物存在与审查结论，不验证方法正确性或答案达成度；预算耗尽即放行（保留风险记录）。

---

## 6. 预算与降级

`BudgetManager` 统一管理两类预算：

- **强制项**（按小问独立计数、超额拒绝、每问开始重置、可临时覆盖）：`SEARCH=10`、`CANDIDATE=4`、`CODE_REPAIR=3`、`VALIDATION_ITERATION=2`、`INTAKE_RETRY=3`、`PAPER_REVISION=2`。
- **监控项**（全程累计、不阻塞、仅统计）：`TIME`、`TOKEN`。

Web 端可在每问求解前（`budget_config_callback`）覆盖单问上限，所有子任务完成后（`delivery_budget_config_callback`）配置 GF 修订预算。预算紧张时按「减少低价值检索 → 优先简单基线 → 减少非关键图表」降级，但不跳过数据质量、数值复现与任务覆盖检查。

---

## 7. 产物与可复现

```text
artifacts/<run_id>/
  run.log                 # 结构化运行日志
  paper.md / paper.docx   # 建模报告
  review_report.json      # 审查报告
  input/                  # 原始任务与附件登记
  context/                # 数据画像、依赖图
  questions/<qid>/        # 每问代码、数据、图表、结果包
  figures/                # 报告图表
```

原始输入只读；随机过程记录种子与重复次数；每张图、每个表、每个关键数字均可追溯到代码与数据版本。

---

## 8. 服务层与前端

- **server/**：FastAPI + SQLite。`POST /api/runs` 提交（题目 + 数据 + 模型配置），后台 `asyncio.to_thread` 执行；`GET /api/runs/{id}/progress/stream` 以 SSE 实时推送节点进度；可经回调触发预算弹窗与 G0 人工澄清；根路径静态托管 `web/dist`。
- **web/**：React + Vite 聊天式建模界面。提交后订阅 SSE 实时渲染进度，支持预算确认、结果查看与接管进行中任务。
