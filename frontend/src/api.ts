import { desktop } from './desktop'
import type { ChatAttachment } from './attachments'
import type { ProjectSelection, ProjectStatus, ProjectListing, ProjectExcerpt } from './project-files'
import { ProjectProposalError, type ProjectProposal, type ProjectProposalRequest } from './project-proposals'
import { readAgentMetadata } from './agent-diagnostics'
import { modelForApi, type CloudModelProvider, type ModelCatalogEntry, type ModelProtocol } from './model-providers'
export type { CloudModelProvider, ModelProtocol } from './model-providers'

export type ChatPhase = 'preparing' | 'querying' | 'answering'

export interface ContextReport {
  limit_chars: number
  input_chars: number
  history_available: number
  history_used: number
  history_omitted: number
  sources_used: number
  sources_omitted: number
  sources_truncated: number
  attachments_used: number
  attachments_truncated: number
  trimmed: boolean
}

export interface CampusReadTask {
  kind: 'campus_reads'
  limit_steps: 3
  planned_steps: number
  attempted_steps: number
  completed_steps: number
  limit_ms: 20000
  stop_reason: 'completed' | 'step_limit' | 'deadline' | 'cancelled' | 'tool_error' | 'invalid_request'
  truncated_results: number
}

export interface AgentRun {
  id: string
  status: 'running' | 'completed' | 'partial' | 'failed'
  duration_ms: number
  steps: Array<{ phase: 'plan' | 'retrieve' | 'tool' | 'answer'; status: 'completed' | 'failed'; duration_ms: number }>
  task?: CampusReadTask
}

export interface Source {
  title: string
  snippet?: string
  source?: string
  score?: number
  url?: string
  kind?: string
  path?: string
  start_line?: number
  end_line?: number
  truncated?: boolean
  excerpt_sha256?: string
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
  context?: ContextReport
  run?: AgentRun
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
  models: Record<string, boolean | undefined>
  demo_services: boolean
}

export interface ConversationHistory {
  id: string
  messages: Array<{ id?: number; role: 'user' | 'assistant'; content: string; created_at: string; sources?: Source[]; tool_calls?: Array<{ name: string }>; mode?: string; partial?: boolean; thinking?: string; feedback?: 'up' | 'down'; context?: ContextReport; run?: AgentRun }>
}

export interface Plugin {
  id: string
  name: string
  description?: string
  enabled: boolean
  url?: string
  parameters?: Record<string, unknown>
}

export type ModelCapability = 'chat' | 'streaming' | 'tools'
export type CapabilityStatus = 'verified' | 'not_tested' | 'not_verified'

export interface ModelRequestOptions {
  token_parameter: 'max_tokens' | 'max_completion_tokens'
  send_temperature: boolean
  supports_tools: boolean
  supports_streaming: boolean
  stream_usage?: boolean
  max_output_tokens?: number
  reasoning_efforts?: import('./reasoning').ReasoningLevel[] | null
}

export interface ModelDiagnostic {
  ok: boolean
  error?: string
  error_code?: string
  http_status?: number
  latency_ms?: number
  provider?: string
  model?: string
  protocol?: string
  capability?: ModelCapability
  capabilities?: Record<ModelCapability, CapabilityStatus>
  hint?: string
}

export interface ModelProvider {
  configured: boolean
  api_key_set?: boolean
  base_url: string
  model: string
  protocol?: ModelProtocol
  request_options?: ModelRequestOptions
  reasoning?: import('./reasoning').ReasoningCapability
}

export interface ModelConfig {
  providers: Record<'qwen' | 'deepseek' | 'openai_compatible', ModelProvider> & Partial<Record<CloudModelProvider, ModelProvider>>
  catalog?: ModelCatalogEntry[]
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

export interface ConversationSummary {
  id: string
  title: string
  message_count: number
  updated_at: string
  pinned?: boolean
}

export interface ConversationSearchResult {
  conversation_id: string
  title: string
  snippet: string
  matches: number
}

export interface ChatStreamCallbacks {
  onMeta?: (conversationId: string) => void
  onStatus?: (phase: ChatPhase, metadata: Partial<ChatResponse>) => void
  onThinking?: (text: string) => void
  onDelta?: (text: string) => void
}

export class ChatStreamError extends Error {
  partial: string
  metadata: Partial<ChatResponse>

  constructor(message: string, partial: string, metadata: Partial<ChatResponse> = {}) {
    super(message)
    this.name = 'ChatStreamError'
    this.partial = partial
    this.metadata = metadata
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
    return data && typeof data === 'object' && !Array.isArray(data) ? { event, data } : null
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

function chatPayload(message: string, conversationId: string, model: string, localModel: string | undefined, clientId: string, web = false, reasoning: import('./reasoning').ReasoningPreference | 'fast' = 'auto', regenerate = false, attachments: ChatAttachment[] = [], project?: ProjectSelection) {
  return {
    message,
    conversation_id: conversationId || undefined,
    model: modelForApi(model),
    client_id: clientId || undefined,
    ...(web ? { web: true } : {}),
    ...(reasoning !== 'auto' && reasoning !== 'fast' ? { reasoning } : {}),
    ...(regenerate ? { regenerate: true } : {}),
    ...(attachments.length ? { attachments } : {}),
    ...(project?.files.length ? { project: { id: project.id, files: [...project.files] } } : {}),
    ...(model === 'ollama' && localModel ? { local_model: localModel } : {}),
  }
}

function responseError(status: number, detail: string) {
  return new Error(detail || `请求失败 (${status})`)
}

/** Streams an answer over SSE; aborts by passing signal.abort(), partial text is kept by the caller. */
export async function chatStream(
  payload: { message: string; conversationId: string; model: string; localModel?: string; clientId: string; web?: boolean; reasoning?: import('./reasoning').ReasoningPreference | 'fast'; regenerate?: boolean; attachments?: ChatAttachment[]; project?: ProjectSelection },
  callbacks: ChatStreamCallbacks,
  signal: AbortSignal,
): Promise<ChatResponse> {
  let response: Response
  try {
    response = await fetch(`${base}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(chatPayload(payload.message, payload.conversationId, payload.model, payload.localModel, payload.clientId, payload.web, payload.reasoning, payload.regenerate, payload.attachments, payload.project)),
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
  let metadata: Partial<ChatResponse> = {}
  let receivedOutput = false
  const interruptedMetadata = () => metadata.run?.status === 'running'
    ? { ...metadata, run: { ...metadata.run, status: receivedOutput ? 'partial' as const : 'failed' as const } }
    : metadata
  try {
    readFrames: for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const frame = parseSseFrame(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
        if (!frame) continue
        if (['meta', 'status', 'done', 'error'].includes(frame.event)) {
          metadata = { ...metadata, ...readAgentMetadata(frame.data) }
        }
        if (frame.event === 'meta') {
          const id = frame.data.conversation_id
          if (typeof id === 'string' && id) callbacks.onMeta?.(id)
        } else if (frame.event === 'status') {
          const phase = frame.data.phase
          if (phase === 'preparing' || phase === 'querying' || phase === 'answering') callbacks.onStatus?.(phase, metadata)
        } else if (frame.event === 'thinking') {
          const text = frame.data.text
          if (typeof text === 'string' && text) {
            receivedOutput = true
            callbacks.onThinking?.(text)
          }
        } else if (frame.event === 'delta') {
          const text = frame.data.text
          if (typeof text === 'string' && text) {
            receivedOutput = true
            answer += text
            callbacks.onDelta?.(text)
          }
        } else if (frame.event === 'done') {
          final = {
            ...metadata,
            conversation_id: metadata.conversation_id || '',
            answer: typeof frame.data.answer === 'string' ? frame.data.answer : answer,
            sources: metadata.sources || [],
            mode: typeof frame.data.mode === 'string' ? frame.data.mode : 'demo',
          }
          break readFrames
        } else if (frame.event === 'error') {
          failure = typeof frame.data.message === 'string' && frame.data.message ? frame.data.message : '生成失败，请重试。'
          const partial = frame.data.partial
          if (typeof partial === 'string' && partial) answer = partial
          break readFrames
        }
      }
    }
  } catch {
    throw new ChatStreamError(t('chat.streamInterrupted'), answer, interruptedMetadata())
  } finally {
    try { await reader.cancel() } catch { /* transport may already be closed */ }
    try { reader.releaseLock() } catch { /* the stream already closed */ }
  }
  if (failure) throw new ChatStreamError(failure, answer, interruptedMetadata())
  if (!final) throw new ChatStreamError(t('chat.streamInterrupted'), answer, interruptedMetadata())
  return final
}

async function projectProposalRequest(path: string, init?: RequestInit): Promise<ProjectProposal> {
  let response: Response
  try { response = await fetch(`${base}${path}`, init) }
  catch { throw new ProjectProposalError('project_service_unavailable', 0) }
  if (!response.ok) {
    const code = response.headers.get('X-Project-Error') || 'project_proposal_request_failed'
    throw new ProjectProposalError(code, response.status)
  }
  try { return await response.json() as ProjectProposal }
  catch { throw new ProjectProposalError('project_proposal_invalid_result', 502) }
}

export const api = {
  projects: () => request<ProjectStatus>('/projects'),
  projectFiles: (id: string, path = '') => request<ProjectListing>(`/projects/${encodeURIComponent(id)}/files?path=${encodeURIComponent(path)}`),
  projectRead: (id: string, path: string) => request<ProjectExcerpt>(`/projects/${encodeURIComponent(id)}/read`, json('POST', { path })),
  projectPropose: (id: string, proposal: ProjectProposalRequest) => projectProposalRequest(`/projects/${encodeURIComponent(id)}/proposals`, json('POST', {
    path: proposal.path,
    instruction: proposal.instruction,
    model: modelForApi(proposal.model),
    ...(proposal.model === 'ollama' && proposal.localModel ? { local_model: proposal.localModel } : {}),
    ...(proposal.reasoning && !['auto', 'fast'].includes(proposal.reasoning) ? { reasoning: proposal.reasoning } : {}),
  })),
  projectProposal: (id: string, proposalId: string) => projectProposalRequest(`/projects/${encodeURIComponent(id)}/proposals/${encodeURIComponent(proposalId)}`),
  closeProject: (id: string) => request<{ ok: boolean }>(`/projects/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  health: () => request<Health>('/health'),
  conversation: (id: string, clientId: string) => request<ConversationHistory>(`/conversations/${encodeURIComponent(id)}?client_id=${encodeURIComponent(clientId)}`),
  conversations: (clientId: string, limit = 50) =>
    request<ConversationSummary[]>(`/conversations?client_id=${encodeURIComponent(clientId)}&limit=${limit}`),
  deleteConversation: (id: string, clientId: string) =>
    request<{ deleted: boolean }>(`/conversations/${encodeURIComponent(id)}?client_id=${encodeURIComponent(clientId)}`, { method: 'DELETE' }),
  clearConversations: (clientId: string) =>
    request<{ deleted: number }>(`/conversations?client_id=${encodeURIComponent(clientId)}`, { method: 'DELETE' }),
  setFeedback: (conversationId: string, messageId: number, value: 'up' | 'down' | null, clientId: string) =>
    request<{ ok: boolean; feedback: string | null }>(`/conversations/${encodeURIComponent(conversationId)}/messages/${messageId}/feedback?client_id=${encodeURIComponent(clientId)}`, json('POST', { value })),
  searchConversations: (clientId: string, q: string) =>
    request<ConversationSearchResult[]>(`/conversations/search?client_id=${encodeURIComponent(clientId)}&q=${encodeURIComponent(q)}`),
  updateConversation: (id: string, clientId: string, patch: { title?: string; pinned?: boolean }) =>
    request<{ id: string; title: string | null; pinned: boolean }>(`/conversations/${encodeURIComponent(id)}?client_id=${encodeURIComponent(clientId)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) }),
  batchDeleteConversations: (ids: string[], clientId: string) =>
    request<{ deleted: number }>('/conversations/batch-delete', json('POST', { ids, client_id: clientId })),
  extractAttachment: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<{ name: string; text: string }>('/chat/attachments/extract', { method: 'POST', body: form })
  },
  chat: (message: string, conversationId: string, model: string, localModel?: string, clientId = '', web = false, project?: ProjectSelection) =>
    request<ChatResponse>('/chat', json('POST', chatPayload(message, conversationId, model, localModel, clientId, web, 'fast', false, [], project))),
  webStatus: () => request<WebStatus>('/web/status'),
  saveWebConfig: (values: { enabled?: boolean; provider?: string; api_key?: string; max_results?: number; fetch_pages?: number }) =>
    request<WebStatus>('/web/config', json('PUT', values)),
  modelConfig: () => request<ModelConfig>('/models/config'),
  saveModelConfig: (provider: CloudModelProvider | 'ollama', values: { api_key?: string; clear_api_key?: boolean; base_url?: string; model?: string; protocol?: ModelProtocol; request_options?: ModelRequestOptions }) =>
    request<ModelConfig>(`/models/config/${provider}`, json('PUT', values)),
  testModel: (provider: CloudModelProvider, capability: ModelCapability = 'chat') => request<ModelDiagnostic>(`/models/test/${provider}`, json('POST', { capability })),
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
  exportConversation: async (id: string, format: 'md' | 'json', clientId: string) => {
    let response: Response
    try {
      response = await fetch(`${base}/conversations/${encodeURIComponent(id)}/export?format=${format}&client_id=${encodeURIComponent(clientId)}`)
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
  exportBackup: async (includeProjectRecoveries = false) => {
    const headers = new Headers()
    if (!desktop) headers.set('X-Admin-Token', sessionStorage.getItem('campus-agent-admin-token') || '')
    let response: Response
    try {
      response = await fetch(`${base}/backup/export${includeProjectRecoveries ? '?include_project_recoveries=true' : ''}`, { headers })
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
    return request<{ restored: string[]; failed: string[]; restart_required: boolean; project_recoveries?: { imported: number; duplicates: number } }>('/backup/import', { method: 'POST', body: form })
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
