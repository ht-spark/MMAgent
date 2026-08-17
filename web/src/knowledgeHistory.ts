export type KnowledgeHistoryAction = 'upload' | 'delete' | 'convert'

export type KnowledgeHistoryEvent = {
  id: string
  timestamp: number
  action: KnowledgeHistoryAction
  detail: string
  status: 'success' | 'failure'
}

const KEY_HISTORY = 'mmagent.knowledgeHistory'

export function loadKnowledgeHistory(): KnowledgeHistoryEvent[] {
  try {
    const raw = localStorage.getItem(KEY_HISTORY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

export function saveKnowledgeHistory(events: KnowledgeHistoryEvent[]) {
  localStorage.setItem(KEY_HISTORY, JSON.stringify(events))
}

export function appendKnowledgeHistory(
  event: Omit<KnowledgeHistoryEvent, 'id' | 'timestamp'>,
) {
  const events = loadKnowledgeHistory()
  events.unshift({
    ...event,
    id: 'khe_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4),
    timestamp: Date.now(),
  })
  saveKnowledgeHistory(events.slice(0, 200))
}
