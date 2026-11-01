import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import { ElMessage } from 'element-plus'
import { campusUi } from '../src/ui'
import App from '../src/App.vue'
import { useWorkspaceStore } from '../src/store'
import { setLocale } from '../src/i18n'

const bridge = vi.hoisted(() => ({ desktop: undefined as any }))
vi.mock('../src/desktop', () => bridge)
let dispose = () => {}
async function flush() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }

beforeEach(() => {
  localStorage.clear(); localStorage.setItem('mens-onboarding-done', '1'); setLocale('zh')
})
afterEach(async () => {
  ElMessage.closeAll(); dispose(); await flush()
  vi.unstubAllGlobals(); bridge.desktop = undefined; localStorage.clear()
  document.querySelectorAll('.el-popper-container, .el-message').forEach(node => node.remove())
})

async function submitRepair(surface: 'web' | 'desktop', reply: unknown, status = 200) {
  bridge.desktop = surface === 'desktop' ? {
    isDesktop: true,
    loadWorkspace: async () => ({ model: 'auto', conversationId: '', clientId: 'repair-fixture', localModel: '',
      appearance: 'system', accentColor: '#147b75', webSearch: false, reasoning: 'auto', projectPermission: 'confirm', onboardingDone: true }),
    saveWorkspace: async () => {},
    getInfo: async () => ({ version: 'test', dataPath: '' }),
  } : undefined
  const submissions: Array<{ method: string; body: unknown }> = []
  vi.stubGlobal('fetch', async (value: string, init?: RequestInit) => {
    const url = String(value)
    if (url.endsWith('/services/repairs')) {
      if (init?.method === 'POST') {
        submissions.push({ method: init.method, body: JSON.parse(String(init.body)) })
        return Response.json(reply, { status })
      }
      return Response.json({ demo: true, items: [] })
    }
    if (url.endsWith('/health')) return Response.json({ status: 'ok', models: {} })
    if (url.endsWith('/models/config')) return Response.json({ providers: {}, ollama: { model: '' } })
    if (url.endsWith('/models/local')) return Response.json({ running: false, installed: [], catalog: [], sources: [] })
    if (url.endsWith('/web/status')) return Response.json({ enabled: false, available: false, providers: [] })
    return Response.json([])
  })
  const host = document.createElement('div'); document.body.append(host)
  const pinia = createPinia(); const app = createApp(App).use(pinia).use(campusUi)
  app.mount(host); dispose = () => { app.unmount(); host.remove() }
  for (let index = 0; index < 5; index++) await flush()
  useWorkspaceStore(pinia).view = 'services'; await flush()
  const repairTab = [...host.querySelectorAll<HTMLButtonElement>('.service-nav button')]
    .find(button => button.textContent?.trim() === '报修申请')!
  expect(repairTab).toBeDefined(); repairTab.click(); await flush()
  const fields = host.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>('.service-panel .field input, .service-panel .field textarea')
  expect(fields).toHaveLength(3)
  for (const [field, value] of [[fields[0]!, '合成楼 A101'], [fields[1]!, 'fixture@example.test'], [fields[2]!, '合成灯具无法开启']] as const) {
    field.value = value; field.dispatchEvent(new Event('input', { bubbles: true }))
  }
  await nextTick()
  host.querySelector<HTMLButtonElement>('.service-panel .form-action button')!.click()
  await flush(); await flush()
  expect(submissions).toEqual([{ method: 'POST', body: { location: '合成楼 A101', issue: '合成灯具无法开启', contact: 'fixture@example.test' } }])
  return host
}

describe.each(['web', 'desktop'] as const)('%s repair receipts in the actual App', surface => {
  it.each([
    { label: 'business rejection', receipt: { success: false, message: '合成回执：未受理' } },
    { label: 'opaque ticket object', receipt: { ticket: 'school-fixture-1', stage: 'unknown-to-Mens' } },
    { label: 'empty object', receipt: {} },
  ])('keeps a $label neutral rather than claiming business success', async ({ receipt }) => {
    const host = await submitRepair(surface, { demo: false, result: receipt })
    expect(document.querySelector('.el-message--success')).toBeNull()
    expect(document.querySelector('.el-message--info')?.textContent).toContain('学校接口已返回')
    const result = host.querySelector('.service-panel .result-section')!
    expect(result.textContent).toContain('业务受理结果以学校回执为准')
    expect(result.textContent).toContain(JSON.stringify(receipt))
    expect(host.querySelector('.service-panel .el-alert--error')).toBeNull()
  })

  it('keeps confirmed local demo saves successful without claiming a school receipt', async () => {
    const host = await submitRepair(surface, { demo: true, id: 'local-demo-fixture', status: 'pending' })
    expect(document.querySelector('.el-message--success')?.textContent).toContain('演示报修单已保存在后端')
    expect(document.querySelector('.el-message--info')).toBeNull()
    expect(host.querySelector('.service-panel')?.textContent).toContain('local-demo-fixture')
    expect(host.querySelector('.service-panel')?.textContent).not.toContain('业务受理结果以学校回执为准')
  })

  it('keeps HTTP submission errors in the error state without a success or receipt notification', async () => {
    const host = await submitRepair(surface, { detail: '合成校园接口请求失败' }, 502)
    expect(host.querySelector('.service-panel .el-alert--error')?.textContent).toContain('查询或提交失败')
    expect(host.querySelector('.service-panel .el-alert--error')?.textContent).toContain('合成校园接口请求失败')
    expect(document.querySelector('.el-message--success, .el-message--info')).toBeNull()
    expect(host.querySelector('.service-panel')?.textContent).not.toContain('业务受理结果以学校回执为准')
  })

  it('shows backend failure details as escaped text while keeping the interface-settings action', async () => {
    const detail = '合成错误 <img src=x onerror="alert(1)"><script>alert(2)</script>'
    const host = await submitRepair(surface, { detail }, 502)
    const failure = host.querySelector('.service-panel .el-alert--error')!
    expect(failure.textContent).toContain(detail)
    expect(failure.querySelector('img, script')).toBeNull()
    expect(failure.querySelector('button')?.textContent).toContain('检查接口设置')
    expect(document.querySelector('.el-message--success, .el-message--info')).toBeNull()
  })

  it('renders the school JSON receipt as text without creating executable receipt markup', async () => {
    const receipt = { message: '<img src=x onerror="alert(1)"><script>alert(2)</script>', ticket: 'fixture-<b>3</b>' }
    const host = await submitRepair(surface, { demo: false, result: receipt })
    const result = host.querySelector('.service-panel .result-section')!
    expect(result.textContent).toContain(JSON.stringify(receipt))
    expect(result.querySelector('img, script, b')).toBeNull()
  })
})
