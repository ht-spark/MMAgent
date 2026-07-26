# 数学建模智能体 开发计划

> 文档关系：
>
> - `spec.md`：能力与业务规则、验收要求。
> - `architecture.md`：七层子图架构基准（L0–L6 + G1–G6 + H1/H2）。
> - `plan.md`（本文件）：项目文件结构与开发顺序。

---

# 第一部分 · 项目文件结构

## 1. 设计原则

1. **结构即架构**：目录划分对齐 architecture.md 的七层子图，一个目录对应一层或一个横切关注点。
2. **数据契约先行**：`schemas/` 独立于业务逻辑，所有节点先依赖 Schema 再实现。
3. **确定性工具独立**：`tools/` 不依赖 LLM，可单测、可复现。
4. **Gate 可复用**：`gates/` 独立于子图，按层引用，便于单测。
5. **运行时横切**：`runtime/`（sandbox / checkpoint / budget / logging）被所有层共享。
6. **Prompt 与代码分离**：`prompts/` 存模板，便于版本管理与 A/B 测试。

## 2. 完整目录结构

```text
project-root/
├── src/
│   └── math_modeling_agent/
│       ├── __init__.py
│       ├── main.py                     # CLI 入口：run / resume
│       ├── config.py                   # pydantic-settings 配置
│       ├── state.py                    # MathModelingState, SubProblemRun, Budgets
│       ├── graph.py                    # 主图组装 + Gate 路由 + 子图串联
│       │
│       ├── schemas/                    # Pydantic 数据契约（无逻辑）
│       │   ├── __init__.py
│       │   ├── common.py               # NodeStatus, NodeIssue, NodeResult, GateResult
│       │   ├── budget.py               # Budgets, BudgetLimit, BudgetSnapshot
│       │   ├── problem.py              # ProblemAnalysis, SubProblem, ProblemClassification, DataInventory
│       │   ├── research.py             # KnowledgeGap, SearchRequest, SearchResult, SourceRecord, EvidenceItem, ResearchSynthesis, ResearchCoverage
│       │   ├── model.py                # ModelCandidate, ModelScore, ModelComparison, ModelCriticReport, DecisionRecord
│       │   ├── data.py                 # DataRequirement, PreprocessingReport, QualityReport
│       │   ├── result.py               # ExecutionResult, ResultAnalysis, ValidationReport
│       │   └── paper.py                # PaperSection, CitationRecord, ReviewIssue, ReviewReport
│       │
│       ├── layers/                     # 七层子图（每文件一子图 + Gate）
│       │   ├── __init__.py
│       │   ├── l0_understanding.py     # ingest→data_inventory→understand→decompose→classify + G1
│       │   ├── l1_research.py          # gaps→queries→search→评级→去重→证据→综合 + G2
│       │   ├── l2_model_decision.py    # candidates→hard_filter→score→critic→H1 + G3
│       │   ├── l3_data.py              # plan_data→preprocess→quality + G4
│       │   ├── l4_solve.py             # formulate→codegen→exec⇄repair→replay→analyze→validate + G5（Send fan-out）
│       │   ├── l5_writing.py           # outline→section_writers→citation→assemble→consistency→abstract
│       │   └── l6_review.py            # programmatic_checks→llm_review→route→H2→final_package + G6
│       │
│       ├── gates/                      # Gate 评估器（程序化，可独立单测）
│       │   ├── __init__.py
│       │   ├── base.py                 # Gate 协议, GateResult
│       │   ├── g1_understanding.py     # 小问完整、DAG 无环、主类型齐备
│       │   ├── g2_coverage.py          # 缺口覆盖率、S/A 来源数、独立来源数
│       │   ├── g3_decision.py          # Critic 裁决路由
│       │   ├── g4_data.py              # 字段齐备率、缺失率、指标方向配置
│       │   ├── g5_result.py            # 作用域回退路由（数据/模型/代码/验证）
│       │   └── g6_review.py            # 程序审查 + LLM 审查聚合
│       │
│       ├── routing/                    # 集中式路由表
│       │   ├── __init__.py
│       │   ├── revision_router.py      # 数据驱动路由表 + 作用域规则 + 预算判定
│       │   └── route_table.py          # issue.category → 目标节点 + 作用域 + 预算
│       │
│       ├── agents/                     # LLM Agent（prompt + 结构化输出）
│       │   ├── __init__.py
│       │   ├── base.py                 # BaseAgent：LLM 调用、重试、结构化输出校验
│       │   ├── problem_analyst.py      # L0
│       │   ├── research_agent.py       # L1：查询规划、证据提取、研究综合
│       │   ├── modeling_agent.py       # L2：候选生成、评分、Critic
│       │   ├── solver_agent.py         # L4：公式生成、代码生成
│       │   ├── result_analyst.py        # L4：结果分析
│       │   ├── paper_writer.py         # L5：分节写作
│       │   └── reviewer.py             # L6：LLM 审查
│       │
│       ├── research/                   # 研究管线（L1 内部组件）
│       │   ├── __init__.py
│       │   ├── gateway.py              # Provider 选择、超时、重试、限流、备用
│       │   ├── query_planner.py        # 知识缺口→中英文查询组
│       │   ├── source_ranker.py        # 来源评级（确定性评分公式）
│       │   ├── source_deduplicator.py  # URL/标题/DOI/同源去重
│       │   ├── evidence_extractor.py   # 来源→证据项
│       │   └── research_synthesizer.py # 证据→研究综合
│       │
│       ├── providers/                  # 可插拔搜索 Provider
│       │   ├── __init__.py
│       │   ├── base.py                 # SearchProvider Protocol
│       │   ├── web_search.py
│       │   ├── academic_search.py
│       │   └── local_knowledge.py
│       │
│       ├── tools/                      # 确定性计算工具（不依赖 LLM）
│       │   ├── __init__.py
│       │   ├── file_tools.py           # CSV/Excel/JSON/MD 读取
│       │   ├── data_tools.py           # data_inventory、质量报告、预处理
│       │   ├── evaluation_tools.py     # 熵权法、TOPSIS
│       │   ├── regression_tools.py     # 线性回归、多元回归
│       │   ├── optimization_tools.py   # 线性规划
│       │   ├── plotting_tools.py       # 图表生成
│       │   └── validation_tools.py     # 权重扰动、MAE/RMSE/MAPE、约束检查
│       │
│       ├── runtime/                    # 运行时（横切关注点）
│       │   ├── __init__.py
│       │   ├── sandbox.py              # 代码执行沙箱（超时、资源限制）
│       │   ├── code_repair.py          # 失败分类（syntax/data/api/logic）+ 定向修复
│       │   ├── checkpoint.py            # SqliteSaver、run_id、resume
│       │   ├── budget.py               # 预算账本 + 降级策略
│       │   └── logging.py              # 结构化日志（run_id/node/tool/token/latency）
│       │
│       ├── prompts/                    # Prompt 模板
│       │   ├── problem_analysis.md
│       │   ├── task_decomposition.md
│       │   ├── problem_classification.md
│       │   ├── knowledge_gap.md
│       │   ├── query_planner.md
│       │   ├── evidence_extraction.md
│       │   ├── research_synthesis.md
│       │   ├── model_candidate.md
│       │   ├── model_scoring.md
│       │   ├── model_critic.md
│       │   ├── model_formulation.md
│       │   ├── code_generation.md
│       │   ├── code_repair.md
│       │   ├── result_analysis.md
│       │   ├── paper_section_*.md      # 按章节
│       │   ├── abstract.md
│       │   └── reviewer.md
│       │
│       └── utils/
│           ├── __init__.py
│           ├── logger.py
│           ├── retry.py                # 指数退避
│           ├── ids.py                  # run_id / evidence_id 生成
│           ├── json_utils.py
│           └── exceptions.py           # 自定义异常层级
│
├── tests/
│   ├── unit/
│   │   ├── schemas/                    # Schema 校验测试
│   │   ├── gates/                      # Gate 判定测试
│   │   ├── tools/                      # 确定性工具测试（已知答案）
│   │   ├── research/                   # 来源评级、去重测试
│   │   ├── routing/                    # 路由表测试
│   │   └── runtime/                    # sandbox、budget、checkpoint 测试
│   ├── integration/                    # 子图级集成测试（Stub LLM）
│   └── workflow/                       # 端到端工作流测试（FakeProvider）
│
├── examples/
│   ├── evaluation/
│   │   ├── problem.md
│   │   └── data.csv
│   ├── prediction/
│   │   ├── problem.md
│   │   └── data.csv
│   └── optimization/
│       ├── problem.md
│       └── data.csv
│
├── data/
│   ├── input/
│   └── processed/
│
├── artifacts/                          # 运行产物（gitignore）
│   └── <run_id>/
│       ├── checkpoints.db
│       ├── reports/
│       ├── data/
│       ├── code/
│       ├── tables/
│       ├── figures/
│       ├── paper/
│       └── final/
│
├── .env
├── .env.example
├── .gitignore
├── pyproject.toml
├── requirements.txt
├── architecture.md
├── spec.md
├── plan.md
└── README.md
```

## 3. 文件职责速查

| 目录 | 职责 | 依赖方向 |
|---|---|---|
| `schemas/` | 数据契约，无逻辑 | 被所有层依赖 |
| `layers/` | 七层子图编排 | 依赖 schemas/gates/agents/tools/runtime |
| `gates/` | 程序化门控判定 | 依赖 schemas/routing |
| `routing/` | 集中式路由表 | 依赖 schemas |
| `agents/` | LLM 调用 + 结构化输出 | 依赖 schemas/prompts |
| `research/` | 研究管线组件 | 依赖 schemas/providers |
| `providers/` | 搜索供应商适配 | 被 research 依赖 |
| `tools/` | 确定性计算 | 依赖 schemas，被 layers 依赖 |
| `runtime/` | 横切运行时 | 被所有层依赖 |

---

# 第二部分 · 开发顺序

## 总览

| Phase | 名称 | 核心交付 | 对应架构层 |
|---|---|---|---|
| 0 | 仓库基线与运行时 | 可安装、可启动、配置可读 | 横切 |
| 1 | Schema 与 State | 完整数据契约 + 分域状态 | §3 |
| 2 | LangGraph 骨架与 Gate 框架 | 空节点图可跑通 + Gate 协议 | §2 §5 |
| 3 | L0 摄入与理解 | 题目可拆解分类 + data_inventory | L0 + G1 |
| 4 | L1 研究管线 | 规范化搜索 + 证据管线 | L1 + G2 |
| 5 | L2 模型决策 | 候选/过滤/评分/Critic/H1 | L2 + G3 |
| 6 | L3 数据处理 | 数据规划 + 预处理 + 质量门 | L3 + G4 |
| 7 | L4 求解与检验 | 沙箱 + 修复 + 确定性复跑 + 检验 | L4 + G5 |
| 8 | L5 论文写作 | 分节生成 + 引用 + 数值核对 | L5 |
| 9 | L6 审查与交付 | 双层审查 + 作用域路由 + 交付包 | L6 + G6 + H2 |

---

## Phase 0：仓库基线与运行时

### 目标
建立可安装、可运行、可测试的项目骨架与横切运行时。

### 任务
- **0.1** 创建目录结构（§2 全部目录 + `__init__.py`）。
- **0.2** 配置 `pyproject.toml`、`requirements.txt`：
  ```
  langgraph langchain langchain-openai pydantic pydantic-settings
  python-dotenv pandas numpy scipy scikit-learn matplotlib pulp
  httpx tenacity pytest pytest-asyncio
  ```
- **0.3** `config.py`：用 pydantic-settings 读取 `.env`（OPENAI_API_KEY / MODEL_NAME / 搜索配置 / 预算限制 / 日志级别）。
- **0.4** `.env.example` 与 `.gitignore`（排除 `.env`、`.venv`、`artifacts/`）。
- **0.5** `runtime/logging.py`：结构化日志（run_id / node / status / token / latency）。
- **0.6** `runtime/checkpoint.py`：SqliteSaver 封装，run_id 生成，resume 接口。
- **0.7** `runtime/budget.py`：预算账本（search_rounds / code_repairs / paper_revisions / token_used / time_used）+ 降级策略接口。
- **0.8** `main.py`：CLI 入口 `run` / `resume`，最小输出 `Math Modeling Agent initialized.`

### 验收
- `python -m math_modeling_agent.main` 可运行。
- `pytest` 可运行（空测试套件不报错）。
- 配置可从 `.env` 读取。
- 日志输出到控制台。

---

## Phase 1：Schema 与 State

### 目标
固化所有数据契约，开发任何节点前先有 Schema。

### 任务
- **1.1** `schemas/common.py`：NodeStatus、NodeIssue、NodeResult、GateResult、CitationRecord。
- **1.2** `schemas/budget.py`：Budgets、BudgetLimit、BudgetSnapshot。
- **1.3** `schemas/problem.py`：ProblemAnalysis、SubProblem、ProblemClassification、DataInventory、DataField。
- **1.4** `schemas/research.py`：KnowledgeGap、SearchRequest、SearchResult、SourceRecord、EvidenceItem、ResearchSynthesis、ResearchCoverage。
- **1.5** `schemas/model.py`：ModelCandidate、ModelScore、ModelComparison、ModelCriticReport、DecisionRecord。
- **1.6** `schemas/data.py`：DataRequirement、PreprocessingReport、QualityReport。
- **1.7** `schemas/result.py`：ExecutionResult、ResultAnalysis、ValidationReport。
- **1.8** `schemas/paper.py`：PaperSection、ReviewIssue、ReviewReport。
- **1.9** `state.py`：MathModelingState（TypedDict）+ SubProblemRun + 三条铁律注释。

### 测试
- 每个 Schema 正常实例化。
- 缺必填字段报错。
- 枚举值非法报错。
- 分数超 0–1 报错。
- EvidenceItem 缺来源报错。
- ReviewIssue 缺 route_to 报错。

### 验收
- 所有核心对象有 Pydantic Schema。
- State 字段与 architecture.md §3 一致。
- 节点开发时不新增匿名字段。

---

## Phase 2：LangGraph 骨架与 Gate 框架

### 目标
用 Stub 节点跑通完整七层图，建立 Gate 协议与路由框架。

### 任务
- **2.1** `gates/base.py`：Gate 协议（`evaluate(state) -> GateResult`）。
- **2.2** `routing/route_table.py`：数据驱动路由表（issue.category → 目标节点 + 作用域 + 预算），对应 architecture.md §5.2。
- **2.3** `routing/revision_router.py`：作用域回退逻辑（只重置受影响子问题，其他缓存保留）+ 预算判定。
- **2.4** 每层 Stub 节点（`layers/l0_understanding.py` … `l6_review.py`）：仅更新 `current_node` 与 `workflow_status`。
- **2.5** `graph.py`：主图组装——子图串联 + Gate 条件边 + H1/H2 interrupt 占位 + Checkpoint。
- **2.6** Fake State 测试夹具：固定假数据验证节点顺序、State 传递、条件路由、可结束、迭代上限停止。

### 测试
- 空工作流从 START 运行到 END。
- G1–G6 条件路由正确（pass / retry / escalate / human）。
- 预算耗尽 → need_human_review。
- interrupt 可暂停与恢复。
- 图结构与 architecture.md §2 一致。

### 验收
- 骨架可运行，Gate 协议就位，路由表数据化。

---

## Phase 3：L0 摄入与理解

### 目标
让系统准确理解一道数学建模题，并产出结构化子问题与数据画像。

### 任务
- **3.1** `tools/file_tools.py`：CSV / Excel 单工作表 / JSON / Markdown 读取。
- **3.2** `tools/data_tools.py` 的 `data_inventory`：附件确定性画像（行列数、字段类型、缺失率、单位线索、时间维度）→ `reports/data_inventory.json`。
- **3.3** `agents/problem_analyst.py`：understand（背景/目标/约束/关键词，禁止建模）+ decompose（子问题 DAG）+ classify（主类型+次类型）。
- **3.4** `gates/g1_understanding.py`：小问完整、依赖无环、主类型齐备；失败重跑（≤2）→ 人工。
- **3.5** `layers/l0_understanding.py`：串联上述节点 + G1。
- **3.6** Prompt 模板：`problem_analysis.md` / `task_decomposition.md` / `problem_classification.md`。
- **3.7** 测试夹具：`tests/fixtures/problems/` 下评价/预测/优化/综合/歧义题各一道。

### 测试
- 所有显式小问被提取。
- 子问题依赖无环。
- 每个子问题有主类型。
- data_inventory 字段类型与缺失率正确。
- 格式修复失败 2 次后进入人工。

### 验收
- 输入题目 → 输出子问题 + 知识缺口 + 数据画像。

---

## Phase 4：L1 研究管线

### 目标
将知识缺口转化为可审计、可引用的证据。

### 任务
- **4.1** `providers/base.py`：SearchProvider Protocol。
- **4.2** `providers/web_search.py`：首个 Web 搜索 Provider。
- **4.3** `research/gateway.py`：Provider 选择、超时、重试、限流、备用 Provider。
- **4.4** `research/query_planner.py`：高优先缺口 → 中英文查询组（带 purpose + source preference）。
- **4.5** `research/source_ranker.py`：来源分级（S/A/B/C/D）+ 确定性评分公式（architecture.md L1）。
- **4.6** `research/source_deduplicator.py`：URL 规范化、标题相似度、DOI、同源标记。
- **4.7** `research/evidence_extractor.py`：来源 → 证据项（一证据一 claim，必记来源与局限）。
- **4.8** `research/research_synthesizer.py`：证据 → 研究综合（domain_findings / candidate_method_families / data_implications / validation_requirements / open_questions）。
- **4.9** `agents/research_agent.py`：封装 LLM 调用（证据提取、研究综合）。
- **4.10** `gates/g2_coverage.py`：缺口覆盖率、S/A 来源数、独立来源数；未达标且轮次 < 3 → 回 queries。
- **4.11** `layers/l1_research.py`：串联 + Send 并行查询 + G2。
- **4.12** 预算：`MAX_SEARCH_ROUNDS=3`、`MAX_QUERIES_PER_GAP=5`、`MAX_RESULTS_PER_QUERY=8`。

### 测试
- FakeSearchProvider：正常/空结果/超时/429/Provider 异常/备用。
- 重复 URL 去重。
- 无 URL 来源标记。
- 冲突证据不静默删除。
- 查询轮数上限触发降级。
- 中英文查询生成。

### 验收
- 上层不依赖具体搜索 API。
- 搜索结果不直接进入模型推荐。
- 关键定义至少一个 S/A 来源。
- 模型判断至少两个独立来源。

---

## Phase 5：L2 模型决策

### 目标
基于题型、数据画像、证据生成并选定模型，经 Critic 与人工确认。

### 任务
- **5.1** 模型规则库（`agents/modeling_agent.py` 内或独立配置）：evaluation/prediction/optimization 三类候选。
- **5.2** `agents/modeling_agent.py`：候选生成（2–4 个/子问题，含所需数据/假设/输出/验证/证据 ID/优缺点/淘汰条件）。
- **5.3** 硬过滤（确定性）：无所需数据/假设不成立/不能回答/无法检验/规模不现实 → 淘汰，输出原因。
- **5.4** 评分（代码化）：architecture.md L2 公式，LLM 只出单项分与理由，Pydantic 约束 0–1，总分代码计算。
- **5.5** Critic：缺口覆盖、权威来源、候选差异、遗漏简单模型、假设合理性、数据可获得、验证明确、可追溯。
- **5.6** `gates/g3_decision.py`：Critic 裁决 → insufficient_evidence 回 L1 / weak_candidates 重生成 / passed → H1。
- **5.7** H1 人工确认（interrupt）：展示推荐/备用/评分/证据/数据/风险；操作 approve/replace/more_research/cancel；前后 checkpoint。
- **5.8** `layers/l2_model_decision.py`：串联 + G3 + H1。
- **5.9** Prompt：`model_candidate.md` / `model_scoring.md` / `model_critic.md`。

### 测试
- 小样本不选深度学习。
- 无时间列不选 ARIMA。
- 多指标评价优先评价模型。
- 线性目标约束选线性规划。
- 证据不足回 L1。
- Critic 拒绝仅因"先进"的模型。
- 用户替换模型后 State 正确更新。

### 验收
- 每子问题有推荐 + 备用模型。
- 选择理由可追溯 EvidenceItem。
- 评分可复算。
- 未经人工确认不得进入求解。

---

## Phase 6：L3 数据处理

### 目标
将模型要求转为字段级需求，产出可复现的预处理结果。

### 任务
- **6.1** `tools/data_tools.py` 补全：plan_data（字段级需求）+ preprocess（缺失值/异常值/标准化/正向化/类型转换/训练测试集划分）+ quality_report。
- **6.2** `agents/`（可选 LLM 辅助）：数据需求映射。
- **6.3** `gates/g4_data.py`：字段齐备率、缺失率阈值、指标方向配置；失败区分"可预处理修复"（回 preprocess）与"本质不足"（回 L2/人工）。
- **6.4** `layers/l3_data.py`：串联 + G4。
- **6.5** 产物：`reports/data_quality.json` / `reports/preprocessing_report.json` / `data/processed.csv`。

### 测试
- 空文件、编码错误、缺字段、全空列、字符串数字、异常值、正负向指标、数据泄漏、可重复划分。

### 验收
- 原始数据不覆盖。
- 每步预处理有记录。
- 处理可复现。
- 模型所需字段齐备，否则回退。

---

## Phase 7：L4 求解与检验

### 目标
让三类 MVP 模型真实运行，数值可复现、可验证。

### 任务
- **7.1** `tools/evaluation_tools.py`：熵权法（标准化矩阵/信息熵/差异系数/权重）+ TOPSIS（正负理想解/距离/贴近度/排名）。
- **7.2** `tools/regression_tools.py`：线性回归 + 多元回归（系数/截距/训练测试指标/预测值/残差）。
- **7.3** `tools/optimization_tools.py`：线性规划（状态/最优值/变量/约束余量）。
- **7.4** `tools/plotting_tools.py`：排名图、回归图、灵敏度图。
- **7.5** `tools/validation_tools.py`：权重扰动、排名稳定性、MAE/RMSE/MAPE、残差、约束检查、参数扰动。
- **7.6** `runtime/sandbox.py`：代码执行沙箱（超时、资源限制、文件隔离）。
- **7.7** `runtime/code_repair.py`：失败分类（syntax/data/api/logic）→ 定向修复，≤ `MAX_CODE_REPAIR`(3)。
- **7.8** `agents/solver_agent.py`：formulate（假设/符号/公式）+ codegen（可运行代码）。
- **7.9** 确定性复跑：同参重跑，关键数值一致才接受。
- **7.10** `agents/result_analyst.py`：结果解释（主要结果/关键数字/图表引用/影响因素/现实含义/限制/结论），禁止改数值或编造实验。
- **7.11** `gates/g5_result.py`：作用域回退——数据问题→L3（仅该子问题）/ 模型不适配→L2（仅该子问题，其他缓存保留）/ 代码问题→局部修复环 / 通过→fan-in。
- **7.12** `layers/l4_solve.py`：Send fan-out（按子问题并行）+ 内部修复环 + 确定性复跑 + G5。
- **7.13** 产物：`code/` / `tables/` / `figures/` / `reports/execution_results.json`。
- **7.14** Prompt：`model_formulation.md` / `code_generation.md` / `code_repair.md` / `result_analysis.md`。

### 测试
- 熵权法：单一指标/常量列/全零列/正负向/权重和为 1。
- TOPSIS：已知小型样例/并列/非法权重/结果 0–1。
- 回归：一元线性/多重共线性/空值/小样本/固定 random_state。
- 线性规划：唯一最优解/无可行解/无界。
- 沙箱：超时中断/资源限制/文件隔离。
- 修复环：syntax 错误修复成功、logic 错误 3 次后降级。
- 确定性复跑：随机性场景数值一致判定。
- 作用域回退：修 Q2 不影响 Q1 缓存。

### 验收
- Agent 不生成最终数值。
- 三类模型有已知答案测试。
- 相同输入相同结果。
- 论文数值可定位 ExecutionResult。
- 模型异常返回明确错误类型。

---

## Phase 8：L5 论文写作

### 目标
生成结构完整、数值一致、来源可追溯的 Markdown 论文。

### 任务
- **8.1** `agents/paper_writer.py`：分节生成（问题重述→问题分析→模型假设→符号说明→数据预处理→模型建立与求解→结果分析→模型检验→模型评价与推广→参考文献→摘要最后）。
- **8.2** 引用注册：外部事实↔EvidenceItem，数值↔ExecutionResult，模型理由↔DecisionRecord。写作节点只读路径与 ID。
- **8.3** 组装：`paper/paper_draft.md` + `citations.json`。
- **8.4** 数值一致性核对（程序化）：论文关键数值必须能在 execution_results 中找到（正则/表格比对），不一致即失败。
- **8.5** 摘要最后生成：含模型名称与核心结论。
- **8.6** `layers/l5_writing.py`：outline → section_writers（独立章节可并行）→ citation_registry → assemble → consistency_check → abstract。
- **8.7** Prompt：`paper_section_*.md`（按章节）+ `abstract.md`。

### 测试
- 缺图表引用报错。
- 引用不存在报错。
- 结果数字与执行结果不一致报错。
- 小问无对应章节报错。
- 摘要缺模型名称报错。
- 参考文献未被正文引用警告。
- 正文引用不存在于证据库报错。

### 验收
- 所有小问有回答。
- 外部事实可追溯。
- 数值可追溯。
- 图表引用存在。
- 论文不含未执行实验。
- Markdown 可正常渲染。

---

## Phase 9：L6 审查与交付

### 目标
建立程序化审查 + LLM 审查双层检查，形成有界修改闭环，产出完整交付包。

### 任务
- **9.1** 程序化检查器：question_coverage / section_completeness / figure_reference / table_reference / citation_integrity / numeric_consistency / symbol_definition / validation_presence / artifact_existence。全过才调 LLM。
- **9.2** `agents/reviewer.py`：LLM 审查（题意/逻辑/假设/模型选择/证据/结果解释/结论/表达），输出 ReviewIssue（category/location/severity/route_to/suggested_fix）。
- **9.3** `gates/g6_review.py`：聚合程序 + LLM 结果，按 architecture.md §5.2 路由表回退，≤3 轮。
- **9.4** `routing/revision_router.py` 接入：作用域回退 + 预算判定 + critical 优先 + 同类按子问题 ID 排序。
- **9.5** H2 终审（interrupt）：展示审查报告与产物清单；确认后进入交付。
- **9.6** `layers/l6_review.py`：programmatic_checks → llm_review → route → H2 → final_package。
- **9.7** final_package：生成 `final/paper_final.md` + 各 JSON 报告 + `submission_checklist.md` + code/figures/tables。
- **9.8** 迭代上限：`MAX_PAPER_REVISIONS=3`，超限 → need_human_review（保存 checkpoint + 未决问题清单）。
- **9.9** Prompt：`reviewer.md`。

### 测试
- 一个 Issue 对应一个正确节点。
- 多 Issue 优先级排序。
- critical 优先 major。
- Reviewer 不直接修改 State。
- 超迭代上限进入人工。
- 论文修改后重新审查。
- 审查通过后不再回退。
- 交付包文件完整、不含密钥。

### 验收
- 程序化审查与 LLM 审查分离。
- ReviewIssue 有位置/严重度/路由。
- 修改后可重新审查。
- 无无限循环。
- 审查通过是 final_package 的必要条件。
- 三个 MVP 样例可端到端运行。

---

## Sprint 节奏建议

| Sprint | 完成 Phase | 可演示 |
|---|---|---|
| Sprint 1 | 0 + 1 + 2 | Stub 数据跑通七层图，Gate 路由可测 |
| Sprint 2 | 3 + 4 | 输入题目 → 子问题 + 知识缺口 + 搜索证据 |
| Sprint 3 | 5 + 6 | 证据 → 候选模型评分 → 人工确认 → 数据预处理 |
| Sprint 4 | 7 | 输入 CSV → 熵权 TOPSIS / 回归 / 线性规划真实运行 |
| Sprint 5 | 8 + 9 | 结果分析 + 检验 + Markdown 论文 + 审查回退 + 交付包 |

---

## 贯穿全程的原则

1. **Schema 先行**：任何节点开发前，对应 Schema 已定义并测试。
2. **确定性优先**：`tools/` 不依赖 LLM，可单测、可复现；LLM 只做推理与解释。
3. **搜索必经证据管线**：搜索结果不直接传给模型选择 Agent。
4. **每阶段可演示**：前一阶段不可运行时不堆积后续节点。
5. **测试与代码同步**：每个任务含对应测试，验收标准可执行。
6. **Checkpoint 贯穿**：每个 Gate 后、每个 interrupt 前自动保存，可 resume。
