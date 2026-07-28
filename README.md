# MMAgent · 数学建模智能体

> 一个面向数学建模竞赛/应用题目的专用智能体系统。
> 核心范式：**七层子图 + 门控闭环 + 作用域状态 + 确定性工具**。

MMAgent 把一道数学建模题（含题目文本、附件数据、竞赛规则）自动推进为一份结构完整、数值可复现、来源可追溯的 Markdown 论文，并在每个关键节点设置程序化闸门与人工确认点，确保**推理可信、数值可靠、过程可中断可恢复**。

---

## 目录

- [特性](#特性)
- [核心范式](#核心范式)
- [系统架构](#系统架构)
- [全局状态模型](#全局状态模型)
- [门控与回退机制](#门控与回退机制)
- [智能体角色](#智能体角色)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [开发路线图](#开发路线图)
- [产物规范](#产物规范)
- [设计原则](#设计原则)
- [当前实现状态](#当前实现状态)
- [许可证](#许可证)

---

## 特性

- **题目理解先于建模**：L0 阶段只做理解、拆解、分类，禁止提前推荐模型或求解。
- **数据画像前置**：ingest 即对所有附件做确定性画像（行列数、字段类型、缺失率、单位线索、时间维度），作为模型硬过滤的客观依据。
- **确定性数值**：所有最终数值（熵权法、TOPSIS、回归、线性规划、校验指标）由纯函数工具产生，LLM 只负责推理与解释，不生成数值。
- **七层门控闭环**：每层出口设程序化 Gate，错误就地消化（有界局部循环），跨层升级为例外而非常态。
- **作用域精准回退**：按子问题分域，回退只重跑受影响的最小节点集，其他子问题缓存保留。
- **证据可追溯**：搜索结果必须经"评级→去重→证据提取→综合"管线，模型选择与论文数值均能追溯到 `EvidenceItem` 与 `ExecutionResult`。
- **可中断可恢复**：每个 Gate 之后、每个人工门之前自动保存 checkpoint，通过 `run_id` 恢复，已完成的节点不重复执行。
- **双层审查**：程序化检查先行（省 token），LLM 审查后行；审查问题按数据化路由表回退，预算有界。

---

## 核心范式

| 支柱             | 含义                                                                                       |
| ---------------- | ------------------------------------------------------------------------------------------ |
| **七层子图**     | 按建模现实逻辑拆分为 L0–L6 共七层，每层编译为独立 LangGraph 子图，单测粒度对齐开发阶段。   |
| **门控闭环**     | 每层出口设 Gate（G1–G6），程序化校验 + 有界局部循环，错误就地消化。                        |
| **作用域状态**   | 状态按子问题分域（`subproblem_runs`），回退只重置受影响节点，避免全链重跑。                |
| **确定性工具**   | `tools/` 不依赖 LLM，可单测、可复现；LLM 只做推理与解释。                                  |

**状态铁律**：

1. 节点只返回部分 State 更新，禁止覆盖整个 State。
2. State 不存 DataFrame / 网页正文 / 大段文本，只存路径与 ID。
3. 写作节点、审查节点不得修改执行结果。

---

## 系统架构

### 七层工作流

```
START
  │
  ▼
┌─ L0 摄入与理解 ──────────────────────────────┐
│ ingest → data_inventory → understand          │
│ → decompose → classify                        │
└──────────┬───────────────────────────────────┘
        G1 理解门（程序校验 + 可选人工）
           ▼
┌─ L1 研究子图 ────────────────────────────────┐
│ gaps → queries → search(并行) → 来源评级       │
│ → 去重 → 证据 → 综合                          │
└──────────┬───────────────────────────────────┘
        G2 覆盖率门（≤3 轮局部循环）
           ▼
┌─ L2 模型决策子图 ────────────────────────────┐
│ 候选生成 → 硬过滤(数据画像) → 评分            │
│ → Critic → H1 人工确认(interrupt)            │
└──────────┬───────────────────────────────────┘
        G3 决策门（≤3 轮；证据不足回 L1）
           ▼
┌─ L3 数据子图 ────────────────────────────────┐
│ plan_data → preprocess → 质量报告             │
└──────────┬───────────────────────────────────┘
        G4 数据门（不满足 → 回 L2 换模型/人工）
           ▼
┌─ L4 求解与检验子图（按子问题并行 fan-out）────┐
│ formulate → codegen → 沙箱执行 ⇄ 自动修复     │
│ → 确定性复跑 → 结果分析 → 模型检验            │
└──────────┬───────────────────────────────────┘
        G5 结果门（作用域回退：L2 / L3 / 局部）
           ▼
┌─ L5 写作子图 ────────────────────────────────┐
│ outline → 分节写作 → 引用注册 → 组装          │
│ → 数值一致性核对 → 摘要（最后）               │
└──────────┬───────────────────────────────────┘
        G6 审查门（程序审查 → LLM 审查，≤3 轮）
           ▼
        H2 终审人工确认（interrupt）
           ▼
        final_package → END
```

### 各层职责

| 层   | 子图                     | 关键节点                                                         | 闸门            |
| ---- | ------------------------ | ---------------------------------------------------------------- | --------------- |
| L0   | 摄入与理解               | ingest / data_inventory / understand / decompose / classify       | G1 理解门       |
| L1   | 研究                     | gaps / queries / search / 评级 / 去重 / evidence / synthesize     | G2 覆盖率门     |
| L2   | 模型决策                 | 候选生成 / hard_filter / score / criticize / H1                   | G3 决策门       |
| L3   | 数据                     | plan_data / preprocess / quality_report                          | G4 数据门       |
| L4   | 求解与检验               | formulate / codegen / execute⇄repair / replay / analyze / validate | G5 结果门     |
| L5   | 写作                     | outline / section_writers / citation / assemble / consistency / abstract | （G6 前序） |
| L6   | 审查与交付               | programmatic_checks / llm_review / route / H2 / final_package     | G6 审查门       |

---

## 全局状态模型

`MathModelingState`（TypedDict）采用**分域状态**：子问题的运行态集中在 `subproblem_runs: dict[str, SubProblemRun]`，主状态只保留各层产出字段的引用（路径 / ID）。核心分区：

- **输入**：`problem_text` / `competition_rules` / `input_files`
- **L0**：`problem_analysis` / `subproblems` / `problem_types` / `data_inventory`
- **L1**：`knowledge_gaps` / `search_plan` / `source_catalog` / `evidence_items` / `research_synthesis` / `research_coverage`
- **L2**：`model_candidates` / `model_comparison` / `selected_models` / `model_critic_report` / `decision_log`
- **L3**：`data_requirements` / `preprocessing_plan` / `processed_data_paths`
- **L4**：`subproblem_runs` / `tables` / `figures` / `code_files`
- **L5**：`paper_sections` / `paper_draft_path` / `citations`
- **L6**：`review_report`
- **跨层**：`budgets` / `gate_log` / `artifacts` / `current_node` / `workflow_status` / `errors`

完整字段定义见 `architecture.md §3`。

---

## 门控与回退机制

### Gate 判定输出

每个 Gate 输出统一的 `GateResult`：

```json
{
  "gate_id": "G2",
  "passed": false,
  "failed_checks": ["high_priority_gap_coverage < 1.0"],
  "action": "retry | escalate | human | pass",
  "budget_used": 2,
  "budget_remaining": 1
}
```

- `retry` 重跑当前层；`escalate` 跨层回退；预算耗尽 → `human`。

### 集中式路由表（节选）

| issue.category  | 默认路由                          | 作用域 | 预算 |
| --------------- | --------------------------------- | ------ | ---- |
| understanding   | understand_problem（L0）          | 全局   | 2    |
| evidence        | plan_research / queries（L1）     | 全局   | 3    |
| model_selection | compare_models / score（L2）      | 子问题 | 3    |
| data            | plan_data / preprocess_data（L3） | 子问题 | 3    |
| code            | solve_model 局部修复环（L4）      | 子问题 | 3    |
| validation      | validate_model（L4）              | 子问题 | 2    |
| writing         | write_paper 仅受影响章节（L5）    | 章节   | 3    |
| format          | write_paper 局部（L5）            | 章节   | 2    |

### 作用域回退规则

- 回退只重置该子问题的 `status` 与下游产物引用，**其他子问题缓存保留**。
- `critical` 优先于 `major`；同类按子问题 ID 排序处理，避免抖动。
- 预算耗尽 → `need_human_review`（保存 checkpoint，输出未决问题清单）。

---

## 智能体角色

| 智能体                      | 所属层 | 职责                               | 主要输出                     |
| --------------------------- | ------ | ---------------------------------- | ---------------------------- |
| Orchestrator                | 跨层   | 控制流程、维护状态、决定路由       | workflow 状态、下一步任务    |
| Problem Understanding Agent | L0     | 解析题目背景、目标、约束           | 问题摘要、关键词、目标清单   |
| Data Inventory Agent        | L0     | 附件确定性画像                     | data_inventory               |
| Research Agent              | L1     | 查询规划、搜索、来源评级、证据提取 | 证据、研究综合               |
| Modeling Agent              | L2     | 候选生成、评分、Critic             | 候选模型、模型比较、决策记录 |
| Solver Agent                | L4     | 公式生成、代码生成、沙箱执行       | ExecutionResult、图表        |
| Result Analyst Agent        | L4     | 解释结果含义                       | 结果分析                     |
| Validation Agent            | L4     | 误差、敏感性、稳健性               | 检验报告                     |
| Paper Writer Agent          | L5     | 分节生成论文                       | 论文初稿、引用               |
| Reviewer Agent              | L6     | 程序审查 + LLM 审查                | 审查清单、修改建议           |
| Final Packaging Agent       | L6     | 整理交付                           | 最终论文、代码、清单         |

---

## 目录结构

源代码位于 `scr/`，目录划分对齐 architecture.md 的七层子图与横切关注点：

```text
D:\MMAgent\
├── scr/                              # 源码包
│   ├── math_modeling_agent/          # 应用入口与横切配置
│   │   ├── __init__.py
│   │   ├── main.py                   # CLI 入口：run / resume
│   │   ├── config.py                 # 环境变量配置（LLM 等）
│   │   ├── graph.py                  # 主图组装 + Gate 路由 + 子图串联
│   │   └── state.py                  # MathModelingState / SubProblemRun
│   │
│   ├── schemas/                      # Pydantic 数据契约（无逻辑）
│   │   ├── common.py                 # NodeStatus / NodeIssue / GateResult
│   │   ├── problem.py                # ProblemAnalysis / SubProblem / DataInventory
│   │   └── research.py               # KnowledgeGap / EvidenceItem / ...
│   │
│   ├── agents/                       # LLM Agent（prompt + 结构化输出）
│   │   ├── base.py                   # BaseAgent：LLM 调用、重试、结构化输出校验
│   │   ├── problem_analyst.py        # L0
│   │   └── research_agent.py         # L1
│   │
│   ├── gates/                        # 程序化门控（可独立单测）
│   │   ├── base.py                   # Gate 协议, GateResult
│   │   └── g1_understanding.py       # 小问完整、DAG 无环、主类型齐备
│   │
│   ├── layers/                       # 七层子图编排
│   │   └── l0_understanding.py       # ingest→...→classify + G1
│   │
│   └── tools/                        # 确定性计算工具（不依赖 LLM）
│       ├── file_tools.py             # CSV/Excel/JSON/MD 读取
│       └── data_tools.py             # data_inventory、质量报告、预处理（规划）
│
├── tests/                            # 单元测试 / 集成测试 / 工作流测试
├── data/                             # input/ 与 processed/ 数据目录
├── artifacts/                        # 运行产物（gitignore，按 run_id 分目录）
├── architecture.md                   # 系统架构说明
├── plan.md                           # 开发计划与目录结构蓝图
├── pyproject.toml
└── README.md
```

> 说明：`plan.md` 中的完整目录蓝图（research / providers / runtime / prompts / routing 等）是后续阶段的实现目标；当前仓库已落地的模块见上文与[当前实现状态](#当前实现状态)。

---

## 快速开始

### 环境要求

- Python ≥ 3.11
- 可访问的 OpenAI 兼容 LLM API（通过环境变量配置，支持第三方 `base_url`）

### 安装

```bash
# 克隆仓库
git clone <repo-url> && cd MMAgent

# 安装依赖（推荐虚拟环境）
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

依赖见 `pyproject.toml`：`langgraph` / `langchain` / `langchain-openai` / `pydantic` / `pandas` / `numpy` / `scipy` / `scikit-learn` / `matplotlib` / `pulp` / `httpx` / `tenacity` 等。

### 配置

复制 `.env.example` 为 `.env` 并填写：

```ini
OPENAI_API_KEY=sk-xxxxxxxx
MODEL_NAME=gpt-4o
OPENAI_BASE_URL=              # 可选，兼容第三方 API
TEMPERATURE=0.0               # 默认 0.0，保证确定性输出
```

### 运行

> 以下为 `plan.md` 规划的 CLI 形态，随 L6 收尾阶段落地：

```bash
# 运行一道题
python -m math_modeling_agent.main run \
  --problem examples/evaluation/problem.md \
  --data examples/evaluation/data.csv

# 从 checkpoint 恢复
python -m math_modeling_agent.main resume --run-id <run_id>
```

### 运行测试

```bash
pytest
```

---

## 开发路线图

| 阶段 | 名称             | 核心交付                          | 对应架构层 |
| ---- | ---------------- | --------------------------------- | ---------- |
| 0    | 仓库基线与运行时 | 可安装、可启动、配置可读          | 横切       |
| 1    | Schema 与 State  | 完整数据契约 + 分域状态           | §3         |
| 2    | LangGraph 骨架   | 空节点图可跑通 + Gate 协议        | §2 §5      |
| 3    | L0 摄入与理解    | 题目可拆解分类 + data_inventory   | L0 + G1    |
| 4    | L1 研究管线      | 规范化搜索 + 证据管线             | L1 + G2    |
| 5    | L2 模型决策      | 候选/过滤/评分/Critic/H1          | L2 + G3    |
| 6    | L3 数据处理      | 数据规划 + 预处理 + 质量门        | L3 + G4    |
| 7    | L4 求解与检验    | 沙箱 + 修复 + 确定性复跑 + 检验   | L4 + G5    |
| 8    | L5 论文写作      | 分节生成 + 引用 + 数值核对        | L5         |
| 9    | L6 审查与交付    | 双层审查 + 作用域路由 + 交付包    | L6 + G6 + H2 |

**三类 MVP 模型**（第一版只输出 Markdown 论文）：

- 综合评价：熵权法、TOPSIS
- 预测：线性回归、多元回归
- 优化：线性规划

---

## 产物规范

每个运行的产物按 `run_id` 落在 `artifacts/<run_id>/`，最终交付包为 `artifacts/<run_id>/final/`：

```
paper_final.md
problem_analysis.json
research_report.json
evidence_catalog.json
model_decision.json
preprocessing_report.json
execution_results.json
validation_report.json
review_report.json
submission_checklist.md
code/
figures/
tables/
```

提交清单自动生成：论文可打开、编号正确、图表完整、代码已保存、格式符合要求。

---

## 设计原则

1. **题目理解先于建模**，任务拆解先于模型选择。
2. 按建模现实逻辑编排工作流。
3. 每层出口设 Gate：程序化校验 + 有界局部循环，错误就地消化。
4. 数据画像前置：ingest 即做附件盘点，模型硬过滤基于真实数据。
5. 数值由确定性工具产生：LLM 不生成最终数值。
6. 状态按子问题分域：回退只重跑受影响的最小节点集。
7. 论文分节生成，摘要最后：数值与外部事实可追溯。
8. 审查分两层：程序化检查先行，LLM 审查后行。
9. 可中断、可恢复：checkpoint + run_id，人工门前后自动保存。

> **以子图分层为骨架，以 Gate 门控为闭环，以作用域状态实现精准回退，以确定性工具保证数值可信。**

---

## 当前实现状态

项目正在按路线图积极开发中。已落地（部分）：

- ✅ **Phase 1 Schema 与 State**：`schemas/`（common / problem / research）、`state.py` 分域状态。
- ✅ **Phase 3 L0 摄入与理解**：`tools/file_tools.py`、`agents/problem_analyst.py`、`gates/g1_understanding.py`、`layers/l0_understanding.py`，以及对应单元测试。
- ✅ **Phase 4 起步**：`agents/research_agent.py` 证据管线骨架。
- 🚧 其余层（L1 完整管线 / L2–L6）、`runtime/`（沙箱、checkpoint、预算）、`providers/`、`prompts/`、`routing/` 等按计划推进中。

详细的架构与分阶段验收标准见 `architecture.md` 与 `plan.md`。

---

## 许可证

见仓库 `LICENSE` 文件。

---

## 相关文档

- [`architecture.md`](architecture.md) — 系统架构：七层子图、状态模型、门控与回退、智能体角色、LangGraph 落地。
- [`plan.md`](plan.md) — 开发计划：目录结构蓝图、Phase 0–9 任务拆解与验收标准。
