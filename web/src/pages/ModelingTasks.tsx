type Props = {
  onNew: () => void
  onHistory: () => void
}

export default function ModelingTasks({ onNew, onHistory }: Props) {
  return (
    <div className="page modeling-tasks-page">
      <div className="page-head modeling-tasks-head">
        <div>
          <h1 className="page-title">建模任务</h1>
          <p className="page-sub">开始新的数学建模，或继续查看和管理已有任务。</p>
        </div>
      </div>

      <div className="modeling-task-grid">
        <button className="modeling-task-card" onClick={onNew}>
          <span className="modeling-task-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 5v14M5 12h14" strokeLinecap="round" />
            </svg>
          </span>
          <span className="modeling-task-copy">
            <strong>新建任务</strong>
            <span>提交问题与资料，启动一次新的建模流程。</span>
          </span>
          <span className="modeling-task-arrow" aria-hidden="true">→</span>
        </button>

        <button className="modeling-task-card" onClick={onHistory}>
          <span className="modeling-task-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 3v18h18" />
              <path d="M7 14l4-4 3 3 5-6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="modeling-task-copy">
            <strong>历史任务</strong>
            <span>查看、继续或管理过去的建模任务与产物。</span>
          </span>
          <span className="modeling-task-arrow" aria-hidden="true">→</span>
        </button>
      </div>
    </div>
  )
}
