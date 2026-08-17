import { useEffect, useMemo, useState } from 'react'

import { getKnowledgeStatus, type KnowledgeDocument } from '../api'

type DocKind = 'original-markdown' | 'converted' | 'not-ready'

interface CategorizedDoc extends KnowledgeDocument {
  kind: DocKind
}

const KIND_LABEL: Record<DocKind, string> = {
  'original-markdown': '原始 Markdown',
  converted: '转换后 Markdown',
  'not-ready': '待转换',
}

const KIND_TAG_CLASS: Record<DocKind, string> = {
  'original-markdown': 'kb-tag-unknown',
  converted: 'kb-tag-success',
  'not-ready': 'kb-tag-normal',
}

export default function KnowledgeBaseStats({
  onBack,
  onNext,
}: {
  onBack: () => void
  onNext: () => void
}) {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    getKnowledgeStatus()
      .then((status) => setDocuments(status.documents))
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '无法连接知识库服务。'))
      .finally(() => setLoading(false))
  }, [])

  const categorized = useMemo<CategorizedDoc[]>(() => {
    return documents.map((doc) => {
      let kind: DocKind = 'not-ready'
      if (doc.is_markdown) kind = 'original-markdown'
      else if (doc.is_conversion) kind = 'converted'
      return { ...doc, kind }
    })
  }, [documents])

  const usableDocs = categorized.filter((doc) => doc.kind !== 'not-ready')
  const originalMarkdownCount = usableDocs.filter((doc) => doc.kind === 'original-markdown').length
  const convertedCount = usableDocs.filter((doc) => doc.kind === 'converted').length
  const notReadyCount = categorized.length - usableDocs.length

  return (
    <div className="page chunk-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">资料统计</h1>
          <p className="page-sub">汇总可用于分块与入库的资料，确认原始 Markdown 与转换后文档。</p>
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
          <span>资料统计</span>
        </div>
        <div className="ce-step">
          <span className="ce-step-dot">3</span>
          <span>分块与嵌入</span>
        </div>
        <div className="ce-step">
          <span className="ce-step-dot">4</span>
          <span>向量检索就绪</span>
        </div>
      </div>

      {error && <div className="err-box">{error}</div>}

      {/* 统计摘要 */}
      <div className="ce-summary">
        <div>
          <span className="ce-summary-num">{usableDocs.length}</span>
          <span className="ce-summary-label">可入库资料</span>
        </div>
        <div>
          <span className="ce-summary-num">{originalMarkdownCount}</span>
          <span className="ce-summary-label">原始 Markdown</span>
        </div>
        <div>
          <span className="ce-summary-num">{convertedCount}</span>
          <span className="ce-summary-label">转换后 Markdown</span>
        </div>
        <div>
          <span className="ce-summary-num">{notReadyCount}</span>
          <span className="ce-summary-label">待转换</span>
        </div>
      </div>

      {/* 资料明细表格 */}
      <div className="ce-table-section" style={{ marginTop: '20px' }}>
        <div className="kb-table-head">
          <h2>资料明细</h2>
          <span className="kb-table-count">
            {loading ? '读取中…' : `共 ${documents.length} 份 · 可入库 ${usableDocs.length}`}
          </span>
        </div>

        <div className="kb-table-wrapper">
          <table className="kb-table">
            <thead>
              <tr>
                <th className="kb-col-id">ID</th>
                <th className="kb-col-name">文件名</th>
                <th className="kb-col-status">来源类型</th>
                <th className="kb-col-status">上传状态</th>
                <th className="kb-col-status">转换状态</th>
              </tr>
            </thead>
            <tbody>
              {!loading && categorized.length === 0 && (
                <tr>
                  <td colSpan={5} className="kb-empty-row">
                    暂无文档，请先返回上一步上传文件
                  </td>
                </tr>
              )}
              {categorized.map((doc, index) => (
                <tr key={doc.id}>
                  <td className="kb-col-id">{index + 1}</td>
                  <td className="kb-col-name" title={doc.name}>
                    {doc.name}
                  </td>
                  <td className="kb-col-status">
                    <span className={`kb-tag ${KIND_TAG_CLASS[doc.kind]}`}>{KIND_LABEL[doc.kind]}</span>
                  </td>
                  <td className="kb-col-status">
                    {doc.upload_success ? (
                      <span className="kb-tag kb-tag-success">成功</span>
                    ) : (
                      <span className="kb-tag kb-tag-fail">失败</span>
                    )}
                  </td>
                  <td className="kb-col-status">
                    {doc.is_markdown ? (
                      <span className="kb-tag kb-tag-normal">—</span>
                    ) : doc.is_conversion ? (
                      <span className="kb-tag kb-tag-success">已转换</span>
                    ) : (
                      <span className="kb-tag kb-tag-normal">未转换</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="kb-actions">
          <button className="api-btn" onClick={onBack}>
            返回上一步
          </button>
          <button className="api-btn primary" disabled={usableDocs.length === 0} onClick={onNext}>
            进入分块与嵌入
          </button>
        </div>
      </div>
    </div>
  )
}
