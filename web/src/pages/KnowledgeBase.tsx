import { useEffect, useRef, useState } from 'react'

import { getKnowledgeStatus, type KnowledgeDocument, uploadKnowledgeDocument } from '../api'

export default function KnowledgeBase() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    getKnowledgeStatus()
      .then((status) => setDocuments(status.documents))
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '无法连接知识库服务。'))
      .finally(() => setLoading(false))
  }, [])

  async function upload(file: File | undefined) {
    if (!file) return
    setUploading(true)
    setError('')
    try {
      const prepared = await uploadKnowledgeDocument(file)
      setDocuments((current) => [
        ...current.filter((item) => !prepared.some((document) => document.name === item.name)),
        ...prepared,
      ])
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '文档上传失败。')
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  return (
    <div className="page knowledge-base-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">知识库维护</h1>
          <p className="page-sub">上传并管理领域资料，为 RAG 检索提供上下文。</p>
        </div>
        <button className="api-btn primary" onClick={() => fileInput.current?.click()} disabled={uploading}>
          {uploading ? '上传中…' : '上传文档'}
        </button>
        <input ref={fileInput} type="file" hidden onChange={(event) => upload(event.target.files?.[0])} />
      </div>

      {error && <div className="err-box">{error}</div>}

      <div className="knowledge-library-card">
        <div className="knowledge-library-head">
          <h2>知识文档</h2>
          <span>{loading ? '正在读取…' : `已归档 ${documents.length} 份`}</span>
        </div>
        {!loading && documents.length === 0 && <p className="muted">暂无文档。上传领域资料后，可在灵感迸发中结合知识库展开讨论。</p>}
        <div className="knowledge-library-list">
          {documents.map((document) => (
            <div className="knowledge-item" key={document.name}>
              <strong>{document.name}</strong>
              <span>{Math.max(1, Math.round(document.size_bytes / 1024))} KB</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
