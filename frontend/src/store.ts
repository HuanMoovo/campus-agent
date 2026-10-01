import { defineStore } from 'pinia'
import { desktop, type AppearanceMode, type WorkspaceModel } from './desktop'

export type View = 'chat' | 'services' | 'knowledge' | 'plugins' | 'settings'
export type Model = WorkspaceModel

function savedValue(key: string) {
  if (desktop) return ''
  try { return localStorage.getItem(key) || '' }
  catch { return '' }
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
    localModel: localModel(savedValue('mens-local-model')),
    appearance: appearanceMode(savedValue('mens-appearance')),
    accentColor: accentColor(savedValue('mens-accent-color')),
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
      } catch (error) {
        this.persistenceError = `无法恢复本地偏好和对话：${error instanceof Error ? error.message : '读取失败'}`
      } finally {
        this.ready = true
      }
    },
    persistWorkspace() {
      const snapshot = { model: this.model, conversationId: this.conversationId, localModel: this.localModel, appearance: this.appearance, accentColor: this.accentColor }
      pendingWrites = pendingWrites.then(async () => {
        try {
          if (desktop) await desktop.saveWorkspace(snapshot)
          else {
            localStorage.setItem('campus-agent-model', snapshot.model)
            localStorage.setItem('campus-agent-conversation-id', snapshot.conversationId)
            localStorage.setItem('mens-local-model', snapshot.localModel)
            localStorage.setItem('mens-appearance', snapshot.appearance)
            localStorage.setItem('mens-accent-color', snapshot.accentColor)
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
    setAccentColor(color: string) {
      if (!this.ready || !/^#[0-9a-f]{6}$/i.test(color)) return
      this.accentColor = accentColor(color)
      void this.persistWorkspace()
    },
  },
})
