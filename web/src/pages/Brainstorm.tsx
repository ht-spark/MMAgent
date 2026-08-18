import { useState } from 'react'

import { sendBrainstormMessage } from '../api'

type Message = { role: 'assistant' | 'user'; content: string }

export default function Brainstorm() {
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content: '你好，我是 MMAgent 灵感助手。请输入建模问题、已有假设或分析方向，我会协助你梳理可行的建模思路。',
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
    <div className="page page-fill brainstorm-page inspiration-page inspiration-chat-page">
      <div className="inspiration-chat-title">
        <strong>灵感讨论</strong>
        <span>RAG 引擎待配置</span>
      </div>
      <section className="brainstorm-chat" aria-label="灵感迸发对话">
        <div className="brainstorm-messages">
          {messages.map((message, index) => (
            <div className={`brainstorm-message-row ${message.role}`} key={`${message.role}-${index}`}>
              {message.role === 'assistant' && <span className="brainstorm-avatar">M</span>}
              <div className={`brainstorm-message ${message.role}`}>
                {message.content}
              </div>
            </div>
          ))}
        </div>
        <div className="brainstorm-composer">
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="输入待讨论的建模问题、假设或分析方向…" rows={2} />
          <div>
            <span>检索与引用将在 RAG 引擎接入后生成。</span>
            <button className="api-btn primary" onClick={submit} disabled={!draft.trim()}>讨论</button>
          </div>
        </div>
      </section>
    </div>
  )
}
