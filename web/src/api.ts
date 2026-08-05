// 与 FastAPI 后端交互的薄封装。开发期经 Vite 代理（/api -> :8000）。

export async function createRun(form: FormData): Promise<{ run_id: string; status: string; output_dir: string }> {
  const res = await fetch('/api/runs', { method: 'POST', body: form })
  if (!res.ok) {
    const e = await res.json().catch(() => ({}))
    throw new Error((e as any).detail || `提交失败 (${res.status})`)
  }
  return res.json()
}

export async function getRun(runId: string): Promise<any> {
  const res = await fetch(`/api/runs/${runId}`)
  if (!res.ok) throw new Error('获取运行状态失败')
  return res.json()
}

export async function getPaper(runId: string): Promise<string> {
  const res = await fetch(`/api/runs/${runId}/paper`)
  if (!res.ok) throw new Error('获取论文失败')
  return res.text()
}

export async function getFigures(runId: string): Promise<string[]> {
  const res = await fetch(`/api/runs/${runId}/figures`)
  if (!res.ok) return []
  const d = await res.json()
  return d.figures || []
}

export async function listRuns(): Promise<any[]> {
  const res = await fetch(`/api/runs`)
  if (!res.ok) throw new Error('获取历史失败')
  return res.json()
}

export async function deleteRun(runId: string): Promise<void> {
  const res = await fetch(`/api/runs/${runId}`, { method: 'DELETE' })
  if (!res.ok) {
    const e = await res.json().catch(() => ({}))
    throw new Error((e as any).detail || `删除失败 (${res.status})`)
  }
}

export async function cancelRun(runId: string): Promise<void> {
  const res = await fetch(`/api/runs/${runId}/cancel`, { method: 'POST' })
  if (!res.ok) {
    const e = await res.json().catch(() => ({}))
    throw new Error((e as any).detail || `中断失败 (${res.status})`)
  }
}
