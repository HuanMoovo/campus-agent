import type { CapabilityStatus, ModelCapability, ModelDiagnostic, ModelProvider, ModelRequestOptions } from './api'
import type { ModelCatalogEntry, ModelProtocol } from './model-providers'

export interface ModelDraft {
  api_key: string
  base_url: string
  model: string
  protocol: ModelProtocol
  request_options: ModelRequestOptions
}

export function createModelDraft(saved?: ModelProvider, preset?: ModelCatalogEntry): ModelDraft {
  const reasoningEfforts = saved?.request_options?.reasoning_efforts !== undefined
    ? saved.request_options.reasoning_efforts
    : preset?.request_options?.reasoning_efforts ?? null
  return {
    api_key: '', base_url: saved?.base_url ?? preset?.base_url ?? '', model: saved?.model || '',
    protocol: saved?.protocol ?? preset?.protocol ?? 'chat_completions',
    request_options: {
      token_parameter: saved?.request_options?.token_parameter ?? preset?.request_options?.token_parameter ?? 'max_tokens',
      send_temperature: saved?.request_options?.send_temperature ?? preset?.request_options?.send_temperature ?? true,
      supports_tools: saved?.request_options?.supports_tools ?? preset?.request_options?.supports_tools ?? true,
      supports_streaming: saved?.request_options?.supports_streaming ?? preset?.request_options?.supports_streaming ?? true,
      stream_usage: saved?.request_options?.stream_usage ?? preset?.request_options?.stream_usage ?? false,
      max_output_tokens: saved?.request_options?.max_output_tokens ?? preset?.request_options?.max_output_tokens ?? 900,
      reasoning_efforts: reasoningEfforts === null ? null : [...reasoningEfforts],
    },
  }
}

export function modelSavePayload(draft: ModelDraft) {
  const key = draft.api_key.trim()
  const reasoningEfforts = draft.protocol === 'chat_completions' || draft.protocol === 'responses'
    ? draft.request_options.reasoning_efforts ?? null
    : null
  return {
    base_url: draft.base_url.trim(), model: draft.model.trim(), protocol: draft.protocol,
    request_options: { ...draft.request_options, stream_usage: draft.protocol === 'chat_completions' && Boolean(draft.request_options.stream_usage), reasoning_efforts: reasoningEfforts === null ? null : [...reasoningEfforts] },
    ...(key ? { api_key: key } : {}),
  }
}

export function isModelDraftDirty(draft: ModelDraft, saved?: ModelProvider, preset?: ModelCatalogEntry): boolean {
  return JSON.stringify(modelSavePayload(draft)) !== JSON.stringify(modelSavePayload(createModelDraft(saved, preset)))
}

export function modelHostChangeNeedsKey(draft: ModelDraft, saved?: ModelProvider): boolean {
  if (!(saved?.api_key_set ?? saved?.configured) || draft.api_key.trim()) return false
  try {
    const previous = new URL(saved!.base_url)
    const next = new URL(draft.base_url.trim())
    if (previous.protocol !== 'https:' || next.protocol !== 'https:') return false
    return previous.hostname.toLowerCase() !== next.hostname.toLowerCase()
      || (previous.port || '443') !== (next.port || '443')
  } catch { return false }
}

export function diagnosticCapabilities(result: ModelDiagnostic, capability: ModelCapability): Record<ModelCapability, CapabilityStatus> {
  const statuses: Record<ModelCapability, CapabilityStatus> = { chat: 'not_tested', streaming: 'not_tested', tools: 'not_tested' }
  // Configuration switches describe compatibility preferences, never evidence.
  statuses[capability] = result.ok ? 'verified' : 'not_verified'
  return statuses
}

export function safeModelEndpoint(value: string): string {
  try {
    const url = new URL(value)
    return `${url.origin}${url.pathname}`
  } catch { return '' }
}
