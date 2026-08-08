import { useEffect, useRef, useState } from 'react'
import { confirmBudget, createRun, checkBackendOnline, getRun, getPaper, getFigures, renameRun } from '../api'
import { loadConfigs, loadActiveId, ApiConfig } from '../apiConfigs'

type MsgKind = 'info' | 'progress' | 'error' | 'success' | 'warn' | 'result'

/** 结果附件数据：任务完成后在聊天中展示 */
type ResultData = {
  paperContent: string
  paperDocxUrl?: string
  figures: string[]
  codeFiles: { name: string; url: string }[]
  stats?: { time: number; token: number }
}

/** 预览模态框内容类型 */
type PreviewState = {
  title: string
  kind: 'paper' | 'code' | 'images'
  paperContent?: string
  codeContent?: string
  codeUrl?: string
  images?: string[]
  runId: string
} | null

type ChatMsg = {
  id: number
  role: 'user' | 'assistant'
  text: string
  kind: MsgKind
  ts: number
  result?: ResultData
}

type Phase = 'compose' | 'running' | 'done'

/** 节点名中文映射 */
const NODE_CN: Record<string, string> = {
  intake: '数据摄入',
  context: '任务理解',
  g0_retry: '任务理解重试',
  select_question: '选择子任务',
  assemble_context: '装配上下文',
  configure_question_budget: '预算配置',
  solve_question: '子任务求解',
  validate_result: '结果验证',
  gq_check: '质量检查',
  archive_result: '归档结果',
  global_review: '全局审查',
  write_paper: '报告写作',
  review_paper: '报告审查',
  deliver: '最终交付',
  gf_revise: '报告修订',
}

/** 工作流状态中文映射 */
const STATUS_CN: Record<string, string> = {
  initializing: '初始化中',
  intake_ready: '数据摄入完成',
  context_ready: '任务理解完成',
  solving: '求解中',
  all_questions_done: '所有子任务完成',
  delivered: '已交付',
  failed: '失败',
}

/** GQ 动作中文映射 */
const ACTION_CN: Record<string, string> = {
  pass: '通过',
  retry: '重试',
  blocked: '阻塞',
}

/** 将 q1/q2 等子问题 ID 转为"第1个子任务"格式 */
function fmtQid(qid: string): string {
  const m = qid.match(/q(\d+)/i)
  return m ? `第${m[1]}个子任务` : qid
}

/** 翻译节点名 + 工作流状态为中文进度行 */
function fmtProgress(node: string, wf: string, gqAction?: string): string {
  const nodeCn = NODE_CN[node] || node
  const parts: string[] = [nodeCn]
  if (wf) parts.push(STATUS_CN[wf] || wf)
  if (gqAction) parts.push(`（${ACTION_CN[gqAction] || gqAction}）`)
  return parts.join(' · ')
}

/** 预算项配置：仅展示强制项（监控项 time/token 不在弹窗中显示，完成后统计） */
const BUDGET_FIELDS: { key: string; label: string; enforced: boolean }[] = [
  { key: 'search', label: '联网检索次数', enforced: true },
  { key: 'candidate', label: '方法候选数量', enforced: true },
  { key: 'code_repair', label: '代码修复次数', enforced: true },
  { key: 'validation', label: '验证迭代次数', enforced: true },
]

type BudgetReq = {
  question_id: string
  proposed: Record<string, number>
}

type Props = {
  /** 若提供，则直接进入“接管进行中任务”模式：跳过输入，实时同步该 run 的进度 */
  resumeRunId?: string | null
  /** 建模完成后跳转到结果页 */
  onViewResult: (runId: string) => void
}

let _seq = 1
const nextId = () => _seq++

export default function ChatModeling({ resumeRunId, onViewResult }: Props) {
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [problemText, setProblemText] = useState('')
  const [problemFile, setProblemFile] = useState<File | null>(null)
  const [dataFiles, setDataFiles] = useState<File[]>([])
  const [phase, setPhase] = useState<Phase>(resumeRunId ? 'running' : 'compose')
  const [runId, setRunId] = useState<string | null>(resumeRunId ?? null)
  const [busy, setBusy] = useState(false)
  const [activeCfg, setActiveCfg] = useState<ApiConfig | null>(null)
  const [activeName, setActiveName] = useState('')
  const [budgetReq, setBudgetReq] = useState<BudgetReq | null>(null)
  const [budgetDraft, setBudgetDraft] = useState<Record<string, number>>({})
  const [budgetBusy, setBudgetBusy] = useState(false)
  /** 当前正在执行的步骤描述（用于动画展示） */
  const [currentStep, setCurrentStep] = useState('')
  /** 预览模态框状态 */
  const [preview, setPreview] = useState<PreviewState>(null)
  /** 任务名称（用户可编辑） */
  const [taskName, setTaskName] = useState('')
  /** 任务名称编辑态（输入框值） */
  const [taskNameDraft, setTaskNameDraft] = useState('')
  const [editingName, setEditingName] = useState(false)

  const esRef = useRef<EventSource | null>(null)
  const listRef = useRef<HTMLDivElement | null>(null)
  const initRef = useRef(false)

  function push(role: 'user' | 'assistant', text: string, kind: MsgKind = 'info', result?: ResultData) {
    setMessages((m) => [...m, { id: nextId(), role, text, kind, ts: Date.now(), result }])
  }

  // 读取当前激活的 API 配置（与 Submit 页同一来源）
  useEffect(() => {
    const configs = loadConfigs()
    const activeId = loadActiveId()
    const active = configs.find((c) => c.id === activeId) ?? configs[0] ?? null
    setActiveCfg(active)
    setActiveName(active?.name ?? '')
  }, [])

  // 首条消息 + （接管模式下）加载历史进度并订阅实时流
  // 使用 ref 守卫防止 React.StrictMode 开发模式下双执行导致欢迎消息重复
  useEffect(() => {
    if (initRef.current) return
    initRef.current = true

    if (resumeRunId) {
      push('assistant', `正在恢复任务 ${resumeRunId} 的进度历史…`, 'info')
      loadHistoryAndResume(resumeRunId)
    } else {
      push(
        'assistant',
        '你好，我是 MMAgent 建模助手。\n请在下方输入任务文本，或用按钮上传「任务文件」；可同时附加若干「数据附件」。准备好后点击「开始建模」，我会把建模进度实时推送到这里。',
        'info',
      )
    }
    return () => {
      esRef.current?.close()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 新消息时滚动到底部
  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  // 缓存预算统计，等 done 事件时一起展示
  const statsRef = useRef<{ time: number; token: number } | null>(null)
  // 合并进度消息的 ID，所有进度事件追加到同一条消息
  const progressMsgIdRef = useRef<number | null>(null)

  /** 追加一行进度到合并进度消息（不存在则创建） */
  function appendProgress(line: string) {
    setMessages((msgs) => {
      const pid = progressMsgIdRef.current
      if (pid !== null) {
        return msgs.map((m) =>
          m.id === pid ? { ...m, text: m.text + '\n' + line, ts: Date.now() } : m,
        )
      }
      const id = nextId()
      progressMsgIdRef.current = id
      return [...msgs, { id, role: 'assistant' as const, text: line, kind: 'progress' as const, ts: Date.now() }]
    })
  }

  /** 批量设置进度消息文本（用于加载历史事件） */
  function setProgressText(lines: string[]) {
    if (lines.length === 0) return
    const text = lines.join('\n')
    // 先确定消息 ID 并同步写入 ref，确保后续 SSE 事件能立即找到目标消息
    const id = progressMsgIdRef.current ?? nextId()
    progressMsgIdRef.current = id
    setMessages((msgs) => {
      const existing = msgs.find((m) => m.id === id)
      if (existing) {
        return msgs.map((m) =>
          m.id === id ? { ...m, text, ts: Date.now() } : m,
        )
      }
      return [...msgs, { id, role: 'assistant' as const, text, kind: 'progress' as const, ts: Date.now() }]
    })
  }

  /** 处理单个进度事件，返回是否为普通节点事件（非预算类） */
  function handleProgressEvent(ev: any) {
    if (ev.type === 'budget_request') {
      const proposed: Record<string, number> = ev.proposed || {}
      setBudgetReq({ question_id: ev.question_id || '', proposed })
      setBudgetDraft({ ...proposed })
      push('assistant', `⏸ ${fmtQid(ev.question_id || '')}预算待确认：请在弹窗中调整并点击「确认」继续建模。`, 'warn')
    } else if (ev.type === 'budget_confirmed') {
      setBudgetReq(null)
      const action = ev.action
      if (action === 'override') {
        push('assistant', `✅ ${fmtQid(ev.question_id || '')}预算已按你的输入覆盖。`, 'success')
      } else if (action === 'default') {
        push('assistant', `✅ ${fmtQid(ev.question_id || '')}预算沿用默认。`, 'info')
      } else {
        push('assistant', `⚠️ ${fmtQid(ev.question_id || '')}预算确认已取消。`, 'warn')
      }
    } else if (ev.type === 'budget_summary') {
      statsRef.current = {
        time: ev.time_total || 0,
        token: ev.token_total || 0,
      }
    } else if (ev.type === 'node_start') {
      // 节点开始事件：只更新动画步骤描述，不追加进度行
      // 如果还没有进度消息，先创建一个空消息让动画立即可见
      const node = ev.node || 'step'
      setCurrentStep(NODE_CN[node] || node)
      if (progressMsgIdRef.current === null) {
        appendProgress('')
      }
    } else {
      // 普通节点进度（节点完成）：追加到合并进度消息
      const node = ev.node || 'step'
      const wf = ev.workflow_status || ''
      const gqAction = ev.gq_action || ''
      const qid = ev.current_question_id || ''
      const qidSuffix = qid ? ` [${fmtQid(qid)}]` : ''
      const line = fmtProgress(node, wf, gqAction) + qidSuffix
      appendProgress(line)
      // 更新当前步骤描述（用于动画）
      setCurrentStep(NODE_CN[node] || node)
    }
  }

  /** 恢复模式：先加载历史进度事件，再接管实时流 */
  async function loadHistoryAndResume(id: string) {
    try {
      const run = await getRun(id)
      if (!run) {
        push('assistant', '未找到该任务记录。', 'error')
        return
      }

      // 恢复模式下从后端加载任务名称
      if (run.task_name) {
        setTaskName(run.task_name)
        setTaskNameDraft(run.task_name)
      }

      const events: any[] = run.progress || []
      const status: string = run.status

      // 将历史事件渲染为进度消息
      const lines: string[] = []
      let lastNode = ''
      for (const ev of events) {
        if (ev.type === 'budget_summary') {
          statsRef.current = {
            time: ev.time_total || 0,
            token: ev.token_total || 0,
          }
        } else if (ev.type === 'budget_request' || ev.type === 'budget_confirmed') {
          // 预算类事件跳过（历史中不需要弹窗）
        } else if (ev.type === 'node_start') {
          // 节点开始事件：只更新最后节点名，不追加进度行
          lastNode = ev.node || 'step'
        } else {
          const node = ev.node || 'step'
          const wf = ev.workflow_status || ''
          const gqAction = ev.gq_action || ''
          const qid = ev.current_question_id || ''
          const qidSuffix = qid ? ` [${fmtQid(qid)}]` : ''
          lines.push(fmtProgress(node, wf, gqAction) + qidSuffix)
          lastNode = node
        }
      }
      if (lines.length > 0) {
        setProgressText(lines)
        setCurrentStep(NODE_CN[lastNode] || lastNode)
      }

      // 根据任务状态决定后续行为
      if (status === 'succeeded') {
        setPhase('done')
        push('assistant', '✅ 建模完成！正在加载结果…', 'success')
        loadResults(id)
      } else if (status === 'failed') {
        setPhase('done')
        push('assistant', `❌ 建模失败：${run.error || '未知错误'}`, 'error')
      } else if (status === 'cancelled') {
        setPhase('done')
        push('assistant', '⚠️ 任务已被中断。', 'warn')
      } else {
        // 仍在运行：接管实时流，跳过已加载的事件
        push('assistant', `已恢复任务进度，继续实时同步…（已完成 ${events.length} 个事件）`, 'info')
        attachStream(id, events.length)
      }
    } catch {
      // 降级：直接从头订阅 SSE
      push('assistant', '历史进度加载失败，直接订阅实时流…', 'warn')
      attachStream(id, 0)
    }
  }

  function attachStream(id: string, after: number = 0) {
    esRef.current?.close()
    // 仅当从头订阅时重置合并消息；恢复模式（after>0）保留已有进度消息
    if (after === 0) {
      progressMsgIdRef.current = null
      // 立即创建进度消息，让用户马上看到"正在建模"动画
      appendProgress('')
      setCurrentStep('数据摄入')
    }
    const url = after > 0
      ? `/api/runs/${id}/progress/stream?after=${after}`
      : `/api/runs/${id}/progress/stream`
    const es = new EventSource(url)
    esRef.current = es

    let reconnectCount = 0

    es.onopen = () => {
      reconnectCount = 0
    }

    es.onmessage = (e) => {
      let data: any
      try {
        data = JSON.parse(e.data)
      } catch {
        return
      }
      if (data.type === 'event') {
        handleProgressEvent(data.event || {})
      } else if (data.type === 'done') {
        es.close()
        setPhase('done')
        setCurrentStep('')
        const status = data.status
        if (status === 'succeeded') {
          push('assistant', '✅ 建模完成！正在加载结果…', 'success')
          loadResults(id)
        } else if (status === 'cancelled') {
          push('assistant', '⚠️ 任务已被中断。', 'warn')
        } else {
          push('assistant', `❌ 建模失败：${data.error || '未知错误'}`, 'error')
        }
      } else if (data.type === 'error') {
        push('assistant', `❌ ${data.message || '进度流出错'}`, 'error')
      }
      // 'subscribed' / 注释心跳无需处理
    }

    es.onerror = () => {
      // EventSource 会自动重连，但若多次失败则提示用户
      reconnectCount++
      if (reconnectCount === 3) {
        push('assistant', '⚠️ 进度流连接不稳定，正在自动重连…', 'warn')
      }
      if (reconnectCount > 10) {
        es.close()
        push('assistant', '❌ 进度流连接失败，请检查后端服务是否正常运行。', 'error')
      }
    }
  }

  /** 任务完成后：拉取产物并在聊天中展示（仅 paper.md/docx、图片、解题代码） */
  async function loadResults(rid: string) {
    try {
      const [run, paper, figs] = await Promise.all([
        getRun(rid).catch(() => null),
        getPaper(rid).catch(() => ''),
        getFigures(rid).catch(() => []),
      ])

      const artifacts: string[] = run?.artifacts || []
      const dl = (p: string) => `/api/runs/${rid}/files/${encodeURIComponent(p)}`

      // 筛选解题代码：questions/<qid>/solution.py
      const codeFiles = artifacts
        .filter((p) => /^questions\/[^/]+\/solution\.py$/.test(p))
        .map((p) => {
          const qid = p.split('/')[1]
          return { name: `解题代码（${fmtQid(qid)}）.py`, url: dl(p) }
        })

      const paperDocx = artifacts.find((p) => p === 'paper.docx')

      const stats = statsRef.current

      push(
        'assistant',
        '建模结果如下：',
        'result',
        {
          paperContent: paper || '（暂无报告内容）',
          paperDocxUrl: paperDocx ? dl(paperDocx) : undefined,
          figures: figs,
          codeFiles,
          stats: stats ? { time: Math.round(stats.time), token: stats.token } : undefined,
        },
      )
    } catch {
      push('assistant', '结果加载失败，可点击右上角「查看结果」手动查看。', 'warn')
    }
  }

  async function handleStart() {
    if (busy || phase !== 'compose') return
    const text = problemText.trim()
    if (!text && !problemFile) {
      push('assistant', '请先输入任务文本，或上传任务文件，再开始建模。', 'warn')
      return
    }
    if (!activeCfg) {
      push('assistant', '尚未配置 API，请先到侧边栏「API 管理」添加并设为默认后再开始。', 'error')
      return
    }
    setBusy(true)

    // 提交前检查后端是否在线，避免长时间等待后才发现连接失败
    const online = await checkBackendOnline()
    if (!online) {
      push('assistant', '后端服务未启动或无法连接。请先在终端运行：python -m uvicorn server.main:app --port 8000', 'error')
      setBusy(false)
      return
    }

    // 用户消息：汇总提交内容
    const parts: string[] = []
    if (problemFile) parts.push(`任务文件：${problemFile.name}`)
    if (text) parts.push(`任务：${text.length > 120 ? text.slice(0, 120) + '…' : text}`)
    if (dataFiles.length) parts.push(`数据附件 ${dataFiles.length} 个：${dataFiles.map((f) => f.name).join('、')}`)
    push('user', parts.join('\n'))

    const fd = new FormData()
    if (problemFile) fd.append('problem_file', problemFile)
    if (text) fd.append('problem_text', text)
    dataFiles.forEach((f) => fd.append('data_files', f))
    const cfg: Record<string, string> = { provider: activeCfg.provider, api_key: activeCfg.apiKey }
    if (activeCfg.baseUrl) cfg.base_url = activeCfg.baseUrl
    if (activeCfg.model) cfg.model = activeCfg.model
    fd.append('llm_config', JSON.stringify(cfg))
    if (taskName.trim()) fd.append('task_name', taskName.trim())

    try {
      const r = await createRun(fd)
      setRunId(r.run_id)
      setPhase('running')
      setCurrentStep('数据摄入')
      push('assistant', `已收到任务，开始建模。(任务编号${r.run_id})`, 'info')
      attachStream(r.run_id)
    } catch (err) {
      push('assistant', `提交失败：${err instanceof Error ? err.message : String(err)}`, 'error')
    } finally {
      setBusy(false)
    }
  }

  const composing = phase === 'compose'

  async function submitBudget(useDefaults: boolean) {
    if (!runId || !budgetReq || budgetBusy) return
    setBudgetBusy(true)
    const limits: Record<string, number> = {}
    if (!useDefaults) {
      for (const k of ['search', 'candidate', 'code_repair', 'validation']) {
        const v = Number(budgetDraft[k])
        if (Number.isFinite(v) && v > 0) limits[k] = Math.floor(v)
      }
    }
    try {
      await confirmBudget(runId, {
        question_id: budgetReq.question_id,
        use_defaults: useDefaults,
        limits: useDefaults ? undefined : limits,
      })
      setBudgetReq(null) // 服务端随后会推 budget_confirmed 事件补充消息
    } catch (err) {
      push('assistant', `预算确认失败：${err instanceof Error ? err.message : String(err)}`, 'error')
    } finally {
      setBudgetBusy(false)
    }
  }

  async function saveTaskName() {
    const name = taskNameDraft.trim()
    if (!runId) {
      setTaskName(name)
      setEditingName(false)
      return
    }
    try {
      await renameRun(runId, name)
      setTaskName(name)
    } catch {
      // 重命名失败时仍更新本地显示
      setTaskName(name)
    }
    setEditingName(false)
  }

  return (
    <div className="chatapp">
      <div className="chatapp-head">
        <div>
          <div className="chatapp-title-row">
            {editingName ? (
              <input
                className="task-name-input"
                value={taskNameDraft}
                onChange={(e) => setTaskNameDraft(e.target.value)}
                onBlur={saveTaskName}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') { e.preventDefault(); saveTaskName() }
                  if (e.key === 'Escape') { setTaskNameDraft(taskName); setEditingName(false) }
                }}
                placeholder="输入任务名称"
                autoFocus
              />
            ) : (
              <h2
                className="chatapp-title"
                onClick={() => { setTaskNameDraft(taskName); setEditingName(true) }}
                title="点击编辑任务名称"
                style={{ cursor: 'pointer' }}
              >
                {taskName || '建模对话'}
                <span className="chatapp-title-edit">✎</span>
              </h2>
            )}
          </div>
          <div className="chatapp-sub">
            {activeName ? (
              <>
                当前 API：<strong>{activeName}</strong>
                {activeCfg?.model ? ` · ${activeCfg.model}` : ''}
              </>
            ) : (
              '尚未配置 API（请到「API 管理」添加）'
            )}
            {runId && (
              <>
                {' '}· 任务编号 <code>{runId}</code>
              </>
            )}
          </div>
        </div>
        {phase === 'done' && runId && (
          <button className="btn-primary" onClick={() => {
            const lastResult = messages.find(m => m.result)
            if (lastResult) {
              listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
            }
          }}>
            滚动到结果 ↓
          </button>
        )}
      </div>

      <div className="chatapp-messages" ref={listRef}>
        {messages.map((m) => (
          <div key={m.id} className={`message ${m.role === 'user' ? 'user' : ''}`}>
            {m.role === 'assistant' && <div className="msg-avatar">M</div>}
            <div className={`msg-content kind-${m.kind}`}>
              <div className="msg-text">{m.text}</div>
              {/* 进度消息 + 运行中：在末尾显示动态"正在建模"动画 */}
              {m.kind === 'progress' && phase === 'running' && (
                <div className="progress-live">
                  <span className="progress-live-text">
                    {currentStep ? `${currentStep}进行中` : '正在建模'}
                  </span>
                  <span className="progress-dots">
                    <span></span>
                    <span></span>
                    <span></span>
                  </span>
                </div>
              )}
              {m.result && (
                <div className="result-block">
                  {m.result.stats && (
                    <div className="result-stats">
                      <span>⏱ 耗时 {m.result.stats.time} 秒</span>
                      <span>🔤 token {m.result.stats.token.toLocaleString()}</span>
                    </div>
                  )}
                  <div className="result-cards">
                    <button
                      className="result-card"
                      onClick={() => setPreview({
                        title: 'Paper (Markdown)',
                        kind: 'paper',
                        paperContent: m.result!.paperContent,
                        runId: runId!,
                      })}
                    >
                      <span className="result-card-icon">📄</span>
                      <span className="result-card-label">paper.md</span>
                      <span className="result-card-hint">点击预览</span>
                    </button>
                    {m.result.paperDocxUrl ? (
                      <a
                        className="result-card"
                        href={m.result.paperDocxUrl}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <span className="result-card-icon">📄</span>
                        <span className="result-card-label">paper.docx</span>
                        <span className="result-card-hint">点击下载</span>
                      </a>
                    ) : (
                      <div className="result-card result-card-disabled">
                        <span className="result-card-icon">📄</span>
                        <span className="result-card-label">paper.docx</span>
                        <span className="result-card-hint">未生成</span>
                      </div>
                    )}
                    {m.result.codeFiles.length > 0 ? (
                      <button
                        className="result-card"
                        onClick={async () => {
                          const cf = m.result!.codeFiles[0]
                          try {
                            const resp = await fetch(cf.url)
                            const code = await resp.text()
                            setPreview({
                              title: cf.name,
                              kind: 'code',
                              codeContent: code,
                              codeUrl: cf.url,
                              runId: runId!,
                            })
                          } catch {
                            setPreview({
                              title: cf.name,
                              kind: 'code',
                              codeContent: '无法加载代码内容',
                              codeUrl: cf.url,
                              runId: runId!,
                            })
                          }
                        }}
                      >
                        <span className="result-card-icon">🐍</span>
                        <span className="result-card-label">解题代码</span>
                        <span className="result-card-hint">点击预览</span>
                      </button>
                    ) : (
                      <div className="result-card result-card-disabled">
                        <span className="result-card-icon">🐍</span>
                        <span className="result-card-label">解题代码</span>
                        <span className="result-card-hint">未生成</span>
                      </div>
                    )}
                    {m.result.figures.length > 0 ? (
                      <button
                        className="result-card"
                        onClick={() => setPreview({
                          title: '图表',
                          kind: 'images',
                          images: m.result!.figures.map((f) =>
                            `/api/runs/${runId}/files/figures/${encodeURIComponent(f)}`,
                          ),
                          runId: runId!,
                        })}
                      >
                        <span className="result-card-icon">🖼️</span>
                        <span className="result-card-label">图表</span>
                        <span className="result-card-hint">{m.result.figures.length} 张 · 点击预览</span>
                      </button>
                    ) : (
                      <div className="result-card result-card-disabled">
                        <span className="result-card-icon">🖼️</span>
                        <span className="result-card-label">图表</span>
                        <span className="result-card-hint">未生成</span>
                      </div>
                    )}
                  </div>
                </div>
              )}
              <div className="msg-time">{new Date(m.ts).toLocaleTimeString()}</div>
            </div>
            {m.role === 'user' && <div className="msg-avatar msg-avatar-user">U</div>}
          </div>
        ))}
      </div>

      <div className="chatapp-composer">
        {(problemFile || dataFiles.length > 0) && (
          <div className="chip-row">
            {problemFile && (
              <span className="file-chip">
                📄 {problemFile.name}
                <button aria-label="移除任务文件" onClick={() => setProblemFile(null)} disabled={!composing}>
                  ×
                </button>
              </span>
            )}
            {dataFiles.map((f, i) => (
              <span key={`${f.name}-${i}`} className="file-chip">
                📎 {f.name}
                <button
                  aria-label="移除数据附件"
                  onClick={() => setDataFiles((d) => d.filter((_, j) => j !== i))}
                  disabled={!composing}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        <textarea
          className="chatapp-textarea"
          placeholder={
            composing
              ? '在此输入任务文本，或用下方按钮上传任务文件 / 数据附件…'
              : phase === 'running'
                ? '建模进行中，完成后可查看结果'
                : '本次建模已结束'
          }
          value={problemText}
          onChange={(e) => setProblemText(e.target.value)}
          disabled={!composing}
          rows={3}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleStart()
            }
          }}
        />

        <div className="chatapp-toolbar">
          <label className={`attach-btn ${composing ? '' : 'disabled'}`}>
            📄 任务文件
            <input
              type="file"
              accept=".md,.txt"
              hidden
              disabled={!composing}
              onChange={(e) => {
                setProblemFile(e.target.files?.[0] ?? null)
                e.target.value = ''
              }}
            />
          </label>
          <label className={`attach-btn ${composing ? '' : 'disabled'}`}>
            📎 数据附件
            <input
              type="file"
              multiple
              hidden
              disabled={!composing}
              onChange={(e) => {
                const files = Array.from(e.target.files ?? [])
                if (files.length) setDataFiles((d) => [...d, ...files])
                e.target.value = ''
              }}
            />
          </label>
          <div className="spacer" />
          <button className="chatapp-send" onClick={handleStart} disabled={busy || !composing}>
            {busy ? '提交中…' : '开始建模 →'}
          </button>
        </div>
      </div>

      {budgetReq && (
        <div className="modal-mask" onClick={() => { /* 不允许点遮罩关闭，避免误操作 */ }}>
          <div className="modal budget-modal" onClick={(e) => e.stopPropagation()}>
            <h3>确认{fmtQid(budgetReq.question_id)}预算</h3>
            <p className="muted">
              建模已暂停。可调整下方强制项上限后「确认覆盖」，或「使用默认」继续。
            </p>
            <div className="budget-fields">
              {BUDGET_FIELDS.map((f) => (
                <label key={f.key} className="budget-field">
                  <span className="budget-field-label">{f.label}</span>
                  <input
                    type="number"
                    min={1}
                    value={budgetDraft[f.key] ?? 0}
                    disabled={!f.enforced || budgetBusy}
                    onChange={(e) =>
                      setBudgetDraft((d) => ({ ...d, [f.key]: Number(e.target.value) }))
                    }
                  />
                </label>
              ))}
            </div>
            <div className="modal-actions">
              <button className="btn-ghost" onClick={() => submitBudget(true)} disabled={budgetBusy}>
                使用默认
              </button>
              <button className="btn-primary" onClick={() => submitBudget(false)} disabled={budgetBusy}>
                {budgetBusy ? '提交中…' : '确认覆盖'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 预览模态框 */}
      {preview && (
        <div className="modal-mask" onClick={() => setPreview(null)}>
          <div className="modal preview-modal" onClick={(e) => e.stopPropagation()}>
            <div className="preview-head">
              <h3>{preview.title}</h3>
              <div className="preview-head-actions">
                {preview.kind === 'paper' && (
                  <a
                    className="btn-primary btn-sm"
                    href={`/api/runs/${preview.runId}/files/paper.md`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    下载 paper.md
                  </a>
                )}
                {preview.kind === 'code' && preview.codeUrl && (
                  <a
                    className="btn-primary btn-sm"
                    href={preview.codeUrl}
                    target="_blank"
                    rel="noreferrer"
                  >
                    下载代码
                  </a>
                )}
                <button className="btn-ghost btn-sm" onClick={() => setPreview(null)}>关闭</button>
              </div>
            </div>
            <div className="preview-body">
              {preview.kind === 'paper' && (
                <pre className="preview-paper">{preview.paperContent}</pre>
              )}
              {preview.kind === 'code' && (
                <pre className="preview-code">{preview.codeContent}</pre>
              )}
              {preview.kind === 'images' && preview.images && (
                <div className="preview-figs">
                  {preview.images.map((src, i) => (
                    <img key={i} src={src} alt={`figure-${i}`} className="preview-fig" />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
