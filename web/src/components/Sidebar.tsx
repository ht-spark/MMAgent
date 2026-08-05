type Props = {
  section: string
  onHome: () => void
  onNew: () => void
  onHistory: () => void
  onApi: () => void
  onDocs: () => void
}

const LOGO = (
  <svg viewBox="0 0 32 32" width="28" height="28">
    <defs>
      <linearGradient id="sidebarLogoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stopColor="#4FC3F7" />
        <stop offset="100%" stopColor="#0288D1" />
      </linearGradient>
    </defs>
    <path
      d="M4 24 L4 8 L10 8 L16 16 L22 8 L28 8 L28 24 L24 24 L24 14 L18 22 L14 22 L8 14 L8 24 Z"
      fill="url(#sidebarLogoGrad)"
    />
  </svg>
)

export default function Sidebar({ section, onHome, onNew, onHistory, onApi, onDocs }: Props) {
  return (
    <aside className="sidebar">
      <div className="sidebar-logo" onClick={onHome}>
        <div className="logo-icon">{LOGO}</div>
        <div className="logo-text">
          <span className="logo-name sidebar-brand">MMAgent</span>
          <span className="logo-sub sidebar-sub">数学建模智能体</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        <button
          className={`nav-item ${section === 'new' ? 'active' : ''}`}
          onClick={onNew}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 5v14M5 12h14" strokeLinecap="round" />
          </svg>
          新建任务
        </button>
        <button
          className={`nav-item ${section === 'history' ? 'active' : ''}`}
          onClick={onHistory}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 3v18h18" />
            <path d="M7 14l4-4 3 3 5-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          历史任务
        </button>
        <button
          className={`nav-item ${section === 'api' ? 'active' : ''}`}
          onClick={onApi}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="9" />
            <path
              d="M14.5 9.5 10 12.5 14 15.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path d="M12 3v3M12 18v3M3 12h3M18 12h3" strokeLinecap="round" />
          </svg>
          API 管理
        </button>
        <button
          className={`nav-item ${section === 'docs' ? 'active' : ''}`}
          onClick={onDocs}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 4h11l5 5v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z" />
            <path d="M14 4v5h5" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M8 13h8M8 17h8" strokeLinecap="round" />
          </svg>
          项目文档
        </button>
      </nav>

      <div className="sidebar-status">
        <span className="status-dot" />
        Agent Online
      </div>
    </aside>
  )
}
