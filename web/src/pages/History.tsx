import { useEffect, useState } from 'react'
import { cancelRun, deleteRun, listRuns } from '../api'

export default function History({ onOpen }: { onOpen: (runId: string) => void }) {
  const [runs, setRuns] = useState<any[]>([])
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)
  const [pendingDel, setPendingDel] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState<string | null>(null)

  function load() {
    setLoading(true)
    listRuns()
      .then(setRuns)
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }

  // 进入页面自动加载（无需手动点刷新）
  useEffect(() => {
    load()
  }, [])

  // 有进行中任务时自动轮询刷新（每 4 秒）
  const hasActive = runs.some((r) => r.status === 'queued' || r.status === 'running')
  useEffect(() => {
    if (!hasActive) return
    const timer = setInterval(() => {
      listRuns()
        .then(setRuns)
        .catch(() => {})
    }, 4000)
    return () => clearInterval(timer)
  }, [hasActive])

  function askDelete(r: any) {
    setPendingDel(r.run_id)
  }

  async function confirmDelete() {
    const rid = pendingDel
    setPendingDel(null)
    if (!rid) return
    try {
      await deleteRun(rid)
      setRuns((prev) => prev.filter((x) => x.run_id !== rid))
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleCancel(r: any) {
    setCancelling(r.run_id)
    try {
      await cancelRun(r.run_id)
      // 立即乐观更新状态，稍后刷新列表确认
      setRuns((prev) =>
        prev.map((x) =>
          x.run_id === r.run_id ? { ...x, status: 'cancelled', error: '用户已中断任务' } : x,
        ),
      )
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setCancelling(null)
    }
  }

  const isActive = (s: string) => s === 'queued' || s === 'running'

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">历史任务</h1>
          <div className="page-sub">
            查看过往所有建模任务与产物
            {hasActive && <span className="auto-refresh-hint">· 进行中任务自动刷新</span>}
          </div>
        </div>
        <button className="back-link" onClick={load}>
          刷新
        </button>
      </div>

      {err && <div className="err-box">{err}</div>}

      {!loading && !err && runs.length === 0 && (
        <div className="form-card">
          <p className="muted">暂无历史任务。请返回“建模任务”新建一次建模任务。</p>
        </div>
      )}

      <div className="history-list">
        {runs.map((r) => (
          <div key={r.run_id} className="run-card">
            <div
              className="run-card-main"
              onClick={() => onOpen(r.run_id)}
            >
              <div>
                <div className="run-id">{r.run_id}</div>
                <div className="meta-row" style={{ margin: '4px 0 0' }}>
                  {r.created_at ? new Date(r.created_at).toLocaleString() : ''}
                </div>
              </div>
              <div className="run-main">
                <div className="run-title">{r.task_name || r.paper_title || '未命名任务'}</div>
                <div className="run-preview">{r.problem_preview || '（无题面预览）'}</div>
              </div>
              <span className={`status-tag ${r.status}`}>
                {isActive(r.status) && <span className="status-pulse" />}
                {r.status === 'queued' ? '排队中' : r.status === 'running' ? '建模中' : r.status === 'succeeded' ? '已完成' : r.status === 'failed' ? '失败' : r.status === 'cancelled' ? '已中断' : r.status}
              </span>
            </div>
            {isActive(r.status) ? (
              <button
                className="run-cancel"
                title="中断该任务"
                disabled={cancelling === r.run_id}
                onClick={() => handleCancel(r)}
              >
                {cancelling === r.run_id ? '中断中…' : '中断'}
              </button>
            ) : (
              <button
                className="run-del"
                title="删除该记录"
                onClick={() => askDelete(r)}
              >
                删除
              </button>
            )}
          </div>
        ))}
      </div>

      {pendingDel && (
        <div className="modal-mask" onClick={() => setPendingDel(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>确认删除？</h3>
            <p className="muted">
              将永久删除任务 <code>{pendingDel}</code> 的记录及其全部产物文件，且无法恢复。
            </p>
            <div className="modal-actions">
              <button className="btn-ghost" onClick={() => setPendingDel(null)}>
                取消
              </button>
              <button className="btn-danger" onClick={confirmDelete}>
                删除
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
