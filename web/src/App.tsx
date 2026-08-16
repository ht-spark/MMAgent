import { useEffect, useState } from 'react'
import Sidebar from './components/Sidebar'
import { syncApiSettingsCache } from './api'
import Home from './pages/Home'
import NewTask from './pages/NewTask'
import History from './pages/History'
import ApiManager from './pages/ApiManager'
import Brainstorm from './pages/Brainstorm'
import Docs from './pages/Docs'
import ModelingTasks from './pages/ModelingTasks'
import BrainstormHub from './pages/BrainstormHub'
import KnowledgeBase from './pages/KnowledgeBase'
import ChunkEmbedding from './pages/ChunkEmbedding'

type Section = 'home' | 'modeling' | 'brainstorm' | 'api' | 'docs'
type TaskStep = 'submit' | 'progress' | 'result'
type ModelingView = 'overview' | 'new' | 'history'
type BrainstormView = 'overview' | 'knowledge' | 'chunking' | 'inspiration'

const SYMBOLS = ['∫', '∑', '∏', '∂', '∇', '∞', 'π', 'σ', 'μ', 'λ', 'α', 'β', 'γ', 'θ', 'Δ', 'Ω']

export default function App() {
  const [section, setSection] = useState<Section>('home')
  const [modelingView, setModelingView] = useState<ModelingView>('overview')
  const [brainstormView, setBrainstormView] = useState<BrainstormView>('overview')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [task, setTask] = useState<{ step: TaskStep; runId: string | null }>({
    step: 'submit',
    runId: null,
  })

  // 启动时把后端本地文件中的 API 配置同步进浏览器缓存，
  // 换浏览器/端口或清缓存后无需重新设置。
  useEffect(() => {
    void syncApiSettingsCache()
  }, [])

  function enterModeling() {
    // 落地页“开始建模”：先进入建模任务总览（新建任务 / 历史任务）
    setSection('modeling')
    setModelingView('overview')
  }

  function startNew() {
    setTask({ step: 'submit', runId: null })
    setSection('modeling')
    setModelingView('new')
  }

  function openFromHistory(runId: string) {
    // 所有历史任务都先恢复聊天上下文；ChatModeling 会根据任务状态展示进度或结果。
    setTask({ step: 'progress', runId })
    setSection('modeling')
    setModelingView('new')
  }

  function goBack() {
    if (section === 'modeling' && modelingView !== 'overview') {
      setModelingView('overview')
      return
    }
    if (section === 'brainstorm' && brainstormView !== 'overview') {
      // 分块与嵌入页返回知识库维护页，其余子页返回头脑风暴总览
      setBrainstormView(brainstormView === 'chunking' ? 'knowledge' : 'overview')
      return
    }
    setSection('home')
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
          onModeling={() => {
            setSection('modeling')
            setModelingView('overview')
          }}
          onBrainstorm={() => {
            setSection('brainstorm')
            setBrainstormView('overview')
          }}
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
        {section !== 'home' && (
          <button className="page-back-button" onClick={goBack} aria-label="返回上一级" title="返回上一级">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M19 12H5" />
              <path d="m12 19-7-7 7-7" />
            </svg>
          </button>
        )}
        {section === 'home' && <Home onStart={enterModeling} onDocs={() => setSection('docs')} />}
        {section === 'modeling' && modelingView === 'overview' && (
          <ModelingTasks onNew={startNew} onHistory={() => setModelingView('history')} />
        )}
        {section === 'modeling' && modelingView === 'new' && (
          <NewTask task={task} setTask={setTask} onHistory={() => setModelingView('history')} />
        )}
        {section === 'brainstorm' && brainstormView === 'overview' && (
          <BrainstormHub
            onKnowledge={() => setBrainstormView('knowledge')}
            onInspiration={() => setBrainstormView('inspiration')}
          />
        )}
        {section === 'brainstorm' && brainstormView === 'knowledge' && (
          <KnowledgeBase onNext={() => setBrainstormView('chunking')} />
        )}
        {section === 'brainstorm' && brainstormView === 'chunking' && (
          <ChunkEmbedding onBack={() => setBrainstormView('knowledge')} />
        )}
        {section === 'brainstorm' && brainstormView === 'inspiration' && <Brainstorm />}
        {section === 'modeling' && modelingView === 'history' && <History onOpen={openFromHistory} />}
        {section === 'api' && <ApiManager onUsed={() => startNew()} />}
        {section === 'docs' && <Docs />}
      </main>
    </div>
  )
}
