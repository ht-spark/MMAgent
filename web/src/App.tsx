import { useState } from 'react'
import Sidebar from './components/Sidebar'
import Home from './pages/Home'
import NewTask from './pages/NewTask'
import History from './pages/History'
import ApiManager from './pages/ApiManager'
import Brainstorm from './pages/Brainstorm'
import Docs from './pages/Docs'

type Section = 'home' | 'new' | 'brainstorm' | 'history' | 'api' | 'docs'
type TaskStep = 'submit' | 'progress' | 'result'

const SYMBOLS = ['∫', '∑', '∏', '∂', '∇', '∞', 'π', 'σ', 'μ', 'λ', 'α', 'β', 'γ', 'θ', 'Δ', 'Ω']

export default function App() {
  const [section, setSection] = useState<Section>('home')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [task, setTask] = useState<{ step: TaskStep; runId: string | null }>({
    step: 'submit',
    runId: null,
  })

  function startNew() {
    setTask({ step: 'submit', runId: null })
    setSection('new')
  }

  function openFromHistory(runId: string) {
    // 所有历史任务都先恢复聊天上下文；ChatModeling 会根据任务状态展示进度或结果。
    setTask({ step: 'progress', runId })
    setSection('new')
  }

  return (
    <div className="shell">
      {/* Animated background (shared across all views) */}
      <div className="bg-grid" />
      <div className="bg-glow" />
      <div className="floating-symbols">
        {SYMBOLS.map((s, i) => (
          <span key={i}>{s}</span>
        ))}
      </div>

      {/* 侧边导航栏：仅在非首页展示（首页是落地页，不显示导航） */}
      {section !== 'home' && (
        <Sidebar
          section={section}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed((c) => !c)}
          onHome={() => setSection('home')}
          onNew={startNew}
          onBrainstorm={() => setSection('brainstorm')}
          onHistory={() => setSection('history')}
          onApi={() => setSection('api')}
          onDocs={() => setSection('docs')}
        />
      )}

      <main
        className={`content ${
          section === 'home'
            ? 'content--full'
            : sidebarCollapsed
              ? 'content--collapsed'
              : ''
        }`}
      >
        {section === 'home' && <Home onStart={startNew} onDocs={() => setSection('docs')} />}
        {section === 'new' && (
          <NewTask task={task} setTask={setTask} onHistory={() => setSection('history')} />
        )}
        {section === 'brainstorm' && <Brainstorm />}
        {section === 'history' && <History onOpen={openFromHistory} />}
        {section === 'api' && <ApiManager onUsed={() => startNew()} />}
        {section === 'docs' && <Docs />}
      </main>
    </div>
  )
}
