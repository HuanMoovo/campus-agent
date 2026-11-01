<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { locale } from '../i18n'
import { chartDays, formatTokens, usageReport, type UsageReport } from '../token-usage'
import { usageText as text } from '../token-usage-i18n'

const props = defineProps<{ active: boolean; clientId: string }>()
const days = ref<7 | 30>(7)
const report = ref<UsageReport | null>(null)
const loading = ref(false)
const failed = ref(false)
const uid = useId().replace(/[^\w-]/g, '')
const patternId = `usage-output-${uid}`
const titleId = `usage-title-${uid}`
const descriptionId = `usage-description-${uid}`
const bars = computed(() => chartDays(report.value?.daily || []))
const metrics = ['total_tokens', 'input_tokens', 'output_tokens'] as const
const metricLabels = { total_tokens: 'total', input_tokens: 'input', output_tokens: 'output' } as const
const detailFields = ['cached_input_tokens', 'cache_creation_input_tokens', 'reasoning_tokens'] as const
const detailLabels = { cached_input_tokens: 'cached', cache_creation_input_tokens: 'cacheCreation', reasoning_tokens: 'reasoning' } as const
const models = computed(() => [...(report.value?.models || [])].sort((first, second) => (second.total_tokens ?? -1) - (first.total_tokens ?? -1) || first.provider.localeCompare(second.provider) || first.model.localeCompare(second.model)))
const maximumModel = computed(() => Math.max(0, ...models.value.map(model => model.total_tokens ?? 0)))
const incomplete = computed(() => Boolean(report.value && (report.value.totals.partial_requests || report.value.totals.unreported_requests)))
const number = (value: number | null) => formatTokens(value, locale.value)
let controller: AbortController | undefined
let request = 0
let alive = true

function invalidate() {
  request++
  controller?.abort()
  controller = undefined
  report.value = null
  failed.value = false
  loading.value = false
}
async function load() {
  invalidate()
  if (!alive || !props.active || !props.clientId) return
  const ticket = request
  controller = new AbortController()
  const current = () => alive && props.active && request === ticket
  loading.value = true
  try {
    const result = await usageReport(props.clientId, days.value, controller.signal)
    if (current()) report.value = result
  } catch {
    if (current()) failed.value = true
  } finally {
    if (current()) { loading.value = false; controller = undefined }
  }
}
watch(() => [props.active, props.clientId, days.value], () => { void load() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { alive = false; invalidate() })
</script>

<template>
  <section class="usage-settings" :aria-label="text('title')" :aria-busy="loading">
    <header class="usage-heading">
      <div><h2>{{ text('title') }}</h2><p>{{ text('description') }}</p></div>
      <el-button data-usage-refresh :icon="Refresh" :disabled="loading || !active || !clientId" @click="load">{{ text('refresh') }}</el-button>
    </header>
    <div class="usage-toolbar">
      <div class="usage-period" role="group" :aria-label="text('period')">
        <button v-for="period in [7, 30] as const" :key="period" type="button" :data-usage-days="period" :aria-pressed="days === period" :disabled="!active" @click="days = period">{{ text(period === 7 ? 'days7' : 'days30') }}</button>
      </div>
      <span>{{ report ? text('range', { start: report.start_date, end: report.end_date }) : text('utc') }}</span>
    </div>
    <p v-if="loading" class="usage-state" role="status">{{ text('loading') }}</p>
    <p v-else-if="failed" class="usage-state usage-error" role="alert">{{ text('failed') }}</p>
    <p v-else-if="report && !report.totals.requests" class="usage-state" data-usage-empty>{{ text('empty') }}</p>
    <template v-else-if="report">
      <dl class="usage-metrics">
        <div v-for="key in metrics" :key="key" :data-metric="key"><dt>{{ text(metricLabels[key]) }}</dt><dd>{{ number(report.totals[key]) }}</dd></div>
      </dl>
      <div class="usage-coverage">
        <span><strong>{{ number(report.totals.requests) }}</strong> {{ text('requests') }}</span>
        <span data-usage-coverage>{{ text('coverageValue', { reported: number(report.totals.reported_requests), requests: number(report.totals.requests) }) }}</span>
      </div>
      <div v-if="incomplete" class="usage-notice"><strong>{{ text('missing', { partial: number(report.totals.partial_requests), unreported: number(report.totals.unreported_requests) }) }}</strong><p>{{ text('incomplete') }}</p></div>
      <div class="usage-chart-section">
        <div class="usage-section-heading"><h3>{{ text('trend') }}</h3><div class="usage-legend"><span><i class="usage-input-swatch" />{{ text('input') }}</span><span><i class="usage-output-swatch" />{{ text('output') }}</span></div></div>
        <svg class="usage-chart" viewBox="0 0 600 180" role="img" :aria-labelledby="`${titleId} ${descriptionId}`">
          <title :id="titleId">{{ text('trend') }}</title>
          <desc :id="descriptionId">{{ text('trendDescription', { input: number(report.totals.input_tokens), output: number(report.totals.output_tokens) }) }}</desc>
          <defs><pattern :id="patternId" width="4" height="4" patternUnits="userSpaceOnUse"><path d="M-1 1L1-1M0 4L4 0M3 5L5 3" fill="none" stroke="currentColor" stroke-width="1" /></pattern></defs>
          <line x1="0" y1="150" x2="600" y2="150" class="usage-baseline" />
          <g v-for="(day, index) in bars" :key="day.date">
            <rect v-if="day.inputHeight" :x="day.x + day.step / 2 - day.barWidth - 1" :y="150 - day.inputHeight" :width="day.barWidth" :height="day.inputHeight" class="usage-input-bar" />
            <rect v-if="day.outputHeight" :x="day.x + day.step / 2 + 1" :y="150 - day.outputHeight" :width="day.barWidth" :height="day.outputHeight" :fill="`url(#${patternId})`" class="usage-output-bar" />
            <text v-if="index === 0 || index === bars.length - 1 || index === Math.floor((bars.length - 1) / 2)" :x="day.x + day.step / 2" y="173" text-anchor="middle">{{ day.date.slice(5) }}</text>
          </g>
        </svg>
        <p class="usage-note">{{ text('knownOnly') }}</p>
        <details class="usage-daily-details">
          <summary>{{ text('dayDetails') }}</summary>
          <div class="usage-table-scroll" role="region" :aria-label="text('dayDetails')" tabindex="0"><table><thead><tr><th scope="col">{{ text('date') }}</th><th scope="col">{{ text('input') }}</th><th scope="col">{{ text('output') }}</th><th scope="col">{{ text('total') }}</th><th scope="col">{{ text('requests') }}</th></tr></thead><tbody><tr v-for="day in report.daily" :key="day.date"><th scope="row">{{ day.date }}</th><td>{{ number(day.input_tokens) }}</td><td>{{ number(day.output_tokens) }}</td><td>{{ number(day.total_tokens) }}</td><td>{{ number(day.requests) }}</td></tr></tbody></table></div>
        </details>
      </div>
      <div v-if="models.length" class="usage-model-section">
        <h3>{{ text('models') }}</h3>
        <ul class="usage-models"><li v-for="(item, index) in models" :key="`${item.provider}:${item.model}:${index}`"><div class="usage-model-heading"><div><strong>{{ item.provider === 'other' && !item.model ? text('otherModels') : item.model || text('unknownModel') }}</strong><small><template v-if="item.provider !== 'other' || item.model">{{ item.provider || text('unknownProvider') }} · </template>{{ text('modelRequests', { count: number(item.requests) }) }}</small></div><span>{{ number(item.total_tokens) }}</span></div><div v-if="item.total_tokens !== null && maximumModel" class="usage-model-track" aria-hidden="true"><div :style="{ width: `${item.total_tokens / maximumModel * 100}%` }" /></div></li></ul>
      </div>
      <div class="usage-detail-section">
        <h3>{{ text('details') }}</h3>
        <dl class="usage-detail-counts"><div v-for="key in detailFields" :key="key"><dt>{{ text(detailLabels[key]) }}</dt><dd>{{ number(report.totals[key]) }}</dd></div></dl>
        <p class="usage-note">{{ text('subsetNote') }}</p>
      </div>
    </template>
    <p class="usage-scope">{{ text('scope') }}</p>
  </section>
</template>

<style scoped>
.usage-settings { min-width: 0; color: var(--text); }
.usage-heading, .usage-toolbar, .usage-section-heading, .usage-model-heading { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.usage-heading { align-items: start; }
.usage-heading h2 { margin: 0; font-size: 18px; font-weight: 600; }
.usage-heading p, .usage-note, .usage-scope, .usage-notice p { margin: 7px 0 0; color: var(--text-muted); font-size: 12px; line-height: 1.7; }
.usage-toolbar { margin: 24px 0 0; flex-wrap: wrap; }
.usage-toolbar > span { font-size: 11px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.usage-period { display: flex; gap: 3px; padding: 3px; background: var(--surface-muted); border-radius: 7px; }
.usage-period button { border: 0; padding: 7px 11px; border-radius: 5px; background: transparent; color: var(--text-muted); font: inherit; font-size: 12px; cursor: pointer; }
.usage-period button[aria-pressed="true"] { background: var(--surface); color: var(--text); box-shadow: 0 0 0 1px var(--border-subtle); }
.usage-settings :is(button, summary, [tabindex]):focus-visible { outline: 2px solid var(--text-muted); outline-offset: 3px; }
.usage-state { min-height: 150px; display: grid; place-items: center; margin: 0; color: var(--text-muted); font-size: 13px; line-height: 1.8; text-align: center; }
.usage-error { color: var(--text); }
.usage-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 26px 0 0; padding: 0 0 23px; border-bottom: 1px solid var(--border-subtle); }
.usage-metrics div, .usage-detail-counts div { min-width: 0; }
.usage-metrics dt, .usage-detail-counts dt { color: var(--text-muted); font-size: 12px; line-height: 1.6; }
.usage-metrics dd { font-size: clamp(20px, 2.6vw, 32px); letter-spacing: -.8px; line-height: 1.3; font-weight: 600; }
.usage-metrics dd, .usage-detail-counts dd { margin: 8px 0 0; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.usage-coverage { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px 15px; margin-top: 14px; font-size: 12px; color: var(--text-muted); }
.usage-coverage strong { font-weight: 500; color: var(--text); }
.usage-notice { margin-top: 18px; padding-left: 12px; border-left: 2px solid var(--text-muted); font-size: 12px; line-height: 1.7; }
.usage-notice strong { font-weight: 500; }
.usage-notice p { margin-top: 3px; }
.usage-chart-section, .usage-model-section, .usage-detail-section { margin-top: 30px; }
.usage-section-heading { flex-wrap: wrap; gap: 9px 16px; }
.usage-settings h3 { margin: 0; font-size: 13px; line-height: 1.7; font-weight: 600; }
.usage-legend { display: flex; flex-wrap: wrap; gap: 12px; font-size: 11px; color: var(--text-muted); }
.usage-legend span { display: inline-flex; align-items: center; gap: 5px; }
.usage-legend i { display: block; width: 9px; height: 9px; border: 1px solid var(--text-secondary); }
.usage-input-swatch { background: var(--text-secondary); }
.usage-output-swatch { background: repeating-linear-gradient(135deg, transparent 0 2px, var(--text-secondary) 2px 3px); }
.usage-chart { display: block; width: 100%; height: auto; margin-top: 18px; overflow: visible; color: var(--text-secondary); }
.usage-chart text { font: 11px var(--font-ui); fill: var(--text-muted); }
.usage-baseline { stroke: var(--border); stroke-width: 1; }
.usage-input-bar { fill: var(--text-secondary); }
.usage-output-bar { stroke: var(--text-secondary); stroke-width: .8; }
.usage-daily-details { margin-top: 14px; font-size: 12px; }
.usage-daily-details summary { color: var(--text-secondary); cursor: pointer; width: fit-content; }
.usage-table-scroll { overflow-x: auto; max-width: 100%; margin-top: 12px; }
.usage-table-scroll table { width: 100%; border-collapse: collapse; white-space: nowrap; color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.usage-table-scroll th, .usage-table-scroll td { padding: 9px 10px; text-align: right; border-bottom: 1px solid var(--border-subtle); font-weight: 400; }
.usage-table-scroll thead th { color: var(--text-muted); font-size: 11px; }
.usage-table-scroll :is(th, td):first-child { text-align: left; padding-left: 0; }
.usage-models { list-style: none; padding: 0; margin: 15px 0 0; display: grid; gap: 18px; }
.usage-model-heading > div { min-width: 0; }
.usage-model-heading strong { font-size: 12px; font-weight: 500; overflow-wrap: anywhere; }
.usage-model-heading small { display: block; margin-top: 3px; color: var(--text-muted); font-size: 11px; overflow-wrap: anywhere; }
.usage-model-heading > span { font-size: 12px; font-variant-numeric: tabular-nums; }
.usage-model-track { margin-top: 8px; height: 3px; background: var(--surface-muted); }
.usage-model-track > div { height: 100%; background: var(--text-secondary); }
.usage-detail-section { padding-top: 22px; border-top: 1px solid var(--border-subtle); }
.usage-detail-counts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 15px 0 0; }
.usage-detail-counts dd { margin-top: 5px; font-size: 15px; }
.usage-scope { margin-top: 27px; padding-top: 16px; border-top: 1px solid var(--border-subtle); }
@media (max-width: 480px) {
  .usage-toolbar { gap: 10px; }
  .usage-metrics { gap: 8px; }
  .usage-metrics dt, .usage-detail-counts dt { font-size: 11px; }
  .usage-metrics dd { font-size: 21px; letter-spacing: -.5px; }
  .usage-detail-counts { gap: 8px; }
  .usage-coverage { font-size: 11px; }
}
</style>
