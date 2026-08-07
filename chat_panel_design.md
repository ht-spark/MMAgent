# MMAgent 对话式交互面板 · 设计文档

> 状态：设计稿（未实现）
> 关联决策：用户在前端交互方向中选择 **D. 对话式交互面板**（2026-08-07）
> 互补项：本方案天然包含 **A. 实时进度流（SSE）** 的管道，可作为后续统一流式基础设施

---

## 1. 目标与定位

为 MMAgent 增加**基于本次建模产物（run artifacts）的对话助手**，让用户在任务完成后（或过程中）以自然语言提问，例如：

- “为什么第 2 问用了熵权法而不是 AHP？”
- “解释一下 TOPSIS 的接近度结果代表了什么？”
- “第 3 问的敏感性分析说明什么？有没有稳健性风险？”
- “摘要里那串接近度数值是怎么算出来的？”

**关键原则**：对话不是通用 GPT，而是把“这次解题过程”作为唯一知识来源。模型只能基于该 run 的真实产物回答，信息不足时明确告知“产物中未包含该信息”，杜绝编造。

> 本文档范围为 **MVP（基于产物的问答 + 流式）**。真正的“引导重做某问”（如“用 AHP 重做第 3 问”）属于运行期人工介入（选项 B）范畴，依赖 `run_graph` 的定点重跑与挂起机制，列入 Phase 2，不在本 MVP。

---

## 2. 总体架构

```
┌─────────────────────────┐         SSE (text/event-stream)        ┌──────────────────────────┐
│   Web 前端 (React/Vite)  │  POST /api/runs/{id}/chat  ──────────▶ │   FastAPI 服务端          │
│  Chat.tsx / ChatPanel    │ ◀─────────── token 流 ──────────────── │   ChatService             │
│  fetch 流式读取 body     │                                        │   ① 装配 run 上下文       │
│  持 messages 数组(多轮)  │                                        │   ② create_llm(流式)      │
└─────────────────────────┘                                        │   ③ 逐 token 推送         │
                                                                     └────────────┬─────────────┘
                                                                                  │ 读取
                                                                                  ▼
                                          artifacts/<run_id>/  ── paper.md / context/*.json / review_report.json
                                          （复用已有文件服务路径，无需新增存储）
```

**复用现有能力**：
- `create_llm(...)`（`scr/math_modeling_agent/llm.py`）：兼容 MeritModel / DeepSeek / OpenAI，支持 `stream=True`。
- `server/main.py` 的 `RunRegistry`：已存 run 的 `ModelConfig`（provider / api_key / base_url / model），聊天端点可直接复用，也允许请求时覆盖。
- 前端已装 `marked`（Markdown 渲染）、无额外依赖。

---

## 3. 后端设计

### 3.1 端点规格

**路径**：`POST /api/runs/{id}/chat`
**Content-Type**：`application/json`
**响应**：`text/event-stream`（SSE）

**请求体**
```json
{
  "messages": [
    { "role": "user", "content": "为什么第2问用熵权法？" }
  ],
  "model_config": {            // 可选；缺省复用该 run 提交时保存的配置
    "provider": "openai",
    "api_key": "...",
    "base_url": "http://219.138.23.79:8000/v1",
    "model": "MeritModel"
  }
}
```

**SSE 事件格式**
```
event: token
data: {"text": "第2问采用熵权法，"}

event: token
data: {"text": "是因为各指标数据..."}

event: done
data: {"ok": true, "usage": {"prompt_tokens": 3120, "completion_tokens": 180}}

event: error
data: {"message": "读取 run 产物失败：..."}
```

**错误码**：
- `404`：run_id 不存在。
- `400`：messages 为空或格式非法。
- 流式中途错误：发送 `event: error` 后关闭流（前端保留已收到的 token）。

### 3.2 ChatService 流程（`server/chat.py`）

```python
async def chat_stream(run_id: str, payload: ChatRequest) -> AsyncGenerator[str, None]:
    # 1. 校验 run 存在（查 RunRegistry）
    # 2. 解析 model_config：payload 优先，否则取 run 存储配置
    # 3. 装配上下文（见 3.3）
    system_prompt = build_system_prompt(run_id)
    # 4. 调 LLM 流式（同步 client 跑在 to_thread，桥接 asyncio.Queue）
    llm = create_llm(model_config)
    queue: asyncio.Queue = asyncio.Queue()
    async def producer():
        for chunk in llm.chat.completions.create(
            model=..., messages=[{"role":"system","content":system_prompt}, *payload.messages],
            stream=True,
        ):
            delta = chunk.choices[0].delta.content or ""
            await queue.put(delta)
        await queue.put(None)  # EOF
    async def consumer():
        prod = asyncio.create_task(producer())
        while True:
            tok = await queue.get()
            if tok is None:
                yield sse("done", {"ok": True})
                break
            yield sse("token", {"text": tok})
        await prod
    return consumer()
```

> **SSE 与同步 LLM 的桥接**：OpenAI 兼容 client 的流式是同步迭代器。用 `asyncio.create_task` 在后台线程/协程驱动 producer 把 token 推入 `asyncio.Queue`，async 生成器从队列消费并 `yield` SSE 分片，避免阻塞事件循环。复用 `server/main.py` 中 `asyncio.to_thread` 调度模式。

### 3.3 上下文装配策略（`build_system_prompt`）

读取 `artifacts/<run_id>/` 下文件并裁剪：

| 来源文件 | 用途 | 裁剪策略 |
|---|---|---|
| `paper.md` | 论文全文（含各小问方法/结论/公式） | 若 < ~12k tokens 全量；否则截断并标注“（论文过长，已截断）” |
| `context/data_profile_report.json` | 数据整体画像 | 全量（结构化、体积可控） |
| `context/data_inventory_*.json` | 各 sheet 字段含义/缺失率 | **只取**字段名、行数、缺失率、类型，丢弃原始样本行 |
| `review_report.json` | 审查结论 | 全量（体积小） |

**System Prompt 模板**
```
你是 MMAgent 数学建模助手的对话界面。下面是关于【本次建模任务】的真实产物，
请仅基于这些内容回答用户问题：
- 不得编造产物中不存在的方法、数据或结论；
- 若信息不足，明确说“该 run 的产物中未包含此信息”；
- 引用论文时指明对应小问（如“第2问”）；尽量用中文、条理清晰。

==== 论文 ====
{paper_md}

==== 数据画像 ====
{data_profile_report}

==== 各数据表清单（字段/行数/缺失率）====
{inventory_summaries}

==== 审查报告 ====
{review_report}
```

### 3.4 会话状态

- **MVP：无状态**。多轮历史由前端持有 `messages` 数组，每次请求回传完整历史；服务端不持久化会话，实现最简单、最稳。
- **后续（可选）**：在 `server/runs.db` 增加 `chats(run_id, role, content, ts)` 表，支持刷新后恢复历史。

---

## 4. 前端设计

### 4.1 路由与组件

| 文件 | 改动 | 说明 |
|---|---|---|
| `web/src/pages/Chat.tsx` | **新建** | 对话页，读 `:runId`，组合 `ChatPanel` |
| `web/src/components/ChatPanel.tsx` | **新建** | 消息列表 + 输入框 + 流式渲染 + 停止按钮 |
| `web/src/api.ts` | 修改 | 新增 `chatRun(runId, messages, modelConfig?)` 流式请求封装 |
| `web/src/App.tsx` | 修改 | 增加路由 `/chat/:runId`；在结果/进度页加“对话助手”入口 |
| `web/src/components/Sidebar.tsx` | 修改 | 增加“💬 对话助手”导航项（按 run 进入） |

### 4.2 流式消费（重要细节）

`EventSource` **仅支持 GET + query**，无法发送带 body 的 messages。因此采用 **`fetch` POST + 读取 `response.body` 流**：

```ts
export async function chatRun(
  runId: string,
  messages: { role: string; content: string }[],
  modelConfig?: any,
  onToken: (t: string) => void,
  signal?: AbortSignal,
) {
  const res = await fetch(`/api/runs/${runId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, model_config: modelConfig }),
    signal,
  })
  if (!res.ok || !res.body) throw new Error('聊天请求失败')
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    // 按 "\n\n" 切分 SSE 事件，解析 event:/data: 行
    const parts = buf.split('\n\n'); buf = parts.pop() || ''
    for (const p of parts) {
      const m = /event: (\w+)\ndata: (.+)/.exec(p)
      if (!m) continue
      const data = JSON.parse(m[2])
      if (m[1] === 'token') onToken(data.text)
      else if (m[1] === 'error') throw new Error(data.message)
      // done 由流结束处理
    }
  }
}
```

### 4.3 UI 形态

- 左侧复用现有 `Sidebar`；新增“对话助手”入口进入 `/chat/:runId`。
- `ChatPanel`：顶部显示 run 元信息；中部滚动消息流（用户右对齐、助手左对齐，助手消息用 `marked` 渲染 Markdown）；底部输入框 + 发送 + 停止（`AbortController`）。
- 助手回复**逐 token 追加**，带“思考中…”占位与光标动画。
- 组件内 `messages` state 保存多轮；每次发送把完整历史 POST 给后端。

---

## 5. 数据流时序

```
用户键入问题
   │
   ▼
ChatPanel.chatRun()  POST /api/runs/{id}/chat  (messages 完整历史)
   │
   ▼
ChatService
   ├─ 校验 run + 解析 model_config
   ├─ build_system_prompt() 读 artifacts/<run_id>/*
   └─ create_llm(...).chat.completions.create(stream=True)
          │  逐 chunk
          ▼
       asyncio.Queue  ──▶  async 生成器 yield SSE 分片
          │
          ▼
前端 reader 解析 SSE  ──▶  onToken 追加到消息流（marked 渲染）
   │
   ▼
流结束（done 事件 / body 关闭）→ 完成本轮
```

---

## 6. 文件改动清单（MVP）

**新建**
- `server/chat.py` — `ChatService` + `chat_stream` + 路由 `POST /api/runs/{id}/chat`
- `web/src/pages/Chat.tsx`
- `web/src/components/ChatPanel.tsx`

**修改**
- `server/main.py` — 挂载 chat 路由（`app.include_router(chat_router)`）
- `web/src/api.ts` — 新增 `chatRun` 流式封装
- `web/src/App.tsx` — 增加 `/chat/:runId` 路由与入口
- `web/src/components/Sidebar.tsx` — 增加“对话助手”导航项

**不需改动**
- `scr/` 核心引擎（聊天复用 `create_llm`，不触碰 `run_graph`）
- `server/runs.db` 表结构（MVP 无状态；持久化历史为可选后续）

---

## 7. 关键技术点与风险

1. **SSE + 同步 LLM 桥接**：必须用 `asyncio.Queue` 把同步流式 client 桥接为 async 生成器，否则阻塞事件循环。
2. **EventSource 不支持 POST body**：前端改用 `fetch` + `ReadableStream` 解析 SSE（见 4.2）。
3. **上下文超长**：`paper.md` 可能很大，需截断/摘要策略（3.3 表）；MeritModel 上下文窗口受限时优先保论文与审查报告。
4. **模型质量依赖**：聊天回答质量受 `MeritModel`（或所配端点）真实能力约束；跑通 ≠ 回答可信，建议用干净样例做“问答准确性”验收。
5. **并发**：单 run 聊天与后台 `run_graph` 互不阻塞（聊天只读 artifacts）。
6. **CORS / 代理**：开发期 Vite 代理 `/api → :8000` 已配置，SSE 同样走代理；生产由 `server/main.py` 静态托管 `web/dist`。

---

## 8. 验收标准（MVP）

- [ ] `POST /api/runs/{id}/chat` 对已有 run 返回 SSE 流，token 实时到达、结尾有 `done`。
- [ ] 问“为什么第2问用熵权法”能基于 `paper.md` 给出对应小问的解释，且不编造。
- [ ] 多轮对话上下文连续（前端回传历史生效）。
- [ ] 前端对话页可进入、可输入、可停止、Markdown 正常渲染。
- [ ] 对不存在的 run_id 返回 404；空 messages 返回 400。
- [ ] 中途 LLM 报错时前端保留已收到 token 并提示错误。

---

## 9. 后续演进（非 MVP）

- **Phase 2 · 引导重做**：用户在对话中说“用 AHP 重做第3问”→ 触发 `run_graph` 定点重跑 + 运行中挂起（依赖选项 B 的 HITL 机制）。
- **过程期对话**：任务运行中即可提问（与 A 实时流合并，进度与问答同屏）。
- **历史持久化**：`chats` 表落库，刷新不丢。
- **产物钻取联动**：对话中点击“第3问收敛图”直接跳转到结果页对应图表。
- **检索增强（RAG）**：产物过大时改用向量检索取相关片段，而非全量塞入。
