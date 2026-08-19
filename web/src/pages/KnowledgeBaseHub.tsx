type Props = {
  onUpdate: () => void
  onHistory: () => void
}

export default function KnowledgeBaseHub({ onUpdate, onHistory }: Props) {
  return (
    <div className="page modeling-tasks-page brainstorm-hub-page">
      <div className="page-head modeling-tasks-head">
        <div>
          <h1 className="page-title">知识库维护</h1>
          <p className="page-sub">更新知识库资料，或查看已有的维护操作记录。</p>
        </div>
      </div>

      <div className="modeling-task-grid">
        <button className="modeling-task-card" onClick={onUpdate}>
          <span className="modeling-task-icon" aria-hidden="true">＋</span>
          <span className="modeling-task-copy">
            <strong>知识库更新</strong>
            <span>上传、转换和管理知识文档，持续维护知识库内容。</span>
          </span>
          <span className="modeling-task-arrow" aria-hidden="true">→</span>
        </button>

        <button className="modeling-task-card" onClick={onHistory}>
          <span className="modeling-task-icon" aria-hidden="true">◷</span>
          <span className="modeling-task-copy">
            <strong>历史记录</strong>
            <span>查看上传、转换和删除等知识库维护操作。</span>
          </span>
          <span className="modeling-task-arrow" aria-hidden="true">→</span>
        </button>
      </div>
    </div>
  )
}
