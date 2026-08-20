import { useEffect, useRef, useState } from 'react'

import { fetchBrainstormDiscussion, renameBrainstormDiscussion, streamBrainstormMessage, type BrainstormSource } from '../api'
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
  const [files, setFiles] = useState<File[]>([])
  const [title, setTitle] = useState('新讨论')
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!discussionId) {
      setMessages([WELCOME_MESSAGE])
      setTitle('新讨论')
      return
    }
    void fetchBrainstormDiscussion(discussionId)
      .then((discussion) => {
        setMessages(discussion.messages)
        setTitle(discussion.title)
      })
      .catch((error) => setMessages([
        WELCOME_MESSAGE,
        { role: 'assistant', content: error instanceof Error ? error.message : '加载讨论记录失败。' },
      ]))
  }, [discussionId])

  async function submit() {
    const message = draft.trim()
    if ((!message && files.length === 0) || isSubmitting) return
    setDraft('')
    setIsSubmitting(true)
    const attachedFiles = files
    setFiles([])
    if (fileInputRef.current) fileInputRef.current.value = ''
    setMessages((current) => [
      ...current,
      { role: 'user', content: message },
      { role: 'assistant', content: '' },
    ])
    try {
      await streamBrainstormMessage(message, discussionId, title, attachedFiles, {
        onSources: (sources) => setMessages((current) => current.map(
          (item, index) => index === current.length - 1 ? { ...item, sources } : item,
        )),
        onToken: (content) => {
          setMessages((current) => current.map(
            (item, index) => index === current.length - 1
              ? { ...item, content: `${item.content}${content}` }
              : item,
          ))
        },
        onDone: onDiscussionId,
      })
    } catch (error) {
      setMessages((current) => [
        ...current.slice(0, -1),
        { role: 'assistant', content: error instanceof Error ? error.message : '头脑风暴服务暂不可用。' },
      ])
    } finally {
      setIsSubmitting(false)
    }
  }

  async function saveTitle() {
    const normalizedTitle = title.trim() || '新讨论'
    setTitle(normalizedTitle)
    if (discussionId) await renameBrainstormDiscussion(discussionId, normalizedTitle)
  }

  return (
    <div className="page page-fill brainstorm-page inspiration-page inspiration-chat-page">
      <div className="inspiration-chat-title">
        <input
          className="discussion-title-input"
          value={title}
          maxLength={80}
          onChange={(event) => setTitle(event.target.value)}
          onBlur={() => void saveTitle()}
          aria-label="讨论名称"
        />
        <span>RAG 混合检索与压缩已接入</span>
      </div>
      <section className="brainstorm-chat" aria-label="灵感迸发对话">
        <div className="brainstorm-messages">
          {messages.map((message, index) => message.content && (
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
        </div>
        <div className="brainstorm-composer">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                void submit()
              }
            }}
            placeholder="输入待讨论的建模问题、假设或分析方向…"
            rows={2}
          />
          <div>
            <input
              ref={fileInputRef}
              className="brainstorm-file-input"
              type="file"
              multiple
              accept=".md,.markdown,.txt,.json,.csv,.xlsx,.xlsm,.png,.jpg,.jpeg,.webp,.gif"
              onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
            />
            <button className="api-btn" onClick={() => fileInputRef.current?.click()} disabled={isSubmitting}>
              上传文件{files.length ? `（${files.length}）` : ''}
            </button>
            <button className="api-btn primary" onClick={submit} disabled={(!draft.trim() && files.length === 0) || isSubmitting}>
              {isSubmitting ? '讨论中…' : '讨论'}
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
