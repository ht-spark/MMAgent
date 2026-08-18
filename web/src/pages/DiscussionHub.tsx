type Props = {
  onNew: () => void
  onHistory: () => void
}

export default function DiscussionHub({ onNew, onHistory }: Props) {
  return (
    <div className="page modeling-tasks-page brainstorm-hub-page discussion-hub-page">
      <div className="page-head modeling-tasks-head">
        <div>
          <h1 className="page-title">灵感迸发</h1>
          <p className="page-sub">新建建模讨论，或回到已有讨论继续交流。</p>
        </div>
      </div>
      <div className="modeling-task-grid discussion-task-grid">
        <button className="modeling-task-card" onClick={onNew}>
          <span className="modeling-task-icon" aria-hidden="true">＋</span>
          <span className="modeling-task-copy">
            <strong>新建讨论</strong>
            <span>围绕新的建模问题、假设或分析方向开始交流。</span>
          </span>
          <span className="modeling-task-arrow" aria-hidden="true">→</span>
        </button>
        <button className="modeling-task-card" onClick={onHistory}>
          <span className="modeling-task-icon" aria-hidden="true">◷</span>
          <span className="modeling-task-copy">
            <strong>历史讨论</strong>
            <span>查看已保存的讨论，并在原对话中继续聊天。</span>
          </span>
          <span className="modeling-task-arrow" aria-hidden="true">→</span>
        </button>
      </div>
    </div>
  )
}
