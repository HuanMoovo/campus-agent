import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, reactive, type Component } from 'vue'
import { campusUi } from '../src/ui'
import ConversationHistory from '../src/components/ConversationHistory.vue'
import WorkspaceSidebar from '../src/components/WorkspaceSidebar.vue'

const cleanup: (() => void)[] = []

function mount(component: Component, props: Record<string, unknown>) {
  const host = document.createElement('div')
  document.body.append(host)
  const app = createApp({ render: () => h(component, props) })
  app.use(campusUi)
  app.mount(host)
  cleanup.push(() => { app.unmount(); host.remove() })
  return host
}

afterEach(() => cleanup.splice(0).forEach(dispose => dispose()))

const conversation = { id: 'saved-chat', title: 'Saved campus question', message_count: 4, updated_at: '2026-10-30T12:00:00Z' }
function historyProps() {
  return {
    conversations: [conversation], conversationsBusy: false, conversationsError: '',
    historyQuery: '', historyResults: [], historySearchActive: false, historySearchBusy: false,
    historySearchError: '', historySelectMode: false, historySelected: [],
    conversationId: '', ready: true, chatBusy: false,
  }
}

describe('workspace sidebar', () => {
  it('keeps returning to the conversation separate from creating a new one', () => {
    const navigate = vi.fn()
    const newChat = vi.fn()
    const host = mount(WorkspaceSidebar, {
      view: 'services', mobileOpen: false, ready: true, busy: false,
      connectedLabel: 'Connected', logo: '', onNavigate: navigate, onNewChat: newChat,
    })
    host.querySelector<HTMLButtonElement>('.sidebar-nav .nav-item')!.click()
    expect(navigate).toHaveBeenCalledWith('chat')
    expect(newChat).not.toHaveBeenCalled()
    host.querySelector<HTMLButtonElement>('.sidebar-new-chat')!.click()
    expect(newChat).toHaveBeenCalledOnce()
  })

  it('reveals tools when navigation arrives there from the command palette', async () => {
    const props = reactive({ view: 'chat', mobileOpen: false, ready: true, busy: false, connectedLabel: '', logo: '' })
    const host = mount(WorkspaceSidebar, props)
    expect(host.querySelector<HTMLDetailsElement>('.sidebar-tools')!.open).toBe(false)
    props.view = 'mcp'
    await nextTick()
    expect(host.querySelector<HTMLDetailsElement>('.sidebar-tools')!.open).toBe(true)
    expect(host.querySelector('.sidebar-tool-list [aria-current="page"]')?.textContent).toContain('MCP')
  })
})

describe('conversation history', () => {
  it('opens a focused row with Enter without opening it from a nested menu button', () => {
    const select = vi.fn()
    const host = mount(ConversationHistory, { ...historyProps(), onItemClick: select })
    host.querySelector('.history-item')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    expect(select).toHaveBeenCalledExactlyOnceWith(conversation)
    select.mockClear()
    host.querySelector('.history-more')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    expect(select).not.toHaveBeenCalled()
  })

  it('blocks mouse and keyboard activation while a response is generating', () => {
    const select = vi.fn()
    const host = mount(ConversationHistory, { ...historyProps(), historySelectMode: true, chatBusy: true, onItemClick: select })
    const row = host.querySelector<HTMLElement>('.history-item')!
    row.click()
    row.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    expect(select).not.toHaveBeenCalled()
    expect(row.getAttribute('tabindex')).toBe('-1')
  })

  it('forwards search text and Enter to the existing search controller', async () => {
    const update = vi.fn()
    const inputChanged = vi.fn()
    const search = vi.fn()
    const host = mount(ConversationHistory, { ...historyProps(), 'onUpdate:historyQuery': update, onSearchInput: inputChanged, onSearch: search })
    const input = host.querySelector<HTMLInputElement>('.history-tools input')!
    input.value = 'library'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()
    expect(update).toHaveBeenCalledWith('library')
    expect(inputChanged).toHaveBeenCalledOnce()
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    expect(search).toHaveBeenCalledOnce()
  })

  it.each(['rename', 'pin', 'md', 'json', 'delete'])('preserves the %s menu action and conversation identity', async command => {
    const run = vi.fn()
    const host = mount(ConversationHistory, { ...historyProps(), onItemCommand: run })
    host.querySelector<HTMLButtonElement>('.history-more')!.click()
    await nextTick()
    await nextTick()
    const commands = ['rename', 'pin', 'md', 'json', 'delete']
    const items = document.querySelectorAll<HTMLElement>('.el-dropdown-menu__item')
    items[commands.indexOf(command)]!.click()
    await nextTick()
    expect(run).toHaveBeenCalledExactlyOnceWith(conversation, command)
  })
})
