// 本地保存的 API 配置（localStorage）
// 一次填写，多次复用；并标记一个当前激活的供 Submit 默认填入。

export type ApiConfig = {
  id: string
  name: string
  provider: 'openai' | 'deepseek' | 'custom'
  apiKey: string
  baseUrl: string
  model: string
  createdAt: number
}

export type ExternalService = 'tavily' | 'mineru'

export type ExternalServiceConfig = {
  apiKey: string
  baseUrl: string
}

export type ApiSettingsSnapshot = {
  configs: ApiConfig[]
  activeId: string | null
  externalServices: Record<ExternalService, ExternalServiceConfig>
}

const KEY_CONFIGS = 'mmagent.apiConfigs'
const KEY_ACTIVE = 'mmagent.apiActiveId'
const KEY_EXTERNAL_SERVICES = 'mmagent.externalServiceConfigs'

export const DEFAULT_EXTERNAL_SERVICES: Record<ExternalService, ExternalServiceConfig> = {
  tavily: { apiKey: '', baseUrl: 'https://api.tavily.com' },
  mineru: { apiKey: '', baseUrl: 'https://mineru.net' },
}

export function loadConfigs(): ApiConfig[] {
  try {
    const raw = localStorage.getItem(KEY_CONFIGS)
    if (!raw) return []
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

export function saveConfigs(configs: ApiConfig[]) {
  localStorage.setItem(KEY_CONFIGS, JSON.stringify(configs))
}

export function loadActiveId(): string | null {
  return localStorage.getItem(KEY_ACTIVE)
}

export function saveActiveId(id: string | null) {
  if (id) localStorage.setItem(KEY_ACTIVE, id)
  else localStorage.removeItem(KEY_ACTIVE)
}

export function loadExternalServiceConfigs(): Record<ExternalService, ExternalServiceConfig> {
  try {
    const raw = localStorage.getItem(KEY_EXTERNAL_SERVICES)
    if (!raw) return { ...DEFAULT_EXTERNAL_SERVICES }
    const saved = JSON.parse(raw) as Partial<Record<ExternalService, ExternalServiceConfig>>
    return {
      tavily: { ...DEFAULT_EXTERNAL_SERVICES.tavily, ...saved.tavily },
      mineru: { ...DEFAULT_EXTERNAL_SERVICES.mineru, ...saved.mineru },
    }
  } catch {
    return { ...DEFAULT_EXTERNAL_SERVICES }
  }
}

export function saveExternalServiceConfigs(
  configs: Record<ExternalService, ExternalServiceConfig>,
) {
  localStorage.setItem(KEY_EXTERNAL_SERVICES, JSON.stringify(configs))
}

export function newId(): string {
  return 'cfg_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4)
}

export function maskKey(k: string): string {
  if (!k) return ''
  if (k.length <= 8) return '••••'
  return k.slice(0, 4) + '••••••••' + k.slice(-4)
}
