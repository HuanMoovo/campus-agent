import { defineStore } from 'pinia'
import { desktop, type AppearanceMode, type WorkspaceModel } from './desktop'

export type View = 'chat' | 'services' | 'knowledge' | 'plugins' | 'settings' | 'mcp' | 'account'
export type Model = WorkspaceModel

function savedValue(key: string) {
  if (desktop) return ''
  try { return localStorage.getItem(key) || '' }
  catch { return '' }
}

function newClientId() {
  try { return crypto.randomUUID() }
  catch { return `mens-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}` }
}

function validClientId(value: unknown): string {
  return typeof value === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(value) ? value : ''
}

function initialClientId() {
  const stored = validClientId(savedValue('mens-client-id'))
  if (stored) return stored
  const created = newClientId()
  if (!desktop) {
    try { localStorage.setItem('mens-client-id', created) } catch { /* storage unavailable */ }
    return created
  }
  return ''
}

function savedModel(): Model {
  const value = savedValue('campus-agent-model')
  return value === 'qwen3' || value === 'deepseek' || value === 'ollama' ? value : 'auto'
}

function appearanceMode(value: unknown): AppearanceMode {
  return value === 'light' || value === 'dark' ? value : 'system'
}

function accentColor(value: unknown) {
  return typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value) ? value.toLowerCase() : '#147b75'
}

function savedWebSearch() {
  return savedValue('campus-agent-web-search') === '1'
}

function savedReasoning(): 'fast' | 'deep' {
  return savedValue('campus-agent-reasoning') === 'deep' ? 'deep' : 'fast'
}

function localModel(value: unknown) {
  return typeof value === 'string' && value.length <= 128 && !/[\x00-\x1f\x7f]/.test(value) ? value : ''
}

// Serialize writes so quick model changes cannot overwrite a newer conversation.
let pendingWrites = Promise.resolve()

export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({
    view: 'chat' as View,
    model: savedModel(),
    conversationId: savedValue('campus-agent-conversation-id'),
    clientId: initialClientId(),
    localModel: localModel(savedValue('mens-local-model')),
    appearance: appearanceMode(savedValue('mens-appearance')),
    accentColor: accentColor(savedValue('mens-accent-color')),
    webSearch: savedWebSearch(),
    reasoning: savedReasoning(),
    ready: !desktop,
    persistenceError: '',
  }),
  actions: {
    async initialize() {
      if (!desktop || this.ready) return
      try {
        const saved = await desktop.loadWorkspace()
        this.model = saved.model === 'qwen3' || saved.model === 'deepseek' || saved.model === 'ollama' ? saved.model : 'auto'
        this.conversationId = typeof saved.conversationId === 'string' ? saved.conversationId : ''
        this.localModel = localModel(saved.localModel)
        this.appearance = appearanceMode(saved.appearance)
        this.accentColor = accentColor(saved.accentColor)
        this.webSearch = saved.webSearch === true
        this.reasoning = saved.reasoning === 'deep' ? 'deep' : 'fast'
        this.clientId = validClientId(saved.clientId) || newClientId()
      } catch (error) {
        this.persistenceError = `无法恢复本地偏好和对话：${error instanceof Error ? error.message : '读取失败'}`
      } finally {
        this.ready = true
        if (!validClientId(this.clientId)) this.clientId = newClientId()
        void this.persistWorkspace()
      }
    },
    persistWorkspace() {
      const snapshot = { model: this.model, conversationId: this.conversationId, clientId: this.clientId, localModel: this.localModel, appearance: this.appearance, accentColor: this.accentColor, webSearch: this.webSearch, reasoning: this.reasoning }
      pendingWrites = pendingWrites.then(async () => {
        try {
          if (desktop) await desktop.saveWorkspace(snapshot)
          else {
            localStorage.setItem('campus-agent-model', snapshot.model)
            localStorage.setItem('campus-agent-conversation-id', snapshot.conversationId)
            localStorage.setItem('mens-client-id', snapshot.clientId)
            localStorage.setItem('mens-local-model', snapshot.localModel)
            localStorage.setItem('mens-appearance', snapshot.appearance)
            localStorage.setItem('mens-accent-color', snapshot.accentColor)
            localStorage.setItem('campus-agent-web-search', snapshot.webSearch ? '1' : '0')
            localStorage.setItem('campus-agent-reasoning', snapshot.reasoning)
          }
          this.persistenceError = ''
        } catch (error) {
          this.persistenceError = `无法保存偏好和对话，下次启动可能无法恢复：${error instanceof Error ? error.message : '写入失败'}`
        }
      })
      return pendingWrites
    },
    async flushWorkspace() {
      await pendingWrites
      return !this.persistenceError
    },
    setModel(model: Model) {
      if (!this.ready) return
      this.model = model
      void this.persistWorkspace()
    },
    setConversationId(id: string) {
      if (!this.ready) return
      this.conversationId = id
      void this.persistWorkspace()
    },
    setLocalModel(name: string) {
      if (!this.ready || !localModel(name)) return
      this.localModel = name
      this.model = 'ollama'
      void this.persistWorkspace()
    },
    setAppearance(mode: AppearanceMode) {
      if (!this.ready) return
      this.appearance = appearanceMode(mode)
      void this.persistWorkspace()
    },
    setWebSearch(enabled: boolean) {
      if (!this.ready) return
      this.webSearch = Boolean(enabled)
      void this.persistWorkspace()
    },
    setReasoning(value: 'fast' | 'deep') {
      if (!this.ready) return
      this.reasoning = value === 'deep' ? 'deep' : 'fast'
      void this.persistWorkspace()
    },
    setAccentColor(color: string) {
      if (!this.ready || !/^#[0-9a-f]{6}$/i.test(color)) return
      this.accentColor = accentColor(color)
      void this.persistWorkspace()
    },
  },
})
