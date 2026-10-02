import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useWorkspaceStore } from '../src/store'

function freshStore() {
  setActivePinia(createPinia())
  return useWorkspaceStore()
}

describe('workspace store', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('generates and persists a client id the backend accepts', () => {
    const store = freshStore()
    expect(store.clientId).toMatch(/^[A-Za-z0-9_-]{1,64}$/)
    expect(localStorage.getItem('mens-client-id')).toBe(store.clientId)
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

  it('remembers the per-user reasoning effort preference', async () => {
    const store = freshStore()
    expect(store.reasoning).toBe('fast')
    store.setReasoning('deep')
    await store.flushWorkspace()
    expect(localStorage.getItem('campus-agent-reasoning')).toBe('deep')
    store.setReasoning('odd' as never)
    await store.flushWorkspace()
    expect(store.reasoning).toBe('fast')
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
