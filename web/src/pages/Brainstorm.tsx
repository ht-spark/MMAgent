import { useEffect, useRef, useState } from 'react'

import {
  getKnowledgeStatus,
  sendBrainstormMessage,
  type KnowledgeDocument,
  uploadKnowledgeDocument,
} from '../api'

type Message = { role: 'assistant' | 'user'; content: string }

export default function Brainstorm() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content: '知识库工作台已就绪。上传领域资料后，可在这里讨论建模思路；检索与 LLM 对话将在 RAG 引擎接入后启用。',
    },
  ])
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    getKnowledgeStatus()
      .then((status) => setDocuments(status.documents))
      .catch((error: unknown) => {
        setMessages((current) => [
          ...current,
          { role: 'assistant', content: error instanceof Error ? error.message : '无法连接知识库服务。' },
        ])
      })
      .finally(() => setLoading(false))
  }, [])

  async function upload(file: File | undefined) {
    if (!file) return
    setUploading(true)
    try {
      const prepared = await uploadKnowledgeDocument(file)
      setDocuments((current) => [
        ...current.filter((item) => !prepared.some((document) => document.name === item.name)),
        ...prepared,
      ])
    } catch (error) {
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: error instanceof Error ? error.message : '文档上传失败。' },
      ])
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  async function submit() {
    const message = draft.trim()
    if (!message) return
    setDraft('')
    setMessages((current) => [...current, { role: 'user', content: message }])
    try {
      await sendBrainstormMessage(message)
    } catch (error) {
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: error instanceof Error ? error.message : '头脑风暴服务不可用。' },
      ])
    }
  }

  return (
    <div className="page page-fill brainstorm-page">
      <header className="page-head">
        <div>
          <h1 className="page-title">头脑风暴</h1>
          <p className="page-sub">围绕专用资料梳理建模思路，并在后续交接给任务智能体。</p>
        </div>
        <span className="brainstorm-status">RAG 引擎待配置</span>
      </header>

      <div className="brainstorm-layout">
        <aside className="knowledge-panel">
          <div className="knowledge-panel-head">
            <div>
              <h2>知识文档</h2>
              <p>{loading ? '正在读取…' : `已归档 ${documents.length} 份`}</p>
            </div>
            <button className="icon-action" onClick={() => fileInput.current?.click()} disabled={uploading} title="上传知识文档" aria-label="上传知识文档">
              +
            </button>
            <input ref={fileInput} type="file" hidden onChange={(event) => upload(event.target.files?.[0])} />
          </div>
          <div className="knowledge-list">
            {!loading && documents.length === 0 && <p className="muted">暂无文档</p>}
            {documents.map((document) => (
              <div className="knowledge-item" key={document.name}>
                <strong>{document.name}</strong>
                <span>{Math.max(1, Math.round(document.size_bytes / 1024))} KB</span>
              </div>
            ))}
          </div>
        </aside>

        <section className="brainstorm-chat" aria-label="知识库头脑风暴对话">
          <div className="brainstorm-messages">
            {messages.map((message, index) => (
              <div className={`brainstorm-message ${message.role}`} key={`${message.role}-${index}`}>
                {message.content}
              </div>
            ))}
          </div>
          <div className="brainstorm-composer">
            <textarea value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="输入待讨论的建模问题、假设或分析方向…" rows={4} />
            <div>
              <span>检索与引用将在 RAG 引擎接入后生成。</span>
              <button className="api-btn primary" onClick={submit} disabled={!draft.trim()}>讨论</button>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
