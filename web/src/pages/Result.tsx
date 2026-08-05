import { useEffect, useState } from 'react'
import { getFigures, getPaper, getRun } from '../api'

export default function Result({
  runId,
  onBack,
  onHistory,
}: {
  runId: string
  onBack: () => void
  onHistory: () => void
}) {
  const [paper, setPaper] = useState('')
  const [figures, setFigures] = useState<string[]>([])
  const [run, setRun] = useState<any>(null)

  useEffect(() => {
    getRun(runId).then(setRun).catch(() => {})
    getPaper(runId).then(setPaper).catch(() => setPaper('（暂无论文内容）'))
    getFigures(runId).then(setFigures).catch(() => setFigures([]))
  }, [runId])

  const artifacts: string[] = run?.artifacts || []

  // 分组：论文 / 审查 / 图表 / 其它
  const isFig = (p: string) => p.startsWith('figures/')
  const paperDocx = artifacts.find((p) => p === 'paper.docx')
  const reviewJson = artifacts.find((p) => p === 'review_report.json')
  const otherFiles = artifacts.filter(
    (p) => !isFig(p) && p !== 'paper.md' && p !== 'paper.docx' && p !== 'review_report.json',
  )

  const dl = (p: string) => `/api/runs/${runId}/files/${encodeURIComponent(p)}`

  return (
    <div className="form-card">
      <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <button className="back-link" onClick={onBack}>
          ← 返回新建
        </button>
        <button className="back-link" onClick={onHistory}>
          历史任务
        </button>
      </div>

      <h2>
        结果 <span className={`status-tag ${run?.status}`}>{run?.status}</span>
      </h2>
      {run && (
        <div className="meta-row">
          论文标题：{run.paper_title || '-'} · 审查状态：{run.review_status || '-'}
        </div>
      )}

      <h3 style={{ fontSize: 16, margin: '18px 0 8px' }}>论文预览（Markdown）</h3>
      <pre className="paper-box">{paper}</pre>

      <div className="dl-section">
        <div className="dl-group-title">下载全部产物</div>
        <ul className="dl-list">
          <li>
            <a href={dl('paper.md')} target="_blank" rel="noreferrer">
              paper.md
            </a>
          </li>
          {paperDocx && (
            <li>
              <a href={dl(paperDocx)} target="_blank" rel="noreferrer">
                paper.docx
              </a>
            </li>
          )}
          {reviewJson && (
            <li>
              <a href={dl(reviewJson)} target="_blank" rel="noreferrer">
                review_report.json
              </a>
            </li>
          )}
          {otherFiles.map((p) => (
            <li key={p}>
              <a href={dl(p)} target="_blank" rel="noreferrer">
                {p.split('/').pop()}
              </a>
            </li>
          ))}
        </ul>
      </div>

      <h3 style={{ fontSize: 16, margin: '22px 0 8px' }}>图表</h3>
      <div className="figs">
        {figures.map((f) => (
          <img key={f} src={`/api/runs/${runId}/files/figures/${encodeURIComponent(f)}`} alt={f} />
        ))}
        {figures.length === 0 && <span className="muted">（无图表）</span>}
      </div>

      {run?.status === 'failed' && <div className="err-box">该任务执行失败：{run.error}</div>}
    </div>
  )
}
