import { useEffect, useRef, useState } from 'react'
import { cancelRun, getRun } from '../api'

type Props = { runId: string; onDone?: () => void }

export default function Progress({ runId, onDone }: Props) {
  const [run, setRun] = useState<any>(null)
  const [cancelling, setCancelling] = useState(false)
  const [requestedCancel, setRequestedCancel] = useState(false)
  const timer = useRef<number | null>(null)
  const doneRef = useRef(false)

  useEffect(() => {
    let alive = true
    const finish = () => {
      if (doneRef.current) return
      doneRef.current = true
      onDone?.()
    }
    const tick = async () => {
      try {
        const r = await getRun(runId)
        if (!alive) return
        setRun(r)
        if (['succeeded', 'failed', 'cancelled'].includes(r.status)) {
          if (timer.current) window.clearInterval(timer.current)
          finish()
        }
      } catch {
        /* ignore transient errors */
      }
    }
    tick()
    timer.current = window.setInterval(tick, 2000)
    return () => {
      alive = false
      if (timer.current) window.clearInterval(timer.current)
    }
  }, [runId])

  async function handleCancel() {
    setCancelling(true)
    try {
      await cancelRun(runId)
      setRequestedCancel(true)
    } catch (e) {
      // 即便接口报错，也乐观标记为已请求，稍后轮询会修正真实状态
      setRequestedCancel(true)
      console.error(e)
    } finally {
      setCancelling(false)
    }
  }

  if (!run) return <div className="form-card">加载中…</div>

  const events: any[] = run.progress || []
  const active = run.status === 'running' || run.status === 'queued'
  const terminal = ['succeeded', 'failed', 'cancelled'].includes(run.status)

  return (
    <div className="form-card">
      <h2>
        任务进度 <span className={`status-tag ${run.status}`}>{run.status}</span>
      </h2>
      <div className="meta-row">
        Run ID: <code>{runId}</code> · 流程状态: {run.workflow_status || '-'} · 已解小问:{' '}
        {run.results_count ?? 0}
      </div>

      <div className="timeline">
        {events.length === 0 && <div className="ev muted">等待节点开始…</div>}
        {events
          .slice()
          .reverse()
          .map((ev, i) => (
            <div key={i} className="ev">
              <span className="node">{ev.node}</span>
              <span className="wf">{ev.workflow_status || ''}</span>
              <span className="t">
                {ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleTimeString() : ''}
              </span>
            </div>
          ))}
      </div>

      {terminal && run.status === 'cancelled' && (
        <div className="err-box warn">任务已被用户中断。</div>
      )}
      {run.status === 'failed' && <div className="err-box">失败：{run.error}</div>}

      {active && (
        <div className="center muted">
          {requestedCancel ? (
            <>
              中断请求已发送，将在当前步骤（如 LLM 调用）完成后停止…
              <div style={{ marginTop: 16 }}>
                <button className="btn-cancel" disabled>
                  中断中…
                </button>
              </div>
            </>
          ) : (
            <>
              求解进行中，完成后自动跳转至结果页…
              <div style={{ marginTop: 16 }}>
                <button className="btn-cancel" disabled={cancelling} onClick={handleCancel}>
                  {cancelling ? '中断请求已发送…' : '中断任务'}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
