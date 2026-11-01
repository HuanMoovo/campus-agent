<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, type CloudModelProvider, type ModelCapability, type ModelConfig, type ModelDiagnostic } from '../api'
import { createModelDraft, diagnosticCapabilities, isModelDraftDirty, modelHostChangeNeedsKey, modelSavePayload, safeModelEndpoint } from '../model-settings'
import { t } from '../i18n'
import { MODEL_PROTOCOLS, modelCatalog, officialDocsUrl, providerGroups } from '../model-providers'
import { REASONING_LEVELS } from '../reasoning'

const props = defineProps<{ config: ModelConfig | null; loadError?: string }>()
const emit = defineEmits<{ 'update:config': [value: ModelConfig]; saved: [] }>()
const provider = ref<CloudModelProvider>('qwen')
const groups = computed(() => providerGroups(props.config))
const preset = computed(() => modelCatalog(props.config).find(item => item.id === provider.value))
const capabilities: ModelCapability[] = ['chat', 'streaming', 'tools']
const saved = computed(() => props.config?.providers[provider.value])
const draft = ref(createModelDraft(saved.value, preset.value))
const reasoningSupport = ref(selectedReasoningSupport())
const canConfigureReasoning = computed(() => draft.value.protocol === 'chat_completions' || draft.value.protocol === 'responses')
const dirty = computed(() => isModelDraftDirty(draft.value, saved.value, preset.value))
const hasKey = computed(() => saved.value?.api_key_set ?? saved.value?.configured ?? false)
const action = ref('')
const error = ref('')
const notice = ref('')
const result = ref<{ diagnostic: ModelDiagnostic; capability: ModelCapability; provider: CloudModelProvider; model: string; endpoint: string } | null>(null)
const statuses = computed(() => result.value ? diagnosticCapabilities(result.value.diagnostic, result.value.capability) : null)

function selectedReasoningSupport() {
  const efforts = draft.value.request_options.reasoning_efforts
  return efforts == null ? 'auto' : efforts.length ? 'manual' : 'disabled'
}
function changeReasoningSupport() {
  draft.value.request_options.reasoning_efforts = reasoningSupport.value === 'auto' ? null : []
}
watch(draft, () => { reasoningSupport.value = selectedReasoningSupport() })

watch(provider, () => {
  draft.value = createModelDraft(saved.value, preset.value)
  result.value = null
  error.value = ''
  notice.value = ''
})
watch(saved, (value, previous) => {
  if (!previous || !isModelDraftDirty(draft.value, previous, preset.value)) draft.value = createModelDraft(value, preset.value)
})

function providerLabel(value: string) {
  return value === 'openai_compatible' ? t('model.compatible') : modelCatalog(props.config).find(item => item.id === value)?.label || value
}
function probeDisabled(capability: ModelCapability) {
  return Boolean(action.value) || dirty.value || !saved.value?.configured
    || (capability === 'tools' && !draft.value.request_options.supports_tools)
    || (capability === 'streaming' && !draft.value.request_options.supports_streaming)
}

async function save(clear = false) {
  if (action.value || !props.config) return
  error.value = ''
  notice.value = ''
  const limit = draft.value.request_options.max_output_tokens
  if (!clear && (typeof limit !== 'number' || !Number.isInteger(limit) || limit < 64 || limit > 65536)) {
    error.value = t('model.invalidOutputLimit')
    return
  }
  if (!clear && modelHostChangeNeedsKey(draft.value, saved.value)) {
    error.value = t('model.hostChangeNeedsKey')
    return
  }
  if (!clear && canConfigureReasoning.value && reasoningSupport.value === 'manual' && !draft.value.request_options.reasoning_efforts?.length) {
    error.value = t('model.reasoningSupportSelectAtLeastOne')
    return
  }
  action.value = clear ? 'clear' : 'save'
  try {
    const config = await api.saveModelConfig(provider.value, clear ? { clear_api_key: true } : modelSavePayload(draft.value))
    if (clear) draft.value.api_key = ''
    else draft.value = createModelDraft(config.providers[provider.value], preset.value)
    result.value = null
    emit('update:config', config)
    emit('saved')
    notice.value = clear ? 'model.keyCleared' : 'model.saved'
  } catch {
    error.value = t('model.saveFailed')
  } finally { action.value = '' }
}

async function probe(capability: ModelCapability) {
  if (probeDisabled(capability)) return
  action.value = capability
  error.value = ''
  notice.value = ''
  const metadata = { capability, provider: provider.value, model: saved.value?.model || '', endpoint: safeModelEndpoint(saved.value?.base_url || '') }
  try {
    result.value = { ...metadata, diagnostic: await api.testModel(provider.value, capability) }
  } catch {
    result.value = { ...metadata, diagnostic: { ok: false, error: t('model.testFailed') } }
  } finally { action.value = '' }
}
</script>

<template>
  <section class="settings-panel model-settings" :aria-label="t('model.title')">
    <div class="panel-heading"><h2>{{ t('model.title') }}</h2><p>{{ t('model.description') }}</p></div>
    <div class="model-provider-row">
      <label class="model-field model-provider"><span>{{ t('model.provider') }}</span><select v-model="provider" :disabled="Boolean(action)"><optgroup v-for="group in groups" :key="group.id" :label="t(`model.group.${group.id}`)"><option v-for="item in group.entries" :key="item.id" :value="item.id">{{ providerLabel(item.id) }}</option></optgroup></select></label>
      <span class="model-key-status">{{ hasKey ? t('model.keySet') : t('model.keyUnset') }}</span>
    </div>
    <p class="model-note">{{ t('model.presetNote') }}</p>
    <p v-if="preset?.note" class="model-note">{{ preset.note }}</p>
    <p v-if="officialDocsUrl(preset)" class="model-note"><a class="model-docs" :href="officialDocsUrl(preset)" target="_blank" rel="noopener noreferrer">{{ t('model.officialDocs') }}</a></p>
    <p v-if="provider === 'openai_compatible'" class="model-note">{{ t('model.compatibleNote') }}</p>
    <form @submit.prevent="save()">
      <fieldset :disabled="Boolean(action) || !config">
        <div class="model-fields">
          <label class="model-field"><span>API Key</span><input v-model="draft.api_key" name="api_key" type="password" autocomplete="new-password" :placeholder="t('model.keyPlaceholder')" /></label>
          <label class="model-field"><span>{{ t('model.endpoint') }}</span><input v-model="draft.base_url" name="base_url" type="url" placeholder="https://…/v1" spellcheck="false" /></label>
          <label class="model-field"><span>{{ t('model.name') }}</span><input v-model="draft.model" name="model" :placeholder="t('model.namePlaceholder')" spellcheck="false" /></label>
          <label class="model-field"><span>{{ t('model.protocol') }}</span><select v-model="draft.protocol" name="protocol"><option v-for="item in MODEL_PROTOCOLS" :key="item.id" :value="item.id">{{ item.label }}</option></select></label>
        </div>
        <details class="model-advanced">
          <summary>{{ t('model.advanced') }}</summary>
          <p class="model-note">{{ t('model.optionsNote') }}</p>
          <label class="model-field"><span>{{ t('model.outputLimit') }}</span><input v-model.number="draft.request_options.max_output_tokens" name="max_output_tokens" type="number" min="64" max="65536" step="1" required /></label>
          <label v-if="draft.protocol === 'chat_completions'" class="model-field"><span>{{ t('model.tokenParameter') }}</span><select v-model="draft.request_options.token_parameter" name="token_parameter"><option value="max_tokens">max_tokens</option><option value="max_completion_tokens">max_completion_tokens</option></select></label>
          <template v-if="canConfigureReasoning">
            <label class="model-field"><span>{{ t('model.reasoningSupportLabel') }}</span><select v-model="reasoningSupport" name="reasoning_support" aria-describedby="model-reasoning-help" @change="changeReasoningSupport"><option value="auto">{{ t('model.reasoningSupportAuto') }}</option><option value="disabled">{{ t('model.reasoningSupportDisabled') }}</option><option value="manual">{{ t('model.reasoningSupportManual') }}</option></select></label>
            <p id="model-reasoning-help" class="model-note">{{ t('model.reasoningSupportHelp') }}</p>
            <template v-if="reasoningSupport === 'manual'">
              <p id="model-reasoning-manual-help" class="model-note">{{ t('model.reasoningSupportManualHelp') }}</p>
              <div class="model-reasoning-levels" role="group" :aria-label="t('model.reasoningSupportLabel')" aria-describedby="model-reasoning-manual-help">
                <label v-for="level in REASONING_LEVELS" :key="level" class="model-check"><input v-model="draft.request_options.reasoning_efforts" name="reasoning_efforts" type="checkbox" :value="level" /><span>{{ t(`chat.reasoningLevel.${level}`) }}</span></label>
              </div>
            </template>
          </template>
          <p v-else class="model-note">{{ t('model.reasoningSupportNative') }}</p>
          <label class="model-check"><input v-model="draft.request_options.send_temperature" name="send_temperature" type="checkbox" /><span>{{ t('model.temperature') }}</span></label>
          <label class="model-check"><input v-model="draft.request_options.supports_streaming" name="supports_streaming" type="checkbox" /><span>{{ t('model.streamingOption') }}</span></label>
          <template v-if="draft.protocol === 'chat_completions'">
            <label class="model-check"><input v-model="draft.request_options.stream_usage" name="stream_usage" type="checkbox" aria-describedby="model-stream-usage-help" /><span>{{ t('model.streamUsage') }}</span></label>
            <p id="model-stream-usage-help" class="model-note">{{ t('model.streamUsageHelp') }}</p>
          </template>
          <label class="model-check"><input v-model="draft.request_options.supports_tools" name="supports_tools" type="checkbox" /><span>{{ t('model.toolsOption') }}</span></label>
        </details>
        <div class="model-actions"><button class="model-primary" type="submit" data-action="save">{{ action === 'save' ? t('model.saving') : t('model.save') }}</button><button type="button" data-action="clear" :disabled="!hasKey" @click="save(true)">{{ t('model.clearKey') }}</button></div>
      </fieldset>
    </form>
    <p v-if="notice" class="model-note" aria-live="polite">{{ t(notice) }}</p>
    <p v-if="error || loadError" class="model-error" role="alert">{{ error || loadError }}</p>
    <div class="model-probes">
      <h3>{{ t('model.testSaved') }}</h3>
      <p v-if="dirty" class="model-note">{{ t('model.unsaved') }}</p>
      <p v-else class="model-note">{{ t('model.probeNote') }}</p>
      <p v-if="saved?.model" class="model-saved-meta">{{ providerLabel(provider) }} · {{ saved.model }}<span v-if="safeModelEndpoint(saved.base_url)"> · {{ safeModelEndpoint(saved.base_url) }}</span></p>
      <div class="model-actions"><button v-for="capability in capabilities" :key="capability" type="button" :data-probe="capability" :disabled="probeDisabled(capability)" @click="probe(capability)">{{ action === capability ? t('model.testing') : t(`model.test.${capability}`) }}</button></div>
    </div>
    <div v-if="result" class="model-result" role="status" aria-live="polite">
      <div class="model-result-heading"><strong>{{ result.diagnostic.ok ? t('model.testPassed') : t('model.testUnverified') }}</strong><span v-if="result.diagnostic.latency_ms !== undefined">{{ Math.round(result.diagnostic.latency_ms) }} ms</span></div>
      <p class="model-note">{{ t('model.testedConfig') }}: {{ providerLabel(result.diagnostic.provider || result.provider) }} · {{ result.diagnostic.model || result.model }}<span v-if="result.endpoint"> · {{ result.endpoint }}</span> · {{ result.diagnostic.protocol || 'Chat Completions' }}</p>
      <ul class="model-capabilities"><li v-for="capability in capabilities" :key="capability" :data-capability="capability"><span>{{ t(`model.capability.${capability}`) }}</span><span>{{ t(`model.status.${statuses?.[capability]}`) }}</span></li></ul>
      <p v-if="result.diagnostic.error" class="model-note">{{ result.diagnostic.error }}</p>
      <p v-if="result.diagnostic.error_code || result.diagnostic.http_status" class="model-note model-error-code"><code v-if="result.diagnostic.error_code">{{ result.diagnostic.error_code }}</code><span v-if="result.diagnostic.http_status"> HTTP {{ result.diagnostic.http_status }}</span></p>
      <p v-if="result.diagnostic.hint" class="model-note">{{ result.diagnostic.hint }}</p>
    </div>
  </section>
</template>

<style scoped>
.model-settings { min-width: 0; overflow-wrap: anywhere; }
.model-settings fieldset { margin: 0; padding: 0; border: 0; min-width: 0; }
.model-provider-row { display: flex; align-items: end; flex-wrap: wrap; gap: 12px 20px; margin-bottom: 18px; }
.model-key-status, .model-note, .model-saved-meta { font-size: 12px; color: var(--text-muted); line-height: 1.7; }
.model-key-status { padding-bottom: 9px; }
.model-docs { color: inherit; text-underline-offset: 3px; }
.model-fields { display: grid; gap: 14px; }
.model-field { display: grid; gap: 7px; font-size: 13px; color: var(--text-secondary); min-width: 0; }
.model-field input, .model-field select { width: 100%; min-width: 0; box-sizing: border-box; border: 1px solid var(--border-subtle); border-radius: 7px; padding: 10px 11px; color: var(--text); background: var(--surface); font: inherit; }
.model-provider { width: 210px; max-width: 100%; }
.model-settings :is(input, select, button, summary):focus-visible { outline: 2px solid var(--text-muted); outline-offset: 3px; }
.model-advanced { margin-top: 18px; font-size: 13px; border-top: 1px solid var(--border-subtle); padding-top: 14px; }
.model-advanced summary { cursor: pointer; width: fit-content; max-width: 100%; }
.model-advanced .model-field { max-width: 300px; margin-bottom: 13px; }
.model-check { display: flex; align-items: start; gap: 8px; margin: 10px 0; color: var(--text-secondary); line-height: 1.6; }
.model-check input { margin: 3px 0 0; flex-shrink: 0; accent-color: var(--text); }
.model-reasoning-levels { display: flex; flex-wrap: wrap; gap: 0 18px; }
.model-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.model-actions button { min-width: 0; max-width: 100%; border: 1px solid var(--border-subtle); border-radius: 7px; background: transparent; color: var(--text); padding: 9px 13px; font: inherit; font-size: 12px; line-height: 1.5; cursor: pointer; white-space: normal; }
.model-actions .model-primary { background: var(--text); color: var(--surface); border-color: var(--text); }
.model-settings :disabled { opacity: .5; cursor: not-allowed; }
.model-settings fieldset:disabled { opacity: 1; }
.model-probes { margin-top: 24px; border-top: 1px solid var(--border-subtle); padding-top: 18px; }
.model-probes h3 { margin: 0; font-size: 13px; font-weight: 600; }
.model-probes p { margin: 7px 0 0; }
.model-result { margin-top: 18px; padding: 15px; border: 1px solid var(--border-subtle); border-radius: 8px; }
.model-result-heading { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px 16px; font-size: 13px; }
.model-result-heading > span { color: var(--text-muted); font-variant-numeric: tabular-nums; }
.model-result p:last-child { margin-bottom: 0; }
.model-capabilities { display: grid; gap: 5px; padding: 0; list-style: none; font-size: 12px; }
.model-capabilities li { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 14px; }
.model-capabilities li span:last-child { color: var(--text-muted); }
.model-error { font-size: 12px; line-height: 1.7; color: var(--text); }
@media (max-width: 480px) { .model-provider { width: 100%; } .model-provider-row { gap: 4px; } .model-key-status { padding: 0; } .model-result { padding: 12px; } }
</style>
