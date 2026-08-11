# MMAgent — 数学建模智能体

> 从读题、数据画像、方法探索、建模计算、结果验证，到报告撰写与全任务审查的全流程自动化智能体系统。

MMAgent 将任务文档与附件数据组织为一个可复现的解题过程：先理解问题与数据，再按小问递进完成模型构建、计算、验证与结果沉淀，最后生成报告草稿、进行审查并交付全部材料。

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+（仅 Web 界面开发/构建需要）
- 推荐使用 [uv](https://docs.astral.sh/uv/) 管理 Python 依赖

### 安装

```bash
# Python 依赖（核心引擎 + 服务层）
uv sync
# 或标准虚拟环境
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -e .

# 前端依赖（仅使用 Web 界面时需要）
cd web && npm install
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

### 三种运行方式

**① 命令行模式** —— 直接运行核心引擎，产物落到 `artifacts/<run_id>/`：

```bash
python -m scr.math_modeling_agent.main run --problem examples/problem.md --data examples/附件1.xlsx examples/附件2.xlsx

# 指定输出目录与日志级别
python -m scr.math_modeling_agent.main run --problem examples/problem.md --data examples/附件1.xlsx --output artifacts/my_run --log-level debug
```

任务参数可直接传入文本或文件路径：`--problem examples/problem.md` 或 `--problem "某工厂生产A、B两种产品..."`。

**② Web 界面模式** —— 启动服务层，浏览器操作（推荐）：

```bash
# 1. 构建前端产物到 web/dist（首次或前端改动后执行）
cd web && npm run build && cd ..

# 2. 启动服务（同时托管前端与 API）
uvicorn server.main:app --port 8000

# 3. 浏览器访问
#    http://localhost:8000
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

## Web 界面与 REST API

### 前端页面

| 页面       | 路由状态    | 功能                                                         |
| ---------- | ----------- | ------------------------------------------------------------ |
| Home       | `home`    | 落地页：能力介绍、工作流展示、入口引导                       |
| NewTask    | `new`     | 新建任务：提交（Submit）→ 进度（Progress）→ 结果（Result） |
| History    | `history` | 历史任务列表，可重新打开查看产物                             |
| ApiManager | `api`     | LLM 提供商 / Key / Base URL / 模型配置管理                   |
| Docs       | `docs`    | 项目文档（即本 README，与仓库同步）                          |

### REST API

| 方法       | 路径                                | 说明                                                                  |
| ---------- | ----------------------------------- | --------------------------------------------------------------------- |
| `POST`   | `/api/runs`                       | 提交解题任务（表单：任务文本/文件 + 附件 + llm_config），后台异步执行 |
| `GET`    | `/api/runs`                       | 运行历史列表                                                          |
| `GET`    | `/api/runs/{run_id}`              | 运行详情（含进度事件与产物清单）                                      |
| `POST`   | `/api/runs/{run_id}/cancel`       | 中断 queued/running 状态的任务                                        |
| `DELETE` | `/api/runs/{run_id}`              | 删除运行记录（DB 行 + 产物目录）                                      |
| `GET`    | `/api/runs/{run_id}/paper`        | 获取报告 Markdown 文本                                                |
| `GET`    | `/api/runs/{run_id}/figures`      | 获取图表文件清单                                                      |
| `GET`    | `/api/runs/{run_id}/files/{path}` | 下载任意产物文件（安全限制在 run 目录内）                             |
| `POST`   | `/api/runs/cleanup-stale`         | 手动清理因重启卡住的僵尸任务                                          |
| `GET`    | `/healthz`                        | 健康检查（前端已构建时可用）                                          |
| `GET`    | `/docs`                           | FastAPI 自动生成的交互式 API 文档                                     |

提交任务示例：

```bash
curl -X POST http://localhost:8000/api/runs \
  -F "problem_text=某工厂生产A、B两种产品..." \
  -F "data_files=@examples/附件1.xlsx" \
  -F 'llm_config={"provider":"deepseek","model":"deepseek-chat"}'
```

---

## 产物结构

每次运行在 `artifacts/<run_id>/` 下保存独立产物：

```text
artifacts/<run_id>/
  run.log                 # JSON 结构化运行日志（节点、步骤、质量门、耗时、错误）
  paper.md                # 报告 Markdown 草稿
  paper.docx              # 报告 DOCX（自动转换）
  review_report.json      # 审查报告
  input/                  # 原始任务与附件拷贝
  context/                # 数据画像报告、inventory JSON
  figures/                # 报告图表 PNG
  questions/<qid>/        # 每小问的建模解题产物（任务驱动建模时生成）
    solution.py           # LLM 生成的完整求解代码
    data.csv              # 传入沙箱执行的输入数据
    result.json           # 执行结果（results + metrics + 方法信息）
```

> `questions/<qid>/` 仅在"任务驱动建模"路径（配置了 LLM 且题型为 optimization / stochastic_optimization / evaluation / prediction / simulation）生成；无 LLM 或回退到预设方法时，该小问不产生代码文件（计算由确定性内置函数完成）。

### 运行日志

每次运行实时输出节点进度（开始/完成/耗时/状态更新），并写入 `run.log`：

- **实时查看**：终端实时显示每个智能体节点与小问的进度；另一终端可用 `Get-Content -Wait artifacts/<run_id>/run.log`（Windows）或 `tail -f`（Linux/macOS）跟随日志。
- **日志级别**：`--log-level debug|info|warning|error` 控制 `run.log` 详细程度（默认 `info`）。
- **日志内容**：每个节点（intake / context / select_question / solve_question / validate_result / 各质量门）的开始、完成、耗时与失败；每个小问的解题步骤（问题澄清、方法探索、建模计算、可复用摘要）；G0/GQ/GF 质量门动作与失败项。

---

## 项目结构

```text
MMAgent/
├── scr/math_modeling_agent/     # 核心引擎（命名空间包，LangGraph 状态图）
│   ├── main.py                  #   CLI 入口（run / init）
│   ├── graph.py                 #   LangGraph 主图构建
│   ├── state.py                 #   项目状态三区 partition
│   ├── config.py                #   配置管理
│   ├── llm.py                   #   LLM 抽象与三级结构化输出回退
│   ├── agents/                  #   结构化推理模块（9 个 Agent）
│   │   ├── base.py              #     Agent 基类（LLM 管理、prompt 渲染）
│   │   ├── problem_analyst.py   #     任务理解与小问拆分
│   │   ├── method_explorer.py   #     联网搜索 + LLM 方法探索与决策
│   │   ├── model_builder.py     #     建模计算与可视化
│   │   ├── question_solver.py   #     小问求解闭环
│   │   ├── result_validator.py  #     题型验证
│   │   ├── paper_writer.py      #     报告撰写
│   │   ├── reviewer.py          #     全任务审查
│   │   ├── research_agent.py    #     证据检索
│   │   └── modeling_agent.py    #     模型评分与批评
│   ├── gates/                   #   质量门（G0 输入 / GQ 小问 / GF 交付）
│   ├── schemas/                 #   Pydantic 数据契约
│   ├── tools/                   #   确定性工具（文件读取/搜索/可视化/表格/转 DOCX）
│   ├── prompts/                 #   LLM 提示词模板
│   ├── templates/               #   报告模板
│   ├── workflow/                #   工作流节点
│   └── runtime/                 #   运行时（检查点、日志、产物、预算）
│
├── server/                      # 服务层（FastAPI 常规包）
│   ├── main.py                  #   FastAPI 入口 + 路由 + 前端静态托管
│   ├── runs.py                  #   运行管理（create/get/list/cancel/delete/execute）
│   ├── files.py                 #   产物文件解析（图表清单、安全路径解析）
│   ├── schemas.py               #   API 响应模型（RunSummary/RunDetail/ModelConfig）
│   └── runs.db                  #   SQLite 运行记录数据库
│
├── web/                         # 前端（React + Vite + TypeScript）
│   ├── src/
│   │   ├── App.tsx              #   根组件，状态路由
│   │   ├── main.tsx             #   React 入口
│   │   ├── api.ts               #   后端 API 客户端
│   │   ├── apiConfigs.ts        #   LLM 配置管理
│   │   ├── pages/               #   Home / NewTask / History / ApiManager / Docs
│   │   │                         #   NewTask 内含 Submit / Progress / Result 子视图
│   │   ├── components/          #   Sidebar 等通用组件
│   │   ├── index.css            #   全局主题（淡蓝科技风）
│   │   └── forms.css            #   表单与功能页样式
│   ├── index.html
│   └── package.json
│
├── tests/                       # 单元测试
├── examples/                    # 任务与附件样例
├── artifacts/                   # 运行产物输出目录（按 run_id 隔离）
├── pyproject.toml               # Python 项目配置（v1.1.0）
├── architecture.md              # 目标架构说明
├── plan.md                      # 实施计划与验收标准
└── LICENSE
```

---

## 技术栈

**核心引擎**

- **LangGraph** — `StateGraph` 主编排图，条件边实现质量门路由、小问循环与回退重试；`MemorySaver` 检查点支持断点恢复。
- **LangChain + langchain-openai** — 统一 LLM 抽象层，支持 OpenAI 与 DeepSeek 等 OpenAI 兼容接口。
- **Pydantic / pydantic-settings** — 全部状态、配置与 LLM 输出的数据契约，端到端类型安全与自动校验。
- **NumPy / SciPy / scikit-learn** — 回归预测、聚类分类、统计检验等数值计算。
- **PuLP** — 线性规划与整数规划求解。
- **Matplotlib** — 图表生成（数据分布、拟合残差、方案比较、敏感性分析）。
- **Pandas + openpyxl** — 多格式文件读取与数据画像，Excel 自动遍历全部 Sheet。
- **scipy.io + h5py** — MATLAB `.mat` 读取（v4/v6/v7 与 v7.3 HDF5）。
- **Tavily Search API** — 方法探索阶段中英文双语联网搜索。
- **tenacity** — API 调用重试与容错；**python-docx** — 报告 Markdown 到 DOCX 转换；**python-dotenv** — 环境变量管理。

**服务层**

- **FastAPI + Uvicorn** — 异步 Web 服务，后台线程执行同步 LangGraph 图，进度回调写回 SQLite。
- **SQLite** — 轻量运行记录存储（`runs.db`），无需额外数据库配置。

**前端**

- **React 18 + Vite 5 + TypeScript 5** — 单页应用，状态路由，构建产物由服务层静态托管。
- **marked** — 项目文档（README）Markdown 渲染。
