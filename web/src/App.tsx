import { useState } from 'react'
import Sidebar from './components/Sidebar'
import Home from './pages/Home'
import NewTask from './pages/NewTask'
import History from './pages/History'
import ApiManager from './pages/ApiManager'

type Section = 'home' | 'new' | 'history' | 'api'
type TaskStep = 'submit' | 'progress' | 'result'

const SYMBOLS = ['∫', '∑', '∏', '∂', '∇', '∞', 'π', 'σ', 'μ', 'λ', 'α', 'β', 'γ', 'θ', 'Δ', 'Ω']

export default function App() {
  const [section, setSection] = useState<Section>('home')
  const [task, setTask] = useState<{ step: TaskStep; runId: string | null }>({
    step: 'submit',
    runId: null,
  })

  function startNew() {
    setTask({ step: 'submit', runId: null })
    setSection('new')
  }

  function openFromHistory(runId: string) {
    setTask({ step: 'result', runId })
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
          onHome={() => setSection('home')}
          onNew={startNew}
          onHistory={() => setSection('history')}
          onApi={() => setSection('api')}
        />
      )}

      <main className={`content ${section === 'home' ? 'content--full' : ''}`}>
        {section === 'home' && <Home onStart={startNew} />}
        {section === 'new' && (
          <NewTask task={task} setTask={setTask} onHistory={() => setSection('history')} />
        )}
        {section === 'history' && <History onOpen={openFromHistory} />}
        {section === 'api' && <ApiManager onUsed={() => startNew()} />}
      </main>
    </div>
  )
}
