import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, reactive } from 'vue'
import ProjectRecoveryList from '../src/components/ProjectRecoveryList.vue'
import { setLocale } from '../src/i18n'
import { changeSessionRevision } from '../src/project-changes'

const bridge = vi.hoisted(() => ({ desktop: { isDesktop: true, projectChanges: vi.fn(), changeProjectFile: vi.fn(), projectChangeStatus: vi.fn(), projectRecoveryOriginal: vi.fn() } }))
vi.mock('../src/desktop', () => bridge)
const record = { operation_id: 'operation-1', project_id: 'root', subject_id: 'draft', proposal_id: 'draft', recovery_id: 'recovery-1', action: 'apply', state: 'applied', path: 'main.py', summary: 'fixture', created_at: '2026-10-31T00:00:00Z', can_revert: true }
const disposals: Array<() => void> = []
const originalClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
async function flush() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
function mount(extra: Record<string, unknown> = {}) {
  const state = reactive({ projectId: 'root', connected: true, disabled: false, revision: 0, ...extra })
  const host = document.createElement('div'); document.body.append(host)
  const app = createApp({ render: () => h(ProjectRecoveryList, state) }); app.mount(host)
  disposals.push(() => { app.unmount(); host.remove() })
  return { host, state }
}
beforeEach(() => { vi.resetAllMocks(); setLocale('zh') })
afterEach(() => {
  disposals.splice(0).forEach(dispose => dispose())
  if (originalClipboard) Object.defineProperty(navigator, 'clipboard', originalClipboard)
  else delete (navigator as { clipboard?: Clipboard }).clipboard
})

it('reloads durable recovery records after mounting and copies the exact original text without a write', async () => {
  bridge.desktop.projectChanges.mockResolvedValue({ available: true, records: [record] })
  bridge.desktop.projectRecoveryOriginal.mockResolvedValue({ text: '  original\r\n', bom: true, newline: 'crlf' })
  const copy = vi.fn(async () => {}); Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: copy } })
  const { host } = mount(); await flush(); await flush()
  expect(host.textContent).toContain('main.py')
  host.querySelector<HTMLDetailsElement>('details')!.open = true
  host.querySelector<HTMLButtonElement>('[data-change-action="original"]')!.click(); await flush(); await flush()
  expect(bridge.desktop.projectRecoveryOriginal).toHaveBeenCalledWith('root', 'recovery-1')
  expect(copy).toHaveBeenCalledWith('  original\r\n')
  expect(bridge.desktop.changeProjectFile).not.toHaveBeenCalled()
})

it('ignores an old root list response after a new root was selected', async () => {
  let resolve!: (value: unknown) => void
  bridge.desktop.projectChanges.mockReturnValueOnce(new Promise(done => { resolve = done })).mockResolvedValue({ available: true, records: [] })
  const { host, state } = mount(); await nextTick()
  state.projectId = 'other-root'; await flush(); await flush()
  resolve({ available: true, records: [record] }); await flush(); await flush()
  expect(host.textContent).not.toContain('main.py')
  expect(bridge.desktop.projectChanges).toHaveBeenLastCalledWith('other-root')
})

it('keeps external-edit conflicts read-only while allowing original recovery copying', async () => {
  bridge.desktop.projectChanges.mockResolvedValue({ available: true, records: [{ ...record, can_revert: false }] })
  const { host } = mount(); await flush(); await flush()
  expect(host.querySelector('[data-change-action="revert"]')).toBeNull()
  expect(host.querySelector('[data-change-action="original"]')).not.toBeNull()
  expect(host.textContent).toContain('不能覆盖或直接撤销')
})

it('offers imported recovery material as escaped copy-only content beside live records', async () => {
  const archive = { archive_id: `backup_${'a'.repeat(64)}`, path: 'draft.py', summary: '<script>fixture</script>', created_at: '2026-10-31T00:00:00Z', size_bytes: 18 }
  bridge.desktop.projectChanges.mockResolvedValue({ available: true, records: [record], archives: [archive] })
  bridge.desktop.projectRecoveryOriginal.mockResolvedValue({ text: '  source\r\n', bom: true, newline: 'crlf' })
  const copy = vi.fn(async () => {}); Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: copy } })
  const { host } = mount({ writeAllowed: false }); await flush(); await flush()
  expect(host.querySelector('[data-change-action="revert"]')).toBeNull()
  expect(host.querySelector('[data-change-action="keep"]')).toBeNull()
  const section = host.querySelector('.project-recovery-archives')!
  expect(section).not.toBeNull()
  expect(section.textContent).toContain('只读')
  expect(section.querySelector('script')).toBeNull()
  expect(section.querySelector('[data-change-action]')).toBeNull()
  expect(bridge.desktop.projectRecoveryOriginal).not.toHaveBeenCalled()
  section.querySelector<HTMLButtonElement>('[data-copy-archive]')!.click(); await flush(); await flush()
  expect(bridge.desktop.projectRecoveryOriginal).toHaveBeenCalledWith('root', archive.archive_id)
  expect(copy).toHaveBeenCalledWith('  source\r\n')
  expect(bridge.desktop.changeProjectFile).not.toHaveBeenCalled()
})

it('does not copy a late backup original after the selected root changes', async () => {
  const archive = { archive_id: `backup_${'b'.repeat(64)}`, path: 'draft.py', summary: '', created_at: '2026-10-31T00:00:00Z', size_bytes: 18 }
  bridge.desktop.projectChanges.mockResolvedValueOnce({ available: true, records: [], archives: [archive] }).mockResolvedValue({ available: true, records: [], archives: [] })
  let resolve!: (value: unknown) => void
  bridge.desktop.projectRecoveryOriginal.mockReturnValue(new Promise(done => { resolve = done }))
  const copy = vi.fn(async () => {}); Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: copy } })
  const { host, state } = mount(); await flush(); await flush()
  host.querySelector<HTMLButtonElement>('[data-copy-archive]')!.click(); await nextTick()
  state.projectId = 'new-root'; await flush()
  resolve({ text: 'old root source', bom: false, newline: 'none' }); await flush(); await flush()
  expect(copy).not.toHaveBeenCalled()
  expect(host.textContent).not.toContain('draft.py')
})

it.each(['revert', 'keep'] as const)('retains an uncertain %s operation when the refreshed list still contains the old apply receipt', async action => {
  bridge.desktop.projectChanges.mockImplementation(async () => ({ available: true, records: [{ ...record }] }))
  const uncertain = { ...record, operation_id: 'operation-2', subject_id: 'recovery-1', action, state: 'uncertain', can_revert: false }
  bridge.desktop.changeProjectFile.mockResolvedValue(uncertain)
  bridge.desktop.projectChangeStatus.mockResolvedValue(uncertain)
  const { host } = mount(); await flush(); await flush()
  host.querySelector<HTMLButtonElement>(`[data-change-action="${action}"]`)!.click()
  for (let i = 0; i < 5; i++) await flush()
  expect(host.textContent).toContain('结果尚未确认')
  expect(host.querySelector('[data-change-action="revert"]')).toBeNull()
  expect(host.querySelector('[data-change-action="keep"]')).toBeNull()
  host.querySelector<HTMLButtonElement>('[data-change-action="status"]')!.click(); await flush(); await flush()
  expect(bridge.desktop.projectChangeStatus).toHaveBeenLastCalledWith('root', 'operation-2')
  expect(bridge.desktop.changeProjectFile).toHaveBeenCalledTimes(1)
  bridge.desktop.projectChanges.mockRejectedValueOnce(new Error('[project_change_journal_unavailable]'))
  host.querySelector<HTMLButtonElement>('[data-recovery-refresh]')!.click()
  for (let i = 0; i < 3; i++) await flush()
  expect(host.querySelector('[role="alert"]')).not.toBeNull()
  expect(host.textContent).toContain('结果尚未确认')
  disposals.pop()!()
  const remounted = mount(); await flush(); await flush()
  expect(remounted.host.textContent).toContain('结果尚未确认')
  expect(remounted.host.querySelector('[data-change-action="revert"]')).toBeNull()
  expect(remounted.host.querySelector('[data-change-action="keep"]')).toBeNull()
  bridge.desktop.projectChangeStatus.mockResolvedValue({ ...uncertain, state: action === 'revert' ? 'reverted' : 'kept' })
  remounted.host.querySelector<HTMLButtonElement>('[data-change-action="status"]')!.click(); await flush(); await flush()
  expect(bridge.desktop.projectChangeStatus).toHaveBeenLastCalledWith('root', 'operation-2')
  expect(remounted.host.textContent).not.toContain('结果尚未确认')
  expect(bridge.desktop.changeProjectFile).toHaveBeenCalledTimes(1)
})

it.each(['revert', 'keep'] as const)('keeps an in-flight %s query-only when reconnecting before its late uncertain receipt', async action => {
  bridge.desktop.projectChanges.mockImplementation(async () => ({ available: true, records: [{ ...record }] }))
  let resolve!: (value: unknown) => void
  bridge.desktop.changeProjectFile.mockReturnValueOnce(new Promise(done => { resolve = done }))
  const { host, state } = mount(); await flush(); await flush()
  host.querySelector<HTMLButtonElement>(`[data-change-action="${action}"]`)!.click(); await nextTick()
  state.connected = false; await flush(); state.connected = true
  await flush(); await flush()
  expect(host.querySelector('[data-change-action="revert"]')).toBeNull()
  expect(host.querySelector('[data-change-action="keep"]')).toBeNull()
  const uncertain = { ...record, operation_id: 'operation-2', subject_id: 'recovery-1', action, state: 'uncertain', can_revert: false }
  resolve(uncertain)
  for (let i = 0; i < 5; i++) await flush()
  expect(host.textContent).toContain('结果尚未确认')
  bridge.desktop.projectChangeStatus.mockResolvedValue({ ...uncertain, state: action === 'revert' ? 'reverted' : 'kept' })
  host.querySelector<HTMLButtonElement>('[data-change-action="status"]')!.click(); await flush(); await flush()
  expect(bridge.desktop.projectChangeStatus).toHaveBeenLastCalledWith('root', 'operation-2')
  expect(bridge.desktop.changeProjectFile).toHaveBeenCalledTimes(1)
})

it('coalesces parent and session refresh signals into one native list read', async () => {
  bridge.desktop.projectChanges.mockResolvedValue({ available: true, records: [] })
  const { state } = mount(); await flush(); await flush()
  expect(bridge.desktop.projectChanges).toHaveBeenCalledTimes(1)
  state.revision++
  changeSessionRevision.value++
  await flush(); await flush()
  expect(bridge.desktop.projectChanges).toHaveBeenCalledTimes(2)
})

it('keeps one read in flight, discards a dirty result and performs one latest follow-up', async () => {
  let first!: (value: unknown) => void
  let second!: (value: unknown) => void
  bridge.desktop.projectChanges.mockReturnValueOnce(new Promise(done => { first = done }))
    .mockReturnValueOnce(new Promise(done => { second = done }))
  const { host, state } = mount(); await nextTick()
  state.revision++; await nextTick()
  changeSessionRevision.value++; await nextTick()
  state.revision++; await nextTick()
  expect(bridge.desktop.projectChanges).toHaveBeenCalledTimes(1)
  first({ available: true, records: [{ ...record, path: 'outdated.py' }] })
  await flush(); await flush()
  expect(host.textContent).not.toContain('outdated.py')
  expect(bridge.desktop.projectChanges).toHaveBeenCalledTimes(2)
  second({ available: true, records: [{ ...record, path: 'current.py' }] })
  await flush(); await flush()
  expect(host.textContent).toContain('current.py')
})

it('drops a queued refresh when the panel unmounts before it starts', async () => {
  bridge.desktop.projectChanges.mockResolvedValue({ available: true, records: [] })
  mount()
  disposals.pop()!()
  await flush()
  expect(bridge.desktop.projectChanges).not.toHaveBeenCalled()
})
