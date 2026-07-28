# 数学建模智能体 系统架构

> 文档定位：定义数学建模智能体的完整工作流架构。
>
> 核心范式：**七层子图 + 门控闭环 + 作用域状态 + 确定性工具**。

---

## 1. 设计原则

1. **题目理解先于建模**，任务拆解先于模型选择。
2. **每层出口设 Gate**：程序化校验 + 有界局部循环，错误就地消化，跨层升级为例外而非常态。
3. **数据画像前置**：ingest 即做附件盘点，模型硬过滤基于真实数据。
4. **数值由确定性工具产生**：LLM 不生成最终数值，只做推理与解释。
5. **状态按子问题分域**：回退只重跑受影响的最小节点集。
6. **论文分节生成，摘要最后**：数值与外部事实可追溯。
7. **审查分两层**：程序化检查先行，LLM 审查后行；路由表数据化，预算有界。
8. **可中断、可恢复**：checkpoint + run_id，人工门前后自动保存。

---

## 2. 架构总览：七层子图

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

![1785078822441](image/architecture/1785078822441.png)

## 3. 全局状态 State

### 3.1 分域状态

```python
class SubProblemRun(TypedDict, total=False):
    id: str
    status: Literal["pending", "formulated", "solved", "analyzed", "validated", "failed"]
    selected_model: dict
    execution: dict          # ExecutionResult 的路径引用
    analysis: dict
    validation: dict
    repair_count: int
    revision_count: int

class MathModelingState(TypedDict, total=False):
    run_id: str
    project_name: str

    # 输入
    problem_text: str
    competition_rules: dict
    input_files: list[str]

    # L0
    problem_analysis: dict
    subproblems: list[dict]
    problem_types: list[dict]
    data_inventory: dict          # 附件画像

    # L1
    knowledge_gaps: list[dict]
    search_plan: list[dict]
    search_round: int
    raw_search_results: list[dict]
    source_catalog: list[dict]
    evidence_items: list[dict]
    research_synthesis: list[dict]
    research_coverage: dict

    # L2
    model_candidates: list[dict]
    model_comparison: list[dict]
    selected_models: list[dict]
    model_critic_report: dict
    decision_log: list[dict]

    # L3
    data_requirements: list[dict]
    preprocessing_plan: list[dict]
    processed_data_paths: list[str]

    # L4（按子问题分域）
    subproblem_runs: dict[str, SubProblemRun]
    tables: list[str]
    figures: list[str]
    code_files: list[str]

    # L5
    paper_sections: dict[str, str]
    paper_draft_path: str
    citations: list[dict]

    # L6
    review_report: dict

    # 跨层
    budgets: dict               # search_rounds / code_repairs / paper_revisions / token_used / time_used
    gate_log: list[dict]        # 每个 Gate 的判定记录
    artifacts: dict[str, str]   # 逻辑名 -> 路径
    current_node: str
    workflow_status: str
    errors: list[dict]
```

### 3.2 状态铁律

1. 节点只返回部分更新，禁止覆盖整个 State。
2. State 不存 DataFrame / 网页正文 / 大段文本，只存路径与 ID。
3. 写作节点、审查节点不得修改执行结果。

---

## 4. 各层详细设计

### L0 摄入与理解

**节点**：ingest → data_inventory → understand → decompose → classify

- **ingest**：读取题目文本、比赛规则、附件路径；生成 `run_id`；创建产物目录 `artifacts/<run_id>/`。
- **data_inventory**：对全部附件做确定性画像（行列数、字段类型、缺失率、单位线索、时间维度），产物 `reports/data_inventory.json`。它是 L2 硬过滤的关键输入：无时间列 → 淘汰 ARIMA；样本量 < 30 → 淘汰机器学习类候选。
- **understand**：提取研究对象、背景、显式小问、约束、预期输出、关键词。禁止推荐模型或开始求解。
- **decompose**：拆为子问题，每个含 id、task、input_requirements、expected_outputs、dependencies、parallelizable。
- **classify**：判定主类型（evaluation / prediction / optimization / classification / simulation / mechanism / composite），允许一主多次。

**G1 理解门**（程序化）：所有显式小问已提取；子问题依赖无环（DAG 校验）；每个子问题有主类型。任一失败 → 重跑该节点（≤2 次）→ 人工。

### L1 研究子图

**节点**：gaps → queries → search → evaluate_sources → dedup → extract_evidence → synthesize

- **gaps**：识别知识缺口（domain_definition / mechanism / standard / data_source / model_precedent / parameter_range / evaluation_metric / validation_method / constraint / implementation）。
- **queries**：每个高优先缺口生成中英文查询组，带 purpose 与 source preference；不将完整题目作为唯一查询。
- **search**：查询级并行（LangGraph Send）；超时、重试、限流、备用 Provider。
- **evaluate_sources**：来源标准化 + 分级（S 政府/标准 / A 同行评审 / B 高校研究机构 / C 官方文档 / D 博客论坛）+ 评分（确定性公式，LLM 只出单项）。
- **dedup**：URL 规范化、标题相似度、DOI、同源转载标记。
- **extract_evidence**：一个证据项支撑一个 claim，必记来源 ID 与局限性，区分事实与推断；无来源 EvidenceItem 不允许。
- **synthesize**：每子问题输出 domain_findings / candidate_method_families / data_implications / validation_requirements / open_questions。

**G2 覆盖率门**：高优先缺口覆盖率、S/A 级来源数、独立模型来源数。未达标且轮次 < `MAX_SEARCH_ROUNDS`(3) → 回 queries；达标或耗尽 → 出图（耗尽标记 `evidence_risk`）。冲突证据显式入 State，不被静默删除。

### L2 模型决策子图

**节点**：generate_candidates → hard_filter → score → criticize → H1

- **generate_candidates**：每子问题生成 2–4 候选，来源 = 题型规则库 + 证据 + 数据画像 + 题目约束。每个候选含所需数据、假设、输出、验证方法、支持证据 ID、优点、局限、实现风险、淘汰条件。
- **hard_filter**（确定性）：无所需数据 / 核心假设不成立 / 不能回答题目 / 无法检验 / 计算规模不现实 → 淘汰，输出原因（可审计）。
- **score**：代码化评分公式——`0.25×problem_fit + 0.20×data_fit + 0.15×assumption_validity + 0.15×validation_feasibility + 0.10×interpretability + 0.10×implementation_feasibility + 0.05×innovation`。LLM 只出单项分与理由，Pydantic 约束分数 0–1，总分由代码计算。
- **criticize**：检查缺口覆盖、权威来源、候选差异、是否遗漏简单模型、假设合理性、数据可获得性、验证方法明确性、推荐可追溯性。
- **H1 人工确认（interrupt）**：展示推荐/备用模型、评分、证据摘要、数据匹配、风险；操作 `approve / replace_model / request_more_research / edit_constraints / cancel`。确认前后自动 checkpoint。

**G3 决策门**：Critic 裁决 `insufficient_evidence → L1`；`weak_candidates → 重生成`；`passed → H1`。未经人工确认不得进入求解。

### L3 数据子图

**节点**：plan_data → preprocess → quality_report

- **plan_data**：以 `selected_models` 为约束生成字段级需求（名称、字段、类型、单位、来源、缺失情况、预处理方式、质量风险）。
- **preprocess**：缺失值处理、异常值标记、标准化、正向化、类型转换、训练测试集划分、指标方向配置。原始数据不覆盖，每步有记录。
- **quality_report**：行列数、字段类型、缺失率、重复行、异常值、单位风险、常量列、高相关字段。

**G4 数据门**：字段齐备率、缺失率阈值、正负向指标配置。失败区分"可预处理修复"（回 preprocess）与"本质不足"（回 L2 换模型或人工）。

### L4 求解与检验子图

**节点（按子问题 fan-out）**：formulate → codegen → execute ⇄ repair → determinism_replay → analyze → validate

- **formulate**：产出假设、符号、模型公式。
- **codegen**：生成可运行代码。
- **execute**：沙箱执行，超时与资源限制。
- **repair**：失败分类（syntax / data / api / logic）→ 定向修复，≤ `MAX_CODE_REPAIR`(3)。
- **determinism_replay**：同参重跑，关键数值一致才接受（防随机性污染论文）。
- **analyze**：每子问题输出主要结果、关键数字、图表引用、影响因素、现实含义、限制、结论。禁止修改数值或编造实验。
- **validate**：按模型类型派发——评价（权重扰动、排名稳定性）/ 预测（MAE、RMSE、MAPE、残差）/ 优化（约束检查、参数扰动）/ 分类（准确率、召回率、F1、混淆矩阵）/ 仿真（多次仿真、参数敏感性）。含对比实验：若 `selected_models` 含 comparison_model，同数据同指标跑基线。

**G5 结果门**：数据问题 → L3（仅该子问题）；模型不适配 → L2（仅该子问题，其他缓存保留）；代码/收敛问题 → 局部修复环；通过 → fan-in barrier。

### L5 写作子图

**节点**：outline → section_writers → citation_registry → assemble → consistency_check → abstract

- **outline**：生成章节大纲。
- **section_writers**：分节生成（独立章节可并行）；摘要最后。
- **citation_registry**：外部事实 ↔ EvidenceItem，数值 ↔ ExecutionResult，模型理由 ↔ DecisionRecord。写作节点只读路径与 ID。
- **assemble**：组装完整论文。
- **consistency_check**（程序化）：论文所有关键数值必须能在 `execution_results` 中找到（正则/表格比对）；不一致即失败，不进入审查。
- **abstract**：最后生成，须含模型名称与核心结论。

**产物**：`artifacts/<run_id>/paper/paper_draft.md` + `citations.json`。

### L6 审查与交付

**节点**：programmatic_checks → llm_review → route → H2 → final_package

- **programmatic_checks**：question_coverage / section_completeness / figure_reference / table_reference / citation_integrity / numeric_consistency / symbol_definition / validation_presence / artifact_existence。全过才调 LLM，节省 token。
- **llm_review**：检查题意理解、建模逻辑、假设合理性、模型选择依据、证据充分性、结果解释、结论覆盖、论文表达。输出 ReviewIssue（含 category、location、severity、route_to、suggested_fix）。
- **H2 终审（interrupt）**：展示审查报告与产物清单；确认后进入交付。
- **final_package**：生成最终论文、代码、图表、结果表、审查报告、提交清单。

---

## 5. 门控与回退

### 5.1 Gate 判定规则

每个 Gate 输出：

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

`retry` 重跑当前层；`escalate` 跨层回退；`budget` 耗尽 → `human`。

### 5.2 集中式路由表

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

### 5.3 作用域回退规则

- 回退只重置该子问题的 `status` 与下游产物引用，**其他子问题缓存保留**，避免全链重跑。
- `critical` 优先于 `major`；同类按子问题 ID 排序处理，避免抖动。
- 预算耗尽 → `need_human_review`（保存 checkpoint，输出未决问题清单）。

---

## 6. 智能体角色

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

## 7. 运行时与可观测性

### 7.1 Checkpoint 与恢复

- 每个 Gate 之后、每个 interrupt 之前自动保存 State。
- 通过 `run_id`（thread_id）恢复，已完成节点不重复执行。

CLI：

```bash
python -m math_modeling_agent.main run \
  --problem examples/evaluation/problem.md \
  --data examples/evaluation/data.csv

python -m math_modeling_agent.main resume --run-id <run_id>
```

### 7.2 日志规范

记录：run_id、node_name、start/end_time、status、input/output_summary、tool_calls、provider、token_usage、retry_count、route_result、error_type。

禁止记录：API Key、`.env`、密码、原始敏感数据。

### 7.3 预算与降级

`budgets` 账本跟踪：search_rounds、code_repairs、paper_revisions、token_used、time_used。耗尽策略：降级（减少候选模型数、跳过对比实验）而非直接失败；无法降级 → `need_human_review`。

---

## 8. 产物规范

最终交付包 `artifacts/<run_id>/final/`：

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

## 9. LangGraph 落地

```python
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send, interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver

# 1. 每层编译为独立子图，单测粒度对齐 Phase
L0 = build_understanding_subgraph().compile()
L1 = build_research_subgraph().compile()
L2 = build_model_decision_subgraph().compile()
L3 = build_data_subgraph().compile()
L4 = build_solve_subgraph().compile()      # 内部用 Send 实现 fan-out
L5 = build_writing_subgraph().compile()
L6 = build_review_subgraph().compile()

# 2. 主图串联子图 + Gate 路由
main = StateGraph(MathModelingState)
main.add_node("L0", L0)
# ...
main.add_conditional_edges("L0_gate", route_g1, {"pass": "L1", "retry": "L0", "human": "human_l0"})
main.add_conditional_edges("L2", route_g3, {"pass": "L3", "back_research": "L1", "retry": "L2"})

# 3. 人工门用 interrupt 实现
def human_approval(state):
    decision = interrupt({"prompt": "model_approval", "payload": state["selected_models"]})
    return {"decision": decision}

# 4. Checkpoint + Resume
checkpointer = SqliteSaver.from_conn_string("artifacts/checkpoints.db")
app = main.compile(checkpointer=checkpointer)
```

要点：

- 子图独立编译，单测粒度对齐 Phase。
- `Send` 实现 L1 查询并行与 L4 子问题并行；fan-in barrier 在 synthesize 与 paper assembly。
- `interrupt` 用于 H1 / H2，恢复时通过 `Command(resume=...)` 注入决策。

---

## 10. 实施路线图

| 阶段               | 内容                                                             | 验收                                            |
| ------------------ | ---------------------------------------------------------------- | ----------------------------------------------- |
| Phase A 基础骨架   | 仓库基线、Schema、State、空节点图 + G1–G6 门控框架 + checkpoint | 空工作流可从 START 运行到 END，条件路由测试通过 |
| Phase B 理解与研究 | L0（含 data_inventory）、L1 研究子图、G1/G2                      | 输入题目输出子问题、知识缺口、搜索结果          |
| Phase C 模型决策   | L2 候选/过滤/评分/Critic/H1                                      | 每子问题有推荐与备用模型，理由可追溯            |
| Phase D 数据与求解 | L3、L4（含沙箱、自动修复、确定性复跑）                           | 三类 MVP 模型真实运行，数值可复现               |
| Phase E 分析与论文 | L4 analyze/validate、L5 分节写作 + 数值核对                      | 生成结果分析、检验报告、Markdown 论文           |
| Phase F 审查与交付 | L6 双层审查、作用域路由、final_package                           | 审查失败自动回退，通过生成交付包                |

三类 MVP 模型：综合评价（熵权法、TOPSIS）、预测（线性回归、多元回归）、优化（线性规划）。第一版只输出 Markdown 论文。

---

## 11. 设计原则总结

> **以子图分层为骨架，以 Gate 门控为闭环，以作用域状态实现精准回退，以确定性工具保证数值可信。**
