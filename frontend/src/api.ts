import { desktop } from './desktop'

export interface Source {
  title: string
  snippet?: string
  source?: string
  score?: number
  url?: string
  kind?: string
}

export interface WebStatus {
  enabled: boolean
  provider: string
  resolved_provider: string
  available: boolean
  api_key_set: boolean
  max_results: number
  fetch_pages: number
  max_fetch_pages: number
  max_results_limit: number
  providers: { id: string; label: string; keyed: boolean }[]
}

export interface ChatResponse {
  conversation_id: string
  answer: string
  sources: Source[]
  tool_calls?: Array<{ name: string; result?: unknown }>
  model?: string
  mode?: string
  web?: { provider?: string; error?: string; fetched_at?: string }
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
  messages: Array<{ id?: number; role: 'user' | 'assistant'; content: string; created_at: string; sources?: Source[]; tool_calls?: Array<{ name: string }>; mode?: string; partial?: boolean; thinking?: string; feedback?: 'up' | 'down' }>
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
  onThinking?: (text: string) => void
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

export interface UpdateCheck {
  configured: boolean
  current: string
  latest?: string
  update_available: boolean
  url?: string
  notes?: string
  message?: string
  error?: string
}

import { t } from './i18n'
/** 把 FastAPI 的字段校验数组（string_too_short 之类）翻成人话，避免把原始 JSON 丢给用户。 */
export function formatFieldErrors(rows: unknown[]): string {
  const labels: Record<string, string> = {
    username: t('auth.username'),
    password: t('auth.password'),
    current: t('auth.password'),
    code: t('auth.register.code'),
  }
  const messages: string[] = []
  for (const row of rows as { loc?: unknown[]; type?: string; ctx?: { min_length?: number; max_length?: number } }[]) {
    const key = Array.isArray(row?.loc) ? String(row.loc[row.loc.length - 1]) : ''
    const label = labels[key] || key || t('api.error.field')
    if (row?.type === 'string_too_short') {
      messages.push(t('api.error.minLength', { field: label, count: String(row.ctx?.min_length ?? 0) }))
    } else if (row?.type === 'string_too_long') {
      messages.push(t('api.error.maxLength', { field: label, count: String(row.ctx?.max_length ?? 0) }))
    } else if (row?.type === 'missing') {
      messages.push(t('api.error.missing', { field: label }))
    } else {
      messages.push(t('api.error.invalid', { field: label }))
    }
  }
  return messages.join('；') || t('api.error.generic')
}

const base = desktop ? '/api' : import.meta.env.VITE_API_BASE_URL || '/api'

async function request<T>(path: string, init?: RequestInit, admin = false): Promise<T> {
  let response: Response
  try {
    const needsAdmin = admin || ((path.startsWith('/documents') || path.startsWith('/plugins') || path.startsWith('/mcp') || path.startsWith('/models') || path.startsWith('/campus-sources') || path.startsWith('/backup') || path.startsWith('/web')) && init?.method !== 'GET' && init?.method !== undefined)
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
      if (typeof data.detail === 'string') {
        detail = data.detail
      } else if (Array.isArray(data.detail)) {
        detail = formatFieldErrors(data.detail)
      } else {
        detail = JSON.stringify(data.detail || data)
      }
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

function chatPayload(message: string, conversationId: string, model: string, localModel: string | undefined, clientId: string, web = false, reasoning: 'fast' | 'deep' = 'fast', regenerate = false) {
  return {
    message,
    conversation_id: conversationId || undefined,
    model: model === 'qwen3' ? 'qwen' : model,
    client_id: clientId || undefined,
    ...(web ? { web: true } : {}),
    ...(reasoning === 'deep' ? { reasoning: 'deep' } : {}),
    ...(regenerate ? { regenerate: true } : {}),
    ...(model === 'ollama' && localModel ? { local_model: localModel } : {}),
  }
}

function responseError(status: number, detail: string) {
  return new Error(detail || `请求失败 (${status})`)
}

/** Streams an answer over SSE; aborts by passing signal.abort(), partial text is kept by the caller. */
export async function chatStream(
  payload: { message: string; conversationId: string; model: string; localModel?: string; clientId: string; web?: boolean; reasoning?: 'fast' | 'deep'; regenerate?: boolean },
  callbacks: ChatStreamCallbacks,
  signal: AbortSignal,
): Promise<ChatResponse> {
  let response: Response
  try {
    response = await fetch(`${base}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(chatPayload(payload.message, payload.conversationId, payload.model, payload.localModel, payload.clientId, payload.web, payload.reasoning, payload.regenerate)),
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
        } else if (frame.event === 'thinking') {
          const text = frame.data.text
          if (typeof text === 'string' && text) callbacks.onThinking?.(text)
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
  setFeedback: (conversationId: string, messageId: number, value: 'up' | 'down' | null) =>
    request<{ ok: boolean; feedback: string | null }>(`/conversations/${encodeURIComponent(conversationId)}/messages/${messageId}/feedback`, json('POST', { value })),
  chat: (message: string, conversationId: string, model: string, localModel?: string, clientId = '', web = false) =>
    request<ChatResponse>('/chat', json('POST', chatPayload(message, conversationId, model, localModel, clientId, web))),
  webStatus: () => request<WebStatus>('/web/status'),
  saveWebConfig: (values: { enabled?: boolean; provider?: string; api_key?: string; max_results?: number; fetch_pages?: number }) =>
    request<WebStatus>('/web/config', json('PUT', values)),
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
  importDocumentUrl: (url: string) => request<KnowledgeDocument>('/documents/import-url', json('POST', { url }))
    .then(doc => ({ ...doc, filename: doc.filename || String((doc as { title?: string }).title || '') })),
  exportConversation: async (id: string, format: 'md' | 'json') => {
    let response: Response
    try {
      response = await fetch(`${base}/conversations/${encodeURIComponent(id)}/export?format=${format}`)
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
    const disposition = response.headers.get('content-disposition') || ''
    const match = /filename="([^"]+)"/.exec(disposition)
    return { blob: await response.blob(), name: match ? match[1] : `mens-conversation.${format}` }
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
  checkUpdate: () => request<UpdateCheck>('/update/check', undefined, true),
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


// ------------------------------------------------------------------ MCP 服务器
export type McpTool = { name: string; description: string; inputSchema: Record<string, unknown> }
export type McpServer = {
  id: string
  name: string
  command: string
  args: string[]
  env_keys: string[]
  env_masked: Record<string, string>
  enabled: boolean
  tools: McpTool[]
  tool_count: number
  last_checked_at: string | null
  last_error: string
}
export type McpServerInput = {
  name: string
  command: string
  args?: string[]
  env?: Record<string, string>
  enabled?: boolean
}
export type McpToolEntry = { server: string; tool: string; function: string; description: string }
export type McpCheckResult = {
  ok: boolean
  error?: string
  server?: string
  version?: string
  protocolVersion?: string
  tool_count?: number
  tools?: McpTool[]
  elapsed_ms?: number
}

export async function listMcpServers(): Promise<McpServer[]> {
  const data = await request<{ servers: McpServer[] }>('/mcp/servers')
  return data.servers
}

export async function createMcpServer(input: McpServerInput): Promise<McpServer> {
  const data = await request<{ server: McpServer }>('/mcp/servers', json('POST', input))
  return data.server
}

export async function updateMcpServer(id: string, patch: Partial<McpServerInput>): Promise<McpServer> {
  const data = await request<{ server: McpServer }>(`/mcp/servers/${encodeURIComponent(id)}`, json('PUT', patch))
  return data.server
}

export async function deleteMcpServer(id: string): Promise<void> {
  await request<void>(`/mcp/servers/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export async function testMcpServer(id: string): Promise<McpCheckResult> {
  return request<McpCheckResult>(`/mcp/servers/${encodeURIComponent(id)}/test`, { method: 'POST' })
}

export async function listMcpTools(): Promise<McpToolEntry[]> {
  const data = await request<{ tools: McpToolEntry[] }>('/mcp/tools')
  return data.tools
}

// ------------------------------------------------------------------ 登录
export type AuthUser = { id: string; username: string; role: string; created_at: string | null;
  disabled?: boolean; last_login_at?: string | null }

export async function healthInfo(): Promise<{ auth_required?: boolean } & Record<string, unknown>> {
  return request<{ auth_required?: boolean } & Record<string, unknown>>('/health')
}

export async function authMe(): Promise<AuthUser | null> {
  try {
    const data = await request<{ user: AuthUser }>('/auth/me')
    return data.user
  } catch (error) {
    if (error instanceof Error && error.message.includes('未登录')) return null
    const message = error instanceof Error ? error.message : ''
    if (/40[13]/.test(message)) return null
    throw error
  }
}

export async function authLogin(username: string, password: string): Promise<AuthUser> {
  const data = await request<{ user: AuthUser }>('/auth/login', json('POST', { username, password }))
  return data.user
}

export async function authLogout(): Promise<void> {
  await request<{ ok: boolean }>('/auth/logout', { method: 'POST' })
}

export async function authRegister(username: string, password: string, code = ''): Promise<AuthUser> {
  const data = await request<{ user: AuthUser }>('/auth/register', json('POST', { username, password, code }))
  return data.user
}

// ------------------------------------------------------------------ 用户管理
export type ManagedUser = AuthUser & { disabled: boolean; last_login_at: string | null }

export async function listUsers(): Promise<ManagedUser[]> {
  const data = await request<{ users: ManagedUser[] }>('/auth/users')
  return data.users
}

export async function createUser(username: string, password: string, role: 'user' | 'admin'): Promise<ManagedUser> {
  const data = await request<{ user: ManagedUser }>('/auth/users', json('POST', { username, password, role }))
  return data.user
}

export async function updateUser(id: string, patch: { role?: 'user' | 'admin'; disabled?: boolean }): Promise<ManagedUser> {
  const data = await request<{ user: ManagedUser }>(`/auth/users/${encodeURIComponent(id)}`, json('PATCH', patch))
  return data.user
}

export async function deleteUser(id: string): Promise<void> {
  await request<void>(`/auth/users/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export async function resetUserPassword(id: string, password: string): Promise<void> {
  await request<{ user: ManagedUser }>(`/auth/users/${encodeURIComponent(id)}/password`, json('POST', { password }))
}

export async function revokeUserSessions(id: string): Promise<{ revoked: number }> {
  return request<{ revoked: number }>(`/auth/users/${encodeURIComponent(id)}/revoke`, { method: 'POST' })
}

export async function changePassword(current: string, password: string): Promise<void> {
  await request<{ ok: boolean }>('/auth/password', json('POST', { current, password }))
}
