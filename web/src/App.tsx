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
import KnowledgeBaseStats from './pages/KnowledgeBaseStats'
import ChunkEmbedding, { type ChunkEmbeddingOptions } from './pages/ChunkEmbedding'
import ChunkEmbeddingProgress from './pages/ChunkEmbeddingProgress'
import VectorRetrievalReady from './pages/VectorRetrievalReady'
import KnowledgeBaseHistory from './pages/KnowledgeBaseHistory'

type Section = 'home' | 'modeling' | 'brainstorm' | 'api' | 'docs'
type TaskStep = 'submit' | 'progress' | 'result'
type ModelingView = 'overview' | 'new' | 'history'
type BrainstormView = 'overview' | 'knowledge' | 'stats' | 'chunking' | 'chunking-progress' | 'retrieval-ready' | 'inspiration' | 'history'

const SYMBOLS = ['∫', '∑', '∏', '∂', '∇', '∞', 'π', 'σ', 'μ', 'λ', 'α', 'β', 'γ', 'θ', 'Δ', 'Ω']

export default function App() {
  const [section, setSection] = useState<Section>('home')
  const [modelingView, setModelingView] = useState<ModelingView>('overview')
  const [brainstormView, setBrainstormView] = useState<BrainstormView>('overview')
  const [chunkEmbeddingOptions, setChunkEmbeddingOptions] = useState<ChunkEmbeddingOptions>({
    strategy: 'semantic',
    chunkSize: 800,
    overlap: 100,
  })
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
      // 资料统计页返回知识库维护页；分块设置页返回资料统计页；执行页返回设置页。
      if (brainstormView === 'stats') {
        setBrainstormView('knowledge')
      } else if (brainstormView === 'chunking') {
        setBrainstormView('stats')
      } else if (brainstormView === 'chunking-progress') {
        setBrainstormView('chunking')
      } else if (brainstormView === 'retrieval-ready') {
        setBrainstormView('chunking-progress')
      } else {
        setBrainstormView('overview')
      }
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
            onHistory={() => setBrainstormView('history')}
          />
        )}
        {section === 'brainstorm' && brainstormView === 'knowledge' && (
          <KnowledgeBase onNext={() => setBrainstormView('stats')} />
        )}
        {section === 'brainstorm' && brainstormView === 'stats' && (
          <KnowledgeBaseStats
            onBack={() => setBrainstormView('knowledge')}
            onNext={() => setBrainstormView('chunking')}
          />
        )}
        {section === 'brainstorm' && brainstormView === 'chunking' && (
          <ChunkEmbedding
            onBack={() => setBrainstormView('stats')}
            onNext={(options) => {
              setChunkEmbeddingOptions(options)
              setBrainstormView('chunking-progress')
            }}
            initialOptions={chunkEmbeddingOptions}
          />
        )}
        {section === 'brainstorm' && brainstormView === 'chunking-progress' && (
          <ChunkEmbeddingProgress
            options={chunkEmbeddingOptions}
            onBack={() => setBrainstormView('chunking')}
            onNext={() => setBrainstormView('retrieval-ready')}
          />
        )}
        {section === 'brainstorm' && brainstormView === 'retrieval-ready' && (
          <VectorRetrievalReady onBack={() => setBrainstormView('chunking-progress')} />
        )}
        {section === 'brainstorm' && brainstormView === 'inspiration' && <Brainstorm />}
        {section === 'brainstorm' && brainstormView === 'history' && <KnowledgeBaseHistory />}
        {section === 'modeling' && modelingView === 'history' && <History onOpen={openFromHistory} />}
        {section === 'api' && <ApiManager onUsed={() => startNew()} />}
        {section === 'docs' && <Docs />}
      </main>
    </div>
  )
}
