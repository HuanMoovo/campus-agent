import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, reactive } from 'vue'
import { campusUi } from '../src/ui'
import UsageSettings from '../src/components/UsageSettings.vue'
import { chartDays, formatTokens, readUsageReport, usageReport, type UsageReport, type UsageTotals } from '../src/token-usage'
import { setLocale } from '../src/i18n'
import { usageCatalogs } from '../src/token-usage-i18n'

function totals(values: Partial<UsageTotals> = {}): UsageTotals {
  return { requests: 0, reported_requests: 0, partial_requests: 0, unreported_requests: 0, input_tokens: null, output_tokens: null, total_tokens: null, cached_input_tokens: null, cache_creation_input_tokens: null, reasoning_tokens: null, ...values }
}
function report(days: 7 | 30 = 7, overrides: Partial<UsageReport> = {}): UsageReport {
  return { days, timezone: 'UTC', start_date: days === 7 ? '2026-10-25' : '2026-10-02', end_date: '2026-10-31', totals: totals({ requests: 3, reported_requests: 1, partial_requests: 1, unreported_requests: 1, input_tokens: 120, output_tokens: 30, total_tokens: 150, cached_input_tokens: 20, reasoning_tokens: 10 }), daily: [{ date: '2026-10-31', ...totals({ requests: 3, reported_requests: 1, partial_requests: 1, unreported_requests: 1, input_tokens: 120, output_tokens: 30, total_tokens: 150 }) }], models: [{ provider: 'qwen', model: 'test-model', ...totals({ requests: 3, reported_requests: 1, partial_requests: 1, unreported_requests: 1, input_tokens: 120, output_tokens: 30, total_tokens: 150 }) }], ...overrides }
}
const cleanup: (() => void)[] = []
function mount(active = true, clientId = 'client-test') {
  const props = reactive({ active, clientId })
  const host = document.createElement('div')
  document.body.append(host)
  const app = createApp({ render: () => h(UsageSettings, props) }).use(campusUi)
  app.mount(host)
  const dispose = () => { app.unmount(); host.remove() }
  cleanup.push(dispose)
  return { host, props, dispose }
}
async function flush() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason?: unknown) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }

beforeEach(() => setLocale('en'))
afterEach(() => { cleanup.splice(0).forEach(dispose => dispose()); vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('observed usage data', () => {
  it('keeps unreported fields distinct from an actual zero and fills UTC calendar gaps', () => {
    const parsed = readUsageReport(report(7, { daily: [{ date: '2026-10-31', ...totals({ requests: 1, reported_requests: 1, input_tokens: 0, output_tokens: 0, total_tokens: 0 }) }] }), 7)
    expect(parsed.daily).toHaveLength(7)
    expect(parsed.daily[0]).toMatchObject({ date: '2026-10-25', requests: 0, input_tokens: null })
    expect(parsed.daily[6]).toMatchObject({ input_tokens: 0, total_tokens: 0 })
    expect(formatTokens(null, 'en')).toBe('—')
    expect(formatTokens(0, 'en')).toBe('0')
    expect(formatTokens(12000, 'en')).toBe('12,000')
  })
  it.each([
    { timezone: 'Asia/Shanghai' }, { days: 30 }, { start_date: '2026-02-30' },
    { totals: totals({ requests: 1, reported_requests: 2 }) },
    { totals: totals({ input_tokens: -1 }) }, { totals: totals({ output_tokens: '20' as unknown as number }) },
    { daily: [{ date: '2026-11-01', ...totals() }] },
  ])('rejects an invalid period or count rather than displaying misleading usage: %o', value => {
    expect(() => readUsageReport({ ...report(), ...value }, 7)).toThrow()
  })
  it('bounds chart coordinates and preserves unknown daily fields without inventing counts', () => {
    const parsed = readUsageReport(report(), 7)
    const chart = chartDays(parsed.daily)
    expect(chart).toHaveLength(7)
    expect(chart[0]!.inputHeight).toBe(0)
    expect(chart[0]!.input_tokens).toBeNull()
    expect(chart[6]!.inputHeight).toBeGreaterThan(chart[6]!.outputHeight)
    expect(chart.every(day => Number.isFinite(day.x) && day.inputHeight <= 140 && day.outputHeight <= 140)).toBe(true)
  })
  it('handles a zero-only corpus without NaN, and keeps all usage text localized', () => {
    const chart = chartDays([{ date: '2026-10-31', ...totals({ requests: 1, reported_requests: 1, input_tokens: 0, output_tokens: 0, total_tokens: 0 }) }])
    expect(chart[0]).toMatchObject({ inputHeight: 0, outputHeight: 0 })
    for (const language of ['en', 'ja'] as const) expect(Object.keys(usageCatalogs[language]).sort()).toEqual(Object.keys(usageCatalogs.zh).sort())
  })
  it('encodes the scoped client and only accepts the expected report shape', async () => {
    const fetch = vi.fn(async () => Response.json(report()))
    vi.stubGlobal('fetch', fetch)
    const controller = new AbortController()
    expect((await usageReport('client&x=1', 7, controller.signal)).days).toBe(7)
    expect(fetch.mock.calls[0]?.[0]).toBe('/api/usage?client_id=client%26x%3D1&days=7')
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({ signal: controller.signal })
  })
})

describe('usage settings panel', () => {
  it('loads only while active and exposes actual counts, incomplete coverage and an accessible chart/table', async () => {
    const fetch = vi.fn(async () => Response.json(report()))
    vi.stubGlobal('fetch', fetch)
    const { host, props } = mount(false)
    await flush()
    expect(fetch).not.toHaveBeenCalled()
    props.active = true
    await flush(); await flush()
    expect(fetch).toHaveBeenCalledOnce()
    expect(host.querySelector('[data-metric="total_tokens"]')?.textContent).toContain('150')
    expect(host.querySelector('[data-metric="input_tokens"]')?.textContent).toContain('120')
    expect(host.querySelector('[data-usage-coverage]')?.textContent).toContain('1 / 3')
    expect(host.textContent).toContain('1 partially reported')
    expect(host.textContent).toContain('1 unreported')
    expect(host.querySelector('svg[role="img"] title')?.textContent).toContain('Daily token usage')
    expect(host.querySelectorAll('table tbody tr')).toHaveLength(7)
    expect(host.textContent).toContain('UTC')
    expect(host.textContent).toContain('test-model')
    expect(host.textContent).not.toContain('NaN')
  })
  it('shows no recorded requests separately from recorded requests without usage', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(Response.json(report(7, { totals: totals(), daily: [], models: [] }))).mockResolvedValueOnce(Response.json(report(7, { totals: totals({ requests: 2, unreported_requests: 2 }), daily: [], models: [] })))
    vi.stubGlobal('fetch', fetch)
    const { host } = mount()
    await flush(); await flush()
    expect(host.querySelector('[data-usage-empty]')?.textContent).toContain('No model requests')
    host.querySelector<HTMLButtonElement>('[data-usage-refresh]')!.click()
    await flush(); await flush()
    expect(host.querySelector('[data-usage-empty]')).toBeNull()
    expect(host.querySelector('[data-metric="total_tokens"]')?.textContent).toContain('—')
    expect(host.textContent).toContain('2 unreported')
  })
  it('aborts older periods and prevents stale responses from overwriting the latest selection', async () => {
    const old = deferred<Response>()
    const fetch = vi.fn().mockReturnValueOnce(old.promise).mockResolvedValueOnce(Response.json(report(30, { totals: totals({ requests: 1, reported_requests: 1, input_tokens: 700, output_tokens: 100, total_tokens: 800 }) })))
    vi.stubGlobal('fetch', fetch)
    const { host } = mount()
    await flush()
    const signal = (fetch.mock.calls[0]![1] as RequestInit).signal!
    host.querySelector<HTMLButtonElement>('[data-usage-days="30"]')!.click()
    await flush(); await flush()
    expect(signal.aborted).toBe(true)
    expect(host.querySelector('[data-metric="total_tokens"]')?.textContent).toContain('800')
    old.resolve(Response.json(report()))
    await flush(); await flush()
    expect(host.querySelector('[data-metric="total_tokens"]')?.textContent).toContain('800')
  })
  it('clears previous results while loading and after failure, and retries explicitly', async () => {
    const next = deferred<Response>()
    const fetch = vi.fn().mockResolvedValueOnce(Response.json(report())).mockReturnValueOnce(next.promise).mockResolvedValueOnce(Response.json(report()))
    vi.stubGlobal('fetch', fetch)
    const { host } = mount()
    await flush(); await flush()
    host.querySelector<HTMLButtonElement>('[data-usage-refresh]')!.click()
    await nextTick()
    expect(host.querySelector('[data-metric="total_tokens"]')).toBeNull()
    expect(host.querySelector('[role="status"]')?.textContent).toContain('Loading')
    next.reject(new Error('offline'))
    await flush(); await flush()
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('Could not load')
    expect(host.querySelector('[data-metric="total_tokens"]')).toBeNull()
    host.querySelector<HTMLButtonElement>('[data-usage-refresh]')!.click()
    await flush(); await flush()
    expect(host.querySelector('[data-metric="total_tokens"]')?.textContent).toContain('150')
  })
  it('renders provider names as text and translates the panel without refetching', async () => {
    const fetch = vi.fn(async () => Response.json(report(7, { models: [{ provider: '<svg onload="bad()">', model: '<img src=x onerror="bad()">', ...totals({ requests: 1, unreported_requests: 1 }) }] })))
    vi.stubGlobal('fetch', fetch)
    const { host } = mount()
    await flush(); await flush()
    expect(host.querySelector('.usage-models img')).toBeNull()
    expect(host.querySelector('.usage-models svg')).toBeNull()
    expect(host.querySelector('.usage-models')?.textContent).toContain('<img src=x')
    setLocale('zh')
    await nextTick()
    expect(host.querySelector('h2')?.textContent).toBe('Token 使用量')
    setLocale('ja')
    await nextTick()
    expect(host.querySelector('h2')?.textContent).toBe('トークン使用量')
    expect(fetch).toHaveBeenCalledOnce()
  })
  it('does not make an unscoped request before workspace initialization supplies a client', async () => {
    const fetch = vi.fn(async () => Response.json(report()))
    vi.stubGlobal('fetch', fetch)
    const { props } = mount(true, '')
    await flush()
    expect(fetch).not.toHaveBeenCalled()
    props.clientId = 'ready-client'
    await flush(); await flush()
    expect(fetch).toHaveBeenCalledOnce()
  })
  it('labels the bounded remaining-model bucket as combined rather than unreported in every language', async () => {
    vi.stubGlobal('fetch', async () => Response.json(report(7, { models: [{ provider: 'other', model: '', ...totals({ requests: 1, reported_requests: 1, input_tokens: 120, output_tokens: 30, total_tokens: 150 }) }] })))
    const { host } = mount()
    await flush(); await flush()
    for (const [language, label] of [['en', 'Other models (combined)'], ['zh', '其他模型（合计）'], ['ja', 'その他のモデル（合計）']] as const) {
      setLocale(language); await nextTick()
      expect(host.querySelector('.usage-models strong')?.textContent).toBe(label)
      expect(host.querySelector('.usage-models small')?.textContent).not.toContain('other')
    }
    setLocale('en'); await nextTick()
    expect(host.querySelector('.usage-note')?.textContent).toContain('tool input')
    expect(host.querySelector('.usage-note')?.textContent).toContain('stopped or failed')
  })
  it('invalidates reads when scope changes, the panel closes, and on unmount', async () => {
    const first = deferred<Response>(); const second = deferred<Response>(); const third = deferred<Response>()
    const fetch = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise).mockReturnValueOnce(third.promise)
    vi.stubGlobal('fetch', fetch)
    const { host, props, dispose } = mount()
    await flush()
    props.clientId = 'new-client'
    await flush()
    expect((fetch.mock.calls[0]![1] as RequestInit).signal?.aborted).toBe(true)
    expect(fetch.mock.calls[1]![0]).toContain('client_id=new-client')
    props.active = false
    await flush()
    expect((fetch.mock.calls[1]![1] as RequestInit).signal?.aborted).toBe(true)
    second.resolve(Response.json(report()))
    await flush()
    expect(host.querySelector('[data-metric="total_tokens"]')).toBeNull()
    props.active = true
    await flush()
    dispose()
    expect((fetch.mock.calls[2]![1] as RequestInit).signal?.aborted).toBe(true)
    third.resolve(Response.json(report()))
    first.resolve(Response.json(report()))
    await flush()
  })
})
