import { useEffect, useState } from 'react'

import {
  chunkAndEmbedKnowledge,
  getKnowledgeStatus,
  type KnowledgeDocument,
} from '../api'

type Strategy = 'semantic' | 'fixed'
type Stage = 'pending' | 'chunking' | 'embedding' | 'done'

interface DocProgress {
  stage: Stage
  chunks: number
  vectors: number
}

const STAGE_LABEL: Record<Stage, string> = {
  pending: '待处理',
  chunking: '分块中…',
  embedding: '嵌入中…',
  done: '完成',
}

/** 按扩展名估算文档字符量（仅用于前端预估分块数，实际值以后端执行结果为准）。 */
function estimateChars(name: string): number {
  const ext = name.toLowerCase().split('.').pop() ?? ''
  if (ext === 'pdf') return 12000
  if (ext === 'docx' || ext === 'doc') return 9000
  if (ext === 'md') return 6000
  if (ext === 'xlsx' || ext === 'xls' || ext === 'csv') return 3000
  return 4000
}

export default function ChunkEmbedding({ onBack }: { onBack: () => void }) {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [strategy, setStrategy] = useState<Strategy>('semantic')
  const [chunkSize, setChunkSize] = useState(800)
  const [overlap, setOverlap] = useState(100)
  const [running, setRunning] = useState(false)
  const [progressMap, setProgressMap] = useState<Record<number, DocProgress>>({})

  useEffect(() => {
    getKnowledgeStatus()
      .then((status) => setDocuments(status.documents))
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '无法连接知识库服务。'))
      .finally(() => setLoading(false))
  }, [])

  function estimateChunks(doc: KnowledgeDocument): number {
    const step = Math.max(chunkSize - overlap, 1)
    const factor = strategy === 'semantic' ? 1.25 : 1
    return Math.max(1, Math.round((estimateChars(doc.name) / step) * factor))
  }

  const totalChunks = documents.reduce((sum, doc) => sum + estimateChunks(doc), 0)

  async function startProcessing() {
    if (documents.length === 0 || running) return
    setRunning(true)
    setError('')
    setProgressMap(
      Object.fromEntries(
        documents.map((doc) => [
          doc.id,
          { stage: 'chunking', chunks: estimateChunks(doc), vectors: 0 },
        ]),
      ),
    )
    try {
      const result = await chunkAndEmbedKnowledge()
      setProgressMap(
        Object.fromEntries(
          documents.map((doc) => {
            const chunks = result.document_chunks[doc.id] ?? estimateChunks(doc)
            return [doc.id, { stage: 'done', chunks, vectors: chunks }]
          }),
        ),
      )
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '分块与嵌入失败。')
      setProgressMap({})
    } finally {
      setRunning(false)
    }
  }

  const doneCount = Object.values(progressMap).filter((p) => p.stage === 'done').length
  const finished = documents.length > 0 && doneCount === documents.length && !running

  return (
    <div className="page chunk-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">分块与嵌入</h1>
          <p className="page-sub">配置分块策略与嵌入模型，将知识库文档转化为可检索向量。</p>
        </div>
      </div>

      {/* 流程步骤指示 */}
      <div className="ce-steps">
        <div className="ce-step ce-step-done">
          <span className="ce-step-dot">✓</span>
          <span>上传与转换</span>
        </div>
        <div className="ce-step ce-step-current">
          <span className="ce-step-dot">2</span>
          <span>分块与嵌入</span>
        </div>
        <div className="ce-step">
          <span className="ce-step-dot">3</span>
          <span>向量检索就绪</span>
        </div>
      </div>

      {error && <div className="err-box">{error}</div>}

      <div className="ce-config-grid">
        {/* 分块设置 */}
        <div className="ce-card">
          <div className="ce-card-head">
            <h2>分块设置</h2>
            <span className="ce-card-hint">预估共 {totalChunks} 个分块</span>
          </div>

          <div className="ce-field">
            <label>分块策略</label>
            <div className="ce-segmented">
              <button
                type="button"
                className={strategy === 'semantic' ? 'ce-seg-active' : ''}
                onClick={() => setStrategy('semantic')}
              >
                按标题语义分块
              </button>
              <button
                type="button"
                className={strategy === 'fixed' ? 'ce-seg-active' : ''}
                onClick={() => setStrategy('fixed')}
              >
                固定长度分块
              </button>
            </div>
            <p className="ce-field-hint">
              {strategy === 'semantic'
                ? '依据 Markdown 标题层级切分，保持语义完整，适合结构化文档。'
                : '按固定字符长度滑窗切分，分块均匀，适合纯文本资料。'}
            </p>
          </div>

          <div className="ce-field">
            <label>
              分块大小
              <span className="ce-field-value">{chunkSize} 字符</span>
            </label>
            <input
              type="range"
              min={200}
              max={2000}
              step={100}
              value={chunkSize}
              onChange={(event) => setChunkSize(Number(event.target.value))}
              disabled={running}
            />
          </div>

          <div className="ce-field">
            <label>
              分块重叠
              <span className="ce-field-value">{overlap} 字符</span>
            </label>
            <input
              type="range"
              min={0}
              max={400}
              step={20}
              value={overlap}
              onChange={(event) => {
                const next = Number(event.target.value)
                setOverlap(next >= chunkSize ? Math.floor(chunkSize / 4) : next)
              }}
              disabled={running}
            />
            <p className="ce-field-hint">相邻分块共享的字符数，缓解关键信息被切断的问题。</p>
          </div>
        </div>

        {/* 嵌入设置 */}
        <div className="ce-card">
          <div className="ce-card-head">
            <h2>嵌入设置</h2>
          </div>

          <div className="ce-field">
            <label>嵌入模型</label>
            <div className="ce-static-value">本地 BAAI/bge-small-zh-v1.5</div>
          </div>

          <div className="ce-field">
            <label>相似度度量</label>
            <div className="ce-static-value">余弦相似度（cosine）</div>
          </div>

          <div className="ce-field">
            <label>向量存储</label>
            <div className="ce-static-value">本地向量索引（随知识库运行目录持久化）</div>
          </div>

          <div className="ce-summary">
            <div>
              <span className="ce-summary-num">{documents.length}</span>
              <span className="ce-summary-label">待处理文档</span>
            </div>
            <div>
              <span className="ce-summary-num">{totalChunks}</span>
              <span className="ce-summary-label">预估分块</span>
            </div>
            <div>
              <span className="ce-summary-num">{doneCount}</span>
              <span className="ce-summary-label">已嵌入</span>
            </div>
          </div>
        </div>
      </div>

      {/* 处理进度表格 */}
      <div className="ce-table-section">
        <div className="kb-table-head">
          <h2>处理进度</h2>
          <span className="kb-table-count">
            {loading
              ? '读取中…'
              : `共 ${documents.length} 份 · 预估 ${totalChunks} 块 · 已完成 ${doneCount}`}
          </span>
        </div>

        <div className="kb-table-wrapper">
          <table className="kb-table">
            <thead>
              <tr>
                <th className="kb-col-id">ID</th>
                <th className="kb-col-name">文件名</th>
                <th className="ce-col-strategy">分块策略</th>
                <th className="ce-col-chunks">分块数（预估）</th>
                <th className="kb-col-status">处理状态</th>
              </tr>
            </thead>
            <tbody>
              {!loading && documents.length === 0 && (
                <tr>
                  <td colSpan={5} className="kb-empty-row">
                    暂无文档，请先返回上一步上传文件
                  </td>
                </tr>
              )}
              {documents.map((doc, index) => {
                const progress = progressMap[doc.id]
                return (
                  <tr key={doc.id}>
                    <td className="kb-col-id">{index + 1}</td>
                    <td className="kb-col-name" title={doc.name}>{doc.name}</td>
                    <td className="ce-col-strategy">
                      {strategy === 'semantic' ? '标题语义分块' : '固定长度分块'}
                    </td>
                    <td className="ce-col-chunks">{progress ? progress.chunks : estimateChunks(doc)}</td>
                    <td className="kb-col-status">
                      {!progress || progress.stage === 'pending' ? (
                        <span className="kb-tag kb-tag-normal">待处理</span>
                      ) : progress.stage === 'done' ? (
                        <span className="kb-tag kb-tag-success">完成</span>
                      ) : (
                        <span className="ce-inline-progress">
                          <span className="ce-mini-spinner" />
                          {STAGE_LABEL[progress.stage]}
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <div className="kb-actions">
          <button className="api-btn" onClick={onBack} disabled={running}>
            返回上一步
          </button>
          <button
            className="api-btn primary"
            disabled={documents.length === 0 || running}
            onClick={startProcessing}
          >
            {running ? '处理中…' : finished ? '重新处理' : '开始分块与嵌入'}
          </button>
          {finished && (
            <button className="api-btn" onClick={onBack}>
              完成并返回
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
