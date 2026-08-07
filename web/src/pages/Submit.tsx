import { useEffect, useState } from 'react'
import { createRun } from '../api'
import { loadConfigs, loadActiveId, ApiConfig } from '../apiConfigs'

export default function Submit({ onSubmitted }: { onSubmitted: (runId: string) => void }) {
  const [problemFile, setProblemFile] = useState<File | null>(null)
  const [dataFiles, setDataFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [activeName, setActiveName] = useState<string>('')

  // 拉取 API 管理里设置的当前配置（仅用于带入后端，不在页面上展示）
  const [activeCfg, setActiveCfg] = useState<ApiConfig | null>(null)

  useEffect(() => {
    const configs: ApiConfig[] = loadConfigs()
    if (configs.length === 0) {
      setActiveCfg(null)
      setActiveName('')
      return
    }
    const activeId = loadActiveId()
    const active = configs.find((c) => c.id === activeId) ?? configs[0]
    setActiveCfg(active ?? null)
    setActiveName(active?.name ?? '')
  }, [])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    const fd = new FormData()
    if (problemFile) fd.append('problem_file', problemFile)
    dataFiles.forEach((f) => fd.append('data_files', f))
    if (activeCfg) {
      const cfg: Record<string, string> = {
        provider: activeCfg.provider,
        api_key: activeCfg.apiKey,
      }
      if (activeCfg.baseUrl) cfg.base_url = activeCfg.baseUrl
      if (activeCfg.model) cfg.model = activeCfg.model
      fd.append('llm_config', JSON.stringify(cfg))
    }
    try {
      const r = await createRun(fd)
      onSubmitted(r.run_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="form-card" onSubmit={submit}>
      <h2>新建建模任务</h2>

      <div className="field">
        <label>任务文件</label>
        <input
          type="file"
          accept=".md,.txt"
          onChange={(e) => setProblemFile(e.target.files?.[0] ?? null)}
        />
        <div className="file-note">支持 .md / .txt。任务内容将以该文件传入智能体。</div>
      </div>

      <div className="field">
        <label>数据附件（可多选）</label>
        <input
          type="file"
          multiple
          onChange={(e) => setDataFiles(Array.from(e.target.files ?? []))}
        />
        <div className="file-note">支持 Excel / CSV / 图片等，将随任务一并传入智能体。</div>
      </div>

      <div className="api-hint">
        {activeName ? (
          <>
            当前 API：<strong>{activeName}</strong>（{activeCfg?.provider}
            {activeCfg?.model ? ` · ${activeCfg.model}` : ''}）·
            可在侧边栏「API 管理」修改
          </>
        ) : (
          <>尚未配置 API，请先到侧边栏「API 管理」添加并设默认。</>
        )}
      </div>

      {error && <div className="err-box">{error}</div>}
      <button type="submit" className="submit-btn" disabled={busy || !activeCfg}>
        {busy ? '提交中…' : '开始建模 →'}
      </button>
    </form>
  )
}
