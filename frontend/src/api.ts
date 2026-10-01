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
  messages: Array<{ role: 'user' | 'assistant'; content: string; created_at: string; sources?: Source[]; tool_calls?: Array<{ name: string }>; mode?: string; partial?: boolean }>
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

export interface ConversationSummary {
  id: string
  title: string
  message_count: number
  updated_at: string
}

export interface ChatStreamCallbacks {
  onMeta?: (conversationId: string) => void
  onDelta?: (text: string) => void
}

export class ChatStreamError extends Error {
  partial: string

  constructor(message: string, partial: string) {
    super(message)
    this.name = 'ChatStreamError'
    this.partial = partial
  }
}

export function parseSseFrame(frame: string): { event: string; data: Record<string, unknown> } | null {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!dataLines.length) return null
  try {
    const data = JSON.parse(dataLines.join('\n'))
    return data && typeof data === 'object' ? { event, data } : null
  } catch {
    return null
  }
}

export interface RepairRecord {
  id: string
  location: string
  issue: string
  contact: string
  status: string
  created_at: string
}

const base = desktop ? '/api' : import.meta.env.VITE_API_BASE_URL || '/api'

async function request<T>(path: string, init?: RequestInit, admin = false): Promise<T> {
  let response: Response
  try {
    const needsAdmin = admin || ((path.startsWith('/documents') || path.startsWith('/plugins') || path.startsWith('/models') || path.startsWith('/campus-sources') || path.startsWith('/backup')) && init?.method !== 'GET' && init?.method !== undefined)
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

function chatPayload(message: string, conversationId: string, model: string, localModel: string | undefined, clientId: string) {
  return {
    message,
    conversation_id: conversationId || undefined,
    model: model === 'qwen3' ? 'qwen' : model,
    client_id: clientId || undefined,
    ...(model === 'ollama' && localModel ? { local_model: localModel } : {}),
  }
}

function responseError(status: number, detail: string) {
  return new Error(detail || `请求失败 (${status})`)
}

/** Streams an answer over SSE; aborts by passing signal.abort(), partial text is kept by the caller. */
export async function chatStream(
  payload: { message: string; conversationId: string; model: string; localModel?: string; clientId: string },
  callbacks: ChatStreamCallbacks,
  signal: AbortSignal,
): Promise<ChatResponse> {
  let response: Response
  try {
    response = await fetch(`${base}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(chatPayload(payload.message, payload.conversationId, payload.model, payload.localModel, payload.clientId)),
      signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new Error('无法连接 Mens 服务。请检查后端是否已启动。')
  }
  if (!response.ok) {
    let detail = ''
    try {
      const data = await response.json()
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data)
    } catch { detail = response.statusText }
    throw responseError(response.status, detail)
  }
  if (!response.body) throw new Error('当前环境不支持流式回答。')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let answer = ''
  let final: ChatResponse | null = null
  let failure = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const frame = parseSseFrame(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
        if (!frame) continue
        if (frame.event === 'meta') {
          const id = frame.data.conversation_id
          if (typeof id === 'string' && id) callbacks.onMeta?.(id)
        } else if (frame.event === 'delta') {
          const text = frame.data.text
          if (typeof text === 'string' && text) {
            answer += text
            callbacks.onDelta?.(text)
          }
        } else if (frame.event === 'done') {
          final = {
            conversation_id: typeof frame.data.conversation_id === 'string' ? frame.data.conversation_id : '',
            answer: typeof frame.data.answer === 'string' ? frame.data.answer : answer,
            sources: (frame.data.sources as Source[]) || [],
            tool_calls: frame.data.tool_calls as ChatResponse['tool_calls'],
            mode: typeof frame.data.mode === 'string' ? frame.data.mode : 'demo',
          }
        } else if (frame.event === 'error') {
          failure = typeof frame.data.message === 'string' && frame.data.message ? frame.data.message : '生成失败，请重试。'
          const partial = frame.data.partial
          if (typeof partial === 'string' && partial) answer = partial
        }
      }
    }
  } finally {
    try { reader.releaseLock() } catch { /* the stream already closed */ }
  }
  if (failure) throw new ChatStreamError(failure, answer)
  if (!final) throw new ChatStreamError('连接中断，未收到完整回答。请重试。', answer)
  return final
}

export const api = {
  health: () => request<Health>('/health'),
  conversation: (id: string) => request<ConversationHistory>(`/conversations/${encodeURIComponent(id)}`),
  conversations: (clientId: string, limit = 50) =>
    request<ConversationSummary[]>(`/conversations?client_id=${encodeURIComponent(clientId)}&limit=${limit}`),
  deleteConversation: (id: string, clientId: string) =>
    request<{ deleted: boolean }>(`/conversations/${encodeURIComponent(id)}?client_id=${encodeURIComponent(clientId)}`, { method: 'DELETE' }),
  clearConversations: (clientId: string) =>
    request<{ deleted: number }>(`/conversations?client_id=${encodeURIComponent(clientId)}`, { method: 'DELETE' }),
  chat: (message: string, conversationId: string, model: string, localModel?: string, clientId = '') =>
    request<ChatResponse>('/chat', json('POST', chatPayload(message, conversationId, model, localModel, clientId))),
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
  repairs: () => request<{ demo: boolean; items: RepairRecord[] }>('/services/repairs', undefined, true),
  exportBackup: async () => {
    const headers = new Headers()
    if (!desktop) headers.set('X-Admin-Token', sessionStorage.getItem('campus-agent-admin-token') || '')
    let response: Response
    try {
      response = await fetch(`${base}/backup/export`, { headers })
    } catch {
      throw new Error('无法连接 Mens 服务。请检查后端是否已启动。')
    }
    if (!response.ok) {
      let detail = ''
      try {
        const data = await response.json()
        detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data)
      } catch { detail = response.statusText }
      throw responseError(response.status, detail)
    }
    return response.blob()
  },
  importBackup: (bytes: Uint8Array, name: string) => {
    const form = new FormData()
    // DOM types require an ArrayBuffer-backed view for Blob parts.
    form.append('file', new Blob([bytes.slice().buffer as ArrayBuffer], { type: 'application/zip' }), name)
    return request<{ restored: string[]; failed: string[]; restart_required: boolean }>('/backup/import', { method: 'POST', body: form })
  },
}
