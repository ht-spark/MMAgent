// 与 FastAPI 后端交互的薄封装。开发期经 Vite 代理（/api -> :8000）。

/** 后端是否在线（缓存结果，避免频繁探测）。 */
import {
  ApiConfig,
  ApiSettingsSnapshot,
  DEFAULT_EXTERNAL_SERVICES,
  ExternalService,
  ExternalServiceConfig,
  loadExternalServiceConfigs,
  saveActiveId,
  saveConfigs,
  saveExternalServiceConfigs,
} from './apiConfigs'

let _backendOnline: boolean | null = null

/**
 * 探测后端是否在线（GET /healthz）。
 * 结果缓存 10 秒，避免每次提交都额外发请求。
 */
export async function checkBackendOnline(): Promise<boolean> {
  try {
    const res = await fetch('/healthz', { signal: AbortSignal.timeout(3000) })
    const ok = res.ok
    _backendOnline = ok
    return ok
  } catch {
    _backendOnline = false
    return false
  }
}

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
    if (t) {
      // Vite 代理错误通常是 HTML，提取关键信息
      if (t.includes('proxy') || t.includes('ECONNREFUSED')) {
        return '后端服务未启动或已崩溃，请检查服务器是否正在运行（端口 8000）'
      }
      return t.slice(0, 500)
    }
  } catch {
    /* ignore */
  }
  return `${fallback} (${res.status})`
}

export async function createRun(form: FormData): Promise<{ run_id: string; status: string; output_dir: string }> {
  let res: Response
  try {
    res = await fetch('/api/runs', {
      method: 'POST',
      body: form,
      signal: AbortSignal.timeout(30000), // 30 秒超时，避免无限等待
    })
  } catch (e) {
    // 网络层错误（如后端未启动 / CORS / 连接拒绝 / 超时）
    const msg = e instanceof Error ? e.message : String(e)
    if (msg.includes('aborted') || msg.includes('timeout') || msg.includes('Timeout')) {
      throw new Error('请求超时：服务器响应时间过长，请检查后端是否正常运行')
    }
    throw new Error('后端服务未启动或无法连接，请确认服务器正在运行（uvicorn server.main:app --port 8000）')
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
  if (!res.ok) throw new Error('获取报告失败')
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

export async function renameRun(runId: string, name: string): Promise<void> {
  const fd = new FormData()
  fd.append('name', name)
  const res = await fetch(`/api/runs/${runId}/name`, { method: 'PATCH', body: fd })
  if (!res.ok) {
    const e = await res.json().catch(() => ({}))
    throw new Error((e as any).detail || `重命名失败 (${res.status})`)
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

/** G0 硬失败澄清：选择终止或上传补充材料继续建模。 */
export async function submitClarification(
  runId: string,
  action: 'terminate' | 'continue',
  dataFiles?: File[],
): Promise<{ ok: boolean }> {
  const fd = new FormData()
  fd.append('action', action)
  if (dataFiles) {
    dataFiles.forEach((f) => fd.append('data_files', f))
  }
  const res = await fetch(`/api/runs/${runId}/clarification`, {
    method: 'POST',
    body: fd,
  })
  if (!res.ok) {
    const e = await res.json().catch(() => ({}))
    throw new Error((e as any).detail || `澄清提交失败 (${res.status})`)
  }
  return res.json()
}

export type KnowledgeDocument = {
  id: string
  name: string
  size_bytes: number
  uploaded_at: string
  upload_success: boolean
  is_markdown: boolean
  is_conversion: boolean
}

export type KnowledgeStatus = {
  retrieval_ready: boolean
  documents: KnowledgeDocument[]
}

export async function getKnowledgeStatus(): Promise<KnowledgeStatus> {
  const res = await fetch('/api/knowledge/status')
  if (!res.ok) throw new Error(await extractDetail(res, '获取知识库状态失败'))
  return res.json()
}

export async function uploadKnowledgeDocument(file: File): Promise<KnowledgeDocument[]> {
  const form = new FormData()
  form.append('document', file)
  form.append('mineru_config', JSON.stringify(loadExternalServiceConfigs().mineru))
  const res = await fetch('/api/knowledge/documents', { method: 'POST', body: form })
  if (!res.ok) throw new Error(await extractDetail(res, '文档上传失败'))
  return res.json()
}

export async function deleteKnowledgeDocuments(documentIds: string[]): Promise<{ deleted_ids: string[] }> {
  const res = await fetch('/api/knowledge/documents', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ document_ids: documentIds }),
  })
  if (!res.ok) throw new Error(await extractDetail(res, '删除知识库文件失败'))
  return res.json()
}

export async function convertKnowledgeDocuments(documentIds: string[]): Promise<{ converted_ids: string[]; failed: string[] }> {
  const res = await fetch('/api/knowledge/documents/convert', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ document_ids: documentIds }),
  })
  if (!res.ok) throw new Error(await extractDetail(res, '文档转换失败'))
  return res.json()
}

export type KnowledgeChunkEmbedResult = {
  collection_name: string
  documents_processed: number
  chunks_indexed: number
  vector_size: number
  document_chunks: Record<string, number>
}

export type KnowledgeChunkEmbedProgress = {
  stage: 'idle' | 'chunking' | 'embedding' | 'done' | 'failed'
  error: string | null
}

export async function chunkAndEmbedKnowledge(): Promise<KnowledgeChunkEmbedResult> {
  const res = await fetch('/api/knowledge/chunk-embed', { method: 'POST' })
  if (!res.ok) throw new Error(await extractDetail(res, '分块与嵌入失败'))
  return res.json()
}

export async function getKnowledgeChunkEmbedProgress(): Promise<KnowledgeChunkEmbedProgress> {
  const res = await fetch('/api/knowledge/chunk-embed/progress')
  if (!res.ok) throw new Error(await extractDetail(res, '获取分块与嵌入进度失败'))
  return res.json()
}

export type BrainstormSource = {
  source_file: string
  document_id: string
  content: string
}

export type BrainstormResponse = {
  message: string
  sources: BrainstormSource[]
  discussion_id: string
}

export type BrainstormDiscussionSummary = {
  id: string
  title: string
  updated_at: string
}

export type BrainstormDiscussion = BrainstormDiscussionSummary & {
  messages: Array<{
    role: 'assistant' | 'user'
    content: string
    sources: BrainstormSource[]
  }>
}

export async function sendBrainstormMessage(message: string, discussionId: string | null): Promise<BrainstormResponse> {
  let res: Response
  try {
    res = await fetch('/api/knowledge/brainstorm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, discussion_id: discussionId }),
      signal: AbortSignal.timeout(150000),
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'TimeoutError') {
      throw new Error('讨论请求超时：模型服务在 150 秒内未响应，请检查 API 配置或稍后重试。')
    }
    throw new Error('讨论服务无法连接，请确认后端服务正在运行。')
  }
  if (!res.ok) throw new Error(await extractDetail(res, '头脑风暴请求失败'))
  return res.json()
}

export async function fetchBrainstormDiscussions(): Promise<BrainstormDiscussionSummary[]> {
  const res = await fetch('/api/knowledge/discussions')
  if (!res.ok) throw new Error(await extractDetail(res, '获取讨论历史失败'))
  return res.json()
}

export async function fetchBrainstormDiscussion(discussionId: string): Promise<BrainstormDiscussion> {
  const res = await fetch(`/api/knowledge/discussions/${discussionId}`)
  if (!res.ok) throw new Error(await extractDetail(res, '获取讨论记录失败'))
  return res.json()
}

/**
 * 从后端本地文件读取 API 配置快照。
 * 后端不可用、或从未保存过（saved=false）时返回 null。
 */
export async function fetchApiSettings(): Promise<(ApiSettingsSnapshot & { saved: boolean }) | null> {
  try {
    const res = await fetch('/api/settings/api', { signal: AbortSignal.timeout(3000) })
    if (!res.ok) return null
    const d = await res.json()
    if (!Array.isArray(d.configs)) return null
    const es = (d.external_services ?? {}) as Record<string, any>
    const merge = (name: ExternalService): ExternalServiceConfig => ({
      apiKey: String(es[name]?.apiKey ?? DEFAULT_EXTERNAL_SERVICES[name].apiKey),
      baseUrl: String(es[name]?.baseUrl ?? DEFAULT_EXTERNAL_SERVICES[name].baseUrl),
    })
    return {
      saved: d.saved === true,
      configs: d.configs as ApiConfig[],
      activeId: typeof d.active_id === 'string' ? d.active_id : null,
      externalServices: { tavily: merge('tavily'), mineru: merge('mineru') },
    }
  } catch {
    return null
  }
}

/**
 * 把后端权威配置同步进浏览器缓存。
 * 仅当后端确实保存过（saved=true）时覆盖，避免首次迁移清掉本地已有配置。
 */
export async function syncApiSettingsCache(): Promise<boolean> {
  const snap = await fetchApiSettings()
  if (!snap || !snap.saved) return false
  saveConfigs(snap.configs)
  saveActiveId(snap.activeId)
  saveExternalServiceConfigs(snap.externalServices)
  return true
}

/** 将配置快照写入后端本地文件；失败时静默降级为仅浏览器缓存。 */
export async function persistApiSettings(snapshot: ApiSettingsSnapshot): Promise<void> {
  try {
    await fetch('/api/settings/api', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        configs: snapshot.configs,
        active_id: snapshot.activeId,
        external_services: snapshot.externalServices,
      }),
      signal: AbortSignal.timeout(5000),
    })
  } catch {
    /* 后端离线时保留 localStorage 缓存即可 */
  }
}
