import { useCallback, useEffect, useRef, useState } from 'react'

import {
  convertKnowledgeDocuments,
  deleteKnowledgeDocuments,
  getKnowledgeStatus,
  type KnowledgeDocument,
  uploadKnowledgeDocument,
} from '../api'
import { appendKnowledgeHistory } from '../knowledgeHistory'

const PAGE_SIZE = 10

export default function KnowledgeBase({ onNext }: { onNext: () => void }) {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([])
  const [currentPage, setCurrentPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [uploadProgress, setUploadProgress] = useState<{ total: number; done: number; currentName: string } | null>(null)
  const [error, setError] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [converting, setConverting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const uploading = uploadProgress !== null

  useEffect(() => {
    getKnowledgeStatus()
      .then((status) =>
        setDocuments(
          status.documents.map((doc, index) => ({
            ...doc,
            id: doc.id ?? index + 1,
            upload_success: doc.upload_success ?? true,
            is_markdown: doc.is_markdown ?? false,
            is_conversion: doc.is_conversion ?? false,
          })),
        ),
      )
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '无法连接知识库服务。'))
      .finally(() => setLoading(false))
  }, [])

  const uploadFiles = useCallback(async (files: FileList | null | undefined) => {
    if (!files || files.length === 0) return
    const fileList = Array.from(files)
    setUploadProgress({ total: fileList.length, done: 0, currentName: fileList[0].name })
    setError('')
    const failedNames: string[] = []
    for (let i = 0; i < fileList.length; i++) {
      const file = fileList[i]
      setUploadProgress((prev) => (prev ? { ...prev, currentName: file.name } : prev))
      try {
        const prepared = await uploadKnowledgeDocument(file)
        setDocuments((current) => [
          ...current.filter((item) => !prepared.some((document) => document.name === item.name)),
          ...prepared.map((doc, index) => ({
            ...doc,
            id: doc.id ?? Date.now() + index,
            upload_success: doc.upload_success ?? true,
            is_markdown: doc.is_markdown ?? false,
            is_conversion: doc.is_conversion ?? false,
          })),
        ])
        appendKnowledgeHistory({
          action: 'upload',
          detail: prepared.map((doc) => doc.name).join('、') || file.name,
          status: 'success',
        })
      } catch (reason) {
        failedNames.push(file.name)
        appendKnowledgeHistory({
          action: 'upload',
          detail: file.name,
          status: 'failure',
        })
      } finally {
        setUploadProgress((prev) => (prev ? { ...prev, done: i + 1 } : prev))
      }
    }
    if (failedNames.length > 0) {
      setError(`${failedNames.length} 个文件上传失败：${failedNames.join('、')}`)
    }
    setCurrentPage(1)
    setUploadProgress(null)
    if (fileInput.current) fileInput.current.value = ''
  }, [])

  function handleDrop(event: React.DragEvent) {
    event.preventDefault()
    setDragOver(false)
    uploadFiles(event.dataTransfer.files)
  }

  function toggleSelect(id: number) {
    setSelectedIds((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSelectAll() {
    if (selectedIds.size === documents.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(documents.map((doc) => doc.id)))
    }
  }

  async function convertFormat() {
    if (selectedIds.size === 0) return
    const documentIds = [...selectedIds]
    setConverting(true)
    setError('')
    try {
      const { converted_ids: convertedIds, failed } = await convertKnowledgeDocuments(documentIds)
      const convertedSet = new Set(convertedIds)
      setDocuments((current) =>
        current.map((doc) =>
          convertedSet.has(doc.id) ? { ...doc, is_conversion: true } : doc,
        ),
      )
      if (failed.length > 0) {
        setError(`${failed.length} 个文件转换失败：${failed.join('、')}`)
        appendKnowledgeHistory({
          action: 'convert',
          detail: `成功 ${convertedIds.length} 个，失败 ${failed.length} 个`,
          status: 'failure',
        })
      } else {
        setSelectedIds(new Set())
        appendKnowledgeHistory({
          action: 'convert',
          detail: `已转换 ${convertedIds.length} 个文件`,
          status: 'success',
        })
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '格式转换失败。')
      appendKnowledgeHistory({
        action: 'convert',
        detail: `尝试转换 ${documentIds.length} 个文件`,
        status: 'failure',
      })
    } finally {
      setConverting(false)
    }
  }

  async function deleteSelected() {
    const documentIds = [...selectedIds]
    if (documentIds.length === 0 || deleting) return
    if (!window.confirm(`确定删除选中的 ${documentIds.length} 份知识库文件吗？`)) return

    setDeleting(true)
    setError('')
    try {
      const { deleted_ids: deletedIds } = await deleteKnowledgeDocuments(documentIds)
      const deletedSet = new Set(deletedIds)
      setDocuments((current) => current.filter((document) => !deletedSet.has(document.id)))
      setSelectedIds(new Set())
      setCurrentPage(1)
      appendKnowledgeHistory({
        action: 'delete',
        detail: `已删除 ${deletedIds.length} 个文件`,
        status: 'success',
      })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '删除知识库文件失败。')
      appendKnowledgeHistory({
        action: 'delete',
        detail: `尝试删除 ${documentIds.length} 个文件`,
        status: 'failure',
      })
    } finally {
      setDeleting(false)
    }
  }

  const successCount = documents.filter((doc) => doc.upload_success).length
  const markdownCount = documents.filter((doc) => doc.is_markdown).length
  const conversionCount = documents.filter((doc) => doc.is_conversion && !doc.is_markdown).length
  const totalPages = Math.max(1, Math.ceil(documents.length / PAGE_SIZE))
  const safePage = Math.min(currentPage, totalPages)
  const paginatedDocuments = documents.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)

  useEffect(() => {
    setCurrentPage((page) => Math.min(page, totalPages))
  }, [totalPages])

  return (
    <div className="page knowledge-base-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">知识库维护</h1>
          <p className="page-sub">上传并管理领域资料，为 RAG 检索提供上下文。</p>
        </div>
      </div>

      {error && <div className="err-box">{error}</div>}

      <div className="kb-layout">
        {/* 顶部：上传文件区域（居中长条） */}
        <div className="kb-upload-section">
          <div
            className={`kb-upload-zone ${dragOver ? 'kb-drag-over' : ''} ${uploading ? 'kb-uploading' : ''}`}
            onDragOver={(event) => {
              event.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => !uploading && fileInput.current?.click()}
          >
            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              onChange={(event) => uploadFiles(event.target.files)}
            />
            {uploading ? (
              <div className="kb-upload-progress">
                <div className="kb-upload-progress-top">
                  <span className="kb-upload-progress-count">
                    已上传 {uploadProgress?.done ?? 0} / {uploadProgress?.total ?? 0}
                  </span>
                  <span className="kb-upload-progress-name" title={uploadProgress?.currentName}>
                    {uploadProgress?.currentName}
                  </span>
                </div>
                <div className="kb-upload-progress-bar">
                  <div
                    className="kb-upload-progress-fill"
                    style={{
                      width: `${uploadProgress && uploadProgress.total > 0 ? (uploadProgress.done / uploadProgress.total) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>
            ) : (
              <>
                <svg className="kb-upload-icon" viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M24 6v24" />
                  <path d="m14 16 10-10 10 10" />
                  <path d="M8 32v6a4 4 0 0 0 4 4h24a4 4 0 0 0 4-4v-6" />
                </svg>
                <span className="kb-upload-copy">
                  <p className="kb-upload-text">点击或拖拽文件到此处上传</p>
                  <p className="kb-upload-hint">支持 PDF / Word / Excel / TXT / Markdown，压缩包自动分批处理</p>
                </span>
              </>
            )}
          </div>
        </div>

        {/* 下方：文件记录表格 */}
        <div className="kb-table-section">
          <div className="kb-table-head">
            <h2>文件记录</h2>
            <span className="kb-table-count">
              {loading ? '读取中…' : `共 ${documents.length} 份 · 成功 ${successCount} · Markdown ${markdownCount} · 已转换 ${conversionCount}`}
            </span>
          </div>

          <div className="kb-table-wrapper">
            <table className="kb-table">
              <thead>
                <tr>
                  <th className="kb-col-check">
                    <input
                      type="checkbox"
                      checked={selectedIds.size === documents.length && documents.length > 0}
                      onChange={toggleSelectAll}
                      aria-label="全选"
                    />
                  </th>
                  <th className="kb-col-id">ID</th>
                  <th className="kb-col-name">文件名</th>
                  <th className="kb-col-time">上传时间</th>
                  <th className="kb-col-status">上传状态</th>
                  <th className="kb-col-unknown">is_markdown</th>
                  <th className="kb-col-unknown">is_conversion</th>
                </tr>
              </thead>
              <tbody>
                {!loading && documents.length === 0 && (
                  <tr>
                    <td colSpan={7} className="kb-empty-row">暂无文件记录</td>
                  </tr>
                )}
                {paginatedDocuments.map((doc) => (
                  <tr
                    key={doc.id}
                    className={selectedIds.has(doc.id) ? 'kb-row-selected' : ''}
                    onClick={() => toggleSelect(doc.id)}
                  >
                    <td className="kb-col-check">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(doc.id)}
                        onChange={() => toggleSelect(doc.id)}
                        onClick={(event) => event.stopPropagation()}
                        aria-label={`选择 ${doc.name}`}
                      />
                    </td>
                    <td className="kb-col-id">{doc.id}</td>
                    <td className="kb-col-name" title={doc.name}>{doc.name}</td>
                    <td className="kb-col-time">
                      {doc.uploaded_at
                        ? new Date(doc.uploaded_at).toLocaleString('zh-CN', {
                            month: '2-digit',
                            day: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit',
                          })
                        : '—'}
                    </td>
                    <td className="kb-col-status">
                      {doc.upload_success ? (
                        <span className="kb-tag kb-tag-success">成功</span>
                      ) : (
                        <span className="kb-tag kb-tag-fail">失败</span>
                      )}
                    </td>
                    <td className="kb-col-unknown">
                      {doc.is_markdown ? (
                        <span className="kb-tag kb-tag-unknown">是</span>
                      ) : (
                        <span className="kb-tag kb-tag-normal">否</span>
                      )}
                    </td>
                    <td className="kb-col-unknown">
                      {doc.is_markdown ? (
                        <span className="kb-tag kb-tag-normal">—</span>
                      ) : doc.is_conversion ? (
                        <span className="kb-tag kb-tag-success">是</span>
                      ) : (
                        <span className="kb-tag kb-tag-normal">否</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {documents.length > 0 && (
            <div className="kb-pagination">
              <button
                className="kb-page-btn"
                disabled={safePage <= 1}
                onClick={() => setCurrentPage((page) => Math.max(page - 1, 1))}
                aria-label="上一页"
              >
                上一页
              </button>
              <span className="kb-page-info">
                第 {safePage} / {totalPages} 页
              </span>
              <button
                className="kb-page-btn"
                disabled={safePage >= totalPages}
                onClick={() => setCurrentPage((page) => Math.min(page + 1, totalPages))}
                aria-label="下一页"
              >
                下一页
              </button>
            </div>
          )}

          <div className="kb-actions">
            <button
              className="api-btn primary"
              disabled={selectedIds.size === 0 || converting}
              onClick={convertFormat}
            >
              {converting ? '转换中…' : '转化格式'}
            </button>
            <button
              className="api-btn danger"
              disabled={selectedIds.size === 0 || deleting}
              onClick={deleteSelected}
            >
              {deleting ? '删除中…' : `删除所选 (${selectedIds.size})`}
            </button>
            <button className="api-btn" disabled={documents.length === 0} onClick={onNext}>
              下一步
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
