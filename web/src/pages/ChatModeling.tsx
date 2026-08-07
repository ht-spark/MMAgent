import { useEffect, useRef, useState } from 'react'
import { confirmBudget, createRun } from '../api'
import { loadConfigs, loadActiveId, ApiConfig } from '../apiConfigs'

type MsgKind = 'info' | 'progress' | 'error' | 'success' | 'warn'

type ChatMsg = {
  id: number
  role: 'user' | 'assistant'
  text: string
  kind: MsgKind
  ts: number
}

type Phase = 'compose' | 'running' | 'done'

/** 预算项配置：键 → 标签 + 是否可编辑（强制项可改，监控项只读） */
const BUDGET_FIELDS: { key: string; label: string; enforced: boolean }[] = [
  { key: 'search', label: '联网检索次数', enforced: true },
  { key: 'candidate', label: '方法候选数量', enforced: true },
  { key: 'code_repair', label: '代码修复次数', enforced: true },
  { key: 'validation', label: '验证迭代次数', enforced: true },
  { key: 'time', label: '时间预算（秒·监控）', enforced: false },
  { key: 'token', label: '令牌预算（·监控）', enforced: false },
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

  const esRef = useRef<EventSource | null>(null)
  const listRef = useRef<HTMLDivElement | null>(null)

  function push(role: 'user' | 'assistant', text: string, kind: MsgKind = 'info') {
    setMessages((m) => [...m, { id: nextId(), role, text, kind, ts: Date.now() }])
  }

  // 读取当前激活的 API 配置（与 Submit 页同一来源）
  useEffect(() => {
    const configs = loadConfigs()
    const activeId = loadActiveId()
    const active = configs.find((c) => c.id === activeId) ?? configs[0] ?? null
    setActiveCfg(active)
    setActiveName(active?.name ?? '')
  }, [])

  // 首条消息 + （接管模式下）订阅进度流
  useEffect(() => {
    if (resumeRunId) {
      push('assistant', `已接管进行中的任务 ${resumeRunId}，正在实时同步建模进度…`, 'info')
      attachStream(resumeRunId)
    } else {
      push(
        'assistant',
        '你好，我是 MMAgent 建模助手。\n请在下方输入题目文本，或用按钮上传「题目文件」；可同时附加若干「数据附件」。准备好后点击「开始建模」，我会把建模进度实时推送到这里。',
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

  function attachStream(id: string) {
    esRef.current?.close()
    const es = new EventSource(`/api/runs/${id}/progress/stream`)
    esRef.current = es
    es.onmessage = (e) => {
      let data: any
      try {
        data = JSON.parse(e.data)
      } catch {
        return
      }
      if (data.type === 'event') {
        const ev = data.event || {}
        if (ev.type === 'budget_request') {
          const proposed: Record<string, number> = ev.proposed || {}
          setBudgetReq({ question_id: ev.question_id || '', proposed })
          setBudgetDraft({ ...proposed })
          push('assistant', `⏸ 第 ${ev.question_id || ''} 问预算待确认：请在弹窗中调整并点击「确认」继续建模。`, 'warn')
        } else if (ev.type === 'budget_confirmed') {
          setBudgetReq(null)
          const action = ev.action
          if (action === 'override') {
            push('assistant', `✅ 第 ${ev.question_id || ''} 问预算已按你的输入覆盖。`, 'success')
          } else if (action === 'default') {
            push('assistant', `✅ 第 ${ev.question_id || ''} 问预算沿用默认。`, 'info')
          } else {
            push('assistant', `⚠️ 第 ${ev.question_id || ''} 问预算确认已取消。`, 'warn')
          }
        } else {
          const node = ev.node || 'step'
          const wf = ev.workflow_status || ''
          push('assistant', wf ? `【${node}】${wf}` : `【${node}】`, 'progress')
        }
      } else if (data.type === 'done') {
        es.close()
        setPhase('done')
        const status = data.status
        if (status === 'succeeded') {
          push('assistant', '✅ 建模完成！论文与图表已生成，点击右上角「查看结果」查看完整产物。', 'success')
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
    // 网络抖动时 EventSource 会自动重连，这里不额外提示
  }

  async function handleStart() {
    if (busy || phase !== 'compose') return
    const text = problemText.trim()
    if (!text && !problemFile) {
      push('assistant', '请先输入题目文本，或上传题目文件，再开始建模。', 'warn')
      return
    }
    if (!activeCfg) {
      push('assistant', '尚未配置 API，请先到侧边栏「API 管理」添加并设为默认后再开始。', 'error')
      return
    }
    setBusy(true)

    // 用户消息：汇总提交内容
    const parts: string[] = []
    if (problemFile) parts.push(`题目文件：${problemFile.name}`)
    if (text) parts.push(`题目：${text.length > 120 ? text.slice(0, 120) + '…' : text}`)
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

    try {
      const r = await createRun(fd)
      setRunId(r.run_id)
      setPhase('running')
      push('assistant', `已收到题目与数据，开始建模（任务 ${r.run_id}）。实时进度如下：`, 'info')
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

  return (
    <div className="chatapp">
      <div className="chatapp-head">
        <div>
          <h2 className="chatapp-title">建模对话</h2>
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
                {' '}· 任务 <code>{runId}</code>
              </>
            )}
          </div>
        </div>
        {phase === 'done' && runId && (
          <button className="btn-primary" onClick={() => onViewResult(runId)}>
            查看结果 →
          </button>
        )}
      </div>

      <div className="chatapp-messages" ref={listRef}>
        {messages.map((m) => (
          <div key={m.id} className={`message ${m.role === 'user' ? 'user' : ''}`}>
            {m.role === 'assistant' && <div className="msg-avatar">M</div>}
            <div className={`msg-content kind-${m.kind}`}>
              <div className="msg-text">{m.text}</div>
              <div className="msg-time">{new Date(m.ts).toLocaleTimeString()}</div>
            </div>
          </div>
        ))}
        {phase === 'running' && <div className="chatapp-typing">● 建模进行中…</div>}
      </div>

      <div className="chatapp-composer">
        {(problemFile || dataFiles.length > 0) && (
          <div className="chip-row">
            {problemFile && (
              <span className="file-chip">
                📄 {problemFile.name}
                <button aria-label="移除题目文件" onClick={() => setProblemFile(null)} disabled={!composing}>
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
              ? '在此输入题目文本，或用下方按钮上传题目文件 / 数据附件…'
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
            📄 题目文件
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
            <h3>确认第 {budgetReq.question_id} 问预算</h3>
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
    </div>
  )
}
