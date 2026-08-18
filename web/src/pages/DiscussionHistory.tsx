import { useEffect, useState } from 'react'

import { fetchBrainstormDiscussions, type BrainstormDiscussionSummary } from '../api'

export default function DiscussionHistory({ onOpen }: { onOpen: (discussionId: string) => void }) {
  const [discussions, setDiscussions] = useState<BrainstormDiscussionSummary[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    void fetchBrainstormDiscussions()
      .then(setDiscussions)
      .catch((reason) => setError(reason instanceof Error ? reason.message : '获取讨论历史失败。'))
  }, [])

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
          <button className="discussion-history-item" key={discussion.id} onClick={() => onOpen(discussion.id)}>
            <strong>{discussion.title}</strong>
            <span>最近更新：{new Date(discussion.updated_at).toLocaleString()}</span>
            <b>继续讨论 →</b>
          </button>
        ))}
      </div>
    </div>
  )
}
