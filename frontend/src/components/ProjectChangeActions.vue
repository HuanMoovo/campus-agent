<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { desktop, type ProjectChangeReceipt } from '../desktop'
import { changeErrorMessage, rememberChangeResult, sameChangeOperation, sameChangeTarget, unresolvedChange } from '../project-changes'
import { t } from '../i18n'

const props = withDefaults(defineProps<{
  projectId: string
  proposalId?: string
  receipt?: ProjectChangeReceipt | null
  available?: boolean
  connected?: boolean
  disabled?: boolean
  revealResult?: boolean
  writeAllowed?: boolean
}>(), { proposalId: '', receipt: null, available: false, connected: true, disabled: false, revealResult: false, writeAllowed: true })
const emit = defineEmits<{ changed: [receipt: ProjectChangeReceipt]; busy: [value: boolean] }>()
const latest = ref<ProjectChangeReceipt | null>(props.receipt)
const waiting = ref(false)
const error = ref('')
const notice = ref('')
const actionsRef = ref<HTMLElement | null>(null)
let alive = true
let epoch = 0
const native = desktop
const enabled = computed(() => Boolean(props.writeAllowed && native?.changeProjectFile && props.available && props.connected && !props.disabled && !waiting.value))
const unknown = computed(() => unresolvedChange(latest.value))
const canApply = computed(() => enabled.value && Boolean(props.proposalId) && !latest.value)
const canRevert = computed(() => enabled.value && latest.value?.state === 'applied' && latest.value.can_revert)
const canKeep = computed(() => enabled.value && latest.value?.state === 'applied')
const canCopy = computed(() => Boolean(native?.projectRecoveryOriginal && props.connected && !props.disabled && !waiting.value && latest.value?.recovery_id))
watch(waiting, value => emit('busy', value), { flush: 'sync' })
watch(() => [props.projectId, props.proposalId] as const, () => {
  epoch++; waiting.value = false; latest.value = props.receipt; error.value = ''; notice.value = ''
}, { flush: 'sync' })
watch(() => props.receipt, (value, previous) => {
  if (waiting.value || !value) return
  if (!latest.value || sameChangeOperation(value, latest.value)
    || (!unresolvedChange(latest.value) && sameChangeOperation(latest.value, previous))) latest.value = value
})
watch(latest, async value => {
  if (!value || !props.revealResult) return
  await nextTick()
  if (alive) actionsRef.value?.scrollIntoView?.({ block: 'nearest' })
})
onUnmounted(() => { alive = false; epoch++; emit('busy', false) })

function current(token: number, projectId: string) { return alive && token === epoch && props.projectId === projectId }

async function change(action: 'apply' | 'revert' | 'keep') {
  if (!enabled.value || !native || unknown.value) return
  if ((action === 'apply' && !canApply.value) || (action === 'revert' && !canRevert.value) || (action === 'keep' && !canKeep.value)) return
  const projectId = props.projectId
  const subjectId = action === 'apply' ? props.proposalId : latest.value?.recovery_id || ''
  const token = epoch
  const prior = latest.value
  const pending: ProjectChangeReceipt = { operation_id: '', project_id: projectId, subject_id: subjectId,
    proposal_id: props.proposalId || prior?.proposal_id || '', recovery_id: action === 'apply' ? '' : subjectId,
    action, state: 'pending', path: prior?.path || '', summary: prior?.summary || '', created_at: new Date().toISOString(), can_revert: false }
  waiting.value = true; error.value = ''; notice.value = ''
  // A replacement panel must remain query-only even before IPC returns.
  // The live caller owns its busy state, so do not refresh its row yet.
  rememberChangeResult(pending, false)
  let received = false
  try {
    const result = await native.changeProjectFile(projectId, subjectId, action)
    received = true
    if (!sameChangeTarget(result, projectId, subjectId, action)) {
      const uncertain: ProjectChangeReceipt = { ...pending, state: 'uncertain' }
      rememberChangeResult(uncertain)
      if (!current(token, projectId)) return
      latest.value = uncertain
      emit('changed', latest.value)
      throw new Error('[project_change_invalid]')
    }
    // Preserve a late validated result even if its original panel was unmounted.
    rememberChangeResult(result)
    if (!current(token, projectId)) return
    if (result.state === 'cancelled') { notice.value = t('project.change.cancelled'); return }
    if (['applied', 'reverted', 'kept', 'pending', 'uncertain'].includes(result.state)) latest.value = result
    else if (!latest.value && (result.recovery_id || result.state === 'conflict')) latest.value = result
    if (result.error_code) error.value = changeErrorMessage(result.error_code)
    emit('changed', result)
  } catch (failure) {
    if (!received) {
      const uncertain: ProjectChangeReceipt = { ...pending, state: 'uncertain' }
      rememberChangeResult(uncertain)
      if (current(token, projectId)) { latest.value = uncertain; emit('changed', uncertain) }
    }
    if (current(token, projectId)) error.value = changeErrorMessage(failure)
  } finally { if (current(token, projectId)) waiting.value = false }
}

async function status() {
  if (!native?.projectChangeStatus || waiting.value || props.disabled || !props.connected || !latest.value) return
  const expected = latest.value
  const projectId = props.projectId; const operationId = expected.operation_id; const token = epoch
  waiting.value = true; error.value = ''; notice.value = ''
  try {
    const result = operationId ? await native.projectChangeStatus(projectId, operationId)
      : (await native.projectChanges(projectId)).records.find(row => row.action === expected.action && row.subject_id === expected.subject_id && row.proposal_id === expected.proposal_id)
    if (!current(token, projectId)) return
    if (!result) throw new Error('[project_change_not_found]')
    if (!sameChangeTarget(result, projectId, expected.subject_id, expected.action) || (operationId && result.operation_id !== operationId)) throw new Error('[project_change_invalid]')
    rememberChangeResult(result)
    latest.value = result; emit('changed', result)
  } catch (failure) { if (current(token, projectId)) error.value = changeErrorMessage(failure) }
  finally { if (current(token, projectId)) waiting.value = false }
}

async function copyOriginal() {
  if (!canCopy.value || !native) return
  const projectId = props.projectId; const recoveryId = latest.value!.recovery_id; const token = epoch
  waiting.value = true; error.value = ''; notice.value = ''
  try {
    const original = await native.projectRecoveryOriginal(projectId, recoveryId)
    if (!current(token, projectId) || !props.connected) return
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable')
    await navigator.clipboard.writeText(original.text)
    if (current(token, projectId)) notice.value = t('project.change.originalCopied')
  } catch { if (current(token, projectId)) error.value = t('project.proposal.copyFailed') }
  finally { if (current(token, projectId)) waiting.value = false }
}
</script>

<template>
  <section ref="actionsRef" class="project-change-actions" :aria-busy="waiting">
    <p v-if="!writeAllowed" class="change-note">{{ t('project.change.readOnly') }}</p>
    <p v-if="waiting" class="change-status" role="status">{{ t('project.change.waiting') }}</p>
    <p v-else-if="latest" class="change-status" role="status">{{ t(`project.change.state.${latest.state}`) }}</p>
    <p v-if="unknown" class="change-note">{{ t('project.change.unknownHelp') }}</p>
    <p v-if="latest?.state === 'applied' && !latest.can_revert" class="change-note">{{ t('project.change.conflict') }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="error" class="change-error" role="alert">{{ error }}</p>
    <div class="change-buttons">
      <button v-if="canApply" type="button" data-change-action="apply" class="primary" @click="change('apply')">{{ t('project.change.apply') }}</button>
      <button v-if="canRevert" type="button" data-change-action="revert" @click="change('revert')">{{ t('project.change.revert') }}</button>
      <button v-if="canKeep" type="button" data-change-action="keep" @click="change('keep')">{{ t('project.change.keep') }}</button>
      <button v-if="latest && (latest.operation_id || unknown)" type="button" data-change-action="status" :disabled="waiting || !connected || disabled" @click="status">{{ t('project.change.status') }}</button>
      <button v-if="latest?.recovery_id" type="button" data-change-action="original" :disabled="!canCopy" @click="copyOriginal">{{ t('project.change.copyOriginal') }}</button>
    </div>
    <p v-if="proposalId && !available" class="change-note">{{ t('project.change.unsupported') }}</p>
  </section>
</template>

<style scoped>
.project-change-actions { margin-top: 12px; font-size: 12px; line-height: 1.6; }
p { margin: 5px 0; }
.change-status { font-weight: 600; }
.change-note { color: var(--text-secondary); }
.change-buttons { display: flex; flex-wrap: wrap; gap: 7px; }
button { padding: 6px 9px; border: 1px solid var(--border); border-radius: 5px; color: var(--text); background: var(--surface); font: inherit; cursor: pointer; }
button:hover:enabled { background: var(--surface-hover); }
button.primary { background: var(--text); color: var(--surface); }
button:disabled { opacity: .5; cursor: default; }
.change-error { border-left: 2px solid var(--text); padding-left: 8px; overflow-wrap: anywhere; }
</style>
