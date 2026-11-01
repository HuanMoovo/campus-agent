import { desktop } from './desktop'
import type { Locale } from './i18n'

export interface UsageTotals {
  requests: number
  reported_requests: number
  partial_requests: number
  unreported_requests: number
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  cached_input_tokens: number | null
  cache_creation_input_tokens: number | null
  reasoning_tokens: number | null
}
export interface UsageDay extends UsageTotals { date: string }
export interface UsageModel extends UsageTotals { provider: string; model: string }
export interface UsageReport {
  days: 7 | 30
  timezone: 'UTC'
  start_date: string
  end_date: string
  totals: UsageTotals
  daily: UsageDay[]
  models: UsageModel[]
}

const tokenFields = ['input_tokens', 'output_tokens', 'total_tokens', 'cached_input_tokens', 'cache_creation_input_tokens', 'reasoning_tokens'] as const
const requestFields = ['requests', 'reported_requests', 'partial_requests', 'unreported_requests'] as const
const dayMs = 86_400_000
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid usage report')
  return value as Record<string, unknown>
}
function count(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw new Error('Invalid usage count')
  return value
}
function totals(value: unknown): UsageTotals {
  const source = object(value)
  const result = {} as UsageTotals
  for (const key of requestFields) result[key] = count(source[key])
  for (const key of tokenFields) result[key] = source[key] == null ? null : count(source[key])
  if (result.reported_requests + result.partial_requests + result.unreported_requests !== result.requests) throw new Error('Invalid usage coverage')
  return result
}
function date(value: unknown): string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error('Invalid usage date')
  const time = Date.parse(`${value}T00:00:00Z`)
  if (!Number.isFinite(time) || new Date(time).toISOString().slice(0, 10) !== value) throw new Error('Invalid usage date')
  return value
}
function emptyTotals(): UsageTotals {
  return { requests: 0, reported_requests: 0, partial_requests: 0, unreported_requests: 0, input_tokens: null, output_tokens: null, total_tokens: null, cached_input_tokens: null, cache_creation_input_tokens: null, reasoning_tokens: null }
}

/** Validate the observed-count contract before it becomes chart geometry or displayed usage. */
export function readUsageReport(value: unknown, days: 7 | 30): UsageReport {
  const source = object(value)
  if (source.days !== days || source.timezone !== 'UTC') throw new Error('Invalid usage period')
  const start = date(source.start_date); const end = date(source.end_date)
  if ((Date.parse(end) - Date.parse(start)) / dayMs !== days - 1 || !Array.isArray(source.daily) || !Array.isArray(source.models)) throw new Error('Invalid usage period')
  const daily = new Map<string, UsageDay>()
  for (const row of source.daily) {
    const item = object(row); const key = date(item.date)
    if (key < start || key > end || daily.has(key)) throw new Error('Invalid daily usage')
    daily.set(key, { date: key, ...totals(item) })
  }
  const filled: UsageDay[] = []
  for (let index = 0; index < days; index++) {
    const key = new Date(Date.parse(start) + index * dayMs).toISOString().slice(0, 10)
    filled.push(daily.get(key) || { date: key, ...emptyTotals() })
  }
  const models = source.models.map(row => {
    const item = object(row)
    if (typeof item.provider !== 'string' || typeof item.model !== 'string') throw new Error('Invalid usage model')
    return { provider: item.provider, model: item.model, ...totals(item) }
  })
  return { days, timezone: 'UTC', start_date: start, end_date: end, totals: totals(source.totals), daily: filled, models }
}

export function formatTokens(value: number | null, language: Locale): string {
  return value === null ? '—' : new Intl.NumberFormat(language === 'zh' ? 'zh-CN' : language, { maximumFractionDigits: 0 }).format(value)
}

/** Separate input/output bars share one domain; absent observations stay absent in the rows. */
export function chartDays(daily: UsageDay[]) {
  const maximum = Math.max(0, ...daily.flatMap(day => [day.input_tokens ?? 0, day.output_tokens ?? 0]))
  const step = 600 / Math.max(1, daily.length)
  return daily.map((day, index) => ({ ...day, x: index * step, step, barWidth: Math.max(1, Math.min(12, step * 0.3)), inputHeight: maximum ? (day.input_tokens ?? 0) / maximum * 140 : 0, outputHeight: maximum ? (day.output_tokens ?? 0) / maximum * 140 : 0 }))
}

export async function usageReport(clientId: string, days: 7 | 30, signal?: AbortSignal): Promise<UsageReport> {
  const base = desktop ? '/api' : import.meta.env.VITE_API_BASE_URL || '/api'
  const query = new URLSearchParams({ client_id: clientId, days: String(days) })
  const response = await fetch(`${base}/usage?${query}`, { method: 'GET', cache: 'no-store', signal })
  if (!response.ok) throw new Error('Usage request failed')
  return readUsageReport(await response.json(), days)
}
