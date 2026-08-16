import { useEffect, useRef, useState } from 'react'
import {
  ApiConfig,
  loadConfigs,
  saveConfigs,
  loadActiveId,
  saveActiveId,
  newId,
  maskKey,
  ExternalService,
  ExternalServiceConfig,
  loadExternalServiceConfigs,
  saveExternalServiceConfigs,
} from '../apiConfigs'
import { persistApiSettings, syncApiSettingsCache } from '../api'

type Props = {
  onUsed?: () => void
}

const EMPTY: Omit<ApiConfig, 'id' | 'createdAt'> = {
  name: '',
  provider: 'openai',
  apiKey: '',
  baseUrl: '',
  model: '',
}

const SERVICE_META: Record<ExternalService, { name: string; keyLabel: string; hint: string }> = {
  tavily: {
    name: 'Tavily 联网检索',
    keyLabel: 'Tavily API Key',
    hint: '用于联网搜索与知识检索补充。',
  },
  mineru: {
    name: 'MinerU 文档转换',
    keyLabel: 'MinerU Token',
    hint: '用于后续将文档转换为 Markdown。',
  },
}

export default function ApiManager({ onUsed }: Props) {
  const [configs, setConfigs] = useState<ApiConfig[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [editing, setEditing] = useState<Partial<ApiConfig>>(EMPTY)
  const [isNew, setIsNew] = useState(false)
  const [serviceConfigs, setServiceConfigs] = useState<Record<ExternalService, ExternalServiceConfig>>(
    loadExternalServiceConfigs,
  )
  const persistDebounceRef = useRef<number | null>(null)

  useEffect(() => {
    setConfigs(loadConfigs())
    setActiveId(loadActiveId())
    setServiceConfigs(loadExternalServiceConfigs())
    // 后端本地文件是权威存储：同步成功后覆盖界面与浏览器缓存
    let cancelled = false
    syncApiSettingsCache().then((synced) => {
      if (!synced || cancelled) return
      setConfigs(loadConfigs())
      setActiveId(loadActiveId())
      setServiceConfigs(loadExternalServiceConfigs())
    })
    return () => {
      cancelled = true
    }
  }, [])

  function persist(next: ApiConfig[], nextActive: string | null) {
    setConfigs(next)
    saveConfigs(next)
    setActiveId(nextActive)
    saveActiveId(nextActive)
    void persistApiSettings({
      configs: next,
      activeId: nextActive,
      externalServices: serviceConfigs,
    })
  }

  function startNew() {
    setEditing({ ...EMPTY })
    setIsNew(true)
  }

  function startEdit(c: ApiConfig) {
    setEditing({ ...c })
    setIsNew(false)
  }

  function cancelEdit() {
    setEditing({ ...EMPTY })
    setIsNew(false)
  }

  function save() {
    const name = (editing.name ?? '').trim() || '未命名配置'
    const provider = (editing.provider ?? 'openai') as ApiConfig['provider']
    const apiKey = editing.apiKey ?? ''
    const baseUrl = editing.baseUrl ?? ''
    const model = editing.model ?? ''

    if (isNew) {
      const c: ApiConfig = {
        id: newId(),
        name,
        provider,
        apiKey,
        baseUrl,
        model,
        createdAt: Date.now(),
      }
      const next = [...configs, c]
      const nextActive = activeId ?? c.id
      persist(next, nextActive)
    } else if (editing.id) {
      const next = configs.map((c) =>
        c.id === editing.id
          ? { ...c, name, provider, apiKey, baseUrl, model }
          : c,
      )
      persist(next, activeId)
    }
    cancelEdit()
  }

  function remove(id: string) {
    if (!confirm('确认删除这个配置？')) return
    const next = configs.filter((c) => c.id !== id)
    const nextActive = activeId === id ? (next[0]?.id ?? null) : activeId
    persist(next, nextActive)
  }

  function setActive(id: string) {
    persist(configs, id)
  }

  function useAndGo() {
    if (onUsed) onUsed()
  }

  /** 扩展服务输入防抖：停止输入 400ms 后才写后端文件 */
  function schedulePersist(snapshot: Parameters<typeof persistApiSettings>[0]) {
    if (persistDebounceRef.current !== null) window.clearTimeout(persistDebounceRef.current)
    persistDebounceRef.current = window.setTimeout(() => {
      persistDebounceRef.current = null
      void persistApiSettings(snapshot)
    }, 400)
  }

  function updateService(
    service: ExternalService,
    field: keyof ExternalServiceConfig,
    value: string,
  ) {
    const next = {
      ...serviceConfigs,
      [service]: { ...serviceConfigs[service], [field]: value },
    }
    setServiceConfigs(next)
    saveExternalServiceConfigs(next)
    schedulePersist({ configs, activeId, externalServices: next })
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">API 管理</h1>
          <div className="page-sub">
            管理 LLM、联网检索和文档转换服务。配置保存在本机（服务端本地文件），重新进入网页自动恢复。
          </div>
        </div>
        <button className="submit-btn" style={{ width: 'auto', marginTop: 0, padding: '10px 18px' }} onClick={startNew}>
          + 新增配置
        </button>
      </div>

      {(isNew || editing.id) && (
        <div className="form-card" style={{ marginBottom: 22 }}>
          <h2>{isNew ? '新增 API 配置' : '编辑 API 配置'}</h2>

          <div className="field">
            <label>配置名（用于区分多个 API）</label>
            <input
              type="text"
              value={editing.name ?? ''}
              onChange={(e) => setEditing({ ...editing, name: e.target.value })}
              placeholder="例如：DeepSeek 个人 / OpenAI 官方"
            />
          </div>

          <div className="form-row">
            <div className="field" style={{ flex: 1 }}>
              <label>服务商</label>
              <select
                value={editing.provider ?? 'openai'}
                onChange={(e) =>
                  setEditing({ ...editing, provider: e.target.value as ApiConfig['provider'] })
                }
              >
                <option value="openai">OpenAI</option>
                <option value="deepseek">DeepSeek</option>
                <option value="custom">自定义</option>
              </select>
            </div>
            <div className="field" style={{ flex: 1 }}>
              <label>模型</label>
              <input
                type="text"
                value={editing.model ?? ''}
                onChange={(e) => setEditing({ ...editing, model: e.target.value })}
                placeholder="如 gpt-4o-mini / deepseek-chat"
              />
            </div>
          </div>

          <div className="field">
            <label>Base URL</label>
            <input
              type="url"
              value={editing.baseUrl ?? ''}
              onChange={(e) => setEditing({ ...editing, baseUrl: e.target.value })}
              placeholder="可留空；OpenAI 官方默认；DeepSeek 可填 https://api.deepseek.com"
            />
          </div>

          <div className="field">
            <label>API Key</label>
            <input
              type="password"
              value={editing.apiKey ?? ''}
              onChange={(e) => setEditing({ ...editing, apiKey: e.target.value })}
              placeholder="sk-..."
            />
          </div>

          <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
            <button className="submit-btn" style={{ marginTop: 0 }} onClick={save}>
              保存
            </button>
            <button
              className="back-link"
              onClick={cancelEdit}
              style={{ cursor: 'pointer', fontFamily: 'inherit' }}
            >
              取消
            </button>
          </div>
        </div>
      )}

      <section className="api-section" aria-labelledby="model-api-heading">
        <div className="api-section-head">
          <h2 id="model-api-heading">模型服务</h2>
          <p>选择默认配置后，新建任务会自动带入。</p>
        </div>

      {configs.length === 0 ? (
        <div className="form-card center muted">
          还没有保存任何 API。点 <strong>新增配置</strong> 添加一个。
        </div>
      ) : (
        <div className="api-grid">
          {configs.map((c) => {
            const isActive = c.id === activeId
            return (
              <div key={c.id} className={`api-card ${isActive ? 'active' : ''}`}>
                <div className="api-card-head">
                  <div className="api-name">{c.name}</div>
                  {isActive && <span className="api-badge">当前使用</span>}
                </div>
                <div className="api-meta">
                  <div><span className="k">服务商</span><span className="v">{c.provider}</span></div>
                  <div><span className="k">模型</span><span className="v">{c.model || '—'}</span></div>
                  <div><span className="k">Base URL</span><span className="v">{c.baseUrl || '默认'}</span></div>
                  <div><span className="k">Key</span><span className="v mono">{c.apiKey ? maskKey(c.apiKey) : '未填'}</span></div>
                </div>
                <div className="api-actions">
                  {!isActive && (
                    <button className="api-btn primary" onClick={() => setActive(c.id)}>
                      使用
                    </button>
                  )}
                  <button className="api-btn" onClick={() => startEdit(c)}>编辑</button>
                  <button className="api-btn danger" onClick={() => remove(c.id)}>删除</button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      </section>

      <section className="api-section" aria-labelledby="external-api-heading">
        <div className="api-section-head">
          <h2 id="external-api-heading">扩展服务</h2>
          <p>这些配置不参与 LLM 默认模型选择。</p>
        </div>
        <div className="api-grid">
          {(Object.keys(SERVICE_META) as ExternalService[]).map((service) => {
            const meta = SERVICE_META[service]
            const config = serviceConfigs[service]
            return (
              <div className="api-card" key={service}>
                <div className="api-card-head">
                  <div className="api-name">{meta.name}</div>
                  <span className={`api-badge ${config.apiKey ? '' : 'muted-badge'}`}>
                    {config.apiKey ? '已配置' : '未配置'}
                  </span>
                </div>
                <p className="api-service-hint">{meta.hint}</p>
                <div className="field">
                  <label>{meta.keyLabel}</label>
                  <input
                    type="password"
                    value={config.apiKey}
                    onChange={(event) => updateService(service, 'apiKey', event.target.value)}
                    placeholder={service === 'tavily' ? 'tvly-...' : '输入 MinerU Token'}
                  />
                </div>
                <div className="field">
                  <label>Base URL</label>
                  <input
                    type="url"
                    value={config.baseUrl}
                    onChange={(event) => updateService(service, 'baseUrl', event.target.value)}
                    placeholder="可使用默认地址"
                  />
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {configs.length > 0 && (
        <div className="center" style={{ marginTop: 24 }}>
          <button className="submit-btn" style={{ width: 'auto', display: 'inline-flex' }} onClick={useAndGo}>
            用当前默认 API 开始建模 →
          </button>
        </div>
      )}
    </div>
  )
}
