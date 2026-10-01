import { desktop } from './desktop'

export interface Source {
  title: string
  snippet?: string
  source?: string
  score?: number
}

export interface ChatResponse {
  conversation_id: string
  answer: string
  sources: Source[]
  tool_calls?: Array<{ name: string; result?: unknown }>
  model?: string
  mode?: string
}

export interface KnowledgeDocument {
  id: string
  filename: string
  content?: string
  updated_at?: string
  warning?: string
  index_status?: 'indexed' | 'keyword' | 'pending'
}

export interface Health {
  status: string
  rag_enabled: boolean
  rag_degraded?: boolean
  models: { qwen: boolean; deepseek: boolean; ollama?: boolean }
  demo_services: boolean
}

export interface ConversationHistory {
  id: string
  messages: Array<{ role: 'user' | 'assistant'; content: string; created_at: string; sources?: Source[]; tool_calls?: Array<{ name: string }>; mode?: string }>
}

export interface Plugin {
  id: string
  name: string
  description?: string
  enabled: boolean
  url?: string
  parameters?: Record<string, unknown>
}

export interface ModelProvider {
  configured: boolean
  base_url: string
  model: string
}

export interface ModelConfig {
  providers: { qwen: ModelProvider; deepseek: ModelProvider }
  ollama: { model: string }
}

export interface LocalModel {
  name: string
  size?: number
  size_bytes?: number
}

export interface LocalCatalogModel {
  name: string
  description?: string
  size?: string
}

export interface LocalModels {
  running: boolean
  installed: LocalModel[]
  catalog: Array<{ id: string; label: string; size_bytes: number; installed: boolean }>
  sources: Array<{ id: string; label: string }>
  error?: string
}

export interface ModelDownload {
  id: string
  status: string
  progress?: number
  error?: string
  completed?: number
  total?: number
  detail?: string
}

export interface CampusSource {
  kind: string
  label: string
  configured: boolean
  url: string
  result_path: string
  has_token: boolean
}

export interface CuratedPlugin {
  id: string
  name: string
  description: string
  source?: string
  installed?: boolean
  enabled?: boolean
}

const base = desktop ? '/api' : import.meta.env.VITE_API_BASE_URL || '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    const needsAdmin = (path.startsWith('/documents') || path.startsWith('/plugins') || path.startsWith('/models') || path.startsWith('/campus-sources')) && init?.method !== 'GET' && init?.method !== undefined
    const headers = new Headers(init?.headers)
    if (needsAdmin && !desktop) headers.set('X-Admin-Token', sessionStorage.getItem('campus-agent-admin-token') || '')
    response = await fetch(`${base}${path}`, { ...init, headers })
  } catch {
    throw new Error('无法连接 Mens 服务。请检查后端是否已启动。')
  }
  if (!response.ok) {
    let detail = ''
    try {
      const data = await response.json()
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data)
    } catch {
      detail = response.statusText
    }
    throw new Error(detail || `请求失败 (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

export const api = {
  health: () => request<Health>('/health'),
  conversation: (id: string) => request<ConversationHistory>(`/conversations/${encodeURIComponent(id)}`),
  chat: (message: string, conversationId: string, model: string, localModel?: string) =>
    request<ChatResponse>('/chat', json('POST', { message, conversation_id: conversationId || undefined, model: model === 'qwen3' ? 'qwen' : model, ...(model === 'ollama' && localModel ? { local_model: localModel } : {}) })),
  modelConfig: () => request<ModelConfig>('/models/config'),
  saveModelConfig: (provider: 'qwen' | 'deepseek' | 'ollama', values: { api_key?: string; clear_api_key?: boolean; base_url?: string; model?: string }) =>
    request<ModelConfig>(`/models/config/${provider}`, json('PUT', values)),
  testModel: (provider: 'qwen' | 'deepseek') => request<{ ok: boolean; error?: string }>(`/models/test/${provider}`, { method: 'POST' }),
  localModels: () => request<LocalModels>('/models/local'),
  pullLocalModel: (model: string, source: string) => request<ModelDownload>('/models/local/pull', json('POST', { model, source })),
  localModelDownload: (id: string) => request<ModelDownload>(`/models/local/jobs/${encodeURIComponent(id)}`),
  cancelLocalModelDownload: (id: string) => request<ModelDownload>(`/models/local/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  campusSources: () => request<CampusSource[]>('/campus-sources'),
  saveCampusSource: (kind: string, values: { url: string; result_path: string; token?: string }) =>
    request<CampusSource>(`/campus-sources/${encodeURIComponent(kind)}`, json('PUT', values)),
  removeCampusSource: (kind: string) => request<{ deleted: boolean }>(`/campus-sources/${encodeURIComponent(kind)}`, { method: 'DELETE' }),
  campusData: (kind: string) => request<unknown>(`/campus-data/${encodeURIComponent(kind)}`),
  documents: async () => {
    const result = await request<Array<{ id: string; title: string; content: string; updated_at?: string }>>('/documents')
    return result.map(doc => ({ ...doc, filename: doc.title }))
  },
  uploadDocument: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<KnowledgeDocument>('/documents/upload', { method: 'POST', body: form })
  },
  updateDocument: (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<KnowledgeDocument>(`/documents/${encodeURIComponent(id)}/upload`, { method: 'PUT', body: form })
  },
  deleteDocument: (id: string) => request<{ deleted: boolean; warning?: string }>(`/documents/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  reindex: () => request<{ indexed: number }>('/documents/reindex', { method: 'POST' }),
  plugins: async () => {
    const result = await request<Plugin[] | { items: Plugin[] }>('/plugins')
    return Array.isArray(result) ? result : result.items
  },
  curatedPlugins: () => request<CuratedPlugin[]>('/plugins/catalog'),
  installCuratedPlugin: (id: string) => request<Plugin>('/plugins/catalog/install', json('POST', { id })),
  installPlugin: (source: string) => request<Plugin>('/plugins/install', json('POST', { source })),
  togglePlugin: (id: string, enabled: boolean) => request<Plugin>(`/plugins/${encodeURIComponent(id)}`, json('PATCH', { enabled })),
  removePlugin: (id: string) => request<void>(`/plugins/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  invokePlugin: (name: string, parameters: Record<string, unknown>) => request<unknown>(`/plugins/${encodeURIComponent(name)}/invoke`, json('POST', parameters)),
  grades: () => request<unknown>('/services/grades'),
  schedule: () => request<unknown>('/services/schedule'),
  credits: () => request<unknown>('/services/credits'),
  classrooms: (building: string, minSeats: number) =>
    request<unknown>(`/services/classrooms?building=${encodeURIComponent(building)}&min_seats=${minSeats}`),
  repair: (payload: { location: string; description: string; contact: string }) =>
    request<unknown>('/services/repairs', json('POST', { location: payload.location, issue: payload.description, contact: payload.contact })),
}
