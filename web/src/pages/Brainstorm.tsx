import { useEffect, useState } from 'react'

import { fetchBrainstormDiscussion, type BrainstormSource, sendBrainstormMessage } from '../api'
import MarkdownContent from '../components/MarkdownContent'

type Message = { role: 'assistant' | 'user'; content: string; sources?: BrainstormSource[] }

const WELCOME_MESSAGE: Message = {
  role: 'assistant',
  content: '你好，我是 MMAgent 灵感助手。请输入建模问题、已有假设或分析方向，我会从知识库检索相关片段供你梳理建模思路。',
}

export default function Brainstorm({ discussionId, onDiscussionId }: {
  discussionId: string | null
  onDiscussionId: (discussionId: string) => void
}) {
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<Message[]>([WELCOME_MESSAGE])
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    if (!discussionId) {
      setMessages([WELCOME_MESSAGE])
      return
    }
    void fetchBrainstormDiscussion(discussionId)
      .then((discussion) => setMessages(discussion.messages))
      .catch((error) => setMessages([
        WELCOME_MESSAGE,
        { role: 'assistant', content: error instanceof Error ? error.message : '加载讨论记录失败。' },
      ]))
  }, [discussionId])

  async function submit() {
    const message = draft.trim()
    if (!message || isSubmitting) return
    setDraft('')
    setIsSubmitting(true)
    setMessages((current) => [...current, { role: 'user', content: message }])
    try {
      const response = await sendBrainstormMessage(message, discussionId)
      onDiscussionId(response.discussion_id)
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: response.message, sources: response.sources },
      ])
    } catch (error) {
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: error instanceof Error ? error.message : '头脑风暴服务暂不可用。' },
      ])
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="page page-fill brainstorm-page inspiration-page inspiration-chat-page">
      <div className="inspiration-chat-title">
        <strong>灵感讨论</strong>
        <span>RAG 混合检索与压缩已接入</span>
      </div>
      <section className="brainstorm-chat" aria-label="灵感迸发对话">
        <div className="brainstorm-messages">
          {messages.map((message, index) => (
            <div className={`brainstorm-message-row ${message.role}`} key={`${message.role}-${index}`}>
              {message.role === 'assistant' && <span className="brainstorm-avatar">M</span>}
              <div className={`brainstorm-message ${message.role}`}>
                {message.role === 'assistant' ? <MarkdownContent content={message.content} /> : message.content}
                {message.sources && message.sources.length > 0 && (
                  <details className="brainstorm-sources">
                    <summary>参考窗口（{message.sources.length} 条）</summary>
                    {message.sources.map((source, sourceIndex) => (
                      <div className="brainstorm-source" key={`${source.document_id}-${sourceIndex}`}>
                        <strong>{source.source_file}</strong>
                        <MarkdownContent content={source.content} />
                      </div>
                    ))}
                  </details>
                )}
              </div>
            </div>
          ))}
          {isSubmitting && (
            <div className="brainstorm-message-row assistant">
              <span className="brainstorm-avatar">M</span>
              <div className="brainstorm-message assistant">正在检索资料、压缩上下文并生成回答…</div>
            </div>
          )}
        </div>
        <div className="brainstorm-composer">
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="输入待讨论的建模问题、假设或分析方向…" rows={2} />
          <div>
            <span>优先检索并压缩知识库上下文；知识库为空时直接与当前模型讨论。</span>
            <button className="api-btn primary" onClick={submit} disabled={!draft.trim() || isSubmitting}>
              {isSubmitting ? '讨论中…' : '讨论'}
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
