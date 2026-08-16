# MMAgent — 数学建模智能体

> 从理解任务、数据画像、方法探索、建模计算、结果验证，到报告撰写的全流程自动化智能体系统。

## 智能体功能

MMAgent 由 9 个结构化推理 Agent 协同工作，覆盖数学建模全流程：

| Agent                     | 职责       | 关键能力                                            |
| ------------------------- | ---------- | --------------------------------------------------- |
| **ProblemAnalyst**  | 任务理解   | 读题、拆分子问题、题型分类（优化/评价/预测/仿真等） |
| **MethodExplorer**  | 方法探索   | 联网检索文献、LLM 方法决策、生成备选方案与理由      |
| **ModelBuilder**    | 建模计算   | 公式构建、数值求解、参数估计、结果可视化            |
| **CodeModeler**     | 代码建模   | LLM 生成求解代码、沙箱执行、提取结构化结果          |
| **QuestionSolver**  | 小问求解   | 编排方法→建模→计算→摘要的完整闭环                |
| **ResultValidator** | 结果验证   | 量纲校验、边界检查、合理性判断、独立复算            |
| **PaperWriter**     | 报告撰写   | 汇总各小问结果、生成 Markdown 报告、自动转 DOCX     |
| **Reviewer**        | 全任务审查 | 逻辑一致性、完整性、方法合理性审查                  |
| **ResearchAgent**   | 证据检索   | 文献溯源、方法依据查找                              |

三道质量门（G0 输入 / GQ 小问 / GF 交付）在关键节点拦截低质量输出，GQ 支持自动重试。

## 项目结构

```text
MMAgent/
├── scr/math_modeling_agent/     # 核心引擎（命名空间包，LangGraph 状态图驱动）
│   ├── main.py                  #   CLI 入口（run / init 子命令）
│   ├── graph.py                 #   LangGraph 主图构建与节点编排
│   ├── state.py                 #   全局状态（三区 partition：任务 / 小问 / 产物）
│   ├── config.py                #   配置加载与环境变量管理
│   ├── llm.py                   #   LLM 抽象层（三级结构化输出回退机制）
│   ├── agents/                  #   结构化推理模块（9 个 Agent）
│   │   ├── base.py              #     Agent 基类（LLM 调用、prompt 渲染、JSON 解析）
│   │   ├── problem_analyst.py   #     任务理解：读题 → 拆分子问题 → 题型分类
│   │   ├── method_explorer.py   #     方法探索：联网检索 + LLM 方法决策与备选
│   │   ├── model_builder.py     #     建模计算：公式构建、数值求解、可视化
│   │   ├── code_modeler.py      #     代码建模：LLM 生成求解代码并沙箱执行
│   │   ├── question_solver.py   #     小问求解闭环（方法 → 建模 → 计算 → 摘要）
│   │   ├── result_validator.py  #     结果验证（量纲、边界、合理性、复算）
│   │   ├── paper_writer.py      #     报告撰写（汇总各小问结果生成 Markdown）
│   │   ├── reviewer.py          #     全任务审查（逻辑、完整性、一致性）
│   │   ├── research_agent.py    #     证据检索（文献 / 方法溯源）
│   │   └── modeling_agent.py    #     模型评分与批评
│   ├── gates/                   #   质量门（三道关卡保障输出质量）
│   │   ├── g0_intake.py         #     G0：输入校验（任务可读性、附件完整性）
│   │   ├── gq_question.py       #     GQ：小问质量门（方法 / 建模 / 结果）
│   │   └── gf_delivery.py       #     GF：交付质量门（报告、图表、产物齐全）
│   ├── schemas/                 #   Pydantic 数据契约（Agent 输入输出强类型）
│   ├── tools/                   #   确定性工具（无 LLM，可复现）
│   │   ├── file_tools.py        #     文件读取（CSV / Excel / JSON / .mat）
│   │   ├── llm_response.py      #     LLM 响应解析（剥离思维链、提取 JSON/代码）
│   │   ├── tavily_search.py     #     联网搜索封装
│   │   ├── visualization.py     #     图表生成（Matplotlib）
│   │   └── docx_converter.py    #     Markdown → DOCX 转换
│   ├── prompts/                 #   LLM 提示词模板（Markdown 格式，与代码分离）
│   ├── templates/               #   报告模板（LaTeX / DOCX 样式）
│   ├── workflow/                #   工作流节点（LangGraph 节点实现）
│   │   ├── intake.py            #     任务接入与文件校验
│   │   ├── project_context.py   #     数据画像与全局上下文构建
│   │   └── question_loop.py     #     小问循环调度（逐题求解 + 质量门）
│   └── runtime/                 #   运行时基础设施
│       ├── checkpoint.py        #     LangGraph 检查点（断点续跑）
│       ├── logger.py            #     结构化 JSON 日志
│       ├── artifacts.py         #     产物目录管理与文件写入
│       └── budget.py            #     调用预算控制（搜索次数 / LLM 调用）
│
├── server/                      # 服务层（FastAPI 常规包）
│   ├── main.py                  #   FastAPI 应用入口 + 路由注册 + 前端静态托管
│   ├── runs.py                  #   运行管理（create / get / list / cancel / delete / execute）
│   ├── files.py                 #   产物文件服务（图表清单、安全路径解析）
│   ├── schemas.py               #   API 响应模型（RunSummary / RunDetail / ModelConfig）
│   └── runs.db                  #   SQLite 运行记录数据库（自动创建）
│
├── web/                         # 前端（React 18 + Vite 5 + TypeScript 5）
│   ├── src/
│   │   ├── App.tsx              #     根组件与路由状态管理
│   │   ├── main.tsx             #     React 入口
│   │   ├── api.ts               #     后端 API 调用封装
│   │   ├── apiConfigs.ts        #     LLM 配置管理（浏览器本地存储）
│   │   ├── pages/               #     页面组件
│   │   │   ├── Home.tsx         #       落地页（能力介绍 + 工作流展示）
│   │   │   ├── NewTask.tsx      #       新建任务（Submit → Progress → Result）
│   │   │   ├── History.tsx      #       历史任务列表
│   │   │   ├── ApiManager.tsx   #       LLM 提供商 / Key / 模型配置
│   │   │   └── Docs.tsx         #       项目文档（内嵌 README）
│   │   ├── components/          #     通用组件（Sidebar 等）
│   │   ├── index.css            #     全局主题（淡蓝科技风）
│   │   └── forms.css            #     表单与功能页样式
│   ├── index.html
│   └── package.json
│
├── tests/                       # pytest 测试（mock LLM 与网络，无需 API Key）
├── examples/                    # 示例任务与附件（problem.md + 数据文件）
├── artifacts/                   # 运行产物目录（按 run_id 隔离，自动创建）
├── pyproject.toml               # Python 项目配置与依赖声明
├── architecture.md              # 架构设计文档（详细设计说明）
└── AGENTS.md                    # 仓库协作规范（编码风格 / 测试 / 安全）
```

### 核心引擎工作流

核心引擎基于 **LangGraph StateGraph** 构建，主流程如下：

```
任务接入 (intake)
    ↓ G0 输入质量门
数据画像 (project_context) — 分析附件、生成数据画像报告
    ↓
小问循环 (question_loop) — 逐题处理
    ├─ 选择当前小问
    ├─ 任务理解 (problem_analyst) — 拆分子问题、判定题型
    ├─ 方法探索 (method_explorer) — 联网检索 + LLM 方法决策
    ├─ 建模计算 (model_builder / code_modeler) — 公式/代码求解 + 可视化
    ├─ 结果验证 (result_validator) — 量纲、边界、合理性校验
    └─ GQ 小问质量门 — 不通过则重试（最多 3 次）
    ↓
报告撰写 (paper_writer) — 汇总结果生成 Markdown → DOCX
    ↓
全任务审查 (reviewer) — 逻辑 / 完整性 / 一致性审查
    ↓ GF 交付质量门
产物交付 (artifacts)
```

### 设计要点

- **状态分区**：全局状态分为任务区、小问区、产物区，各 Agent 只读写自己负责的分区，避免状态污染。
- **三级 LLM 回退**：结构化输出优先使用 `response_format`，不支持时降级为 JSON prompt + 手动解析，最后降级为正则提取，保证兼容性。
- **确定性与 LLM 分离**：文件读取、数值计算、图表生成等可复现逻辑放在 `tools/`，LLM 仅负责推理与决策。
- **质量门拦截**：G0 / GQ / GF 三道质量门在关键节点拦截低质量输出，GQ 支持自动重试。
- **产物可复现**：每次运行独立目录，包含原始输入、中间上下文、求解代码、执行结果与最终报告，全程可追溯。

## 快速开始

#### 环境要求

- Python 3.11+
- Node.js 18+
- 推荐使用 [uv](https://docs.astral.sh/uv/) 管理 Python 依赖

#### 安装

```
bash
# Python 依赖
uv sync

# 或标准虚拟环境
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -e .

# 前端依赖
cd web && npm install
```

#### 配置 LLM

在项目根目录创建 `.env` 文件：

```
#只支持 OpenAI 兼容格式 的大模型 API

LLM_PROVIDER=custom
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-model-name

# Tavily API Key（联网搜索用，可选）
TAVILY_API_KEY=your_tavily_api_key_here
```

### Agent运行方式

**① 命令行模式** —— 直接运行核心引擎，产物落到 `artifacts/<run_id>/`：

```bash
python -m scr.math_modeling_agent.main run --problem examples/ --data examples/

# 指定输出目录与日志级别
python -m scr.math_modeling_agent.main run --problem examples/ --data examples/ --output artifacts/my_run --log-level debug
```

任务参数可直接传入文本或文件路径：`--problem examples/problem.md` 或 `--problem "某工厂生产A、B两种产品..."`。

**② Web 界面模式(用户使用)** —— 启动服务层，浏览器操作：

```bash
# 1. 构建前端产物到 web/dist（首次）
cd web && npm run build && cd ..

# 2. 启动服务（同时托管前端与 API）
uvicorn server.main:app --port 8000

# 3. 浏览器访问
http://localhost:8000
```

服务启动后自动清理上次未完成的"僵尸"任务，前端产物由根路径静态托管。

**③ 开发模式** —— 前后端分离，支持热更新：

```bash
# 终端一：后端（热重载）
uvicorn server.main:app --reload --port 8000

# 终端二：前端（Vite 热更新）
cd web && npm run dev
# 访问 Vite 提示的地址（默认 http://localhost:5173）
```

> 服务层已开启 CORS（`allow_origins=["*"]`，本地开发用），前端 dev server 可直接调用 `localhost:8000` 的 API。生产部署应将 CORS 收敛为前端域名。

---

## 产物结构

每次运行在 `artifacts/<run_id>/` 下保存独立产物：

```text
artifacts/<run_id>/
  run.log                 # JSON 结构化运行日志（节点、步骤、质量门、耗时、错误）
  paper.md                # 报告 Markdown 
  paper.docx              # 报告 DOCX（自动转换）
  review_report.json      # 审查报告
  input/                  # 原始任务与附件拷贝
  context/                # 数据画像报告
  figures/                # 图片
  questions/<qid>/        # 每小问的建模解题产物
    solution.py           # 生成的完整求解代码
    data.csv              # 传入沙箱执行的输入数据
    result.json           # 执行结果
```

## 运行日志

每次运行实时输出节点进度（开始/完成/耗时/状态更新），并写入 `run.log`：

- **实时查看**：终端实时显示每个智能体节点与小问的进度；另一终端可用 `Get-Content -Wait artifacts/<run_id>/run.log`（Windows）或 `tail -f`（Linux/macOS）跟随日志。
- **日志级别**：`--log-level debug|info|warning|error` 控制 `run.log` 详细程度（默认 `info`）。
- **日志内容**：每个节点（intake / context / select_question / solve_question）的开始、完成、耗时与失败；每个小问的解题步骤；G0/GQ/GF 质量门动作与失败项。

---
