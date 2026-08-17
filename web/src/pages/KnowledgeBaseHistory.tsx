import { useMemo } from 'react'

import { loadKnowledgeHistory, type KnowledgeHistoryAction } from '../knowledgeHistory'

const ACTION_LABELS: Record<KnowledgeHistoryAction, string> = {
  upload: '上传文件',
  delete: '删除文件',
  convert: '转化格式',
}

const STATUS_LABELS = {
  success: '成功',
  failure: '失败',
}

export default function KnowledgeBaseHistory() {
  const events = useMemo(() => loadKnowledgeHistory(), [])

  return (
    <div className="page knowledge-base-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">历史记录</h1>
          <p className="page-sub">记录历次知识库维护操作，包括上传、删除与格式转换。</p>
        </div>
      </div>

      <div className="kb-table-section">
        <div className="kb-table-head">
          <h2>操作记录</h2>
          <span className="kb-table-count">共 {events.length} 条</span>
        </div>

        <div className="kb-table-wrapper">
          <table className="kb-table kb-history-table">
            <thead>
              <tr>
                <th className="kb-history-time">时间</th>
                <th className="kb-history-action">操作</th>
                <th className="kb-history-detail">详情</th>
                <th className="kb-history-status">状态</th>
              </tr>
            </thead>
            <tbody>
              {events.length === 0 && (
                <tr>
                  <td colSpan={4} className="kb-empty-row">暂无知识库维护记录</td>
                </tr>
              )}
              {events.map((event) => (
                <tr key={event.id}>
                  <td className="kb-history-time">
                    {new Date(event.timestamp).toLocaleString('zh-CN', {
                      year: 'numeric',
                      month: '2-digit',
                      day: '2-digit',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </td>
                  <td className="kb-history-action">{ACTION_LABELS[event.action]}</td>
                  <td className="kb-history-detail" title={event.detail}>{event.detail}</td>
                  <td className="kb-history-status">
                    <span className={`kb-tag kb-tag-${event.status === 'failure' ? 'fail' : 'success'}`}>{STATUS_LABELS[event.status]}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
