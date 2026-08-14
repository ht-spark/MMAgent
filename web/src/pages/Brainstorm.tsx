import { useState } from 'react'

import { sendBrainstormMessage } from '../api'

type Message = { role: 'assistant' | 'user'; content: string }

export default function Brainstorm() {
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content: '欢迎来到灵感迸发。输入建模问题、已有假设或待分析的方向，我们一起梳理可能的建模思路。',
    },
  ])

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
        { role: 'assistant', content: error instanceof Error ? error.message : '头脑风暴服务暂不可用。' },
      ])
    }
  }

  return (
    <div className="page page-fill brainstorm-page inspiration-page">
      <header className="page-head">
        <div>
          <h1 className="page-title">灵感迸发</h1>
          <p className="page-sub">围绕建模问题梳理假设、变量与可行的分析方向。</p>
        </div>
        <span className="brainstorm-status">RAG 引擎待配置</span>
      </header>

      <section className="brainstorm-chat" aria-label="灵感迸发对话">
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
  )
}
