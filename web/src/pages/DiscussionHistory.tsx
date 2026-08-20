import { useEffect, useState } from 'react'

import { deleteBrainstormDiscussion, fetchBrainstormDiscussions, type BrainstormDiscussionSummary } from '../api'

export default function DiscussionHistory({ onOpen }: { onOpen: (discussionId: string) => void }) {
  const [discussions, setDiscussions] = useState<BrainstormDiscussionSummary[]>([])
  const [error, setError] = useState('')
  const [deletingId, setDeletingId] = useState<string | null>(null)

  useEffect(() => {
    void fetchBrainstormDiscussions()
      .then(setDiscussions)
      .catch((reason) => setError(reason instanceof Error ? reason.message : '获取讨论历史失败。'))
  }, [])

  async function removeDiscussion(discussion: BrainstormDiscussionSummary) {
    if (!window.confirm(`确认永久删除“${discussion.title}”及其全部对话内容吗？`)) return
    setDeletingId(discussion.id)
    setError('')
    try {
      await deleteBrainstormDiscussion(discussion.id)
      setDiscussions((current) => current.filter((item) => item.id !== discussion.id))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '删除讨论失败。')
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div className="page discussion-history-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">历史讨论</h1>
          <p className="page-sub">选择一条记录即可查看完整对话并继续交流。</p>
        </div>
      </div>
      {error && <p className="discussion-history-error">{error}</p>}
      {!error && discussions.length === 0 && <p className="discussion-history-empty">暂无已保存的讨论。</p>}
      <div className="discussion-history-list">
        {discussions.map((discussion) => (
          <div className="discussion-history-item" key={discussion.id}>
            <strong>{discussion.title}</strong>
            <span>最近更新：{new Date(discussion.updated_at).toLocaleString()}</span>
            <div className="discussion-history-actions">
              <button onClick={() => onOpen(discussion.id)}>继续讨论 →</button>
              <button className="discussion-history-delete" onClick={() => void removeDiscussion(discussion)} disabled={deletingId === discussion.id}>
                {deletingId === discussion.id ? '删除中…' : '删除'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
