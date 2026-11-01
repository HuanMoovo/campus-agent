import { locale, type Locale } from './i18n'

const zh = {
  title: 'Token 使用量', description: '查看本应用记录的模型用量。', period: '统计范围', days7: '近 7 天', days30: '近 30 天', refresh: '刷新',
  loading: '正在加载用量…', failed: '无法加载用量，请稍后刷新重试。', empty: '这段时间尚无模型请求记录。',
  total: '已报告总量', input: '输入 Token', output: '输出 Token', requests: '模型请求', coverage: '完整报告',
  coverageValue: '{reported} / {requests} 次请求完整报告', missing: '{partial} 次部分报告 · {unreported} 次未报告',
  incomplete: '部分请求未返回完整用量。以下仅汇总已报告字段，未报告的字段不按 0 计算。',
  range: '{start} — {end} · UTC', trend: '每日 Token 使用量', trendDescription: '输入 {input}，输出 {output}。仅显示接口实际报告的用量；空白日期可能无请求或未报告。',
  dayDetails: '查看逐日明细', date: '日期（UTC）', models: '按模型', modelRequests: '{count} 次请求', unknownModel: '未报告模型', unknownProvider: '未报告服务商', otherModels: '其他模型（合计）',
  knownOnly: '图表与排行仅使用已报告字段；不同字段可能覆盖不同请求。服务商的总量可能还含工具输入，停止或失败请求的快照可能不完整。',
  details: '用量细分', cached: '缓存读取', cacheCreation: '缓存写入', reasoning: '推理 Token',
  subsetNote: '缓存与推理是服务商报告的细分项，不额外加到总量；未提供的字段显示为“—”。',
  scope: '统计来自启用此功能后本应用记录的模型调用，不包含模型连接测试。用量以服务商返回为准，不代表服务商账单。',
  utc: '按 UTC 自然日统计',
}
type UsageText = keyof typeof zh
const en: Record<UsageText, string> = {
  title: 'Token usage', description: 'Model usage recorded by this app.', period: 'Time range', days7: 'Last 7 days', days30: 'Last 30 days', refresh: 'Refresh',
  loading: 'Loading usage…', failed: 'Could not load usage. Refresh to try again.', empty: 'No model requests recorded in this period.',
  total: 'Reported total', input: 'Input tokens', output: 'Output tokens', requests: 'Model requests', coverage: 'Complete reports',
  coverageValue: '{reported} / {requests} requests fully reported', missing: '{partial} partially reported · {unreported} unreported',
  incomplete: 'Some requests did not report complete usage. Only observed fields are summed; missing fields are not counted as zero.',
  range: '{start} — {end} · UTC', trend: 'Daily token usage', trendDescription: 'Input {input}, output {output}. Only provider-reported usage is shown; gaps can mean no requests or unreported usage.',
  dayDetails: 'View daily details', date: 'Date (UTC)', models: 'By model', modelRequests: '{count} requests', unknownModel: 'Unreported model', unknownProvider: 'Unreported provider', otherModels: 'Other models (combined)',
  knownOnly: 'Charts and rankings use reported fields only; each field may cover different requests. Provider totals may also include tool input, and snapshots from stopped or failed requests may be incomplete.',
  details: 'Usage breakdown', cached: 'Cache reads', cacheCreation: 'Cache writes', reasoning: 'Reasoning tokens',
  subsetNote: 'Cache and reasoning are provider-reported breakdowns, not extra amounts to add to the total. Unreported fields show “—”.',
  scope: 'Local app records since usage tracking was introduced. Model connection tests are excluded. Counts come from providers and are not a provider billing statement.',
  utc: 'UTC calendar days',
}
const ja: Record<UsageText, string> = {
  title: 'トークン使用量', description: 'このアプリが記録したモデル使用量。', period: '集計期間', days7: '過去 7 日', days30: '過去 30 日', refresh: '更新',
  loading: '使用量を読み込み中…', failed: '使用量を読み込めません。更新して再試行してください。', empty: 'この期間のモデルリクエスト記録はありません。',
  total: '報告済み合計', input: '入力トークン', output: '出力トークン', requests: 'モデルリクエスト', coverage: '完全な報告',
  coverageValue: '{reported} / {requests} 件が完全に報告', missing: '部分報告 {partial} 件 · 未報告 {unreported} 件',
  incomplete: '使用量の報告が不完全なリクエストがあります。報告済みの項目だけを集計し、未報告は 0 として扱いません。',
  range: '{start} — {end} · UTC', trend: '日別トークン使用量', trendDescription: '入力 {input}、出力 {output}。サービス側が報告した使用量のみ表示します。空白はリクエストなし、または未報告です。',
  dayDetails: '日別明細を見る', date: '日付（UTC）', models: 'モデル別', modelRequests: '{count} 件', unknownModel: 'モデル未報告', unknownProvider: 'サービス未報告', otherModels: 'その他のモデル（合計）',
  knownOnly: 'グラフと順位は報告済みの項目のみを表示します。項目ごとに対象が異なる場合があります。合計にはツール入力が含まれることがあり、停止・失敗時の値は不完全な場合があります。',
  details: '使用量の内訳', cached: 'キャッシュ読み取り', cacheCreation: 'キャッシュ書き込み', reasoning: '推論トークン',
  subsetNote: 'キャッシュと推論はサービス側の内訳であり、合計に加算しません。未報告の項目は「—」と表示します。',
  scope: 'この機能の導入後にアプリが記録した呼び出しを集計し、モデル接続テストは含みません。使用量はサービス側の報告に基づき、請求明細ではありません。',
  utc: 'UTC の暦日で集計',
}
export const usageCatalogs: Record<Locale, Record<UsageText, string>> = { zh, en, ja }
export function usageText(key: UsageText, params?: Record<string, number | string>): string {
  let value = usageCatalogs[locale.value][key]
  for (const [name, replacement] of Object.entries(params || {})) value = value.split(`{${name}}`).join(String(replacement))
  return value
}
