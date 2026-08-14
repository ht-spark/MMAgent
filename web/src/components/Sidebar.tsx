type Props = {
  section: string
  collapsed: boolean
  onToggleCollapse: () => void
  onHome: () => void
  onNew: () => void
  onBrainstorm: () => void
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

const COLLAPSE_ICON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M15 18l-6-6 6-6" />
  </svg>
)

const EXPAND_ICON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 18l6-6-6-6" />
  </svg>
)

export default function Sidebar({
  section,
  collapsed,
  onToggleCollapse,
  onHome,
  onNew,
  onBrainstorm,
  onHistory,
  onApi,
  onDocs,
}: Props) {
  return (
    <aside className={`sidebar ${collapsed ? 'sidebar--collapsed' : ''}`}>
      <div className="sidebar-top">
        <div className="sidebar-logo" onClick={onHome} title={collapsed ? 'MMAgent 数学建模智能体' : undefined}>
          <div className="logo-icon">{LOGO}</div>
          {!collapsed && (
            <div className="logo-text">
              <span className="logo-name sidebar-brand">MMAgent</span>
              <span className="logo-sub sidebar-sub">数学建模智能体</span>
            </div>
          )}
        </div>
        <button
          className="sidebar-toggle"
          onClick={onToggleCollapse}
          title={collapsed ? '展开侧边栏' : '收起侧边栏'}
          aria-label={collapsed ? '展开侧边栏' : '收起侧边栏'}
        >
          {collapsed ? EXPAND_ICON : COLLAPSE_ICON}
        </button>
      </div>

      <nav className="sidebar-nav">
        <button
          className={`nav-item ${section === 'new' ? 'active' : ''}`}
          onClick={onNew}
          title={collapsed ? '新建任务' : undefined}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 5v14M5 12h14" strokeLinecap="round" />
          </svg>
          {!collapsed && '新建任务'}
        </button>
        <button
          className={`nav-item ${section === 'brainstorm' ? 'active' : ''}`}
          onClick={onBrainstorm}
          title={collapsed ? '头脑风暴' : undefined}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 18h6" />
            <path d="M10 22h4" />
            <path d="M8.2 14.5A6 6 0 1 1 15.8 14.5c-.8.65-1.3 1.4-1.45 2.2h-2.7c-.15-.8-.65-1.55-1.45-2.2Z" />
          </svg>
          {!collapsed && '头脑风暴'}
        </button>
        <button
          className={`nav-item ${section === 'history' ? 'active' : ''}`}
          onClick={onHistory}
          title={collapsed ? '历史任务' : undefined}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 3v18h18" />
            <path d="M7 14l4-4 3 3 5-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {!collapsed && '历史任务'}
        </button>
        <button
          className={`nav-item ${section === 'api' ? 'active' : ''}`}
          onClick={onApi}
          title={collapsed ? 'API 管理' : undefined}
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
          {!collapsed && 'API 管理'}
        </button>
        <button
          className={`nav-item ${section === 'docs' ? 'active' : ''}`}
          onClick={onDocs}
          title={collapsed ? '项目文档' : undefined}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 4h11l5 5v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z" />
            <path d="M14 4v5h5" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M8 13h8M8 17h8" strokeLinecap="round" />
          </svg>
          {!collapsed && '项目文档'}
        </button>
      </nav>

      <div className="sidebar-status" title={collapsed ? 'Agent Online' : undefined}>
        <span className="status-dot" />
        {!collapsed && 'Agent Online'}
      </div>
    </aside>
  )
}
