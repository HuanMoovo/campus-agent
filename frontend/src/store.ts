import { defineStore } from 'pinia'
import { desktop, type AppearanceMode, type DesktopWorkspace, type WorkspaceModel, type ProjectPermission } from './desktop'
import { isWorkspaceModel } from './model-providers'
import { normalizeReasoning, type ReasoningPreference } from './reasoning'
import { t } from './i18n'

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
  return isWorkspaceModel(value) ? value : 'auto'
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

function savedReasoning(): ReasoningPreference {
  return normalizeReasoning(savedValue('campus-agent-reasoning'))
}

function localModel(value: unknown) {
  return typeof value === 'string' && value.length <= 128 && !/[\x00-\x1f\x7f]/.test(value) ? value : ''
}

function projectPermission(value: unknown): ProjectPermission {
  return desktop && value !== 'read_only' ? 'confirm' : 'read_only'
}

// Serialize writes so quick model changes cannot overwrite a newer conversation.
let pendingWrites = Promise.resolve()
let pendingInitialization: Promise<void> | null = null
const pendingPermissionWrites = new Set<Promise<void>>()

function enqueueWorkspaceWrite(state: DesktopWorkspace & { workspacePersistenceError: string }): Promise<void> {
  const snapshot = { model: state.model, conversationId: state.conversationId, clientId: state.clientId, localModel: state.localModel, appearance: state.appearance, accentColor: state.accentColor, webSearch: state.webSearch, reasoning: state.reasoning, projectPermission: state.projectPermission, onboardingDone: state.onboardingDone }
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
        localStorage.setItem('mens-project-permission', snapshot.projectPermission)
      }
      state.workspacePersistenceError = ''
    } catch (error) {
      state.workspacePersistenceError = `无法保存偏好和对话，下次启动可能无法恢复：${error instanceof Error ? error.message : '写入失败'}`
    }
  })
  return pendingWrites
}

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
    projectPermission: projectPermission(savedValue('mens-project-permission')),
    onboardingDone: Boolean(savedValue('mens-onboarding-done')),
    ready: !desktop,
    workspacePersistenceError: '',
    projectPermissionError: '',
    projectPermissionRevision: 0,
  }),
  getters: {
    persistenceError: state => state.workspacePersistenceError || state.projectPermissionError,
  },
  actions: {
    async initialize(): Promise<void> {
      if (!desktop || this.ready) return
      if (pendingInitialization) return pendingInitialization
      pendingInitialization = (async () => {
        try {
          const saved = await desktop.loadWorkspace()
          this.model = isWorkspaceModel(saved.model) ? saved.model : 'auto'
          this.conversationId = typeof saved.conversationId === 'string' ? saved.conversationId : ''
          this.localModel = localModel(saved.localModel)
          this.appearance = appearanceMode(saved.appearance)
          this.accentColor = accentColor(saved.accentColor)
          this.webSearch = saved.webSearch === true
          this.reasoning = normalizeReasoning(saved.reasoning)
          this.projectPermission = projectPermission(saved.projectPermission)
          this.onboardingDone = saved.onboardingDone === true
          this.clientId = validClientId(saved.clientId) || newClientId()
          this.workspacePersistenceError = ''
          await enqueueWorkspaceWrite(this)
          this.ready = true
        } catch (error) {
          this.workspacePersistenceError = `无法恢复本地偏好和对话：${error instanceof Error ? error.message : '读取失败'}。原有数据已保留，请重试恢复。`
        }
      })()
      try { await pendingInitialization }
      finally { pendingInitialization = null }
    },
    async persistWorkspace(): Promise<void> {
      // The existing retry action must restore the saved identity before any write.
      if (desktop && !this.ready) return this.initialize()
      if (desktop && this.projectPermissionError) await this.setProjectPermission(this.projectPermission)
      return enqueueWorkspaceWrite(this)
    },
    async flushWorkspace() {
      await pendingInitialization
      await pendingWrites
      await Promise.all([...pendingPermissionWrites])
      return this.ready && !this.persistenceError
    },
    async completeOnboarding() {
      if (!this.ready) return
      this.onboardingDone = true
      if (desktop) await this.persistWorkspace()
      else {
        try { localStorage.setItem('mens-onboarding-done', '1') } catch { /* private browsing */ }
      }
    },
    setModel(model: Model) {
      if (!this.ready || !isWorkspaceModel(model)) return
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
    setReasoning(value: ReasoningPreference) {
      if (!this.ready) return
      this.reasoning = normalizeReasoning(value)
      void this.persistWorkspace()
    },
    setProjectPermission(value: ProjectPermission): Promise<void> {
      if (!this.ready || !['read_only', 'confirm'].includes(value)) return Promise.resolve()
      if (!desktop) {
        this.projectPermission = 'read_only'
        return enqueueWorkspaceWrite(this)
      }
      const revision = ++this.projectPermissionRevision
      if (value === 'read_only') this.projectPermission = 'read_only'
      let result: ReturnType<typeof desktop.setProjectPermission>
      try {
        // Send revocation immediately, outside the ordinary preference write queue.
        result = desktop.setProjectPermission(value)
      } catch { result = Promise.reject(new Error('Permission bridge unavailable')) }
      const write = Promise.resolve(result).then(response => {
        if (revision !== this.projectPermissionRevision) return
        if (!response || !['confirm', 'read_only'].includes(response.projectPermission) || typeof response.persisted !== 'boolean') throw new Error('Invalid permission response')
        this.projectPermission = response.projectPermission === 'confirm' && response.persisted ? 'confirm' : 'read_only'
        this.projectPermissionError = response.persisted ? '' : t('chat.projectPermissionSaveFailed')
      }).catch(() => {
        if (revision !== this.projectPermissionRevision) return
        this.projectPermission = 'read_only'
        this.projectPermissionError = t('chat.projectPermissionSaveFailed')
      }).finally(() => { pendingPermissionWrites.delete(write) })
      pendingPermissionWrites.add(write)
      return write
    },
    setAccentColor(color: string) {
      if (!this.ready || !/^#[0-9a-f]{6}$/i.test(color)) return
      this.accentColor = accentColor(color)
      void this.persistWorkspace()
    },
  },
})
