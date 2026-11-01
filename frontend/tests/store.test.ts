import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { CampusDesktop, DesktopWorkspace } from '../src/desktop'
import { CLOUD_MODEL_IDS, workspaceModelForProvider } from '../src/model-providers'

const bridge = vi.hoisted(() => ({
  desktop: undefined as (Pick<CampusDesktop, 'loadWorkspace' | 'saveWorkspace'> & Partial<Pick<CampusDesktop, 'setProjectPermission'>>) | undefined,
}))
vi.mock('../src/desktop', () => bridge)

import { useWorkspaceStore } from '../src/store'

function freshStore() {
  setActivePinia(createPinia())
  return useWorkspaceStore()
}

describe('workspace store', () => {
  beforeEach(() => {
    localStorage.clear()
    bridge.desktop = undefined
  })

  it('generates and persists a client id the backend accepts', () => {
    const store = freshStore()
    expect(store.clientId).toMatch(/^[A-Za-z0-9_-]{1,64}$/)
    expect(localStorage.getItem('mens-client-id')).toBe(store.clientId)
  })

  it('keeps web projects read-only even when a stale write preference is stored or requested', async () => {
    localStorage.setItem('mens-project-permission', 'confirm')
    const store = freshStore()
    expect(store.projectPermission).toBe('read_only')
    store.setProjectPermission('confirm')
    await store.flushWorkspace()
    expect(store.projectPermission).toBe('read_only')
    expect(localStorage.getItem('mens-project-permission')).toBe('read_only')
  })

  it.each([undefined, 'legacy-unknown', 'confirm', 'read_only'])('restores and persists desktop permission %s', async value => {
    const disk = { model: 'auto', clientId: 'fixture-client', projectPermission: value }
    bridge.desktop = {
      async loadWorkspace() { return disk as DesktopWorkspace },
      async saveWorkspace(value) { Object.assign(disk, value) },
      async setProjectPermission(projectPermission) { disk.projectPermission = projectPermission; return { projectPermission, persisted: true } },
    }
    const store = freshStore(); await store.initialize()
    expect(store.projectPermission).toBe(value === 'read_only' ? 'read_only' : 'confirm')
    store.setProjectPermission('read_only'); await store.flushWorkspace()
    expect(disk.projectPermission).toBe('read_only')
    store.setProjectPermission('full_access' as never); await store.flushWorkspace()
    expect(store.projectPermission).toBe('read_only')
    store.setProjectPermission('confirm'); await store.flushWorkspace()
    expect(disk.projectPermission).toBe('confirm')
    const restored = freshStore(); await restored.initialize(); expect(restored.projectPermission).toBe('confirm')
  })

  it('revokes immediately ahead of queued workspace saves and retains permission persistence errors', async () => {
    let mode = 'confirm' as 'confirm' | 'read_only'
    let blockSave = false; let release!: () => void
    const blocked = new Promise<void>(resolve => { release = resolve })
    const setter = vi.fn(async (value: 'confirm' | 'read_only') => { mode = value; return { projectPermission: mode, persisted: false } })
    bridge.desktop = {
      async loadWorkspace() { return { model: 'auto', clientId: 'fixture-client', projectPermission: mode } as DesktopWorkspace },
      async saveWorkspace() { if (blockSave) await blocked }, setProjectPermission: setter,
    }
    const store = freshStore(); await store.initialize(); blockSave = true
    store.setModel('qwen3'); await Promise.resolve(); store.setReasoning('high')
    store.setProjectPermission('read_only')
    try {
      expect(setter).toHaveBeenCalledWith('read_only'); expect(mode).toBe('read_only'); expect(store.projectPermission).toBe('read_only')
    } finally { release() }
    await Promise.resolve(); release()
    expect(await store.flushWorkspace()).toBe(false)
    expect(store.persistenceError).not.toBe('')
    expect(store.projectPermission).toBe('read_only')
  })

  it('does not promote before successful persistence or apply a late permission response', async () => {
    let resolveConfirm!: (value: { projectPermission: 'confirm'; persisted: boolean }) => void
    const confirmation = new Promise<{ projectPermission: 'confirm'; persisted: boolean }>(resolve => { resolveConfirm = resolve })
    bridge.desktop = {
      async loadWorkspace() { return { model: 'auto', clientId: 'fixture-client', projectPermission: 'read_only' } as DesktopWorkspace },
      async saveWorkspace() {},
      setProjectPermission(value) { return value === 'confirm' ? confirmation : Promise.resolve({ projectPermission: 'read_only', persisted: true }) },
    }
    const store = freshStore(); await store.initialize()
    store.setProjectPermission('confirm'); expect(store.projectPermission).toBe('read_only')
    store.setProjectPermission('read_only'); await Promise.resolve()
    resolveConfirm({ projectPermission: 'confirm', persisted: true }); await store.flushWorkspace()
    expect(store.projectPermission).toBe('read_only')
    bridge.desktop.setProjectPermission = async () => ({ projectPermission: 'read_only', persisted: false })
    await store.setProjectPermission('confirm'); expect(await store.flushWorkspace()).toBe(false)
    expect(store.projectPermission).toBe('read_only')
  })

  it('keeps a stored client id across sessions', () => {
    localStorage.setItem('mens-client-id', 'kept-client-id')
    expect(freshStore().clientId).toBe('kept-client-id')
  })

  it('replaces malformed stored client ids', () => {
    localStorage.setItem('mens-client-id', '../escape')
    const store = freshStore()
    expect(store.clientId).not.toBe('../escape')
    expect(store.clientId).toMatch(/^[A-Za-z0-9_-]{1,64}$/)
  })

  it('persists model, conversation and accent choices for the web deployment', async () => {
    const store = freshStore()
    store.setModel('deepseek')
    store.setConversationId('c-1')
    store.setAccentColor('#A1B2C3')
    store.setAccentColor('not-a-colour')
    await store.flushWorkspace()
    expect(localStorage.getItem('campus-agent-model')).toBe('deepseek')
    expect(localStorage.getItem('campus-agent-conversation-id')).toBe('c-1')
    expect(localStorage.getItem('mens-accent-color')).toBe('#a1b2c3')
    expect(store.accentColor).toBe('#a1b2c3')
  })

  it('restores a selected OpenAI-compatible model after a reload', async () => {
    const store = freshStore()
    store.setModel('openai_compatible')
    await store.flushWorkspace()
    expect(localStorage.getItem('campus-agent-model')).toBe('openai_compatible')
    expect(freshStore().model).toBe('openai_compatible')
  })

  it('remembers the per-user web search preference', async () => {
    const store = freshStore()
    expect(store.webSearch).toBe(false)
    store.setWebSearch(true)
    await store.flushWorkspace()
    expect(localStorage.getItem('campus-agent-web-search')).toBe('1')
    store.setWebSearch(false)
    await store.flushWorkspace()
    expect(localStorage.getItem('campus-agent-web-search')).toBe('0')
    localStorage.setItem('campus-agent-web-search', '1')
    expect(freshStore().webSearch).toBe(true)
  })

  it.each(CLOUD_MODEL_IDS.map(workspaceModelForProvider))('persists and restores %s on web and desktop', async model => {
    const store = freshStore()
    store.setModel(model)
    await store.flushWorkspace()
    expect(freshStore().model).toBe(model)
    const disk: DesktopWorkspace = { model, conversationId: '', clientId: 'saved-client', localModel: '', appearance: 'system', accentColor: '#147b75', webSearch: false, reasoning: 'fast', projectPermission: 'confirm' }
    bridge.desktop = { async loadWorkspace() { return disk }, async saveWorkspace(value) { Object.assign(disk, value) } }
    const restored = freshStore()
    await restored.initialize()
    expect(restored.model).toBe(model)
    expect(disk.model).toBe(model)
  })

  it('remembers the per-user reasoning effort preference', async () => {
    const store = freshStore()
    expect(store.reasoning).toBe('auto')
    store.setReasoning('deep')
    await store.flushWorkspace()
    expect(localStorage.getItem('campus-agent-reasoning')).toBe('deep')
    store.setReasoning('odd' as never)
    await store.flushWorkspace()
    expect(store.reasoning).toBe('auto')
    localStorage.setItem('campus-agent-reasoning', 'deep')
    expect(freshStore().reasoning).toBe('deep')
  })

  it.each(['auto', 'low', 'medium', 'high', 'xhigh', 'max'] as const)('saves and restores the Codex-style %s reasoning preference', async level => {
    const store = freshStore()
    store.setReasoning(level as never)
    await store.flushWorkspace()
    expect(store.reasoning).toBe(level)
    expect(localStorage.getItem('campus-agent-reasoning')).toBe(level)
    expect(freshStore().reasoning).toBe(level)
  })

  it('migrates legacy fast to default while preserving an explicit legacy thinking switch', () => {
    localStorage.setItem('campus-agent-reasoning', 'fast')
    expect(freshStore().reasoning).toBe('auto')
    localStorage.setItem('campus-agent-reasoning', 'deep')
    expect(freshStore().reasoning).toBe('deep')
  })

  it('ignores local model names that would break the api contract', () => {
    const store = freshStore()
    store.setLocalModel('bad\nname')
    expect(store.localModel).toBe('')
    expect(store.model).toBe('auto')
    store.setLocalModel('organization/custom:Q4_K_M')
    expect(store.localModel).toBe('organization/custom:Q4_K_M')
    expect(store.model).toBe('ollama')
  })
})

describe('desktop workspace recovery', () => {
  const saved: DesktopWorkspace = {
    model: 'deepseek', conversationId: 'kept-conversation', clientId: 'kept-client',
    localModel: '', appearance: 'dark', accentColor: '#123abc', webSearch: true, reasoning: 'deep', projectPermission: 'confirm', onboardingDone: false,
  }

  it('preserves saved data and the recovery error when reading fails', async () => {
    let disk = { ...saved }
    bridge.desktop = {
      async loadWorkspace() { throw new Error('read unavailable') },
      async saveWorkspace(value) { disk = { ...value } },
    }
    const store = freshStore()
    await store.initialize()
    expect(await store.flushWorkspace()).toBe(false)
    expect(disk).toEqual(saved)
    expect(store.ready).toBe(false)
    expect(store.persistenceError).toContain('read unavailable')

    store.setModel('qwen3')
    await store.persistWorkspace()
    expect(disk).toEqual(saved)
    expect(store.persistenceError).toContain('read unavailable')
  })

  it('retries reading before saving and restores the original conversation identity', async () => {
    let unavailable = true
    let disk = { ...saved }
    bridge.desktop = {
      async loadWorkspace() {
        if (unavailable) throw new Error('read unavailable')
        return { ...disk }
      },
      async saveWorkspace(value) { disk = { ...value } },
    }
    const store = freshStore()
    await store.initialize()
    unavailable = false
    await store.persistWorkspace()
    expect(await store.flushWorkspace()).toBe(true)
    expect(store.ready).toBe(true)
    expect(store.clientId).toBe('kept-client')
    expect(store.conversationId).toBe('kept-conversation')
    expect(store.model).toBe('deepseek')
    expect(disk).toEqual(saved)
    expect(store.persistenceError).toBe('')
  })

  it('retains a save failure after recovery and allows a later save retry', async () => {
    let unwritable = true
    let disk = { ...saved }
    bridge.desktop = {
      async loadWorkspace() { return { ...disk } },
      async saveWorkspace(value) {
        if (unwritable) throw new Error('disk full')
        disk = { ...value }
      },
    }
    const store = freshStore()
    await store.initialize()
    store.setModel('qwen3')
    expect(await store.flushWorkspace()).toBe(false)
    expect(store.persistenceError).toContain('disk full')
    expect(disk.model).toBe('deepseek')
    unwritable = false
    await store.persistWorkspace()
    expect(await store.flushWorkspace()).toBe(true)
    expect(disk.model).toBe('qwen3')
  })

  it('keeps chat unavailable until the initial save has finished', async () => {
    let startSave!: () => void
    let finishSave!: () => void
    const savingStarted = new Promise<void>(resolve => { startSave = resolve })
    const saving = new Promise<void>(resolve => { finishSave = resolve })
    bridge.desktop = {
      async loadWorkspace() { return { ...saved } },
      async saveWorkspace() { startSave(); await saving },
    }
    const store = freshStore()
    const initializing = store.initialize()
    await savingStarted
    try {
      expect(store.ready).toBe(false)
      store.setConversationId('new-conversation')
      expect(store.conversationId).toBe('kept-conversation')
    } finally {
      finishSave()
      await initializing
    }
    expect(store.ready).toBe(true)
    expect(await store.flushWorkspace()).toBe(true)
  })

  it('can retry after the desktop bridge throws synchronously', async () => {
    let unavailable = true
    bridge.desktop = {
      loadWorkspace() {
        if (unavailable) throw new Error('bridge unavailable')
        return Promise.resolve({ ...saved })
      },
      async saveWorkspace() {},
    }
    const store = freshStore()
    await store.initialize()
    unavailable = false
    await store.persistWorkspace()
    expect(await store.flushWorkspace()).toBe(true)
    expect(store.clientId).toBe('kept-client')
  })

  it('waits for one shared read before concurrent retries can write', async () => {
    let finishRead!: (value: DesktopWorkspace) => void
    const reading = new Promise<DesktopWorkspace>(resolve => { finishRead = resolve })
    let reads = 0
    const written: DesktopWorkspace[] = []
    bridge.desktop = {
      loadWorkspace() { reads += 1; return reading },
      async saveWorkspace(value) { written.push({ ...value }) },
    }
    const store = freshStore()
    const initializing = store.initialize()
    const retrying = store.persistWorkspace()
    const flushing = store.flushWorkspace()
    expect(written).toEqual([])
    finishRead({ ...saved })
    await Promise.all([initializing, retrying])
    expect(await flushing).toBe(true)
    expect(reads).toBe(1)
    expect(written).toEqual([saved])
  })
})
