<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { ElConfigProvider, ElDialog } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'
import ja from 'element-plus/es/locale/lang/ja'
import { api } from '../api'
import { locale, t } from '../i18n'
import { ProjectProposalError, proposalErrorMessage, type ProjectProposal } from '../project-proposals'
import type { ReasoningPreference } from '../reasoning'
import ProjectDiff from './ProjectDiff.vue'
import ProjectChangeActions from './ProjectChangeActions.vue'
import type { ProjectChangeReceipt } from '../desktop'

const props = withDefaults(defineProps<{
  modelValue: boolean
  projectId: string
  path: string
  model?: string
  localModel?: string
  reasoning?: ReasoningPreference | 'fast'
  disabled?: boolean
  connected?: boolean
  changesAvailable?: boolean
  writeAllowed?: boolean
}>(), { model: 'auto', reasoning: 'auto', connected: true, writeAllowed: true })
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; busy: [value: boolean]; changed: [receipt: ProjectChangeReceipt] }>()
const visible = computed({ get: () => props.modelValue, set: (value: boolean) => emit('update:modelValue', value) })
const dialogLocale = computed(() => ({ zh: zhCn, en, ja })[locale.value])
const instruction = ref('')
const proposal = ref<ProjectProposal | null>(null)
const operation = ref<'' | 'generate' | 'check' | 'copy'>('')
const error = ref('')
const notice = ref('')
const expired = ref(false)
const view = ref<'diff' | 'before' | 'after'>('diff')
const changeBusy = ref(false)
const changedVersion = ref(false)
const changeUnresolved = ref(false)
const busy = computed(() => operation.value !== '' || changeBusy.value)
const canCheck = computed(() => Boolean(proposal.value && proposal.value.state === 'ready' && !changedVersion.value && !expired.value && !busy.value && !props.disabled && props.connected))
const format = computed(() => {
  if (!proposal.value) return ''
  const original = newlineLabel(proposal.value.newline)
  const changed = newlineLabel(proposal.value.after_newline || proposal.value.newline)
  return t('project.proposal.format', {
    encoding: proposal.value.bom ? t('project.proposal.encodingBom') : 'UTF-8',
    newline: original === changed ? original : `${original} → ${changed}`,
  })
})
let alive = true
let epoch = 0
let request = 0
watch(busy, value => emit('busy', value), { flush: 'sync' })

function newlineLabel(newline: ProjectProposal['newline']) {
  if (newline === 'none') return t('project.proposal.newline.none')
  if (newline === 'mixed') return t('project.proposal.newline.mixed')
  return newline.toUpperCase()
}

function begin(next: 'generate' | 'check' | 'copy') {
  const token = { epoch, request: ++request, projectId: props.projectId, path: props.path }
  operation.value = next; error.value = ''; notice.value = ''
  return token
}
function current(token: ReturnType<typeof begin>) {
  return alive && props.connected && token.epoch === epoch && token.request === request && token.projectId === props.projectId && token.path === props.path
}
function matches(result: ProjectProposal, id?: string) {
  return result.project_id === props.projectId && result.path === props.path && (!id || result.id === id)
}
async function generate() {
  const requirement = instruction.value.trim()
  if (!requirement || props.disabled || !props.connected || busy.value || changeUnresolved.value) return
  const token = begin('generate')
  proposal.value = null; expired.value = false; view.value = 'diff'
  changedVersion.value = false
  try {
    const result = await api.projectPropose(token.projectId, { path: token.path, instruction: requirement, model: props.model, localModel: props.localModel, reasoning: props.reasoning })
    if (!current(token)) return
    if (!matches(result)) throw new ProjectProposalError('project_proposal_invalid_result', 502)
    proposal.value = result
  } catch (failure) {
    if (current(token)) error.value = proposalErrorMessage(failure)
  } finally { if (current(token)) operation.value = '' }
}
async function check(copy = false) {
  if (!canCheck.value || !proposal.value) return
  const id = proposal.value.id
  const token = begin(copy ? 'copy' : 'check')
  try {
    const result = await api.projectProposal(token.projectId, id)
    if (!current(token) || proposal.value?.id !== id) return
    if (!matches(result, id)) throw new ProjectProposalError('project_proposal_invalid_result', 502)
    proposal.value = result
    if (result.state !== 'ready') return
    if (copy) {
      try {
        if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable')
        await navigator.clipboard.writeText(result.after_text)
        if (current(token)) notice.value = t('project.proposal.copied')
      } catch { if (current(token)) error.value = t('project.proposal.copyFailed') }
    } else notice.value = t('project.proposal.verified')
  } catch (failure) {
    if (!current(token)) return
    if (failure instanceof ProjectProposalError) {
      if (failure.status === 409 && proposal.value) proposal.value = { ...proposal.value, state: 'conflict' }
      if ([403, 404, 410].includes(failure.status)) expired.value = true
    }
    error.value = proposalErrorMessage(failure, true)
  } finally { if (current(token)) operation.value = '' }
}

watch(() => [props.projectId, props.path, props.connected] as const, () => {
  epoch++; request++; operation.value = ''; proposal.value = null; instruction.value = ''; error.value = ''; notice.value = ''; expired.value = false
  changeBusy.value = false; changedVersion.value = false; changeUnresolved.value = false
  emit('update:modelValue', false)
}, { flush: 'sync' })
function changed(receipt: ProjectChangeReceipt) {
  if (receipt.project_id !== props.projectId) return
  changeUnresolved.value = receipt.state === 'pending' || receipt.state === 'uncertain'
  if (['pending', 'uncertain', 'applied', 'reverted', 'kept'].includes(receipt.state)) changedVersion.value = true
  emit('changed', receipt)
}
onUnmounted(() => { alive = false; epoch++; request++; emit('busy', false) })
</script>

<template>
  <ElConfigProvider :locale="dialogLocale">
  <ElDialog v-model="visible" class="project-proposal-dialog" :title="t('project.proposal.title')" width="min(1040px, calc(100vw - 24px))" top="5vh" append-to-body :close-on-click-modal="false">
    <div class="proposal-content" :aria-busy="busy">
      <strong class="proposal-path">{{ path }}</strong>
      <p class="proposal-notice">{{ t('project.proposal.notice') }}</p>
      <label class="proposal-instruction-label" for="project-proposal-instruction">{{ t('project.proposal.instruction') }}</label>
      <textarea id="project-proposal-instruction" v-model="instruction" class="proposal-instruction" rows="3" maxlength="4000" :placeholder="t('project.proposal.instructionPlaceholder')" :disabled="busy || disabled || !connected" />
      <div class="proposal-actions">
        <button class="proposal-generate primary" type="button" :disabled="!instruction.trim() || busy || changeUnresolved || disabled || !connected" @click="generate">{{ t(operation === 'generate' ? 'project.proposal.generating' : proposal ? 'project.proposal.regenerate' : 'project.proposal.generate') }}</button>
        <span v-if="operation === 'generate'" class="proposal-pending" role="status">{{ t('project.proposal.pendingClose') }}</span>
      </div>
      <p v-if="error" class="proposal-error" role="alert">{{ error }}</p>
      <p v-if="notice" class="proposal-status" role="status">{{ notice }}</p>
      <template v-if="proposal">
        <p v-if="proposal.state === 'conflict'" class="proposal-conflict" role="alert">{{ t('project.proposal.conflict') }}</p>
        <p v-else-if="!expired && !changedVersion" class="proposal-state">{{ t('project.proposal.ready') }}</p>
        <p class="proposal-model">{{ t('project.proposal.model', { provider: proposal.model, model: proposal.model_name }) }}</p>
        <p class="proposal-format">{{ format }}</p>
        <div class="proposal-summary"><strong>{{ t('project.proposal.summary') }}</strong><p>{{ proposal.summary }}</p></div>
        <div class="proposal-review-toolbar">
          <strong class="proposal-counts">{{ t('project.proposal.changes', { added: proposal.added_lines, removed: proposal.removed_lines }) }}</strong>
          <div class="proposal-views" role="group" :aria-label="t('project.proposal.view')">
            <button class="proposal-view-diff" type="button" :aria-pressed="view === 'diff'" @click="view = 'diff'">{{ t('project.proposal.diff') }}</button>
            <button class="proposal-view-before" type="button" :aria-pressed="view === 'before'" @click="view = 'before'">{{ t('project.proposal.before') }}</button>
            <button class="proposal-view-after" type="button" :aria-pressed="view === 'after'" @click="view = 'after'">{{ t('project.proposal.after') }}</button>
          </div>
        </div>
        <ProjectDiff v-if="view === 'diff'" :lines="proposal.diff_lines" />
        <pre v-else class="proposal-file-text" tabindex="0">{{ view === 'before' ? proposal.before_text : proposal.after_text }}</pre>
        <div class="proposal-actions proposal-result-actions">
          <button class="proposal-check" type="button" :disabled="!canCheck" @click="check()">{{ t(operation === 'check' ? 'project.proposal.checking' : 'project.proposal.check') }}</button>
          <button class="proposal-copy" type="button" :disabled="!canCheck" @click="check(true)">{{ t('project.proposal.copy') }}</button>
        </div>
        <ProjectChangeActions :write-allowed="writeAllowed" :key="proposal.id" :project-id="projectId" :proposal-id="proposal.state === 'ready' && !expired ? proposal.id : ''" :available="Boolean(changesAvailable)" :connected="connected" :disabled="disabled || operation !== ''" reveal-result @busy="changeBusy = $event" @changed="changed" />
      </template>
    </div>
    <template #footer><button class="proposal-close" type="button" @click="visible = false">{{ t('project.proposal.close') }}</button></template>
  </ElDialog>
  </ElConfigProvider>
</template>

<style scoped>
.proposal-content { min-width: 0; max-height: 72dvh; overflow: auto; color: var(--text, #222); font-size: 13px; line-height: 1.6; }
.proposal-path { display: block; overflow-wrap: anywhere; }
.proposal-notice, .proposal-pending, .proposal-model, .proposal-format { color: var(--text-secondary, #666); }
p { margin: 8px 0; }
.proposal-instruction-label { display: block; margin: 14px 0 5px; font-weight: 600; }
.proposal-instruction { display: block; box-sizing: border-box; width: 100%; min-height: 88px; resize: vertical; border: 1px solid var(--border, #bbb); border-radius: 5px; padding: 9px; background: var(--surface, #fff); color: inherit; font: inherit; }
button { padding: 5px 9px; border: 1px solid var(--border, #bbb); border-radius: 5px; color: var(--text, #222); background: var(--surface, #fff); font: inherit; cursor: pointer; }
button:hover:enabled { background: var(--surface-hover, #eee); }
button:disabled { opacity: .45; cursor: default; }
.primary, button[aria-pressed='true'] { color: var(--surface, #fff); background: var(--text, #222); border-color: var(--text, #222); }
.primary:hover:enabled, button[aria-pressed='true']:hover:enabled { opacity: .85; background: var(--text, #222); }
.proposal-actions, .proposal-review-toolbar, .proposal-views { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.proposal-actions { margin-top: 10px; }
.proposal-pending { flex: 1 1 260px; font-size: 12px; }
.proposal-error, .proposal-conflict { padding: 8px 10px; border: 1px solid var(--text, #222); border-radius: 5px; font-weight: 600; overflow-wrap: anywhere; }
.proposal-state, .proposal-status { font-weight: 600; }
.proposal-summary { margin: 12px 0; overflow-wrap: anywhere; white-space: pre-wrap; }
.proposal-review-toolbar { justify-content: space-between; margin: 14px 0 8px; }
.proposal-counts { font-size: 12px; }
.proposal-file-text { margin: 0; padding: 10px; overflow: auto; border: 1px solid var(--border, #ccc); border-radius: 5px; background: var(--surface, #fff); color: inherit; white-space: pre; font-family: var(--font-code); font-size: 12px; line-height: 1.7; }
.proposal-result-actions { margin-bottom: 2px; }
.proposal-close { font-size: 13px; }
@media (max-width: 540px) { .proposal-content { max-height: 70dvh; font-size: 12px; } .proposal-actions { align-items: stretch; } .proposal-pending { flex-basis: 100%; } .proposal-views { gap: 5px; } }
</style>
