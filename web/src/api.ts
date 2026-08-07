// 与 FastAPI 后端交互的薄封装。开发期经 Vite 代理（/api -> :8000）。

/**
 * 从非 OK 响应中尽力提取后端返回的 detail（支持 JSON 或纯文本）。
 * 失败时回退到通用模板，便于本地调试时直接看到具体异常类型与消息。
 */
async function extractDetail(res: Response, fallback: string): Promise<string> {
  // 优先尝试 JSON：FastAPI 的 HTTPException 序列化为 {"detail": "..."}
  try {
    const data = await res.clone().json()
    if (data && typeof (data as any).detail === 'string') return (data as any).detail
    const s = JSON.stringify(data)
    if (s && s !== '{}') return s
  } catch {
    /* 非 JSON，继续尝试 text */
  }
  try {
    const t = await res.text()
    if (t) return t.slice(0, 500)
  } catch {
    /* ignore */
  }
  return `${fallback} (${res.status})`
}

export async function createRun(form: FormData): Promise<{ run_id: string; status: string; output_dir: string }> {
  let res: Response
  try {
    res = await fetch('/api/runs', { method: 'POST', body: form })
  } catch (e) {
    // 网络层错误（如后端未启动 / CORS / 连接拒绝）
    throw new Error(`网络请求失败：${e instanceof Error ? e.message : String(e)}`)
  }
  if (!res.ok) {
    throw new Error(await extractDetail(res, '提交失败'))
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

/** 确认某小问的预算覆盖（弹窗提交）。use_defaults=true 表示沿用默认。 */
export async function confirmBudget(
  runId: string,
  body: { question_id?: string; use_defaults?: boolean; limits?: Record<string, number> },
): Promise<{ ok: boolean }> {
  const res = await fetch(`/api/runs/${runId}/budget-confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const e = await res.json().catch(() => ({}))
    throw new Error((e as any).detail || `预算确认失败 (${res.status})`)
  }
  return res.json()
}
