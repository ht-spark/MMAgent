# MMAgent(Math Modeling Agent Platform)

> 数学建模智能体平台 — 全流程自动化建模 + RAG 知识库头脑风暴

MMAgent 是一个面向**数学建模任务**的**智能体平台**。平台由两大核心功能模块构成：

| 模块           | 目录               | 角色                                   | 何时调用                         |
| -------------- | ------------------ | -------------------------------------- | -------------------------------- |
| 数学建模智能体 | `scr/`           | 端到端任务求解引擎（从题目到建模报告） | 用户提交建模任务                 |
| 本地知识库 RAG | `KnowledgeBase/` | 检索增强的"头脑风暴/灵感讨论"助手      | 用户在知识库中进行问答、形成思路 |

二者通过 `server/` 中的 FastAPI 服务层与 `web/` 前端集成，共享同一套 LLM 配置与文件存储基础设施。

---

## 1. 功能介绍

### 1.1 功能一：建模任务（智能体求解）

提交一道数学建模题，系统自动产出完整建模报告。产出报告可以再审查后上传知识库，形成可复用的经验。

**你能做什么：**

- 提交一道数学建模题（直接粘贴文本，或上传 `.md`/`.txt` 题目文件）。
- 附加数据文件（CSV/Excel/图片等，可多个）。
- 选择/配置大模型（OpenAI、DeepSeek 或自定义 OpenAI 兼容 endpoint）。
- 在运行中**人工介入**：回答澄清、调整每问预算、取消任务。
- 获取**完整产物**：建模报告（Markdown）、图表、表格、中间代码与数据，以及审查报告。

**端到端流程：**

```
提交题目+数据 → Phase1 数据画像+问题拆解 → 题目是否清晰?
  ├─ 否,需澄清 → 你补充材料/终止
  └─ 是 → 逐问求解 → 自动选型(联网搜索+LLM) → 生成求解代码并沙箱执行
       → 结果验证 → (不通过且可重试 → 重执行)
       → 全问题完成 → 撰写报告 → 自动审查 → (需修订 → 重写)
       → 通过/强制交付 → 最终报告
```

**关键能力亮点：**

- **自动方法探索**：联网检索相关建模方法 + LLM 思考双路径，避免"拍脑袋选型"；如果启动了头脑风暴功能，构建了知识库，则可选择加载讨论中思路。
- **代码化求解**：LLM 生成 Python 求解代码并在隔离子进程执行，结果可复现。
- **可追溯报告**：报告章节与证据、决策日志、各问结论一一对应，便于人工复核。

**产物清单：**

- `input/`：题目与数据原件
- `questions/`：各子问题的中间产物（代码、数据 CSV、表格 JSON）
- `figures/`：输出的图片
- `paper/`：报告（`paper.md`、`paper.docx`）
- `review_report.json`：审查报告
- `run.log`：运行日志

### 1.2 功能二：基于 RAG 知识库的头脑风暴

构建本地知识库，与"读过这些资料的 LLM"对话，帮助梳理建模思路或者直接形成可用的针对问题的模型，形成的最终思路或模型可以直接加载到建模智能体。

**你能做什么：**

- 上传参考资料（PDF/DOC/DOCX/PPT/PPTX/PNG/JPG/Markdown/TXT，或含上述文件的 ZIP）。
- 将非 Markdown 文档经 **MinerU** 转换为 Markdown（公式、表格可识别）。
- 一键**分块 + 向量化**，建立本地检索索引。
- 在"头脑风暴"对话中与加载了知识库知识的 LLM 提问，获得**带引用出处**的回答，辅助形成建模思路。

**使用流程：**

```
上传文档/ZIP → 归档到 raw → {是 Markdown?}
  ├─ 否 → MinerU 转 Markdown → documents/*.md
  └─ 是 → documents/*.md
→ 分块+嵌入→Qdrant → 知识库就绪 → 头脑风暴提问
→ 混合检索 Top5 + LLM 回答 → 返回答案+来源引用
```

**检索能力说明：**

- **混合检索**：稠密（BGE 语义向量）+ 稀疏（BM25 关键词）双路召回，各取 Top 50。
- **RRF 融合**：两路排名融合后取最相关的 Top 5 片段。
- **LLM 压缩**：传入 LLM 时对候选做上下文压缩，去除冗余噪声。
- **引用溯源**：每个回答附带 `source_file`（来源文档）与原文片段，便于核对。

**管理操作：**

- 管理历史知识文档上传操作记录；可以管理灵感讨论历史对话记录，继续聊天或者删除对话（网页和本地记录同时删除）。

---

## 2. 面向群体

---

## 3. 主要技术

### 3.1 技术栈

| 层次              | 技术选型                                                                          |
| ----------------- | --------------------------------------------------------------------------------- |
| 编排              | LangGraph（`StateGraph` + `MemorySaver` 检查点）                              |
| 大模型接入        | `langchain-openai`（OpenAI 兼容：OpenAI / DeepSeek / 自定义 endpoint）          |
| 结构化数据        | Pydantic v2                                                                       |
| 数值计算 / 可视化 | pandas, numpy, scipy, scikit-learn, matplotlib, pulp                              |
| 文档转换          | MinerU API（PDF/DOC/PPT/图片 → Markdown）                                        |
| 文本切分          | LlamaIndex`SentenceWindowNodeParser`                                            |
| 向量嵌入          | BGE-Small-Zh-V1.5（本地 HuggingFace，CPU 推理）                                   |
| 向量存储          | Qdrant（本地文件型，无需独立服务进程）                                            |
| 检索后处理        | `langchain-classic` `LLMChainFilter` 上下文压缩                               |
| 服务框架          | FastAPI + Uvicorn，SSE（Server-Sent Events）实时进度                              |
| 前端              | React + Vite + TypeScript（react-markdown + remark-math + rehype-katex 渲染公式） |

## 4. 安装说明

### 4.1 环境要求

- Python 3.11+
- Node.js 18+
- uv（Python 包管理器）

### 4.2 配置条件

1. **LLM API**：OpenAI、DeepSeek 或自定义 OpenAI 兼容 endpoint。
2. **Tavily API**：联网检索功能需要（[www.tavily.com](https://www.tavily.com)）。
3. **MinerU API**：非 Markdown 文档转换需要（[mineru.net](https://mineru.net)）。
4. **本地嵌入模型**：需下载 `bge-small-zh-v1.5` 到 `KnowledgeBase/embedding_model/`。

### 4.3 环境安装

```bash
# 1. 安装 Python 依赖（使用 uv）
uv sync

# 2. 安装前端依赖
cd web && npm install
```

### 4.4 部署运行

**1.构建前端：**

```bash
cd web && npm run build
# 构建产物在 web/dist/，后端会直接静态托管
```

**2.启动后端：**

```bash
uvicorn server.main:app --host 0.0.0.0 --port 8000
# 访问网址：http://localhost:8000
```
