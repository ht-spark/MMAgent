# MMAgent — 数学建模竞赛智能体

面向数学建模竞赛的端到端智能体系统。MMAgent 将题目文档与附件数据组织为一个可复现的解题过程：先理解问题和数据，再按小问递进完成模型构建、计算、验证与结果沉淀，最后生成论文草稿、进行审查并交付全部材料。

---

## 智能体功能

### 全流程自动化

MMAgent 覆盖从读题到交卷的完整竞赛流程，无需人工介入即可完成以下环节：

- **多格式文件读取**：支持 CSV、Excel（自动遍历全部 Sheet）、MATLAB `.mat`（v4/v6/v7/v7.3）、JSON、Markdown，对每张表生成字段定义、描述统计、缺失率和异常报告。
- **题目理解与小问拆分**：提取研究对象、背景机制、显式与隐式约束，自动拆分小问并建立依赖关系图和题目-数据映射表。
- **数据画像与质量检查**：对全部附件生成确定性画像（行列数、字段类型、缺失率、时间维度、单位线索），画像结果直接约束后续方法选择。
- **方法探索与决策**：通过联网搜索（Tavily）和大模型推理（LLM）动态生成候选方法，不依赖预设方法目录；再用启发式评分和数据硬过滤完成方法选择。
- **建模与计算**：根据选中方法构建数学模型表述（决策变量、目标函数、约束条件），调用确定性工具（NumPy/SciPy/scikit-learn/PuLP）执行计算，生成结果表格和图表。
- **结果验证**：按题型自动组合验证项——评价类检查权重敏感性和排名稳定性，预测类检查残差和误差指标，优化类检查约束可行性和目标值，仿真类检查种子可复现性和样本量敏感性。
- **论文写作**：从已验证的小问结果包生成完整竞赛论文草稿（Markdown），包含摘要、问题重述、模型假设、符号说明、各小问的模型建立与求解、模型评价和参考文献，并自动转换为 DOCX。
- **全题审查与交付**：完成所有小问后进行一致性审查（逻辑连贯性、数据口径一致、数值可追溯），通过格式与内容审查后交付最终产物包。

### 核心智能体模块

| 模块            | 职责                                        | 核心输出                          |
| --------------- | ------------------------------------------- | --------------------------------- |
| ProblemAnalyst  | 题目理解、背景提取、小问拆分                | `ProjectContext`                |
| MethodExplorer  | 联网搜索+LLM 生成候选方法、硬过滤、评分决策 | 候选列表 +`decision_record`     |
| ModelBuilder    | 构建数学模型表述、执行确定性计算、生成图表  | `formulation` + `computation` |
| ResultValidator | 按题型执行数值与逻辑验证                    | `validation` 报告               |
| QuestionSolver  | 串联理解→选法→建模→验证的小问闭环        | `QuestionResult`                |
| PaperWriter     | 基于已验证结果包组织论文                    | `PaperDraft`                    |
| Reviewer        | 全题一致性审查与格式审查                    | `ReviewReport`                  |

---

## 主要技术

### 工作流编排

- **LangGraph**：使用 `StateGraph` 构建主编排图，通过条件边实现质量门路由、小问循环和回退重试。支持 `MemorySaver` 检查点，可从断点恢复。

### 大模型集成

- **LangChain + langchain-openai**：统一的 LLM 抽象层，支持 OpenAI 和 DeepSeek 等 OpenAI 兼容接口。
- **三级结构化输出回退策略**：`with_structured_output(schema)` → `with_structured_output(schema, method='json_mode')` → JSON prompt + 手动解析。兼容 DeepSeek 等仅支持 `json_object` 响应格式的模型，并缓存 `_json_schema_unsupported` 标志避免重复失败。
- **Pydantic 数据契约**：全部状态、配置和 LLM 输出使用 Pydantic 模型定义，实现端到端类型安全和自动校验。

### 联网搜索

- **Tavily Search API**：方法探索阶段通过中英文双语查询联网搜索候选方法，搜索结果由 LLM 提取为结构化方法候选（`WebMethodCandidate`），包含方法名称、家族、优缺点、假设、所需数据、实现难度、产出要求和验证要求。

### 确定性计算

- **NumPy / SciPy / scikit-learn**：回归预测、聚类分类、统计检验等数值计算。
- **PuLP**：线性规划与整数规划求解。
- **Matplotlib**：图表生成，服务于数据分布展示、拟合残差、方案比较和敏感性分析。

### 数据处理

- **Pandas + openpyxl**：多格式文件读取与数据画像，Excel 自动遍历全部 Sheet。
- **scipy.io + h5py**：MATLAB `.mat` 文件读取，支持 v4/v6/v7 和 v7.3（HDF5）格式。

### 工程化

- **python-dotenv**：环境变量管理，支持灵活切换 LLM 后端。
- **tenacity**：API 调用重试与容错。
- **python-docx**：论文 Markdown 到 DOCX 的自动转换。

---

## 工作流编排

系统由 LangGraph 主图驱动，分为三个阶段：

```text
START → intake → context → G0 质量门
  G0 pass → select_question ──────────────────────────────────────+
    has_next → assemble_context → solve_question → validate_result → GQ 质量门    │
      pass → archive_result → select_question (循环下一问)                          │
      retry → solve_question (重试当前问)                                           │
      blocked → archive_result → select_question (跳过阻塞问)                       │
    done → global_review → write_paper → review_paper → GF 交付门 ────────────────+
      deliver → END
      revise → write_paper (修订重写)
  G0 retry → g0_retry → intake (重跑输入摄入)
  G0 human → END (请求人工介入)
```

### 阶段一：输入理解与全局规划

读取题目文档和全部附件，生成数据画像，提取小问列表和依赖关系。通过 `G0` 质量门检查：小问是否完整提取、附件是否全部读取、依赖关系是否无环、关键数据缺口是否已记录。

### 阶段二：逐问求解闭环

按依赖顺序逐问处理。每问执行：上下文装配（选择性继承前问结论）→ 问题澄清（确定数学任务类型）→ 方法探索（联网搜索+LLM 生成候选）→ 方法决策（硬过滤+启发式评分）→ 建模计算 → 结果验证 → `GQ` 质量门。

后问只接收前问的 `reusable_summary`（已验证结论、可复用数据集、模型接口、关键参数、限制和改进方向），不接收完整推理记录，避免错误传播。

### 阶段三：全题审查与交付

所有小问完成后，进行全题一致性审查（逻辑连贯性、数据口径一致、数值可追溯），然后生成论文草稿，经格式与内容审查通过后交付。`GF` 门未通过时自动修订重写，通过后交付最终产物包。

### 质量门体系

| 质量门     | 检查内容                                           | 失败处理                   |
| ---------- | -------------------------------------------------- | -------------------------- |
| G0（输入） | 小问完整、附件已读、依赖无环、数据缺口已记录       | 重跑输入摄入或请求人工介入 |
| GQ（小问） | 回答题目要求、计算可复现、验证已完成、结论已记录   | 局部回退重试或标记 blocked |
| GF（交付） | 题目覆盖完整、图文表公式齐备、引用可追溯、格式合规 | 自动修订重写               |

---

## 亮点

### 方法探索不预设目录

方法候选完全由联网搜索和大模型思考生成，不依赖预设方法目录或注册表。这使方法选择不再受限于预定义清单，能够根据题目特点灵活匹配最合适的方法。无网络时降级为按任务类型的通用候选，确保工作流不中断。

### 数据约束方法选择

数据画像直接参与方法硬过滤：无时间维度时淘汰时间序列方法，样本量不足时淘汰高参数模型，只有排序指标时不允许宣称因果关系。方法选择不是"选最先进的"，而是"选数据能支撑的"。

### LLM 推理与确定性计算分离

LLM 负责推理、方案和解释，最终数值、图表和表格由确定性代码生成。每张图、每个表、每个关键数字均可追溯到对应代码和数据版本。随机模型固定种子并记录重复次数。

### 三级结构化输出回退

针对不同 LLM 后端对结构化输出的支持差异，实现了三级回退策略：`json_schema` → `json_mode` → JSON prompt 手动解析。首次失败后缓存标志，后续直接跳过不支持的格式，避免重复报错。

### 选择性继承机制

小问间通过 `reusable_summary` 传递信息，只保留后问确实需要的结论、数据、模型接口和限制。前问的中间推理、失败尝试和冗长原始文本不传入，既保持上下文聚焦，又避免错误传播。

### 预算与降级

对联网检索次数、方法候选数量、代码修复次数、验证迭代次数、时间和令牌设有预算。预算紧张时按优先级降级：减少低价值候选 → 优先简单基线 → 减少非关键图表 → 保留必要验证，但不得跳过数据质量检查、数值复现和题目覆盖检查。

---

## 使用方法

### 环境要求

- Python 3.11+
- 推荐使用 [uv](https://docs.astral.sh/uv/) 管理依赖

### 安装

```bash
# 使用 uv
uv sync

# 或使用标准虚拟环境
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -e .
```

### 配置 LLM

在项目根目录创建 `.env` 文件：

```ini
# OpenAI
OPENAI_API_KEY=your-api-key
MODEL_NAME=gpt-4o
OPENAI_BASE_URL=

# 或 DeepSeek（兼容 OpenAI 接口）
DEEPSEEK_API_KEY=your-api-key
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# 联网搜索（方法探索用，可选）
TAVILY_API_KEY=your-tavily-key
```

未配置 LLM 时可使用 `--no-llm` 运行确定性演示路径，但会使用占位分析，不能代表真实解题效果。

### 运行

```bash
# 基本运行（需配置 .env）
python -m scr.math_modeling_agent.main run --problem examples/problem.md --data examples/附件1.xlsx examples/附件2.xlsx

# 无 LLM 模式（确定性测试）
python -m scr.math_modeling_agent.main run --problem examples/problem.md --data examples/附件1.xlsx examples/附件2.xlsx --no-llm

# 指定输出目录
python -m scr.math_modeling_agent.main run --problem examples/problem.md --data examples/附件1.xlsx --output artifacts/my_run
```

题目参数可直接传入文本或文件路径：

```bash
# 文件路径
--problem examples/problem.md

# 直接传文本
--problem "某工厂生产A、B两种产品..."
```

### 运行测试

```bash
uv run pytest

# 或
python -m pytest tests/ -q
```

### 运行日志

每次运行实时输出节点进度（开始/完成/耗时/状态更新），并写入结构化日志：

```text
artifacts/<run_id>/
  run.log                 # JSON 结构化运行日志（节点、步骤、质量门、耗时、错误）
```

- **实时查看状态**：终端实时显示每个智能体节点与小问的进度；另一个终端可用
  `Get-Content -Wait artifacts/<run_id>/run.log` 实时跟随日志文件。
- **日志级别**：`--log-level debug|info|warning|error` 控制 run.log 的详细程度（默认 `info`）。
- **日志内容**：每个节点（intake/context/select_question/solve_question/validate_result/各质量门等）的开始、完成、耗时与失败；每个小问的解题步骤（问题澄清、方法探索、建模计算、可复用摘要）；G0/GQ/GF 质量门动作与失败项。

```bash
# 以 debug 级别记录详细日志
python -m scr.math_modeling_agent.main run --problem examples/problem.md \
  --data examples/附件1.xlsx --output artifacts/my_run --no-llm --log-level debug
```

### 产物结构

每次运行在 `artifacts/<run_id>/` 下保存独立产物：

```text
artifacts/<run_id>/
  run.log                 # JSON 结构化运行日志（节点、步骤、质量门、耗时、错误）
  paper.md                # 论文 Markdown 草稿
  paper.docx              # 论文 DOCX（自动转换）
  review_report.json      # 审查报告
  input/                  # 原始题目与附件拷贝
  context/                # 数据画像报告、inventory JSON
  figures/                # 论文图表 PNG
  questions/<qid>/        # 每小问的建模解题产物（题目驱动建模时生成）
    solution.py           # LLM 生成的完整求解代码
    data.csv              # 传入沙箱执行的输入数据
    result.json           # 执行结果（results + metrics + 方法信息）
```

> 说明：`questions/<qid>/` 仅在"题目驱动建模"路径（配置了 LLM 且题型为
> optimization / stochastic_optimization / evaluation / prediction / simulation）
> 生成；无 LLM 或回退到预设方法时，该小问不产生代码文件（计算由确定性内置函数完成）。

---

## 项目结构

```text
scr/
  math_modeling_agent/     # 命令行入口、LangGraph 图编排、状态管理
    main.py                # CLI 入口（run / init）
    graph.py               # LangGraph 主图构建
    state.py               # 项目状态分区定义
    config.py              # 配置管理
  agents/                  # 结构化推理模块
    base.py                # Agent 基类（LLM 管理、prompt 渲染）
    problem_analyst.py     # 题目理解与小问拆分
    method_explorer.py     # 联网搜索+LLM 方法探索与决策
    model_builder.py       # 建模计算与可视化
    question_solver.py     # 小问求解闭环
    result_validator.py    # 题型验证
    paper_writer.py        # 论文写作
    reviewer.py            # 全题审查
    research_agent.py      # 证据检索
    modeling_agent.py      # 模型评分与批评
  gates/                   # 质量门
    g0_intake.py           # 输入质量门
    gq_question.py         # 小问结果质量门
    gf_delivery.py         # 交付质量门
  schemas/                 # Pydantic 数据契约
    context.py             # 项目上下文与数据画像
    question.py            # 小问上下文与结果包
    formulation.py         # 模型表述 IR
    paper.py               # 论文与审查报告
    evidence.py            # 证据库与决策日志
  tools/                   # 确定性工具
    file_tools.py          # 多格式文件读取（CSV/Excel/MAT/JSON/MD）
    tavily_search.py       # Tavily 联网搜索
    visualization_tools.py # 图表生成
    table_tools.py         # 表格与 LaTeX 公式
    md2docx.py             # Markdown 转 DOCX
  prompts/                 # LLM 提示词模板
  templates/               # 论文模板
  workflow/                # 工作流节点
  runtime/                 # 运行时（检查点、日志、产物、预算）
tests/                     # 单元测试
examples/                  # 题目与附件样例
architecture.md            # 目标架构说明
plan.md                    # 实施计划与验收标准
```

## 文档

- [architecture.md](architecture.md)：逐问闭环的目标架构、状态分区、质量门、模块职责与交付规范。
- [plan.md](plan.md)：MVP 范围、阶段任务、测试与验收标准。
- [LICENSE](LICENSE)：许可证信息。
