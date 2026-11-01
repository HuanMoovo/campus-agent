import type { ModelConfig, ModelRequestOptions } from './api'

export const CLOUD_MODEL_IDS = ['qwen', 'deepseek', 'openai_compatible', 'openai_responses', 'anthropic', 'gemini', 'zhipu', 'moonshot', 'doubao', 'siliconflow', 'hunyuan', 'qianfan', 'minimax', 'stepfun', 'spark', 'yi', 'xiaomi', 'zai', 'xai', 'openrouter', 'groq', 'mistral', 'together', 'fireworks', 'deepinfra', 'cerebras', 'huggingface', 'cohere'] as const
export type CloudModelProvider = typeof CLOUD_MODEL_IDS[number]
export type ModelProtocol = 'chat_completions' | 'responses' | 'anthropic' | 'gemini'
export type WorkspaceModel = 'auto' | 'qwen3' | Exclude<CloudModelProvider, 'qwen'> | 'ollama'
export interface ModelCatalogEntry {
  id: CloudModelProvider
  label: string
  protocol: ModelProtocol
  base_url: string
  docs_url: string
  note: string
  region?: 'china' | 'global' | 'custom'
  request_options?: Partial<ModelRequestOptions>
  auth_header?: string
}

export const MODEL_PROTOCOLS: { id: ModelProtocol; label: string }[] = [
  { id: 'chat_completions', label: 'Chat Completions' }, { id: 'responses', label: 'OpenAI Responses' },
  { id: 'anthropic', label: 'Anthropic Messages' }, { id: 'gemini', label: 'Gemini generateContent' },
]

export function isCloudModelProvider(value: unknown): value is CloudModelProvider {
  return typeof value === 'string' && (CLOUD_MODEL_IDS as readonly string[]).includes(value)
}
export function isWorkspaceModel(value: unknown): value is WorkspaceModel {
  return value === 'auto' || value === 'ollama' || value === 'qwen3' || (value !== 'qwen' && isCloudModelProvider(value))
}
export function workspaceModelForProvider(id: CloudModelProvider): WorkspaceModel { return id === 'qwen' ? 'qwen3' : id }
export function modelForApi(model: string): string { return model === 'qwen3' ? 'qwen' : model }

const LEGACY_CATALOG: ModelCatalogEntry[] = [
  { id: 'qwen', label: 'Qwen', protocol: 'chat_completions', base_url: '', docs_url: '', note: '', region: 'china' },
  { id: 'deepseek', label: 'DeepSeek', protocol: 'chat_completions', base_url: '', docs_url: '', note: '', region: 'china' },
  { id: 'openai_compatible', label: 'OpenAI compatible', protocol: 'chat_completions', base_url: '', docs_url: '', note: '' },
]

export function modelCatalog(config?: ModelConfig | null): ModelCatalogEntry[] {
  const source = config?.catalog ?? LEGACY_CATALOG
  const seen = new Set<string>()
  return source.filter(item => {
    if (!isCloudModelProvider(item.id) || seen.has(item.id)) return false
    seen.add(item.id)
    return true
  })
}
export function providerGroups(config?: ModelConfig | null) {
  const entries = modelCatalog(config)
  return (['china', 'global', 'custom'] as const).map(id => ({ id, entries: entries.filter(entry => (entry.region || 'custom') === id) })).filter(group => group.entries.length)
}
export function officialDocsUrl(entry?: ModelCatalogEntry): string {
  try {
    const url = new URL(entry?.docs_url || '')
    return url.protocol === 'https:' && !url.username && !url.password ? url.href : ''
  } catch { return '' }
}
