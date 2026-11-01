<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { api } from '../api'
import { desktop, type ProjectChangeReceipt } from '../desktop'
import { t } from '../i18n'
import { canProposeProjectFile } from '../project-files'
import type { ReasoningPreference } from '../reasoning'
import type { ProjectEntry, ProjectExcerpt, ProjectInfo, ProjectListing, ProjectSelection } from '../project-files'
import ProjectProposalPanel from './ProjectProposalPanel.vue'
import ProjectRecoveryList from './ProjectRecoveryList.vue'

const props = withDefaults(defineProps<{ modelValue: ProjectSelection | null; writeAllowed?: boolean; disabled?: boolean; connected?: boolean; model?: string; localModel?: string; reasoning?: ReasoningPreference | 'fast' }>(), { connected: true, model: 'auto', reasoning: 'auto', writeAllowed: true })
const emit = defineEmits<{ 'update:modelValue': [value: ProjectSelection | null]; busy: [value: boolean] }>()
const native = desktop
const project = ref<ProjectInfo | null>(null)
const listing = ref<ProjectListing | null>(null)
const preview = ref<ProjectExcerpt | null>(null)
const available = ref(Boolean(native))
const error = ref('')
const statusBusy = ref(false)
const listingBusy = ref(false)
const previewBusy = ref(false)
const picking = ref(false)
const closing = ref(false)
const proposalOpen = ref(false)
const proposalBusy = ref(false)
const recoveryBusy = ref(false)
const changesAvailable = ref(false)
const changesRevision = ref(0)
let refreshPreviewPending = false
const maxFiles = ref(4)
let generation = 0
let listRequest = 0
let previewRequest = 0
let statusRequest = 0
let alive = true
const busy = computed(() => statusBusy.value || listingBusy.value || previewBusy.value || picking.value || closing.value || proposalBusy.value || recoveryBusy.value)
const selected = computed(() => props.modelValue?.id === project.value?.id ? props.modelValue?.files || [] : [])
const crumbs = computed(() => {
  const segments = (listing.value?.path || '').split('/').filter(Boolean)
  return segments.map((name, index) => ({ name, path: segments.slice(0, index + 1).join('/') }))
})
watch(busy, value => emit('busy', value), { flush: 'sync' })

function reset(next: ProjectInfo | null, keepSelection = false) {
  generation++; listRequest++; previewRequest++
  project.value = next; listing.value = null; preview.value = null
  proposalOpen.value = false; proposalBusy.value = false
  recoveryBusy.value = false; changesAvailable.value = false; refreshPreviewPending = false
  listingBusy.value = false; previewBusy.value = false; error.value = ''
  if (!keepSelection) emit('update:modelValue', next ? { id: next.id, files: [] } : null)
}

async function loadDirectory(path = '') {
  if (!project.value || props.disabled || !props.connected) return
  const id = project.value.id; const epoch = generation; const request = ++listRequest
  listingBusy.value = true; error.value = ''; preview.value = null; previewRequest++; previewBusy.value = false; proposalOpen.value = false
  try {
    const result = await api.projectFiles(id, path)
    if (alive && epoch === generation && request === listRequest) listing.value = result
  } catch {
    if (alive && epoch === generation && request === listRequest) error.value = t('project.listFailed')
  } finally {
    if (alive && epoch === generation && request === listRequest) listingBusy.value = false
  }
}

async function refreshStatus() {
  if (!native || !props.connected) return
  const epoch = generation
  const request = ++statusRequest
  statusBusy.value = true; error.value = ''
  try {
    const result = await api.projects()
    if (!alive || epoch !== generation) return
    available.value = result.available
    maxFiles.value = Math.min(4, result.limits?.max_files || 4)
    reset(result.project, Boolean(result.project && props.modelValue?.id === result.project.id))
    changesAvailable.value = result.changes_available === true
    if (result.project) await loadDirectory()
  } catch {
    if (alive && epoch === generation && request === statusRequest) { reset(null); error.value = t('project.loadFailed') }
  } finally { if (alive && request === statusRequest) statusBusy.value = false }
}

async function pick() {
  if (!native || props.disabled || picking.value || closing.value || proposalBusy.value || recoveryBusy.value || !props.connected) return
  picking.value = true; error.value = ''
  const epoch = generation
  try {
    const result = await native.pickProject()
    if (!alive || epoch !== generation || !result.picked) return
    if (!result.project) { error.value = t('project.loadFailed'); return }
    available.value = result.available !== false
    maxFiles.value = Math.min(4, result.limits?.max_files || 4)
    reset(result.project)
    changesAvailable.value = result.changes_available === true
    await loadDirectory()
  } catch {
    if (alive && epoch === generation) error.value = t('project.pickFailed')
  } finally { if (alive) picking.value = false }
}

function toggle(entry: ProjectEntry) {
  if (!project.value || props.disabled || busy.value || entry.kind !== 'file' || entry.readable === false) return
  const files = [...selected.value]
  const index = files.indexOf(entry.path)
  if (index >= 0) files.splice(index, 1)
  else if (files.length < maxFiles.value) files.push(entry.path)
  emit('update:modelValue', { id: project.value.id, files })
}
function clear() {
  if (project.value && !props.disabled && !busy.value) emit('update:modelValue', { id: project.value.id, files: [] })
}
async function read(entry: ProjectEntry) {
  if (!project.value || props.disabled || busy.value || entry.readable === false) return
  const id = project.value.id; const epoch = generation; const request = ++previewRequest
  previewBusy.value = true; preview.value = null; error.value = ''; proposalOpen.value = false
  try {
    const result = await api.projectRead(id, entry.path)
    if (alive && epoch === generation && request === previewRequest) {
      preview.value = result
      const listed = listing.value?.entries.find(item => item.path === result.path)
      if (listed) listed.size_bytes = result.size_bytes
    }
  } catch {
    if (alive && epoch === generation && request === previewRequest) error.value = t('project.readFailed')
  } finally {
    if (alive && epoch === generation && request === previewRequest) previewBusy.value = false
  }
}
async function close() {
  if (!project.value || props.disabled || picking.value || closing.value || proposalBusy.value || recoveryBusy.value) return
  const id = project.value.id
  reset(null); closing.value = true
  const epoch = generation
  try { await api.closeProject(id) }
  catch { if (alive && epoch === generation) error.value = t('project.closeFailed') }
  finally { if (alive) closing.value = false }
}
function fileChanged(receipt: ProjectChangeReceipt) {
  if (receipt.project_id !== project.value?.id) return
  changesRevision.value++
  if (['applied', 'reverted'].includes(receipt.state) && receipt.path === preview.value?.path) refreshPreviewPending = true
}
watch([proposalOpen, busy, () => props.connected, () => props.disabled], () => {
  if (!alive || proposalOpen.value || busy.value || !props.connected || props.disabled || !refreshPreviewPending || !preview.value) return
  const path = preview.value.path; refreshPreviewPending = false
  void read({ path, name: path.split('/').at(-1) || path, kind: 'file', readable: true })
})
watch(() => props.connected, connected => {
  if (connected) void refreshStatus()
  else { statusRequest++; reset(null); statusBusy.value = false; picking.value = false; closing.value = false }
}, { immediate: true })
onUnmounted(() => { alive = false; generation++; emit('busy', false) })
</script>
<template>
  <div class="project-files">
    <details>
      <summary>{{ t('project.title') }}<span v-if="selected.length"> · {{ t('project.selectedCount', { count: selected.length, max: maxFiles }) }}</span><span v-if="busy" role="status"> · {{ t('project.loading') }}</span></summary>
      <div class="project-content">
        <p v-if="!native || !available">{{ t('project.desktopRequired') }}</p>
        <template v-else>
          <div class="project-toolbar">
            <strong v-if="project">{{ project.name }}</strong>
            <button class="project-pick" type="button" :disabled="disabled || picking || closing || statusBusy || proposalBusy || recoveryBusy || !connected" @click="pick">{{ t(project ? 'project.reselect' : 'project.choose') }}</button>
            <button v-if="project" class="project-close" type="button" :disabled="disabled || picking || closing || proposalBusy || recoveryBusy" @click="close">{{ t('project.close') }}</button>
          </div>
          <p class="project-notice">{{ t('project.notice', { max: maxFiles }) }}</p>
          <ProjectRecoveryList :write-allowed="writeAllowed" v-if="project" :key="project.id" :project-id="project.id" :revision="changesRevision" :disabled="disabled || proposalBusy" :connected="connected" @busy="recoveryBusy = $event" @changed="fileChanged" />
          <button v-if="!project && !busy" class="project-refresh" type="button" :disabled="disabled || !connected" @click="refreshStatus">{{ t('project.refresh') }}</button>
          <template v-if="project">
            <nav class="project-breadcrumbs" :aria-label="t('project.breadcrumbs')">
              <button type="button" :disabled="disabled || busy" @click="loadDirectory()">{{ project.name }}</button>
              <template v-for="crumb in crumbs" :key="crumb.path"><span>/</span><button type="button" :disabled="disabled || busy" @click="loadDirectory(crumb.path)">{{ crumb.name }}</button></template>
            </nav>
            <ul class="project-entries" :aria-busy="listingBusy">
              <li v-for="entry in listing?.entries || []" :key="entry.path">
                <button v-if="entry.kind === 'directory'" class="project-directory" type="button" :disabled="disabled || busy" @click="loadDirectory(entry.path)">▸ {{ entry.name }}/</button>
                <template v-else>
                  <input type="checkbox" :aria-label="t('project.selectFile', { path: entry.path })" :checked="selected.includes(entry.path)" :disabled="disabled || busy || entry.readable === false || (!selected.includes(entry.path) && selected.length >= maxFiles)" @change="toggle(entry)" />
                  <button class="project-preview-file" type="button" :disabled="disabled || busy || entry.readable === false" :title="t('project.previewFile', { path: entry.path })" @click="read(entry)">{{ entry.name }}</button>
                  <small v-if="entry.size_bytes !== undefined">{{ entry.size_bytes }} B</small>
                </template>
              </li>
            </ul>
            <p v-if="listing && !listing.entries.length">{{ t('project.empty') }}</p>
            <p v-if="listing?.truncated">{{ t('project.listTruncated') }}</p>
            <div v-if="preview" class="project-preview">
              <strong>{{ preview.path }} · {{ t('project.lines', { start: preview.start_line, end: preview.end_line }) }} · {{ preview.size_bytes }} B</strong>
              <p>{{ t('project.previewOnly') }} <span v-if="preview.truncated">{{ t('project.truncated') }}</span></p>
              <pre tabindex="0">{{ preview.text }}</pre>
              <button class="project-propose" type="button" :disabled="disabled || busy || !connected || !canProposeProjectFile(preview)" @click="proposalOpen = true">{{ t('project.proposal.open') }}</button>
              <p v-if="preview.truncated">{{ t('project.proposal.truncated') }}</p>
              <ProjectProposalPanel :write-allowed="writeAllowed" v-if="project && canProposeProjectFile(preview)" :key="`${project.id}:${preview.path}:${preview.excerpt_sha256}`" v-model="proposalOpen" :project-id="project.id" :path="preview.path" :model="model" :local-model="localModel" :reasoning="reasoning" :changes-available="changesAvailable" :disabled="disabled || recoveryBusy" :connected="connected" @busy="proposalBusy = $event" @changed="fileChanged" />
            </div>
          </template>
        </template>
        <p v-if="error" role="alert">{{ error }}</p>
      </div>
    </details>
    <div v-if="selected.length" class="project-selected">
      <span>{{ t('project.nextQuestion') }}</span><span v-for="path in selected" :key="path" class="project-selected-path">{{ path }}</span>
      <button class="project-clear" type="button" :disabled="disabled || busy" @click="clear">{{ t('project.clear') }}</button>
    </div>
  </div>
</template>

<style scoped>
.project-files { min-width: 0; color: var(--text-secondary, #555); font-size: 12px; border-top: 1px solid var(--border, #ddd); }
summary { padding: 9px 12px; cursor: pointer; user-select: none; overflow-wrap: anywhere; }
.project-content { padding: 0 12px 10px; max-height: min(55dvh, 480px); overflow: auto; }
.project-content p { line-height: 1.6; margin: 7px 0; }
.project-toolbar, .project-breadcrumbs, .project-selected { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }
.project-toolbar strong { margin-right: auto; overflow-wrap: anywhere; }
button { font: inherit; color: inherit; border: 1px solid var(--border, #bbb); border-radius: 5px; background: transparent; padding: 4px 7px; cursor: pointer; }
button:hover:enabled { background: var(--surface-hover, #eee); }
button:disabled, input:disabled { opacity: .45; cursor: default; }
.project-entries { max-height: 190px; overflow: auto; padding: 0; list-style: none; }
.project-entries li { display: flex; gap: 7px; align-items: center; min-width: 0; padding: 3px 0; }
.project-entries input[type='checkbox'] { accent-color: var(--text, #222); }
.project-entries button { border: 0; text-align: left; min-width: 0; overflow-wrap: anywhere; }
.project-entries small { margin-left: auto; white-space: nowrap; }
.project-preview { min-width: 0; }
.project-preview strong { overflow-wrap: anywhere; }
pre { overflow: auto; max-height: 240px; white-space: pre; border: 1px solid var(--border, #ccc); border-radius: 5px; padding: 8px; color: var(--text, #222); background: var(--surface, #fff); }
.project-selected { padding: 0 12px 9px; }
.project-selected-path { overflow-wrap: anywhere; border: 1px solid var(--border, #ccc); border-radius: 4px; padding: 2px 5px; }
[role='alert'] { font-weight: 600; }
@media (max-width: 540px) { .project-entries small { display: none; } .project-toolbar { align-items: flex-start; } .project-selected { gap: 5px; } }
</style>
