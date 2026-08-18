import { useEffect, useState } from 'react'

import {
  chunkAndEmbedKnowledge,
  getKnowledgeChunkEmbedProgress,
  getKnowledgeStatus,
  type KnowledgeDocument,
} from '../api'
import type { ChunkEmbeddingOptions } from './ChunkEmbedding'
import { formatKnowledgeDocumentId } from '../knowledgeDocumentId'

type Stage = 'pending' | 'chunking' | 'embedding' | 'done'

interface DocProgress {
  stage: Stage
  chunks: number
}

const PAGE_SIZE = 10

const STAGE_LABEL: Record<Stage, string> = {
  pending: '待处理',
  chunking: '分块中…',
  embedding: '嵌入中…',
  done: '完成',
}

function estimate_chars(name: string): number {
  const ext = name.toLowerCase().split('.').pop() ?? ''
  if (ext === 'pdf') return 12000
  if (ext === 'docx' || ext === 'doc') return 9000
  if (ext === 'md') return 6000
  if (ext === 'xlsx' || ext === 'xls' || ext === 'csv') return 3000
  return 4000
}

export default function ChunkEmbeddingProgress({
  options,
  onBack,
  onNext,
}: {
  options: ChunkEmbeddingOptions
  onBack: () => void
  onNext: () => void
}) {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)
  const [progressMap, setProgressMap] = useState<Record<string, DocProgress>>({})
  const [currentPage, setCurrentPage] = useState(1)

  useEffect(() => {
    getKnowledgeStatus()
      .then((status) => setDocuments(status.documents))
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '无法连接知识库服务。'))
      .finally(() => setLoading(false))
  }, [])

  function estimateChunks(doc: KnowledgeDocument): number {
    const step = Math.max(options.chunkSize - options.overlap, 1)
    const factor = options.strategy === 'semantic' ? 1.25 : 1
    return Math.max(1, Math.round((estimate_chars(doc.name) / step) * factor))
  }

  const totalChunks = documents.reduce((sum, doc) => sum + estimateChunks(doc), 0)
  const doneCount = Object.values(progressMap).filter((progress) => progress.stage === 'done').length
  const finished = documents.length > 0 && doneCount === documents.length && !running
  const totalPages = Math.max(1, Math.ceil(documents.length / PAGE_SIZE))
  const safePage = Math.min(currentPage, totalPages)
  const paginatedDocuments = documents.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)

  useEffect(() => {
    setCurrentPage((page) => Math.min(page, totalPages))
  }, [totalPages])

  async function startProcessing() {
    if (documents.length === 0 || running) return
    setRunning(true)
    setError('')
    setProgressMap({})
    let polling = true
    const refreshProgress = async () => {
      try {
        const progress = await getKnowledgeChunkEmbedProgress()
        if (!polling || (progress.stage !== 'chunking' && progress.stage !== 'embedding')) return
        setProgressMap(
          Object.fromEntries(
            documents.map((doc) => [doc.id, { stage: progress.stage, chunks: estimateChunks(doc) }]),
          ),
        )
      } catch {
        // The processing request remains the source of truth for failures.
      }
    }
    const progressTimer = window.setInterval(() => void refreshProgress(), 400)
    void refreshProgress()
    try {
      const result = await chunkAndEmbedKnowledge()
      setProgressMap(
        Object.fromEntries(
          documents.map((doc) => {
            const chunks = result.document_chunks[doc.id] ?? estimateChunks(doc)
            return [doc.id, { stage: 'done', chunks }]
          }),
        ),
      )
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '分块与嵌入失败。')
      setProgressMap({})
    } finally {
      polling = false
      window.clearInterval(progressTimer)
      setRunning(false)
    }
  }

  return (
    <div className="page chunk-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">执行分块与嵌入</h1>
          <p className="page-sub">确认设置后，开始将知识库文档转化为可检索向量。</p>
        </div>
      </div>

      <div className="ce-steps">
        <div className="ce-step ce-step-done"><span className="ce-step-dot">✓</span><span>上传与转换</span></div>
        <div className="ce-step ce-step-done"><span className="ce-step-dot">✓</span><span>资料统计</span></div>
        <div className="ce-step ce-step-done"><span className="ce-step-dot">✓</span><span>分块与嵌入设置</span></div>
        <div className="ce-step ce-step-current"><span className="ce-step-dot">4</span><span>执行分块与嵌入</span></div>
        <div className="ce-step"><span className="ce-step-dot">5</span><span>向量检索就绪</span></div>
      </div>

      {error && <div className="err-box">{error}</div>}

      <div className="ce-table-section">
        <div className="kb-table-head">
          <h2>处理进度</h2>
          <span className="kb-table-count">
            {loading ? '读取中…' : `共 ${documents.length} 份 · 预估 ${totalChunks} 块 · 已完成 ${doneCount}`}
          </span>
        </div>
        <div className="kb-table-wrapper">
          <table className="kb-table">
            <thead><tr><th className="kb-col-id">ID</th><th className="kb-col-name">文件名</th><th className="ce-col-strategy">分块策略</th><th className="ce-col-chunks">分块数（预估）</th><th className="kb-col-status">处理状态</th></tr></thead>
            <tbody>
              {!loading && documents.length === 0 && <tr><td colSpan={5} className="kb-empty-row">暂无文档，请先返回上一步上传文件</td></tr>}
              {paginatedDocuments.map((doc) => {
                const progress = progressMap[doc.id]
                return (
                  <tr key={doc.id}>
                    <td className="kb-col-id" title={doc.id}>{formatKnowledgeDocumentId(doc.id)}</td>
                    <td className="kb-col-name" title={doc.name}>{doc.name}</td>
                    <td className="ce-col-strategy">{options.strategy === 'semantic' ? '标题语义分块' : '固定长度分块'}</td>
                    <td className="ce-col-chunks">{progress?.chunks ?? estimateChunks(doc)}</td>
                    <td className="kb-col-status">
                      {!progress || progress.stage === 'pending' ? <span className="kb-tag kb-tag-normal">待处理</span> : progress.stage === 'done' ? <span className="kb-tag kb-tag-success">完成</span> : <span className="ce-inline-progress"><span className="ce-mini-spinner" />{STAGE_LABEL[progress.stage]}</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {documents.length > 0 && (
          <div className="kb-pagination">
            <button className="kb-page-btn" disabled={safePage <= 1} onClick={() => setCurrentPage((page) => Math.max(page - 1, 1))}>上一页</button>
            <span className="kb-page-info">第 {safePage} / {totalPages} 页</span>
            <button className="kb-page-btn" disabled={safePage >= totalPages} onClick={() => setCurrentPage((page) => Math.min(page + 1, totalPages))}>下一页</button>
          </div>
        )}

        <div className="kb-actions">
          <button className="api-btn" onClick={onBack} disabled={running}>上一步</button>
          <button className="api-btn primary" disabled={documents.length === 0 || running} onClick={startProcessing}>
            {running ? '处理中…' : '执行分块与嵌入'}
          </button>
          <button className="api-btn" disabled={!finished || running} onClick={onNext}>下一步</button>
        </div>
      </div>
    </div>
  )
}
