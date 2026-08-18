import { useEffect, useState } from 'react'

import { getKnowledgeStatus, type KnowledgeDocument } from '../api'

type Strategy = 'semantic' | 'fixed'

export type ChunkEmbeddingOptions = {
  strategy: Strategy
  chunkSize: number
  overlap: number
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

export default function ChunkEmbedding({
  onBack,
  onNext,
  initialOptions,
}: {
  onBack: () => void
  onNext: (options: ChunkEmbeddingOptions) => void
  initialOptions: ChunkEmbeddingOptions
}) {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [strategy, setStrategy] = useState<Strategy>(initialOptions.strategy)
  const [chunkSize, setChunkSize] = useState(initialOptions.chunkSize)
  const [overlap, setOverlap] = useState(initialOptions.overlap)

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

  return (
    <div className="page chunk-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">分块与嵌入设置</h1>
          <p className="page-sub">配置分块策略与嵌入模型，然后进入执行页面开始处理。</p>
        </div>
      </div>

      {/* 流程步骤指示 */}
      <div className="ce-steps">
        <div className="ce-step ce-step-done">
          <span className="ce-step-dot">✓</span>
          <span>上传与转换</span>
        </div>
        <div className="ce-step ce-step-done">
          <span className="ce-step-dot">✓</span>
          <span>资料统计</span>
        </div>
        <div className="ce-step ce-step-current">
          <span className="ce-step-dot">3</span>
          <span>分块与嵌入设置</span>
        </div>
        <div className="ce-step">
          <span className="ce-step-dot">4</span>
          <span>执行分块与嵌入</span>
        </div>
        <div className="ce-step">
          <span className="ce-step-dot">5</span>
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
          </div>
        </div>
      </div>

      <div className="kb-actions">
        <button className="api-btn" onClick={onBack}>上一步</button>
        <button
          className="api-btn primary"
          disabled={documents.length === 0 || loading}
          onClick={() => onNext({ strategy, chunkSize, overlap })}
        >
          下一步
        </button>
      </div>
    </div>
  )
}
