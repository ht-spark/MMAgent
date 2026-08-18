export default function VectorRetrievalReady({ onBack }: { onBack: () => void }) {
  return (
    <div className="page chunk-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">向量检索就绪</h1>
          <p className="page-sub">知识库文档已完成分块与嵌入，可用于后续的向量检索。</p>
        </div>
      </div>

      <div className="ce-steps">
        <div className="ce-step ce-step-done"><span className="ce-step-dot">✓</span><span>上传与转换</span></div>
        <div className="ce-step ce-step-done"><span className="ce-step-dot">✓</span><span>资料统计</span></div>
        <div className="ce-step ce-step-done"><span className="ce-step-dot">✓</span><span>分块与嵌入设置</span></div>
        <div className="ce-step ce-step-done"><span className="ce-step-dot">✓</span><span>执行分块与嵌入</span></div>
        <div className="ce-step ce-step-current"><span className="ce-step-dot">5</span><span>向量检索就绪</span></div>
      </div>

      <div className="ce-table-section">
        <div className="kb-empty-row">知识库向量已准备完成。</div>
        <div className="kb-actions">
          <button className="api-btn" onClick={onBack}>上一步</button>
        </div>
      </div>
    </div>
  )
}
