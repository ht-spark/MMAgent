type Props = {
  onKnowledge: () => void
  onInspiration: () => void
  onHistory: () => void
}

export default function BrainstormHub({ onKnowledge, onInspiration, onHistory }: Props) {
  return (
    <div className="page modeling-tasks-page brainstorm-hub-page">
      <div className="page-head modeling-tasks-head">
        <div>
          <h1 className="page-title">头脑风暴</h1>
          <p className="page-sub">维护领域资料，或围绕建模问题开展灵感讨论。</p>
        </div>
      </div>

      <div className="modeling-task-grid">
        <button className="modeling-task-card" onClick={onKnowledge}>
          <span className="modeling-task-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 4h11l5 5v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z" />
              <path d="M14 4v5h5M8 13h8M8 17h8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="modeling-task-copy">
            <strong>知识库维护</strong>
            <span>上传并查看领域资料，为后续检索与建模提供依据。</span>
          </span>
          <span className="modeling-task-arrow" aria-hidden="true">→</span>
        </button>

        <button className="modeling-task-card" onClick={onInspiration}>
          <span className="modeling-task-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 18h6M10 22h4" />
              <path d="M8.2 14.5A6 6 0 1 1 15.8 14.5c-.8.65-1.3 1.4-1.45 2.2h-2.7c-.15-.8-.65-1.55-1.45-2.2Z" />
            </svg>
          </span>
          <span className="modeling-task-copy">
            <strong>灵感迸发</strong>
            <span>在交互式对话中梳理建模问题、假设与分析方向。</span>
          </span>
          <span className="modeling-task-arrow" aria-hidden="true">→</span>
        </button>

        <button className="modeling-task-card" onClick={onHistory}>
          <span className="modeling-task-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 3v18h18" />
              <path d="M7 14l4-4 3 3 5-6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="modeling-task-copy">
            <strong>历史记录</strong>
            <span>查看知识库维护的历史操作，包括上传、删除与格式转换。</span>
          </span>
          <span className="modeling-task-arrow" aria-hidden="true">→</span>
        </button>
      </div>
    </div>
  )
}
